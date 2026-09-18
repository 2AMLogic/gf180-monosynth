# Area budget on gf180mcu, measured

The target is a wafer.space gf180mcu quarter slot: **1.73 mm² inside the default
pad ring** (~1000 dies, $3500–4500; those three figures are the premise this
document was asked to budget against, not something re-derived here). An hour
before this was written the plan assumed the design would use 10–20 % of that.
The first real synthesis said ~76 %. This document says where every square
micron goes, what polyphony and the modal bank actually cost, what the cheapest
credible instrument is, and whether the 9-track library is worth it — with
measurements, not opinion.

**Every cell-area number below is yosys 0.69+62 → ABC, mapped to
`gf180mcu_fd_sc_mcu7t5v0`, liberty corner `tt_025C_5v00`, PDK
`gf180mcuD` (ciel `54435919ab…`), unless a row is explicitly labelled 9t
(`gf180mcu_fd_sc_mcu9t5v0`, same corner).** Cell area is the sum of liberty
`area` values of the mapped cells. **It is not die area.** No block here has been
placed or routed by this document. To turn cell area into core area the
document uses **one utilisation assumption, 50 %, everywhere** (core = cells ÷
0.5), and shows the 60 % sensitivity once in section 4. The pad ring is *not* a
further deduction — the 1.73 mm² is already inside it. The power grid on this
platform (Metal1 follow-pin rails, Metal4/Metal5 straps, tap and end-cap cells)
sits above and between the cells and is absorbed by the utilisation assumption;
it is not budgeted separately. SRAM and USB are real additions and are treated
in section 4.

Everything is reproducible: `rtl-sketch/area/run_all.sh` regenerates every row
(section 7).

---

## 0. Method, and what one cell costs here

