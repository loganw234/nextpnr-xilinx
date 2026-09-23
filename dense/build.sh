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
# THE CONTROL. openXC7's blinky-kc705 (demo-projects a38fb89) is built
# twice in the same image: with the image's own binary, which should give
# the bitstream the image's manifest recorded when it was built (sha256
# 2471bcc7...), and with this build first on PATH. Equal bytes say this
# build places and routes as the pinned binary does wherever this
# branch's changes are off - and every change here is off by default
# until dense/LEDGER.md records it helping. The verdict is written into
# BUILD-INFO.txt beside the binary; this script does not decide for the
# reader whether a difference was intended.
set -euo pipefail

IMAGE=${IMAGE:-cft-openxc7}
JOBS=${JOBS:-8}
DEMO=${DEMO:-$HOME/dense-demo}
DEMO_SHA=a38fb89796f6f0d3d19c3c6b22ff177fae7609c2
RECORDED_BIT=2471bcc7786ce513d9a071d8fa3f7d87fb062bf90a925d6f0ed26bbfb234531f

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

# The control, image binary first: if the environment no longer
# reproduces the recorded bytes, that is said, and the comparison that
# still means something is between the two builds made here.
[ -d "$DEMO/.git" ] || git clone --quiet https://github.com/openXC7/demo-projects.git "$DEMO"
git -C "$DEMO" checkout --quiet --detach "$DEMO_SHA"
blinky () {  # <extra PATH or empty>  ->  sha256 of blinky.bit
  docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT":/src:ro -v "$DEMO":/demo -w /demo/blinky-kc705 "$IMAGE" \
    bash -c "rm -f blinky.bit blinky.frames blinky.fasm blinky.json
             ${1:+export PATH=$1:\$PATH;} make > make.log 2>&1 && sha256sum blinky.bit | cut -d' ' -f1"
}
echo "== control: blinky-kc705 with the image's binary, then with this build"
IMG_BIT=$(blinky "") || IMG_BIT="build failed"
cp "$DEMO/blinky-kc705/make.log" "$BUILD/control-image.log"
FORK_BIT=$(blinky "/src/$BUILD") || FORK_BIT="build failed"
cp "$DEMO/blinky-kc705/make.log" "$BUILD/control-fork.log"
# Which binary ran is read from the logs, not assumed from PATH: only this
# branch prints "router2 settings:".
grep -q "router2 settings:" "$BUILD/control-fork.log" \
  || FORK_BIT="NOT THIS BUILD - its log lacks this branch's 'router2 settings:' line"
if grep -q "router2 settings:" "$BUILD/control-image.log"; then
  IMG_BIT="NOT THE IMAGE BINARY - its log has this branch's 'router2 settings:' line"
fi

if [ "$FORK_BIT" = "$IMG_BIT" ] && [ "$IMG_BIT" != "build failed" ]; then
  VERDICT="MATCH - this build's bitstream equals the image binary's"
else
  VERDICT="DIFFERS - image $IMG_BIT, this build $FORK_BIT"
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
  echo "control   blinky-kc705, demo-projects $DEMO_SHA"
  echo "          recorded when the image was built  $RECORDED_BIT"
  echo "          image binary, this session         $IMG_BIT$([ "$IMG_BIT" = "$RECORDED_BIT" ] && echo '  (reproduces the record)' || echo '  (does NOT reproduce the record)')"
  echo "          this build                         $FORK_BIT"
  echo "          $VERDICT"
} > "$INFO"
cat "$INFO"
