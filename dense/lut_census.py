#!/usr/bin/env python3
"""What fills the LUT bels of a placed nextpnr-xilinx design.

Each cell on a SLICE's 6LUT or 5LUT bel is counted by where it came from,
read from its name: a LUT or SRL of the synthesised netlist, a feed-through
LUT the packer inserted to relay a net ("<net>$LUT$<n>"), a constant LUT
the packer inserted ($PACKER_VCC_NET / $PACKER_GND_NET), or distributed RAM
("/DPR", "/SPR"). The 6LUT count is the number of physical LUTs in use,
the figure to set beside Vivado's LUT count.

usage: lut_census.py PLACED_JSON
"""
import collections
import re
import sys

key_re = re.compile(r'^        "(.+)": \{$')
bel_re = re.compile(r'"NEXTPNR_BEL": "SLICE_X\d+Y\d+/([A-D][56]LUT)"')


def kind(n):
    if n.startswith("$PACKER_VCC_NET$LUT$"):
        return "packer: VCC LUT"
    if n.startswith("$PACKER_GND_NET$LUT$"):
        return "packer: GND LUT"
    if "$LUT$" in n:
        return "packer: feed-through LUT"
    if "/DPR" in n or "/SPR" in n:
        return "distributed RAM"
    return "netlist LUT or SRL"


kinds = collections.Counter()
cur = section = None
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith('      "cells": {'):
            section = "cells"; continue
        if line.startswith('      "netnames": {'):
            break
        if section != "cells":
            continue
        m = key_re.match(line)
        if m:
            cur = m.group(1); continue
        m = bel_re.search(line)
        if m and cur:
            kinds[(m.group(1)[1:], kind(cur))] += 1
tot = collections.Counter()
for (b, k), v in kinds.items():
    tot[b] += v
print(f"{sys.argv[1]}: 6LUT bels in use (physical LUTs) {tot['6LUT']:,}; 5LUT bels {tot['5LUT']:,}")
for (b, k), v in sorted(kinds.items()):
    print(f"  {b}  {v:8,}  {k}")