The flow mirrors what `klt synthesize` runs: `read_verilog; hierarchy -check;
synth -top` (no `-flatten`, so `stat` reports every submodule); `dfflibmap
-liberty`; `abc -liberty`; `stat -liberty -json`. No `-constr`, no `dont_use`
(klt's own choice for gf180). `synth -booth` is off unless a row says "booth".

It reproduces the numbers this document was given, to four digits, which is
how the method was validated before anything else was measured:

| block | given | measured here | note |
|---|---:|---:|---|
| ladder, time-shared | 0.1136 mm² | **0.1136** (113,619 µm², 5,428 cells) | |
| modal bank, 4 modes | 0.1505 | **0.1505** (150,510 µm², 7,327 cells) | |
| touch, 8 pads | 0.0200 | **0.0200** (19,985 µm², 714 cells) | |
| synth_core NV=4 | 0.3743 | **0.3743 flat**; **0.3960 hierarchical** | the given figure was a *flat* synthesis; keeping the hierarchy loses 5.8 % of cross-module optimisation. Section 1 is measured hierarchically because that is the only way to see inside. |

What things cost in this library (liberty `area`, µm²), because it explains most of what follows:

| cell | 7t | 9t | 9t/7t |
|---|---:|---:|---:|
| `dffq_1` (the only D flop; **there is no enable flop**) | 63.66 | 79.03 | 1.24 |
| `mux2_1` — what every enabled register bit pays on top of its flop | 28.54 | 36.69 | 1.29 |
| `nand2_1` / `inv_1` | 10.98 / 8.78 | 14.11 / 11.29 | 1.29 |
| `addf_1` (full adder) | 72.44 | 84.67 | 1.17 |
| `xor2_1` | 26.34 | 33.87 | 1.29 |

So a state bit that is written under an enable — which is nearly every register
bit in a synth — costs **92 µm²** before any logic touches it. A thousand of them
is 0.09 mm².

Bare multipliers, registered in and out, synthesized alone (7t):

| multiplier | cells | µm² | µm² per partial-product bit |
|---|---:|---:|---:|
| 16×16 signed | 1,730 | 35,843 | 140 |
| 18×18 signed | 2,155 | 43,777 | 135 |
| 24×20 signed×unsigned (the ladder's) | 3,257 | 63,856 | 133 |
| 24×20, `-booth` | 2,173 | 45,711 | 95 |
| 24×24 signed | 3,868 | 76,915 | 134 |
| 28×26 signed (the modal bank's) | 4,845 | 94,113 | 129 |
| 28×26, `-booth` | 3,113 | 64,668 | 89 |

Area is linear in partial-product bits at ~130–140 µm² each with yosys's
default array multiplier, ~90 with Booth. **A 28×26 multiplier is 0.094 mm² —
half a modal bank, three quarters of a voice.** Keep that number in mind.

---

## 1. Where the area actually goes (the 4-voice core)

Measured on the sibling's `rtl/{uart_rx,synth_voice,synth_core}.v` (contract
rev 1) with `NV=4`, hierarchy kept. To see the blocks that live inline in
`synth_core.v` and `synth_voice.v` — parser, FIFO, mixer, the two ROM includes,
the two multipliers — they were moved into named submodules by textual
wrapping with no logic change (`rtl-sketch/area/wrap_polysynth.py`, which
asserts every pattern matched). The wrapped copy totals 411,703 µm² against
395,990 unwrapped; that 4 % is lost cross-boundary optimisation and is the
price of the visibility. Percentages below are of the wrapped total.

| instance | cells | flops | µm² | % |
|---|---:|---:|---:|---:|
| `synth_core` own: frame counter, output register, byte-port merge | 126 | 26 | 3,256 | 0.8 |
| `uart_rx` | 151 | 34 | 3,938 | 1.0 |
| `byte_parser` | 187 | 34 | 4,928 | 1.2 |
| **`cmd_fifo8`** — 8 × 35-bit command FIFO | 733 | 293 | **33,505** | **8.1** |
| `mixer4` — 4-input sum + saturate | 257 | 0 | 4,720 | 1.1 |
| **4 × `synth_voice`** | 4 × 4,347 | 4 × 235 | **361,356** | **87.8** |
| **total** | 18,842 | 1,327 | **411,703** | 100 |

Inside one voice (90,339 µm²):

| part of `synth_voice` | cells | µm² | % of voice |
|---|---:|---:|---:|
| `mul_s16u16` — the output scaler, `osc × g` | 1,429 | 27,883 | 30.9 |
| `mul_u16u7` — `env × velocity` | 560 | 10,322 | 11.4 |
| `sine_q_rom` — 257 × 16 bit, `always @* case` | 506 | 8,829 | 9.8 |
| `note_inc_rom` — 128 × 24 bit, `always @* case` | 329 | 5,782 | 6.4 |
| the 235 register bits (phase 24, inc 24, level 20, A/D/S/R 64, velocity 7, wave 2, state 3, scaler pipeline 73, out 17), flops only | 235 | 14,960 | 16.6 |
| everything else: phase adder, waveform formers, ADSR compare/add/sub, command decode, enable muxes | ~1,290 | ~22,560 | 25.0 |

Cross-check: yosys's own `sequential_area` for the NV=4 core is 84,478 µm² =
1,327 × 63.66, i.e. **flops are 21 % of the core**; the rest is logic.

**What dominates.** The four voices, at 88 %. Inside a voice, the two
multipliers are 42 % and the two ROMs 16 %: **58 % of every voice is a
multiplier-and-ROM set that is used for exactly one multiply and one or two
lookups per 256-cycle frame** — and there are four copies of it. That is the
single largest lever in the design (section 2).

**Are the ROMs synthesized as logic?** Yes. Both `case` tables become
`$pmux`es and then ABC logic: the sine table costs **8,829 µm² (2.15 µm² per
stored bit)** and the note table **5,782 µm² (1.88 µm²/bit)**, standalone
numbers agree within 1 %. That is cheap per bit — cheaper than a flop — and
not the surprise. The cost is the ×4: **58,444 µm² of ROM in the core, of which
three quarters is duplicate**; the note table is read once per NOTE_ON and
the sine table once per voice per frame, so one copy serves four voices
trivially at 256 cycles per frame.

**What is surprisingly expensive.** The **command FIFO: 33,505 µm² for 280 bits
of storage, 120 µm² per bit, 8 % of the whole core** — more than the UART,
parser and mixer combined, ×2.5. It is the no-enable-flop tax (293 × 63.66 =
18,653 of flops, then a `mux2` per bit for the write enable, then an 8:1 read
mux across 35 bits). Depth 8 buys nothing: the FIFO pops every cycle it is
non-empty except the tick cycle and is pushed at most once per cycle, so by
construction it never holds more than one or two entries; over the UART a byte
arrives every ~4 frames (115,200 baud is 0.24 bytes per 48 kHz frame). A
2-deep FIFO would save roughly 20,000 µm².

---

## 2. What polyphony costs

### 2.1 Voices: the existing core at NV = 1, 2, 4

| NV | cells | µm² | mm² | per added voice | 9t | `-booth` |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5,422 | 131,914 | 0.1319 | | 166,911 | 126,874 |
| 2 | 9,698 | 220,277 | 0.2203 | +88,363 | | 210,008 |
| 4 | 18,246 | 395,990 | 0.3960 | +87,856 each | 502,486 | 376,220 |

**One voice as currently written costs 88,000 µm² (0.088 mm² of cells, 0.176
mm² of core at 50 %).** The front end without any voice (UART + parser + FIFO +
mixer + frame counter, extrapolated to NV = 0) is ~44,000 µm². Booth helps the
core only 5 % because its multipliers are 16-bit.

### 2.2 Filters: N independent ladders on one datapath

`rtl-sketch/ladder_dp_n.v` is `ladder_dp.v` with a `NCH` parameter and a `ch`
input: the four stage integrators `y[]`, the four `tanh` outputs `w[]` and the
two half-sample-delay words `d1`, `d2` — **208 bits per channel** — become
per-channel arrays; the multiplier, `tanh` unit, saturators and sequencer are
unchanged and shared. At NCH = 1 it is the original module. **Verified
bit-exact against `model/fixed.py` on every channel**: the 28,800-sample
five-patch stimulus of `verify_ladder.py` driven to each channel in turn,
`tb_ladder_n.v`, NCH = 1, 2, 4 → 28,800 / 57,600 / 115,200 channel-samples,
**0 mismatches, worst error 0 LSB**, output channel tag checked on every sample.

| NCH | cells | flops | µm² | mm² | per added channel | cycles / frame (24 per channel) | `-booth` |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5,530 | 317 | 113,588 | 0.1136 | | 24 | |
| 2 | 6,478 | 529 | 139,307 | 0.1393 | +25,719 | 48 | 122,058 |
| 4 | 8,087 | 947 | 186,232 | 0.1862 | +23,462 avg | 96 | 169,834 |
| 8 | 10,738 | 1,782 | 287,850 | 0.2878 | +25,402 avg | 192 | |

**An extra independent filter costs ~24,500 µm² (0.0245 mm² of cells), i.e.
22 % of a filter, not 100 %.** The register-count reasoning predicts the flop
part exactly — 210 added flops per channel × 63.66 = 13,370 µm² — and the
measurement adds ~11,000 µm² of read/write muxing for the channel-indexed
arrays: **~118 µm² per replicated state bit, all in**. Four independent filters
are 0.186 mm² of cells and 96 of the 256 cycles; eight are 0.288 mm² and 192
cycles, the cycle budget's practical ceiling.

### 2.3 Consequence: the voices should be built the way the filter is (derived, not measured)

Apply the same 118 µm²/bit calibration to the voice's per-note state (phase,
increment, level, A/D/S/R, velocity, wave, state: 144 bits): **~17,000 µm² per
additional voice on a time-shared voice datapath**, against the 88,000 µm² an
additional copy of `synth_voice` costs today. A 4-voice time-shared core would
be roughly 132,000 + 3 × 17,000 ≈ **183,000 µm², versus 396,000 measured** for
four copies — and it needs 4 of 256 cycles for its four multiplies. This is a
derivation from two measurements (the NV sweep and the ladder channel cost),
not a measurement of a written engine; the engine is not written, and its
tick-versus-apply timing against contract §4.2/§10.4 has to be designed, not
assumed. It is the first thing to build if area matters.

---

## 3. Does the modal bank earn its 0.1505 mm²?

### 3.1 Why it is big

| part of `modal_dp` (150,510 µm²) | µm² | % |
|---|---:|---:|
| the 28 × 26 signed multiplier (bare, section 0) | 94,113 | 62.5 |
| 387 flops: `y1`/`y2` 2 × 4 × 28, `acc` 54, `mix` 30, `ma`/`mb` 54, sequencer | 24,637 | 16.4 |
| parallel coefficient ports and their 4:1 mux trees (measured as the difference to the ROM version, below) | ~7,400 | 4.9 |
| saturators, the 58-bit `acc + mr` adder, shifts, sequencer logic | ~24,400 | 16.2 |

**The earlier note was wrong about the cause.** The mux trees on the twelve
parallel coefficient ports are ~5 % of the block. The block is big because its
coefficients are **Q2.24 (26 bits) against a 28-bit state**, which the model's
sizing sweep found necessary (at MIDI 28 the pitch lives in the difference
between `a1` and 2; Q2.16 is 2.4 % off pitch), and a 28 × 26 multiplier is
0.094 mm² in this library. The ladder's multiplier is 24 × 20 = 480
partial-product bits; the modal's is 728, hence 1.47× the multiplier and 1.32×
the block.

### 3.2 Rewritten with the coefficients in a ROM, and re-measured

`rtl-sketch/modal_dp_rom.v` replaces the twelve ports with a `preset` input and
a coefficient ROM (`modal_coef_rom_p{4,8,16}.v`, word = `{preset, mode,
kind}`, generated by `gen_modal_rom.py` from `ModalFx.coefficients()` so the
ROM holds exactly the model's integers; the presets are MIDI-note pitches of
the model's default four-mode bar). The datapath and the 15-cycle sequence are
untouched; the ROM is read combinationally in the cycle the mux used to be.
`rtl-sketch/modal_dp_regs.v` is the other real design — the coefficients in
twelve host-written registers (issue 7's "parameter write" packet).

**Bit-exact:** `tb_modal_rom.v` drives the exact stimulus of `verify_modal.py`
(six hits and the rail-to-rail stress, 48,000 samples) with the preset index
instead of the coefficient words, against `model/modal_fixed.py`: **P = 8 and
P = 16: 0 mismatches, worst error 0 LSB.** The bench can fail: with
`INJECT_BUG_MODAL_SHIFT` it reports 47,991 mismatches.

| modal bank variant | coefficient store | cells | µm² | mm² | vs ports |
|---|---|---:|---:|---:|---:|
| as sketched: 12 parallel ports + mux trees | off-chip / elsewhere | 7,327 | 150,510 | 0.1505 | |
| **ROM, 4 presets** | ROM 152 cells, 2,507 µm² | 7,008 | 145,272 | 0.1453 | −3.5 % |
| **ROM, 8 presets** | ROM 306 cells, 5,005 µm² | 7,159 | **148,126** | **0.1481** | −1.6 % |
| ROM, 16 presets | ROM 520 cells, 8,737 µm² | 7,489 | 152,968 | 0.1530 | +1.6 % |
| host-written registers (12 × 26 bits) | 272 flops + decode | 7,908 | 175,212 | 0.1752 | +16.4 % |
| ROM, 8 presets, `-booth` | | 5,475 | **119,531** | **0.1195** | −20.6 % |
| ROM, 8 presets, **9t** | | 7,127 | 186,913 | 0.1869 | +24.2 % |

**Done properly it costs 0.148 mm² — essentially what it costs now.** The ROM
is ~2 µm² per stored bit, like the sine table (96 words of real 26-bit
coefficients = 5,005 µm²), and replaces muxes of about the same size; the "parallel ports inflate
it" explanation does not survive measurement, and the parallel-port sketch
was in fact the *cheapest* version because it externalised the storage.
Holding the coefficients in host-written registers, which is what a
parameter-write control model implies, is the expensive option (+16 %).

What does move it:

- **`synth -booth`: −20 %** (150,510 → 120,376 as sketched; 148,126 → 119,531
  with the ROM). Same for the ladder (−14.5 %) and the drum strawman (−6 %).
  A yosys Booth netlist is functionally the same multiplier; the P = 8 ROM
  netlists, plain and Booth, were additionally simulated at gate level with
  the PDK's `gf180mcu_fd_sc_mcu7t5v0.v` cell models against the same 48,000
  vectors — see section 6 for the result.
- **Sharing one 28 × 26 multiplier between the ladder and the modal bank**
  (derived): the ladder's 24 × 20 (63,856 µm²; 45,711 Booth) disappears, a
  few thousand µm² of operand muxing appears, net **≈ −60,000 µm² (≈ −43,000
  with Booth)**. The two blocks already time-share internally and together use
  24 + 15 = 39 of 256 cycles (96 + 15 with four filter channels), so nothing
  in the schedule prevents it. Not built; the number is the difference of two
  measurements.
- Narrowing the multiplier is **not** on the table: the coefficient width is
  the model's finding, and the modal bank's tuning at low notes is exactly
  what that width buys.

### 3.3 So does it earn it?

Nobody asked for "a modal bank" by name. But issue 7's percussion family —
snare (tuned partials + noise), toms, cowbell (two tuned squares), the hats'
band-pass — **is** a set of two-pole resonators struck by noise and impulses,
which is precisely what `modal_dp` is, with no RAM. Read that way, the modal
bank is the drum bodies, and the question becomes whether the instrument has
drums. If it does, the bank earns its 0.12–0.15 mm² and the sources cost
another ~0.09 (section 4). If the instrument is a monosynth without drums or a
"something you can hit", it is the second-largest block on the die for a
feature no one specified, and it goes.

---

## 4. The cheapest credible instrument

Adds, all 7t, 1× the measured cell area of each block; core area at 50 %
utilisation; percentage of the 1.73 mm² slot. "Booth" is the same
configuration with `synth -booth` on every block that has a multiplier (each
measured, not scaled).

| # | configuration | blocks | cells µm² | core mm² @50 % | % of slot | Booth: cells / core / % | what it gives up |
|---|---|---|---:|---:|---:|---|---|
| A | **Mono Moog** | core NV=1 + ladder | 245,533 | **0.49** | **28** | 224,062 / 0.45 / 26 | polyphony, drums, "hit" sounds, touch |
| B | **Mono Moog + drums** | A + drum sources (strawman) + modal bank (ROM, 8) | 482,663 | **0.97** | **56** | 427,502 / 0.86 / 49 | polyphony, touch; the drum sources are an unverified strawman (below) |
| C | **Paraphonic** — 4 oscillators, one filter | core NV=4 + ladder | 509,609 | **1.02** | **59** | 473,408 / 0.95 / 55 | independent filtering per note, drums |
| D | **4-voice polyphonic** — 4 oscillators, 4 filters | core NV=4 + ladder NCH=4 | 582,222 | **1.16** | **67** | 546,054 / 1.09 / 63 | drums |
| E | the premise: NV=4 + ladder + modal + touch | as given | 680,104 | 1.36 | 79 | 613,769 / 1.23 / 71 | independent filters, drum sources |
| F | **everything** | NV=4 + ladder NCH=4 + modal (ROM 8) + drums + touch | 839,337 | **1.68** | **97** | 769,479 / 1.54 / 89 | nothing — and nothing else fits |

Then add what is not in any row:

| addition | cells | at 50 % | source |
|---|---:|---:|---|
| **USB device core** | 4–5 k cells × 22–26 µm²/cell = **0.09–0.13 mm²** | **+0.18–0.26 mm² (+10–15 % of slot)** | *not measured*: no USB device core (SIE, endpoints) exists in this workspace. The cell count is the premise; the µm²/cell is what this library gives our own control logic (UART 26.1, parser 26.4, touch 28.0, whole core 21.7). For scale, the routed `gf180-usb2-phy` UTMI PHY on 9t (fleet PDN-audit record, klt 0.3.0): core 33,733 µm² at 44 % utilisation ≈ 14,900 µm² of 9t cells — the PHY alone is small; the device core is the unknown. |
| **any SRAM** | one macro, footprint (die area, no utilisation factor): `sram64x8` 0.101 mm², `sram128x8` 0.116, `sram256x8` 0.147, `sram512x8` **0.209 mm² for 4 kbit** | | `gf180mcu_fd_ip_sram` LEF. A 1 s 16-bit delay line is 768 kbit = 192 of the largest macro. **Any delay/reverb/sample feature is off the table on this PDK**; the modal bank's no-RAM design is vindicated. |
| 60 % utilisation instead of 50 % | × 0.83 on every core-area column | | e.g. F becomes 1.40 mm² (81 %) |

**What fits.** A (0.49 mm²) fits with USB, an SRAM macro and room to spare —
it is within a factor of 1.5–3 of the 10–20 % the project assumed. B and C (0.86–1.02) fit with USB
at 60–75 % of the slot. D fits with USB only with Booth and at the edge (1.09 +
0.26 = 1.35, 78 %). E and F do not fit once USB is added (E: 1.36 + 0.26 = 1.62
= 94 % with no margin for the placer; F: over). None of these leaves room for
an SRAM macro except A and, with Booth, B.

**With the derived time-shared voice engine (section 2.3)** the picture
changes: C becomes ≈ 297,000 µm² (0.59 mm², 34 %), D ≈ 369,000 (0.74, 43 %),
and F ≈ 626,000 (1.25 mm², 72 %; ≈ 1.15 with Booth). That is the difference
between "pick two" and "everything, with USB". It is also unbuilt.

**The drum sources**, since row B and F depend on them: `rtl-sketch/drum_src_seq.v`
is an *area strawman, verified against nothing* (the same status as
`touch_dp.v`): eight edge-triggered stops, eight exponential-decay envelopes
through one time-shared shifter, a 23-bit LFSR, a swept-pitch sine kick via
the contract's quarter-sine ROM, one 16 × 16 multiplier applying env × source
in 8 cycles per frame, a saturating mix, and an enveloped-noise excitation for
the modal bank. **89,004 µm² (3,976 cells, 332 flops); 83,909 with Booth.** A
first version with eight parallel barrel shifters measured 110,160 µm² — the
same "sequence it" lesson as the voices, and the reason the kept version is
the sequenced one.

**What "cheapest credible" means here.** Row A is a real instrument (the
product DR 0002 describes, minus the drum section) at a quarter of the slot.
Row B is that instrument with drums at half the slot. Row C is issue 7's
paraphonic lead at the same cost as B — polyphony and drums cost about the
same, ~0.24 mm² of cells each on today's RTL, and the choice between them is
musical. Row D's extra filters are cheap (0.07 mm²); what makes D expensive is
the four voice copies, which section 2.3 says should not be copies.

---

## 5. Is 9-track worth it?

Area difference, measured on every block, same corner:

| block | 7t µm² | 9t µm² | 9t / 7t |
|---|---:|---:|---:|
| core NV=4 | 395,990 | 502,486 | **1.269** |
| core NV=1 | 131,914 | 166,911 | 1.265 |
| ladder | 113,619 | 144,225 | 1.269 |
| modal bank (ports) | 150,510 | 190,413 | 1.265 |
| modal bank (ROM, 8) | 148,126 | 186,913 | 1.262 |
| touch | 19,985 | 25,128 | 1.257 |

**9-track costs +26–27 % on everything** — row F would be 2.13 mm² of core,
larger than the slot. The speed side was not re-measured here (ABC under this
yosys build does not report a mapped delay without a constraint file); the
liberty-derived FO4 figures in `DESIGN.md` put 9t ~5 % faster. The design has
no use for it: at 12.288 MHz the earlier 18 × 18 MAC analysis closes with 38 ns
of margin even at ss/3.0 V, and nothing in this document needs a faster clock.
**Use 7t.** One correction that follows: the sibling's
`asic/synthesize-polysynth.json` names `gf180mcu_fd_sc_mcu9t5v0`; run as
written, the core is 0.50 mm² of cells, not 0.37–0.40.

---

## 6. Not measured, and other caveats

- **No placement or routing.** Every mm² in sections 1–5 is cell area ÷ 0.5.
  At the time of writing an in-progress, uncommitted `pnr/` effort exists in
  this checkout (klt and ORFS configs for `ladder_dp` and `synth_core`); its
  klt response files were empty (the run had not completed) and its
  placement metrics show the placer reaching 53 % at a requested 50 % for the
  ladder — a hint that 50 % is realisable for this block, not a result. The
  first routed number replaces the assumption; until then the utilisation is
  the largest single uncertainty in this document (a 10-point change moves
  every core area by 17–25 %).
- **Booth netlists were not equivalence-checked.** Instead, the P = 8 modal
  ROM netlists as mapped to `gf180mcu_fd_sc_mcu7t5v0` — plain and Booth — were
  simulated at gate level (iverilog, the PDK's `gf180mcu_fd_sc_mcu7t5v0.v`
  functional cell models) against the first 4,800 samples of the model's
  stimulus (the note-28 strike and its ring, all four modes and every ROM
  word of that preset): **both PASS, 0 mismatches, worst error 0 LSB**. That
  is the ROM-as-logic and the Booth multiplier shown correct after mapping,
  on a tenth of the stimulus; the full 48,000-sample gate-level run costs
  about an hour per netlist and had not completed when this was committed.
- **`drum_src_seq.v` is an area sketch**, unverified against any model, exactly
  as `touch_dp.v` is. Its 0.089 mm² is a lower bound for "drum sources", not a
  design.
- **The time-shared 4-voice engine (2.3) and the shared ladder/modal
  multiplier (3.2) are derived**, each from the difference of two
  measurements. They are labelled as such wherever they appear.
- **The USB device core is not in this workspace** and was not measured; its
  row is the premise's cell count at this library's measured µm²/cell.
- **Speed of 9t vs 7t was not measured here.**
- The wrapped copy of the core (section 1) measures 4 % more than the
  unwrapped hierarchy; the per-block percentages carry that.
- The concurrent ladder P&R in `pnr/` is someone else's uncommitted work and is
  cited only for what its intermediate metrics file said on the day.

---

## 7. Reproduce it

```sh
export GF180_PDK_REF=<pdk>/gf180mcuD/libs.ref       # the ciel/volare install
export OSS_CAD_SUITE=/path/to/oss-cad-suite         # yosys 0.69, iverilog
export POLYSYNTH=../gf180-polysynth                 # the sibling checkout
rtl-sketch/area/run_all.sh                          # every cell-area row, ~5 min
```

Results land in `rtl-sketch/build/area/<tag>/{synth.ys,yosys.log,stat.json,netlist.v,result.json}`.
The bit-exact checks:

```sh
cd rtl-sketch
.venv/bin/python verify_ladder.py --tanh-n 16 --outdir build         # writes build/ladder_vectors.hex
iverilog -g2012 -P tb_ladder_n.NCH=4 -o build/n4.vvp tb_ladder_n.v ladder_dp_n.v
vvp -n build/n4.vvp +vec=build/ladder_vectors.hex +out=build/n4.txt    # expect PASS, 115200 channel-samples
.venv/bin/python gen_modal_rom.py                                    # ROMs + build/modal_rom_vectors_p{8,16}.hex
iverilog -g2012 -P tb_modal_rom.PRESETS=8 -o build/p8.vvp tb_modal_rom.v modal_dp_rom.v modal_coef_rom_p8.v
vvp -n build/p8.vvp +vec=build/modal_rom_vectors_p8.hex               # expect PASS, 0 mismatches
```

Files added by this document: `rtl-sketch/ladder_dp_n.v`, `tb_ladder_n.v`,
`modal_dp_rom.v`, `modal_dp_regs.v`, `modal_coef_rom_p{4,8,16}.v`
(generated), `gen_modal_rom.py`, `tb_modal_rom.v`, `drum_src_seq.v`,
`rtl-sketch/area/{synth_area.py,wrap_polysynth.py,run_all.sh}`.
