# synth_top on an FPGA

A verified-RTL instrument is worth having before a board exists. This is the
physical half: `synth_top` through a fully open flow (yosys + nextpnr), what it
costs, and what does not fit. Run it with `make -C fpga`; every number below is
regenerated into `fpga/reports/` together with the RTL commit that produced it.

> ## READ THIS BEFORE QUOTING ANY NUMBER IN THIS DOCUMENT
>
> **Every `synth_top` figure here is of a chip with PLACEHOLDER DRUMS.**
> `rtl-sketch/synth_top.v:81` instantiates `drum_section_placeholder` — eight
> trigger bits firing a decaying LFSR burst into a **four-mode**
> `modal_dp_rom`. It does **not** instantiate `drum_kit`, the real 808, and no
> `synth_top` on any branch does (contract item 17.23). The real drum section
> is *larger than the entire chip measured here*: 6,777 LUT4 against 5,885 for
> all of `synth_top` (section 7), and 603,118 µm² of gf180 cells against
> 925,387 µm² for the whole placeholder chip.
>
> So: the ECP5 result below is **"routed with placeholder drums"**, and the
> iCE40 result is **"does not fit, with placeholder drums"**. Neither is a
> number for the instrument anyone intends to ship.

**These are FPGA numbers and nothing else.** A clean place-and-route says
nothing about whether the instrument computes the right samples
(`docs/verification-rules.md` rule 3). Function is being established
separately, and this document must not be cited for it.

---

## 1. What the design needs, and therefore what to target

`synth_top` is unusual in a way that decides the target, and the decision is
the opposite of the one you would guess from its ASIC area.

**It uses no memory at all.** Every table — the 256×16 sine, the 129×16 `g`
table, the 33×16 `k` table, the ladder's `tanh16`, the modal coefficient ROM —
is a `$readmemh`'d `reg` array read **combinationally**, and the modal bank's
own header says so of its state: "there is NO DELAY LINE and no RAM: the whole
state is two registers per mode." On gf180 that is a virtue: SRAM macros cost
money and area, and the design needs none. On a small FPGA it is a liability,
because BRAM is the resource you are *given* and LUTs are the resource you run
out of. yosys confirms it directly — `memory_libmap` reports "using FF mapping"
for every table, and the routed device uses **0 of 30 block RAMs**.

So the design is **logic- and multiplier-bound, with its memory budget
unspendable**. That, not gate count, is what rules out the small parts.

**Multipliers.** The ladder's is 24×20 and the modal bank's is 28×26; yosys
decomposes each into several 16×16 MACs. The design asks for **12 hard
multipliers**.

---

## 2. iCE40 UP5K — does not fit, on two axes (placeholder drums)

`nextpnr-ice40 --up5k --package sg48`, iCEBreaker pinout,
constraint 12.288 MHz. Full log: `fpga/build/ice40_pnr.log`.

*FPGA synthesized* (yosys technology mapping, not placed):

| primitive | count |
|---|---:|
| `SB_LUT4` | 5,885 |
| `SB_CARRY` | 1,464 |
| `SB_DFF*` (all flavours) | 2,931 |
| `SB_MAC16` | 12 |
| `SB_RAM40_4K` | **0** |

*FPGA place-and-route*, device utilisation as nextpnr reports it:

| resource | used | available | |
|---|---:|---:|---:|
| `ICESTORM_LC` | 8,623 | 5,280 | **163 %** |
| `ICESTORM_DSP` | 12 | 8 | **150 %** |
| `ICESTORM_RAM` | 0 | 30 | 0 % |
| `ICESTORM_SPRAM` | 0 | 4 | 0 % |
| `SB_GB` (globals) | 8 | 8 | 100 % |
| `SB_IO` | 9 | 39 | 23 % |

It fails in placement:

```
ERROR: Unable to place cell 'u_synth.u_drums.u_modal.mr_SB_MAC16_O_DSP',
       no BELs remaining to implement cell type 'ICESTORM_DSP'
```

**There is no Fmax for UP5K and there is no bitstream**, because there is no
placed design. Quoting one would be the same mistake as quoting a cell count
for a netlist whose outputs are X.

Note what the utilisation table says about the shape of the problem: the part's
entire memory — 30 EBRs and 1 Mbit of SPRAM, the reason most people choose a
UP5K — is **completely unused**, while logic is 63 % over and DSP 50 % over.
Shrinking the design to fit would mean giving up the ROM-as-logic architecture
that makes it cheap on gf180. That is a product decision and it is not made
here.

Two further facts that matter for anyone tempted to try a nearby iCE40:

- **HX8K/LP8K have no `SB_MAC16` at all.** The 12 hard multipliers would become
  LUT arrays; 7,680 LCs would not come close.
- **The UP5K's PLL cannot make this design's clock.** Its output range starts
  at 16 MHz, so `icepll -i 12 -o 12.288` refuses. Even a UP5K that fitted would
  need a 12.288 or 24.576 MHz oscillator on the board.

