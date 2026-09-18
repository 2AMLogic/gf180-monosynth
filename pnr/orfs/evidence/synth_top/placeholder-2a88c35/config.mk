# OpenROAD-flow-scripts design config: synth_top -- THE WHOLE CHIP -- on gf180mcu, 7-track, 5.0 V.
# Run with ../run-orfs.sh synth_top   (see ../README.md, docs/pnr-synth-top.md).
#
# READ THIS BEFORE QUOTING A DIE AREA.
# The die here is a FIXED INPUT, not a result: 1314.88 x 1317.12 um = 1.7319 mm^2, the
# wafer.space gf180mcu quarter slot inside the default pad ring (1.73 mm^2) that
# docs/area-budget.md budgets against, rendered as an aspect-1 rectangle on the 7t site
# grid (0.56 x 3.92 um). CORE_UTILIZATION is deliberately NOT set: setting a target
# utilisation makes the die area a restatement of the cell area divided by that target,
# which is an assumption wearing the clothes of a measurement. Here the die is fixed by
# the product and the UTILISATION IS THE MEASURED QUANTITY.
export PLATFORM        = gf180
# gf180mcu_fd_sc_mcu7t5v0 (ORFS default is 9t)
export TRACK_OPTION    = 7t
# TC = tt_025C_5v00. ORFS default is BC = ff_n40C_5v50 (optimistic); WC = ss_125C_4v50
export CORNER          = TC
export DESIGN_NAME     = synth_top
export DESIGN_NICKNAME = synth_top

DESIGN_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
RTL := $(abspath $(DESIGN_DIR)/../../../rtl-sketch)
# docs/ARCHITECTURE.md section 10's file list, the same one rtl-sketch/area/run_all.sh
# measures as top_7t.
export VERILOG_FILES   = $(RTL)/synth_top.v $(RTL)/spi_ctl.v $(RTL)/voice_dp.v $(RTL)/recip_div.v $(RTL)/ladder_dp_n.v $(RTL)/i2s_tx.v $(RTL)/modal_dp_rom.v $(RTL)/modal_coef_rom_p8.v
export VERILOG_INCLUDE_DIRS = $(RTL)
export SDC_FILE        = $(DESIGN_DIR)/constraint.sdc
# voice_dp's sine (256 x 16) / g (129 x 16) / kc (33 x 16) tables and the ladder's tanh16 are
# $readmemh'd reg arrays; yosys folds them into $mem and the default SYNTH_MEMORY_MAX_BITS=4096
# would turn them into a macro request. Allow them as logic, as every other flow here does.
export SYNTH_MEMORY_MAX_BITS = 65536

# The stock ORFS gf180 platform techmaps adders/latches to hard-coded 9t cell names; use 7t copies.
export ADDER_MAP_FILE = $(DESIGN_DIR)/../gf180_7t/cells_adders.v
export LATCH_MAP_FILE = $(DESIGN_DIR)/../gf180_7t/cells_latch.v
# OpenSTA rejects `signed` port declarations that yosys carries over from the RTL; this wrapper runs the
# stock synth.tcl and strips the qualifier from the gate-level netlist (a no-op for connectivity).
export SYNTH_SCRIPT = $(DESIGN_DIR)/../gf180_7t/synth_unsigned.tcl

export ABC_AREA          = 1
# Fixed floorplan. Die 0 0 1314.88 1317.12 = 1.7319 mm^2. Core 1293.6 x 1293.6 um = 1.6734 mm^2,
# 2310 sites x 330 rows, margin 10.64 um (19 sites) in x and 11.76 um (3 rows) in y.
export DIE_AREA          = 0 0 1314.88 1317.12
export CORE_AREA         = 10.64 11.76 1304.24 1305.36
# Measured floorplan utilisation is 55.3 % on this fixed die; global-placement target density is
# set a little above it (the resizer and CTS add 1-4 points in this platform's other runs here).
export PLACE_DENSITY     = 0.68
# The image sets LEC_CHECK=1 with a Kepler formal binary that dies with "illegal instruction" under Docker's
# amd64 emulation on Apple Silicon (CTS step, run_lec_test). Not needed for area/timing numbers.
export LEC_CHECK = 0
# Skip the static IR-drop analysis in the finish step: platforms/gf180/setRC.tcl only sets via
# resistances for CORNER=WC, so at TC analyze_power_grid aborts ([ERROR PSM-0021] zero via resistance)
# after the final DEF/ODB/SPEF/netlist are written but before report_metrics runs.
export PWR_NETS_VOLTAGES =
export GND_NETS_VOLTAGES =
