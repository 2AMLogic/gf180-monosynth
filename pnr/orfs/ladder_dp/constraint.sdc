# ladder_dp: 12.288 MHz core clock = 81.38 ns. I/O delays are 20 % of the period on the same clock.
set clk_period 81.38
create_clock -name clk -period $clk_period [get_ports clk]
set_input_delay  [expr $clk_period * 0.2] -clock clk [all_inputs -no_clocks]
set_output_delay [expr $clk_period * 0.2] -clock clk [all_outputs]
