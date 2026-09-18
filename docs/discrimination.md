# Can our digital 808 be told apart from a real one?

**Short answer: yes, easily, at every voice the corpus can adjudicate — and
three of our eight voices it cannot adjudicate at all.**

The useful part is not that answer. It is *how far* apart, in a unit the
design team can act on, and *which* three voices no freely licensed reference
material can currently settle.

Run it:

```
git clone --depth 1 https://github.com/tidalcycles/sounds-tr808-fischer /tmp/tr808-ref
.venv/bin/python model/discrimination_run.py --refs /tmp/tr808-ref \
    --out docs/img/discrimination --json /tmp/discrimination.json
.venv/bin/python -m pytest model/test_discrimination.py -q   # the harness checks itself
```

`model/test_discrimination.py` is the machinery and its self-tests,
`model/discrimination_run.py` the reproducible script. The Minimoog half (§8)
is `model/reference_compare.py` + `model/reference_rigs.py`, ground-truthed by
`model/test_reference_compare.py`; `model/moog_probe.py` is the older
settings-independent probe and **two of its published numbers were withdrawn
on 2026-09-18** — see §8.1 before quoting anything it prints.

---

## 1. Scorecard

| | |
|---|---|
| model revision rendered | `d9921a4` + `model/drums_fx.py`, `model/modal_fixed.py` from `origin/drums` `1e638ac` (the drums merge into main was still in flight; see §9). **Superseded: contract revision 6 changed five of the eight voices** — the snare's noise band and level, the cowbell's gating, tail and band-pass, the kick's f0 and its attack window, and the toms' pitch drop (`docs/drum-verification.md` §8, DR 0009, DR 0010). Every number below describes the kit as it was before those, so **re-run this study before quoting it**. Its conclusion that the attack carries most of the separability is what makes contract 17.20 — the excitation shape — the next thing to do, and none of these changes touch that. **Re-run 2026-09-18 on revisions 6 and 7**, same corpus, same split hash, arm `ours` only: knob-equivalent **SD 7.6 → 3.4** (balanced accuracy 1.000 → 0.938), BD 2.5, LT 6.7, OH 6.9, HT 7.2 (`docs/drum-verification.md` §8.6). So SD 8.8 was revision 5's snare, 7.6 is revision 6's, and 3.4 is revision 7's — the snare is no longer the worst voice, it is the second best. |
| reference | Fischer/Technopolis 1994, CC0-1.0 via TidalCycles, real TR-808 **s/n 103852**, individual voice outputs, 16-bit/44.1 kHz |
| unique source recordings | **68** (the 8 voices we implement), of 116 in the set |
| unique knob settings | 68 — the corpus has **exactly one take per setting** |
| law-fitting settings | 30 (knobs at 0.0 / 5.0 / 10.0) |
| held-out settings | **38** (any knob at 2.5 or 7.5) |
| generated comparisons | 76 held-out clip decisions, 38 paired ABX trials — *listed separately from the 68 recordings on purpose; they are not 76 independent observations* |
| classifier | L2 logistic regression, `C` by grouped inner CV on the fit split only |
| equivalence margin, pre-specified | 0.60 |
| held-out balanced accuracy, arm `ours` | **1.000** [0.95, 1.00] |
| paired ABX | **38 / 38** |
| positive controls | all pass (§4) |
| verdict | **known defect remains** (BD, SD); **no verdict — underpowered** (LT, HT, OH); **no verdict — corpus cannot test** (CH, CP, CB) |

---

## 2. The split, and the two different experiments

The control law that turns a knob position into register values is fitted on
**FIT_KNOBS = {0.0, 5.0, 10.0}** and then frozen. Everything reported as a
result is measured at **TEST_KNOBS = {2.5, 7.5}**, which the law has never
seen. A two-knob setting is held out if *either* knob is held out, so the 16
held-out bass-drum settings also test the law's separability assumption —
that is a claim about the circuit, not only about interpolation.

That split is what separates two claims which must never be conflated:

| | what the model is given | what a pass shows |
|---|---|---|
| **emulation** | knob positions and note events only; renders blind | the engine reproduces the **instrument** |
| **sound-matching** | the target recording, and a search for parameters | the engine can **reach** that tone |

Results at the fit settings are sound-matching and are never quoted as
emulation. **Every number in §3–§6 is emulation.** The Minimoog work in §8
could only ever have been sound-matching, and is labelled so.

Split hash and per-run revision hashes are written into
`/tmp/discrimination.json` by every run.

### The knob laws, and where they came from

Which physical quantity each knob moves was measured off the machine at the
three fit positions, not assumed:

| voice | knob | what it actually moves | measured at knobs 0 / 5 / 10 |
|---|---|---|---|
| BD | DECAY | body τ (f0 does **not** move: 50.0 Hz on all 25 files) | 17.5 / 241 / 541 ms |
| BD | TONE | click energy above 300 Hz in the first 10 ms | 1.29 / 1.67 / 1.93 % |
| SD | TONE | ~~body ring, *not* pitch (168/172 Hz throughout)~~ — **WITHDRAWN 2026-09-18**; the two partials' amplitude **ratio**, and neither mode's decay | 0.0015 / 0.0839 / 2.205 (energy, upper over lower) |
| SD | SNAPPY | noise share above 700 Hz | 0.00 / 51.7 / 92.5 % |
| LT | TUNING | f0 | 80.0 / 90.0 / 100.0 Hz |
| HT | TUNING | f0 | 170.0 / 186.7 / 213.3 Hz |
| OH | DECAY | envelope τ — **saturates**, and 7.5 is held out | 22.9 / 186 / 219 ms |

