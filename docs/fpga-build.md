# synth_top on an FPGA

A verified-RTL instrument is worth having before a board exists. This is the
physical half: `synth_top` through a fully open flow (yosys + nextpnr), what it
costs, and what does not fit. Run it with `make -C fpga`; every number below is
regenerated into `fpga/reports/` together with the RTL commit that produced it.

> ## The numbers in this document changed on 2026-09-18, and the old ones were wrong about what they measured
>
> Every `synth_top` FPGA figure this repository published before that date —
> including the widely quoted **27 % logic / 43 % DSP / 33.01 MHz** — was a
> chip with **placeholder drums**. `fpga/Makefile`'s `SRC` list named nine
> files and none of them were `drum_kit.v`, `drum_dp.v`, `drum_regs.v` or
> `modal_dp.v`, and `synth_top.v` at that commit (`3372e78`, branch
> `flow/fpga`) instantiated `drum_section_placeholder`.
>
> Everything below is the **joined** engine: the real drum section, the one
> `rtl-sketch/verify_drums.py` shows bit-exact against `model/drums_fx.py`.
> Where an old figure is quoted it is labelled *(placeholder, superseded)*.
> `fpga/reports/scope.txt` is the check, not the assertion.

**These are FPGA numbers and nothing else.** A clean place-and-route says
nothing about whether the instrument computes the right samples
(`docs/verification-rules.md` rule 3). Rule 3 also says to quote area only
alongside a simulation result: that result, for this exact file set, is
`fpga/reports/sim_alongside.txt` — run red first with an injected drum-path
defect, then clean. Section 8.

**Nothing here has been on a board.** No bitstream has been loaded, no audio
has come out of anything, and no frequency has been counted with an instrument.

---

## 1. What the design needs, and therefore what to target

**It uses no memory at all.** Every table — the 256×16 sine, the 129×16 `g`
table, the 33×16 `k` table, the ladder's `tanh16` — is a `$readmemh`'d `reg`
array read **combinationally**, and the modal bank holds its whole state in two
registers per mode. On gf180 that is a virtue: SRAM macros cost money and area.
On a small FPGA it is a liability, because BRAM is the resource you are *given*
and LUTs are the resource you run out of. The routed device uses **0 of 56
block RAMs** and **0 of 3,036 distributed RAM slices**.

So the design is **logic- and multiplier-bound, with its memory budget
unspendable** — and with the real drums in it, that is now much more true.

**Multipliers.** The ladder's is 24×20 and the modal bank's is 28×26; yosys
decomposes each into several MACs. The joined design asks for **14** hard
multipliers (the placeholder chip asked for 12).

---

## 2. iCE40 UP5K — does not fit, by a wide margin

`nextpnr-ice40 --up5k --package sg48`, iCEBreaker pinout, constraint
12.288 MHz. `fpga/reports/ice40_up5k.txt`, full log `fpga/build/ice40_pnr.log`.

*FPGA synthesised* (yosys technology mapping, not placed): 12,301 `SB_LUT4`,
2,044 `SB_CARRY`, 8,314 `SB_DFF*`, 14 `SB_MAC16`, **0** `SB_RAM40_4K`.

*FPGA place-and-route*, device utilisation:

| resource | used | available | | placeholder build |
|---|---:|---:|---:|---:|
| `ICESTORM_LC` | 20,252 | 5,280 | **383 %** | *163 %* |
| `ICESTORM_DSP` | 14 | 8 | **175 %** | *150 %* |
| `ICESTORM_RAM` | 0 | 30 | 0 % | *0 %* |
| `ICESTORM_SPRAM` | 0 | 4 | 0 % | *0 %* |
| `SB_GB` | 8 | 8 | 100 % | *100 %* |

It fails in placement:

```
ERROR: Unable to place cell 'u_synth.u_voice.mb_SB_MAC16_B_DSP',
       no BELs remaining to implement cell type 'ICESTORM_DSP'
```

**There is no Fmax for UP5K and no bitstream**, because there is no placed
design. Quoting one would be the same mistake as quoting a cell count for a
netlist whose outputs are X. Note again that the part's entire memory — 30 EBRs
and 1 Mbit of SPRAM, the reason most people choose a UP5K — is **completely
unused** while logic is 283 % over.

HX8K/LP8K have no `SB_MAC16` at all, so the 14 hard multipliers would become LUT
arrays; 7,680 LCs would not come close. And the UP5K's PLL cannot make this
design's clock either (section 4).

---

## 3. ECP5 LFE5U-25F — routed, with the real drums

