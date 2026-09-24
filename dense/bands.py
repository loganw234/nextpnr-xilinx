#!/usr/bin/env python3
"""Horizontal bands by recursive min-cut bisection: which rows of the chip each
cell of a placed design should live in, so that few nets cross each band
boundary.

The vertical wiring across the middle rows is what runs out on cft-fp256's
tile (dense/LEDGER.md, 2026-09-24). A placement's cells above and below a row
are a bisection of the netlist; Fiduccia-Mattheyses from that split halves
the nets that must cross the middle (bisect.py). This does it recursively:
the chip's rows are split in two, the cells of each half split again, and so
on to 2^LEVELS bands of equal height. At each split:

  - the start is the placement's own split at the middle row of the region;
  - FM moves cells, the move that cuts the fewest nets first, keeping each
    side's cell count within BALANCE of its share and its block RAMs within
    90% of the RAM sites its rows hold;
  - pins outside the region count on the side they lie (terminal
    propagation): a net to a cell in a band above pulls towards the top.

Cells constrained together (a carry chain and what is tied to it, named by
the placed JSON's CONSTR_PARENT) move as one. Cells on sites other than
slices, RAMs and DSPs (I/O, clock buffers) stay where the placement put them.

Writes BANDS_FILE: a header, then "<band> <cell name>" per cell, band 0 the
bottom. dense/bands.cc-side: NEXTPNR_DENSE_BANDS=BANDS_FILE confines each
named cell to its band's rows (placer_heap.cc).

usage: bands.py PLACED_JSON BANDS_FILE [LEVELS] [BALANCE] [PASSES]
"""
import json
import re
import sys
import time
from collections import defaultdict

path, out = sys.argv[1], sys.argv[2]
levels = int(sys.argv[3]) if len(sys.argv) > 3 else 2
balance = float(sys.argv[4]) if len(sys.argv) > 4 else 0.02
passes = int(sys.argv[5]) if len(sys.argv) > 5 else 8
ROWS = 350                 # slice rows of the XC7K325T
RAM_PER_ROW = 445 / ROWS   # RAMB36 sites per slice row (a RAMB18 is half of one)
MAX_PINS = 100
FANOUT_GLOBAL = 2000
site_re = re.compile(r'"NEXTPNR_BEL": "([A-Z0-9]+)_X(\d+)Y(\d+)/')
parent_re = re.compile(r'"CONSTR_PARENT": "(.+)"')
key_re = re.compile(r'^        "(.+)": \{$')
int_re = re.compile(r'\b(\d+)\b')
yscale = {"SLICE": 1.0, "RAMB36": 5.0, "RAMB18": 2.5, "DSP48": 2.5}

t0 = time.time()
names, ys, kinds, parents, cellbits = [], [], [], [], []
section = cur = site = parent = None
bits = []
in_conn = False
with open(path) as f:
    for line in f:
        if line.startswith('      "cells": {'):
            section = "cells"; continue
        if line.startswith('      "netnames": {'):
            break
        if section != "cells":
            continue
        if line.startswith('      },') or line.startswith('      }\n'):
            section = None; continue
        m = key_re.match(line)
        if m:
            cur = m.group(1); site = None; parent = None; bits = []; in_conn = False; continue
        if site is None:
            ms = site_re.search(line)
            if ms:
                site = (ms.group(1), int(ms.group(3)))
        if parent is None:
            mp = parent_re.search(line)
            if mp:
                parent = json.loads('"' + mp.group(1) + '"')
        if '"connections": {' in line:
            in_conn = True; continue
        if in_conn:
            if line.strip().startswith('}'):
                in_conn = False
                if site is not None:
                    # the JSON's own escaping undone: a name holding a backslash
                    # ("$flatten\u_krnl...") is written with two (until 2026-09-24
                    # 715 such names reached the band file unmatched)
                    names.append(json.loads('"' + cur + '"'))
                    ys.append(site[1] * yscale.get(site[0], 1.0))
                    kinds.append(site[0])
                    parents.append(parent)
                    cellbits.append(bits)
                continue
            payload = line.split(':', 1)[1] if ':' in line else line
            bits.extend(int(t) for t in int_re.findall(payload.replace('"0"', '').replace('"1"', '')))

