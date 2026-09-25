#!/usr/bin/env bash
# One route of the frozen placement, recorded so it can be traced.
#
#   bash dense/bench.sh --name NAME [--binary BUILD_DIR] [--settings FILE]
#                       [--max-iter N] [--heatmap] [--input netlist|placed]
#                       [--bench DIR] [--expect-placement PLACE_DIR] [--seed N]
#                       [--freq MHZ]
#
# --freq MHZ is the clock target, 100 unless given. The placer is timing-driven,
# so another target is another placement: --expect-placement must then name a
# placement dense/place.sh made at the same --freq.
#
# --heatmap adds --set router2/heatmap=heat: after each iteration the run
# directory gets heat_iterN_by_{type,xy,net}.csv, where the overuse is (a
# build from 5186cac on; it changes no routing).
#
# THE PLACEMENT is the same in every run, and each run shows it:
#   --input netlist (the default) places and routes DIR/netlist.json in one
#     process, as the unmodified runs of 2026-09-22/23 did. Placement is
#     deterministic (dense/LEDGER.md), so every run places identically - and
#     each run's placement trajectory, every "wirelen" line of HeAP and the
#     annealer, is compared with the frozen placement's (DIR/place.log); the
#     summary says IDENTICAL or where it first differs.
#   --input placed routes DIR/placed.json, written once by the pinned 0.9.6
#     with --no-route, with --no-pack --no-place. NOT FAITHFUL in 0.9.6: an
#     arc the in-memory flow routes is unroutable after the reload
#     (dense/LEDGER.md, 2026-09-23). Kept for the day that is fixed.
# --expect-placement PLACE_DIR compares the trajectory with a dense/place.sh
# placement's instead, for settings that move the placer: the route is then
# shown to be of the placement that was measured.
# Either way two runs differ only in the binary and the settings, which is
# what makes their curves comparable. DIR (default ~/dense-bench) holds the
# constraints (placed.xdc) and a PROVENANCE.txt saying from what netlist,
# binary and chip database the frozen placement was made.
#
# THE SETTINGS are a file of KEY=VALUE lines (# starts a comment), e.g.
#     router2/estimateWeight=1.25
# A router2/ key is passed as this branch's --set-route, applied after
# placement and immediately before routing - a setting added before packing
# changes the annealer's placement even when only the router reads it. Any
# other key is --set, applied after the design loads (a placed design's own
# settings are otherwise written over the command line's), and the placement
# check reports what it did. Both log what they replaced. The 0.9.6 base can
# take neither: its Python bindings do not reach ctx->settings. A NEXTPNR_
# name is set in the run's environment instead: the base's HeAP knobs for
# the 7-series (NEXTPNR_PLACER_BETA, NEXTPNR_SPREAD_SCALE_X/_Y,
# NEXTPNR_PLACER_ALPHA, xilinx/arch.cc) are read from nowhere else - its
# own assignments overwrite placerHeap/beta. The file is copied into the
# run, and what the binary says it APPLIED (the "router2 settings:" and
# "HeAP congestion knobs:" lines) is what the summary records, not the file.
#
# EACH RUN gets DIR/runs/<yyyymmdd-hhmm>-NAME/:
#   PROVENANCE.txt  binary version and hash, its BUILD-INFO, the settings file
#                   and its hash, the placement and chip database hashes, the
#                   command, every NEXTPNR_* variable passed
#   route.log       nextpnr's output, each line timestamped as it was written
#   curve.tsv       per iteration: time, minutes since routing began, wires,
#                   overused wires, total overuse
#   load.log        the box's load average and free memory each minute:
#                   iteration TIMES depend on what else is running; the
#                   overuse per iteration should not, and that is checked by
#                   running a configuration twice, not assumed
#   summary.txt     the outcome, read from the log: converged, stopped at the
#                   cap, or failed - never from nextpnr's exit code, which is
#                   1 both for a failure and for a run stopped at --max-iter
#
# Run it detached; a route is hours:
#   setsid nohup bash dense/bench.sh --name base > /dev/null 2>&1 &
set -euo pipefail

IMAGE=${IMAGE:-cft-openxc7}
NAME=""; BIN=""; SETTINGS=""; MAX_ITER=""; INPUT=netlist; HEATMAP=0; SUMMARIZE=""; EXPECT=""; SEED=""; FREQ=100
BENCH=${BENCH:-$HOME/dense-bench}
die () { echo "FATAL: $*" >&2; exit 1; }

