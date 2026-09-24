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

## 2026-09-23 - three runs with three placements, and why: a setting added before packing moves the annealer

**The runs.** `diag` (defaults and `--heatmap`), `altweights` and `est125`
(each with `--heatmap`), by 0.9.6-5-g5186cac4, `--input netlist`, from
13:55. All three placed differently from the frozen placement: the 17 HeAP
lines matched and the annealer's did not, from its fifth iteration, and
differently from one another. The two variants were stopped at 14:37 by
decision - neither curve could be compared with the reference or with the
other - and `diag` left to run, for its congestion maps, which describe a
placement of this design whichever it is. `est125`'s one iteration
(283,396 overuse, 11 minutes) is recorded in its summary and compared with
nothing.

**The cause, isolated.** Two placements by 0.9.6-9-ge2cd46ea, `--no-route`,
from 14:38:

    no --set                          IDENTICAL to the frozen placement, all 26 lines
    --set router2/heatmap=heat only   DIFFERS from the annealer's fifth iteration

So this branch's build places exactly as the pinned binary does, and
`--set` - which creates a setting's name and a new key in ctx->settings
before packing - moves the annealer, though only the router ever reads the
setting. (Why the annealer is sensitive to that is upstream's to answer; an
iteration order that follows interned-name indices or hash order would do
it.) **The fix is `--set-route`**, applied after placement, immediately
before routing; `bench.sh` passes every `router2/` key that way. Whether a
setting applied just before routing changes the routing itself, when it
should not, is the next thing to show: a run with nothing set and a run
with only the heatmap on must give the same curve.

**The first congestion map** (`diag`, iteration 1, 342,894 overuse over a
238 x 366 grid): by wire type, vertical quads 109,654 (32%), singles 35,006,
pin feeds into LUT inputs 31,747 (counted once as PINFEED and again as
LUTINPUT), horizontal quads 29,572, doubles 25,518 - general interconnect,
led by vertical wiring, more than slice pin access. By place, concentrated
right of centre, x 165 to 175 and y 150 to 270. By net, broad: 111,662 nets
touch an overused wire, and the 482 of fanout above 100 carry about 5% of
the per-net total - with one outlier, `u_krnl.arr_rdy`, fanout 31,968. The
first iteration is inflated by the router's nearly free first pass; which of
this persists is for iterations 2 and 3.

**Builds.** b2d8e81 (the three convergence knobs and `router2/timingDriven`)
and e2cd46e (phase timing) both MATCH the pinned binary's blinky FASM. The
d47beff build compiled but never finished its control: a `pkill -f` whose
pattern also matched the command running it ended the build script and the
session. Its directory carries a SUPERSEDED note; nothing was run on it.

## 2026-09-23 - the bench validated end to end, and where an iteration's time goes

**The validation pair**, 0.9.6-10-gb5271f45 (control MATCH), `--input
netlist`, capped at two iterations, from 15:04:

| run | settings | placement | overuse after iterations 1, 2 |
|---|---|---|---|
| base | none | IDENTICAL, 26 lines | 340,836 (10 min); 98,546 (79 min) |
| diag2 | `router2/heatmap` by `--set-route` | IDENTICAL, 26 lines | 340,836 (10 min); 98,546 (80 min) |
| reference | the pinned binary, in memory, 2026-09-23 | the frozen placement | 340,836; 98,546; 74,578 |

Both match the reference to the wire - wires 3,884,647 and 4,346,409,
overused 264,619 and 93,732. So this branch's default build routes cft-fp256's
board netlist exactly as 0.9.6 does, `--set-route` changes neither the
placement nor the routing when it sets what only reports, and a variant's
curve can now be read against the reference's directly. (Both runs stopped
at the cap by router2's own "failed to converge" error, which bench.sh reads
as the cap it is.)

**Where the time goes.** The phase line, per iteration:

    iteration 1, 645 s   quadrants 198,919 nets 193 s | halves 18,032 nets 66 s, 16,277 nets 140 s |
                         one thread 34,895 nets 245 s | 32 retried 1 s
    iteration 2, 4,106 s quadrants 83,865 nets 304 s  | halves 10,767 nets 96 s, 13,117 nets 1,755 s |
                         one thread 3,409 nets 1,929 s | 32 retried 22 s

