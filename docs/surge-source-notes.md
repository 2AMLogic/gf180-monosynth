# What Surge's filter source says, and what it costs us

Surge XT is the only reference in `docs/discrimination.md` §8 whose internals
can be read. This file is what reading them produced, with our own numbers
beside each one. Source: `surge-synthesizer/sst-filters` `main`
(`include/sst/filters/`) and `surge-synthesizer/sst-basic-blocks`
(`include/sst/basic-blocks/dsp/FastMath.h`). The `VintageLadder::Huov`
namespace is mathematically identical at the Surge 1.2.3-era commit `8ea9b8d`
and on `main`, so `main` describes the 1.2.3 that is installed here.

**Nothing here is a recommendation.** Each section gives the reference's
choice, ours, and the cost of changing, so the agent that owns
`model/fixed.py` can make the trade.

---

## 1. Coefficient smoothing — Surge band-limits its cutoff control; we do not

`FilterCoefficientMaker_Impl.h`, and `constexpr float smooth = 0.2f`:

```cpp
tC[i] = (1.f - smooth) * tC[i] + smooth * N[i];   // one-pole LP on the TARGET, per block
dC[i] = (tC[i] - C[i]) * blockSizeInv;            // then a linear ramp of C across the block
```
and inside every filter's `process`, per oversampled sub-step:
```cpp
f->C[k] = A(f->C[k], M(dFac, f->dC[k]));          // dFac = 0.5 at 2x, 0.25 at 4x
```

Two stages: a one-pole low-pass on the coefficient **target**, then a linear
ramp of the coefficient itself across the block. At Surge's 32-sample block
and 48 kHz the first stage is a time constant of about **3 ms (a ~53 Hz
corner)**. Surge deliberately band-limits the control signal before it reaches
the filter.

**Ours has no smoothing of any kind.** `voice_fx._render` computes the cutoff
per frame from the filter envelope, reads `g` from the ROM per frame, and
`LadderFx.process` uses `g_tab[i]` per sample. Per-sample update is the
*favourable* case for stepping — it is block-rate updates that zipper — but it
also means an envelope step reaches the coefficient with no lag and no limit.

Neither is obviously right: smoothing costs 3 ms of lag on a fast filter
envelope, which is audible in its own way. But ours has not been chosen
deliberately, and `model/reference_movement.py` now measures the consequence.

---

## 2. Our cutoff control resolution, in closed form

`model/reference_movement.py --stage control`. The control path is
`cutoff in INTEGER Hz -> g in Q0.16, from a 128-entry ROM read with linear
interpolation`. Inverting the realised `g` back to an effective cutoff gives:

| commanded | effective | static error | one step | step | gain step at 24 dB/oct |
|---|---|---|---|---|---|
| 30 Hz | 29.64 | **−21.1 cents** | 1 Hz | **53.7 cents** | **1.075 dB** |
| 60 Hz | 59.57 | −12.6 | 1 Hz | 27.0 | 0.540 |
| 120 Hz | 119.36 | −9.2 | 1 Hz | 13.6 | 0.272 |
| 200 Hz | 199.46 | −4.7 | 1 Hz | 10.2 | 0.204 |
| 500 Hz | 499.77 | −0.8 | 1 Hz | 3.3 | 0.067 |
| 2 kHz | 1999.50 | −0.4 | 1 Hz | 0.92 | 0.018 |
| 6.4 kHz | 6399.83 | −0.05 | 1 Hz | 0.19 | 0.004 |
| 16 kHz | 15999.26 | −0.08 | 1 Hz | 0.14 | 0.003 |

Two separate findings:

- **The step is one hertz, because the cutoff register is integer hertz**
  (contract 5.1: `cut_lo`, `cut_hi`, `track_hz` are 16-bit integer Hz). One
  hertz at 30 Hz is 58 cents. The `g` ROM is not the limit — it interpolates.
  The staircase is therefore **coarse at the bottom of the range and invisible
  at the top**, which is the opposite of where a test that sweeps the top
  octave would look.
- **The ROM is 9–21 cents flat below 120 Hz**, statically, and under a cent
  above 300 Hz. That is the 128-entry ROM's 256 Hz-spaced linear interpolation
  across the part of `1 − exp(−2πf/fs)` that bends most, with entry 0 pinned at
  `g(0) = 0`. It is a static accuracy defect, not a movement one, and it sits
  in exactly the region DR 0006's compensation also lives in.

---

## 3. Movement, measured

`model/reference_movement.py --stage sweep|plugins`. A steady 2 kHz carrier,
the cutoff swept 500 Hz → 8 kHz, ripple = what survives a high-pass of the
output's envelope (`audio_measure.envelope_ripple_db`, ground-truthed against
a staircase of known step size).

| filter | 10 oct/s | 2.5 oct/s | 1 oct/s |
|---|---|---|---|
| **ours** | **−46.1 dB** | **−69.9** | **−82.0** |
| Surge Type 2 (Huov) | −52.0 | −76.4 | −91.2 |
| Surge Type 1 (RK) | −51.6 | −76.1 | −90.9 |
| Mini V3 | −51.5 | −74.5 | −86.2 |
| Diva | −32.0 | −33.0 | −33.1 |

