#!/usr/bin/env python3
"""Does every LUT's INIT in the FASM compute what the netlist says?

An independent check of the LUT contents nextpnr-xilinx writes, and of
shared LUTs above all (a 6LUT and a 5LUT on one physical LUT: carry DI
feeds, netlist LUT6_2 halves, NEXTPNR_PACK_LUT_PAIRS). For each LUT on a
SLICE's 6LUT or 5LUT bel - a netlist LUT, or a feed-through or constant
LUT the packer made, whose function its name gives - it takes:

  - the function, from the synthesised netlist (Yosys JSON): the INIT
    over the logical inputs I0..In-1 (an INV is a LUT1 of INIT 01);
  - which net reaches which physical pin A1..A6, from the routed design
    nextpnr wrote (--write), its ports being physical after routing;
  - the INIT[63:0] nextpnr wrote to the FASM for that physical LUT.

and checks, for every address of the physical pins, that the FASM bit is
the netlist function of the nets on those pins: O6 over all 64 addresses
when the 5LUT is free, O6 over A6=1 and O5 over A6=0 when both are used
(A6 must then be tied to VCC). The mapping nextpnr keeps for itself
(X_ORIG_PORT_*) is not read, so a mistake there shows here as a mismatch.
Nets are matched by name: the routed design's name for a net must be one
of the netlist's names for it (a bus bit as "<bus>[<i>]"). Other packer
cells (SRLs, RAM, "$sumLUT$") are only counted.

usage: fasm_lut_check.py TILEGRID_JSON NETLIST_JSON ROUTED_JSON FASM
"""
import json
import re
import sys
from collections import Counter, defaultdict

tilegrid, netlist, routed, fasm = sys.argv[1:5]

# --- sites: SLICE site -> FASM prefix "TILE.SLICEx_Xh" -------------------
site_prefix = {}
for tname, t in json.load(open(tilegrid)).items():
    slices = sorted((s for s in t.get("sites", {}) if s.startswith("SLICE_X")),
                    key=lambda s: int(re.match(r"SLICE_X(\d+)", s).group(1)))
    for s in slices:
        half = int(re.match(r"SLICE_X(\d+)", s).group(1)) % 2
        kind = "SLICEM" if (t["type"].startswith("CLBLM") and half == 0) else "SLICEL"
        site_prefix[s] = f"{tname}.{kind}_X{half}"


def load(path):
    """cells {name: (type, params, attrs, conns)}, bit -> [names] of a JSON design's top module"""
    d = json.load(open(path))
    mods = d["modules"]
    top = max(mods, key=lambda m: len(mods[m].get("cells", {})))
    m = mods[top]
    names = defaultdict(list)
    for n, v in m.get("netnames", {}).items():
        bits = v["bits"]
        # a bus is one netname over several bits; nextpnr names each bit
        # "<bus>[<index>]" (index from the netname's offset, reversed when
        # it is declared upto)
        off = int(v.get("offset", 0))
        upto = int(v.get("upto", 0))
        for i, b in enumerate(bits):
            if not isinstance(b, int):
                continue
            names[b].append(n)
            if len(bits) > 1:
                names[b].append(f"{n}[{off + (len(bits) - 1 - i if upto else i)}]")
    return m["cells"], names


ncells, nnames = load(netlist)
rcells, rnames = load(routed)


def bits_of(s):
    """a Yosys INIT parameter (binary string, MSB first) -> list, index = address"""
    if isinstance(s, int):
        return [(s >> i) & 1 for i in range(64)]
    return [1 if ch == "1" else 0 for ch in reversed(s)]


def logical(name):
    """(inputs, init) of a netlist LUT or INV, or of a feed-through the packer
    made ("<net>$LUT$<n>": a LUT1 buffer of <net>, xilinx/pack.cc
    feed_through_lut; a constant LUT when <net> is a constant net). Inputs
    are netlist net bits, '0'/'1', or ('name', <routed net name>)."""
    c = ncells.get(name)
    if c is None:
        m = re.match(r"^(.*)\$LUT\$\d+$", name)
        if not m:
            return None
        net = m.group(1)
        if net == "$PACKER_VCC_NET":
            return ["1"], [0, 1]
        if net == "$PACKER_GND_NET":
            return ["0"], [0, 1]
        return [("name", net)], [0, 1]
    t = c["type"]
    if t == "INV":
        return [c["connections"]["I"][0]], [1, 0]
    m = re.match(r"LUT(\d)$", t)
    if not m:
        return None
    k = int(m.group(1))
    ins = [c["connections"][f"I{i}"][0] for i in range(k)]
    return ins, bits_of(c["parameters"]["INIT"])


