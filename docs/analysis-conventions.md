# Analysis conventions

**What established practice actually is for the two kinds of measurement this
project makes, where our code departs from it, and — where there is no
established practice — that there is none.**

Written after #101: a **6.07 dB** error in a metric with a **3.0 dB** tolerance,
caused by *prepending digital silence*, an operation that cannot change what the
machine did.

---

## How to read this document

This repository's central failure mode is the confident unsourced number. Every
claim below carries one of three tags, and they are not decorative:

| tag | means |
|---|---|
| **[S]** | **Sourced.** A specific document says this. The link is in *Sources* and the claim is paraphrased no further than it has to be. |
| **[M]** | **Measured here.** Produced by the script in appendix A, which runs in seconds and can be re-run. A number, not an opinion — but on a *synthetic* signal, not a real one. |
| **[R]** | **Reasoning.** My inference. No source says this. It may be wrong. |

An **[R]** paragraph is not a weaker **[S]** paragraph. It is a different kind of
thing, and a conventions document that blurs the two is worse than no document.

**Search budget note.** This document was researched with the session's WebSearch
budget already exhausted (200/200). Sources below were reached by direct fetch of
URLs known in advance. That biases the source list toward primary documentation
(SciPy, reference implementations) and against the survey literature. **Sections
5, 6 and 7 are consequently thinner than sections 1–4, and say so.**

---

## 0. The failure this document exists because of

**[S]** `scipy.signal.sosfiltfilt` defaults to `padtype='odd'`. The default pad
length is

```
padlen = 3 * (2*len(sos) + 1 - min((sos[:,2] == 0).sum(), (sos[:,5] == 0).sum()))
```

and `padtype=None` means "no padding is used". The `filtfilt` documentation adds
that padding helps when "the filter's transients have dissipated by the time the
actual data is reached", and that "in general, transient effects at the edges are
unavoidable".
([sosfiltfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html),
[filtfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.filtfilt.html))

**[M] The pad is longer than #101 and #103 state.** Both issues quote "~12–15
samples ≈ 0.25–0.3 ms at 48 kHz". That is the figure for a 4th-order **low- or
high-pass** (2 sections → `padlen` 15 → 0.312 ms at 48 kHz). The filter in
`audio_measure.band_energy` and in `run_case._bandpass` is a 4th-order
**band-pass**, which is 8th order overall — **4 sections → `padlen` 27 → 0.562 ms
at 48 kHz, 0.612 ms at 44.1 kHz.** Every "how much lead is enough" number derived
from 0.3 ms is therefore about half what it should be. This matters: `prepare()`
grants a 1 ms lead, which clears 0.562 ms — but only when it grants it at all.

**[R] The asymmetry is a clamp, not a choice.** `prepare()` computes
`i = argmax(|x| > 0.02*peak)` and trims to `lead = max(0, i - 1 ms)`. The `max(0,
…)` is the whole bug. #101 records that the Fischer references cross 2 % of peak
at **sample 7**, so `i - 1 ms` is negative and the clamp fires: the reference gets
a **0.16 ms** lead, shorter than the 0.562 ms pad, so the odd extension reflects
through a near-zero first sample and *reaches into the strike behind it*. Our
renders lead with 10 ms of digital silence, so they get the full 1 ms of true
zeros and the extension is exactly zero. **The two sides of every drum comparison
are filtered under different boundary conditions**, and nothing in the result
record says so.

> Note for whoever reconciles the issues: #101 ("references … `lead = 0`") and the
> code agree with the reading above. #103's prose — "the reference's window
> 0.16 ms **before** onset (benign) and ours 1.00 ms **after** onset (large
> edge)" — puts the artefact on our side instead. Both cannot be right. The code
> says the short lead is the reference's. **Nothing in this document depends on
> which side it is**, only on the fact that the two differ.

---

## 1. Onset alignment

### What the field does

