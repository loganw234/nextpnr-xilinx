#!/usr/bin/env python3
"""Group a high-fanout net's sinks by where a placement put them, for
NEXTPNR_REPLICATE (xilinx/pack.cc): the net's driver is copied once per
group and each group's sinks move to their own copy, as Vivado's fanout
optimisation replicates the driver of a high-fanout net.

Reads prjxray's tilegrid.json (each site's tile position on the grid) and
a placed design nextpnr wrote (dense/place.sh's placed.json, streamed: it is
350 MB). The net's sink pins are clustered by the grid position of their
cells into K groups (k-means, deterministic: the first centres spread over
the sinks by a fixed-seed k-means++, then iterated until no sink changes
group). Writes

    replicate <net name> <K>
    <group> <cell name> <port>        one line a sink pin, groups 0..K-1

with a comment header naming the input. Group 0 stays on the original
driver. The cell and port names are the packed design's, which is what the
pass meets: it runs at the end of packing.

usage: replicate_groups.py TILEGRID_JSON PLACED_JSON NET K OUT_FILE
"""
import json
import random
import re
import sys

tilegrid, placed, net, K, out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
if K < 2:
    sys.exit("K must be at least 2")

site_xy = {}
for t in json.load(open(tilegrid)).values():
    for s in t.get("sites", {}):
        site_xy[s] = (t["grid_x"], t["grid_y"])

key_re = re.compile(r'^        "(.+)": \{$')
bel_re = re.compile(r'"NEXTPNR_BEL": "([A-Za-z0-9_]+)/')
conn_re = re.compile(r'^            "([A-Za-z0-9_\[\]]+)": \[ (.*) \]')
dir_re = re.compile(r'^            "([A-Za-z0-9_\[\]]+)": "(input|output|inout)"')

# pass 1: the net's bit, from the netnames at the end of the module
bit = None
with open(placed) as f:
    section = None
    for line in f:
        if line.startswith('      "netnames": {'):
            section = "nets"; continue
        if section != "nets":
            continue
        m = key_re.match(line)
        if m and m.group(1) == net:
            nxt = next(f)
            while '"bits"' not in nxt:
                nxt = next(f)
            bit = int(re.search(r'\[ *(\d+)', nxt).group(1))
            break
if bit is None:
    sys.exit(f"net {net!r} not found in {placed}")

# pass 2: every cell pin on that bit
sinks, driver = [], None
with open(placed) as f:
    section = sub = None
    cur = site = None
    dirs, conns = {}, {}

    def finish():
        global driver
        if cur is None:
            return
        for p, bs in conns.items():
            if bit in bs:
                xy = site_xy.get(site) if site else None
                if dirs.get(p) == "output":
                    driver = (cur, p, xy)
                elif dirs.get(p) == "input":
                    sinks.append((cur, p, xy))

    for line in f:
        if line.startswith('      "cells": {'):
            section = "cells"; continue
        if line.startswith('      "netnames": {'):
            finish(); break
        if section != "cells":
            continue
        m = key_re.match(line)
        if m:
            finish()
            cur, site, dirs, conns, sub = m.group(1), None, {}, {}, None
            continue
        if site is None:
            mb = bel_re.search(line)
            if mb:
                site = mb.group(1)
        if '"port_directions": {' in line:
            sub = "dir"; continue
        if '"connections": {' in line:
            sub = "conn"; continue
        if sub == "dir":
            md = dir_re.match(line)
            if md:
                dirs[md.group(1)] = md.group(2)
            elif line.strip().startswith('}'):
                sub = None
        elif sub == "conn":
            mc = conn_re.match(line)
            if mc:
                conns[mc.group(1)] = [int(t) for t in mc.group(2).split(',') if t.strip().isdigit()]
            elif line.strip().startswith('}'):
                sub = None

placed_sinks = [s for s in sinks if s[2] is not None]
if len(placed_sinks) < K:
    sys.exit(f"{net}: {len(placed_sinks)} placed sinks, fewer than K={K}")
pts = [s[2] for s in placed_sinks]

# k-means++ from a fixed seed, then Lloyd iterations until stable
import numpy as np
P = np.array(pts, dtype=float)
rng = random.Random(1)
cent = [P[rng.randrange(len(P))]]
while len(cent) < K:
    d2 = np.min(np.stack([((P - c) ** 2).sum(1) for c in cent]), axis=0)
    r = rng.random() * d2.sum()
    cent.append(P[int(np.searchsorted(np.cumsum(d2), r))])
C = np.array(cent)
assign = np.full(len(P), -1)
for it in range(100):
    d = ((P[:, None, :] - C[None, :, :]) ** 2).sum(2)
    new_assign = d.argmin(1)            # ties go to the lower group
    changed = int((new_assign != assign).sum())
    assign = new_assign
    for k in range(K):
        m = assign == k
        if m.any():
            C[k] = P[m].mean(0)
    if changed == 0:
        break
cent = [tuple(c) for c in C]
assign = assign.tolist()
# group 0 stays on the original driver: the cluster nearest it
if driver and driver[2]:
    dx, dy = driver[2]
    near = min(range(K), key=lambda k: ((cent[k][0] - dx) ** 2 + (cent[k][1] - dy) ** 2, k))
    order = [near] + [k for k in range(K) if k != near]
else:
    order = list(range(K))
rename = {old: new for new, old in enumerate(order)}
sizes = [0] * K
lines = []
for (cell, port, _), a in zip(placed_sinks, assign):
    g = rename[a]
    sizes[g] += 1
    lines.append((g, cell, port))
unplaced = len(sinks) - len(placed_sinks)
with open(out, "w") as o:
    o.write(f"# dense/replicate_groups.py: the sinks of {net} in {placed},\n")
    o.write(f"# {len(placed_sinks)} placed sink pins in {K} groups by k-means on their tiles "
            f"({it + 1} iterations); {unplaced} sinks without a placed site left out\n")
    o.write(f"replicate {net} {K}\n")
    for g, cell, port in sorted(lines):
        o.write(f"{g} {cell} {port}\n")
print(f"{net}: driver {driver[0] if driver else '?'} at {driver[2] if driver else '?'}; "
      f"{len(sinks)} sink pins, {unplaced} unplaced; {K} groups of {min(sizes)} to {max(sizes)}; "
      f"k-means {it + 1} iterations")
for k in range(K):
    c = cent[order[k]]
    print(f"  group {k}: {sizes[k]} sinks about ({c[0]:.0f}, {c[1]:.0f})")
