#!/usr/bin/env python3
"""Where two routes' overuse differs: two router2 heatmaps side by side
(router2/heatmap's heat_iterN_by_xy.csv and _by_type.csv), by row band, by
twelfth of the grid's width and by wire type.

usage: heatcmp.py RUN_A RUN_B ITER [ITER_B]
Rows are printed as 25-slice-row bands counted from slice row 0 (grid row
363, the grid counts downward; an HCLK row falls every 25 slice rows, so
each band is 26 grid rows), to line up with placement_metrics.py.
"""
import csv, sys, os, collections

def xy(run, it):
    p = os.path.join(run, f"heat_iter{it}_by_xy.csv")
    rows = [list(map(int, r[:-1] if r and r[-1] == '' else r)) for r in csv.reader(open(p))]
    return rows

def types(run, it):
    p = os.path.join(run, f"heat_iter{it}_by_type.csv")
    return {r['type']: int(r['overuse']) for r in csv.DictReader(open(p))}

a, b = sys.argv[1], sys.argv[2]
ia = int(sys.argv[3]); ib = int(sys.argv[4]) if len(sys.argv) > 4 else ia
A, B = xy(a, ia), xy(b, ib)
H = max(len(A), len(B)); W = max(max(map(len, A)), max(map(len, B)))
def band(y):
    return max(0, min(13, (363 - y) // 26))
def agg(R):
    rb = collections.Counter(); cb = collections.Counter(); tiles = []
    for y, r in enumerate(R):
        for x, v in enumerate(r):
            rb[band(y)] += v; cb[x * 12 // W] += v
            if v: tiles.append(v)
    return rb, cb, sorted(tiles, reverse=True)
ra, ca, ta = agg(A); rb, cb, tb = agg(B)
na, nb = os.path.basename(a.rstrip('/')), os.path.basename(b.rstrip('/'))
print(f"A = {na} iter {ia}: total {sum(ta):,}")
print(f"B = {nb} iter {ib}: total {sum(tb):,}")
print("by 25-slice-row band from slice row 0 (bottom):  band  A  B  B-A")
for k in range(14):
    print(f"  {k:2d}  {ra[k]:8,}  {rb[k]:8,}  {rb[k]-ra[k]:+8,}")
print(f"by twelfth of the grid width ({W} columns), left to right:  A  B  B-A")
for k in range(12):
    print(f"  {k:2d}  {ca[k]:8,}  {cb[k]:8,}  {cb[k]-ca[k]:+8,}")
def conc(t):
    s = sum(t) or 1
    n = len(t)
    top = lambda f: sum(t[:max(1, int(n * f))]) / s
    return f"{n:,} tiles; top 1% hold {top(0.01):.0%}, top 10% {top(0.1):.0%}; max {t[0] if t else 0}"
print("A:", conc(ta)); print("B:", conc(tb))
TA, TB = types(a, ia), types(b, ib)
print("by wire type (overuse):  A  B  B-A")
for k in sorted(set(TA) | set(TB), key=lambda k: -(TA.get(k, 0) + TB.get(k, 0)))[:12]:
    print(f"  {k:14s} {TA.get(k,0):8,}  {TB.get(k,0):8,}  {TB.get(k,0)-TA.get(k,0):+8,}")
