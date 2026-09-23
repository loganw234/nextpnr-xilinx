#!/usr/bin/env bash
# Build this branch inside the cft-openxc7 toolchain image, then check it
# against the pinned binary it was forked from.
#
#   bash dense/build.sh [BUILD_DIR]        default BUILD_DIR: build-dense
#
# The image (cft-fp256's docker/Dockerfile.openxc7) carries the compiler,
# Boost, Eigen and Python that built its own nextpnr-xilinx 0.9.6 - this
# branch's base, 3fd78784 - and the chip database that binary uses.
# Building here, with the flags openXC7's toolchain builder passes
# (-DARCH=xilinx -DUSE_OPENMP=ON -DBUILD_GUI=OFF), leaves this branch's
# commits as the only difference from the binary it is compared with.
#
# The version stamped into the binary is `git describe --tags --always
# --dirty`: 0.9.6-N-g<hash>, with -dirty when the tree has uncommitted
# changes. A dirty build's results are not the results of any commit.
#
# THE CONTROL. openXC7's blinky-kc705 (demo-projects a38fb89) goes through
# the whole flow twice in the same image - with the image's own binary, and
# with this build first on PATH - and the two FASM files, nextpnr's output,
# must be identical apart from the one comment line naming the version.
# Equal FASM says this build places and routes as the pinned binary does
# wherever this branch's changes are off, and every change here is off by
# default until dense/LEDGER.md records it helping.
#
# The FASM and not the bitstream: xc7frames2bit writes the date and time
# into every .bit header, so no two bitstreams match, ever - which is also
# why the image manifest's recorded self-test hash (2471bcc7...) cannot be
# reproduced and is not compared with (dense/LEDGER.md, 2026-09-23).
set -euo pipefail

IMAGE=${IMAGE:-cft-openxc7}
JOBS=${JOBS:-8}
DEMO=${DEMO:-$HOME/dense-demo}
DEMO_SHA=a38fb89796f6f0d3d19c3c6b22ff177fae7609c2

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUILD=${1:-build-dense}
cd "$ROOT"
VERSION=$(git describe --tags --always --dirty)
COMMIT=$(git rev-parse HEAD)
mkdir -p "$BUILD"
INFO="$BUILD/BUILD-INFO.txt"

echo "== building $VERSION in $IMAGE, $JOBS jobs -> $BUILD"
docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT":/src -w /src "$IMAGE" bash -c "
  set -e
  cmake -S . -B '$BUILD' -DARCH=xilinx -DUSE_OPENMP=ON -DBUILD_GUI=OFF \
        -DCURRENT_GIT_VERSION='$VERSION' > '$BUILD/cmake.log' 2>&1
  cmake --build '$BUILD' --target nextpnr-xilinx --parallel $JOBS > '$BUILD/make.log' 2>&1
  c++ --version | head -1 > '$BUILD/compiler.txt'"
test -x "$BUILD/nextpnr-xilinx" || { echo "FATAL: no $BUILD/nextpnr-xilinx; see $BUILD/make.log" >&2; exit 1; }

[ -d "$DEMO/.git" ] || git clone --quiet https://github.com/openXC7/demo-projects.git "$DEMO"
git -C "$DEMO" checkout --quiet --detach "$DEMO_SHA"
blinky () {  # <tag> <extra PATH or empty>: the whole flow; FASM and log kept as $BUILD/control-<tag>.*
  docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT":/src:ro -v "$DEMO":/demo -w /demo/blinky-kc705 "$IMAGE" \
    bash -c "rm -f blinky.bit blinky.frames blinky.fasm blinky.json
             ${2:+export PATH=$2:\$PATH;} make > make.log 2>&1" || true
  cp "$DEMO/blinky-kc705/make.log" "$BUILD/control-$1.log"
  cp "$DEMO/blinky-kc705/blinky.fasm" "$BUILD/control-$1.fasm" 2>/dev/null || : > "$BUILD/control-$1.fasm"
  [ -s "$DEMO/blinky-kc705/blinky.bit" ] && echo "bitstream written" || echo "NO BITSTREAM - see control-$1.log"
}
fasm_sha () { grep -v '^# nextpnr-xilinx' "$1" | sha256sum | cut -c1-16; }

echo "== control: blinky-kc705 with the image's binary, then with this build"
IMG_FLOW=$(blinky image "")
FORK_FLOW=$(blinky fork "/src/$BUILD")
IMG_FASM=$(fasm_sha "$BUILD/control-image.fasm")
FORK_FASM=$(fasm_sha "$BUILD/control-fork.fasm")
# Which binary ran is read from the logs, not assumed from PATH: only this
# branch prints "router2 settings:".
WHO_IMG=$(grep -q "router2 settings:" "$BUILD/control-image.log" && echo "THIS BRANCH (wrong binary)" || echo "the image's binary")
WHO_FORK=$(grep -q "router2 settings:" "$BUILD/control-fork.log" && echo "this build" || echo "NOT THIS BUILD (wrong binary)")
if [ -s "$BUILD/control-image.fasm" ] && [ "$IMG_FASM" = "$FORK_FASM" ] \
   && [ "$WHO_IMG" = "the image's binary" ] && [ "$WHO_FORK" = "this build" ]; then
  VERDICT="MATCH - identical FASM apart from the version comment"
else
  VERDICT="DIFFERS - read control-image.* and control-fork.* beside this file"
fi
{
  echo "nextpnr-xilinx, dense branch"
  echo "version   $(docker run --rm -v "$ROOT":/src:ro "$IMAGE" "/src/$BUILD/nextpnr-xilinx" --version 2>&1 | head -1)"
  echo "commit    $COMMIT$(git diff --quiet && git diff --cached --quiet || echo ' (DIRTY TREE)')"
  echo "binary    $(sha256sum "$BUILD/nextpnr-xilinx" | cut -d' ' -f1)"
  echo "built     $(date -Is) on $(hostname), $JOBS jobs"
  echo "image     $IMAGE $(docker image inspect "$IMAGE" --format '{{.Id}}' | cut -c8-19)"
  echo "compiler  $(cat "$BUILD/compiler.txt")"
  echo "cmake     -DARCH=xilinx -DUSE_OPENMP=ON -DBUILD_GUI=OFF -DCURRENT_GIT_VERSION=$VERSION"
  echo "control   blinky-kc705, demo-projects $DEMO_SHA, the whole flow twice"
  echo "          image binary  FASM $IMG_FASM  ($WHO_IMG; $IMG_FLOW)"
  echo "          this build    FASM $FORK_FASM  ($WHO_FORK; $FORK_FLOW)"
  echo "          $VERDICT"
  echo "          (FASM hashes exclude the '# nextpnr-xilinx <version>' line; bitstreams are not"
  echo "          compared, because xc7frames2bit writes the date and time into each .bit header)"
} > "$INFO"
cat "$INFO"