index = {n: i for i, n in enumerate(names)}
root = list(range(len(names)))
for i in range(len(names)):
    r, seen = i, 0
    while parents[r] is not None and parents[r] in index and seen < 64:
        r = index[parents[r]]
        seen += 1
    root[i] = r
vid = {}
for r in root:
    vid.setdefault(r, len(vid))
V = len(vid)
weight = [0] * V
ram = [0.0] * V           # RAMB36 equivalents
fixed = [False] * V
ysum = [0.0] * V
for i, r in enumerate(root):
    v = vid[r]
    weight[v] += 1
    ysum[v] += ys[i]
    if kinds[i] == "RAMB36":
        ram[v] += 1.0
    elif kinds[i] == "RAMB18":
        ram[v] += 0.5
    elif kinds[i] not in yscale:
        fixed[v] = True
vy = [ysum[v] / weight[v] for v in range(V)]

users = defaultdict(int)
pins = defaultdict(set)
for i, bs in enumerate(cellbits):
    v = vid[root[i]]
    for b in set(bs):
        users[b] += 1
        pins[b].add(v)
nets = [list(vs) for b, vs in pins.items() if users[b] <= FANOUT_GLOBAL and len(vs) >= 2]
vnets = [[] for _ in range(V)]
for e, vs in enumerate(nets):
    for v in vs:
        vnets[v].append(e)
print(f"{path}: {len(names)} cells as {V} vertices, {len(nets)} nets; read in {time.time() - t0:.0f} s")

band_lo = [0.0] * V       # the rows each vertex may lie in, narrowed level by level
band_hi = [float(ROWS)] * V


