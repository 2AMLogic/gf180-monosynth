# `synth_top` with the real drum engine does not fit the quarter slot

Floorplan only. There is no placement here because there cannot be one: the design's
standard cells are larger than the die.

- RTL: `d1e5068` (`main`), `rtl-sketch/{synth_top,spi_ctl,drum_regs,drum_kit,drum_dp,modal_dp,voice_dp,recip_div,ladder_dp_n,i2s_tx}.v`
- flow: ORFS `openroad/orfs:26Q3-296-gda37dce1c`, `gf180` platform, `TRACK_OPTION=7t`, `CORNER=TC`,
  stock `DONT_USE_CELLS = *_1`
- die **1314.88 x 1317.12 um = 1,731,850 um2**, core **1,673,400 um2** (fixed input: the
  wafer.space quarter slot inside the pad ring)
- synthesized: **59,289 instances, 1,979,380 um2** of standard cells
- **utilisation 118.285 %** — measured, and the reason the flow stops here

`2_1_floorplan.json` carries all of the above as ORFS wrote it.