**[S] There is a standard *detector* family and it is not what we use.** The
common tooling (librosa, `aubio`, the MIR literature) detects onsets from a
**spectral-flux novelty function** computed on a short-time spectrum, then
peak-picks it — not from a fixed amplitude threshold. librosa's `onset_detect`
additionally ships `onset_backtrack`, which exists precisely to move a detected
onset *earlier*, to the preceding local minimum of energy. (I was unable to fetch
the librosa page — the documented URL 404s at both `/doc/latest/` and `/doc/main/`
— so this is stated from knowledge of the API and is **downgraded to [R] until
someone re-fetches it**.)

**[R] But detection is the wrong question here.** Onset *detection* is for finding
unknown events in a stream. We have one strike per file and we know it is there.
What we need is **alignment** — a common time origin for two recordings of the
same event — and the two problems have different error criteria. A detector that
is right to ±10 ms is excellent; an alignment that is wrong by 10 ms invalidates an
attack-time comparison.

**[R] For alignment of two recordings of the same event, cross-correlation is the
obvious instrument and we do not use it.** It is what is used for time-delay
estimation generally, it is sub-sample accurate with parabolic interpolation on
the correlation peak, and it uses the whole waveform rather than one threshold
crossing. Its weakness is exactly our case: our render and a 1981 hardware
recording are **not** the same waveform, so the correlation peak is broad and its
location depends on which band dominates. **I could not find a source saying
either "cross-correlate" or "threshold" is standard for percussive A/B spectral
comparison, and I do not believe one exists.** This is genuinely unsettled.

**[R] A fixed fraction-of-peak threshold — what `prepare()` uses at 2 % — is
level-dependent in a way that bites here.** 2 % of peak is −34 dB. On a voice with
a slow rise (a tom body) that crossing is far later, in absolute time, than on a
voice with a click (a rimshot). So the trim point is not a fixed offset from the
physical onset; it varies per voice *and* per side, since our render and the
hardware have different rise shapes. That is a second, independent misalignment on
top of the clamp in §0.

### Pre-onset lead

**[R] No source I reached states a conventional pre-onset lead.** What I can say
is that the requirement is *derivable* rather than conventional, and the
derivation gives a number:

**[M] The lead must exceed the analysis filter's pad, and a little more.** With a
4th-order band-pass (`padlen` = 27 samples) on a synthetic conga-like decay, the
band split reads:

| lead | 0 smp | 7 smp (0.15 ms) | 27 smp (0.56 ms) | 48 smp (1 ms) | 96 smp (2 ms) | 480 smp (10 ms) | 200 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| `padtype='odd'` (our default) | −38.04 | −35.10 | −28.82 | −28.26 | −27.98 | −27.87 | −27.87 |

**A 10.2 dB swing from prepending silence alone.** It converges once the lead
exceeds the pad, and is settled to 0.12 dB by 2 ms and to 0.001 dB by 10 ms.
(#101 measured **+6.07 dB** on the real conga case; the sign differs from the
synthetic case above because it depends on which band the manufactured edge lands
in. The magnitude is the same order.)

**[R] Recommendation, as an engineering bound rather than a convention: give both
sides at least 10 ms of true pre-onset lead, or 20× the filter's `padlen`,
whichever is larger** — and *state the lead in the result record* so a reader can
check it rather than trust it.

**[M] Once both sides have adequate lead, alignment precision barely matters for
band-energy metrics.** Sliding a 5 ms-lead window by ±1 ms moves the filtered band
split by **0.005 dB** and a rectangular-FFT split by ~0.1 dB. This is the useful
inversion: **the lead is load-bearing, the alignment is not** — for *energy*
metrics. It is emphatically not true for attack time, where the alignment *is* the
measurement.

---

## 2. Zero-phase filtering on transients

### Is `filtfilt` appropriate for a signal that starts at its peak?

**[S] The SciPy documentation states the precondition and we violate it.** Padding
works when "the filter's transients have dissipated by the time the actual data is
reached". A segment beginning at full amplitude has no dissipation region at all.
SciPy documents no warning specific to transients beyond "in general, transient
effects at the edges are unavoidable", and offers `padtype=None` as the escape.
([filtfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.filtfilt.html))

**[R] There are two defensible camps and they are not reconcilable by argument.**

