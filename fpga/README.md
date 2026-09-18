# synth_top on an FPGA

One command, from a clean checkout:

```sh
make -C fpga
```

That runs yosys + nextpnr for two targets, writes `fpga/reports/`, and
records the RTL commit that produced them in `fpga/reports/provenance.txt`.

Tools: `yosys`; `nextpnr-ice40` + `icestorm` for the iCE40 target;
`nextpnr-ecp5` + `prjtrellis` for the ECP5 target. On macOS,
`brew install yosys nextpnr-ice40 icestorm prjtrellis` gets everything except
`nextpnr-ecp5`, which has no formula and must be built from the nextpnr source
tree (`cmake -DARCH=ecp5 -DTRELLIS_INSTALL_PREFIX=/opt/homebrew
-DPython3_EXECUTABLE=$(brew --prefix python@3.14)/bin/python3.14`; the Python
pin matters — the chipdb generator imports `pytrellis`, and building it against
a different interpreter segfaults). Point `NEXTPNR_ECP5` at the result if it is
not on `PATH`. A missing tool skips its target and says so in the report; it
does not fail the build.

## What this is not

These are **physical** numbers: FPGA resource counts, device utilisation, and
achieved Fmax. Nothing here is evidence that the instrument computes the right
samples. `docs/verification-rules.md` rule 3 applies literally — a netlist all
of whose outputs are X has a resource count too. Function is
`rtl-sketch/verify_*.py`'s question and is recorded separately.

## What a board must provide

`synth_top` has no external memory of any kind. Every table it reads
(`sine_q256`, `g_rom128`, `k_rom32`, `tanh16`, the modal coefficient ROM) is a
`$readmemh`'d `reg` array read **combinationally**, and the modal bank's own
comment is explicit: "there is NO DELAY LINE and no RAM: the whole state is two
registers per mode." So a board needs no SRAM, no SDRAM, no flash beyond the
configuration image. What it must provide is exactly three things:

1. **A clock.** `synth_top` wants 12.288 MHz — 256 cycles per 48 kHz frame,
   with `LRCLK = clk/256` and `BCLK = clk/4` taken as bits of the frame counter,
   not as derived clocks. The design is the **I2S master**, so it is not slaved
   to a codec: the board clock *sets* the sample rate and therefore the pitch.
   12.288 MHz gives exactly 48 kHz; anything else scales everything by the same
   ratio.

   On iCE40 the PLL cannot help: its output range starts at 16 MHz, so
   `icepll -i 12 -o 12.288` refuses outright. An iCE40 board must carry a
   12.288 MHz or 24.576 MHz oscillator; the iCEBreaker's stock 12 MHz runs the
   instrument 2.3 % flat (about 40 cents). On ECP5 the PLL can get close from a
   25 MHz reference but not exactly — 12.288/25 = 1536/3125 is not reachable
   with integer dividers — so a fractional result of ~12.2807 MHz is 47.97 kHz,
   about 1 cent flat. Audible only against a reference; recorded here rather
   than hidden.

2. **An I2S DAC**, as a slave. Contract section 13: BCLK = 64 × fs, LRCLK low =
   left, one 16-bit sample MSB first, left-justified in a 32-bit slot, MSB on
   the second BCLK after the LRCLK edge, SDATA changing on BCLK's falling edge,
   the same sample on both channels. Three output pins, no MCLK, no I2C
   configuration side-channel — a PCM5102A-class part strapped for
   no-MCLK operation is the intended shape.

3. **An SPI host** (DR 0007): mode 0, 32-bit transactions framed by CS_N,
   SCK ≤ f_core/4 (≤ 2 MHz at 12.288 MHz core, and the record says ≤ 2 MHz).
   Four pins. Without a host the instrument powers up silent and stays silent:
   every coefficient, envelope and note arrives over this link. There is no
   on-chip pattern sequencer and no default kit in RTL.

Total: 1 clock + 1 reset + 4 SPI + 3 I2S = **9 pins**.

## Targets and why

See `docs/fpga-build.md` for the measured numbers and the target decision.
