### synth_top (placeholder)

| Stage | instances | std-cell area (um2) | utilisation | setup WNS @tt (ns) |
|---|---|---|---|---|
| synth (yosys+ABC, DONT_USE *_1) | 28810 | 925,387 |  |  |
| floorplan (+ 0 (taps/endcaps not counted as std cells)) | 28810 | 925,387 | 55.3 % | +53.26 |
| place (+ input/output buffers, resizing) | 30209 | 917,291 | 54.8 % | +48.09 |
| cts (+ clock tree) | 30542 | 948,981 | 56.7 % | +48.04 |
| finish (incl. fillers/taps/endcaps in count; area = std cells only) | 77751 | 948,985 | 56.7 % | +46.39 |

| Cell class (final) | count | area (um2) |
|---|---|---|
| fill_cell | 47208 | 724,416.0 |
| multi_input_combinational_cell | 21216 | 658,202.0 |
| sequential_cell | 2925 | 199,138.0 |
| inverter | 3156 | 41,739.5 |
| clock_buffer | 255 | 29,279.6 |
| tap_cell | 1992 | 8,745.7 |
| timing_repair_buffer | 260 | 6,568.0 |
| endcap_cell | 660 | 2,897.7 |
| clock_inverter | 78 | 2,410.3 |
| antenna_cell | 1 | 4.4 |

- die area **1,731,850 um2** (1316.0 x 1316.0 um, aspect 1), core area **1,673,400 um2**
- final std-cell area 948,985 um2 = 56.7 % of core; die / synth cell area = 1.87, core / synth cell area = 1.81
- routed wirelength 1,574,795 um, detailed-route DRC errors 2, antenna violating nets 0, antenna diodes 1
- finish (tt_025C_5v00, RCX typ): setup WNS +46.391 ns, hold WNS +0.572 ns, TNS 0/0, setup/hold violations 0/0, max slew/cap violations 0/0, clock skew 0.236 ns, ORFS fmax 28.6 MHz, power 118.72 mW
- multi-corner STA on the routed design (`sta-corners.tcl`, per-corner OpenRCX):
  - **tt_025C_5v00**: setup WNS +46.391 ns (TNS 0.000), hold WNS +0.572 ns (TNS 0.000); implied min period 34.99 ns (28.6 MHz)
  - **ss_125C_4v50**: setup WNS +15.417 ns (TNS 0.000), hold WNS +1.090 ns (TNS 0.000); implied min period 65.96 ns (15.2 MHz)
  - **ff_n40C_5v50**: setup WNS +59.802 ns (TNS 0.000), hold WNS +0.344 ns (TNS 0.000); implied min period 21.58 ns (46.3 MHz)
- synth cell mix (top 8 of 47 types): 4258x and2_2, 4042x nand2_2, 3111x clkinv_2, 2925x dffq_2, 1686x addf_1, 1649x aoi21_2, 1364x addh_1, 1002x buf_2
