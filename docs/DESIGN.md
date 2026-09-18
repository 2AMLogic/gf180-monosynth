# Design state

One place for what has been decided and measured, because the reasoning is
otherwise scattered across issue comments. Every number here was measured or
computed in this repository or a sibling; nothing is quoted from intuition.
Where a figure is an estimate it says so.

**Read the gap list at the bottom first if you are deciding whether to rely on
any of this.**

---

## 1. What it is

A monophonic Minimoog-shaped voice — three detuned oscillators into a nonlinear
four-pole ladder — with a drum section and a modal resonator bank, on
gf180mcu. Control comes from a host over a serial link; audio leaves as I2S.
The host owns all musical time; there is no sequencer on the chip.

The product it targets is a small sound module that a MIDI keyboard plugs into,
with a speaker so it demonstrates itself and a jack for real listening. See
[DR 0002](../spec/decision-records/0002-the-product-this-block-is-for.md) —
**and its Corrections section, which withdraws the commercial argument.**

---

## 2. The per-sample budget

12.288 MHz over 48 kHz is **256 core cycles per audio frame**. Everything
below is measured — cycle counts from iverilog, cell counts from yosys generic
mapping.

| block | cycles | cells | RAM | status |
|---|---:|---:|---:|---|
| ladder filter, time-shared | **24** | 5,725 | 0 | RTL bit-exact against `model/fixed.py`, in simulation |
| modal resonator, 4 modes | **15** | 7,017 | 0 | RTL bit-exact against `model/modal_fixed.py`; sizing proposed, not ratified |
| capacitive touch, 8 pads | — | 568 | 0 | area sketch |
| formant voice, 5 resonators | ~20–25 *(est)* | — | ~1.8 kbit ROM | not written |
| existing 4-voice core (sibling repo) | not measured | 19,049 | 0 | verified, in production |
| **used** | **39 of 256** | | | |

The ladder's worst-case cycle count equals its mean — the fixed latency that
justified choosing an explicit solver over an iterative one.

**Nothing needs a faster clock.** The formant family, the feature a 4× clock
was contemplated for, fits nine times over at 12.288 MHz.

---

## 3. The process is slower than "180 nm" implies

This is foundational and easy to get wrong. `gf180mcu_fd_sc_mcu7t5v0` cells are
built from **0.5–0.6 µm, 5 V transistors** (`nfet_05v0 W=0.82u L=0.6u`), not
0.18 µm core devices. The PDK contains 0.28 µm 3.3 V devices; the digital
libraries do not use them.

FO4 from the liberty tables (7-track; 9-track ≈ 5 % faster):

| corner | FO4 | vs textbook 180 nm / 1.8 V (~60 ps) |
|---|---:|---:|
| ff_n40C_5v50 | 0.164 ns | 2.7× slower |
| tt_025C_5v00 | 0.251 ns | 4.2× |
| ss_125C_4v50 | 0.442 ns | 7.4× |
| ss_125C_3v00 | 0.669 ns | **11×** |

An 18×18 MAC (Dadda, Baugh-Wooley, Kogge-Stone CPA, ~2,420 cells) times at
**13.9 ns at tt/5 V and 42.1 ns at ss/3.0 V**. At 81.4 ns it closes everywhere
with 38 ns of margin; at 20.35 ns (49.152 MHz) it closes only at typical 5 V
and needs 2–4 pipeline stages otherwise.

**When reading other people's gf180 results:** ORFS judges at `ff_n40C_5v50`;
open_pdks' LibreLane config loads only 5 V corners and fails violations only at
`*tt*`. Caravel's gf180mcu core is constrained at 33 MHz; a cycle-accurate
68000 closed at 20 MHz. Every published "50 MHz on gf180" is a typical- or
fast-corner number.

---

## 4. Fixed point