Each law is a three-parameter interpolant through exactly those three points
(log link for τ and f0, logit for energy shares). CH, CP and CB have no knob,
so they have no law and — see §7 — no possible held-out setting.

> **The SD TONE row was wrong, and it was the fifth instance of this voice's
> recurring error.** "28.5 / 27.4 / 13.6 ms" is one τ fitted to a sum of two
> modes that decay at different rates; fitted separately the machine's modes
> are 29–39 ms and 5–11 ms at *every* TONE position and what moves is their
> ratio, by 31.7 dB. Roland says the same thing ("the output ratio of the
> two", SN p.6). Reproduced from a construction with the decays held fixed in
> `test_discrimination.test_a_single_tau_on_two_modes_reads_a_balance_change_as_a_decay_change`,
> and it mattered: `kit_at` wrote that τ into **both** our body modes, so the
> study was driving our snare wrongly and part of the SD distance it reported
> was its own. Corrected 2026-09-18 (`docs/drum-verification.md` §8.6).

---

## 3. Result

Held out, level-matched, arm `ours`. Balanced accuracy, Clopper-Pearson
interval, uncertainty computed over **settings** rather than over generated
comparisons.

| voice | held-out settings | balanced acc. | 95 % CI | knob-equivalent | verdict |
|---|---|---|---|---|---|
| **SD** | 16 | 1.000 | [0.89, 1.00] | **8.8 / 10** | known defect remains |
| **LT** | 2 | 1.000 | [0.40, 1.00] | 7.1 / 10 | no verdict — underpowered |
| **OH** | 2 | 1.000 | [0.40, 1.00] | 6.9 / 10 | no verdict — underpowered |
| **HT** | 2 | 1.000 | [0.40, 1.00] | 6.0 / 10 | no verdict — underpowered |
| **BD** | 16 | 1.000 | [0.89, 1.00] | **3.6 / 10** | known defect remains |
| CH, CP, CB | **0** | — | — | — | no verdict — corpus cannot test |
| pooled | 38 | 1.000 | [0.95, 1.00] | — | known defect remains |

### The knob-equivalent is the number to read, not the accuracy

Accuracy saturates. Once every held-out clip is called correctly, 1.000
cannot say whether we sit just outside the machine's own spread or far
outside it, and all five testable voices sit at 1.000.

So each voice's distance from the machine is expressed in the machine's own
units: **how far its own knob would have to move for it to look this
different from itself.** Our BD is as far from the real BD as moving the real
machine's own knob **3.6 of 10**; our SD is **8.8 of 10** away. That ranking
is the actionable output, and it is why SD is the first thing to fix.

---

## 4. Controls — without these, none of §3 means anything

| control | what it proves | result |
|---|---|---|
| **cross-voice**, real vs real, different voice, same machine, same converter, same afternoon (LT vs LC, HT vs HC, BD vs MT, LT vs MT, LC vs MC) | the pipeline resolves **timbre** with zero provenance cue | **1.000** on all five — PASS |
| **label permutation**, 200 shuffles | calibrates what chance is for this pipeline at this N | mean **0.500** [0.421, 0.579] — PASS, chance is 0.5 |
| **real-vs-real random split** of the 25 real BDs into two pseudo-classes | the pipeline does not manufacture separation from nothing | mean **0.44** [0.31, 0.69] — PASS |
| **large degradations** (τ×4, noise path removed, 4-bit cutoff) | catches gross errors | 0.97–1.00 — PASS |
| **graded degradations** (τ×0.75, snare noise −6 dB, 6-bit cutoff) | catches errors *near the margin that matters*, not only enormous ones | **1.000** on all six — PASS |

The graded row is the one that matters. τ×0.75 — a 25 % tail change, well
inside what a listener would call "the same drum" — is caught at 1.000, as is
a snare noise level only 6 dB from its target and a cutoff quantised to
6 bits rather than 4. The discriminator is not merely detecting catastrophes,
and the large-degradation row is therefore not the only thing holding up the
§3 verdicts.

A consequence worth stating plainly: because even the mildest degradation we
built is caught at ceiling, these controls establish **sensitivity** but not a
*detection threshold*. We know the discriminator catches a 25 % tail error; we
do not know how small an error it would stop catching. Bracketing that would
need a finer degradation ladder, and would be the natural next step if any
voice ever reached chance.

**All controls pass, so the §3 verdicts stand.** Had any failed, the correct
output would have been "no verdict" everywhere, and the harness enforces that
in code (`verdict(..., controls_ok=False)`).

### What the corpus cannot give: the real-vs-real floor

The number that would make an ours-vs-real accuracy fully interpretable is
the **same-setting real-vs-real** accuracy. Two genuine takes at the same
knobs are not identical — the 808's six hat oscillators free-run, its noise
source is an avalanche diode, components drift. If real separated from real
at 80 %, our 100 % would mean much less.

**That number cannot be computed from any freely licensed 808 material we
could obtain.** Fischer states he recorded many hits of each sound and kept
the one he judged most representative, so the set has exactly **one take per
setting**; the `808*` directories redistributed in tidalcycles/Dirt-Samples
are byte-identical to the same files. This is a real limitation, not a
detail.

What we computed instead is the **separation curve** — real against real at a
known knob distance, one knob at a time, split on the other knob:

| | Δ = 2.5 | Δ = 5.0 | Δ = 7.5 | Δ = 10.0 |
|---|---|---|---|---|
| BD **DECAY** | 1.00 | 1.00 | 1.00 | 1.00 |
| BD **TONE** | **0.50** | **0.50** | 0.75 | 0.75 |
| SD **SNAPPY** | 1.00 | 1.00 | 1.00 | 1.00 |
| SD **TONE** | **0.50** | **0.50** | 0.75 | 0.75 |

This is an **upper bound on the floor**, not the floor: every pair on it
differs by a real knob move, and Δ = 0 is off its left edge. But it is
informative in both directions. The machine's own TONE knob, moved *end to
end*, is separated at only 0.75 — and at one step, at chance. Our renders are
separated at 1.00. **We are further from the real machine than the real
machine's weakest knob can travel across its whole range.**

To get the true floor someone must record multi-take material. 808 From Mars
(≈ $39) ships real 808 recordings across tone/decay/accent with a clean
digital subset and would supply it; it was **not purchased**. New recordings
would serve equally.

---

## 5. What carries the discrimination

Two representations, deliberately, because each misses what the other finds.

### 5a. Interpretable diagnostics, at held-out settings only

These are the quantities the model was fitted against. Measuring them at
settings the fit never saw is a legitimate generalisation test, and they are
the only features a circuit designer can act on directly. Mean relative
error, ours against the machine, over held-out settings:

| voice | n | largest errors |
|---|---|---|
| **SD** | 16 | energy above 5 kHz **+1989 %**, 0.7–5 kHz **+450 %**, below 700 Hz +305 % |
| **OH** | 2 | energy below 700 Hz **+16896 %**, 0.7–5 kHz −81 %, attack −81 % |
| **BD** | 16 | attack **+103 %**, τ **+111 %**, energy above 5 kHz −83 % |
| **LT** | 2 | 0.7–5 kHz **−100 %**, attack +82 %, above 5 kHz −60 % |
| **HT** | 2 | 0.7–5 kHz **−100 %**, above 5 kHz −50 %, attack −18 % |

The SD row is the known missing-noise defect, now confirmed to **generalise
across the knob**: it is not a mid-point mapping error. The LT/HT "−100 % in
0.7–5 kHz" is the absent pink-noise path — our toms have literally nothing
there. The OH low-frequency excess is new and is the largest single
proportional error in the table.

### 5b. General representation, grouped permutation importance

40 log-mel bands and 20 MFCCs over four time segments; accuracy drop when a
whole (band × segment) bucket is shuffled on held-out clips:

| feature group | accuracy drop |
|---|---|
| MFCC, **attack segment** (0–60 ms) | **+0.20** |
| MFCC, early segment (60–120 ms) | +0.072 |
| 5–18 kHz, mid segment | +0.020 |
| 5–18 kHz, tail segment | +0.016 |
| 5–18 kHz, attack segment | +0.012 |
| 200–700 Hz, attack segment | +0.010 |

**The attack carries almost all of it.** That is consistent across voices and
matches `docs/drum-verification.md`'s finding that we strike every resonator
with an impulse where the machine uses a pulse shaped over ~10 ms.

---

## 6. Ranked: what to fix next

Ordered by knob-equivalent separation — how far our render sits from the
machine in the machine's own units.

1. ~~**SD — 8.8 / 10.** The snappy path. Noise carries 1.2 % of the energy
   where the machine's carries 47–92 % depending on SNAPPY, and it is flat to
   Nyquist where the machine humps at 3–5 kHz.~~ **SUPERSEDED — SD is now
   3.4 / 10, second only to the kick.** The "1.2 % against 47–92 %" pair
   is the withdrawn whole-span Hann split on both sides (§8.0 of
   `docs/drum-verification.md`); measured honestly the share was never far
   off. What was really wrong: the noise *band* (fixed in revision 6), then
   the snappy burst's *length* (τ 15 → 30 ms) and the two partials'
   *balance* (0.394 → 1.42), both fixed in revision 7 (§8.6). What remains at
   3.4 has not been identified and is spread thinly rather than concentrated.
2. **LT / HT — 7.1 and 6.0 / 10.** The missing pink-noise path (§4 of the
   reference): ours have *zero* energy in 0.7–5 kHz against the machine's.
   Cheap to add. **Underpowered verdict — the corpus has 2 held-out settings
   each — but the diagnostic error is unambiguous.**
3. **OH — 6.9 / 10.** Low-frequency excess, and the DECAY law saturation
   above 7.5 that our linear decay control does not reproduce. Also
   underpowered.
4. **BD — 3.6 / 10.** Closest of the five. The attack: +103 % attack-time
   error and no harmonics. The τ error largely disappeared once the DECAY law
   was fitted properly, which confirms `drum-verification.md`'s reading that
   the old 45 % shortfall was mid-point mapping, not mechanism.
5. **The attack shaping, globally.** §5b says the 0–60 ms segment carries
   ~90 % of the discrimination across all voices. One fix — a shaped
   excitation pulse instead of an impulse — attacks every voice at once and
   is the highest-leverage single change in the list.

`docfix` (the fixes `drum-verification.md` prescribes, applied as register
overrides) was rendered as a second arm and is **still separated at 1.000**.
Those fixes are necessary and not sufficient; they do not touch the attack.

---

## 7. What this test does **not** say

- **It is not a listening test.** Near-chance classifier accuracy would be an
  automated *screening* result about these evaluators on this corpus. It
  would not be a claim about human indistinguishability — that is a different
  experiment, with listeners, trials and controls we have not run. No such
  claim is made anywhere here.
- **Three of eight voices cannot be tested at all.** CH, CP and CB have no
  knob, so the corpus has one recording each and there is nothing to hold
  out. CB is documented as *wrong* and this test cannot confirm or deny it.
  LT, HT and OH have two held-out settings each — eight is the minimum at
  which any number of correct calls could exclude chance, so they get no
  verdict either. **The voices most likely to pass are exactly the ones the
  corpus is too small to adjudicate.**
- **Power.** 38 held-out settings bound a chance-performing discriminator
  below 0.61 one-sided; ~270 trials would be needed to bound it at 0.60, and
  the corpus offers 38. Had we measured near-chance, the honest report would
  have been "no verdict — screening inconclusive", not "indistinguishable".
- **The unmatched-level pass is void.** The reference pack is **peak-limited
  to −2.4 dBFS** — 38 of 116 files sit within 1 % of the ceiling and the whole
  set spans 6.0 dB. Level differences therefore carry no information about
  the machine's accent behaviour. Measured, not assumed; the run prints it.
- **FD-mel is reported, and not relied on.** The Fréchet construct behind FAD,
  computed on this module's own 320-d representation (not VGGish — so it is
  *not* FAD and is never called that), with encoder, sample counts, voice
  balance and preprocessing fixed across rows:

  | row | FD-mel |
  |---|---|
  | reference vs `ours` | 67 |
  | reference vs `docfix` | 69 |
  | reference vs graded degradations | 113 – 149 |
  | reference vs large degradations | 160 – 261 |
  | **reference vs reference subsets** | **211** |

  The arm ordering is sensible and `ours` sits well below the reference's own
  subset-to-subset spread. But that spread (211) lands *inside* the range of
  the degraded arms, which means at 25 clips per side FD-mel is dominated by
  sampling noise and has little resolving power here. Comparative only, as
  intended, and weak.