fasm_init = {}
for line in open(fasm):
    m = re.match(r"^(\S+)\.([ABCD])LUT\.INIT\[63:0\] = 64'b([01]{64})$", line.strip())
    if m:
        fasm_init[(m.group(1), m.group(2))] = [int(ch) for ch in reversed(m.group(3))]

# physical LUTs: (prefix, letter) -> {6: cell, 5: cell}
phys = defaultdict(dict)
bel_re = re.compile(r"(SLICE_X\d+Y\d+)/([ABCD])([56])LUT$")
for name, c in rcells.items():
    bel = c.get("attributes", {}).get("NEXTPNR_BEL", "")
    m = bel_re.match(bel)
    if m:
        phys[(site_prefix[m.group(1)], m.group(2))][int(m.group(3))] = name

stats = Counter()
bad = []


def pin_nets(name):
    """physical pin index (0..5) -> the routed design's net name on it"""
    c = rcells[name]
    out = {}
    for i in range(6):
        b = c["connections"].get(f"A{i + 1}")
        if b and isinstance(b[0], int) and rnames.get(b[0]):
            out[i] = rnames[b[0]][0]
    return out


def expect(name, pins, lo, hi, init):
    """compare the netlist function of cell `name` on pins with FASM bits [lo, hi)"""
    lg = logical(name)
    if lg is None:
        stats["cells not checked (neither a netlist LUT nor a feed-through)"] += 1
        return
    if name not in ncells:
        stats["of those checked, packer feed-throughs and constants"] += 1
    ins, fn = lg
    where = []
    for b in ins:
        if isinstance(b, str):
            where.append(("const", 1 if b == "1" else 0))
            continue
        want = {b[1]} if isinstance(b, tuple) else set(nnames.get(b, []))
        p = next((i for i, n in pins.items() if n in want), None)
        if p is None:
            where.append(None)
        else:
            where.append(("pin", p))
    if any(w is None for w in where):
        stats["cells with an input net not found on any pin"] += 1
        if len(bad) < 20:
            bad.append(f"UNMATCHED {name}: logical inputs {ins}, pins {pins}")
        return
    # a pin the router ties to a constant only ever reads that value, so
    # addresses with it the other way are never used (a constant LUT is a
    # buffer of a tied pin); A6 does not reach O5, so it counts for the
    # 5LUT's half only when it is the whole LUT
    tied = {}
    for p, n in pins.items():
        if p == 5 and hi <= 32:
            continue
        if n == "$PACKER_VCC_NET":
            tied[p] = 1
        elif n == "$PACKER_GND_NET":
            tied[p] = 0
    wrong = 0
    for a in range(lo, hi):
        if any(((a >> p) & 1) != v for p, v in tied.items()):
            continue
        idx = 0
        for k, w in enumerate(where):
            v = w[1] if w[0] == "const" else (a >> w[1]) & 1
            idx |= v << k
        if fn[idx] != init[a]:
            wrong += 1
    stats["cells checked"] += 1
    if wrong:
        stats["cells WRONG"] += 1
        if len(bad) < 20:
            bad.append(f"WRONG {name}: {wrong} of {hi - lo} addresses; logical {where}")


for key, halves in sorted(phys.items()):
    init = fasm_init.get(key, [0] * 64)
    if key not in fasm_init:
        stats["physical LUTs with no INIT line (all zero)"] += 1
    stats["physical LUTs"] += 1
    c6, c5 = halves.get(6), halves.get(5)
    if c6 and c5:
        stats["shared (6LUT and 5LUT both used)"] += 1
        a6 = rcells[c6]["connections"].get("A6")
        a6n = rnames.get(a6[0], ["?"])[0] if a6 and isinstance(a6[0], int) else "unconnected"
        if "VCC" not in a6n:
            stats["shared with A6 not tied to VCC"] += 1
            if len(bad) < 20:
                bad.append(f"A6 of {c6} is {a6n}, not VCC")
        expect(c6, pin_nets(c6), 32, 64, init)
        expect(c5, pin_nets(c5), 0, 32, init)
        if logical(c5) is not None and logical(c6) is not None:
            stats["shared, both halves netlist LUTs"] += 1
    elif c6:
        expect(c6, pin_nets(c6), 0, 64, init)
    elif c5:
        stats["5LUT alone"] += 1
        expect(c5, pin_nets(c5), 0, 32, init)

for k in sorted(stats):
    print(f"{stats[k]:9,}  {k}")
for b in bad:
    print("  " + b[:300])
print("VERDICT: " + ("PASS" if stats["cells WRONG"] == 0 and stats["shared with A6 not tied to VCC"] == 0
                     and stats["cells checked"] > 0 else "FAIL"))
