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

## 2026-09-24 - the partition round: its runs were refused, and nothing checked that they had started

`router2/partition` (a28f0e4) was built at 00:49 by a script that would
launch nothing unless the build's control matched, and it did: blinky's
FASM from the new build is identical to the image binary's apart from the
version comment (BUILD-INFO.txt, `build-dense-a28f0e4`). The script then
stopped `revisit` in its third iteration - -2.2% and -7.1% against the
reference at iterations 1 and 2, the gain grow15 gets for nothing, at 2.7
times the time (its run directory's `STOPPED`) - to free a slot for
`altw-part`, and launched `altw-part` at 00:52 and `part` at 01:07.

Neither ran. `dense/bench.sh` refused both settings files at their first
line with a value in it:

    FATAL: settings line is not KEY=VALUE: 'router2/partition=8x8,4x4,8x1,4x1,1x4,2x2,2x1,1x2'

A value could hold letters, digits and `_ . + -`, and the partition's grid
list is separated by commas. The refusal was right to stop the run and it
named the line. Two things were wrong around it:

- the refusal came after the run directory was made, so each launch left
  a directory holding only `settings.txt` (`20260924-0052-altw-part`,
  `20260924-0107-part`); each now holds a `REFUSED` file saying so, and
  neither is a run;
- the script that launched them wrote "launched" and went on without
  looking at what it had launched. `revisit`'s slot stood empty for an
  hour, until a look at the machine's processes at 01:39 found no
  partition run among them.

**Fixed in bench.sh:**

- a value may hold commas;
- the settings are read and checked from a copy before the run directory
  exists, and that copy is what the run keeps, so a refused run leaves
  nothing behind;
- PROVENANCE.txt now names the bench script's own commit (`bench` line).
  Until now it named only the binary's, and a run's settings are parsed
  by the script.

From here on, a launch is recorded only after the run's own log has
started.

## 2026-09-24 - where the overuse is: small nets in the placement's densest rows; grow15 stopped; the placer's own spreading tried

Overuse after each iteration, on the validated placement, as of 03:10
(the table of "the first variants", continued; percentages against the
reference unless said otherwise):

| run | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| reference | 340,836 | 98,546 | 74,578 | 66,479 |
| grow15 | 340,836 | 91,488 (-7.2%) | 69,817 (-6.4%) | 65,622 (-1.3%), then stopped |
| altweights | 28,199 | 28,761 (+2.0% on its own first) | running | |
| altw-est175 | 40,476 (+44% on altweights') | running | | |

**altw-est175** - alt-weights' prices with the base's 1.75 estimate
weight - took 96 minutes for its first iteration against altweights' 226,
its one-thread phase 4,240 s against 10,484. The greedier search is 2.4
times faster and leaves 44% more overuse.

**altweights' second iteration is flat**, and slower per net where it is
serial:

    quadrants 9,280 nets 724 s | halves 1,847 nets 589 s, 7,359 nets 3,388 s |
    one thread 2,518 nets 8,409 s

- 3.3 s a net on one thread, eleven times the first iteration's 0.30 s.
With the congestion price held at 5.0 (its addition is 0.0), only the
history price moves between iterations; `altw-grow15` (71b2eb5), queued
behind cft-fp256's U50 sweep, raises the price by 1.5 times each
iteration to see whether that breaks the plateau.

**Where the overuse is.** From altweights' heat files and the frozen
placement's cells (`placed.json`'s BEL attributes):

- *by net:* 21,004 nets carry overuse after iteration 1 and 22,455 after
  iteration 2. Nets of 1 to 16 users carry 96.5% and 97.2% of the per-net
  total, nets of more than 40 users 2.1% and 1.6%. `u_krnl.arr_rdy`, the
  31,968-user outlier of the first congestion map above, carries 5 units
  of 57,534 after iteration 2. High fanout is not what is overused.
- *by place:* grid rows 150 to 224 hold 64% of iteration 1's overuse and
  73% of iteration 2's. Along the rows it spreads over columns 36 to 215.
  The six hottest columns - 165, 166, 170, 171, 175, 176 - hold 18.5% of
  iteration 1's. **A correction:** the first congestion map's "concentrated
  right of centre, x 165 to 175", and "the first variants"' "in the same
  columns as the defaults', x 165 to 176", name the hottest columns, not
  where most of the overuse is. Most of it lies along the middle rows.
- *the placement:* 44,377 of the chip's 50,950 slices are used, and the
  160,261 LUTs fill 39% of the LUT sites (eight a slice, 6- and 5-input).
  Every 25-row band of slice rows is roughly 75 to 92% used. LUTs per used
  slice rise from 2.73 in rows 0-24 to between 3.85 and 4.11 in rows
  125-274, then fall to 3.41 in the top band. The densest rows are the
  rows with the overuse.

So the demand is highest where the placement is densest, and it is spread
over some twenty thousand small nets in those rows. A price moves a net
only onto a free detour. That the best prices tried so far level off near
28,000 fits too few free detours in those rows, but it does not prove it.

**Decision.** grow15 was stopped at 03:09, in its fifth iteration (its
`STOPPED`): the growth factor's gain shrank each iteration, from 7.2% to
6.4% to 1.3%. Its slot went to a placement question.

**The placer's own spreading.** The base's HeAP spreads a region of the
chip once its cells exceed beta times its sites. `xilinx/arch.cc` sets
beta to 0.4 for the 7-series, over `placerHeap/beta`, and reads
`NEXTPNR_PLACER_BETA` from the environment ("try 0.2-0.3 to de-congest",
its comment says). This design fills 39% of its LUT sites, so at 0.3 no
region meets the target, and the spreading reaches across the whole chip.

- `bench.sh` (8d12587) now takes `NEXTPNR_` lines in a settings file as
  the run's environment. It refuses a name that the caller's environment
  sets as well, and it refuses the iteration cap, which is `--max-iter`.
  Both refusals were checked (exit 1, no run directory).
- PROVENANCE.txt now records every passed variable with its value; until
  now it recorded names alone.
- `altw-beta30` is altweights' prices with `NEXTPNR_PLACER_BETA=0.3`,
  capped at three iterations. It was launched at 03:09 from 8d12587 on
  the a28f0e4 binary. Its log reads `beta=0.300`, and its placement
  differs from the frozen one by design.

**A precision about "altweights".** It runs the four values of mainline's
alt-weights profile in 0.9.6's cost function. Mainline's router also
scales both congestion prices by the arc's criticality (a weight of
max(0.05, 1 - crit^2)), prices shared "resources", and differs in other
ways. Nothing here measures mainline's router. "The first variants"'
heading - "mainline's alt-weights cuts the first iteration's overuse
twelvefold" - should be read as mainline's alt-weights values doing so.

