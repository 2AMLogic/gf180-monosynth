# Why 2× oversampling the oscillators made aliasing worse

Issue #80. **Explanation only — no fix is implemented here.**

Instrument: `model/alias_probe.py`. Locked in `model/test_moog_acceptance.py`
(five tests, 1.7 s). Raw signals, JSON and provenance under `build/alias/<commit>-…/`.

---

## The answer in one paragraph

**Oversampling worked. The rate reduction is what cost 22.4 dB, and it cost it
by folding down harmonics that only exist because the oscillator is running at
96 kHz.** At 96 kHz the corrected sawtooth reads −55.5 dB, which is that
estimator's floor — no resolvable aliasing at all, 12.8 dB *better* than the
−42.7 dB we ship at 48 kHz. Keeping the last sub-step then moves the entire
24–48 kHz band into the baseband, and that band holds 0.05 % of the signal's
power at note 40 — **−33.1 dB, which is exactly the number the decimated signal
reads.** The fold-down budget *is* the regression, to within 0.0–0.3 dB at every
note measured.

Nothing about PolyBLEP, fixed point, or our implementation is involved. A
mathematically exact band-limited sawtooth, summed from its Fourier series,
comes out of the same decimator **worse than ours** (−29.8 vs −33.1).

**The bounded conclusion: this implementation regressed for this identified
reason — a drop-decimator applied to a signal with a full harmonic series above
the target Nyquist. It is not a result about oversampling as a technique.** The
same oversampled signal through a 127-tap decimation filter reads −58.3 dB,
15.6 dB better than what we ship.

---

## Two structures, which must not be called by the same name

| | what runs at 96 kHz | how it returns to 48 kHz |
|---|---|---|
| **Chain A** — the #80 experiment | the **oscillator** (increment halved, PolyBLEP evaluated at 96 kHz) | keep the last sub-step |
| **Chain B** — what the voice **ships** | the **ladder's nonlinearity** only | keep the last sub-step |

Chain B is `VoiceFx._render` + `LadderFx.process`, both read and confirmed:
`_render` calls `o.render(n, inc)` with the **base-rate** increment whatever the
ladder is set to; `process` reuses the same input sample for all `self.os`
internal updates (sample-and-hold), computes `g` for the internal rate, and
returns after the last sub-step. There is no decimation filter.

    base-rate oscillator → sample-and-hold → oversampled nonlinear ladder → last sub-step

Neither chain is "a properly reconstructed, oversampled, filtered path", and
**the 9.6 dB regression belongs to chain A only.** Changing `LadderFx.os` does
not touch `OscFx`'s increment or reciprocal at all, so a PolyBLEP rate mismatch
was never available as a chain B mechanism.

---

## Chain A: the four points

Sawtooth, 0.5 s, `inharmonic_fraction_db` at guard 5, measured at the rate each
signal is actually at. `floor` is the same estimator on an **analytic**
band-limited sawtooth — a signal with no inharmonic content by construction — so
every reading can be read against what "nothing resolvable" looks like there.

| note | f0 | floor | **P1** naive 48k | **P2** blep 48k | **P3** blep 96k | **P4** dropped to 48k | P2→P4 | above 24 kHz in P3 |
|---|---|---|---|---|---|---|---|---|
| 40 | 82.4 | −55.6 | −27.5 | **−42.7** | **−55.5** | **−33.1** | **−9.6** | **−33.1** |
| 52 | 164.8 | −53.7 | −23.8 | −39.7 | −42.6 | −30.0 | −9.6 | −30.3 |
| 64 | 329.6 | −55.9 | −20.8 | −36.6 | −39.7 | −27.0 | −9.7 | −27.2 |
| 76 | 659.3 | −53.9 | −17.8 | −33.7 | −36.6 | −24.0 | −9.8 | −24.2 |
| 88 | 1318.5 | −54.8 | −14.8 | −31.0 | −33.8 | −21.1 | −9.9 | −21.3 |
| 100 | 2637.0 | −53.3 | −11.9 | −28.5 | −31.0 | −18.2 | −10.3 | −18.5 |

Read the transitions:

- **P1 → P2** PolyBLEP removes 15.2–16.6 dB. Working as designed, at every register.
- **P2 → P3** oversampling **improves** the correction by 12.8 dB at note 40 (to
  the floor) and 2.5 dB at note 100. *The aliasing does not enter here.*
- **P3 → P4** −22.4 dB at note 40. **The whole regression enters at the rate
  reduction, and nowhere else.**