---

## 8. Minimoog: what our ladder measures against three independent emulations

> ### ⚠️ WITHDRAWN 2026-09-18: every u-he Diva number below
>
> Diva was running **unlicensed**. It prints `ERROR: Could not read lic from
> file.` on every instantiation and inserts periodic broadband clicks — 20 in
> a 360 s render, none in the first 167 s, then clusters every ~33 s, each a
> ~0.1 ms burst that raises the 6–20 kHz band by **32–43 dB** while leaving
> the note's own band unchanged. Surge XT over the same test: **zero**.
> `docs/reference-integrity.md` §1 has the evidence.
>
> **Every Diva figure in this section is withdrawn**, including
> **h5 − h3 = −41.2 dB at matched h3**, which has been quoted elsewhere.
> Surge XT and Arturia Mini V3 are unaffected — both showed zero events.
> Read this section as a two-reference study until Diva is licensed.

**Revision 2026-09-18. Revision 1 of this section concluded that no Minimoog
validation was possible and produced none. That conclusion was wrong, and one
of the numbers it rested on was a measurement artefact. Both are corrected
here.**

Revision 1's argument was: the only free hardware corpus (Legowelt's 222 WAVs
from Minimoog #5529) ships no panel settings, and the parameter-labelled
datasets — InverSynth, Sound2Synth, DiffMoog — were rejected because they are
"rendered from *software* synths, so comparing against them would test our
chip against another emulation." The material facts are still true. The
conclusion drawn from them is not.