`nextpnr-ecp5 --25k --package CABGA381`, ULX3S pinout, seed 1, wrapper
`fpga/rtl/ulx3s_top.v` (PLL included). `fpga/reports/ecp5_25f.txt`, full log
`fpga/build/ecp5_pnr.log`.

*FPGA place-and-route*, **routed, bitstream written** (`ecp5.bit`, 582,369 bytes):

| resource | used | available | | placeholder build *(superseded)* |
|---|---:|---:|---:|---:|
| `TRELLIS_COMB` (logic) | 13,792 | 24,288 | **57 %** | *27 %* |
| `TRELLIS_FF` | 8,412 | 24,288 | **35 %** | *12 %* |
| `MULT18X18D` | 14 | 28 | **50 %** | *43 %* |
| `DP16KD` (block RAM) | 0 | 56 | 0 % | *0 %* |
| `TRELLIS_RAMW` | 0 | 3,036 | 0 % | *0 %* |
| `TRELLIS_IO` | 18 | 197 | 9 % | *5 %* |
| `EHXPLLL` | **1** | 2 | 50 % | ***0 %*** |

**It fits.** Logic slightly more than doubled (×2.07) and flip-flops nearly
tripled (×2.87) when the real drums went in; the design went from a quarter of
the part to a little over half of it.

**Achieved Fmax, post-route: 30.49 MHz**, against the derived 12.29 MHz
constraint — PASS with **2.48× margin** (the placeholder build's was 33.01 MHz
and 2.69×). The report prints the post-*placement* estimate (30.30 MHz) next to
it and labels both, because nextpnr emits the line twice and the first one is
not the result.

The critical path is unchanged in character — still the ladder's multiplier:

```
u_synth.u_voice.u_ladder.mul_a_TRELLIS_FF_Q_12.Q        (ladder_dp_n.v:93)
  -> mul_r_CCU2C_..._MULT18X18D_P9                      3.93 ns logic
```

the 24×20 multiply of `ladder_dp_n.v:93–95`, decomposed by yosys into a hard
`MULT18X18D` plus a `CCU2C` carry chain. Adding the drums did **not** move the
critical path into the drum section.

### The `EHXPLLL 0/2 → 1/2` row is the other half of this build

The placeholder build's LPF asserted `FREQUENCY PORT "clk" 12.288 MHz` on a pin
carrying the ULX3S's **25 MHz** oscillator, and instantiated no PLL. It met the
constraint and would have played 1229.6 cents sharp. See section 4.

---

## 4. The clock

Full treatment in **`docs/fpga-clock.md`**. In short:

* `synth_top` is the I2S master, so `fs = f_core / 256` and the core clock *is*
  the tuning. 25 MHz straight in gives fs = 97 656.25 Hz, **+1229.6 cents**.
* `FREQUENCY PORT` is an assertion the checker verifies, not a frequency the
  board produces. `EHXPLLL: 0/2` in the old routed report is the tell.
* 12.288/25 = 1536/3125 with 3125 = 5^5 is unreachable on the EHXPLLL's primary
  output, which is why `ecppll -i 25 -o 12.288` silently answers 12.5 MHz.
* Taking the core clock off the **secondary** divider reaches
  **725/59 = 12.288135593 MHz, +11.03 ppm, +0.019 cents**, fs = 48 000.530 Hz.
  `CLKI_DIV=1, CLKFB_DIV=1, CLKOP_DIV=29, CLKOS_DIV=59`, VCO 725 MHz, PFD
  25 MHz. Reproduce with `python3 fpga/scripts/pll_search.py`.
* That is **54× closer** than the ~12.2807 MHz (−594 ppm) `fpga/README.md`
  previously recorded as the best available, and it is below the board
  oscillator's own ±30 ppm — so the crystal, not the PLL, limits the tuning.
* nextpnr **derives** the core-clock constraint from the PLL instance rather
  than from the LPF. The report quotes the derivation:
  `Derived frequency constraint of 12.3 MHz for net clk_core`.
* On **iCE40** no PLL can reach it from 12 MHz (output range starts at 16 MHz);
  the board must carry a 12.288 or 24.576 MHz oscillator.

Nothing about the clock has been measured on hardware. First bring-up job:
count LRCLK against a known reference and check 48 000.53 Hz.

---

## 5. What a board must provide

Nine signal pins, no external memory of any kind.

