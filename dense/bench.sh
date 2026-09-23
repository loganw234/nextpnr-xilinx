#!/usr/bin/env bash
# One route of the frozen placement, recorded so it can be traced.
#
#   bash dense/bench.sh --name NAME [--binary BUILD_DIR] [--settings FILE]
#                       [--max-iter N] [--bench DIR]
#
# THE PLACEMENT is made once and never again: DIR/placed.json (default
# ~/dense-bench), written by the pinned 0.9.6 binary with --no-route, beside
# the constraints it was placed with (placed.xdc) and a PROVENANCE.txt saying
# from what netlist, binary and chip database. Every run routes that same
# placement (--no-pack --no-place), so two runs differ only in the binary and
# the settings - which is what makes their curves comparable.
#
# THE SETTINGS are a file of KEY=VALUE lines (# starts a comment), e.g.
#     router2/estimateWeight=1.25
# each passed as this branch's --set, which applies it AFTER the placement
# is loaded - a placed design's own settings are otherwise written over the
# command line's - and logs what it replaced. The 0.9.6 base cannot take
# them any other way: its Python bindings do not reach ctx->settings. The
# file is copied into the run, and what router2 says it APPLIED (the
# "router2 settings:" line) is what the summary records, not the file.
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
NAME=""; BIN=""; SETTINGS=""; MAX_ITER=""; BENCH=${BENCH:-$HOME/dense-bench}
die () { echo "FATAL: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    --name)     NAME=${2:-}; shift 2 ;;
    --binary)   BIN=${2:-}; shift 2 ;;
    --settings) SETTINGS=${2:-}; shift 2 ;;
    --max-iter) MAX_ITER=${2:-}; shift 2 ;;
    --bench)    BENCH=${2:-}; shift 2 ;;
    *)          die "unknown option $1" ;;
  esac
done
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ -n "$NAME" ] || die "--name is required"
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "--name may hold letters, digits, . _ - only"
[ -z "$MAX_ITER" ] || [[ "$MAX_ITER" =~ ^[0-9]+$ ]] || die "--max-iter takes a number"
[ -s "$BENCH/placed.json" ] || die "no $BENCH/placed.json - the placement is made once; see DENSE.md"
[ -s "$BENCH/placed.xdc" ] || die "no $BENCH/placed.xdc beside the placement"
[ -z "${NEXTPNR_SKIP_FAILED_ARCS:-}" ] || die "NEXTPNR_SKIP_FAILED_ARCS accepts a partial route; unset it"
BIN=$(readlink -f "${BIN:-$ROOT/build-dense}")
[ -x "$BIN/nextpnr-xilinx" ] || die "no $BIN/nextpnr-xilinx - run dense/build.sh"
[ -z "$SETTINGS" ] || [ -f "$SETTINGS" ] || die "no settings file $SETTINGS"