# The curve and the outcome, read from RUN's log. A function so that
# --summarize can read an existing run again with this version's parser; and
# with errexit off, because a run that died before its first iteration - the
# run whose summary matters most - leaves greps that find nothing (until
# 2026-09-23 that ended the script before summary.txt was written).
summarize () {
  set +e
  local START PLACEMENT OUTCOME
  START=$(grep -m1 "Running main router loop" "$RUN/route.log" | cut -d' ' -f1)
  {
    printf 'time\tminutes\titer\twires\toverused\toveruse\n'
    [ -z "$START" ] || grep -E ' iter=[0-9]+ ' "$RUN/route.log" | while read -r t rest; do
      m=$(( ( $(date -d "$t" +%s) - $(date -d "$START" +%s) ) / 60 ))
      echo "$rest" | sed -E "s/.*iter=([0-9]+) wires=([0-9]+) overused=([0-9]+) overuse=([0-9]+).*/$t\t$m\t\1\t\2\t\3\t\4/"
    done
  } > "$RUN/curve.tsv"
  # The placement, shown to be the frozen one: every "wirelen" line of HeAP
  # and the annealer, with the timestamps and elapsed times taken out.
  PLACEMENT="not checked (--input placed routes the frozen placement itself)"
  if [ "$INPUT" = netlist ]; then
    traj () { grep "wirelen" "$1" | sed -E 's/^[0-9]{4}-[0-9-]+T[0-9:]+ //; s/time = [0-9.]+s//g; s/ +$//'; }
    local REF=${EXPECT:-$BENCH}/place.log WHOSE="the frozen placement's"
    [ -z "$EXPECT" ] || WHOSE="$(basename "$EXPECT")'s"
    diff <(traj "$REF") <(traj "$RUN/route.log") > "$RUN/placement.diff"
    if [ ! -s "$RUN/placement.diff" ]; then
      PLACEMENT="IDENTICAL to $WHOSE trajectory ($(traj "$REF" | wc -l) wirelen lines)"
    else
      PLACEMENT="DIFFERS from $WHOSE at $(grep -m1 -E '^[0-9]' "$RUN/placement.diff") - see placement.diff"
    fi
  fi
  if grep -q "Router2 time" "$RUN/route.log" && ! grep -q "failed to converge" "$RUN/route.log"; then
    OUTCOME="CONVERGED ($(grep -m1 'Router2 time' "$RUN/route.log" | sed 's/.*Router2 time //'))"
  elif grep -q "failed to converge" "$RUN/route.log"; then
    OUTCOME="STOPPED: $(grep -m1 'failed to converge' "$RUN/route.log" | sed 's/.*router2: //' | cut -c1-120)"
  elif [ -f "$RUN/STOPPED" ]; then
    OUTCOME="STOPPED BY DECISION: $(cut -c1-160 "$RUN/STOPPED")"
  else
    OUTCOME="FAILED (rc $(cat "$RUN/rc" 2> /dev/null)): $(grep -m1 -E 'ERROR' "$RUN/route.log" | cut -c21-220)"
  fi
  {
    echo "$NAME: $OUTCOME"
    echo "binary     $VERSION"
    echo "placement  $PLACEMENT"
    echo "placer     $(grep -m1 'HeAP congestion knobs:' "$RUN/route.log" | sed 's/.*HeAP congestion knobs: //')"
    echo "applied    $(grep -m1 'router2 settings:' "$RUN/route.log" | sed 's/.*router2 settings: //' || echo 'NOT PRINTED - a binary without this branch')"
    echo "caps       $(grep -m1 'router2 caps:' "$RUN/route.log" | sed 's/.*router2 caps: //')"
    echo "curve      $(tail -n +2 "$RUN/curve.tsv" | awk -F'\t' '{printf "%s%s:%s@%smin", sep, $3, $6, $2; sep=" "}')"
    echo "load       $(awk '{print $3}' "$RUN/load.log" | sort -n | sed -n '1p;$p' | tr '\n' ' ' | sed 's/ $//; s/ / to /') (1-minute average over the run)"
  } > "$RUN/summary.txt"
  cat "$RUN/summary.txt"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --summarize) SUMMARIZE=${2:-}; shift 2 ;;
    --name)     NAME=${2:-}; shift 2 ;;
    --binary)   BIN=${2:-}; shift 2 ;;
    --settings) SETTINGS=${2:-}; shift 2 ;;
    --max-iter) MAX_ITER=${2:-}; shift 2 ;;
    --input)    INPUT=${2:-}; shift 2 ;;
    --heatmap)  HEATMAP=1; shift ;;
    --bench)    BENCH=${2:-}; shift 2 ;;
    --expect-placement) EXPECT=${2:-}; shift 2 ;;
    --seed)     SEED=${2:-}; shift 2 ;;
    --freq)     FREQ=${2:-}; shift 2 ;;
    *)          die "unknown option $1" ;;
  esac