---

## 3. ECP5 LFE5U-25F — the target (routed, placeholder drums)

`nextpnr-ecp5 --25k --package CABGA381`, ULX3S pinout, constraint 12.288 MHz,
seed 1. Full log: `fpga/build/ecp5_pnr.log`.

*FPGA place-and-route*, **routed, bitstream written** (`ecp5.bit`, 582,369 bytes):

| resource | used | available | |
|---|---:|---:|---:|
| `TRELLIS_COMB` (logic) | 6,677 | 24,288 | **27 %** |
| `TRELLIS_FF` | 2,932 | 24,288 | **12 %** |
| `MULT18X18D` | 12 | 28 | **43 %** |
| `DP16KD` (block RAM) | 0 | 56 | **0 %** |
| `TRELLIS_RAMW` (distributed RAM) | 0 | 3,036 | 0 % |
| `TRELLIS_IO` | 9 | 197 | 5 % |
| `EHXPLLL` | 0 | 2 | 0 % |

**Achieved Fmax, post-route: 33.01 MHz**, against the 12.288 MHz constraint —
PASS with **2.69× margin**. Read that number off the *second* "Max frequency"
line in the log, after `Routing complete.`; the first (34.33 MHz) is the
post-placement estimate and is not the result.

The critical path is 30.29 ns — 13.88 ns logic, 16.41 ns routing — and it runs
through **the ladder's multiplier**:

```
u_synth.u_voice.u_ladder.mul_a_TRELLIS_FF_Q_9.Q        (ladder_dp_n.v:93)
  -> mul_r_MULT18X18D_P9                               3.93 ns logic
  -> mul_r_CCU2C_...                                   (mul2dsp.v:150)
  -> mul_b_TRELLIS_FF_Q_11.M
```

That is the 24×20 multiply of `ladder_dp_n.v:93–95`, decomposed by yosys into a
hard `MULT18X18D` plus a `CCU2C` carry chain to assemble the partial products.
It is the same block that dominates the design on gf180, which is reassuring
about where the design's cost lives but is **not** a claim that the two flows
measure the same thing.

**Timing closes with room, and the design is a quarter full — with placeholder
drums.** Neither of those is a correctness statement, and neither is a number
for the finished instrument.

---

## 4. Recommendation

**Target ECP5 25F.** The reasons, in order:

1. It is the smallest fully-open-flow part that holds the design **as written**,
   without giving up the memory-free architecture that makes it cheap on gf180.
2. It has the multiplier count. UP5K has 8 hard MACs and the design wants 12;
   the ECP5 25F has 28.
3. **Headroom for the instrument that is actually being built.** `synth_top`
   today contains `drum_section_placeholder`, not the real 808. The drum
   section on the `drums` branch is **larger than the whole of `synth_top` as
   measured here** — 6,777 LUT4 against 5,885 — and
   `docs/integration-area.md` section 3 shows the mode count wants to grow
   beyond 12 as well. A part that is already 163 % full has nowhere to put any
   of it; a part at 27 % plausibly does. **Plausibly.** Nobody has synthesised
   the joined top, so section 7 states that as a projection and not as a fit.
4. The boards exist and are cheap: ULX3S (25F/45F/85F), OrangeCrab 25F,
   icesugar-pro, Colorlight 5A-75B/E. All are placed and routed by
   yosys + nextpnr-ecp5 + prjtrellis with no vendor tools.

**The cheap alternative that is not recommended: Gowin GW1NR-9 (Tang Nano 9K,
~$15).** 8,640 LUT4 against a design that needs 8,623 iCE40 logic cells is not
headroom, it is a coin toss, and it leaves nothing for the drum section. It is
also a third toolchain (`nextpnr-himbaechel` + apicula) that this flow has not
been run through, so the number above is an analogy, not a measurement. If
someone wants it, measure it; do not assume it.

---

## 5. What a board must provide

`synth_top` makes **no external memory assumption of any kind** — no SRAM, no
SDRAM, no flash beyond the configuration image. It needs exactly three things,
on nine pins:

| | what | detail |
|---|---|---|
| **clock** | 12.288 MHz, 1 pin | 256 cycles per 48 kHz frame. `LRCLK = clk/256` and `BCLK = clk/4` are bits of the frame counter, not derived clocks. The design is the **I2S master**, so the board clock *sets* the sample rate and the pitch — it is not slaved to a codec. 12.288 MHz gives exactly 48 kHz; anything else scales everything by that ratio. iCE40 PLLs cannot synthesise it (output range starts at 16 MHz); an ECP5 PLL from 25 MHz gets ≈12.2807 MHz, which is 47.97 kHz and about 1 cent flat. |
| **I2S DAC**, slave | 3 pins: BCLK, LRCLK, SDATA | Contract 13: BCLK = 64 × fs, LRCLK low = left, 16-bit MSB first, left-justified in a 32-bit slot, MSB on the second BCLK after the LRCLK edge, SDATA changing on BCLK's falling edge, same sample both channels. No MCLK, no I2C side-channel — a PCM5102A-class part strapped for no-MCLK is the intended shape. |
| **SPI host** | 4 pins: SCK, MOSI, CS_N, MISO | DR 0007: mode 0, 32-bit transactions framed by CS_N, SCK ≤ f_core/4 (≤ 2 MHz here). **Without a host the instrument powers up silent and stays silent** — every coefficient, envelope and note arrives over this link. There is no on-chip sequencer and no default kit in RTL. |