| | what | detail |
|---|---|---|
| **clock** | 1 pin | 12.288 MHz, or a PLL that reaches it — section 4. |
| **I2S DAC**, slave | 3: BCLK, LRCLK, SDATA | Contract 13: BCLK = 64 × fs, LRCLK low = left, 16-bit MSB first, left-justified in a 32-bit slot, MSB on the second BCLK after the LRCLK edge, SDATA changing on BCLK's falling edge, same sample both channels. No MCLK, no I2C side-channel — a PCM5102A-class part strapped for no-MCLK is the intended shape. |
| **SPI host** | 4: SCK, MOSI, CS_N, MISO | DR 0007 **revision 2**: mode 0, **48-bit** transactions framed by CS_N (`{F,6'b0,SEC}`, `A[7:0]`, `D[31:0]`), SCK ≤ f_core/4. Without a host the instrument powers up silent and stays silent. There is no on-chip sequencer and no default kit in RTL. |

Plus one reset. `fpga/rtl/ulx3s_top.v` also holds `wifi_gpio0` high, which the
ULX3S requires or its ESP32 boots into its bootloader and contends for shared
pins, and drives eight LEDs from an I2S sniffer so a bare board shows liveness.

**Pin sites are taken from the board vendor's own constraint file**
(`emard/ulx3s`, `doc/constraints/ulx3s_v20.lpf`), not guessed. The previous
`fpga/boards/ulx3s.lpf` had `lrclk` on **B3** and `sdata` on **C3**, which are
`audio_l[3]` and `audio_l[2]` — two bits of the on-board 3.5 mm jack's 4-bit
resistor ladder. That build would have driven raw I2S framing into the
headphone socket and put only BCLK on the header. I2S now goes to GP0/GP1/GP2
and SPI to GN0/GN1/GN2/GN3, one header block, adjacent.

### The host is not in this repository

The bass drum's 4 ms attack window and the toms' diode pitch drop are **timed
coefficient writes from the host** (`model/drums_fx.py`, contract 15.7.1) —
sequences of register writes at named frames, not settings. A USB-MIDI bridge
that loads the kit and forwards note-ons will not reproduce those two voices.
That host is deferred until the 808 is complete, so it is written against the
finished instrument. Nothing in `fpga/` depends on it.

---

## 6. Headroom: the completed 808, measured rather than estimated

Today's eight drums are 8 of the 808's 11 circuits. Completing the kit raises
`synth_top`'s `MODES` from 12 to 16 and `NUMS` from 6 to 11.
`fpga/rtl/headroom_top.v` is the same wrapper with the same PLL and those two
parameters overridden — nothing else differs — so `make -C fpga headroom`
answers the margin question with a routed number instead of an addition.
`fpga/reports/ecp5_25f_headroom.txt`.

| ECP5 25F | today (12/6) | completed 808 (16/11) | growth |
|---|---:|---:|---:|
| `TRELLIS_COMB` | 13,792 (57 %) | **14,218 (59 %)** | +426, +3.1 % |
| `TRELLIS_FF` | 8,412 (35 %) | **8,692 (36 %)** | +280, +3.3 % |
| `MULT18X18D` | 14 (50 %) | **14 (50 %)** | none |
| Fmax post-route | 30.49 MHz | **30.88 MHz** | — |

**The completed instrument still routes on a 25F with 41 % of the logic free.**
The growth is small because the extra modes add state and coefficient registers,
not another datapath: the modal bank is time-multiplexed, so `MODES` costs
registers and `NUMS` costs numerator mux width, and neither buys a multiplier.
DSP is unmoved at 50 % and remains the resource to watch — a *second* filter
datapath, not more drums, is what would push it.

### A finding that falls out of the probe, for whoever finishes the kit

At `MODES=16` the drum register map runs out of room. `drum_regs.v` decodes
mode registers at `0xC0 + 4m` for `m < MODES`, so 16 modes occupy `0xC0..0xFF`
— and `0xFF` is also the section soft reset (`drum_regs.v:58`,
`soft_rst = wr_valid && (wr_addr == 8'hFF)`, contract 15.8). That assignment is
a continuous one, outside the write decoder's `if`/`else` chain, so at
`MODES=16` a write to mode 15's `num` register would land **and** reset the
whole drum section. The headroom probe still routes — it is an area question,
and the extra modes are unpopulated — but the map needs a decision before the
kit is completed. Not fixed here: `rtl-sketch/` is the ASIC RTL and this branch
only measures it.

### The old projection, for calibration

`docs/fpga-build.md` before this revision projected the joined design by
addition and said so. Against the measurement (ECP5, *synthesised* LUT4/FF, so
apples to apples with the projection):

| | projected | measured | error |
|---|---:|---:|---:|
| LUT4 | ~11,400 | 10,804 | −5 % |
| FF | ~6,400 | 8,315 | **+30 %** |
| DSP | ~14–18 | 14 | in range |

The logic projection was good and the flip-flop projection was 30 % low —
because summing standalone blocks misses the registers the top level adds
around them (`drum_regs` alone is 2,276 FF and was not in the sum). Worth
remembering the next time an addition is offered in place of a run.

