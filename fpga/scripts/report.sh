#!/bin/sh
# Turn one nextpnr run into a report. Every number is labelled FPGA and says
# whether it came from synthesis (technology-mapped cell counts) or from
# place-and-route (utilisation against a real device, achieved Fmax).
set -u
F="$(cd "$(dirname "$0")/.." && pwd)"; B="$F/build"; T="$1"
case "$T" in
  ice40) DEV="iCE40 UP5K (SG48)"; PNR="$B/ice40_pnr.log"; STAT="$B/ice40_stat.txt"; BIT="$B/ice40.bin";;
  ecp5)  DEV="ECP5 LFE5U-25F (CABGA381)"; PNR="$B/ecp5_pnr.log"; STAT="$B/ecp5_stat.txt"; BIT="$B/ecp5.bit";;
esac
echo "=== $DEV : synth_top (fpga_top wrapper) ==="
echo
echo "-- FPGA synthesised (yosys technology mapping; NOT place-and-routed) --"
awk '/=== fpga_top ===/{f=1} f' "$STAT" 2>/dev/null \
  | grep -E "^[[:space:]]+[0-9]+[[:space:]]+(SB_|TRELLIS|DP16KD|MULT|CCU2|L6MUX|PFUMX)" | sed 's/^ */   /'
awk '/=== fpga_top ===/{f=1} f && /cells$/ {print "   total mapped cells:", $1; exit}' "$STAT" 2>/dev/null
echo
echo "-- FPGA place-and-route --"
if [ ! -f "$PNR" ]; then echo "  nextpnr did not run (tool missing)"; exit 0; fi
if grep -q "Device utilisation" "$PNR"; then
  echo "  device utilisation:"
  sed -n '/Device utilisation/,/^Info: Placed/p' "$PNR" | grep -E "^Info:[[:space:]]+[A-Z]" | sed 's/^Info:/   /'
fi
echo
if grep -qE "ERROR|Error:" "$PNR"; then
  echo "  RESULT: DOES NOT FIT / did not complete."
  grep -E "ERROR|Error:" "$PNR" | head -5 | sed 's/^/    /'
else
  echo "  RESULT: routed."
fi
echo
echo "  achieved Fmax (nextpnr post-route STA, typical corner):"
grep -E "Max frequency for clock" "$PNR" | tail -3 | sed 's/^Info:/   /'
grep -E "Max delay .*posedge" "$PNR" | tail -3 | sed 's/^Info:/   /'
echo
if [ -f "$BIT" ]; then echo "  bitstream: $(basename "$BIT") $(wc -c < "$BIT" | tr -d ' ') bytes"; else echo "  bitstream: none (no routed design)"; fi
echo
echo "  NOTE: this is a physical result only. It says nothing about whether the"
echo "  design computes the right samples; see docs/verification-rules.md rule 3."