**Why it is wrong.** A purity standard that admits only a real Model D
produced *zero* validation instead of imperfect validation, and shipped a
filter whose only evidence was that it agreed with our own decision records.
And it gave up the one thing an unlabelled hardware corpus can never
provide: **a software reference can be set to a known patch, and ours set to
the same patch.** That is a controlled experiment. Sound-matching against
222 unlabelled recordings could only ever have been a similarity score.

So: three references, all on this machine, all driven headlessly from Python
through `dawdreamer` (VST3, programmatic parameters, no GUI), all at 48 kHz —
which is our own `SR`, so **nothing in this study is resampled**.

| reference | what it is | what it can be asked |
|---|---|---|
| **Surge XT 1.2.3** — `LP Vintage Ladder`, subtype **Type 2** | **open source.** `sst::filters::VintageLadder::Huov` — Huovilainen's DAFx-04 nonlinear ladder, **the same published model DR 0001 implements** | everything, and its cutoff is commanded *and read back* in Hz, so cutoff accuracy is answerable here and nowhere else |
| **Surge XT 1.2.3** — same filter, subtype **Type 1** | `VintageLadder::RK` — Runge-Kutta 4 integration of the Stilson/Puckette ladder ODE, cubic soft-clip, 4× oversampled | everything |
| **Arturia Mini V3** | a dedicated Minimoog Model D emulation; 2 audio inputs (the Model D's external-input jack), so a known signal can be put through its filter | shape, drive, self-oscillation. Every parameter is a bare 0..1 with no units and no readback, so **commanded-cutoff accuracy is not answerable against it** |
| **u-he Diva** — VCF model `Ladder`, 24 dB | a ladder model in a synth with a strong reputation for analogue accuracy; `Accuracy: divine`, `OfflineAcc: best`, all voice-drift slop zeroed | shape and self-oscillation. **0 audio input channels**, so it is excited by its own white noise against a wide-open reference render, and **drive is not answerable against it at all** |

**What this does and does not establish, and the label goes on every result
below: none of the three is a Minimoog.** Agreeing with them means
"consistent with high-quality emulations", not "sounds like a Minimoog". Two
of them are commercial products whose internals cannot be inspected. The
protocol that would settle the real question is written down —
`docs/moog-recording-protocol.md` — and needs one person with the instrument
and an hour.

Run it:

```
.venv/bin/pip install dawdreamer
.venv/bin/python -m pytest model/test_reference_compare.py -q      # the estimators, first
.venv/bin/python model/reference_compare.py --stage all --devices ours,surge-rk,surge-huov,diva,miniv3
.venv/bin/python model/reference_compare.py --stage peakdrive,bigdrive --devices ...
.venv/bin/python model/reference_compare.py --report --out /tmp/refcmp
```

`model/reference_rigs.py` holds the five rigs (ours, its injected defects, and
the three plugins), `model/reference_compare.py` the measurements and the
report, `model/test_reference_compare.py` their ground truth.

---

### 8.1 The number revision 1 got wrong, and how

Revision 1 published this table and called it 25 dB of structural separation:

| structure | h5 − h3, at 129 / 258 / 516 Hz | as published |
|---|---|---|
| ours (tanh in every stage) | −14.0, −14.1, −14.5 dB | |
| one-tanh (linearised) — negative control | −38.4, −39.1, −40.8 dB | |

**Re-measured on the identical signals with a validated estimator, four of
those six numbers do not exist.** `model/moog_probe.py`'s `harmonics()`
integrates FFT bins around each harmonic with no window and no floor check. A
*rectangular* coherent projection leaks the fundamental sideways at roughly
1/(π·Δbins), which for a half-second record puts a phantom "harmonic" at −55
to −75 dB — precisely the range these h5 values live in. Measured with a
Blackman-Harris window (sidelobes 92 dB down) and a floor probed at four
off-harmonic offsets, `ours` at 258 Hz and `one-tanh` at 258 and 516 Hz have
**no fifth harmonic above their own noise floor at all**, and where h5 does
exist the spread is −25.5 dB, not −14.0.

This is the failure `docs/verification-rules.md` exists about, in the section
that was arguing for the rest of the filter. `audio_measure.harmonic_signature`
replaces it: windowed projection, a floor measured at (k ± 0.3) and
(k ± 0.5)·f0 taking the **largest** of the four, harmonics above Nyquist
returned as `None` rather than 0, and a `drift_db` so that a still-growing
ring is not analysed as a steady one. Its ground truth recovers harmonics at
−60 and −75 dB from a record that is *not* a whole number of periods, to
0.003 dB.

**The second thing revision 1 got wrong: h5 − h3 is not settings-independent.**
It depends strongly on how hard the limit cycle drives the nonlinearity, and
h3 is the measure of that. Against the fixed-point one-tanh control the probe
separates the two structures by **21 dB at res 1.3, 8 dB at res 1.05 and 3 dB
at res 2.0** — because at the top of the range the control's hard input clip
takes over. Quoted without a resonance, the number means nothing. Everything
below is quoted either at a stated resonance or at **matched h3**, which
controls the drive.

---

### 8.2 Method, and the four ways it could have been a gain error

- **Stepped tone, coherent projection** — the measured transfer function, the
  same probe `model/test_moog_acceptance.py` already uses on our filter, at
  the same drive, for all five rigs. Not an impulse response: it would presume
  a linearity that none of these four filters has. Never a spectral centroid.
- **Everything quoted is a ratio** — dB over a passband plateau, dB per
  octave, a harmonic over its own fundamental, a frequency over another
  frequency. A fixed gain difference between two synthesisers cancels out of
  every one of them by construction.
- **48 kHz end to end.** No result can be a resampler.
- **Every estimator is ground-truthed against a closed-form signal before any
  number it produces is quoted** (`model/test_reference_compare.py`, 17
  tests): −24.00 dB/oct recovered exactly from a −24 dB/oct line and *refused*
  on a resonant skirt; the −3 dB corner of four cascaded one-poles against its
  algebraic value 0.434995·f_p; a resonator's peak height, peak frequency and
  Q against their closed forms; harmonics at −60/−75 dB recovered; a pure sine
  under noise reported as **having no third harmonic** rather than as the
  noise level.
- **Start red.** Three deliberately-wrong ladders are carried through the same
  measurements (§8.7). If a broken model landed inside the reference spread on
  a property, that property proves nothing and is reported as proving nothing.
- **Level.** Input levels are referred to each plugin's own full scale, which
  is a matched documented setting (it is the rail) but is *not* the level at
  each filter's input. §8.6 measures where each filter actually starts to
  saturate, which is what makes the drive columns comparable.

---

### 8.3 Surge XT gets its own verdict

Surge is not the same kind of evidence as the other two. Its Vintage Ladder
"Type 2" is an implementation of the *same paper* DR 0001 implements, so a
disagreement is a bug in one of the two, not a difference of modelling taste.
Read from `sst-filters` `include/sst/filters/VintageLadders.h` (the Huov
namespace is mathematically identical at the 1.2.3-era commit `8ea9b8d` and on
`main`, checked), here is every place the two differ **by design**:

| | ours (DR 0001, contract 11.4) | Surge `VintageLadder::Huov` |
|---|---|---|
| topology | four one-poles, `y[s] += g·(tanh(y[s−1]) − tanh(y[s]))` | identical |
| oversampling | 2× (96 kHz) | 2×, input fed at both sub-steps (no zero-stuffing), same |
| feedback tap | `(y3[n−1] + y3[n−2])/2`, half-sample phase compensation | `(stage3 + delay4)/2`, the same |
| **output tap** | `y[3]`, **before** the averaging | `delay[5]`, **after** it |
| arithmetic | integer, Q1.15 signal, 24-bit Q4.20 state | float32 SIMD |
| **tanh** | **16-entry table over [0,4), linear interpolation**, max error **0.0060** | Padé rational, clamped at ±5, max error **1.5e-5** |
| **tuning** | `g = 1 − exp(−2π f / f_os)`, no correction | **`fcr = 1.8730 fc³ + 0.4955 fc² − 0.6490 fc + 0.9988`**, Huovilainen's published tuning polynomial, applied to the exponent |
| resonance law | `k = 4·res`, corrected per cutoff by DR 0006's own measured ROM | `4·res·acr`, `acr = −3.9364 fc² + 1.8409 fc + 0.9968`, Huovilainen's published polynomial |

> **The `fcr` quadratic term is `0.4955`, and `sst-filters` ships `0.4995`.**
> Surge's own comment in `VintageLadders.h` reads `0.4955 * fc2` and the
> constant beside it is *named* `m04955` — but it is *initialised* to
> `0.4995f`, in both the 1.2.3-era commit `8ea9b8d` and on `main`. The cited
> source spells it **`0.4955`**, so the paper's value is 0.4955 and Surge
> ships a typo: its comment and its constant name both agree with the paper
> against its own code.
>
> **This repository implements 0.4955**, in `model/reference_rigs.py`'s
> `OurLadder.fcr` and in the table above. It is recorded here because the next
> person to compare our implementation against Surge's source will find our
> value differing from the code in front of them and reasonably assume we are
> wrong.
>
> **It changes nothing measured.** At a 10 kHz cutoff the two differ by
> 1.7e−4 in an `fcr` of 0.9022 — **0.003 cents**. Every figure in §8.4 stands
> as measured.
>
> Worth the line for its own sake: a reference can be **authoritative about
> its intent and wrong in its artefact**, and the two have to be read
> separately.
| **resonance range** | `res` clamps at 2.0 (the 17-bit `k` register); **res = 1 is the onset at every cutoff** (DR 0006) | `res` clamped to ≤ 0.9925 and reduced further above f_s/3: **it never reaches the onset and cannot self-oscillate** |
| **signal scale into the tanh** | `gain = drive·0.13/0.05 = 2.6`, so full scale is 2.6 in tanh units | `thermal = 1/70`, so full scale is **0.0143** in tanh units |
| gain compensation | `ogain = (2V_T/v_pu)·(1 + 2·res)` at the output | `gComp = 0.5` inside the feedback, on the "Compensated" subtypes only |

Two of those rows decide what Surge can be used for:

**Surge's Huovilainen subtype cannot self-oscillate.** Measured: at resonance
100 % its free ring decays monotonically from −82.5 dB to −127.3 dB over
1.65 s. That is not a defect, it is the `0.9925` clamp doing its job. It means
Surge Type 2 contributes nothing to the self-oscillation fingerprint.

**Surge's Huovilainen subtype does not reach its own nonlinearity at any
usable level.** With `thermal = 1/70`, a full-scale ±1.0 signal presents 0.014
to a `tanh` that is linear to one part in 10⁴ there. Predicted h3 at 0 dBFS:
−101 dB. **Measured: −102 dB.** It first produces −40 dB of third harmonic at
**+18 dBFS** — 18 dB past the rail. Ours reaches that at **−6.6 dBFS**, Mini
V3 at **−5.7 dBFS**, Surge's RK model at **−0.6 dBFS**.

So the honest verdict on Surge: **on the linear structure it is an excellent
reference and we should agree with it exactly. On the nonlinearity it is not a
reference at all — at normal levels it is a linear 4-pole ladder with
Huovilainen's tuning polynomials bolted on.** Our input scaling, which is 27×
hotter, is the one that matches both the physics (a transistor ladder sees a
few hundred mV against 2V_T ≈ 50 mV) and the dedicated Minimoog emulation.

---

### 8.4 Result: the cutoff control does not mean the same thing across its range

Self-oscillation pitch against **commanded** cutoff, at maximum resonance, over
six octaves:

| filter | 100 Hz | 800 Hz | 6400 Hz | **spread** |
|---|---|---|---|---|
| **ours** | −8.30 % | −6.77 % | −0.38 % | **7.92 pp** |
| Surge Type 2 (Huov) | −0.37 % | −0.23 % | +0.25 % | **0.62 pp** |
| Surge Type 1 (RK) | −2.18 % | −2.32 % | −3.46 % | **1.28 pp** |
| Diva *(knob calibrated on f_osc — circular, not evidence)* | +0.10 % | +0.04 % | +0.04 % | 0.09 pp |
| Mini V3 *(same, circular)* | +0.03 % | −0.15 % | −0.24 % | 1.02 pp |

A frequency-*independent* offset is one scale factor and is removable in an
afternoon; the **spread** is the defect, and ours is 6 to 13 times the
spread of either Surge model. Contract 17.12 already records the symptom
(+7.2 % at 10 kHz, ±2 % from 400 Hz to 1.6 kHz) as an open item. What the
reference adds is **the cause and the fix**, both read out of Surge's source:
Huovilainen's `fcr` tuning polynomial, which Surge applies and we do not.

Applying `fcr` to our own cutoff lookup — one multiply in the ROM build, no
change to the datapath — and then one constant scale:

| cutoff | ours | + `fcr` | + `fcr` × 1.030 |
|---|---|---|---|
| 200 Hz | −2.51 % | −2.98 % | **+0.03 %** |
| 800 Hz | −1.41 % | −2.66 % | **+0.31 %** |
| 3 kHz | +1.56 % | −2.61 % | **+0.42 %** |
| 10 kHz | **+6.85 %** | −3.90 % | **−0.89 %** |

**Worst error 6.85 % (115 cents) → 0.89 % (15 cents)**, measured at
res = 1.05. It also flattens the measured −3 dB corner: the corner/commanded
ratio goes from 0.752–0.818 (8.8 % drift) to 0.748–0.775 (3.5 %). The
constant differs with resonance — at maximum resonance the residual offset is
−8 % rather than −2.6 % — so the scale has to be chosen for a stated operating
point, and that choice is a decision record, not a measurement.

**This is the strongest result in the study**: we differ from every reference
in the same direction, the mechanism is identified in the source of a
reference implementing the same paper, and applying the published correction
removes 87 % of the error.

---

### 8.5 Result: the shipped tanh table, not the structure, is what our fifth harmonic measures

The self-oscillation fingerprint at each device's own maximum resonance, and
at **matched h3 = −42 dB** (equal drive into each nonlinearity):

| filter | onset | h2 | h3 | h5 | h7 | h5 − h3 | **at matched h3** |
|---|---|---|---|---|---|---|---|
| **ours** | res 1.02 | −95.5 | −40.0 | −63.4 | −62.6 | −23.4 | **−20.4** |
| ours, 256-entry tanh table | res 1.02 | −95.9 | −39.8 | −81.7 | −105.2 | −41.8 | **−46.0** |
| Surge Type 1 (RK) | 0.90 | *< floor* | −50.4 | −100.6 | −138.3 | −50.3 | — |
| Diva Ladder | 0.90 | **−33.9** | −36.0 | −71.4 | −107.1 | −35.3 | **−41.2** |
| Mini V3 | 0.78 | *< floor* | −41.8 | −70.5 | −87.4 | −28.7 | **−28.7** |
| Surge Type 2 (Huov) | **never** | — | — | — | — | — | — |
| *one-tanh — injected defect* | 1.02 | −94.8 | −39.7 | −66.2 | −97.2 | −26.4 | *−38.7* |

Three things come out of this, and only the first is comfortable.

**Our third harmonic sits inside the references' range** (−40.0 against −36.0,
−41.8 and −50.4). h3 is the measure of the nonlinearity's real curvature, and
on it we agree.

