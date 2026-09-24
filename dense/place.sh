#!/usr/bin/env bash
# One placement of the bench netlist, written out and measured: the fast loop
# for placer changes. A placement takes minutes, a routing iteration hours,
# so a placement is judged first by what the router will face.
#
#   bash dense/place.sh --name NAME [--binary BUILD_DIR] [--settings FILE]
#                       [--bench DIR]
#
# THE SETTINGS are bench.sh's KEY=VALUE lines: a NEXTPNR_ name sets the run's
# environment, anything else is --set. A router2/ key is refused - nothing is
# routed here.
#
# EACH PLACEMENT gets DIR/placements/<yyyymmdd-hhmm>-NAME/:
#   PROVENANCE.txt  bench script commit, binary version and hash, settings and
#                   their hash, input hashes, the command, every variable
#                   passed with its value
#   place.log       nextpnr's output, each line timestamped
#   placed.json     the placement (--no-route --write)
#   metrics.txt     dense/placement_metrics.py on it: how many nets cross each
#                   row and column boundary, LUTs per used slice by row band,
#                   and where each block's cells lie
#   summary.txt     the final wirelength, the iteration HeAP kept, the
#                   placement's trajectory against the frozen one, and the
#                   headline metrics
#
# Placement is deterministic, and a binary at its defaults places as the frozen
# placement did: that is checked, not assumed (the summary's trajectory line).
set -euo pipefail

IMAGE=${IMAGE:-cft-openxc7}
NAME=""; BIN=""; SETTINGS=""
BENCH=${BENCH:-$HOME/dense-bench}
die () { echo "FATAL: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    --name)     NAME=${2:-}; shift 2 ;;
    --binary)   BIN=${2:-}; shift 2 ;;
    --settings) SETTINGS=${2:-}; shift 2 ;;
    --bench)    BENCH=${2:-}; shift 2 ;;
    *)          die "unknown option $1" ;;
  esac
done
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ -n "$NAME" ] || die "--name is required"
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "--name may hold letters, digits, . _ - only"
[ -s "$BENCH/netlist.json" ] || die "no $BENCH/netlist.json; see DENSE.md"
[ -s "$BENCH/place.log" ] || die "no $BENCH/place.log to compare the trajectory with"
[ -s "$BENCH/placed.xdc" ] || die "no $BENCH/placed.xdc"
BIN=$(readlink -f "${BIN:-$ROOT/build-dense}")
[ -x "$BIN/nextpnr-xilinx" ] || die "no $BIN/nextpnr-xilinx - run dense/build.sh"
[ -z "$SETTINGS" ] || [ -f "$SETTINGS" ] || die "no settings file $SETTINGS"

