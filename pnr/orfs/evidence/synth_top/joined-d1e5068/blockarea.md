instances 154246, area 3,382,067.8 um2 (excluding fillers: 2,014,497.7 um2)

cell classes over the whole die (combinational cells are renamed `_NNNNN_` by yosys and
carry no block identity, so they all land in one bucket -- that is a property of the flow,
not a measurement of synth_top's own logic):

| bucket | instances | area um2 | % of non-filler |
|---|---:|---:|---:|
| synth_top own + resizer-inserted | 48,093 | 1,383,983.6 | 68.7 |
| ZZ flow: filler cells | 96,487 | 1,367,570.1 |  |
| u_dregs           (drum_regs control register file) | 2,276 | 154,884.5 | 7.7 |
| u_drums.bank      (modal_dp resonator bank) | 2,072 | 141,046.0 | 7.0 |
| u_voice           (own: oscs, mixer, ADSRs, ROMs, VCA, mix) | 1,590 | 108,212.4 | 5.4 |
| u_drums.src       (drum_dp: envelopes, paths, LFSR) | 1,367 | 93,069.9 | 4.6 |
| ZZ flow: clock tree (CTS) | 475 | 64,648.6 | 3.2 |
| u_voice.u_ladder  (ladder_dp_n, NCH=2) | 530 | 36,078.1 | 1.8 |
| u_spi             (spi_ctl) | 292 | 19,881.9 | 1.0 |
| u_voice.u_div     (recip_div) | 77 | 5,239.9 | 0.3 |
| ZZ flow: endcap cells | 938 | 4,118.2 | 0.2 |
| u_i2s             (i2s_tx) | 49 | 3,334.5 | 0.2 |

sequential cells only (8,298 flops, 564,974.2 um2) -- the only part of a
flattened netlist that can be attributed to a block:

| block | flops | flop area um2 | % of flops |
|---|---:|---:|---:|
| u_dregs           (drum_regs control register file) | 2,276 | 154,884.5 | 27.4 |
| u_drums.bank      (modal_dp resonator bank) | 2,072 | 141,046.0 | 25.0 |
| u_voice           (own: oscs, mixer, ADSRs, ROMs, VCA, mix) | 1,590 | 108,212.4 | 19.2 |
| u_drums.src       (drum_dp: envelopes, paths, LFSR) | 1,367 | 93,069.9 | 16.5 |
| u_voice.u_ladder  (ladder_dp_n, NCH=2) | 530 | 36,078.1 | 6.4 |
| u_spi             (spi_ctl) | 292 | 19,881.9 | 3.5 |
| u_voice.u_div     (recip_div) | 77 | 5,239.9 | 0.9 |
| u_i2s             (i2s_tx) | 49 | 3,334.5 | 0.6 |
| synth_top own (cyc, frame, overrun, rst sync) | 45 | 3,226.9 | 0.6 |