**Our fifth harmonic does not, and the excess is our tanh look-up table.**
Rebuilding the identical filter with a 256-entry table instead of the shipped
16 leaves h3 unchanged (−39.8 vs −40.0) and drops **h5 by 18 dB and h7 by
43 dB**. The full sweep, at res 1.1:

| entries | ROM bits | max table error | h3 | h5 |
|---|---|---|---|---|
| 8 | 128 | 0.0233 | −53.9 | −93.1 |
| **16 (shipped)** | **256** | **0.0060** | **−50.8** | **−70.1** |
| 32 | 512 | 0.0015 | −50.9 | −76.7 |
| 64 | 1024 | 0.00067 | −51.1 | −83.4 |
| 128 | 2048 | 0.00067 | −51.2 | −95.1 |
| 256 | 4096 | 0.00067 | −51.2 | −96.1 |
| 1024 | 16384 | 0.00067 | −51.2 | −97.1 |

A 16-segment piecewise-linear `tanh` has 16 corners in its derivative, and the
corners — not the saturation — are what emit the fifth and seventh. **128
entries converges** (2048 ROM bits against 256, a 1792-bit increase: the whole
ladder is 1,917 cells, so this is worth costing rather than guessing at). At
16 entries, the "structural fingerprint" this section was built around is
measuring our LUT resolution.

