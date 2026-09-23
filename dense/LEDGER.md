# Ledger, `dense` branch

Dated, appended to, never edited: a correction is a new entry naming the
one it corrects. Each run is traceable to the commit that produced it
(`git describe --dirty`), the settings router2 printed as applied, the
placement it routed, and the load on the machine that ran it - the files
`dense/bench.sh` writes hold all four. Times are in the build machine's
clock (UTC-7).

## 2026-09-23 - the branch, and the baseline it has to beat

**Why.** cft-fp256's single tile is routable on an XC7K325T - Vivado 2026.1
routes the board configuration at 100 MHz with +0.411 ns, the full tile at
+0.155 and +0.182 (cft-fp256 docs/VALIDATION.md, 2026-09-23) - and the
0.9.6 router does not converge on it. The reading of that router, and why
this branch starts where it does, is cft-fp256's
docs/studies/TOOL-A-dense-router.md.

**The base.** 3fd78784 = tag 0.9.6, forked from openXC7/nextpnr-xilinx to
loganw234/nextpnr-xilinx on 2026-09-23; `dense` created at that commit.

**The baseline: four runs of the unmodified 0.9.6, none converged.** Each
placed and routed in one run by cft-fp256's toolchain image (56bca0f723e3)
on amd-arc-box, `--freq 100 --timing-allow-fail`, from netlists
cft-fp256's `hw/openxc7/run_pnr_inner.sh` synthesised with Yosys 0.69. No
run timestamped its iterations; the times below are when each line was
seen in the log. Overuse is router2's total over wires of (nets on the wire
- 1); "overused" counts the wires.

| run | configuration | LUT bels | overuse after iterations 1, 2, 3 ... | end |
|---|---|---|---|---|
| pnr | board: MUL_PASSES=10, ladders on (ef9c3ec) | 160,138 of 407,600 (39%) | 334,494; 85,421; 56,656; 47,133; 43,343 (iteration 5 by 12:07) | stopped 13:05 |
| pnr-f1 | full rate, ladders on (ef9c3ec) | 182,106 (44%) | 542,678 (iteration 1 by 07:07; no second in the six hours after) | stopped 13:05 |
| pnr-f2 | full rate, ladders off (ef9c3ec) | 214,154 (52%) | 420,129; 128,231; 89,419; 77,116; 69,979 (iteration 5 by 12:58) | stopped 13:05 |
| pnr-board-6a2b26c | board, integer multiply registered (6a2b26c) | 160,261 (39%) | 340,836; 98,546 (iteration 2 by 10:49) | running |

The three on ef9c3ec were stopped by decision, to free the machine for the
experiments below; their logs stay in cft-fp256's `~/cft-board-run/` on
amd-arc-box. Each nextpnr process used 1.3 to 1.5 cores of 36 while routing.
The board run's last step shrank overuse by 8%, from an iteration of more
than two hours.

**What comes next, and how it will be judged.** One placement of the
6a2b26c board netlist is made once, by the pinned binary with
`--no-route`, and every experiment routes that same placement through
`dense/bench.sh`, with a cap on iterations. Settings first
(`dense/settings/`: mainline's estimate weight, mainline's alt-weights
profile, a wider bounding box, timing-driven routing off), then code. A
change is judged by its overuse curve against the base settings' curve on
the same placement, and by minutes per iteration beside the load it ran
under.