done

# --summarize RUN_DIR: read an existing run again, from its own files.
if [ -n "$SUMMARIZE" ]; then
  RUN=$(readlink -f "$SUMMARIZE")
  [ -f "$RUN/route.log" ] && [ -f "$RUN/PROVENANCE.txt" ] || die "$SUMMARIZE is not a bench run directory"
  NAME=$(basename "$RUN" | sed -E 's/^[0-9]{8}-[0-9]{4}-//')
  VERSION=$(sed -n 's/^binary     //p' "$RUN/PROVENANCE.txt" | head -1)
  INPUT=$(sed -n 's/^input      \([a-z]*\):.*/\1/p' "$RUN/PROVENANCE.txt" | head -1)
  INPUT=${INPUT:-placed}      # runs before the input line routed placed.json
  EXPECT=$(sed -n 's/^expect     \(\/[^ ]*\)$/\1/p' "$RUN/PROVENANCE.txt" | head -1)
  summarize
  exit 0
fi
case "$INPUT" in
  netlist) DESIGN=netlist.json; FLOW="" ;;
  placed)  DESIGN=placed.json;  FLOW=" --no-pack --no-place" ;;
  *)       die "--input takes netlist or placed" ;;
esac
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ -n "$NAME" ] || die "--name is required"
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "--name may hold letters, digits, . _ - only"
[ -z "$MAX_ITER" ] || [[ "$MAX_ITER" =~ ^[0-9]+$ ]] || die "--max-iter takes a number"
[ -s "$BENCH/$DESIGN" ] || die "no $BENCH/$DESIGN; see DENSE.md"
[ "$INPUT" = placed ] || [ -s "$BENCH/place.log" ] || die "no $BENCH/place.log to check this run's placement against"
[ -z "$EXPECT" ] || [ -s "$EXPECT/place.log" ] || die "--expect-placement: no $EXPECT/place.log (a dense/place.sh directory)"
[ -z "$EXPECT" ] || EXPECT=$(readlink -f "$EXPECT")
[ -z "$SEED" ] || [[ "$SEED" =~ ^[0-9]+$ ]] || die "--seed takes a whole number"
[[ "$FREQ" =~ ^[0-9]+$ ]] && [ "$FREQ" -ge 10 ] && [ "$FREQ" -le 500 ] || die "--freq takes a whole number of MHz from 10 to 500"
[ -s "$BENCH/placed.xdc" ] || die "no $BENCH/placed.xdc beside the placement"
[ -z "${NEXTPNR_SKIP_FAILED_ARCS:-}" ] || die "NEXTPNR_SKIP_FAILED_ARCS accepts a partial route; unset it"
BIN=$(readlink -f "${BIN:-$ROOT/build-dense}")
[ -x "$BIN/nextpnr-xilinx" ] || die "no $BIN/nextpnr-xilinx - run dense/build.sh"
[ -z "$SETTINGS" ] || [ -f "$SETTINGS" ] || die "no settings file $SETTINGS"