RUN="$BENCH/runs/$(date +%Y%m%d-%H%M)-$NAME"
[ ! -e "$RUN" ] || die "$RUN exists"
mkdir -p "$RUN"
if [ -n "$SETTINGS" ]; then cp "$SETTINGS" "$RUN/settings.txt"
else echo "# no settings: every router2 setting at its default" > "$RUN/settings.txt"; fi
SETARGS=""
while read -r line; do
  line=${line%%#*}; line=$(echo "$line" | tr -d '[:space:]')
  [ -n "$line" ] || continue
  [[ "$line" =~ ^[A-Za-z0-9_./-]+=[A-Za-z0-9_.+-]+$ ]] || die "settings line is not KEY=VALUE: '$line'"
  SETARGS="$SETARGS --set $line"
done < "$RUN/settings.txt"

VERSION=$(docker run --rm -v "$BIN":/bindense:ro "$IMAGE" /bindense/nextpnr-xilinx --version 2>&1 | head -1)
ENVARGS=()
[ -z "$MAX_ITER" ] || ENVARGS+=(-e "NEXTPNR_ROUTER2_MAX_ITER=$MAX_ITER")
while IFS='=' read -r k _; do
  [ "$k" = NEXTPNR_ROUTER2_MAX_ITER ] && [ -n "$MAX_ITER" ] && continue
  ENVARGS+=(-e "$k")
done < <(env | grep -E '^(NEXTPNR|NPNR)_' || true)
CMD="nextpnr-xilinx --chipdb /opt/openxc7/chipdb/xc7k325tffg900.bin --xdc /bench/placed.xdc --json /bench/placed.json --no-pack --no-place --freq 100 --timing-allow-fail$SETARGS"
{
  echo "dense bench run $NAME, $(date -Is), host $(hostname)"
  echo "binary     $VERSION"
  echo "           $BIN/nextpnr-xilinx sha256 $(sha256sum "$BIN/nextpnr-xilinx" | cut -d' ' -f1)"
  case "$VERSION" in *-dirty*) echo "           A DIRTY BUILD: this run is not a result of any commit" ;; esac
  [ -f "$BIN/BUILD-INFO.txt" ] && sed 's/^/  build-info /' "$BIN/BUILD-INFO.txt"
  echo "settings   $RUN/settings.txt sha256 $(sha256sum "$RUN/settings.txt" | cut -d' ' -f1)"
  sed 's/^/  | /' "$RUN/settings.txt"
  echo "placement  $BENCH/placed.json sha256 $(sha256sum "$BENCH/placed.json" | cut -d' ' -f1)"
  echo "xdc        $BENCH/placed.xdc sha256 $(sha256sum "$BENCH/placed.xdc" | cut -d' ' -f1)"
  echo "chipdb     $(docker run --rm "$IMAGE" sha256sum /opt/openxc7/chipdb/xc7k325tffg900.bin | cut -d' ' -f1)"
  echo "image      $IMAGE $(docker image inspect "$IMAGE" --format '{{.Id}}' | cut -c8-19)"
  echo "command    $CMD"
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
set -e

# The curve and the outcome, from the log.
START=$(grep -m1 "Running main router loop" "$RUN/route.log" | cut -d' ' -f1 || true)
{
  printf 'time\tminutes\titer\twires\toverused\toveruse\n'
  [ -z "$START" ] || grep -E ' iter=[0-9]+ ' "$RUN/route.log" | while read -r t rest; do
    m=$(( ( $(date -d "$t" +%s) - $(date -d "$START" +%s) ) / 60 ))
    echo "$rest" | sed -E "s/.*iter=([0-9]+) wires=([0-9]+) overused=([0-9]+) overuse=([0-9]+).*/$t\t$m\t\1\t\2\t\3\t\4/"
  done
} > "$RUN/curve.tsv"
if grep -q "Router2 time" "$RUN/route.log" && ! grep -q "failed to converge" "$RUN/route.log"; then
  OUTCOME="CONVERGED ($(grep -m1 'Router2 time' "$RUN/route.log" | sed 's/.*Router2 time //'))"
elif grep -q "failed to converge" "$RUN/route.log"; then
  OUTCOME="STOPPED: $(grep -m1 'failed to converge' "$RUN/route.log" | sed 's/.*router2: //' | cut -c1-120)"
else
  OUTCOME="FAILED (rc $(cat "$RUN/rc")): $(grep -m1 -E 'ERROR|error' "$RUN/route.log" | cut -c1-160)"
fi
{
  echo "$NAME: $OUTCOME"
  echo "binary     $VERSION"
  echo "applied    $(grep -m1 'router2 settings:' "$RUN/route.log" | sed 's/.*router2 settings: //' || echo 'NOT PRINTED - not this branch?')"
  echo "caps       $(grep -m1 'router2 caps:' "$RUN/route.log" | sed 's/.*router2 caps: //')"
  echo "curve      $(tail -n +2 "$RUN/curve.tsv" | awk -F'\t' '{printf "%s%s:%s@%smin", sep, $3, $6, $2; sep=" "}')"
  echo "load       $(awk '{print $3}' "$RUN/load.log" | sort -n | sed -n '1p;$p' | tr '\n' ' ' | sed 's/ $//; s/ / to /') (1-minute average over the run)"
} > "$RUN/summary.txt"
cat "$RUN/summary.txt"