| | format | why |
|---|---|---|
| signal | Q1.15 | |
| filter state | 24-bit, **20 fraction bits**, in units of 2·Vt | 20 is the floor — below it the low-cutoff dead zone opens (at 16 bits a 40 Hz cutoff is 5.8 dB off) |
| coefficients | Q0.16 | |
| `tanh` table | **16 entries, edge-sampled, interpolated** — 256 ROM bits | 16 scores identically to 256 on every patch |
| phase accumulator | 24-bit | |
| PolyBLEP reciprocal | 16-bit mantissa + 16-bit reciprocal, computed at note-on; one 16×16 multiply per sample | set by tracking the float waveform inside Q1.15, not by aliasing — 8 bits already reach the float's suppression |
| envelope | 24-bit level, Q0.16 rate, release `L −= max(1, (L·rate) >> 16)` | 20 is the floor for attack time; 24 keeps the release floor below −62 dBFS up to a 1 s release |
| cutoff → `g` ROM | 128 × Q0.16, interpolated — 2 kbit | −0.6 % at 120 Hz, −0.05 % at 1 kHz |

Holding state in units of 2·Vt rather than volts turns the paper's stage into
`Y += g·(tanh(X) − tanh(Y))`: the `tanh` argument becomes the state itself and
one multiply leaves the inner loop.

Two things fixed point found that float hid:

- **A truncation limit cycle at −73 dBFS.** Real, permanent, and below any
  DAC's noise floor. Bounded by a test.
- **Four of eight audition patches exceed full scale** — `growl-bass` peaks at
  1.787 with 7.1 % of samples over. Invisible in float because the renderer
  normalises afterwards. Saturation must be *designed*, not discovered.

A methodological note worth keeping: table values sit at bin **edges** when
interpolating and **midpoints** when not. Mixing them costs ~8 dB and presents
as "interpolation made accuracy worse," which is impossible and is the tell.

---

## 5. The filter

Huovilainen, DAFx-04 — not the linearised model. The nonlinearity is in every
stage; equation (17)'s reuse makes that five `tanh` per sample rather than
eight; the feedback carries a half-sample delay (average of the last two
outputs) or the resonant peak drifts off the cutoff; 2× oversampling is
mandatory.

Self-oscillation tracks cutoff within ±2 % from 200 Hz to 1.6 kHz. **Above
~3 kHz it stops self-oscillating at fixed resonance** — the paper's own caveat
that required feedback varies with frequency. A small compensation ROM is the
intended fix and is not designed.

Why not the alternatives ([DR 0001](../spec/decision-records/0001-ladder-filter-model.md)):
ZDF/TPT with Newton-Raphson has better tuning but needs iteration, and converges
*slower* as feedback and cutoff rise — its worst case is exactly how the
instrument gets played. Levien's matrix form is exact on the linear part but is
16 multiplies against 5, with the nonlinearity still unsolved. **An FIR cannot
do it at all**: matching the ladder at 200 Hz / res 0.9 needs 15,355 taps, and
at res 1.0 it cannot self-oscillate because it has no feedback.

---

## 6. Oscillators

The committed sibling's oscillators use direct phase-bit formulas and alias
badly — **−14.8 dB of inharmonic energy at MIDI note 88**, −20.8 dB at middle
C. That is worse, and more objectionable, than any difference between filter
models.

PolyBLEP recovers **~16 dB uniformly** on saw and square, for a comparison and
about three multiplies applied only within one phase increment of the
discontinuity. No iteration, fixed latency. It needs 1/dt, which is constant
for a held note and so computed at note-on.

Note the square's correction has the **opposite sign** to the saw's — a square
steps up at the wrap where a saw steps down. Getting this backwards measures
5 dB *worse* than naive.

In fixed point (`model/voice_fx.py`) the suppression is identical to float at
every note measured (−42.7 / −36.6 / −31.0 dB at notes 40 / 64 / 88). The
reciprocal's width turned out not to matter for aliasing at all — a constant
per-note error is periodic with f0 and lands on the harmonics — so its 16 bits
are set by waveform accuracy against the float instead. Note also that the
float voice as auditioned (`engines.mono_note`) used the naive oscillators;
`blep=True` is now an opt-in flag there, and the integer voice always
band-limits.

---

## 7. Output

**I2S, with a 1-bit modulator as a debug pad.**

The sigma-delta loop is fine — 103 dB simulated at OSR 256, above the 16-bit
floor, and 3rd order buys nothing. The **pad** is the limit: rise/fall
asymmetry from this PDK's liberty is up to 0.44 ns at 3.3 V, capping it at
**65–80 dB SINAD**, and PSRR is 0 dB by construction because the output *is*
the supply.

