#!/usr/bin/env python3
"""How many of a synthesised netlist's LUTs could share a physical LUT?

A 7-series LUT6 can hold two functions (LUT6_2: O6 and O5) when their
inputs together number at most five. nextpnr-xilinx's placer never pairs
general LUTs this way - on the bench placement the 5LUT bels in use were
four to each carry slice, the chains' DI feeds - while Vivado pairs
routinely (NEXTPNR_PACK_LUT_PAIRS does it in the packer). This reads a
Yosys JSON netlist (streamed; nextpnr's input, not a placed design) and
matches LUTs that share an input net, greedily, most shared inputs first:
two LUTs are a candidate pair when both have at most five inputs and their
inputs together number at most five. LUTs driving a CARRY4's S input are
left out (each already shares its LUT with the chain's DI feed-through), as
are nets above FANOUT_CAP readers when looking for partners (a pair found
through such a net still counts if it shares a smaller one too).

It prints the LUTs by size, the pairs found, the physical LUTs they save,
and the LUT input pins the router must reach before and after: a shared
input is one pin of the pair's LUT, not two.

usage: lut_pairs.py NETLIST_JSON [FANOUT_CAP]
"""
import re
import sys
from collections import Counter, defaultdict

path = sys.argv[1]
cap = int(sys.argv[2]) if len(sys.argv) > 2 else 32
key_re = re.compile(r'^        "(.+)": \{$')
type_re = re.compile(r'^          "type": "([A-Za-z0-9_]+)"')
conn_re = re.compile(r'^            "([A-Za-z0-9_\[\]]+)": \[ (.*) \]')

luts = []            # (type, inputs tuple, output bit)
carry_s = set()      # nets on CARRY4 S inputs
in_conn = False
ctype = None
conns = {}


def finish():
    if ctype and ctype.startswith("LUT") and ctype[3:].isdigit():
        ins = tuple(sorted({b for p, bs in conns.items() if p.startswith("I") for b in bs}))
        out = conns.get("O", [None])[0]
        luts.append((ctype, ins, out))
    elif ctype == "CARRY4":
        for b in conns.get("S", []):
            carry_s.add(b)


with open(path) as f:
    section = None
    for line in f:
        if line.startswith('      "cells": {'):
            section = "cells"; continue
        if line.startswith('      "netnames": {'):
            section = None; continue      # a netlist may hold several modules
        if section != "cells":
            continue
        if key_re.match(line):
            finish()
            ctype = None; conns = {}; in_conn = False
            continue
        m = type_re.match(line)
        if m:
            ctype = m.group(1); continue
        if '"connections": {' in line:
            in_conn = True; continue
        if in_conn:
            m = conn_re.match(line)
            if m:
                conns[m.group(1)] = [int(t) for t in m.group(2).split(',') if t.strip().isdigit()]
            elif line.strip().startswith('}'):
                in_conn = False
    finish()

n = len(luts)
if n == 0:
    sys.exit(f"{path}: no LUT cells found - not a Yosys JSON netlist of a Xilinx design?")
size = Counter(t for t, _, _ in luts)
print(f"{path}: {n:,} LUTs: " + ", ".join(f"{k} {size[k]:,}" for k in sorted(size)))
pinned = {i for i, (_, _, o) in enumerate(luts) if o in carry_s}
print(f"{len(pinned):,} drive a CARRY4 S input and are left out; {len(carry_s):,} S nets")
readers = defaultdict(list)
for i, (_, ins, _) in enumerate(luts):
    if i in pinned or len(ins) > 5:
        continue
    for b in ins:
        readers[b].append(i)
cand = {}
for b, rs in readers.items():
    if len(rs) < 2 or len(rs) > cap:
        continue
    for x in range(len(rs)):
        a = rs[x]; sa = set(luts[a][1])
        for y in range(x + 1, len(rs)):
            c = rs[y]
            if (a, c) in cand:
                continue
            u = sa | set(luts[c][1])
            if len(u) <= 5:
                cand[(a, c)] = (len(sa) + len(luts[c][1]) - len(u), len(u))
order = sorted(cand.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))
used = set(); pairs = []
for (a, c), (sh, un) in order:
    if a in used or c in used:
        continue
    used.add(a); used.add(c); pairs.append((a, c, sh, un))
pins_before = sum(len(ins) for _, ins, _ in luts)
saved = sum(sh for _, _, sh, _ in pairs)
by_shared = Counter(sh for _, _, sh, _ in pairs)
kinds = Counter(tuple(sorted((luts[a][0], luts[c][0]))) for a, c, _, _ in pairs)
print(f"candidate pairs (sharing a net of at most {cap} readers): {len(cand):,}")
print(f"pairs matched: {len(pairs):,} ({2 * len(pairs):,} LUTs, {100 * 2 * len(pairs) / n:.1f}%): "
      f"{len(pairs):,} physical LUTs fewer, {n:,} -> {n - len(pairs):,}")
print("  by inputs shared: " + ", ".join(f"{k} {by_shared[k]:,}" for k in sorted(by_shared)))
print("  most common kinds: " + ", ".join(f"{a}+{b} {v:,}" for (a, b), v in kinds.most_common(8)))
print(f"LUT input pins: {pins_before:,} -> {pins_before - saved:,} ({-100 * saved / pins_before:.1f}%)")
free_small = Counter(len(luts[i][1]) for i in range(n) if i not in used and i not in pinned and len(luts[i][1]) <= 3)
print("unpaired LUTs of at most 3 inputs (pairable by size alone, if placed together): "
      + ", ".join(f"{k} inputs {free_small[k]:,}" for k in sorted(free_small)))
