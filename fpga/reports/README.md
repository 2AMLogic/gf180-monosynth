# Evidence record

Regenerate everything here with `make -C fpga` (FPGA) and
`GF180_PDK_REF=… fpga/scripts/mode_sweep.sh` (gf180 cell area).

| file | what | label |
|---|---|---|
| `provenance.txt` | RTL commit, per-file blob hashes, tool versions, constraint | — |
| `ice40_up5k.txt` | iCE40 UP5K: does not fit, 163 % logic / 150 % DSP | *FPGA* |
| `ecp5_25f.txt` | ECP5 25F: routed, 27 % logic, Fmax 33.01 MHz post-route | *FPGA* |
| `blocks.txt` | per-block resource breakdown, both families, synthesis only | *FPGA synthesized* |
| `mode_sweep.txt` | `modal_dp` / `drum_kit` / config-storage area vs MODES and NUMS | *cell* |
| `x1_ab.txt` | `DONT_USE_CELLS` A/B per block, incl. `drum_kit` at 8/12/16 modes | *cell* |
| `mode_census.txt` | what the shipped kit actually occupies in the bank | — |
| `logs/` | the nextpnr logs verbatim, and the tails of the yosys logs | — |
| `../../pnr/orfs/evidence/` | the ORFS `DONT_USE_CELLS` A/B run, verbatim | *synthesized cell* |
| `../../rtl-sketch/area/results/` | every gf180 cell-area run's `result.json` | *cell* |

Read the labels. *cell* is a sum of liberty areas; *synthesized* is a mapped
netlist's area; *routed* is after place-and-route; *FPGA* is none of those.
This repository has conflated them before.

Every `synth_top` figure in here is a **placeholder-drums** chip —
`rtl-sketch/synth_top.v:81` instantiates `drum_section_placeholder`, not
`drum_kit`, and no `synth_top` on any branch instantiates the real drum section
(contract 17.23). `x1_ab.txt` measures both sides of that swap.

**None of it is evidence that the design computes anything.**
