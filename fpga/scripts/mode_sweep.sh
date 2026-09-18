#!/bin/sh
# Task: what does one resonator/filter mode of the drum section actually cost,
# configuration storage included? gf180mcu 7t, tt_025C_5v00, CELL area only --
# no placement, no routing, no utilisation assumption.
#
#   GF180_PDK_REF=<pdk>/gf180mcuD/libs.ref fpga/scripts/mode_sweep.sh
#
# Writes fpga/reports/mode_sweep.txt. Two dials are swept SEPARATELY because
# every naive sweep moves both: MODES (how many resonators) and NUMS (how many
# of them can carry a band-pass/high-pass numerator). See
# docs/integration-area.md section 3 for what the numbers mean.
set -e
cd "$(dirname "$0")/../../rtl-sketch"
q() { python3 area/synth_area.py --quiet "$@"; }
M="--chparam HR=0 --chparam OW=19"
# MODES sweep at NUMS=6 (what the shipped kit uses). MW must be 5 above 16 modes.
q --tag ms_modal_m4  --top modal_dp --chparam MODES=4  --chparam NUMS=4  $M ./modal_dp.v
for m in 8 9 11 12 14 16; do
  q --tag ms_modal_m$m --top modal_dp --chparam MODES=$m --chparam NUMS=6 $M ./modal_dp.v
done
for m in 17 18; do
  q --tag ms_modal_m$m --top modal_dp --chparam MODES=$m --chparam NUMS=11 --chparam MW=5 $M ./modal_dp.v
done
# NUMS sweep at fixed MODES=16 -- isolates the numerator cost from the state cost
q --tag ms_modal_m16n11 --top modal_dp --chparam MODES=16 --chparam NUMS=11 $M ./modal_dp.v
q --tag ms_modal_m16n16 --top modal_dp --chparam MODES=16 --chparam NUMS=16 $M ./modal_dp.v
# the whole drum section
for m in 8 11 12 14 16; do
  q --tag ms_kit_m$m --top drum_kit --chparam MODES=$m --chparam NUMS=6 ./drum_kit.v ./drum_dp.v ./modal_dp.v
done
q --tag ms_kit_m16n11 --top drum_kit --chparam MODES=16 --chparam NUMS=11 ./drum_kit.v ./drum_dp.v ./modal_dp.v
q --tag ms_kit_m18    --top drum_kit --chparam MODES=18 --chparam NUMS=11 --chparam MW=5 ./drum_kit.v ./drum_dp.v ./modal_dp.v
q --tag ms_drumdp     --top drum_dp  ./drum_dp.v
# the configuration storage that does not exist in RTL (strawman)
for m in 4 8 11 12 14 16 18; do
  q --tag ms_cfg_m$m --top mode_cfg_regs --chparam MODES=$m area/mode_cfg_regs.v
done
python3 "$(dirname "$0")/mode_report.py"
