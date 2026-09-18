#!/bin/sh
# Where the FPGA area goes, per block. SYNTHESIS ONLY (yosys technology mapping
# to iCE40 and ECP5 primitives): these are NOT placed or routed, and the
# per-block numbers do not sum to the top-level number because the top level
# optimises across module boundaries.
#
# Parameters matter here and getting them wrong is the easiest mistake in this
# file: modal_dp defaults to MODES=4/NUMS=0/HR=10 and ladder_dp_n to NCH=1,
# neither of which is what the design instantiates. Every row below pins the
# parameters the instantiating module actually passes, and says so.
set -u
F="$(cd "$(dirname "$0")/.." && pwd)"; ROOT="$(cd "$F/.." && pwd)"; R="$ROOT/rtl-sketch"; B="$F/build/blocks"
mkdir -p "$B"
one() { # tag top family chparams files...
  tag="$1"; top="$2"; fam="$3"; cp="$4"; shift 4
  case "$fam" in
    ice40) cmd="synth_ice40 -top $top -dsp";;
    ecp5)  cmd="synth_ecp5 -top $top";;
  esac
  cps=""; [ -n "$cp" ] && cps="chparam $cp $top;"
  ( cd "$R" && yosys -q -l "$B/$tag.$fam.log" \
      -p "read_verilog -defer $*; $cps hierarchy -top $top; $cmd; tee -o $B/$tag.$fam.txt stat -top $top" ) 2>/dev/null
}
pull() { # tag fam
  f="$B/$1.$2.txt"; [ -f "$f" ] || { printf "%6s %6s %5s %5s %6s" - - - - -; return; }
  awk -v fam="$2" '
    fam=="ice40" && $2=="SB_LUT4"    {lut+=$1}
    fam=="ecp5"  && $2=="LUT4"       {lut+=$1}
    $2 ~ /^SB_DFF/                   {ff+=$1}
    $2 == "TRELLIS_FF"               {ff+=$1}
    $2=="SB_MAC16" || $2=="MULT18X18D" {dsp+=$1}
    $2=="SB_RAM40_4K" || $2=="DP16KD"  {bram+=$1}
    $2=="SB_CARRY" || $2=="CCU2C"      {cy+=$1}
    END {printf "%6d %6d %5d %5d %6d", lut, ff, dsp, bram, cy}' "$f"
}
TOPSRC="$F/rtl/fpga_top.v $R/synth_top.v $R/spi_ctl.v $R/voice_dp.v $R/recip_div.v $R/ladder_dp_n.v $R/i2s_tx.v $R/modal_dp_rom.v $R/modal_coef_rom_p8.v"
run_all() {
  fam="$1"
  one top       fpga_top     $fam ""                                           "$TOPSRC"
  one voice     voice_dp     $fam ""                                           "$R/voice_dp.v $R/recip_div.v $R/ladder_dp_n.v"
  one ladderN2  ladder_dp_n  $fam "-set NCH 2 -set OW 19"                      "$R/ladder_dp_n.v"
  one modalrom4 modal_dp_rom $fam "-set MODES 4 -set PRESETS 8"                "$R/modal_dp_rom.v $R/modal_coef_rom_p8.v"
  one spi       spi_ctl      $fam ""                                           "$R/spi_ctl.v"
  one i2s       i2s_tx       $fam ""                                           "$R/i2s_tx.v"
  one recip     recip_div    $fam ""                                           "$R/recip_div.v"
  one drumkit12 drum_kit     $fam "-set MODES 12 -set NUMS 6"                  "$R/drum_kit.v $R/drum_dp.v $R/modal_dp.v"
  one drumdp12  drum_dp      $fam "-set MODES 12 -set ENVS 12 -set PATHS 16"   "$R/drum_dp.v"
  one modal12n6 modal_dp     $fam "-set MODES 12 -set NUMS 6 -set HR 0 -set OW 19" "$R/modal_dp.v"
  one modal18n11 modal_dp    $fam "-set MODES 18 -set NUMS 11 -set HR 0 -set OW 19 -set MW 5" "$R/modal_dp.v"
}
run_all ice40; run_all ecp5
printf "%-26s %-34s %-34s\n" "" "--------- iCE40 UP5K ---------" "--------- ECP5 25F ---------"
printf "%-26s %6s %6s %5s %5s %6s %6s %6s %5s %5s %6s\n" "block (parameters as used)" "LUT4" "FF" "DSP" "BRAM" "CARRY" "LUT4" "FF" "DSP" "BRAM" "CCU2"
lbl() { printf "%-26s %s %s\n" "$1" "$(pull $2 ice40)" "$(pull $2 ecp5)"; }
lbl "synth_top (whole chip)"        top
lbl "  voice_dp"                    voice
lbl "    ladder_dp_n NCH=2"         ladderN2
lbl "    recip_div"                 recip
lbl "  modal_dp_rom M=4 P=8"        modalrom4
lbl "  spi_ctl"                     spi
lbl "  i2s_tx"                      i2s
lbl "drum_kit M=12 N=6 (NOT in top)" drumkit12
lbl "  drum_dp E=12 P=16 M=12"      drumdp12
lbl "  modal_dp M=12 N=6"           modal12n6
lbl "  modal_dp M=18 N=11"          modal18n11
cat <<'NOTE'

synth_top's drum section is drum_section_placeholder + a FOUR-mode modal_dp_rom.
drum_kit / drum_dp / modal_dp M=12 are the REAL drum section and are instantiated
by NO synth_top on any branch; modal_dp M=18 N=11 is the bank a complete 808
needs (docs/integration-area.md section 3).
Blocks are synthesised standalone, so they do not sum to the top-level row.
Device capacity: UP5K 5280 LC / 30 BRAM(4k) / 8 DSP ; ECP5 25F 24288 LUT / 56 BRAM(18k) / 28 DSP
FPGA numbers only. Nothing here is evidence that anything computes correctly.
NOTE
