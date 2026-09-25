#!/usr/bin/env python3
"""Which placement quantity stands where the router fails?

Reads a placed nextpnr-xilinx design (the JSON dense/place.sh keeps), the
router's heatmap for one iteration of a route of that placement
(heat_iterN_by_xy.csv: overuse per wire, at the centre of the wire's box,
on the tile grid), and prjxray's tilegrid.json for the part, which gives each
site its tile and each tile its grid position. A slice's wiring is in the
INT tile beside its CLB: grid x + 1 for a CLB*_L tile, x - 1 for CLB*_R.

For each INT tile it counts, from the placement: cells, LUTs, cell pins on
routed nets (2 to FANOUT_GLOBAL users), and RUDY - each net's box wirelength
(width + height, in tiles) spread evenly over its box - also split into its
vertical and horizontal parts. Then, with heat and quantity both summed over
square windows, it prints for each quantity the rank correlation with the
heat, and the share of all the heat standing in the windows the quantity
ranks in its top 5% (5% would be chance). Given the heatmap of another
placement's route, the heat-weighted demand line says how much of this
placement's vertical demand stands where that route failed.

usage: heat_vs_placement.py TILEGRID_JSON PLACED_JSON HEAT_BY_XY_CSV [WINDOW...]
"""
import csv
import json
import re
import sys
from collections import Counter

import numpy as np

tilegrid, placed, heatfile = sys.argv[1:4]
windows = [int(w) for w in sys.argv[4:]] or [1, 5, 11]
FANOUT_GLOBAL = 2000

g = json.load(open(tilegrid))
site_int = {}                       # site name -> (x, y) of its INT tile
for name, t in g.items():
    ty = t["type"]
    if ty.endswith("_L"):
        dx = 1
    elif ty.endswith("_R"):
        dx = -1
    else:
        continue
    for s in t.get("sites", {}):
        site_int[s] = (t["grid_x"] + dx, t["grid_y"])
del g

heat = np.array([[int(v) for v in r if v != ''] for r in csv.reader(open(heatfile))], dtype=float)
GY, GX = heat.shape

site_re = re.compile(r'"NEXTPNR_BEL": "([A-Z0-9_]+_X\d+Y\d+)/([A-Z0-9_]+)"')
key_re = re.compile(r'^        "(.+)": \{$')
int_re = re.compile(r'\b(\d+)\b')
cells = []                          # (x, y, is_lut, bits)
unmapped = Counter()
section = site = None
bits = []
in_conn = False
with open(placed) as f:
    for line in f:
        if line.startswith('      "cells": {'):
            section = "cells"; continue
        if line.startswith('      "netnames": {'):
            break
        if section != "cells":
            continue
        if key_re.match(line):
            site = None; bits = []; in_conn = False; continue
        if site is None:
            m = site_re.search(line)
            if m:
                site = (m.group(1), m.group(2))
        if '"connections": {' in line:
            in_conn = True; continue
        if in_conn:
            if line.strip().startswith('}'):
                in_conn = False
                if site is not None:
                    xy = site_int.get(site[0])
                    if xy is None:
                        unmapped[site[0].split('_X')[0]] += 1
                    else:
                        cells.append((xy[0], xy[1], site[1].endswith("LUT"), bits))
                continue
            payload = line.split(':', 1)[1] if ':' in line else line
            bits.extend(int(t) for t in int_re.findall(payload.replace('"0"', '').replace('"1"', '')))

users = Counter()
for (_, _, _, bs) in cells:
    for b in set(bs):
        users[b] += 1

ncell = np.zeros((GY, GX)); nlut = np.zeros((GY, GX)); npin = np.zeros((GY, GX))
box = {}
for (x, y, is_lut, bs) in cells:
    ncell[y, x] += 1
    if is_lut:
        nlut[y, x] += 1
    for b in set(bs):
        if 2 <= users[b] <= FANOUT_GLOBAL:
            npin[y, x] += 1
            x0, x1, y0, y1 = box.get(b, (x, x, y, y))
            box[b] = (min(x0, x), max(x1, x), min(y0, y), max(y1, y))