# The settings are read from a copy, and the copy is what the run keeps: a
# refused line stops the run before its directory exists (until 2026-09-24 a
# refusal left a directory holding only settings.txt). A value may hold
# commas, for lists such as router2/partition's grids.
SETCOPY=$(mktemp)
trap 'rm -f "$SETCOPY"' EXIT
if [ -n "$SETTINGS" ]; then cp "$SETTINGS" "$SETCOPY"
else echo "# no settings: every router2 setting at its default" > "$SETCOPY"; fi
SETARGS=""; FILEENV=()
while read -r line; do
  line=${line%%#*}; line=$(echo "$line" | tr -d '[:space:]')
  [ -n "$line" ] || continue
  [[ "$line" =~ ^[A-Za-z0-9_./-]+=[A-Za-z0-9_.,+/-]+$ ]] || die "settings line is not KEY=VALUE: '$line'"
  # A router setting goes in after placement: a setting added before packing
  # changes the annealer's placement even when only the router reads it
  # (dense/LEDGER.md, 2026-09-23). A NEXTPNR_ name is the run's environment:
  # the base reads some placer knobs from nowhere else. Anything else is
  # --set, and the placement check says what it did.
  case "$line" in
    router2/*)  SETARGS="$SETARGS --set-route $line" ;;
    NEXTPNR_ROUTER2_MAX_ITER=*) die "the iteration cap is --max-iter, not a settings line" ;;
    NEXTPNR_*)  FILEENV+=("$line") ;;
    *)          SETARGS="$SETARGS --set $line" ;;
  esac
done < "$SETCOPY"
[ "$HEATMAP" -eq 0 ] || SETARGS="$SETARGS --set-route router2/heatmap=heat"

# The run's environment: the cap, the settings file's NEXTPNR_ lines, and
# every NEXTPNR_/NPNR_ variable of the caller's - each passed and recorded
# with its value. A name both the caller and the file set is refused.
ENVARGS=()
[ -z "$MAX_ITER" ] || ENVARGS+=(-e "NEXTPNR_ROUTER2_MAX_ITER=$MAX_ITER")
for kv in ${FILEENV[@]+"${FILEENV[@]}"}; do ENVARGS+=(-e "$kv"); done
while IFS='=' read -r k v; do
  [ "$k" = NEXTPNR_ROUTER2_MAX_ITER ] && [ -n "$MAX_ITER" ] && continue
  for kv in ${FILEENV[@]+"${FILEENV[@]}"}; do
    [ "${kv%%=*}" != "$k" ] || die "$k is set both in the environment and in the settings file"
  done
  ENVARGS+=(-e "$k=$v")
done < <(env | grep -E '^(NEXTPNR|NPNR)_' || true)

RUN="$BENCH/runs/$(date +%Y%m%d-%H%M)-$NAME"
[ ! -e "$RUN" ] || die "$RUN exists"
mkdir -p "$RUN"
cp "$SETCOPY" "$RUN/settings.txt"

VERSION=$(docker run --rm -v "$BIN":/bindense:ro "$IMAGE" /bindense/nextpnr-xilinx --version 2>&1 | head -1)
CMD="nextpnr-xilinx --chipdb /opt/openxc7/chipdb/xc7k325tffg900.bin --xdc /bench/placed.xdc --json /bench/$DESIGN$FLOW --freq $FREQ --timing-allow-fail${SEED:+ --seed $SEED}$SETARGS"
{
  echo "dense bench run $NAME, $(date -Is), host $(hostname)"
  echo "bench      dense/bench.sh at $(git -C "$ROOT" describe --tags --always --dirty 2> /dev/null || echo 'no git checkout')"
  echo "binary     $VERSION"
  echo "           $BIN/nextpnr-xilinx sha256 $(sha256sum "$BIN/nextpnr-xilinx" | cut -d' ' -f1)"
  case "$VERSION" in *-dirty*) echo "           A DIRTY BUILD: this run is not a result of any commit" ;; esac
  [ -f "$BIN/BUILD-INFO.txt" ] && sed 's/^/  build-info /' "$BIN/BUILD-INFO.txt"
  echo "settings   $RUN/settings.txt sha256 $(sha256sum "$RUN/settings.txt" | cut -d' ' -f1)"
  sed 's/^/  | /' "$RUN/settings.txt"
  echo "input      $INPUT: $BENCH/$DESIGN sha256 $(sha256sum "$BENCH/$DESIGN" | cut -d' ' -f1)"
  echo "xdc        $BENCH/placed.xdc sha256 $(sha256sum "$BENCH/placed.xdc" | cut -d' ' -f1)"
  echo "chipdb     $(docker run --rm "$IMAGE" sha256sum /opt/openxc7/chipdb/xc7k325tffg900.bin | cut -d' ' -f1)"
  echo "image      $IMAGE $(docker image inspect "$IMAGE" --format '{{.Id}}' | cut -c8-19)"
  echo "command    $CMD"
  echo "expect     ${EXPECT:-the frozen placement, $BENCH/place.log}"
  echo "env        ${ENVARGS[*]:-none}"
  [ -f "$BENCH/PROVENANCE.txt" ] && sed 's/^/  placement: /' "$BENCH/PROVENANCE.txt"
} > "$RUN/PROVENANCE.txt"

( while [ ! -f "$RUN/rc" ]; do
    echo "$(date -Is) load $(cut -d' ' -f1-3 /proc/loadavg) avail $(awk '/MemAvailable/ {printf "%.1f", $2 / 1048576}' /proc/meminfo)G"
    sleep 60
  done >> "$RUN/load.log" ) &

set +e
docker run --rm --name "dense-$NAME-$$" -u "$(id -u):$(id -g)" ${ENVARGS[@]+"${ENVARGS[@]}"} \
  -v "$BIN":/bindense:ro -v "$BENCH":/bench:ro -v "$RUN":/out -w /out "$IMAGE" bash -c "
    set -o pipefail
    export PATH=/bindense:\$PATH
    $CMD 2>&1 | gawk '{ print strftime(\"%Y-%m-%dT%H:%M:%S\"), \$0; fflush() }' > /out/route.log"
echo $? > "$RUN/rc"
summarize