**Times for the record.** The two refused partition launches of 00:52
and 01:07 were relaunched as `altw-part` at 01:43, 51 minutes after the
first; the entry above rounds that to an hour. `part` waits in a launcher
for the sweep to finish, and `altw-part` has routed since 02:04 with the
partition applied, its placement IDENTICAL.

## 2026-09-24 - the placement is where the overuse comes from: every lane spread over the chip's height, and a placer that stops early

**The vertical demand.** `dense/placement_metrics.py` (cfe9141) reads a
placed design and counts, from each net's box, the nets that must cross
each row boundary and each column boundary (nets above 2,000 cells left
out). On the frozen placement:

    nets across a row boundary, mean per 25-row band from the bottom:
      2,062  4,822  8,290  10,917  13,319  13,653  13,708  13,879  12,556  11,612  9,671  7,907  5,892  3,267
    nets across a column boundary, peak 12-column band: 9,208

About 13,800 nets cross each boundary in the middle rows, and they share
the vertical wiring of some 77 CLB columns. The at most 9,208 crossing a
column boundary share the horizontal wiring of 350 rows. Per track, the
vertical demand in the middle is several times the horizontal. The
overuse is on vertical wires in those rows (the entries above), so the
two agree.

**Who crosses.** Most cells carry names ABC generated, but most nets
keep their RTL paths. So each cell was given the block its nets name
most often. The nets crossing row 175 are mostly INSIDE a lane: fp256's
own 1,697, fp32 lanes' 964, fp64's 738, fp128's 595, against a few
hundred between blocks. Their median vertical span is 69 rows, and 32%
span more than 100. Each lane's logic lies spread over most of the
chip's height. The middle 80% of a lane's cells covers 253 rows for
fp256, 236 for fp128, a median 210 for fp64 and 208 for fp32 - where a
2,000-cell fp32 lane with 8-row carry chains would fit in some 25.
Wide arithmetic is vertical on this fabric (fp256's 60-row carry
chains), but not by that much.