The decisive problem is images, not noise. With no interpolator, a 19 kHz tone
puts a zero-order-hold image at 29 kHz at **−12 dBFS**, and no filter with a
20 kHz passband removes it. That is why every audio DAC interpolates.

And both claimed advantages dissolve: "bit-exactness extends to the pin" is
**already true of I2S** and already tested that way; "no DAC in the BOM"
replaces a specified 112 dB part with an unspecified one made of a pad.

The modulator is still worth a fourth pad (~500–1000 cells, zero BOM) as a
characterisation instrument: scope-and-RC bring-up before any DAC is trusted.

---

## 8. Board

| | |
|---|---|
| host link | UART today; SPI time-slice under discussion in the sibling repo |
| MIDI in | 3.5 mm TRS + optocoupler → the UART the chip already has |
| USB | CH32V203F8U6, **3 × 3 mm, $0.33**, TinyUSB MIDI works today |
| audio | I2S → MAX98357A (speaker, has its own DAC) + PCM5102A (line/jack) |
| headphones | PCM5102A is **line level**; 32 Ω needs 66 mA. A TPA6132A2 (~$1, 3 × 3 mm) is the honest fix |
| one-part alternative | TLV320DAC3100: headphone *and* 1.6 W class-D in one 5 × 5 mm, needs I2C |

Size, from component footprints × 2.1 for routing:

| | board | thick | like |
|---|---|---|---|
| dongle (TRS MIDI, no speaker) | 29 × 20 mm | 8.6 mm | car key fob |
| **all-in-one (+ speaker, amp, 200 mAh)** | **38 × 25 mm** | **12.6 mm** | book of matches |
| + USB-A host | 45 × 30 mm | 16 mm | Zippo |

**Our bare die is 2.2 mm².** The USB-A host connector is 87× that; the battery
273×. The chip is never the size constraint.

Power: 11 mA quiescent, 35 mA at normal listening levels, 247 mA at 1 W peak,
against USB 2.0's 500 mA. A 400 mAh cell gives ~7.5 h of normal use.

**A 15 mm speaker in a matchbox cannot produce bass.** It proves the thing is
alive; it does not demonstrate the sound. The jack is the real output.

---

## 9. What is NOT done

The honest list. Nothing below is in progress unless a linked PR says so.

- **The reference model's per-sample path is fully integer** (`model/voice_fx.py`),
  but float still turns the patch's physical units into note-on register
  values and ROM contents — Hz to phase increment, seconds to envelope rate,
  the tanh / sine / `g` tables. In the product those are the host's job or a
  ROM's, and neither is specified yet. Note-on retrigger semantics (legato,
  envelope restart, phase reset) and the glide curve (the float model glides
  geometrically, the integer one slews linearly) are undecided in both models.
- **One of three sketches is still unverified.** `rtl-sketch/ladder_dp.v` and
  `modal_dp.v` are bit-exact against `model/fixed.py` and `model/modal_fixed.py`
  under iverilog, with negative controls that show each bench can fail
  (`rtl-sketch/test_rtl.py`). `touch_dp.v` has never been compared against
  anything. The earlier "20 cycles, 1,917 cells" ladder figure was the area of
  a circuit whose ROM reads were out of range — every output was X — and is
  withdrawn; the table above has the measured numbers.
- **There is no numeric contract for this instrument.** The sibling repo has
  one for its four-voice engine; this block has none. The filter and the modal
  bank are bit-exact against their own models; the rest of the voice has
  nothing for RTL to be bit-exact *against* yet.
- **No PDK has been run.** No synthesis, floorplan, route, GDS, DRC, LVS, STA
  or ERC on gf180mcu. **No area in mm², no timing, no power.** Every cell count
  here is PDK-neutral yosys output.
- **No hardware.** No FPGA bitstream for this block, no board, no silicon.
- **The commercial case is withdrawn** (DR 0002 Corrections) and the consumer
  promise still does not explain why someone would want to play it.
- The filter's resonance-vs-frequency compensation ROM is not designed.
- Signoff voltage is undecided. 5 V vs 3.3 V is 2.3× in dynamic power and 1.5×
  in speed; the open flow defaults to 5 V, which works against a battery
  product, and USB pads need 3.3 V. These interact.