**Ours has a 5–9 dB higher movement ripple floor than Surge and Mini V3**, and
the gap widens as the sweep slows. Every filter's ripple falls with the sweep
rate at roughly 12 dB per octave of rate, which is the signature of a smooth
process — **nobody here is stepping badly**, ours included. The size of our
excess is consistent with the control quantisation of §2, but this measurement
does not isolate the cause.

**Diva's row is not comparable**: at a flat −33 dB at every rate it is
reporting the floor of its own oscillator (it has no audio input, so its own
triangle is the carrier), not its filter.

**A harness artefact that had to be found first, and is worth recording.** At
dawdreamer's default 512-sample block, parameter automation is applied per
block — 93.75 Hz — so a swept cutoff moves in 93.75 Hz steps. The first run
measured *all three plugins* at an identical 94 Hz dominant ripple rate while
ours (which moves per sample) sat at the floor, and it looked exactly like
"the references step and we do not". Re-running at a 16-sample block moved the
artefact out of band and reversed the conclusion. The table above is the
16-sample run.

**Differential check, ours only and the strongest evidence available**: render
the same sweep twice through the same filter, once with the shipping integer
control path and once with the cutoff and `g` in float. The difference is
**−49 dB** over a 60–960 Hz sweep and **−66 dB** over 500 Hz–8 kHz, and it is
**independent of sweep rate** over a 40× range — which says it is the *static*
error of §2, not a staircase. Injected control: rounding the commanded cutoff
to 32 Hz moves that differential by **+24.5 dB**, so the measurement has power.

---

## 4. The `tanh`: a table against a polynomial, with both costs

`docs/discrimination.md` §8.5 established that our excess 5th harmonic at
self-oscillation is the 16-entry table. Surge uses
`basic_blocks::dsp::fasttanhSSEclamped` — a Padé rational, clamped to ±5:

```cpp
auto x2  = x * x;
auto num = x * (135135 + x2 * (17325 + x2 * (378 + x2)));
auto den = 135135 + x2 * (62370 + x2 * (3150 + 28 * x2));
return num / den;
```

Measured over our own domain [0, 4):

| approximation | ROM bits | max &#124;err&#124; | rms err | cost per evaluation |
|---|---|---|---|---|
| **LUT 16 linear (shipping)** | **256** | **6.00e−03** | 2.09e−03 | 1 mul, 1 add, 2 reads |
| LUT 32 linear | 512 | 1.52e−03 | 5.35e−04 | 1 mul, 1 add, 2 reads |
| LUT 64 linear | 1024 | 6.71e−04 | 1.48e−04 | 1 mul, 1 add, 2 reads |
| LUT 128 linear | 2048 | 6.71e−04 | 5.64e−05 | 1 mul, 1 add, 2 reads |
| LUT 16 quadratic | 256 | 3.25e−02 | 5.95e−03 | 3 mul, 4 add, 3 reads |
| Padé [3/2] `x(27+x²)/(27+9x²)` | 0 | 2.35e−02 | 1.33e−02 | 3 mul + **1 divide** |
| Padé [7/6] (Surge) | 0 | **1.50e−05** | 3.39e−06 | 7 mul + **1 divide** |

The ladder evaluates `tanh` **five times per oversampled sub-step and runs two
sub-steps per frame — ten evaluations per sample, 480 000 per second.** So
Surge's polynomial is **70 multiplies and 10 divides per sample** against our
table's 10 multiplies and 20 ROM reads. The ECP5 build already uses 14 of 28
DSPs; on the ASIC a divider is a sequential unit. **A polynomial does not
obviously win here, and this table is the trade, not a recommendation.**

Two results that were not expected:

- **A quadratic interpolator on the existing table is WORSE than the linear
  one** (3.25e−02 against 6.00e−03). The table is *edge-sampled for linear
  interpolation* and its guard entry is the clamp value, so a 3-point
  Lagrange runs into that discontinuity. A table designed for quadratic
  interpolation was not measured and might do better; this one does not.
- **There is a 6.707e−04 step discontinuity in our `tanh` at x = 4, and it
  costs nothing to remove.** `tanh(4) = 0.9993293`, which is 32745 in Q1.15,
  but `fixed.LadderFx.tanh_fx` returns **32767** above the domain and the last
  bin interpolates toward 32767. Measured max error restricted to [0, 3.9]
  versus over [0, 4.0]:

  | entries | [0, 3.9] | [0, 4.0] |
  |---|---|---|
  | 16 | 6.00e−03 | 6.00e−03 |
  | 32 | 1.52e−03 | 1.52e−03 |
  | 64 | 4.08e−04 | **6.71e−04** |
  | 128 | 1.32e−04 | **6.71e−04** |
  | 256 | 6.42e−05 | **6.71e−04** |

  **Past 64 entries the clamp step is the entire error.** Widening the table
  beyond 64 buys nothing until the guard entry is changed to 32745 (or the
  domain extended). That is a one-constant change with no area cost, and it
  should be made *before* anyone pays 1792 ROM bits for 128 entries.