**The fingerprint does not support DR 0001 on its own.** At matched drive ours
sits at −20.4 dB, the references at −28.7 and −41.2, and **the injected
one-tanh defect at −38.7 — closer to Diva than we are.** A discriminator that
ranks a structure we know is wrong above the one we ship cannot be used to
argue the structure is right. With a 256-entry table ours moves to −46.0,
inside the references' spread, but by then the argument is about the table.
DR 0001 remains supported by circuit derivation; this measurement does not add
to it, and revision 1's claim that it did was resting on the leakage of §8.1.

**A fourth thing, about the references rather than about us.** Diva's ladder
emits h2 at −33.9 dB, *2.1 dB above its own h3*: its nonlinearity is
**asymmetric**, which an odd-symmetric `tanh` cannot be, and which a real
transistor ladder with a mismatched differential pair is. Ours and Mini V3 are
odd-symmetric (h2 below the floor, or −95 dB). This is a genuine disagreement
*among the references*, and it means the target itself is uncertain: at least
one of the two commercial emulations is modelling something the other decided
not to.

---

### 8.6 Result: slope, corner and resonance

**Stopband slope.** Ours −21.4 to −21.9 dB/oct over 2.2–7× the measured
corner, fit residual 0.21–0.34 dB. The references over the same band: Surge
Type 2 −19.4 to −21.5, Surge Type 1 −19.2 to −21.4, Diva −18.2 to −21.2,
Mini V3 −17.6 to −21.6. **An ideal analogue 4-pole gives −17.6 dB/oct over
that band** (closed form, in the report's `ideal4p` column) — 24 dB/octave is
the asymptote, not what any 4-pole does two octaves above its corner. So the
24 dB/oct claim holds: ours is the *steepest* of the five, and the injected
dropped-pole control reads −11.6 to −11.8.

**−3 dB corner against commanded cutoff.** Nobody's ratio is constant:
ours 0.752→0.818 (drifting up), Surge Type 2 0.627→0.566 and Mini V3
0.697→0.730 (drifting the other way), Diva 0.584–0.697 with no clean trend.
The corner is the weaker discriminator of the two frequency measurements —
it moves with resonance and with the passband reference band — and §8.4's
self-oscillation pitch is the one to read.

**Resonant peak, at 0.9 of each filter's own self-oscillation threshold**,
against input level:

| filter | −60 dBFS | −48 | −36 | −24 | −12 dBFS |
|---|---|---|---|---|---|
| **ours** | 23.3 dB / Q 14.3 | 23.2 / 14.1 | 21.8 / 12.8 | 14.5 / 6.3 | **8.0 / 2.6** |
| ours, 256-entry table | 20.2 / 11.2 | 20.1 / 11.0 | 20.8 / 11.7 | 14.7 / 6.5 | 8.1 / 2.7 |
| Surge Type 2 | 21.9 / 12.7 | 21.9 | 21.9 | 21.9 | **21.9 / 12.7** |
| Surge Type 1 | 22.0 / 12.7 | 22.0 | 22.0 | 22.0 | 22.5 / 13.2 |
| Diva | 17.7 / 9.7 | 18.4 | 19.7 | 20.9 | 20.0 / 10.6 |
| Mini V3 | 14.1 / 3.4 | 14.1 | 13.7 | 14.4 | 16.6 / 7.5 |
| *2-pole — injected defect* | 2.1 / — | 2.1 | 2.0 | 2.0 | 1.6 / — |

**At small signal the five agree**: 23.3, 22.0, 21.9, 17.7, 14.1 dB. Ours is
at the top of the spread, not outside it.

**With drive we are the only one whose resonance collapses**: −15.2 dB from
−48 to −12 dBFS, against +0.0, +0.5, +1.6 and +2.5 for the four references.
This is the "thickens vs flat-tops" question and the answer is not flattering,
but **it is confounded** and the confound must be stated: at 0.9 of its own
threshold ours reaches Q 14.3 while Mini V3 reaches only Q 3.4, so our
internal signal is four times larger before the nonlinearity ever sees it. Our
*input-referred* saturation threshold (−6.6 dBFS) agrees with Mini V3's
(−5.7 dBFS) to within a dB. What differs is how much Q each knob buys, which
is a resonance-law difference, not a gain-staging one. **Reported as a
measured difference with its confound named, not as a defect.**

---

### 8.7 The controls: does any of this have power?

Three deliberately-wrong ladders through the identical measurements:

| injected defect | what it must move | measured | ours |
|---|---|---|---|
| **dropped pole** (2 stages) | the slope, the peak | −11.6 to −11.8 dB/oct; peak 2.1 dB, no Q at any drive | −21.4 to −21.9; 23.3 dB, Q 14.3 |
| **cutoff ROM read 30 % high** | the corner | corner/commanded 0.97–1.08 | 0.752–0.818 |
| **one-tanh** (four linear poles, one saturating element in the feedback — the structure DR 0001 rejected) | the fingerprint | h5 − h3 at matched h3 **−38.7 dB** | **−20.4 dB** |

Each is separated from ours by far more than the spread between the three
references, so the measurements can see a broken filter. The one-tanh control
carries the caveat of §8.1: it separates by 21 dB at res 1.3, 8 dB at 1.05 and
**3 dB at res 2.0**, where its hard input clip dominates — so the structural
probe has power only at a stated resonance, and `model/test_reference_compare.py`
asserts *both* the separation and its disappearance, so that the caveat cannot
quietly stop being true.

`_Variant(stages=4, nonlin='every')` is asserted bit-exact against `LadderFx`,
as in the acceptance suite: a control that has drifted measures its own drift.

---

### 8.8 Ranked: what this says to fix

1. **Apply Huovilainen's `fcr` tuning polynomial to the cutoff ROM** (contract
   17.12). One multiply at ROM-build time, no datapath change. Worst
   self-oscillation tuning error 6.85 % → 0.89 % with one accompanying
   constant; corner-ratio drift 8.8 % → 3.5 %. We are outside all four
   references in the same direction and the fix is published.
