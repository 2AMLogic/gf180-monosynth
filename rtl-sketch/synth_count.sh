#!/bin/sh
# The PDK-neutral yosys cell counts the README quotes, reproducibly.
# Generic `synth` (no liberty, no -booth), then `stat`. Needs yosys on PATH.
set -e
cd "$(dirname "$0")"
count() { yosys -q -l "$2" -p "$1" >/dev/null 2>&1; grep -E '^\s+[0-9]+ +cells$' "$2" | tail -1 | awk '{print $1}'; }
L=${TMPDIR:-/tmp}/synth_count.$$
printf 'ladder_dp, 16-entry tanh  : %s cells\n'  "$(count 'read_verilog ladder_dp.v; synth -top ladder_dp; stat' $L.a)"
printf 'ladder_dp, 256-entry tanh : %s cells\n' "$(count 'read_verilog ladder_dp.v; chparam -set TANH_LOG2N 8 -set ROM_FILE "tanh256.hex" ladder_dp; synth -top ladder_dp; stat' $L.b)"
printf 'modal_dp, 4 modes         : %s cells\n'  "$(count 'read_verilog modal_dp.v; synth -top modal_dp; stat' $L.c)"
rm -f $L.a $L.b $L.c
