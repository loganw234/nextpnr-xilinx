#!/usr/bin/env python3
"""How few nets must cross the chip's middle: a Fiduccia-Mattheyses bisection
of a placed design's netlist, started from the placement's own split.

A placement's cells above and below MIDDLE_ROW are a bisection of the
netlist, and the nets it cuts are the nets that must cross that row
boundary. FM then moves cells between the halves, one at a time, the move
that cuts the fewest nets first, keeping each half's weight within BALANCE
of even, and keeps the best of each pass. What it ends with is an upper
bound on the netlist's minimum bisection: a placement exists that sends no
more nets across the middle than that - if the rest of the chip could hold
each half.

Cells constrained together (a carry chain and the cells tied to it) move as
one vertex: the placed JSON's CONSTR_PARENT attributes name each cell's
parent. A vertex weighs its cell count. Nets of more than MAX_PINS cells are
not moved on (FM's gains for them are not kept) but are counted in the cut;
nets above 2000 cells (clock, resets) are left out, as in
placement_metrics.py.

usage: bisect.py PLACED_JSON [MIDDLE_ROW] [BALANCE] [PASSES]
"""
import re
import sys
import time
from collections import defaultdict

path = sys.argv[1]
middle = float(sys.argv[2]) if len(sys.argv) > 2 else 175
balance = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
passes = int(sys.argv[4]) if len(sys.argv) > 4 else 8
MAX_PINS = 100
FANOUT_GLOBAL = 2000
site_re = re.compile(r'"NEXTPNR_BEL": "([A-Z0-9]+)_X(\d+)Y(\d+)/')
parent_re = re.compile(r'"CONSTR_PARENT": "(.+)"')
key_re = re.compile(r'^        "(.+)": \{$')
int_re = re.compile(r'\b(\d+)\b')
yscale = {"SLICE": 1.0, "RAMB36": 5.0, "RAMB18": 2.5, "DSP48": 2.5}

t0 = time.time()
names, ys, parents, cellbits = [], [], [], []
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
                parent = mp.group(1)
        if '"connections": {' in line:
            in_conn = True; continue
        if in_conn:
            if line.strip().startswith('}'):
                in_conn = False
                if site is not None:
                    names.append(cur)
                    ys.append(site[1] * yscale.get(site[0], 1.0))
                    parents.append(parent)
                    cellbits.append(bits)
                continue
            payload = line.split(':', 1)[1] if ':' in line else line
            bits.extend(int(t) for t in int_re.findall(payload.replace('"0"', '').replace('"1"', '')))

# vertices: each cell's root (follow CONSTR_PARENT to the top)
index = {n: i for i, n in enumerate(names)}
root = list(range(len(names)))
for i, p in enumerate(parents):
    r = i
    seen = 0
    while parents[r] is not None and parents[r] in index and seen < 64:
        r = index[parents[r]]
        seen += 1
    root[i] = r
vid = {}
for r in root:
    if r not in vid:
        vid[r] = len(vid)
V = len(vid)
weight = [0] * V
ysum = [0.0] * V
for i, r in enumerate(root):
    v = vid[r]
    weight[v] += 1
    ysum[v] += ys[i]
side = [1 if ysum[v] / weight[v] >= middle else 0 for v in range(V)]

# nets: distinct vertices per net bit
pins = defaultdict(set)
for i, bs in enumerate(cellbits):
    v = vid[root[i]]
    for b in bs:
        pins[b].add(v)
nets = []
users = defaultdict(int)
for i, bs in enumerate(cellbits):
    for b in set(bs):
        users[b] += 1
for b, vs in pins.items():
    if users[b] > FANOUT_GLOBAL or len(vs) < 2:
        continue
    nets.append(list(vs))
E = len(nets)
vnets = [[] for _ in range(V)]
for e, vs in enumerate(nets):
    if len(vs) <= MAX_PINS:
        for v in vs:
            vnets[v].append(e)
cnt = [[0, 0] for _ in range(E)]
for e, vs in enumerate(nets):
    for v in vs:
        cnt[e][side[v]] += 1


def cut():
    return sum(1 for c in cnt if c[0] and c[1])


W = sum(weight)
lo, hi = (0.5 - balance) * W, (0.5 + balance) * W
w1 = sum(weight[v] for v in range(V) if side[v] == 1)
start_cut = cut()
print(f"{path}: {len(names)} cells as {V} vertices, {E} nets (of 2 to {FANOUT_GLOBAL} cells; "
      f"above {MAX_PINS} counted, not moved on); read in {time.time() - t0:.0f} s")
print(f"the placement's own split at row {middle:.0f}: {start_cut} nets cut, "
      f"top half {100 * w1 / W:.1f}% of the cells")


def gain(v):
    s = side[v]
    g = 0
    for e in vnets[v]:
        c = cnt[e]
        if c[s] == 1:
            g += 1          # v alone on its side: moving it uncuts the net
        if c[1 - s] == 0:
            g -= 1          # the net lies wholly on v's side: moving cuts it
    return g


for p in range(passes):
    t1 = time.time()
    # bucket queue of unlocked vertices by gain
    g = [gain(v) for v in range(V)]
    buckets = defaultdict(set)
    for v in range(V):
        buckets[g[v]].add(v)
    locked = bytearray(V)
    maxg = max(buckets)
    moves = []
    running = best_run = 0
    best_len = 0
    cur_w1 = w1
    while True:
        while maxg > -10**6 and not buckets.get(maxg):
            maxg -= 1
            if maxg < -2 * MAX_PINS:
                maxg = -10**6
        if maxg == -10**6:
            break
        # the best vertex whose move keeps the balance
        chosen = None
        for gg in range(maxg, max(-2 * MAX_PINS, maxg - 40), -1):
            for v in buckets.get(gg, ()):
                nw1 = cur_w1 - weight[v] if side[v] == 1 else cur_w1 + weight[v]
                # within the balance, or nearer it (the placement's own split
                # may start outside it)
                if lo <= nw1 <= hi or abs(nw1 - W / 2) < abs(cur_w1 - W / 2):
                    chosen = v
                    break
            if chosen is not None:
                break
        if chosen is None:
            break
        v = chosen
        buckets[g[v]].discard(v)
        locked[v] = 1
        s = side[v]
        running += g[v]
        # update the nets and the neighbours' gains
        touched = set()
        for e in vnets[v]:
            c = cnt[e]
            c[s] -= 1
            c[1 - s] += 1
            for u in nets[e]:
                if not locked[u]:
                    touched.add(u)
        side[v] = 1 - s
        cur_w1 = cur_w1 - weight[v] if s == 1 else cur_w1 + weight[v]
        for u in touched:
            ng = gain(u)
            if ng != g[u]:
                buckets[g[u]].discard(u)
                g[u] = ng
                buckets[ng].add(u)
                if ng > maxg:
                    maxg = ng
        moves.append(v)
        if running > best_run:
            best_run = running
            best_len = len(moves)
    # undo the moves after the best prefix
    for v in reversed(moves[best_len:]):
        s = side[v]
        for e in vnets[v]:
            c = cnt[e]
            c[s] -= 1
            c[1 - s] += 1
        side[v] = 1 - s
    w1 = sum(weight[v] for v in range(V) if side[v] == 1)
    now = cut()
    print(f"pass {p + 1}: kept {best_len} of {len(moves)} moves, gain {best_run}: {now} nets cut "
          f"({100 * now / start_cut:.0f}% of the placement's), top half {100 * w1 / W:.1f}%; "
          f"{time.time() - t1:.0f} s")
    if best_run <= 0:
        break
