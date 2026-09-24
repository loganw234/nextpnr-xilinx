#!/usr/bin/env python3
"""What the router will face, read from a placed nextpnr-xilinx design.

One pass over the placed JSON, line by line (nextpnr writes it pretty-printed;
json.load of the 350 MB bench placement would cost gigabytes). Each cell's
site comes from its NEXTPNR_BEL attribute; site rows are SLICE Y as is,
RAMB36 Y x5, RAMB18 and DSP48 Y x2.5 (those tiles span five CLB rows); site
columns are SLICE X (other site types number their columns apart, so a net's
x extent comes from its slices).

Printed, with the headline lines that dense/place.sh's summary collects:
  crossings  nets that must cross each row boundary (vertical demand) and
             each column boundary (horizontal demand), from the nets' boxes;
             nets above FANOUT_GLOBAL cells (clock, resets) are left out
  density    LUTs per used slice in each 25-row band
  smear      for each block, the rows holding the middle 80% of its cells
  the blocks crossing the middle row, by the pair at the ends of each net

Blocks: most cells carry names ABC generated, while most nets keep the RTL's
hierarchical names, so a cell belongs to the block its connected nets name
most often (FANOUT_GLOBAL nets and generated names do not vote).

On 2026-09-24 the bench's frozen placement gave 14,120 nets across row 175
and the lanes' cells spread over most of the chip's height (dense/LEDGER.md).

usage: placement_metrics.py PLACED_JSON [DEPTH] [MIDDLE_ROW]
"""
import re
import sys
from collections import Counter, defaultdict

path = sys.argv[1]
depth = int(sys.argv[2]) if len(sys.argv) > 2 else 3
middle = float(sys.argv[3]) if len(sys.argv) > 3 else 175
FANOUT_GLOBAL = 2000
BAND = 25
site_re = re.compile(r'"NEXTPNR_BEL": "([A-Z0-9]+)_X(\d+)Y(\d+)/([A-Z0-9_]+)"')
key_re = re.compile(r'^        "(.+)": \{$')
int_re = re.compile(r'\b(\d+)\b')
yscale = {"SLICE": 1.0, "RAMB36": 5.0, "RAMB18": 2.5, "DSP48": 2.5}


def block_of(name):
    """u_krnl.u_lanes.g_bank32.g_lane32[3].u_fma.s0[7] -> u_lanes.g_bank32.g_lane32[3]:
    an instance keeps its index; a signal's bit index is dropped when the
    signal itself is within DEPTH (u_krnl.u_lanes.a[46] -> u_lanes.a[])."""
    if not name.startswith("u_krnl."):
        return None
    parts = name.split(".")[1:]
    head = parts[:depth]
    if len(parts) <= depth:
        head[-1] = re.sub(r'\[\d+\]$', '[]', head[-1])
    return ".".join(head)


cells = []          # (x, y, is_slice, bits)
slice_luts = Counter()
slices_used = set()
net_block = {}
section = cur = site = None
bits = []
in_conn = in_bits = False
with open(path) as f:
    for line in f:
        if line.startswith('      "cells": {'):
            section = "cells"; continue
        if line.startswith('      "netnames": {'):
            section = "nets"; continue
        if line.startswith('      },') or line.startswith('      }\n'):
            section = None; continue
        if section == "cells":
            m = key_re.match(line)
            if m:
                cur = m.group(1); site = None; bits = []; in_conn = False; continue
            if site is None:
                ms = site_re.search(line)
                if ms:
                    site = (ms.group(1), int(ms.group(2)), int(ms.group(3)), ms.group(4))
                    if site[0] == "SLICE":
                        slices_used.add((site[1], site[2]))
                        if site[3].endswith("LUT"):
                            slice_luts[(site[1], site[2])] += 1
            if '"connections": {' in line:
                in_conn = True; continue
            if in_conn:
                if line.strip().startswith('}'):
                    in_conn = False
                    if site is not None and site[0] in yscale:
                        cells.append((site[1], site[2] * yscale[site[0]], site[0] == "SLICE", bits))
                    continue
                payload = line.split(':', 1)[1] if ':' in line else line
                bits.extend(int(t) for t in int_re.findall(payload.replace('"0"', '').replace('"1"', '')))
        elif section == "nets":
            m = key_re.match(line)
            if m:
                cur = m.group(1); in_bits = False; continue
            if '"bits": [' in line or in_bits:
                blk = block_of(cur) if cur else None
                payload = line.split('[', 1)[1] if '"bits": [' in line else line
                for t in int_re.findall(payload.replace('"0"', '').replace('"1"', '')):
                    b = int(t)
                    if blk is not None and b not in net_block:
                        net_block[b] = blk
                in_bits = ']' not in line

