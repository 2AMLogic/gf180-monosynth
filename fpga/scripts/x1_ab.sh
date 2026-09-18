#!/bin/sh
# The DONT_USE_CELLS A/B, run locally on whichever block you name, so the
# drive-strength effect can be separated from everything else without a
# full ORFS run. Mirrors what ORFS's stock gf180 DONT_USE_CELLS does: exclude
# every *_1 drive-strength cell (the ORFS base netlist contains none).
#
#   GF180_PDK_REF=<pdk>/gf180mcuD/libs.ref fpga/scripts/x1_ab.sh
#
# Writes fpga/reports/x1_ab.txt. CELL area, gf180mcu 7t tt_025C_5v00.
# NOT placed, NOT routed. Area is not correctness.
set -e
: "${GF180_PDK_REF:?set GF180_PDK_REF to <pdk>/gf180mcuD/libs.ref}"
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$(dirname "$HERE")")"; R="$ROOT/rtl-sketch"
LIB="$GF180_PDK_REF/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib"
B="$ROOT/rtl-sketch/build/x1ab"; mkdir -p "$B"
# every *_1 cell in the library, as -dont_use arguments
grep -oE 'cell *\(gf180mcu_fd_sc_mcu7t5v0__[A-Za-z0-9_]+_1\)' "$LIB" \
  | sed 's/cell *(//; s/)//' | sort -u > "$B/x1_cells.txt"
DU=$(awk '{printf " -dont_use %s", $1}' "$B/x1_cells.txt")
echo "excluding $(wc -l < "$B/x1_cells.txt" | tr -d ' ') *_1 cells" >&2

run() { # tag variant top chparams files...
  tag="$1"; var="$2"; top="$3"; cp="$4"; shift 4
  case "$var" in
    x1)   du=""  ;;   # *_1 allowed  (klt's choice)
    nox1) du="$DU";;  # *_1 excluded (ORFS's default)
  esac
  cps=""; [ -n "$cp" ] && cps="chparam $cp $top;"
  ( cd "$R" && yosys -q -l "$B/$tag.$var.log" -p \
     "read_verilog -sv $*; $cps hierarchy -check -top $top; synth -top $top; \
      dfflibmap -liberty $LIB $du; abc -liberty $LIB $du; opt_clean -purge; \
      tee -q -o $B/$tag.$var.json stat -liberty $LIB -json -top $top" ) 2>/dev/null
}
KIT="$R/drum_kit.v $R/drum_dp.v $R/modal_dp.v"
PLH="$R/synth_top.v $R/spi_ctl.v $R/voice_dp.v $R/recip_div.v $R/ladder_dp_n.v $R/i2s_tx.v $R/modal_dp_rom.v $R/modal_coef_rom_p8.v"
for v in x1 nox1; do
  run kit12  $v drum_kit                  "-set MODES 12 -set NUMS 6" "$KIT"
  run kit8   $v drum_kit                  "-set MODES 8 -set NUMS 6"  "$KIT"
  run kit16n11 $v drum_kit                "-set MODES 16 -set NUMS 11" "$KIT"
  run plh    $v drum_section_placeholder  ""                          "$PLH"
  run top    $v synth_top                 ""                          "$PLH"
done
python3 "$HERE/x1_report.py"
