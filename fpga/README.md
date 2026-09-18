# synth_top on an FPGA

One command, from a clean checkout:

```sh
make -C fpga
```

That runs `srccheck`, writes provenance, runs yosys + nextpnr for two targets
and the per-block sweep, and records the RTL commit that produced them in
`fpga/reports/provenance.txt`. `make -C fpga headroom` adds the completed-808
margin probe.

**Reproduced.** With `fpga/build/` deleted *and the generated reports deleted*
— `make clean` alone is not enough, because the report targets are then still
newer than their sources and make does nothing — a full rerun regenerates
`ecp5_25f.txt`, `ecp5_25f_headroom.txt` and `blocks.txt` **byte-identically**
to the committed copies. `ice40_up5k.txt` is the copy from that rerun.

## Read this before quoting any number from here

**Every `synth_top` FPGA figure this repository published before 2026-09-18
described a chip with no drums in it.** The build on `flow/fpga` (commit
`3372e78`) listed nine source files and none of them were `drum_kit.v`,
`drum_dp.v`, `drum_regs.v` or `modal_dp.v`; `synth_top.v` at that commit
instantiated `drum_section_placeholder`. The 27 % logic / 43 % DSP /
33.01 MHz numbers are that chip's. They are not evidence about the instrument,
and they are gone from `reports/`.

What is in `reports/` now is the **joined** engine: `synth_top` +
`spi_ctl` + `voice_dp` + `recip_div` + `ladder_dp_n` + `i2s_tx` +
`drum_regs` + `drum_kit` (`drum_dp` + `modal_dp`) — the drum engine
`rtl-sketch/verify_drums.py` shows bit-exact against `model/drums_fx.py`.

The file list is not maintained by hand against a comment. `make srccheck`
asserts that the set the Makefile routes is exactly
`rtl-sketch/verify_synth_top.py`'s own `SRCS` — the set that bench elaborates
and compares against the model — and `make` runs it first. If the two drift,
the build stops. That check is what would have caught the original defect.

`reports/blocks.txt` also carries a `modal_dp M=18 N=11` row. That is **not**
in this build. The eight drums here are 8 of the 808's 11 circuits, and
finishing the kit grows the modal bank; the row is there so the headroom
question can be answered without re-deriving it.

## Targets

| target | device | wrapper | clock |
|---|---|---|---|
| `make ecp5` | ECP5 LFE5U-25F, CABGA381 (ULX3S) | `rtl/ulx3s_top.v` | **EHXPLLL, 25 MHz → 12.288136 MHz** |
| `make ice40` | iCE40 UP5K, SG48 (iCEBreaker) | `rtl/fpga_top.v` | none possible; the board must supply it |

The ECP5 wrapper is the one that has been made correct end to end: a real PLL,
real pin sites taken from the board vendor's own constraint file, and the
ESP32's GPIO0 held high as that board requires. See **docs/fpga-clock.md** —
the previous LPF asserted `FREQUENCY PORT "clk" 12.288 MHz` on a pin carrying
25 MHz with no PLL instantiated, which is a promise to the timing checker and
not a frequency on a wire.

`rtl/fpga_top.v` is the bare wrapper with no PLL, kept for the iCE40
comparison and for the ORFS/ASIC file-set parity check. It is not a board
design.

## Tools

`yosys`; `nextpnr-ecp5` + `prjtrellis` for the ECP5 target; `nextpnr-ice40` +
`icestorm` for the iCE40 target. On macOS,
`brew install yosys nextpnr-ice40 icestorm prjtrellis` gets everything except
`nextpnr-ecp5`, which has no formula and must be built from the nextpnr source
tree:

```sh
git clone --depth 1 https://github.com/YosysHQ/nextpnr
cmake -S nextpnr -B nextpnr/build -DARCH=ecp5 \
  -DTRELLIS_INSTALL_PREFIX=/opt/homebrew \
  -DPython3_EXECUTABLE=$(brew --prefix python@3.14)/bin/python3.14 \
  -DBUILD_PYTHON=OFF -DBUILD_GUI=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build nextpnr/build -j8
```

The Python pin matters — the chipdb generator imports `pytrellis`, and only the
interpreter prjtrellis was built against can import it (here, 3.14). Point
`NEXTPNR_ECP5` at the result if it is not on `PATH`. A missing tool skips its
target and says so in the report; it does not fail the build.

## What this is and is not

These are **physical** numbers: FPGA resource counts, device utilisation, and
achieved Fmax. `docs/verification-rules.md` rule 3 applies literally — a
netlist all of whose outputs are X has a resource count too.

Rule 3 also says to quote area only alongside a simulation result. The
simulation result for **this same file set at this same commit** is
`reports/sim_alongside.txt`: `rtl-sketch/verify_synth_top.py`, which drives the
register writes over the SPI pins, decodes the I2S wire the way a DAC does, and
compares it against `model/synth_top_model.py` with no tolerance — run first
with an injected drum-path defect to watch it go red, then clean.

Nothing here has been on a board. No bitstream has been loaded, nothing has
been measured with an instrument, and no audio has come out of anything. The
clock frequency in `docs/fpga-clock.md` is computed from the PLL's integer
dividers, not counted.

## What a board must provide

`synth_top` has no external memory of any kind. Every table it reads
(`sine_q256`, `g_rom128`, `k_rom32`, `tanh16`) is a `$readmemh`'d `reg` array
read **combinationally**, and the modal bank holds its whole state in two
registers per mode. No SRAM, no SDRAM, no flash beyond the configuration image.
Three things are needed:

1. **A clock** — 12.288 MHz, or a PLL that reaches it. `docs/fpga-clock.md`.
2. **An I2S DAC**, as a slave (contract section 13): BCLK = 64 x fs, LRCLK low
   = left, one 16-bit sample MSB first, left-justified in a 32-bit slot, MSB on
   the second BCLK after the LRCLK edge, SDATA changing on BCLK's falling edge,
   the same sample on both channels. Three pins, no MCLK, no I2C side-channel —
   a PCM5102A-class part strapped for no-MCLK operation is the intended shape.
   On the ULX3S these are header pins GP0/GP1/GP2. They are deliberately **not**
   the on-board 3.5 mm jack: that jack is a 4-bit resistor ladder on
   `audio_l[3:0]` = B3, C3, D3, E4, and the previous LPF put LRCLK on B3 and
   SDATA on C3 — two bits of that ladder driven with raw I2S framing.
3. **An SPI host** (DR 0007): mode 0, **48-bit** transactions framed by CS_N,
   SCK <= f_core/4. Four pins. Without a host the instrument powers up silent
   and stays silent: every coefficient, envelope and note arrives over this
   link. There is no on-chip sequencer and no default kit in RTL. **No host
   software exists in this repository yet** — see the note below.

Total: 1 clock + 1 reset + 4 SPI + 3 I2S = **9 pins**, plus 8 LEDs and
`wifi_gpio0` on the ULX3S wrapper.

## The host, which is not here

Two of this instrument's voices are not fully in the RTL. The bass drum's 4 ms
attack window and the toms' diode pitch drop are **timed coefficient writes
from the host** (`model/drums_fx.py`, contract 15.7.1) — sequences of register
writes at named frames, not settings. A USB-MIDI bridge that loads the kit and
forwards note-ons will not reproduce those voices.

That host is deliberately **not** in this branch. It is deferred until the 808
is complete (8 of 11 circuits today), so that it is written against the finished
instrument rather than this one. Nothing in `fpga/` depends on it and nothing
here claims it exists.