users = Counter()
for (_, _, _, bs) in cells:
    for b in set(bs):
        users[b] += 1

# --- crossings -------------------------------------------------------------
net_y = {}
net_x = {}
for (x, y, sl, bs) in cells:
    for b in set(bs):
        if users[b] < 2 or users[b] > FANOUT_GLOBAL:
            continue
        lo, hi = net_y.get(b, (y, y))
        net_y[b] = (min(lo, y), max(hi, y))
        if sl:
            lo, hi = net_x.get(b, (x, x))
            net_x[b] = (min(lo, x), max(hi, x))
rows = Counter()
cols = Counter()
for (y0, y1) in net_y.values():
    for y in range(int(y0), int(y1)):
        rows[y] += 1
for (x0, x1) in net_x.values():
    for x in range(x0, x1):
        cols[x] += 1
row_bands = [sum(rows[y] for y in range(b, b + BAND)) / BAND for b in range(0, 350, BAND)]
col_bands = [sum(cols[x] for x in range(b, b + 12)) / 12 for b in range(0, 156, 12)]
spans = sorted(y1 - y0 for (y0, y1) in net_y.values() if y0 < middle <= y1)
print(f"{path}")
print(f"crossings  row {middle:.0f}: {len(spans)} nets (median span {spans[len(spans) // 2]:.0f} rows, "
      f"{100 * sum(1 for s in spans if s > 100) / len(spans):.0f}% over 100); "
      f"row bands' mean peak {max(row_bands):.0f}, column bands' {max(col_bands):.0f}; "
      f"{len(net_y)} nets counted")
print(f"  nets across each row boundary, mean per {BAND}-row band from row 0:")
print("   " + " ".join(f"{v:6.0f}" for v in row_bands))
print("  nets across each column boundary, mean per 12-column band from column 0:")
print("   " + " ".join(f"{v:6.0f}" for v in col_bands))

# --- rudy: where the vertical and horizontal demand lands -------------------
# A row total is not enough: on 2026-09-24 the block-pull placement had 11%
# fewer nets across its peak row than the frozen placement and routed 59%
# worse, its crossings spread over more rows and gathered in the lanes' own
# columns. So each net's demand is spread over its box (RUDY): a net crossing
# row boundary y adds 1/width to each slice column of its box there - its one
# vertical track, shared out - and likewise for column boundaries. The map is
# per slice column and slice row; the percentiles and the sums above a level
# say how much of it stands where the wiring runs out.
import numpy as np
NX, NY = 154, 350
dv = np.zeros((NY + 2, NX + 2))
dh = np.zeros((NY + 2, NX + 2))
for b, (y0, y1) in net_y.items():
    xr = net_x.get(b)
    if xr is None:
        continue
    x0, x1 = xr
    ya, yb = int(y0), min(int(y1), NY - 1)
    if yb > ya:
        v = 1.0 / (x1 - x0 + 1)
        dv[ya, x0] += v; dv[ya, x1 + 1] -= v; dv[yb, x0] -= v; dv[yb, x1 + 1] += v
    if x1 > x0:
        h = 1.0 / (yb - ya + 1)
        dh[ya, x0] += h; dh[ya, x1] -= h; dh[yb + 1, x0] -= h; dh[yb + 1, x1] += h