In the second iteration 88% of the time is two phases: the nets that cross
the chip's horizontal midline within one half - tall nets, two threads,
about 0.21 s a net - and the nets that cross both midlines, on one thread,
about 0.57 s a net, against 0.013 s a net in the quadrants. It is the
vertical congestion the heatmaps show, seen from the clock. Two levers
follow: more column strips, so tall nets route in parallel; and cheaper
searches through congested channels.

**The congestion moves between wire types.** diag2, by type:

    iteration 1   VQUAD 109,008   SINGLE 34,696   PINFEED 31,553   LUTINPUT 31,553   HQUAD 29,629   DOUBLE 25,067
    iteration 2   BENTQUAD 28,833 DOUBLE 20,947   VQUAD 19,960     VLONG 9,585       SINGLE 9,455   HQUAD 4,209

The vertical quads' overuse fell by four fifths and the bent quads took the
lead: the negotiation moves the vertical demand onto other resources rather
than dissolving it.

**The variants** (revisit, grow15, notiming, altweights, each capped at five
iterations with the heatmap) were launched from 16:47 by a script that
first checked both runs' summaries - placement IDENTICAL and the curve
1:340836 2:98546 - and would have launched nothing otherwise.

## 2026-09-24 - the first variants: mainline's alt-weights cuts the first iteration's overuse twelvefold, and the rest move it by single digits

On the validated placement, 0.9.6-10-gb5271f45, `--input netlist`,
`--heatmap`, each capped at five iterations, launched 16:47 to 17:09 on
2026-09-23, sharing the machine with each other and with cft-fp256's U50
sweep - so times are indicative, and each run's `load.log` says how
indicative. Overuse after each iteration, as of 00:45:

| run | settings | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| reference | none (the pinned binary; `base` reproduced 1 and 2 to the wire) | 340,836 | 98,546 | 74,578 | 66,479 |
| grow15 | price x1.5 + 2 per iteration | 340,836 | 91,488 (-7.2%) | 69,817 (-6.4%) | running |
| revisit | cheaper paths re-queued | 333,334 (-2.2%) | 91,540 (-7.1%) | running | |
| notiming | router ignores timing | 342,868 (+0.6%) | 99,734 (+1.2%) | 75,195 (+0.8%) | 68,666 (+3.3%) |
| **altweights** | **mainline's alt-weights** | **28,199 (-92%)** | running | | |

grow15's first iteration equals the reference's because the growth factor
first acts after it. revisit's second iteration took 3 h 9 min, about 2.7
times the base's 69, for the same gain grow15 has for nothing. notiming was
never below the reference: timing-driven routing is not what holds
convergence back.

**altweights.** Pricing a shared wire at 5 from the first pass, and
keeping it there, leaves 28,199 overused after one iteration where the
defaults leave 340,836 - and 2.4 times less than the defaults leave after
four. The first iteration took 3 h 46 min against the base's 10, and the
phase line says where:

    quadrants 198,919 nets 285 s | halves 18,032 nets 139 s, 16,277 nets 2,616 s |
    one thread 34,895 nets 10,484 s | 32 retried 39 s

- 77% of it on one thread, at 0.30 s a net. Its remaining overuse is on
vertical long wires (VLONG 11,027, VLONG12 4,490, VQUAD 6,681, BENTQUAD
1,843, DOUBLE 1,050), in the same columns as the defaults', x 165 to 176.
So the negotiation that works here is expensive exactly where the router
is serial, and the column band is a property of the placement, whichever
prices the router uses.

**Decisions.** The reference was stopped at 20:20, in its fifth iteration
after 3 h 24 min of it: cft-fp256's U50 sweep was waiting for the memory it
held, and `base` having reproduced it to the wire, its later iterations can
be regenerated whenever a comparison needs them. notiming was stopped at
00:44 in its fifth, its question answered four times over. Its slot went to
`altw-est175`: alt-weights' prices with the 1.75 estimate weight, to see
whether a greedier search keeps the quality and costs less.

One placement, one seed. Everything here is deterministic, so the
differences are real for this placement; whether they hold on another is
not shown.
