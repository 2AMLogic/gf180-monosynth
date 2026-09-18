#!/bin/sh
# Every cell-area row in docs/area-budget.md, reproducibly. ~5 min on a laptop.
#   GF180_PDK_REF=<pdk>/gf180mcuD/libs.ref  OSS_CAD_SUITE=...  POLYSYNTH=../../gf180-polysynth  ./run_all.sh
set -e
cd "$(dirname "$0")"
: "${POLYSYNTH:=../../../gf180-polysynth}"
A=./synth_area.py; R=..; B=../build/area; mkdir -p $B
P="$POLYSYNTH/rtl/uart_rx.v $POLYSYNTH/rtl/synth_voice.v $POLYSYNTH/rtl/synth_core.v"
python3 wrap_polysynth.py "$POLYSYNTH/rtl" $B/polysynth-wrapped
PW="$B/polysynth-wrapped/uart_rx.v $B/polysynth-wrapped/synth_voice.v $B/polysynth-wrapped/synth_core.v"
q() { $A --quiet "$@"; }
# section 1: the core, hierarchical, and the wrapped copy with every block named
for nv in 1 2 4; do q --tag core_nv${nv}_7t --top synth_core --chparam NV=$nv $P; done
q --tag core_nv4_7t_flat --top synth_core --chparam NV=4 --flatten $P
q --tag core_nv4_7t_booth --top synth_core --chparam NV=4 --booth $P
q --tag core_nv4_9t --track 9 --top synth_core --chparam NV=4 $P
q --tag core_nv1_9t --track 9 --top synth_core --chparam NV=1 $P
q --tag coreh_nv4_7t --top synth_core --chparam NV=4 $PW
# the monosynth blocks
for t in 7 9; do q --tag ladder16_${t}t --track $t --top ladder_dp $R/ladder_dp.v; q --tag modal_${t}t --track $t --top modal_dp $R/modal_dp.v; done
q --tag ladder256_7t --top ladder_dp --chparam TANH_LOG2N=8 --chparam 'ROM_FILE="tanh256.hex"' $R/ladder_dp.v
q --tag ladder16_7t_booth --top ladder_dp --booth $R/ladder_dp.v
q --tag modal_7t_booth --top modal_dp --booth $R/modal_dp.v
q --tag touch_7t --top touch_dp $R/touch_dp.v
# section 2: N filter channels on one datapath
for n in 1 2 4 8; do q --tag laddern${n}_7t --top ladder_dp_n --chparam NCH=$n $R/ladder_dp_n.v; done
# section 3: the modal bank with its coefficients in a ROM / in host registers
python3 ../gen_modal_rom.py >/dev/null
for p in 4 8 16; do q --tag modalrom_p${p}_7t --top modal_dp_rom --chparam PRESETS=$p $R/modal_dp_rom.v $R/modal_coef_rom_p$p.v; done
q --tag modalrom_p8_7t_booth --top modal_dp_rom --booth --chparam PRESETS=8 $R/modal_dp_rom.v $R/modal_coef_rom_p8.v
q --tag modalrom_p8_9t --track 9 --top modal_dp_rom --chparam PRESETS=8 $R/modal_dp_rom.v $R/modal_coef_rom_p8.v
q --tag modalregs_7t --top modal_dp_regs $R/modal_dp_regs.v
# multiplier width sweep and the drum strawman
cat > $B/mul.v <<'V'
module mul #(parameter A = 28, parameter B = 26, parameter BSIGNED = 1) (
    input wire clk, input wire signed [A-1:0] a, input wire [B-1:0] b, output reg signed [A+B-1:0] p);
    reg signed [A-1:0] ra; reg [B-1:0] rb;
    wire signed [A+B-1:0] prod = BSIGNED ? ra * $signed(rb) : ra * $signed({1'b0, rb});
    always @(posedge clk) begin ra <= a; rb <= b; p <= prod; end
endmodule
V
for w in 28:26:1 24:24:1 24:20:0 18:18:1 16:16:1; do a=${w%%:*}; r=${w#*:}; b=${r%%:*}; s=${r#*:}
  q --tag mul_${a}x${b}_7t --top mul --chparam A=$a --chparam B=$b --chparam BSIGNED=$s $B/mul.v; done
q --tag mul_28x26_booth_7t --top mul --booth --chparam A=28 --chparam B=26 --chparam BSIGNED=1 $B/mul.v
q --tag mul_24x20_booth_7t --top mul --booth --chparam A=24 --chparam B=20 --chparam BSIGNED=0 $B/mul.v
q --tag drumseq_7t --top drum_src_seq $R/drum_src_seq.v
q --tag drumseq_7t_booth --top drum_src_seq --booth $R/drum_src_seq.v
python3 - <<'PY'
import json, glob, os
for f in sorted(glob.glob('../build/area/*/result.json')):
    d = json.load(open(f)); print(f"{d['tag']:24s} {d['total_cells']:6d} cells {d['total_area_um2']:10.1f} um2  {d['total_area_um2']/1e6:.4f} mm2")
PY