2. **Cost a wider `tanh` table.** 16 → 128 entries removes 25 dB of excess
   fifth harmonic and 43 dB of seventh at self-oscillation, for 1792 extra ROM
   bits against a 1,917-cell datapath. Whether that is audible is a separate
   question and should be asked with a listening test, not asserted here;
   whether it is affordable is an area question and should be measured, not
   guessed.
3. **Decide whether the resonance law is right.** Ours buys Q 14 at 0.9 of
   threshold where Mini V3 buys Q 3.4. That is not a defect on any evidence
   here, but it is the mechanism behind the only property on which we behave
   unlike all three references, and nobody has chosen it deliberately.
4. **Nothing here impeaches the 24 dB/octave claim or the −3 dB corner**, and
   the third-harmonic depth at self-oscillation is inside the references'
   range.

---

### 8.9 What is still not established

- **None of this is a Minimoog.** It is three emulations, two of them
  closed. Where they disagree with each other — Diva's asymmetric
  nonlinearity, Mini V3's Q 3.4 against Surge's Q 12.7 at the same fraction
  of threshold — the target is genuinely uncertain and no amount of averaging
  would fix that.
- **Surge Type 2 is a linear reference.** Every nonlinearity result above
  rests on Mini V3, Diva and Surge's RK model, i.e. on two closed products and
  one model of a different paper.
