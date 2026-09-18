# synth_unsigned.tcl -- ORFS SYNTH_SCRIPT wrapper: run the stock synth.tcl, then drop the `signed`
# qualifier from port/wire declarations in the gate-level netlist it wrote.
#
# Why: yosys preserves `input wire signed [15:0] x_in` from the RTL into 1_2_yosys.v, and OpenSTA's
# Verilog reader rejects it ([ERROR STA-0171] ... syntax error). In a structural (gate-level) netlist
# signedness is a declaration attribute with no effect on connectivity, so removing it is a no-op for
# the design; the alternative would be editing verified RTL. Same trap is documented in
# gf180-polysynth/rtl/README.md ("No `signed` in any port or wire declaration").
source $::env(SCRIPTS_DIR)/synth.tcl

set nl $::env(RESULTS_DIR)/1_2_yosys.v
set fh [open $nl r]
set txt [read $fh]
close $fh
set n [regsub -all -line {^(\s*(?:input|output|inout|wire|reg)\s+)signed\s+} $txt {\1} txt]
set fh [open $nl w]
puts -nonewline $fh $txt
close $fh
puts "synth_unsigned.tcl: removed $n 'signed' qualifier(s) from $nl"