---

## 7. Where the FPGA area goes

*FPGA synthesised* — yosys technology mapping, **not** placed or routed. Blocks
are synthesised standalone, so they do not sum to the top row.
`fpga/reports/blocks.txt`, regenerated by `make -C fpga blocks`.

| block (parameters as instantiated) | iCE40 LUT4 | FF | DSP | ECP5 LUT4 | FF | DSP |
|---|---:|---:|---:|---:|---:|---:|
| **`synth_top`** (whole chip, **real drums**) | **12,301** | 8,314 | 14 | **10,804** | 8,315 | 14 |
| `voice_dp` | 4,922 | 2,214 | 8 | 3,843 | 2,215 | 8 |
| `ladder_dp_n` NCH=2 | 984 | 531 | 4 | 842 | 531 | 4 |
| `recip_div` | 229 | 77 | 0 | 258 | 77 | 0 |
| `drum_regs` E=12 P=16 M=12 | 287 | 2,276 | 0 | 336 | 2,276 | 0 |
| `spi_ctl` | 245 | 317 | 0 | 240 | 317 | 0 |
| `i2s_tx` | 40 | 49 | 0 | 147 | 49 | 0 |
| **`drum_kit`** M=12 N=6 (**in the top**) | **6,777** | 3,461 | 6 | **6,770** | 3,461 | 6 |
| `drum_dp` E=12 P=16 M=12 | 3,576 | 1,385 | 2 | 3,388 | 1,385 | 2 |
| `modal_dp` M=12 N=6 | 3,266 | 2,076 | 4 | 3,319 | 2,076 | 4 |
| `modal_dp` M=18 N=11 *(larger than this build)* | 5,830 | 3,983 | 4 | 5,942 | 3,983 | 4 |

`drum_kit` is **63 % of the ECP5 top row on its own** and `drum_regs` — pure
register file, 2,276 flip-flops — is why the FF count nearly tripled. The
voice, which used to be 82 % of the chip, is now 36 % of it.

Watch the parameters when reading this table: `modal_dp` defaults to MODES=4
NUMS=0 and `ladder_dp_n` to NCH=1, neither of which is what the design
instantiates, and an earlier draft of `fpga/scripts/blocks.sh` reported the
defaults under the right-sounding names.

---

## 8. Reproducing this, and the simulation the area is quoted alongside

```sh
make -C fpga            # srccheck, provenance, both targets, per-block breakdown
make -C fpga headroom    # the completed-808 margin (section 6)
```

`make` runs **`srccheck` first**: it asserts that the file set the Makefile
routes is byte-for-byte the tuple `rtl-sketch/verify_synth_top.py` declares as
its `SRCS`, and fails the build otherwise. The original defect was exactly that
drift between the flow's file list and the bench's, and nothing but a comment
was watching for it.

| file | what |
|---|---|
| `fpga/reports/provenance.txt` | commit SHA, blob hashes, tool versions, what is in the build, the clock |
| `fpga/reports/scope.txt` | the greps and the `srccheck` run that show the placeholder is gone |
| `fpga/reports/ecp5_25f.txt` | section 3 |
| `fpga/reports/ecp5_25f_headroom.txt` | section 6 |
| `fpga/reports/ice40_up5k.txt` | section 2 |
| `fpga/reports/blocks.txt` | section 7 |
| `fpga/reports/sim_alongside.txt` | the red-then-green pin-level comparison below |

**The simulation result.** `rtl-sketch/verify_synth_top.py --short`, on the same
ten files, sends the register writes over the SPI pins as 48-bit DR 0007 rev 2
frames, decodes the I2S wire from BCLK/LRCLK/SDATA the way a DAC does, and
compares it against `model/synth_top_model.py` with no tolerance.

* **Red first** (rule 1): `--inject MODAL_NUM_HOLD --expect-fail` — a defect in
  the **drum** path, the part the old build did not contain — fails 89 of 441
  decoded periods, first at period 243 (model 1542, wire 5913), and the bench
  correctly localises it upstream of the serialiser. Caught for the recorded
  reason, not merely with a non-zero exit.
* **Then clean**: 441 of 441 I2S periods identical to the model, both channels
  agreeing, every slot 32 BCLK, the core's own stream matching too; 170 writes
  accepted at the pin and drained, none landing in a frame the CS_N pin did not
  predict, no overrun and no queue overflow.

That is an RTL simulation, not a simulation of the routed netlist, and not a
board. What it buys is that the area figures above describe a design that
computes the model's samples — rather than a netlist that might be all X, which
this repository has quoted three times before anyone checked.