Plus one reset pin. `fpga/rtl/fpga_top.v` adds a power-on reset counter so a
board with no button still comes out of reset; that is the only thing the
wrapper adds.

---

## 6. Reproducing this

```sh
make -C fpga          # both targets + the per-block breakdown
```

Outputs, all committed:

| file | what |
|---|---|
| `fpga/reports/provenance.txt` | RTL commit SHA, per-file blob hashes, tool versions, the constraint |
| `fpga/reports/ice40_up5k.txt` | the UP5K result above |
| `fpga/reports/ecp5_25f.txt` | the ECP5 result above |
| `fpga/reports/blocks.txt` | per-block resource breakdown, both families |
| `fpga/build/*.log` | full yosys and nextpnr logs |

`fpga/README.md` has the tool install notes, including the one trap: building
`nextpnr-ecp5` against a Python other than the one `pytrellis` was built for
makes the chipdb generator segfault, and the failure looks like a compiler
error rather than an ABI mismatch.

---

## 7. Where the FPGA area goes, and what the real drum section would add

*FPGA synthesized* — yosys technology mapping, **not** placed or routed.
Blocks are synthesised standalone, so they do not sum to the top row.
`fpga/reports/blocks.txt`, regenerated by `make -C fpga blocks`.

| block (parameters as instantiated) | iCE40 LUT4 | FF | DSP | BRAM | ECP5 LUT4 | DSP |
|---|---:|---:|---:|---:|---:|---:|
| **`synth_top`** (whole chip, **placeholder drums**) | **5,885** | 2,931 | 12 | 0 | 4,675 | 12 |
| `voice_dp` | 4,829 | 2,138 | 8 | 0 | 3,853 | 8 |
| `ladder_dp_n` NCH=2 | 984 | 531 | 4 | 0 | 842 | 4 |
| `recip_div` | 229 | 77 | 0 | 0 | 258 | 0 |
| `modal_dp_rom` M=4 P=8 | 752 | 387 | 4 | 0 | 654 | 4 |
| `spi_ctl` | 207 | 250 | 0 | 0 | 208 | 0 |
| `i2s_tx` | 40 | 49 | 0 | 0 | 147 | 0 |
| **`drum_kit`** M=12 N=6 — **in no `synth_top`** | **6,777** | 3,461 | 6 | 0 | 6,770 | 6 |
| `drum_dp` E=12 P=16 M=12 | 3,576 | 1,385 | 2 | 0 | 3,388 | 2 |
| `modal_dp` M=12 N=6 | 3,266 | 2,076 | 4 | 0 | 3,319 | 4 |
| `modal_dp` M=18 N=11 | 5,830 | 3,983 | 4 | 0 | 5,942 | 4 |

**`voice_dp` is 82 % of the chip that exists**, and inside it the ladder and the
`recip_div` are only a quarter — the rest is the oscillators, envelopes, the
three combinationally-read tables and the mixer.

**`drum_kit` is larger than the entire chip that exists**: 6,777 LUT4 against
5,885. That is the whole point of the labelling in this document. Watch the
parameters when reading this table — `modal_dp` defaults to MODES=4 NUMS=0 and
`ladder_dp_n` to NCH=1, neither of which is what the design instantiates, and
an earlier draft of `fpga/scripts/blocks.sh` reported the defaults under the
right-sounding names.

### A joined-design projection — NOT a measurement

Nobody has synthesised a `synth_top` containing `drum_kit` (contract 17.23),
so this is addition, not a fit:

| | LUT4 | FF | DSP |
|---|---:|---:|---:|
| `synth_top` (placeholder) | 4,675 | 2,932 | 12 |
| + `drum_kit` M=12 | +6,770 | +3,461 | +6 |
| − the placeholder it replaces (inside the top row) | small | small | −4 |
| **≈ joined, ECP5** | **~11,400** | **~6,400** | **~14–18** |
| ECP5 LFE5U-25F capacity | 24,288 | 24,288 | 28 |

On that projection the joined design is roughly **half** an ECP5 25F, and the
**DSPs are the tightest resource at 50–64 %** — worth watching, because the
mode count in `docs/integration-area.md` §3 does not move DSP use but a second
filter datapath would. It does not change the target: UP5K is already 163 %
over with placeholder drums and is not a candidate for anything.
