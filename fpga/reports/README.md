# Evidence record

Regenerate everything here with `make -C fpga` (FPGA), `make -C fpga headroom`
(the completed-808 margin) and `GF180_PDK_REF=… fpga/scripts/mode_sweep.sh`
(gf180 cell area).

| file | what | label |
|---|---|---|
| `provenance.txt` | RTL commit, per-file blob hashes, tool versions, what is in the build, the clock | — |
| `scope.txt` | the greps and the `srccheck` run proving the placeholder is gone | — |
| `ecp5_25f.txt` | ECP5 25F, **real drums**: routed, 57 % logic / 35 % FF / 50 % DSP, Fmax 30.49 MHz post-route | *FPGA routed* |
| `ecp5_25f_headroom.txt` | the same design with the drum bank grown to the completed 808 (MODES=16 NUMS=11): routed, 59 % logic | *FPGA routed* |
| `ice40_up5k.txt` | iCE40 UP5K, **real drums**: does not fit, 383 % logic / 175 % DSP | *FPGA* |
| `blocks.txt` | per-block resource breakdown, both families, synthesis only | *FPGA synthesized* |
| `sim_alongside.txt` | the pin-level bit comparison against `model/synth_top_model.py` for this exact file set, red control first | *simulation* |
| `mode_sweep.txt` | `modal_dp` / `drum_kit` / config-storage area vs MODES and NUMS | *cell* |
| `x1_ab.txt` | `DONT_USE_CELLS` A/B per block, incl. `drum_kit` at 8/12/16 modes | *cell* |
| `mode_census.txt` | what the shipped kit actually occupies in the bank | — |
| `logs/` | the nextpnr logs verbatim, and the tails of the yosys logs | — |
| `../../pnr/orfs/evidence/` | the ORFS `DONT_USE_CELLS` A/B run, verbatim | *synthesized cell* |
| `../../rtl-sketch/area/results/` | every gf180 cell-area run's `result.json` | *cell* |

Read the labels. *cell* is a sum of liberty areas; *synthesized* is a mapped
netlist's area; *routed* is after place-and-route; *FPGA* is none of those.
This repository has conflated them before.

## Which figures are placeholder and which are joined

**The FPGA figures above are the JOINED chip** — `synth_top` with `drum_regs` +
`drum_kit` (`drum_dp` + `modal_dp`), the real 808 engine. They replaced a set
of figures (27 % logic, 43 % DSP, 33.01 MHz on ECP5; 163 % / 150 % on UP5K)
that described a chip with `drum_section_placeholder` in it, because
`fpga/Makefile`'s source list omitted the four drum files. `scope.txt` is the
check; `make -C fpga srccheck` is what keeps it from happening again.

**The `*cell*` figures below the line are still the placeholder chip** —
`x1_ab.txt`, `mode_sweep.txt`, `mode_census.txt` and everything under
`rtl-sketch/area/results/` and `pnr/orfs/evidence/` are gf180 records produced
by the ASIC flow, and this branch did not regenerate them. `x1_ab.txt` measures
both sides of the placeholder/`drum_kit` swap and labels them.

**None of it is evidence that the design computes anything** — except
`sim_alongside.txt`, which is the only file here that is, and which is a
simulation of the RTL rather than of a routed netlist or a board.
