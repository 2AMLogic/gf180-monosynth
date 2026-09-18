# synth_top: 12.288 MHz core clock = 81.38 ns (ARCHITECTURE.md section 5: 256 cycles per 48 kHz frame).
set clk_period 81.38
create_clock -name clk -period $clk_period [get_ports clk]
set_input_delay  [expr $clk_period * 0.2] -clock clk [all_inputs -no_clocks]
set_output_delay [expr $clk_period * 0.2] -clock clk [all_outputs]
