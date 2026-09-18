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

.PHONY: help verify verify-fast verify-full controls test dag

help:
	@echo "make verify       every fast check, in parallel, in ONE turn"
	@echo "make verify-full  adds the hour-long runs (voice full set, drums)"
	@echo "make controls     every injected defect that must turn something red"
	@echo "make test         the Python suites only"
	@echo "make dag          re-run the evidence and regenerate the README diagram"

## Everything a push should run.
verify:
	@$(RUN) \
	  "$(PY) -m pytest model/ spec/ -q" \
	  "$(PY) rtl-sketch/verify_ladder.py" \
	  "$(PY) rtl-sketch/verify_modal.py" \
	  "$(PY) rtl-sketch/verify_ctl.py" \
	  "$(PY) rtl-sketch/verify_synth_top.py" \
	  "$(PY) rtl-sketch/verify_voice.py --set quick"

verify-fast: verify

## Adds the runs that take an hour. Still one turn.
verify-full:
	@$(RUN) --timeout 7200 \
	  "$(PY) -m pytest model/ spec/ -q" \
	  "$(PY) rtl-sketch/verify_ladder.py" \
	  "$(PY) rtl-sketch/verify_modal.py" \
	  "$(PY) rtl-sketch/verify_ctl.py" \
	  "$(PY) rtl-sketch/verify_synth_top.py" \
	  "$(PY) rtl-sketch/verify_voice.py --set full" \
	  "$(PY) rtl-sketch/verify_drums.py"

## Every injected control that must turn something red, together.
## A run where these do not fire is a broken run, not a quiet one.
##
## NOTE the per-variant --outdir. These are several VARIANTS OF THE SAME
## verifier running concurrently, and the verifiers here write fixed filenames
## under their output directory -- so without this they would overwrite each
## other's intermediate files and the results would be meaningless in a way
## that still looks like a clean run. Any future concurrent variants of one
## verifier need the same treatment.
controls:
	@$(RUN) \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_ADDR7 --expect-fail --outdir build/ctl-addr7" \
	  "$(PY) rtl-sketch/verify_ctl.py --inject SPI_DATA24 --expect-fail --outdir build/ctl-data24" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject VOICE_MASTER_PRESHIFT --expect-fail --outdir build/top-preshift" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject I2S_SHIFT --expect-fail --outdir build/top-i2sshift" \
	  "$(PY) rtl-sketch/verify_synth_top.py --inject I2S_SWAP --expect-fail --outdir build/top-i2sswap"

test:
	@$(PY) -m pytest model/ spec/ -q

dag:
	@$(PY) tools/compile_dag.py --run && $(PY) tools/compile_dag.py