- **Diva's and Mini V3's cutoff scales have no units.** Their tracking rows are
  circular by construction and are printed only so the circularity is visible.
- **Nothing here is a listening test**, and none of it should be reported as
  one. The one measurement that would settle the structure question against
  the real instrument is a few seconds of a Model D's filter self-oscillating
  with the mixer at zero; `docs/moog-recording-protocol.md` §4.1 is how to
  capture it, and `model/moog_probe.py` reads it the day it exists.

---

## 9. Reproducing, and one caveat

The `drums` branch had not yet merged to `main` when this was run, so
`model/drums_fx.py` and `model/modal_fixed.py` were taken from `origin/drums`
`1e638ac` and the rest from `main` `d9921a4`. `model/drum_verify.py` on main
is in the same state — it already references `drums_fx_render`. Re-run after
the merge lands; the run prints the commit and a SHA-256 of the model files it
actually rendered, so a stale result is self-identifying.

Nothing in this test was tuned on a held-out setting. The pre-registered
split, the equivalence margin and the minimum-N rule were fixed before any
accuracy was computed, and `model/test_discrimination.py`'s own pytest suite
checks each of them (window shorter than the shortest reference file, features
rate-independent across 44.1 k and 48 k, floor clamp hides a −76 dBFS
converter floor, level matching removes a pure gain, a recording never on both
sides of a split, and that 10-of-20 is reported as an upper bound of 0.68
rather than as "indistinguishable").
