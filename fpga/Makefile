# fpga/Makefile -- synth_top on an open FPGA flow (yosys + nextpnr), reproducibly.
#
#   make            everything: both targets, per-block breakdown, reports/
#   make ice40      iCE40 UP5K  (iCEBreaker / Upduino v3)
#   make ecp5       ECP5 25F    (ULX3S / OrangeCrab / Colorlight)
#   make blocks     per-block resource breakdown (synthesis only)
#   make clean
#
# Needs: yosys; nextpnr-ice40 + icestorm for ice40; nextpnr-ecp5 + prjtrellis
# for ecp5. Set NEXTPNR_ECP5 / ECPPACK if they are not on PATH.
#
# Nothing here claims the design is correct. These are AREA and TIMING numbers
# for a place-and-routed FPGA image. Whether the instrument computes the right
# samples is model/ and rtl-sketch/verify_*.py's question, not this Makefile's.

SHELL     := /bin/sh
FPGA      := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT      := $(abspath $(FPGA)/..)
RTL       := $(ROOT)/rtl-sketch
BUILD     := $(FPGA)/build
REPORTS   := $(FPGA)/reports

YOSYS         ?= yosys
NEXTPNR_ICE40 ?= nextpnr-ice40
ICEPACK       ?= icepack
ICETIME       ?= icetime
NEXTPNR_ECP5  ?= nextpnr-ecp5
ECPPACK       ?= ecppack

# docs/ARCHITECTURE.md section 10's file list -- the same set pnr/orfs/synth_top/config.mk
# gives ORFS, plus the board wrapper. Keep the two in step.
SRC := $(FPGA)/rtl/fpga_top.v \
       $(RTL)/synth_top.v $(RTL)/spi_ctl.v $(RTL)/voice_dp.v $(RTL)/recip_div.v \
       $(RTL)/ladder_dp_n.v $(RTL)/i2s_tx.v $(RTL)/modal_dp_rom.v $(RTL)/modal_coef_rom_p8.v

# The design is the I2S master, so this frequency is the sample rate: 12.288 MHz
# = 256 cycles x 48 kHz. It is the constraint nextpnr is asked to meet.
FREQ_MHZ  ?= 12.288

.PHONY: all ice40 ecp5 blocks clean provenance
all: provenance ice40 ecp5 blocks
	@echo "--- reports in $(REPORTS)"

$(BUILD) $(REPORTS):
	@mkdir -p $@

provenance: | $(REPORTS)
	@{ echo "# FPGA build provenance"; echo; \
	   echo "date        : $$(date -u '+%Y-%m-%dT%H:%M:%SZ')"; \
	   echo "rtl commit  : $$(git -C $(ROOT) rev-parse HEAD)"; \
	   echo "rtl branch  : $$(git -C $(ROOT) rev-parse --abbrev-ref HEAD)"; \
	   echo "tree state  : $$(git -C $(ROOT) status --porcelain -- rtl-sketch fpga/rtl fpga/scripts fpga/boards fpga/Makefile | wc -l | tr -d ' ') modified file(s) among the RTL and the flow (reports/ excluded: this file is one of them)"; \
	   echo "yosys       : $$($(YOSYS) -V 2>/dev/null | head -1)"; \
	   echo "nextpnr-ice40: $$($(NEXTPNR_ICE40) --version 2>&1 | head -1)"; \
	   echo "nextpnr-ecp5 : $$($(NEXTPNR_ECP5) --version 2>&1 | head -1)"; \
	   echo "constraint  : $(FREQ_MHZ) MHz (= 48 kHz x 256; the design is the I2S master)"; \
	   echo; echo "## source files"; for f in $(SRC); do \
	     echo "  $$(git -C $(ROOT) hash-object $$f 2>/dev/null || echo '-') $${f#$(ROOT)/}"; done; \
	 } > $(REPORTS)/provenance.txt
	@cat $(REPORTS)/provenance.txt

# ---------------------------------------------------------------- iCE40 UP5K
ice40: $(REPORTS)/ice40_up5k.txt
$(REPORTS)/ice40_up5k.txt: $(SRC) | $(BUILD) $(REPORTS)
	@mkdir -p $(BUILD)
	cd $(RTL) && $(YOSYS) -l $(BUILD)/ice40_synth.log -p \
	  'read_verilog -defer $(SRC); hierarchy -top fpga_top; \
	   synth_ice40 -top fpga_top -dsp -json $(BUILD)/ice40.json; \
	   tee -o $(BUILD)/ice40_stat.txt stat -top fpga_top'
	-cd $(BUILD) && $(NEXTPNR_ICE40) --up5k --package sg48 \
	  --json $(BUILD)/ice40.json --pcf $(FPGA)/boards/icebreaker.pcf \
	  --asc $(BUILD)/ice40.asc --freq $(FREQ_MHZ) --seed 1 \
	  --report $(BUILD)/ice40_report.json --log $(BUILD)/ice40_pnr.log 2>&1 | tail -40
	-cd $(BUILD) && test -f ice40.asc && $(ICEPACK) ice40.asc ice40.bin && $(ICETIME) -d up5k -mtr $(BUILD)/ice40_icetime.txt ice40.asc
	@$(FPGA)/scripts/report.sh ice40 > $@
	@cat $@

# ----------------------------------------------------------------- ECP5 25F
ecp5: $(REPORTS)/ecp5_25f.txt
$(REPORTS)/ecp5_25f.txt: $(SRC) | $(BUILD) $(REPORTS)
	@mkdir -p $(BUILD)
	cd $(RTL) && $(YOSYS) -l $(BUILD)/ecp5_synth.log -p \
	  'read_verilog -defer $(SRC); hierarchy -top fpga_top; \
	   synth_ecp5 -top fpga_top -json $(BUILD)/ecp5.json; \
	   tee -o $(BUILD)/ecp5_stat.txt stat -top fpga_top'
	-cd $(BUILD) && $(NEXTPNR_ECP5) --25k --package CABGA381 \
	  --json $(BUILD)/ecp5.json --lpf $(FPGA)/boards/ulx3s.lpf \
	  --textcfg $(BUILD)/ecp5.config --freq $(FREQ_MHZ) --seed 1 \
	  --report $(BUILD)/ecp5_report.json --log $(BUILD)/ecp5_pnr.log 2>&1 | tail -40
	-cd $(BUILD) && test -f ecp5.config && $(ECPPACK) ecp5.config ecp5.bit
	@$(FPGA)/scripts/report.sh ecp5 > $@
	@cat $@

# ------------------------------------------------- per-block area breakdown
blocks: $(REPORTS)/blocks.txt
$(REPORTS)/blocks.txt: $(SRC) | $(BUILD) $(REPORTS)
	$(FPGA)/scripts/blocks.sh > $@
	@cat $@

clean:
	rm -rf $(BUILD)