And the last column closes it quantitatively: **the share of P3's power sitting
in harmonics above 24 kHz equals the decimated reading** at every note (−33.1 vs
−33.1; −18.5 vs −18.2). Dropping every other sample maps each harmonic
`k·f0 > 24 kHz` to `48 kHz − k·f0`, which is not a multiple of `f0`, so the
whole band lands inharmonically in the baseband. That band is not "aliasing we
gained and lost" — at 48 kHz those harmonics are **not in the signal at all.**
Oversampling created them; the drop-decimator aliased them.

The closed form agrees. For an ideal saw the folded share is
`Σ_{k>K} k⁻² / Σ_{k≤K₂} k⁻²` with `K = ⌊24000/f0⌋`, `K₂ = ⌊48000/f0⌋` — **−29.8 dB
at note 40, −14.9 dB at note 100**, computed with no FFT anywhere and matching
the estimator to 0.01 dB.

### All four hypotheses, tested

| # | hypothesis | verdict | evidence |
|---|---|---|---|
| 1 | the correction was computed for one rate, applied at another | **ruled out** | `blep_fx` decides its window with `ph < inc` and scales by `1/inc`, so it is one sample per side *at whatever rate*. Measured at six registers: peak ratio 1.0000, window 0.99/0.99 samples per side, 1.99 corrected samples per wrap — identical at both rates. PolyBLEP's gain is 15.2–16.6 dB at 48 kHz and 15.7–16.2 dB at 96 kHz. |
| 2 | the naive decimator folds back what oversampling gained | **right mechanism, wrong words** | It does not fold back a gain; it folds down harmonics that only exist at the higher rate. It is 22.4 dB at note 40, not 9.6 — the 9.6 is the net after oversampling's 12.8 dB improvement. See below for why Surge's Huovilainen survives the same decimator. |
| 3 | fixed-point interaction, more quantisation events | **ruled out** | The same PolyBLEP in float64 — no Q1.15, no reciprocal approximation, no saturation — regresses **identically** (within 0.1 dB at every note). |
| 4 | something in how we implemented it | **ruled out, and inverted** | An exact additive band-limited sawtooth through the same decimator reads **−29.8 dB against our −33.1**: 3.3 dB *worse* than ours, because PolyBLEP's two-sample residual attenuates the top of the oversampled band, leaving less to fold. A perfect oscillator would have regressed more. |

---

## Chain B: why the same decimator is harmless where we already use it

Issue #80 correctly flagged that Surge's Huovilainen returns `outputOS[1]` and
does not have our problem — so "naive decimation is bad" cannot be the whole
story. It is not. Sine drive, cutoff 8 kHz, res 0, drive 2.0:

| note | B1 source 48k | B2 S&H input 96k | B3 sub-steps 96k | B4 output 48k | **B3→B4** | above 24 kHz in B3 |
|---|---|---|---|---|---|---|
| 40 | −57.0 | −50.3 | −56.7 | −56.7 | **−0.00** | −90.1 |
| 64 | −57.7 | −39.3 | −57.0 | −57.0 | **−0.04** | −78.2 |
| 100 | −52.2 | −21.3 | −50.6 | −50.2 | **−0.48** | −62.1 |

**The rate reduction costs nothing here — 0.0 to 0.5 dB.** The difference is not
the decimator; it is what is sitting above 24 kHz when the decimator runs. After
a four-pole lowpass, −62 to −102 dB. After an oscillator, −33 to −18 dB. That is
a 30–70 dB difference in the fold-down budget, and it is the entire reason the
same operation is free in one place and ruinous in the other.

Two details worth keeping:

- **The sample-and-hold's images are large and cost nothing.** B2 shows −50 to
  −21 dB of image energy introduced by holding each sample across both
  sub-steps. It is harmless because `repeat(x, 2)[1::2] == x` **exactly** —
  asserted in the table — so in a linear path hold-then-keep-the-last-sub-step
  is the identity. The images only matter to the extent the nonlinearity
  intermodulates them.
- **A higher-rate render of this ladder is a different filter.** The feedback
  path is a half-sample delay at the *internal* rate, so its phase moves with
  the rate: `k_onset` at 8 kHz goes 4.769 (2×) → 4.119 (16×), 13.6 %, and the
  self-oscillation frequency moves 8010 → 7474 Hz (−120 cents). The converged
  reference here retunes `k` through `k_onset` and reports the residual
  harmonic-amplitude difference (0.3–2.7 dB at res 0); no aliasing claim in that
  table is smaller than it. **Anyone proposing to raise the ladder's oversample
  ratio has to retune, and that is a separate decision from #80.**

