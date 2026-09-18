# One target, one turn. That is the whole point of this file.
#
# Agents kept firing verifiers one at a time -- fire, wake, fire, wake -- which
# cost 89 context reprocesses in a single session for no work at all. Writing
# "do not do that" in CLAUDE.md did not stop it: two more happened within five
# minutes of the rule being committed.
#
# So the choice is removed rather than discouraged. There is no documented way
# to run "some of the verifiers". There is `make verify`, and it runs them
# together through tools/run_all.py, in parallel, in one turn.

PY  := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
RUN := $(PY) tools/run_all.py

.PHONY: help verify verify-fast verify-full controls test dag board

help:
	@echo "make verify       every fast check, in parallel, in ONE turn"
	@echo "make verify-full  adds the hour-long runs (voice full set, drums)"
	@echo "make controls     every injected defect that must turn something red"
	@echo "make test         the Python suites only"
	@echo "make board        fill the scorecard's first batch and re-render the board"
	@echo "make dag          re-run the evidence and regenerate the README diagram"

## Everything a push should run.
verify:
	@$(RUN) \
	  "$(PY) -m pytest model/ spec/ tools/ fpga/ -q" \
	  "$(PY) rtl-sketch/verify_ladder.py" \
	  "$(PY) rtl-sketch/verify_modal.py" \
	  "$(PY) rtl-sketch/verify_ctl.py" \
	  "$(PY) rtl-sketch/verify_synth_top.py" \
	  "$(PY) fpga/verify_fixture.py --outdir build/fx-base" \
	  "$(PY) rtl-sketch/verify_voice.py --set quick"

verify-fast: verify

## Adds the runs that take an hour. Still one turn.
verify-full:
	@$(RUN) --timeout 7200 \
	  "$(PY) -m pytest model/ spec/ tools/ fpga/ -q" \
	  "$(PY) rtl-sketch/verify_ladder.py" \
	  "$(PY) rtl-sketch/verify_modal.py" \
	  "$(PY) rtl-sketch/verify_ctl.py" \
	  "$(PY) rtl-sketch/verify_synth_top.py" \
	  "$(PY) fpga/verify_fixture.py --outdir build/fx-base" \
	  "$(PY) rtl-sketch/verify_voice.py --set full" \
	  "$(PY) rtl-sketch/verify_drums.py"

## Every injected control that must turn something red, together.
## A run where these do not fire is a broken run, not a quiet one.
##
## TWO CONTROLS ARE DELIBERATELY NOT HERE, and both were MEASURED, not assumed:
##
##   I2S_SWAP -- no longer discriminates at the whole-chip level. i2s_tx re-reads
##   `held` for the right slot at cycle 127; the core used to strobe its sample by
##   cycle 124 and now, with revision 10's drum section, strobes as late as 156, so
##   `held` still holds the LEFT word and the swapped stream is bit-identical to
##   the correct one. Measured both ways with verify_synth_top.py --rtl against
##   the pre-integration drum section: 124 of 256 before, 156 of 256 after, no
##   overrun either way. verify_synth_top.py prints a NOTE whenever the strobe is
##   past 128. The control still fires against i2s_tx on its own bench.
##
##   VOICE_MIX_SAT -- the voice's pre-ladder mixer never reaches its rail on this
##   patch, so the control is silent here. It is verify_voice.py's (BUGS) and
##   test_rtl.py's, and it fires there. An unsatisfiable gate is worse than no
##   gate, so it is not listed as one.
##
## NOTE the per-variant --outdir. These are several VARIANTS OF THE SAME
## verifier running concurrently, and the verifiers here write fixed filenames
## under their output directory -- so without this they would overwrite each
## other's intermediate files and the results would be meaningless in a way
## that still looks like a clean run. Any future concurrent variants of one
## verifier need the same treatment.
controls:
	@$(RUN) \
	  "$(PY) rtl-sketch/verify_ctl.py --link dr7rev1 --expect-fail --outdir build/ctl-rev1" \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_ADDR7 --expect-fail --outdir build/ctl-addr7" \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_DATA24 --expect-fail --outdir build/ctl-data24" \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_NOSEC --expect-fail --outdir build/ctl-nosec" \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_ANYLEN --expect-fail --outdir build/ctl-anylen" \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_DRAIN_LATE --expect-fail --outdir build/ctl-drainlate" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject VOICE_MASTER_PRESHIFT --expect-fail --outdir build/top-preshift" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject VOICE_DRUM_CLAMP16 --expect-fail --outdir build/top-dclamp16" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject VOICE_OUT_SAT --expect-fail --outdir build/top-outsat" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject I2S_SHIFT --expect-fail --outdir build/top-i2sshift" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject I2S_DELAY --expect-fail --outdir build/top-i2sdelay" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject SPI_ADDR7 --expect-fail --outdir build/top-addr7" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject SPI_DATA24 --expect-fail --outdir build/top-data24" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject SPI_NOSEC --expect-fail --outdir build/top-nosec" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject SPI_DRAIN_LATE --expect-fail --outdir build/top-drainlate" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject MODAL_NUM_HOLD --expect-fail --outdir build/top-numhold" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject DRUM_ENV_FLOOR --expect-fail --outdir build/top-envfloor" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject DRUM_LFSR_TAP --expect-fail --outdir build/top-lfsrtap" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject DRUM_RESET_ALIAS --expect-fail --outdir build/top-resetalias" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject DRUM_STOPS8 --expect-fail --outdir build/top-stops8" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject DRUM_BUS_STALE --expect-fail --outdir build/top-busstale" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject DRUM_DONE_NOWAIT --expect-fail --outdir build/top-nowait" \
	  "$(PY) fpga/verify_fixture.py --wrong no-coef-seq --expect-fail --outdir build/fx-nocoef" \
	  "$(PY) fpga/verify_fixture.py --wrong drop-restore --expect-fail --outdir build/fx-droprest" \
	  "$(PY) fpga/verify_fixture.py --wrong late-window --expect-fail --outdir build/fx-late" \
	  "$(PY) fpga/verify_fixture.py --wrong no-tom-bend --expect-fail --outdir build/fx-notom" \
	  "$(PY) fpga/verify_fixture.py --wrong drop-tom-step --expect-fail --outdir build/fx-tomstep" \
	  "$(PY) fpga/verify_fixture.py --wrong burst --expect-fail --outdir build/fx-burst" \
	  "$(PY) tools/run_case.py --inject REF_F0_20PCT D01A --results build/case-detune --expect fail" \
	  "$(PY) tools/run_case.py --inject REF_MISSING D01A --results build/case-noref --expect 'no verdict'"

test:
	@$(PY) -m pytest model/ spec/ tools/ fpga/ -q

dag:
	@$(PY) tools/compile_dag.py --run && $(PY) tools/compile_dag.py

## Fill the scorecard and re-render the board from what came back. The runner's
## own exit convention is 0 match / 1 mismatch / 2 no evidence, and a first
## batch that holds deliberate not-runs exits 2 by design -- so the board, not
## the status, is the report.
board:
	-@$(PY) tools/run_case.py --batch "First 32"
	@$(PY) tools/scorecard.py --markdown --readme
	@$(PY) tools/scorecard.py --check