V = dv.cumsum(0).cumsum(1)[:NY, :NX]
H = dh.cumsum(0).cumsum(1)[:NY, :NX]


def over(m, level):
    return float(np.maximum(m - level, 0).sum())


pv = np.percentile(V, [50, 90, 99, 99.9])
ph = np.percentile(H, [50, 90, 99, 99.9])
print(f"rudy       vertical per slice column and row: median {pv[0]:.0f}, 90% {pv[1]:.0f}, 99% {pv[2]:.0f}, "
      f"99.9% {pv[3]:.0f}, max {V.max():.0f}; above 60/80/100: {over(V, 60):.0f} / {over(V, 80):.0f} / "
      f"{over(V, 100):.0f}; horizontal 99% {ph[2]:.0f}, max {H.max():.0f}, above 20/30: "
      f"{over(H, 20):.0f} / {over(H, 30):.0f}")

# --- density ---------------------------------------------------------------
dens = []
for b in range(0, 350, BAND):
    used = [s for s in slices_used if b <= s[1] < b + BAND]
    luts = sum(slice_luts[s] for s in used)
    dens.append(luts / len(used) if used else 0)
print(f"density    LUTs per used slice by {BAND}-row band: {min(dens):.2f} to {max(dens):.2f}; "
      f"{len(slices_used)} slices used")
print("   " + " ".join(f"{v:6.2f}" for v in dens))

# --- blocks ----------------------------------------------------------------
cell_blk = []
for (x, y, sl, bs) in cells:
    votes = Counter(net_block[b] for b in set(bs) if b in net_block and users[b] <= FANOUT_GLOBAL)
    cell_blk.append(votes.most_common(1)[0][0] if votes else "(no named net)")
blk_rows = defaultdict(list)
for (x, y, sl, bs), blk in zip(cells, cell_blk):
    blk_rows[blk].append(y)
def mid80(ys_):
    ys_ = sorted(ys_)
    return ys_[len(ys_) // 10], ys_[(9 * len(ys_)) // 10]


# the lanes, one block each: g_bank256.u_fma and g_bankNN.g_laneNN[i]
by_bank = defaultdict(list)
for b, ys_ in blk_rows.items():
    m = re.match(r'u_lanes\.(g_bank\d+)\.(u_fma|g_lane\d+\[\d+\])$', b)
    if m and len(ys_) >= 100:
        p10, p90 = mid80(ys_)
        by_bank[m.group(1)].append(p90 - p10)
summ = []
for bank in sorted(by_bank, key=lambda k: -int(k[6:])):
    v = sorted(by_bank[bank])
    summ.append(f"{bank} {v[len(v) // 2]:.0f}" + (f" (of {len(v)} lanes, {v[0]:.0f} to {v[-1]:.0f})" if len(v) > 1 else ""))
print("smear      rows holding the middle 80% of a lane's cells, median by bank: " + "; ".join(summ))
big = sorted(blk_rows, key=lambda k: -len(blk_rows[k]))[:16]
print(f"  {'block':44s} {'cells':>7s}  rows of the middle 80%")
for b in big:
    p10, p90 = mid80(blk_rows[b])
    print(f"  {b[:44]:44s} {len(blk_rows[b]):7d}  {p10:5.0f} - {p90:5.0f}")

# --- who crosses the middle -------------------------------------------------
net_cells = defaultdict(list)
for (x, y, sl, bs), blk in zip(cells, cell_blk):
    for b in set(bs):
        if b in net_y:
            net_cells[b].append((y, blk))
pairs = Counter()
for b, cl in net_cells.items():
    lo, hi = min(cl), max(cl)
    if lo[0] < middle <= hi[0]:
        pairs[(net_block.get(b) or Counter(k for _, k in cl).most_common(1)[0][0], lo[1], hi[1])] += 1
print(f"  nets across row {middle:.0f} by block: the net's | at its lowest cell | at its highest cell")
for (nb, lo, hi), n in pairs.most_common(12):
    print(f"    {n:6d}  {nb[:32]:32s} | {lo[:28]:28s} | {hi[:28]:28s}")