def split(members, r0, r1):
    """FM bisection of MEMBERS (the vertices of rows r0..r1) at the middle row.

    FM from one start finds one local optimum, and on this netlist the start
    decides a lot (the placement's split at the middle row: 14,215 -> 7,524;
    at the weighted median: 14,552 -> 12,654). So it starts several times - at
    the middle row, and at the placement order's 47%, 50% and 53% weights -
    and keeps the least cut that ends within BALANCE of even."""
    mid = (r0 + r1) / 2
    mem = set(members)
    W = sum(weight[v] for v in members)
    lo, hi = (0.5 - balance) * W, (0.5 + balance) * W
    ram_cap = 0.9 * RAM_PER_ROW * (mid - r0)       # each half holds half the rows
    ram_all = sum(ram[v] for v in members)
    enets = {}
    for v in members:
        for e in vnets[v]:
            enets.setdefault(e, None)
    live = {e for e in enets if len(nets[e]) <= MAX_PINS}
    outside = {}
    for e in enets:
        c = [0, 0]
        for u in nets[e]:
            if u in mem:
                continue
            if band_hi[u] <= mid:
                c[0] += 1
            elif band_lo[u] >= mid:
                c[1] += 1
            else:
                c[1 if vy[u] >= mid else 0] += 1
        outside[e] = c
    order = sorted(members, key=lambda u: vy[u])

    def start_at(frac):
        s, acc = {}, 0
        for v in order:
            s[v] = 0 if acc < frac * W else 1
            acc += weight[v]
        return s

    starts = [("the middle row", {v: (1 if vy[v] >= mid else 0) for v in members})]
    starts += [(f"{int(100 * f)}% of the weight", start_at(f)) for f in (0.47, 0.50, 0.53)]

    def fm(side):
        for v in members:
            if fixed[v]:
                side[v] = 1 if vy[v] >= mid else 0
        cnt = {}
        for e in enets:
            c = list(outside[e])
            for u in nets[e]:
                if u in mem:
                    c[side[u]] += 1
            cnt[e] = c

        def cut():
            return sum(1 for c in cnt.values() if c[0] and c[1])

        def gain(v):
            s = side[v]
            g = 0
            for e in vnets[v]:
                if e not in live:
                    continue
                c = cnt[e]
                if c[s] == 1:
                    g += 1
                if c[1 - s] == 0:
                    g -= 1
            return g

        w1 = sum(weight[v] for v in members if side[v] == 1)
        ram1 = sum(ram[v] for v in members if side[v] == 1)
        first = cut()
        for p in range(passes):
            g = {v: gain(v) for v in members if not fixed[v]}
            buckets = defaultdict(set)
            for v, gv in g.items():
                buckets[gv].add(v)
            locked = set()
            maxg = max(buckets) if buckets else -10**6
            moves, running, best_run, best_len = [], 0, 0, 0
            cw1, cram1 = w1, ram1
            while True:
                while maxg > -10**6 and not buckets.get(maxg):
                    maxg -= 1
                    if maxg < -2 * MAX_PINS:
                        maxg = -10**6
                if maxg == -10**6:
                    break
                chosen = None
                for gg in range(maxg, max(-2 * MAX_PINS, maxg - 40), -1):
                    for v in buckets.get(gg, ()):
                        to_top = side[v] == 0
                        nw1 = cw1 + weight[v] if to_top else cw1 - weight[v]
                        nram1 = cram1 + ram[v] if to_top else cram1 - ram[v]
                        if not (lo <= nw1 <= hi or abs(nw1 - W / 2) < abs(cw1 - W / 2)):
                            continue
                        if ram[v] and (nram1 > ram_cap or ram_all - nram1 > ram_cap):
                            continue
                        chosen = v
                        break
                    if chosen is not None:
                        break
                if chosen is None:
                    break
                v = chosen
                buckets[g[v]].discard(v)
                locked.add(v)
                s = side[v]
                running += g[v]
                touched = set()
                for e in vnets[v]:
                    c = cnt[e]
                    c[s] -= 1
                    c[1 - s] += 1
                    if e in live:
                        for u in nets[e]:
                            if u in g and u not in locked:
                                touched.add(u)
                side[v] = 1 - s
                cw1 = cw1 + weight[v] if s == 0 else cw1 - weight[v]
                cram1 = cram1 + ram[v] if s == 0 else cram1 - ram[v]
                for u in touched:
                    ng = gain(u)
                    if ng != g[u]:
                        buckets[g[u]].discard(u)
                        g[u] = ng
                        buckets[ng].add(u)
                        maxg = max(maxg, ng)
                moves.append(v)
                if running > best_run:
                    best_run, best_len = running, len(moves)
            for v in reversed(moves[best_len:]):
                s = side[v]
                for e in vnets[v]:
                    c = cnt[e]
                    c[s] -= 1
                    c[1 - s] += 1
                side[v] = 1 - s
            w1 = sum(weight[v] for v in members if side[v] == 1)
            ram1 = sum(ram[v] for v in members if side[v] == 1)
            if best_run <= 0:
                break
        return side, first, cut(), w1, ram1

    best = None
    for label, s0 in starts:
        side, first, last, w1, ram1 = fm(dict(s0))
        ok = lo <= w1 <= hi
        print(f"    from {label}: cut {first} -> {last}, top {100 * w1 / W:.1f}%{'' if ok else ' (unbalanced: not kept)'}")
        if ok and (best is None or last < best[2]):
            best = (side, first, last, w1, ram1)
    if best is None:
        raise SystemExit(f"rows {r0}-{r1}: no start ended within the balance")
    side, first, end, w1, ram1 = best
    print(f"  rows {r0:5.1f}-{r1:5.1f} at {mid:5.1f}: {len(members)} vertices, kept cut {end}, "
          f"top {100 * w1 / W:.1f}% of the cells, RAMs {ram_all - ram1:.1f} / {ram1:.1f} of {ram_cap:.0f} a side")
    top = [v for v in members if side[v] == 1]
    bottom = [v for v in members if side[v] == 0]
    for v in top:
        band_lo[v] = mid
    for v in bottom:
        band_hi[v] = mid
    return bottom, top


regions = [(list(range(V)), 0.0, float(ROWS))]
for lvl in range(levels):
    print(f"level {lvl + 1}:")
    nxt = []
    for members, r0, r1 in regions:
        b, t = split(members, r0, r1)
        mid = (r0 + r1) / 2
        nxt += [(b, r0, mid), (t, mid, r1)]
    regions = nxt

K = 2 ** levels
band_of_v = [0] * V
for k, (members, r0, r1) in enumerate(regions):
    for v in members:
        band_of_v[v] = k
with open(out, "w") as f:
    f.write(f"# dense bands: {K} bands of the {ROWS} slice rows, band 0 the bottom; "
            f"recursive FM bisection of {path}, balance {balance}, {passes} passes a split\n")
    f.write(f"bands {K} rows {ROWS}\n")
    for i, n in enumerate(names):
        f.write(f"{band_of_v[vid[root[i]]]} {n}\n")
print(f"{out}: {len(names)} cells in {K} bands; {time.time() - t0:.0f} s in all")