**The spreading experiment, measured before it routes.** altw-beta30's
placement, reproduced with `--no-route --write` (trajectory IDENTICAL,
29 lines): the middle rows' LUTs per used slice fell from 3.9-4.1 to
3.6-3.8 and the edges' rose. But 15,532 nets cross row 175 against
14,120 (median span 94 rows against 69), and the wirelength is 13%
higher. Spreading thinned the dense rows and lengthened the nets that
cross them. Its first routing iteration will show whether the crossing
count predicts the router.

**Why the lanes spread: the analytic placer stops early.** HeAP ends at
iteration 11, five iterations after its best legal wirelength, and keeps
iteration 6. At that point the solver's wirelength is 59% of the legal
one; the loop's own target is 80%. The anchors that hold a spread
placement are weak at iteration 6 (alpha x 6 = 0.48).

**Two placer changes, each off by default:**

- e279f69 `NEXTPNR_PLACER_MAX_STALL`, `_MIN_ITER` and `_KEEP=best|last`:
  how long the loop runs and which legal placement it keeps. These are
  environment variables, like the base's other HeAP knobs, because a
  setting added before packing moves the placement through name
  interning. Its control MATCHes blinky. At the defaults it places the
  tile IDENTICALLY to the frozen placement (p-default).
- efa4e31 `NEXTPNR_PLACER_BLOCK_WEIGHT` (with `_DEPTH`, `_MIN`): each
  solved cell of a named block is tied to the block's mean position by a
  two-pin net of that weight, every solve. Blocks are read from the net
  names as above.

`dense/place.sh` (cfe9141) places the bench netlist once, compares the
trajectory with the frozen one, and runs the metrics. A placement takes
minutes where a routing iteration takes hours, so placer changes are
screened on these numbers and only the promising ones are routed.

