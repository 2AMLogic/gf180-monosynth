### synth_top (base)

| Stage | instances | std-cell area (um2) | utilisation | setup WNS @tt (ns) |
|---|---|---|---|---|
| synth (yosys+ABC, DONT_USE *_1) | 59289 | 1,979,380 |  |  |
| floorplan (+ 0 (taps/endcaps not counted as std cells)) | 59289 | 1,979,380 | 58.5 % | +50.69 |
| place (+ input/output buffers, resizing) | 61120 | 1,950,350 | 57.7 % | +45.54 |
| cts (+ clock tree) | 61998 | 2,033,110 | 60.1 % | +45.26 |
| finish (incl. fillers/taps/endcaps in count; area = std cells only) | 154246 | 2,033,110 | 60.1 % | +43.59 |

| Cell class (final) | count | area (um2) |
|---|---|---|
| fill_cell | 92248 | 1,348,960.0 |
| multi_input_combinational_cell | 38419 | 1,231,910.0 |
| sequential_cell | 8298 | 564,974.0 |
| inverter | 8617 | 114,664.0 |
| clock_buffer | 689 | 78,035.0 |
| tap_cell | 4239 | 18,610.9 |
| timing_repair_buffer | 609 | 16,064.5 |
| clock_inverter | 189 | 4,728.5 |
| endcap_cell | 938 | 4,118.2 |

- die area **3,464,960 um2** (1861.4 x 1861.4 um, aspect 1), core area **3,382,070 um2**
- final std-cell area 2,033,110 um2 = 60.1 % of core; die / synth cell area = 1.75, core / synth cell area = 1.71
- routed wirelength 3,362,120 um, detailed-route DRC errors 0, antenna violating nets 0, antenna diodes 0
- finish (tt_025C_5v00, RCX typ): setup WNS +43.592 ns, hold WNS +0.600 ns, TNS 0/0, setup/hold violations 0/0, max slew/cap violations 0/2, clock skew 0.212 ns, ORFS fmax 26.5 MHz, power 143.54 mW
- multi-corner STA on the routed design (`sta-corners.tcl`, per-corner OpenRCX):
  - **tt_025C_5v00**: setup WNS +43.592 ns (TNS 0.000), hold WNS +0.600 ns (TNS 0.000); implied min period 37.79 ns (26.5 MHz)
  - **ss_125C_4v50**: setup WNS +10.173 ns (TNS 0.000), hold WNS +1.140 ns (TNS 0.000); implied min period 71.21 ns (14.0 MHz)
  - **ff_n40C_5v50**: setup WNS +58.055 ns (TNS 0.000), hold WNS +0.363 ns (TNS 0.000); implied min period 23.32 ns (42.9 MHz)
- synth cell mix (top 8 of 51 types): 8540x clkinv_2, 8298x dffq_2, 6124x and2_2, 6040x nand2_2, 4670x oai22_2, 4198x mux2_2, 2692x buf_2, 2206x aoi21_2