# RUDY by 2D difference arrays: a net adds (w + h) / (w * h) to each tile of
# its box, w and h counted in tiles; the vertical part is h / (w * h) = 1 / w.
d_all = np.zeros((GY + 1, GX + 1)); d_v = np.zeros((GY + 1, GX + 1)); d_h = np.zeros((GY + 1, GX + 1))
for (x0, x1, y0, y1) in box.values():
    w, h = x1 - x0 + 1, y1 - y0 + 1
    for d, v in ((d_all, (w + h) / (w * h)), (d_v, 1.0 / w if h > 1 else 0.0), (d_h, 1.0 / h if w > 1 else 0.0)):
        if v:
            d[y0, x0] += v; d[y0, x1 + 1] -= v; d[y1 + 1, x0] -= v; d[y1 + 1, x1 + 1] += v
rudy = d_all.cumsum(0).cumsum(1)[:GY, :GX]
rudy_v = d_v.cumsum(0).cumsum(1)[:GY, :GX]
rudy_h = d_h.cumsum(0).cumsum(1)[:GY, :GX]


def boxsum(m, k):
    if k == 1:
        return m
    c = np.pad(m, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    r = k // 2
    ys = np.arange(GY); xs = np.arange(GX)
    y0 = np.clip(ys - r, 0, GY); y1 = np.clip(ys + r + 1, 0, GY)
    x0 = np.clip(xs - r, 0, GX); x1 = np.clip(xs + r + 1, 0, GX)
    return c[y1][:, x1] - c[y0][:, x1] - c[y1][:, x0] + c[y0][:, x0]


def ranks(a):
    o = a.argsort(kind="stable"); r = np.empty(len(a)); r[o] = np.arange(len(a))
    return r


# only tiles that have wiring for cells: INT tiles beside at least one site
mask = np.zeros((GY, GX), dtype=bool)
for (x, y) in site_int.values():
    if 0 <= y < GY and 0 <= x < GX:
        mask[y, x] = True
print(f"{placed}\n{heatfile}: heat total {heat.sum():,.0f}, {int((heat > 0).sum()):,} tiles; "
      f"{len(cells):,} cells placed, {sum(unmapped.values())} on sites without an INT neighbour "
      f"({', '.join(f'{k} {v}' for k, v in unmapped.most_common(4))}); {len(box):,} nets")
print(f"heat outside the INT tiles beside sites: {heat[~mask].sum():,.0f}")
rv = rudy_v[mask]; hv = heat[mask]
pct = ranks(rv) / len(rv) * 100
order = np.argsort(pct); cum = np.cumsum(hv[order]) / hv.sum()
q = lambda f: pct[order][min(len(order) - 1, np.searchsorted(cum, f))]
print(f"the heat by its tile's rudy_v percentile: a quarter below {q(.25):.0f}, half below {q(.5):.0f}, "
      f"three quarters below {q(.75):.0f}; {hv[pct >= 90].sum() / hv.sum():.0%} of it in the top 10%")
hb = boxsum(heat, 7)[mask]
print(f"rudy_v where the heat is (each tile weighted by the heat summed over 7x7 tiles): "
      f"{(rv * hb).sum() / hb.sum():.1f}; over all these tiles {rv.mean():.1f}, their 99th percentile "
      f"{np.percentile(rv, 99):.1f} - with another placement's heatmap, what this placement puts where that one failed")
qs = [("pins", npin), ("cells", ncell), ("LUTs", nlut), ("rudy", rudy), ("rudy_v", rudy_v), ("rudy_h", rudy_h)]
for k in windows:
    hk = boxsum(heat, k)[mask]
    tot = hk.sum()
    rh = ranks(hk)
    out = []
    for name, m in qs:
        mk = boxsum(m, k)[mask]
        rho = np.corrcoef(rh, ranks(mk))[0, 1]
        top = mk >= np.percentile(mk, 95)
        out.append(f"{name} {rho:+.2f} / {hk[top].sum() / tot:.0%}")
    print(f"window {k:2d}x{k:<2d}  rank correlation / heat in its top 5%:  " + ";  ".join(out))