**The first placements** (efa4e31 and e279f69 binaries, `dense/place.sh`,
metrics as above; "lane spread" is the rows holding the middle 80% of a
lane's cells, median by bank):

| placement | kept | wirelength | nets across row 175 | row bands' peak | column bands' peak | lane spread fp256 / fp128 / fp64 / fp32 |
|---|---|---|---|---|---|---|
| p-default (e279f69, no knobs) | #6 of 11 | 8,568,341 | 14,120 | 13,879 | 9,208 | 253 / 236 / 210 / 208 |
| altw-beta30 (NEXTPNR_PLACER_BETA=0.3) | #10 of 15 | 9,709,979 | 15,532 | 15,449 | 9,127 | 246 / 238 / 243 / 213 |
| p-stall20 | #6 of 26 | 8,568,884 | 14,111 | 13,885 | 9,210 | 254 / 235 / 208 / 208 |
| p-min40-last | #40 of 40 | 9,570,948 | 15,203 | 15,496 | 8,980 | 254 / 243 / 241 / 202 |
| **p-block1** (block weight 1) | #16 of 21 | **8,739,322** | **12,496** | **12,380** | 10,624 | **133 / 118 / 77 / 73** |
| p-block4 (block weight 4) | #21 of 26 | 9,721,753 | 12,454 | 14,294 | 13,199 | 200 / 95 / 67 / 53 |

- p-default's trajectory is IDENTICAL to the frozen placement's (26
  lines): the new code places the tile exactly as upstream does at its
  defaults.
- Letting the loop run to 26 iterations changed nothing. Its legal
  wirelength wanders between 8.8 and 10.2 million and never beats
  iteration 6, so iteration 6 is kept.
- Keeping the last of 40 iterations costs 12% wirelength and spreads the
  lanes no less.
- The block pull at weight 1 is what moves the placement. It gathers
  each lane into a third to a half of the rows it spread over before, and
  cuts the nets across the middle rows by 11% (14,120 to 12,496 at row
  175; 13,879 to 12,380 at the peak band). The cost is 2% wirelength and 15% more
  crossing the column boundaries, the direction with room to spare. At
  weight 4 the small lanes are tighter still, but fp256 spreads out again
  and the wirelength rises 13%.

`altw-block1` routes p-block1's placement with altweights' prices. It was
launched at 04:48 from 244b5fe on the efa4e31 binary, capped at three
iterations, with `--expect-placement` (new in 244b5fe): its trajectory is
compared with p-block1's, not with the frozen placement's. Its curve
against altweights' 28,199 and 28,761 is the test of the whole reading.
p-block05, p-block2 and p-block1-d5 (depth 5: fp256's sub-instances as
blocks) follow as placements. place.sh now asks the kernel to take a
placement first if memory runs out (`--oom-score-adj 1000`, fc6efac).
The placements before that ran at 6 GB free beside a U50 build; their
processes were marked by hand at 04:17.

**Decisions.** `part` (partitioning at the default prices) was cancelled
at 04:10. altw-part answers its question better, and its slot goes to
routing the best placement. `altw-grow15`'s launcher had waited on
`part`'s; it was restarted without that dependency.

## 2026-09-24 - a correction: the block pull's 11% was one draw; the placer varies by seed as much as by any knob so far

The entry above reported p-block1 as cutting the nets across the middle
rows by 11%. That was one placement at nextpnr's default seed. With
`--seed` (7b78a60) the same settings drew differently:

| placement | seed | wirelength | nets across row 175 | row bands' peak | lane spread fp256 / fp128 / fp64 / fp32 |
|---|---|---|---|---|---|
| default placer | default | 8,568,341 | 14,120 | 13,879 | 253 / 236 / 210 / 208 |
| default placer | 2 | 8,514,453 | 12,088 | 15,038 | 261 / 216 / 215 / 180 |
| block pull 1 | default | 8,739,322 | 12,496 | 12,380 | 133 / 118 / 77 / 73 |
| block pull 1 | 2 | 10,713,715 | 16,980 | 16,936 | 201 / 104 / 154 / 101 |
| block pull 1 | 3 | 9,449,276 | 15,248 | 15,444 | 204 / 130 / 109 / 59 |

- The pull gathers the lanes at every seed; fp32's lanes span 59 to 101
  rows against 180 to 208.
- It does not lower the vertical demand. Two draws of three raised the
  peak band above both of the default placer's, with 10 to 25% more
  wirelength.
- The default placer's own peak moves 8% between two seeds.

So a single placement proves nothing here, and from now on each
configuration is judged on three draws.

**Why the pull draws badly.** At seed 2 it began from a legal wirelength
of 26.1 million (seed 1: 20.7; no pull: 14.4), because at the first
solves each block's mean is the mean of a random placement. f38f2f7 lets
the pull start later and ramp in (`NEXTPNR_PLACER_BLOCK_FROM` /
`_RAMP`); p-late-s1..s3 test that.

**What crosses once the lanes are gathered.** The fp256 lane's own nets
(2,125 to 2,211 at row 175) and cells no named net reaches (60,480 of
them, spread over rows 38 to 324 whatever the pull). fp256's cells still
span some 200 rows: its 60-row carry chains and 19,000 cells make it
tall.

**Another knob, more direct.** The vertical weight of HeAP's wirelength
and of the refining annealer's cost is fixed at 2 in the base.
dd2bc97 makes it `NEXTPNR_PLACER_HPWL_SCALE_Y`. p-ys4 and p-ys8 test 4
and 8, each at three seeds.

`altw-block1` routes the lucky draw. What it shows is still worth
having, since it tests whether a lower peak routes better. But it is not
a placement anyone can have by asking for the pull.

## 2026-09-24 - the router's overuse follows the vertical crossings; no placer knob moves them past the seed's own spread; the netlist needs half of them

**The first check of the placement metric.** `altw-beta30` routed the
spread placement (NEXTPNR_PLACER_BETA 0.3) with altweights' prices. Its
first iteration left 40,447 overuse where altweights left 28,199 on the
frozen placement, 43% more, in 5 h 57 min against 3 h 46. Its peak
middle-row crossings were 15,449 against 13,879, 11% more. That is the
direction the metric predicted, and a large response to a small change,
as expected when the demand sits at the vertical wiring's capacity: the
overuse is only what lies above it. One point, not a law. The run was
stopped at 09:30, its question answered.

**Partitioned routing gives no time back.** `altw-part` (alt-weights and
`router2/partition`) took 4 h 05 min for its first iteration against
altweights' 3 h 46, with overuse 29,037 against 28,199. Its grids routed
97% of the nets in parallel in about an hour. The 3,257 nets that no
cell holds took 11,306 s on one thread, 3.5 s each. The time is in the
chip-spanning nets, routed last into a crowded fabric, and a partition
cannot share them out. Stopped at 06:11.

**Every placer knob tried, on three draws each.** The mean of the three
draws' peak middle-row crossings:

| configuration | peak middle-row crossings | mean |
|---|---|---|
| default placer | 13,879 / 15,038 / 13,251 | 14,056 |
| block pull, weight 1 | 12,380 / 16,936 / 15,444 | 14,920 |
| block pull from iteration 1, over 5 (f38f2f7) | 14,948 / 17,109 / 15,733 | 15,930 |
| vertical weight 4 (dd2bc97) | 15,155 / 14,729 / 13,697 | 14,527 |
| vertical weight 8 | 16,317 / 15,547 / 18,093 | 16,652 |

None is below the default's mean. The block pull gathers the lanes at
every seed, yet the crossings do not fall: gathered lanes stacked one
above another send their shared operand and result buses across the
middle instead.

**What the netlist itself needs.** `dense/bisect.py`: FM from the frozen
placement's own split at row 175 cuts 7,467 nets where the placement
cuts 14,215, with the halves at 49.4/50.6. `dense/bands.py` does it
recursively, several starts a split: 7,524 at the middle row, 7,457 and
3,772 at the quarter rows. The start matters a great deal (one start gave
12,654 at the middle) - FM's single level. A placement that respected
such bands would ask the middle rows' vertical wiring for about half of
what HeAP's placements ask.

**Applying the bands: four faults, each caught before a result was
recorded.**

1. The band file carried 715 names JSON-escaped ("\\u_krnl"), and
   `NEXTPNR_DENSE_BANDS` refused the file by name (a1ee2a4 decodes names
   and parents).
2. The 7-series grid counts rows downward (slice row 0 is grid row 363),
   so each band's rectangle ran from its higher row to its lower and was
   empty. The first banded placement aborted in HeAP's first solve (rc
   134). ab98706 takes each band's lowest-to-highest grid rows and counts
   each band's sites before use.
