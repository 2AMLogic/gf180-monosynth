# Raw gf180 cell-area results

Every run behind `docs/integration-area.md`. **CELL area** — a sum of liberty
`area` values for a mapped netlist. Not placed, not routed, not a die area.
gf180mcu_fd_sc_mcu7t5v0, corner `tt_025C_5v00`, PDK `gf180mcuD`, ciel
`54435919abffb937387ec956209f9cf5fd2dfbee`.

| prefix | what | regenerate |
|---|---|---|
| `repro_top_7t.*` | reproduction of `docs/area-budget.md` row G (`synth_top`, klt recipe) | `rtl-sketch/area/synth_area.py` |
| `ms_modal_m*` | `modal_dp` vs MODES and NUMS | `fpga/scripts/mode_sweep.sh` |
| `ms_kit_m*` | `drum_kit` vs MODES and NUMS | `fpga/scripts/mode_sweep.sh` |
| `ms_cfg_m*` | `mode_cfg_regs` strawman vs MODES | `fpga/scripts/mode_sweep.sh` |
| `ms_drumdp` | `drum_dp` alone | `fpga/scripts/mode_sweep.sh` |
| `x1ab_*.x1.json` | `*_1` drive strengths ALLOWED (klt's recipe) | `fpga/scripts/x1_ab.sh` |
| `x1ab_*.nox1.json` | `*_1` EXCLUDED (ORFS's stock gf180 default) | `fpga/scripts/x1_ab.sh` |
| `x1ab_excluded_cells.txt` | the 62 cells excluded in the `nox1` runs | — |

**Reading a `stat -json` file correctly.** yosys keys parameterised modules as
`$paramod$<hash>\<name>`, and the top module is **not** necessarily first.
Select by the exact `\<top>` key. Taking `modules.values()[0]` reports
`drum_kit` as 325,388 µm² when the top is 603,118 — that is `modal_dp`, a
submodule. This happened here and was caught by cross-checking against the
MODES sweep.

Every `synth_top`/`x1ab_top` result is a chip with **placeholder drums**
(`rtl-sketch/synth_top.v:81`), not `drum_kit`. Contract 17.23.

Area is not correctness: `docs/verification-rules.md` rule 3.