`B1 → B4` crosses a filter, so it mixes a spectral-shape change with aliasing —
a lowpass removes harmonic energy, which raises an inharmonic *fraction* with no
new aliasing. It is printed but **not quoted**. The load-bearing comparisons are
the ones that hold the signal fixed: `B3` vs `B4`, and `B4` vs a filtered
decimation.

---

## The estimator was validated before any of this was quoted

Three independent checks, in the regime this actually uses — hundreds of
harmonics, not the eleven `model/test_audio_measure.py` covers:

1. **A dense analytic band-limited sawtooth**, which has no inharmonic content:
   the reading is the floor, −53.3 to −55.9 dB depending on note. *Not* the
   constant −54 dB the module docstring quotes; it moves with f0 and record
   length, which is why it is measured per row.
2. **A planted inharmonic comb** carrying a known share: read back to **0.02 dB**
   at −20, −30 and −40 dB, at three notes.
3. **A drop-decimated analytic sawtooth**, whose alias content is computable in
   closed form from the Fourier coefficients and the guard rule with no FFT
   anywhere: agreement to **0.01 dB** at three notes.

---

## What the explanation implies, and what it costs

Stated, not implemented — the fix is the next task.

**The direction is a decimation filter, not a longer correction.** The
oversampled oscillator is already clean at 96 kHz; the only thing missing is the
filter that should precede the rate reduction. A float64 bound, half-band FIRs
(order % 4 == 3, so `(order+1)/4` multiplies per output sample), monotone as
required:

| note | ship (P2) | drop | hb7 | hb11 | hb15 | hb23 | hb31 | hb47 | hb63 | floor |
|---|---|---|---|---|---|---|---|---|---|---|
| 40 | −42.7 | −33.1 | −41.2 | −43.4 | −44.5 | −46.0 | −47.0 | −48.5 | −49.6 | −55.6 |
| 64 | −36.6 | −27.0 | −35.1 | −37.4 | −38.4 | −39.9 | −40.9 | −42.3 | −43.2 | −55.9 |
| 100 | −28.5 | −18.2 | −26.8 | −29.7 | −31.5 | −34.3 | −36.9 | −42.1 | −46.7 | −53.3 |

Reading it: **an 11-tap half-band (3 multiplies per output sample) is
break-even** with what we ship. Everything past that is profit, and **the profit
grows with pitch** — 6.9 dB at note 40 but 18.2 dB at note 100 for a 63-tap
half-band — which is the exact shape of #61, where our defect worsens 2.8 dB per
octave and Surge is flat.

That is the result #61 should take from this: the thing our aliasing is most
sensitive to is band-limiting *near the output Nyquist*, and oversampling plus a
real decimator attacks it where it is worst. Whether that beats a higher-order
PolyBLEP per multiply is not answered here.

**Cost is deliberately not quoted.** These are float64 diagnostics; a half-band
tap count is not an area number, and the binding constraint is the 256-clock
sample deadline with both datapaths inside it, not area (DR 0014). Costing
belongs with the implementation.

---

## Wrong before it was right

One measurement in this work was wrong first, caught by a control rather than by
inspection, and is recorded here because that rate is how a reader calibrates
everything above.

**Chain B's first operating point was invalid.** Drive 4.0 overflows the
ladder's 24-bit input word by 0.34 dB, so the probe was measuring the hard clamp
rather than the nonlinearity — it read −34 dB of "aliasing" at note 100 that did
not move with the tanh table size (16 vs 128 entries) or with the oversample
ratio (2× vs 16×), which is what aliasing cannot do. `assert_drive_headroom` now
computes the headroom and **REFUSES** at or below zero. Drive 2.0 leaves 5.68 dB
and still drives the tanh past its domain edge.

A second reading was corrected without ever being quoted: the `resp` column
compared harmonic amplitudes including the **even** harmonics, which a symmetric
nonlinearity does not produce — a ratio of two numbers at the window floor,
reading as an 18 dB "response difference". It now uses only harmonics the
reference actually has. This is the same shape as the 25 dB of separation that
turned out to be window leakage.

---

## Scope

Chain A's numbers are the sawtooth. Every other discontinuous shape shares
`blep_fx` and the same fold-down argument applies to them, but they were not
swept. Chain B was measured at one cutoff (8 kHz) with sine and sawtooth drive,
res 0 and res 0.85. The decimator table is float64 and is a bound, not a design.