SETCOPY=$(mktemp)
trap 'rm -f "$SETCOPY"' EXIT
if [ -n "$SETTINGS" ]; then cp "$SETTINGS" "$SETCOPY"
else echo "# no settings: every placer knob at its default" > "$SETCOPY"; fi
SETARGS=""; ENVARGS=()
while read -r line; do
  line=${line%%#*}; line=$(echo "$line" | tr -d '[:space:]')
  [ -n "$line" ] || continue
  [[ "$line" =~ ^[A-Za-z0-9_./-]+=[A-Za-z0-9_.,+-]+$ ]] || die "settings line is not KEY=VALUE: '$line'"
  case "$line" in
    router2/*) die "$line: nothing is routed here" ;;
    NEXTPNR_*) ENVARGS+=(-e "$line") ;;
    *)         SETARGS="$SETARGS --set $line" ;;
  esac
done < "$SETCOPY"
while IFS='=' read -r k v; do
  for kv in ${ENVARGS[@]+"${ENVARGS[@]}"}; do
    [ "${kv%%=*}" != "$k" ] || die "$k is set both in the environment and in the settings file"
  done
  ENVARGS+=(-e "$k=$v")
done < <(env | grep -E '^(NEXTPNR|NPNR)_' || true)
# the -e flags and their values interleave; drop the flags to list the values
# (an empty list is "none": until 2026-09-24 it was printed as a blank)
ENVLIST=""
for a in ${ENVARGS[@]+"${ENVARGS[@]}"}; do [ "$a" = -e ] || ENVLIST="$ENVLIST${ENVLIST:+ }$a"; done

OUT="$BENCH/placements/$(date +%Y%m%d-%H%M)-$NAME"
[ ! -e "$OUT" ] || die "$OUT exists"
mkdir -p "$OUT"
cp "$SETCOPY" "$OUT/settings.txt"
VERSION=$(docker run --rm -v "$BIN":/bindense:ro "$IMAGE" /bindense/nextpnr-xilinx --version 2>&1 | head -1)
CMD="nextpnr-xilinx --chipdb /opt/openxc7/chipdb/xc7k325tffg900.bin --xdc /bench/placed.xdc --json /bench/netlist.json --freq 100 --timing-allow-fail --no-route --write /out/placed.json$SETARGS"
{
  echo "dense placement $NAME, $(date -Is), host $(hostname)"
  echo "bench      dense/place.sh at $(git -C "$ROOT" describe --tags --always --dirty 2> /dev/null || echo 'no git checkout')"
  echo "binary     $VERSION"
  echo "           $BIN/nextpnr-xilinx sha256 $(sha256sum "$BIN/nextpnr-xilinx" | cut -d' ' -f1)"
  case "$VERSION" in *-dirty*) echo "           A DIRTY BUILD: this placement is not a result of any commit" ;; esac
  echo "settings   $OUT/settings.txt sha256 $(sha256sum "$OUT/settings.txt" | cut -d' ' -f1)"
  sed 's/^/  | /' "$OUT/settings.txt"
  echo "input      $BENCH/netlist.json sha256 $(sha256sum "$BENCH/netlist.json" | cut -d' ' -f1)"
  echo "xdc        $BENCH/placed.xdc sha256 $(sha256sum "$BENCH/placed.xdc" | cut -d' ' -f1)"
  echo "image      $IMAGE $(docker image inspect "$IMAGE" --format '{{.Id}}' | cut -c8-19)"
  echo "command    $CMD"
  echo "env        ${ENVLIST:-none}"
} > "$OUT/PROVENANCE.txt"

set +e
docker run --rm --name "dense-place-$NAME-$$" -u "$(id -u):$(id -g)" ${ENVARGS[@]+"${ENVARGS[@]}"} \
  -v "$BIN":/bindense:ro -v "$BENCH":/bench:ro -v "$OUT":/out -w /out "$IMAGE" bash -c "
    set -o pipefail
    export PATH=/bindense:\$PATH
    $CMD 2>&1 | gawk '{ print strftime(\"%Y-%m-%dT%H:%M:%S\"), \$0; fflush() }' > /out/place.log"
echo $? > "$OUT/rc"

traj () { grep "wirelen" "$1" | sed -E 's/^[0-9]{4}-[0-9-]+T[0-9:]+ //; s/time = [0-9.]+s//g; s/ +$//'; }
diff <(traj "$BENCH/place.log") <(traj "$OUT/place.log") > "$OUT/trajectory.diff"
if [ ! -s "$OUT/trajectory.diff" ]; then
  TRAJ="IDENTICAL to the frozen placement's ($(traj "$OUT/place.log" | wc -l) wirelen lines)"
else
  TRAJ="DIFFERS from the frozen placement's at $(grep -m1 -E '^[0-9]' "$OUT/trajectory.diff")"
fi
if [ -s "$OUT/placed.json" ]; then
  python3 "$ROOT/dense/placement_metrics.py" "$OUT/placed.json" 3 175 > "$OUT/metrics.txt" 2>&1
fi
{
  echo "$NAME: rc $(cat "$OUT/rc")"
  echo "binary     $VERSION"
  echo "env        ${ENVLIST:-none}"
  echo "heap       $(grep -m1 'HeAP congestion knobs' "$OUT/place.log" | sed 's/.*knobs: //') | $(grep -m1 'HeAP convergence' "$OUT/place.log" | sed 's/.*convergence: //')"
  echo "kept       $(grep -m1 'HeAP kept' "$OUT/place.log" | sed 's/.*HeAP kept //')"
  echo "wirelen    $(grep -E 'at iteration #[0-9]+: temp' "$OUT/place.log" | tail -1 | sed -E 's/.*wirelen = ([0-9]+).*/\1/') after refinement"
  echo "trajectory $TRAJ"
  grep -E '^(crossings|density|smear) ' "$OUT/metrics.txt" 2> /dev/null || true
} > "$OUT/summary.txt"
cat "$OUT/summary.txt"
