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