3. Four carry chains are 90 CARRY4s, taller than an 87-row band, and the
   legaliser refused them. 6bfb608 leaves a chain taller than its band
   unconstrained: 3,599 cells in the 4 chains.
4. A 66-row chain whose root could only sit in the far 23 rows of its
   band was never searched there. Upstream's legaliser centres its window
   on the cell with a half-width of at most half the region, and the
   solver had left the root at the near edge. f758d8a keeps a
   region-constrained cell's window inside its region. Only cells with a
   region are affected.

The runs these stopped carry REFUSED or CRASHED notes. One note was
first written as "stopped by decision" for a run that had already
aborted; it was corrected to CRASHED within minutes.

**The sweep beside it.** cft-fp256's U50 sweep missed 175 MHz with the
standard recipe (-0.171 ns). altweights and altw-est175 were stopped at
05:42, both climbing (28,199 / 28,761 / 31,319, and 40,476 / 43,843),
and the memory went to the sweep's retry. altw-grow15 (the price rising
1.5 times an iteration) routes beside it.

## 2026-09-24 - the banded placement: every draw below every default draw, and 11% less wirelength

f758d8a with `NEXTPNR_DENSE_BANDS` at bands/20260924-b4-frozen-v2 (four
bands, the four 90-row chains left free), `dense/place.sh` at three
seeds:

| placement | wirelength | nets across row 175 | peak row band | peak column band | kept |
|---|---|---|---|---|---|
| default placer, default seed | 8,568,341 | 14,120 | 13,879 | 9,208 | #6 of 11 |
| default placer, seed 2 | 8,514,453 | 12,088 | 15,038 | 9,400 | #6 of 11 |
| default placer, seed 3 | 8,943,161 | 12,801 | 13,251 | 10,183 | #6 of 11 |
| **bands, default seed** | **7,703,566** | **7,820** | **11,361** | 12,280 | #10 of 15 |
| **bands, seed 2** | **7,567,994** | **8,460** | **12,315** | 9,244 | #13 of 18 |
| **bands, seed 3** | **7,898,171** | **9,545** | **12,361** | 10,702 | #11 of 16 |

- The crossings at the middle row fall by a third, and every banded
  draw's peak is below every default draw's (means 12,012 against
  14,056).
- The wirelength falls 11%, so the bands help the analytic placer as
  well as constrain it.
- The peak moves into band 1 (rows 100 to 150): the nets inside it, and
  those passing through it between bands 0 and 2 or 3. That is where
  more levels, or different band heights, would act next.
- The lanes are no more gathered than before (a lane's middle 80% over
  158 to 265 rows). The bands cut the crossings by where they put the
  logic, not by gathering blocks.

Two routes of the default-seed placement, launched at 10:22 and 10:23
from 06dc5f4 on the f758d8a binary, capped at five iterations, each with
`--expect-placement` at p-bands4d-sd:

- `altw-bands4`, altweights' prices (to compare with altweights' 28,199);
- `base-bands4`, the default prices (to compare with the reference's
  340,836 / 98,546 / 74,578 / 66,479).

## 2026-09-24 - the banded placement routes: a third of altweights' first-iteration overuse, in half the time; the default prices fall four times as fast

The default-seed banded placement (p-bands4d-sd, f758d8a), routed from
17:53 UTC. Each route's placement was checked IDENTICAL to p-bands4d-sd's
(32 wirelen lines).

| route | placement | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| reference (default prices) | frozen | 340,836 | 98,546 | 74,578 | 66,479 (~8.8 h) |
| **base-bands4 (default prices)** | **bands** | **301,534** (11 min) | **61,437** (31 min) | **26,839** (65 min) | **18,628** (1 h 40 min) |
| altweights | frozen | 28,199 (3 h 46) | 28,761 | 31,319 | stopped |
| **altw-bands4 (alt-weights)** | **bands** | **9,926** (1 h 45) | running | | |

- The banded placement's fourth iteration of the default prices leaves
  72% less overuse than the frozen placement's, five times sooner. The
  curve is still falling steeply (61,437; 26,839; 18,628).
- Its remaining overuse is on short wires: DOUBLE 7,736, SINGLE 4,690,
  BENTQUAD 3,534, VQUAD 1,362, HQUAD 482, VLONG 429. The long vertical
  wires, 11,027 on VLONG alone after altweights' first iteration on the
  frozen placement, are no longer where it is.
- Alt-weights' first iteration on the bands leaves 9,926: a third of the
  frozen placement's 28,199, in 1 h 45 min against 3 h 46. Its one-thread
  phase ran 0.14 s a net against 0.30.
- base-bands4-long (the same route, capped at 40 iterations instead of 5)
  began at 12:35 to see whether the default prices converge. Its first
  five iterations must repeat base-bands4's, a determinism check in
  passing.

**The placement metric, corrected.** altw-block1 (the block pull's lucky
draw) left 44,745 after one iteration, 59% more than the frozen
placement, although its peak middle-row crossings were 11% lower. A row
total cannot see crossings gathered into a few columns. The RUDY map
(93a2242: each net's crossing shared over its box's columns) ranks the
four routed placements as the router did. Vertical sum above 100 per
slice column and row: bands 75,333; frozen 265,629; block1 484,159;
beta30 545,165. altw-block1 was stopped at 12:38.

**The bands' fifth fault, and the fix under way.** The first 8-band
placement failed: a 36-row chain in rows 87 to 130 had no legal start.
The packer writes a chain's offsets as -(i + i/25), skipping the clock
row after every 25 CARRY4s, so a chain of more than 25 starts on a
25-row group boundary. The only one in that band is row 100, and from
there the chain ends at 135. aa2e4b7 puts the band boundaries on those
groups. The 4-band file routed above has boundaries at 87.5 and 262.5,
not on groups; that it worked is partly the tall-chain rule and partly
luck.