---

## 5. Decimation — we match the reference exactly, and neither filters

We run 2× oversampling, and `fixed.LadderFx.process` takes `y[3]` from the
**last sub-step** with no decimation filter, and holds the input across both
sub-steps with no interpolation filter. Naive 2×.

**Surge's `VintageLadder::Huov` does exactly the same thing**: its `process`
runs two sub-steps and `return outputOS[1];`. Surge's RK model does slightly
better — 4× with a 4-tap Lanczos-ish window (`windowFactors = {−0.0637, 0,
0.5732, 1}`, scaled by 1.5), described in its own comment as "a bit of a
hack... really we should do a proper little FIR".

`sst-filters` *does* ship `HalfRateFilter.h` — a polyphase all-pass half-band,
`M` = 1…6 stages, steep and soft coefficient sets — but **no filter in
`sst-filters` uses it.** It is Surge's synth-wide oversampler, not part of any
ladder. So on decimation quality we are identical to the implementation of the
same paper, and the honest statement is that *neither* of us filters, not that
we are behind.

---

## 6. `CutoffWarp.h` and `ResonanceWarp.h`

Nonlinear cutoff and resonance variants. `CutoffWarp` puts a saturator in the
loop selected by the low bits of the subtype — `stages = subtype & 3` and
`sat = (subtype >> 2) & 3` — choosing between `softclip_ps`, `fasttanhSSEclamped`
and others, with a per-subtype `lpNormTable` makeup gain and, for the OJD
subtypes, a resonance makeup of `1/sqrt(reso)`. Nothing here is closer to a
Minimoog than what we have; it is a menu of saturator placements. Worth
knowing it exists when the drive character is next argued about; nothing to
adopt today.

---

## 7. The errand: does `ddiakopoulos/MoogLadders` exist, and what is in it?

**Yes.** `github.com/ddiakopoulos/MoogLadders`, created 2012, last pushed
**2026-06-13**, 397 stars, default licence **Unlicense**, CI on three
platforms. Verified by fetching the repository tree, not from recollection.

**Ten ladder models**, one header each, no external dependencies:
`StilsonModel`, `HuovilainenModel`, `KrajeskiModel`, `MicrotrackerModel`,
`MusicDSPModel`, `OberheimVariationModel`, `ImprovedModel`,
`RKSimulationModel`, `SimplifiedModel`, `HyperionModel` (19.6 kB, the newest,
2025). Plus `LadderFilterBase.h`, `LadderFilterOversampledBase.h`,
`Oversampler.h`, `HalfBandFilter.h`, `NoiseGenerator.h`, `MoogUtils.h`, a
`RunFilters` example, and `assets/sample.wav`.

**It also ships its own validation suite**, which the coordinator's
recollection did not include and which is the most useful part:
`scripts/filter_verification.py` (71 kB) generates impulse, step, chirp, sine,
two-tone, white-noise and near-DC test signals, runs them through each filter,
and computes frequency response, phase, group delay, THD, IMD, spectrogram,
step metrics, RMS, PSD and **self-oscillation detection**, with
`scripts/dashboard_generator.py` (28 kB) producing an interactive HTML
dashboard.

**Two cautions before it is treated as a reference set:**

- **Licences are per model, and they are not all permissive.** The README's
  own table: Huovilainen is **LGPLv3** (from CSound) and "closed-source
  friendly: if dynamically linked"; `Simplified` is a custom licence and
  "No"; `MusicDSP` is suggested CC-BY-SA. The repository default is Unlicense
  but that does not cover those files. We implement Huovilainen **from the
  paper**, not from that code, so nothing here contaminates us — but anyone
  copying a header needs to read its own licence first.
- **The README states the filters "have not been rigorously verified for all
  combinations of cutoff, resonance, and sampling rate"** and warns of
  blow-ups at untested parameters. It is a collection of *candidates*, not a
  set of validated references.

**Which is the better reference set for #46?** They answer different
questions. `sst-filters` is better as a *reference implementation*: it ships
in a product, is exercised by users daily, has one consistent API and
oversampling wrapper, and includes the non-ladder family (`DiodeLadder.h`,
`K35Filter.h`, `OBXDFilter.h`, `TriPoleFilter.h`, `CytomicSVF.h`) alongside
the two Vintage Ladder models we already measured. `MoogLadders` is better as
a *candidate survey*: ten ladder topologies side by side in one readable style
with a ready-made analysis harness, which is exactly what "pick a ladder
variant" needs. **Use MoogLadders to choose, and `sst-filters` to check the
choice against something that ships** — and take neither on trust, because
this project already found that Surge's Vintage Ladder Type 2 cannot
self-oscillate and never reaches its own nonlinearity at any usable level
(§8.3 of `docs/discrimination.md`).