- **Zero-phase (`filtfilt`).** Used because it does not smear a transient forward
  in time, which is what a causal filter does and what would corrupt an attack or
  decay measurement. In *room acoustics* this is the settled answer: band-filtering
  an impulse response for reverberation analysis is conventionally done
  time-symmetrically so that the filter's own ringing is not read as part of the
  room's decay. **[R] — I know this as ISO 3382-1 Annex practice but could not
  fetch the standard, which is paywalled. Treat as unsourced.**
- **Causal (`sosfilt` / `lfilter`).** Used because it is what a physical filter
  does, it is exactly invariant to prepended silence, and it has no acausal
  precursor. It smears energy forward, which for a decay measurement is precisely
  the contamination the zero-phase camp is avoiding.

**[M] Both camps are right about the other one.** On the same synthetic signal,
prepending silence:

| method | 0 lead | 0.15 ms | 0.56 ms | 1 ms | 10 ms | spread |
|---|---:|---:|---:|---:|---:|---:|
| `padtype='odd'` | −38.04 | −35.10 | −28.82 | −28.26 | −27.87 | **10.18 dB** |
| `padtype=None` | −30.66 | −29.23 | −28.82 | −28.26 | −27.87 | **2.79 dB** |
| `padtype='even'` | −24.96 | −25.51 | — | −28.26 | −27.87 | 3.29 dB |
| causal `sosfilt` | −23.01 | −23.01 | −23.01 | −23.01 | −23.01 | **0.000 dB** |
| rectangular-FFT Parseval | −27.23 | −27.47 | −27.20 | −27.04 | −27.03 | **0.44 dB** |

Three things fall out of this table:

1. **`padtype=None` is not a fix.** It removes the *pad*, not the filter's own
   start-up transient — 2.79 dB of residual non-invariance. #103 says this and the
   measurement agrees. Once the lead exceeds `padlen`, `'odd'` and `None` are
   **identical** (the pad is then all zeros), so choosing `None` buys nothing that
   an adequate lead does not already buy.
2. **Causal filtering is perfectly invariant to prepended silence** — and answers a
   different question, 4.9 dB away. That is not an error in either: zero-phase
   filtering applies |H(f)|² to the amplitude and so |H(f)|⁴ to the energy, where a
   causal single pass applies |H(f)|². **Neither is the brick-wall band energy the
   metric's name claims.** [R]
3. **Appending silence is harmless** (0.02 dB) because these signals already end in
   near-silence. The whole defect lives at the start. [M]

**[R] Recommendation: keep zero-phase, fix the lead.** The reason is not that
zero-phase is more correct — it is that our decay metrics (§4) are the ones with
the most to lose from causal forward-smearing, and an adequate lead makes the
padding question disappear entirely. But **`padtype` and the achieved lead must be
recorded in the result**, because the number is not reproducible without them.

---

## 3. Band energy

### What the field does

**[R] Three methods are in use and the choice is not settled by any standard I can
point to for *this* purpose:**

1. **Octave / third-octave filter banks.** Standardised — IEC 61260 / ANSI S1.11 —
   and those standards specify Butterworth-class band-pass filters with defined
   tolerance masks. **This is the closest thing to a sanction for our Butterworth
   split, and it is a partial one:** the standards govern *steady-state* band
   analysis for acoustics, with defined band edges (octave, third-octave), not
   arbitrary two-way splits on a 15 ms transient. **[R] — I could not fetch either
   standard; both are paywalled.**
2. **Parseval over FFT bins.** Exact, by theorem, over the analysis window.
3. **Constant-Q / wavelet.** Used where time resolution must scale with frequency;
   the usual choice for transient onsets in MIR.

### What we do, and the argument in the docstring

`band_energy` filters rather than summing bins, and the docstring gives a specific
reason: `spectrum` applies a Hann window, so on a decaying voice it weights the
middle of the file and reports the tail's spectrum — "on a real TR-808 cymbal the
two disagree by a factor of four in the 5–9 kHz band".

**[M] That observation is real and enormous — and it is an argument against the
Hann window, not against the FFT.** On the synthetic decay, a 150 ms analysis
window:

- rectangular-FFT band split: **−27.23 dB**
- Hann-windowed FFT band split: **−82.50 dB**

**55 dB of error.** The Hann window's first 10 ms are ~0.4 % of full weight, and
that is where the entire strike lives. But Parseval holds *exactly* for the
rectangular window — verified to 7 significant figures in appendix A — and a
rectangular window is the correct one when the quantity wanted is **the energy in
this window**, not a spectral estimate of a stationary process. **[R] The
conclusion drawn in the docstring ("therefore filter") does not follow from the
evidence given ("Hann is wrong"). The evidence supports "therefore do not
window".**

### Tradeoffs on a short decaying signal

**[R]**

| | Butterworth `sosfiltfilt` | rectangular-FFT Parseval | constant-Q |
|---|---|---|---|
| invariant to prepended silence | **no** (10 dB) | yes (0.4 dB) | no |
| exact band definition | no — |H|⁴ skirts, 4th-order rolloff bleeds across the split | **yes**, to one bin | no |
| needs a lead | **yes**, ≥ `padlen` | no | yes |
| sums to total energy | approximately | **exactly** | no |
| cost on a 15 ms signal | fine | fine | fine |
| resolution at 20 Hz on a 15 ms window | filter cannot settle | 67 Hz bins — **cannot resolve a 20/400 Hz split at all** | better |

**[R] The last row is the real tradeoff and it cuts toward the filter for short
windows.** A 15 ms rectangular FFT has 67 Hz bins, which cannot place a band edge
at 400 Hz to better than ±33 Hz, and cannot represent a 20 Hz lower edge at all.
Our windows are 100–150 ms (7–10 Hz bins), where this is a non-issue — but a
metric taken over a 15 ms rimshot window would be, and the choice should be made
per-window rather than globally.

---

## 4. Decay time

### Is Schroeder backward integration the right instrument for a drum tail?

**[S] The T20 construction we use is the standard one, verbatim.** Two independent
reference implementations agree with `audio_measure.schroeder_t20` on every
detail:

- `python-acoustics`' `t60_impulse` uses `sch = cumsum(signal[::-1]**2)[::-1]`,
  normalised to its maximum and read in dB, with **T20 evaluated from −5 dB to
  −25 dB and multiplied by 3**; T30 from −5 to −35 (×2); EDT from 0 to −10 (×6).
  Band filtering before integration is an **8th-order Butterworth** octave or
  third-octave band-pass.
  ([acoustics/room.py](https://raw.githubusercontent.com/python-acoustics/python-acoustics/master/acoustics/room.py))
- `pyroomacoustics`' `rt60` uses the same backward cumulative sum and starts the
  fit at "the −5 dB headroom point", `i_5db = min(where(energy_db < -5.0))`,
  extrapolating to −60 dB.
  ([pyroomacoustics/experimental/rt60.py](https://raw.githubusercontent.com/LCAV/pyroomacoustics/master/pyroomacoustics/experimental/rt60.py))

**[S]** The method is defined for rooms — ISO 3382-1 (performance spaces), -2
(ordinary rooms), -3 (open-plan offices) — and the −5 dB start exists to skip the
direct sound and early reflections.
([Reverberation](https://en.wikipedia.org/wiki/Reverberation))

**[R] Using it on a synthetic drum tail is a borrowing, and it is a reasonable
one, for a reason the docstring already gives:** for a single damped sinusoid the
backward-integrated curve's slope gives exactly `ln(10)·tau`, so T20 degenerates
to the physical time constant when the signal is a single exponential and
degrades gracefully when it is not. Nothing about the construction is
room-specific. **I found no source endorsing it for instrument decay and none
forbidding it.**

**[R] What the instrument literature uses instead, where a single mode is
involved,** is a least-squares fit of an exponential-plus-noise model to the
envelope, or a linear regression on the log envelope over a stated dB range.
(Karjalainen, Antsalo, Mäkivirta, Peltonen and Välimäki, *Estimation of Modal
Decay Parameters from Noisy Response Measurements*, AES 2002, is the paper I
would cite — **I could not reach it; the Aalto host refused the connection.
Unsourced.**)

### Three failure modes of our T20, measured

**[M] The noise-floor failure is guarded and the guard works.** Adding a noise
floor to a 40 ms-tau decay (exact T20 = 92.10 ms):

| floor | −100 | −80 | −70 | −60 | −50 | −40 dB |
|---|---:|---:|---:|---:|---:|---:|
| T20 | 92.11 | 92.11 | 92.15 | 92.57 | 97.18 | 1293.94 ms |
| error | 0.0 % | 0.0 % | +0.1 % | +0.5 % | **+5.5 %** | **+1305 %** |
| residual | 0.08 | 0.08 | 0.08 | 0.13 | 0.58 | **11.02 dB** |

The −40 dB case is refused by `_t20_ms`'s `MAX_T20_RESIDUAL_DB = 6.0`. The −50 dB
case is not, and is 5.5 % wrong — inside our 50 % time tolerance, so harmless
here, but it is the mechanism that produced the 4.5-second rimshot T20 that
`prepare()`'s docstring records.

**[M] The truncation guard does not do what it says.** `schroeder_t20` refuses
when `tail_db > hi_db - margin_db` (i.e. when the curve's last value is above
−35 dB), on the stated reasoning that "a decay cut while it is still sounding …
cannot keep going afterwards". **On a clean, noiseless record that test is nearly
vacuous**, because the backward integral of *any* finite record falls towards
−∞ at its last sample regardless of where it was cut:

| record length | 300 ms | 200 | 150 | 100 | 50 ms |
|---|---:|---:|---:|---:|---:|
| T20 | 92.11 | 91.90 | 89.65 | **75.19** | **40.74 ms** |
| error | 0.0 % | −0.2 % | −2.7 % | **−18.4 %** | **−55.8 %** |
| `tail_db` (the guard) | −122.8 | −101.0 | −90.2 | −79.3 | −68.1 dB |

**A 55.8 % error passes a guard that wants −35 dB and is seeing −68 dB.** The
guard only bites when there is a noise floor to stop the integral falling. This
is a real defect, it is not the one #101 found, and it matters directly: the
`prepare()` docstring notes that three reference recordings are editor-trimmed at
20–40 ms. **[R] The right guard is a length criterion — refuse unless the record
extends some multiple of the fitted T20 past the −25 dB point — not a level
criterion on `tail_db`.** In room acoustics the equivalent problem is solved by
Lundeby's iterative truncation-point method; I could not source it.

**[M] On a genuinely two-exponential envelope, T20 reports the slow component.**
A 40 ms head plus a 300 ms tail at various tail amplitudes:

| tail amplitude | 0.50× | 0.20× | 0.05× |
|---|---:|---:|---:|
| T20 | 660.6 ms | 606.4 ms | 234.5 ms |
| residual | 0.59 | 2.93 | 3.76 dB |

All three pass the 6 dB residual guard, and all three report something between 2.5×
and 7× the head's decay. **[R] That is not a bug — it is what backward integration
means — but "T20" and "how long the drum sounds" are then different quantities, and
our tolerance of 50 % on time is doing a lot of work to hide the difference.**

---

## 5. Aliasing measurement

**This section is the least sourced in the document.** With WebSearch exhausted I
could not reach any virtual-analog paper's text. What follows is one bibliographic
record and then measurement and reasoning.

**[S] The canonical reference exists and is:** Vesa Välimäki and Antti Huovilainen,
*Antialiasing Oscillators in Subtractive Synthesis*, IEEE Signal Processing
Magazine **24**(2), 116–125, 2007.
([Aalto research portal](https://research.aalto.fi/en/publications/antialiasing-oscillators-in-subtractive-synthesis))
**I could not fetch its text**, so nothing below about what it contains is sourced.

**[R] What I believe the field does, offered as belief and not as fact:** the
virtual-analog literature reports oscillator aliasing as a **noise-to-mask ratio
(NMR)** in dB — aliased energy measured against a psychoacoustic masking threshold
derived from the wanted harmonics, with values below roughly 0 dB taken as
inaudible — and secondarily as an **A-weighted signal-to-noise ratio** measured by
comparing against a bandlimited (additive or high-oversampled) reference at the
same f0. Both differ from what we compute in the same way: they weight the aliased
energy perceptually, and they are referenced to a *synthesised alias-free
reference signal*, not to the total energy of the signal under test.

**[M] Our two aliasing estimators have floors that swing by 60 dB with f0, and one
of them reports a floor that is 35 dB worse than it needs to be.** On a purely
additive, alias-free saw at 48 kHz over a 0.5 s record — where the true answer is
"none" — the reading *is* the floor:

| f0 | on a bin? | `inharmonic_fraction_db` | `foldback_alias_db` |
|---|---|---:|---:|
| 110.0 Hz | yes | **−112.92** | refused (image/harmonic collision) |
| 111.0 Hz | no | **−53.39** | refused |
| 111.3 Hz | no | −54.07 | refused (images cover the spectrum) |
| 261.626 Hz | no | −55.87 | refused |
| 440.0 Hz | yes | **−113.21** | **−126.44** |
| 441.0 Hz | no | **−53.38** | **−65.11** |

**A 1 Hz change in f0 moves the floor by 60 dB.** The docstring's stated "about
−54 dB" floor is the honest off-bin figure and is correct as far as it goes; what
it does not say is that the same estimator reads −113 dB when f0 happens to land
on a bin centre, which is not a better measurement, it is the same measurement
with the leakage removed by coincidence. **[R] A floor quoted as a constant is the
#92 failure again.**

**[M] The floor is a window choice, and the better window is already in the file.**
`inharmonic_fraction_db` calls `spectrum`, which applies a Hann window.
`audio_measure._bh4` (4-term Blackman-Harris, written for
`windowed_tone_amplitude`) is 35 dB better at the same guard width, and **changes
the measured aliasing figure by 0.00 dB**:

| f0 | window | guard | floor | naive saw reads | headroom |
|---|---|---:|---:|---:|---:|
| 441 Hz | Hann | ±5 | −53.38 | −19.53 | 33.8 dB |
| 441 Hz | Hann | ±9 | −65.61 | −19.55 | 46.1 dB |
| 441 Hz | **Blackman-Harris** | ±5 | **−88.44** | −19.53 | **68.9 dB** |
| 441 Hz | **Blackman-Harris** | ±9 | **−94.78** | −19.55 | **75.2 dB** |

**[R] Recommendation: (a) window with `_bh4`, not Hann; (b) measure the floor for
every reported number by running the same estimator, at the same f0 and record
length, over a synthesised alias-free saw, and report floor and headroom beside
the value.** The repository already does exactly (b) in one place —
`harmonic_signature` measures a floor at four off-harmonic offsets and returns
`None` for any harmonic within 6 dB of it. That pattern is right and is not
applied to the aliasing estimators.

**[M] `foldback_alias_db` is usable over a narrow band of f0 only.** It refused at
110, 111, 111.3, 261.6, 1000 and 2000 Hz — for collisions, occupancy, or too few
images — and succeeded at 440/441 Hz. That is correct behaviour (refusing beats
guessing) but it means the metric exists for roughly a fifth of the musical range
at these settings, and a comparison built on it cannot be swept across pitch.

---

## 6. Sustained tones: harmonics, cutoff, resonance, pitch

**[R] Little of this section is contested and little of it is written down.** The
conventions below are, as far as I can tell, universal practice in audio
measurement rather than anything specific to virtual analog:

- **Steady-state, not transient.** Measure after the envelope has settled; state
  the window.
- **Stepped sine, not impulse, for anything nonlinear.** An impulse response
  presumes linearity and cannot state the drive level it was taken at. Our
  `tone_amplitude` docstring makes exactly this argument and
  `reference_compare.py` follows it. **This is the single place where our practice
  is clearly ahead of the casual norm**, which is to take one FFT of a sweep and
  call it the filter's response.
- **Cutoff as the −3 dB point relative to a stated passband reference**, and
  resonance as either the peak height in dB above that reference or as
  `f_peak / bandwidth`. **[R] The two definitions of Q are not interchangeable and
  a measurement that does not say which it used is not reproducible.** `corner_3db`
  takes `ref_band`; `bandwidth_q` and `resonant_peak` are separate functions,
  which is the right shape.
- **Pitch from a long window, not a short one.** Our `refine_f0` /
  interpolated-zero-crossing approach is exact for a steady periodic signal and
  is the conventional choice; `dominant_frequency`'s parabolic interpolation on
  the log magnitude is the conventional FFT fallback and is accurate to a small
  fraction of a bin for an isolated peak.

**[R] One departure worth naming:** `harmonic_signature` reports harmonics in dB
relative to the fundamental, with a measured floor. The more common report in the
literature is a **THD** or **THD+N** percentage, or a harmonic-amplitude table
relative to *full scale*. Per-harmonic dB-relative-to-fundamental is more
informative and less comparable. Since our purpose is A/B against a named software
reference rather than publication, **[R] keep it** — but a THD figure is cheap to
add from the same numbers and would make the results legible to anyone outside
this repository.

---

## 7. Analog drum machines and virtual analog specifically

**[S] The TR-808 modelling literature exists and is by one group.** Kurt James
Werner, Jonathan S. Abel and Julius O. Smith III published, all in 2014:

- *A Physically-Informed, Circuit-Bendable, Digital Model of the Roland TR-808
  Bass Drum Circuit* — DAFx-14, Erlangen
- *The TR-808 Cymbal: a Physically-Informed, Circuit-Bendable, Digital Model* —
  40th ICMC / 11th SMC, Athens
- *More Cowbell: a Physically-Informed, Circuit-Bendable, Digital Model of the
  TR-808 Cowbell* — AES 137th Convention, Los Angeles

([author's publication list](https://ccrma.stanford.edu/~kwerner/))

**I could not fetch any of the three PDFs** — the DAFx-14 host, the DAFx paper
archive's per-year pages and the author's own paper directory all 404 from here.
**So I cannot tell you what measurement methodology they used, and this document
will not guess.** Getting these three PDFs is the single highest-value follow-up
to this research, because they are the only published work that does precisely
what we are doing — comparing a digital model of a TR-808 voice against the
circuit — and if they state an alignment or windowing convention, that convention
should simply be adopted.

**[R] What I can say about their approach from general knowledge, flagged as
unverified:** the "physically-informed" family models the circuit (bridged-T
oscillator, envelope, VCA) rather than fitting the sound, and validates by
comparison against SPICE simulation of the schematic and against recordings, with
spectrogram overlays and partial-frequency tables rather than scalar error
metrics. If that is right, then **there is no scalar-metric convention in this
literature to copy** and our band-ratio/T20/partial-frequency scorecard is a local
invention — a defensible one, but ours.

**[R] On the Moog ladder,** the reference points are Stilson and Smith's *Analyzing
the Moog VCF with Considerations for Digital Implementation* (CCRMA, 1996) and
Huovilainen's *Non-Linear Digital Implementation of the Moog Ladder Filter*
(DAFx-04). I fetched the former's PDF and it did not decode to text. **The
methodological point I would expect from them, unverified:** the ladder's
resonance and cutoff are **level-dependent by design**, so a transfer function is
meaningless without a stated drive, which is the argument our `tone_amplitude`
docstring already makes independently.

---

## 8. What we do → what the field does → change or keep

Ordered by how much the change would move a number on the board.

| # | what we do now | what the field does | verdict | reason |
|---|---|---|---|---|
| 1 | `prepare()` trims to `max(0, onset − 1 ms)`. The `max(0, …)` clamp fires on the Fischer references (onset at sample 7), so **the two sides are filtered with different amounts of pre-onset lead** | no stated convention found; the *requirement* is derivable: lead > filter `padlen` | **CHANGE** | **[M]** 10.2 dB of swing from prepended silence alone; #101 measured 6.07 dB on a real case against a 3.0 dB tolerance. Give both sides ≥ 10 ms of true lead, and **refuse** (not clamp) when a recording cannot supply it |
| 2 | `padlen` assumed ~12–15 samples (#101, #103) | — | **CHANGE** | **[M]** that is the low/high-pass figure. Our band-pass is 4 sections → **27 samples, 0.562 ms @ 48 k**. Every lead budget derived from 0.3 ms is half what it should be |
| 3 | `sosfiltfilt` with default `padtype='odd'` | `python-acoustics` defaults `bandpass` to **causal** (`zero_phase=False`) and only `octavepass` to zero-phase | **KEEP**, but record it | **[M]** once the lead exceeds `padlen`, `'odd'` and `padtype=None` are **identical**; causal is exactly invariant but answers a different question (|H|² vs |H|⁴ energy weighting). Fixing the lead makes the choice moot. `padtype` and achieved lead belong in the result record |
| 4 | `schroeder_t20` guards truncation with `tail_db > −35 dB` | ISO 3382 T20 = −5 to −25 dB ×3, SNR-based guards; Lundeby truncation-point iteration | **CHANGE** | **[M]** the guard is nearly vacuous on a clean record: a 100 ms cut of a 92 ms T20 reads **−18.4 % error** while `tail_db` shows −79 dB. Add a **length** criterion: refuse unless the record runs ≥ 2× the fitted T20 past the −25 dB point |
| 5 | `inharmonic_fraction_db` windows with Hann; floor documented as "about −54 dB" | alias-free synthesised reference at the same f0; NMR or A-weighted SNR **[R, unsourced]** | **CHANGE** | **[M]** the floor is **−53 dB off-bin and −113 dB on-bin** — a 60 dB swing, so it is not a constant. Swapping Hann for the `_bh4` already in the file moves the floor to **−88 dB and the answer by 0.00 dB**. Measure and report the floor per call, as `harmonic_signature` already does |
| 6 | `band_energy` filters "because FFT bins are Hann-windowed and weight the tail" | Parseval over a **rectangular** FFT; IEC 61260 Butterworth filter banks for octave bands **[R, paywalled]** | **KEEP** (for our window lengths) | **[M]** the Hann observation is real and worth **55 dB** on a decaying signal — but it argues against the *window*, not the FFT; rectangular Parseval is exact (verified to 7 s.f.) and invariant to prepended silence to 0.44 dB. Keep the filter because a 15 ms window gives 67 Hz bins, which cannot place a 400 Hz split. **Fix the docstring's reasoning, and use rectangular Parseval for any window under ~50 ms** |
| 7 | onset = first sample past **2 % of peak** | spectral-flux novelty + peak-picking, then `onset_backtrack` to the **preceding energy minimum** | **CHANGE the framing, keep the mechanism** | **[S]** librosa's default hop is 512 samples (23 ms at 22.05 k) — the standard detector is *coarser* than our threshold, so adopting it would be a downgrade for alignment. But `onset_backtrack`'s existence is the field telling us the same thing #101 did: **the window should open before the attack, not at it** |
| 8 | 44.1 k references vs 48 k renders, never resampled | — | **KEEP** | every metric is a frequency, a time or a ratio. #101 measured the rate difference at < 0.36 dB. But **[M]** `padlen` in *milliseconds* differs between the two rates (0.612 vs 0.562 ms), so a lead budget must be stated in samples-per-rate or set generously in ms |
| 9 | both sides peak-normalised | standard when comparing shape | **KEEP** | the Fischer set pinned LEVEL at maximum, so its inter-voice levels are not the machine's; original peak/RMS are already recorded |
| 10 | stepped-sine transfer at a stated drive for the ladder | — | **KEEP** | **[R]** this is better than the casual norm (one FFT of a sweep) and is the only correct choice for a level-dependent filter |
| 11 | attack = onset-to-peak of a short-time RMS envelope, per-voice window | MPEG-7 log-attack-time; Timbre Toolbox "weakest effort" thresholds **[R, unsourced]** | **KEEP**, state the window | the docstring already concedes the window-sized floor and `docs/drum-verification.md` already compares ratios rather than absolutes. That is the right handling of a known floor |
| 12 | nothing in the result record states the windowing convention | — | **CHANGE** | #103 asks for exactly this. A number that cannot be re-derived can only be re-trusted |

