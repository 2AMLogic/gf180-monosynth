# sta-corners.tcl -- post-route multi-corner STA on an ORFS result at the three 5.0 V gf180mcu corners.
# Each corner gets its own OpenRCX extraction (typ / wst / bst rules) rather than reusing the flow's
# single-corner SPEF. Run from the ORFS flow directory via run-orfs.sh; everything is printed to the
# step log ($LOG_DIR/sta_corners.log):
#   ./run-orfs.sh ladder_dp run RUN_SCRIPT=<abs path>/sta-corners.tcl RUN_LOG_NAME_STEM=sta_corners
set res  $::env(RESULTS_DIR)
set trk  $::env(TRACK_OPTION)
set libd $::env(PLATFORM_DIR)/lib
set rcxd $::env(PLATFORM_DIR)/openROAD/rcx

read_db $res/6_final.odb
define_corners tt ss ff
read_liberty -corner tt $libd/gf180mcu_fd_sc_mcu${trk}5v0__tt_025C_5v00.lib.gz
read_liberty -corner ss $libd/gf180mcu_fd_sc_mcu${trk}5v0__ss_125C_4v50.lib.gz
read_liberty -corner ff $libd/gf180mcu_fd_sc_mcu${trk}5v0__ff_n40C_5v50.lib.gz
read_sdc $res/6_final.sdc
set_propagated_clock [all_clocks]

define_process_corner -ext_model_index 0 X
foreach {c rules} {tt typ ss wst ff bst} {
  extract_parasitics -ext_model_file $rcxd/gf180mcu_1p5m_1tm_9k_sp_smim_OPTB_${rules}.rules
  write_spef $res/6_final_${c}.spef
  read_spef -corner $c $res/6_final_${c}.spef
}

set clk [lindex [all_clocks] 0]
set period [get_property -object_type clock $clk period]
puts "=== STA_CORNERS design=[[ord::get_db_block] getName] clock_period_ns=$period lib=${trk}5v0 tt_025C_5v00/ss_125C_4v50/ff_n40C_5v50 rcx=typ/wst/bst"
foreach c {tt ss ff} {
  set ws_max [worst_slack -corner $c -max]
  set ws_min [worst_slack -corner $c -min]
  set tns_max [total_negative_slack -corner $c -max]
  set tns_min [total_negative_slack -corner $c -min]
  # implied minimum period: the worst setup path would still meet at (period - WNS); an estimate, not a closure run
  set minp [expr $period - $ws_max]
  puts [format "=== CORNER %s setup_wns_ns=%+.3f setup_tns_ns=%.3f hold_wns_ns=%+.3f hold_tns_ns=%.3f implied_min_period_ns=%.2f implied_fmax_mhz=%.1f" \
    $c $ws_max $tns_max $ws_min $tns_min $minp [expr 1000.0/$minp]]
}
foreach c {tt ss ff} {
  puts "=== WORST SETUP PATH corner $c"
  report_checks -corner $c -path_delay max -group_path_count 1 -format full_clock_expanded -fields {slew cap fanout}
  puts "=== WORST HOLD PATH corner $c"
  report_checks -corner $c -path_delay min -group_path_count 1 -format full_clock_expanded
}
puts "=== CLOCK SKEW corner ss"
report_clock_skew -corner ss -setup
puts "=== DONE"
