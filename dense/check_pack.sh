#!/bin/bash
# Is what the packer switches pack still the design? One cft-fp256 FMA lane
# (cft_fpfma_pipe, fp64: EXP_W=11 MAN_W=52), small enough to route, is put
# in a harness (dense/harness.py), synthesised as openXC7 does, and placed
# and routed twice by one binary: without the switches (the control) and
# with NEXTPNR_PACK_CARRY_SHARED_S and NEXTPNR_PACK_LUT_PAIRS. Each route's
# LUT contents are checked against the netlist (dense/fasm_lut_check.py)
# and its FASM is taken through fasm2frames and xc7frames2bit, which refuse
# a feature the part does not have.
#
#   bash dense/check_pack.sh RTL_DIR BUILD_DIR OUT_DIR [TILEGRID_JSON]
#
# EXTRA_ENV="NAME=VALUE ..." adds settings to the switched run only (for
# example NEXTPNR_PLACER_CELL_VALID=1), recorded in PROVENANCE.txt.
#
# RTL_DIR is a cft-fp256 checkout's rtl/ (its commit goes into OUT_DIR's
# PROVENANCE.txt); BUILD_DIR holds the nextpnr-xilinx binary under test.
set -euo pipefail
RTL=$(cd "$1" && pwd); BIN=$(cd "$2" && pwd); mkdir -p "$3"; OUT=$(cd "$3" && pwd)
TG=${4:-$HOME/dense-bench/grid/tilegrid.json}
HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE=${IMAGE:-cft-openxc7}
XDC=$RTL/../hw/openxc7/cft_pnr_harness.xdc
run () { docker run --rm -u "$(id -u):$(id -g)" -v "$RTL":/rtl:ro -v "$BIN":/bindense:ro -v "$OUT":/out -w /out "$@"; }
{
  echo "check_pack.sh at $(git -C "$HERE" describe --tags --always --dirty 2>/dev/null)"
  echo "rtl      $RTL at $(git -C "$RTL" rev-parse HEAD 2>/dev/null) (tree $(git -C "$RTL" rev-parse HEAD:rtl 2>/dev/null))"
  echo "binary   $(run "$IMAGE" /bindense/nextpnr-xilinx --version 2>&1 | head -1) sha256 $(sha256sum "$BIN/nextpnr-xilinx" | cut -d' ' -f1)"
  echo "image    $IMAGE $(docker image inspect "$IMAGE" --format '{{.Id}}' | cut -c8-19)"
  echo "extra    ${EXTRA_ENV:-none} (the switched run only)"
  echo "started  $(date -Is)"
} > "$OUT/PROVENANCE.txt"
cp "$XDC" "$OUT/harness.xdc"

run "$IMAGE" yosys -q -l ports.log -p "read_verilog -defer -sv -I /rtl /rtl/*.sv; hierarchy -top cft_fpfma_pipe -chparam EXP_W 11 -chparam MAN_W 52; proc; write_json ports.json"
python3 "$HERE/harness.py" "$OUT/ports.json" cft_fpfma_pipe "$OUT/harness.sv" clk rst_n -p EXP_W=11 -p MAN_W=52
run "$IMAGE" yosys -q -l synth.log -p "read_verilog -defer -sv -I /rtl /rtl/*.sv /out/harness.sv; hierarchy -top harness_top; synth_xilinx -flatten -abc9 -arch xc7 -top harness_top; tee -o stat.txt stat; write_json netlist.json"

for v in control packed; do
  envs=()
  if [ $v = packed ]; then
    envs=(-e NEXTPNR_PACK_CARRY_SHARED_S=1 -e NEXTPNR_PACK_LUT_PAIRS=1)
    for kv in ${EXTRA_ENV:-}; do envs+=(-e "$kv"); done
  fi
  mkdir -p "$OUT/$v"
  if run "${envs[@]}" "$IMAGE" /bindense/nextpnr-xilinx --chipdb /opt/openxc7/chipdb/xc7k325tffg900.bin \
       --xdc /out/harness.xdc --json /out/netlist.json --write /out/$v/routed.json --fasm /out/$v/out.fasm \
       --freq 100 --timing-allow-fail > "$OUT/$v/pnr.log" 2>&1; then
    echo "$v: routed; $(grep -E "NEXTPNR_PACK" "$OUT/$v/pnr.log" | cut -c7-200 | tr '\n' ' ')"
  else
    echo "$v: nextpnr FAILED, see $OUT/$v/pnr.log"; continue
  fi
  python3 "$HERE/fasm_lut_check.py" "$TG" "$OUT/netlist.json" "$OUT/$v/routed.json" "$OUT/$v/out.fasm" > "$OUT/$v/lut_check.txt" 2>&1 || true
  echo "$v: $(grep -E "VERDICT|cells checked|WRONG|shared \(" "$OUT/$v/lut_check.txt" | tr -s ' ' | tr '\n' ';')"
  if run "$IMAGE" bash -c "fasm2frames --part xc7k325tffg900-2 --db-root \$PRJXRAY_DB_DIR/kintex7 /out/$v/out.fasm > /out/$v/out.frames && xc7frames2bit --part_file \$PRJXRAY_DB_DIR/kintex7/xc7k325tffg900-2/part.yaml --part_name xc7k325tffg900-2 --frm_file /out/$v/out.frames --output_file /out/$v/out.bit" > "$OUT/$v/bit.log" 2>&1; then
    echo "$v: bitstream written ($(stat -c %s "$OUT/$v/out.bit") bytes)"
  else
    echo "$v: bitstream FAILED, see $OUT/$v/bit.log"
  fi
done
echo "finished $(date -Is)" >> "$OUT/PROVENANCE.txt"
