# nextpnr-xilinx, `dense` branch

A fork of [openXC7/nextpnr-xilinx](https://github.com/openXC7/nextpnr-xilinx)
for routing designs that fill most of a 7-series part. It exists for
[cft-fp256](https://github.com/loganw234/cft-fp256), whose tile, at 53 to
67% of an XC7K325T's LUTs in Vivado's count, routes in Vivado at 100 MHz and
did not converge in this router: on 2026-09-22/23 four runs of the unmodified
0.9.6 still had tens to hundreds of thousands of overused wires after one to
five iterations, each iteration taking half an hour to several hours
([dense/LEDGER.md](dense/LEDGER.md)). The reading of the router behind this
branch is cft-fp256's
[docs/studies/TOOL-A-dense-router.md](https://github.com/loganw234/cft-fp256/blob/main/docs/studies/TOOL-A-dense-router.md).

## The base

`dense` starts at **3fd78784**, which is tag **0.9.6**: the nextpnr-xilinx
that openXC7's toolchain installer 3752d35d pins and that cft-fp256's
`docker/Dockerfile.openxc7` image carries, with the chip database
`xc7k325tffg900.bin` sha256 d3d90cb6... built beside it. On 2026-09-23
openXC7's `main` was seven commits ahead of it, none in the router or the
placer; one of them moves prjxray-db, which changes the chip database every
comparison here depends on, so rebasing waits until a change here is worth
sending back.

## How work is done here

The rule is traceability: any number in the ledger can be traced to the
commit that produced it, the settings that actually applied, and the input
it ran on.

- **A change to what the router or placer does is off by default,** behind
  a named setting, until the ledger records it helping. One binary then
  runs both sides of every comparison, and the default build routes as
  0.9.6 does.
- **`dense/build.sh` checks that**, every build: openXC7's blinky-kc705 goes
  through the whole flow with the image's own binary and with this build,
  and the two FASM files must be identical apart from the comment naming
  the version. The verdict is written into `BUILD-INFO.txt` beside the
  binary.
- **Every run is recorded in [dense/LEDGER.md](dense/LEDGER.md)** -
  dated, appended to and never edited; a correction is a new entry. An
  entry names the binary's version (`git describe --dirty`), the settings
  as router2 printed them, the placement, and the load on the machine,
  and says what did not work as plainly as what did.
- **A build from uncommitted changes calls itself `-dirty`,** and its
  results are not results of any commit.

## Using it

    bash dense/build.sh [BUILD_DIR]        # -> BUILD_DIR/nextpnr-xilinx and BUILD-INFO.txt
    bash dense/bench.sh --name NAME --binary BUILD_DIR --settings dense/settings/FILE.txt                         [--max-iter N] [--heatmap]
    bash dense/bench.sh --summarize RUN_DIR   # read a finished run again

`bench.sh` places and routes cft-fp256's board netlist
(`~/dense-bench/netlist.json`) in one process and shows each run's
placement to be the frozen one (`~/dense-bench/place.log`, made once by the
pinned binary, with its PROVENANCE.txt): placement is deterministic, and the
summary says IDENTICAL or where it differs. So runs differ only in the
binary and the settings. Each run's directory holds its provenance, the
timestamped log, the overuse curve, the machine's load, and a summary read
from the log rather than from the exit code. The settings files in
`dense/settings/` are `KEY=VALUE` lines: a `router2/` key goes to
`--set-route`, a `NEXTPNR_` name into the run's environment, anything else
to `--set`. `--heatmap` adds the per-iteration congestion files. A run
whose settings move the placer is expected to place differently, and its
summary says so; compare its curve with that in mind.

## What this branch adds, so far

| commit | what | changes routing? |
|---|---|---|
| router2 prints its settings | every router2 setting as applied, which were set explicitly, and the iteration caps from the environment; an unknown `router2/` key is refused by name | no |
| `--set KEY=VALUE` | a setting applied after the design file loads, logged with what it replaced; and a log line for every setting a design file overrode | no |
| `--set-route KEY=VALUE` | the same, applied after placement and immediately before routing, so a router setting cannot change the placement; `bench.sh` passes every `router2/` key this way | no |
| `router2/heatmap=PREFIX` | after each iteration, overuse by wire type (pin feeds and bounces against singles, doubles, quads, longs), by grid coordinate and by net, as CSV, and the top wire types in the log; off by default | no |
| `router2/timingDriven=0|1` | the router's own switch for timing-driven routing (criticality in the wire cost, and the per-iteration timing analysis); the global `timing_driven` also steers the placer, so it cannot ask a routing-only question. Unset, the global one decides, as before | only when set |
| `router2/currCongWeightGrowth=F` | the congestion price becomes price x F + currCongWeightMult after each iteration; 1.0 (the default) is upstream's addition, bit for bit | only when not 1.0 |
| `router2/revisitCheaper=1` | a wire the search reaches again for less is re-parented and queued again, stale queue entries skipped; upstream keeps the first path to reach a wire | only when set |
| `router2/bbGrowEvery=N`, `bbGrowBy=M` | a net that keeps failing grows its box by M tiles every N failures; upstream's 1 every 10 by default | only when changed |
| `router2/partition=GXxGY,...`, `router2/threads=N` | grids, finest first: a net routes in the first grid one of whose cells holds its box, a grid's cells in parallel up to N threads (0: the hardware's count), then what fits no cell on one thread. Unset, upstream's quadrants-halves-one-thread code runs unchanged | only when set |

## What bites

- **A placed design's own settings are written over the command line's.**
  `frontend_base.h` imports a JSON's `settings` after the options are
  applied, so routing a placed design again with another `--freq`,
  `--no-tmdriv` or `--seed` silently keeps the file's. This branch logs
  every setting the file replaced; `--set` is applied after the load.
- **A setting added before packing changes the placement, even one only the
  router reads.** With `--set router2/heatmap=heat` the annealer's trajectory
  left the frozen placement's at its fifth iteration; the same build with no
  `--set` placed identically (dense/LEDGER.md). Router settings go in with
  `--set-route`.
- **A misspelt setting is silently defaulted upstream.** `Context::setting()`
  returns the default when the key is absent. This branch refuses unknown
  `router2/` keys; other prefixes (`placerHeap/`, ...) are still silent.
- **The 0.9.6 base reads knobs from the environment:**
  `NEXTPNR_ROUTER2_MAX_STALL` / `_MAX_ITER`, `NEXTPNR_PLACER_BETA`,
  `NEXTPNR_SPREAD_SCALE_X` / `_Y`, `NEXTPNR_PLACER_ALPHA`,
  `NEXTPNR_ARC_MAX_VISIT`, `NEXTPNR_SKIP_FAILED_ARCS` (which accepts a
  partial route - `bench.sh` refuses to run with it set) and
  `NPNR_ROUTER1_RECHECK`. `bench.sh` records every `NEXTPNR_` and `NPNR_`
  variable it passes, with its value (by name alone until 2026-09-24).
  For the 7-series the HeAP knobs are the variables and nothing else:
  `xilinx/arch.cc` sets `beta` 0.4 and `alpha` 0.08 over whatever
  `placerHeap/beta` and `placerHeap/alpha` said.
- **0.9.6 does not route a placed design it wrote the way it routes the same
  design in memory.** Reloaded with `--no-pack --no-place`, cft-fp256's
  placement has an arc no search can reach, which the in-memory flow routes;
  the pinned binary fails identically, so this is upstream's. `bench.sh`
  places and routes in one process instead (`--input placed` keeps the
  reload for when it is fixed).
- **Its Python bindings do not reach `ctx->settings`,** so a `--pre-route`
  script cannot set router options; hence `--set`.
- **Iteration times depend on the machine's load.** `bench.sh` logs it each
  minute. The overuse per iteration should not depend on it - to be shown
  by running a configuration twice, and recorded, not assumed.
- **No bitstream is byte-reproducible.** `xc7frames2bit` writes the date
  and time into every `.bit` header, so two builds of the same design never
  hash alike - compare the FASM. (This branch's first control compared
  bitstreams and reported a difference that was only the clock.)
- **The chip database must be the one the base was built with.**
