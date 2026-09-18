instances 77751, area 1,673,401.0 um2 (excluding fillers: 940,239.3 um2)

cell classes over the whole die (combinational cells are renamed `_NNNNN_` by yosys and
carry no block identity, so they all land in one bucket -- that is a property of the flow,
not a measurement of synth_top's own logic):

| bucket | instances | area um2 | % of non-filler |
|---|---:|---:|---:|
| ZZ flow: filler cells | 49,200 | 733,161.7 |  |
| synth_top own + resizer-inserted | 24,817 | 715,854.7 | 76.1 |
| u_voice           (own: oscs, mixer, ADSRs, ROMs, VCA, mix) | 1,514 | 103,040.5 | 11.0 |
| u_voice.u_ladder  (ladder_dp_n, NCH=2) | 530 | 36,078.1 | 3.8 |
| u_drums.u_modal   (modal_dp_rom, 8 presets) | 385 | 26,199.7 | 2.8 |
| ZZ flow: clock tree (CTS) | 181 | 24,634.5 | 2.6 |
| u_spi             (spi_ctl) | 250 | 17,034.8 | 1.8 |
| u_drums           (drum section) | 87 | 5,920.5 | 0.6 |
| u_voice.u_div     (recip_div) | 77 | 5,239.9 | 0.6 |
| u_i2s             (i2s_tx) | 49 | 3,334.5 | 0.4 |
| ZZ flow: endcap cells | 660 | 2,897.7 | 0.3 |
| ZZ flow: antenna diode | 1 | 4.4 | 0.0 |

sequential cells only (2,925 flops, 199,137.6 um2) -- the only part of a
flattened netlist that can be attributed to a block:

| block | flops | flop area um2 | % of flops |
|---|---:|---:|---:|
| u_voice           (own: oscs, mixer, ADSRs, ROMs, VCA, mix) | 1,514 | 103,040.5 | 51.7 |
| u_voice.u_ladder  (ladder_dp_n, NCH=2) | 530 | 36,078.1 | 18.1 |
| u_drums.u_modal   (modal_dp_rom, 8 presets) | 385 | 26,199.7 | 13.2 |
| u_spi             (spi_ctl) | 250 | 17,034.8 | 8.6 |
| u_drums           (drum section) | 87 | 5,920.5 | 3.0 |
| u_voice.u_div     (recip_div) | 77 | 5,239.9 | 2.6 |
| u_i2s             (i2s_tx) | 49 | 3,334.5 | 1.7 |
| synth_top own (cyc, frame, overrun, rst sync) | 33 | 2,289.6 | 1.1 |
