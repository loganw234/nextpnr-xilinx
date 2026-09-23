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

## 2026-09-23 - the first build, and a control that compared the wrong file

`dense/build.sh` at 9ffb7d6 built 0.9.6-3-g9ffb7d6a (binary sha256
5942c475...) in the toolchain image in about ten minutes on eight jobs, and
its control reported **DIFFERS**: blinky-kc705's bitstream was 9d0befc4...
from the image's own binary and 3109a856... from this build, and neither
was the 2471bcc7... the image recorded when it was built.

Taken apart on the same machine, one step at a time:

    yosys, twice on blinky.v               identical netlists (d1e99e30...)
    image binary, twice on that netlist    identical FASM (53ccdc52...)
    image binary, OMP_NUM_THREADS=1, twice identical FASM (53ccdc52...)
    this build, on that netlist            FASM 4f82b273..., differing from the image's in ONE line:
                                           "# nextpnr-xilinx 0.9.6" against "# nextpnr-xilinx 0.9.6-3-g9ffb7d6a"

So nextpnr is deterministic here, run to run and across thread counts, and
this build routes blinky exactly as the pinned binary does. The bitstreams
differ because `xc7frames2bit` writes the date and time into the `.bit`
header ("2026/09/23 20:18:39" in this build's; "2026/08/13 10:23:30" in the
one committed to demo-projects): no two bitstreams hash alike, so the
recorded 2471bcc7... could never have been reproduced. The control was
comparing the one file that cannot match.

`build.sh` now compares the FASM, excluding the version comment, and reads
which binary ran from its log (only this branch prints `router2 settings:`).
Found by chasing the DIFFERS rather than waving it through; the determinism
it established is also what the bench's curve comparisons rest on, and it
holds on blinky - on the tile it is still to be shown, by running one
configuration twice.

## 2026-09-23 - the first bench runs: a reloaded placement 0.9.6 cannot route

Four runs of the frozen placement, `--input placed` (the only mode then),
from 13:26 box time; times below are the log's, in UTC.

| run | binary, settings | outcome |
|---|---|---|
| base | 0.9.6-4-g2860169e, defaults, cap 2 | **failed** in iteration 1, 12 minutes into routing (20:27 to 20:39) |
| altweights | same binary, alt-weights | stopped by decision at 13:41, still in iteration 1 |
| est125 | same binary, estimate weight 1.25 | stopped by decision at 13:41, still in iteration 1 |
| roundtrip-image | the image's own 0.9.6, copied out of it (sha256 4c7e1b92...) | **failed** identically, 20:52:50 |

Both failures:

    ERROR: Failed to route arc 7 of net '$abc$5595557$flatten\u_krnl.\u_seq.$procmux$122531_Y[1]',
           from SITEWIRE/SLICE_X121Y302/A6LUT_O6 to SITEWIRE/SLICE_X120Y303/AFFMUX_OUT.

That error comes after the search without a bounding box has found no path
at all - a connectivity failure, which no cost setting changes; so the two
variants were stopped rather than left to reach it. The same placement,
placed and routed in one process by the same pinned binary (cft-fp256's
`pnr-board-6a2b26c`, still running), routed every arc through three
iterations (340,836; 98,546; 74,578). Both flows adopted 50,736 pre-routed
arcs before router2 started. So **0.9.6 does not route a placed design it
wrote itself the way it routes the same design in memory**, and since the
pinned binary fails identically, the defect is upstream's, not this
branch's. Not investigated further yet; the arc - a LUT output to the
flip-flop input multiplexer of a neighbouring slice - is named above for
whoever does.

The placement is the same either way: placement is deterministic here (the
frozen placement's 26 wirelength lines equal the original run's, line for
line). So `bench.sh` now places and routes in one process by default
(`--input netlist`, about 20 minutes of placement a run) and compares each
run's trajectory with the frozen placement's - checked both ways before use:
IDENTICAL against the original 6a2b26c run, DIFFERS from the first line
against the ef9c3ec board's.

**And a defect of `bench.sh`'s own.** Neither failed run got a
`summary.txt`: the grep for iteration lines found nothing, and under `set
-e` that ended the script before the summary was written - the one kind of
run whose summary matters most. The analysis is now a function with
errexit off, and `bench.sh --summarize RUN_DIR` reads any run again; the
four runs above were summarised that way by the commit that adds it.
