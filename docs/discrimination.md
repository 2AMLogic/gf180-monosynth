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
`model/discrimination_run.py` the reproducible script, `model/moog_probe.py`
the Minimoog half (§8).

---

## 1. Scorecard

| | |
|---|---|
| model revision rendered | `d9921a4` + `model/drums_fx.py`, `model/modal_fixed.py` from `origin/drums` `1e638ac` (the drums merge into main was still in flight; see §9). **Superseded: contract revision 6 changed five of the eight voices** — the snare's noise band and level, the cowbell's gating, tail and band-pass, the kick's f0 and its attack window, and the toms' pitch drop (`docs/drum-verification.md` §8, DR 0009, DR 0010). Every number below describes the kit as it was before those, so **re-run this study before quoting it**. Its conclusion that the attack carries most of the separability is what makes contract 17.20 — the excitation shape — the next thing to do, and none of these changes touch that. |
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
| SD | TONE | body ring, *not* pitch (168/172 Hz throughout) | 28.5 / 27.4 / 13.6 ms |
| SD | SNAPPY | noise share above 700 Hz | 0.00 / 51.7 / 92.5 % |
| LT | TUNING | f0 | 80.0 / 90.0 / 100.0 Hz |
| HT | TUNING | f0 | 170.0 / 186.7 / 213.3 Hz |
| OH | DECAY | envelope τ — **saturates**, and 7.5 is held out | 22.9 / 186 / 219 ms |

Each law is a three-parameter interpolant through exactly those three points
(log link for τ and f0, logit for energy shares). CH, CP and CB have no knob,
so they have no law and — see §7 — no possible held-out setting.

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

1. **SD — 8.8 / 10.** The snappy path. Noise carries 1.2 % of the energy
   where the machine's carries 47–92 % depending on SNAPPY, and it is flat to
   Nyquist where the machine humps at 3–5 kHz. Confirmed to generalise across
   the whole knob, so this is mechanism, not calibration. Biggest win
   available.
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

## 8. Minimoog: is the same thing feasible?

**Patch-level emulation: no. Structure probe: the probe design works, but the
material does not exist.**

Legowelt publishes 222 WAVs from his 1970s **Minimoog serial #5529** at
<https://legowelt.org/samples/>, free ("the samples are free but please
consider a donation"), 16-bit/44.1 kHz, explicitly including the instrument's
noise and instability. We downloaded and audited it.

**It ships no panel settings.** Three photographs, an info text, and
filenames that are characterisations — `BASS-Mudsy`, `SYNTH-Zoemer`,
`WEIRD-BlubbyChomper` — not settings. A Model D patch is ~25 controls (three
oscillators × range/waveform/frequency, five mixer levels, cutoff, emphasis,
contour amount, two ADS envelopes, glide, mod mix). Without that vector we
cannot place our model at the same point, so **no emulation experiment is
possible with this set**; only sound-matching, which would show the engine can
*reach* those tones and nothing about structure. A wider search (Freesound,
archive.org, Zenodo, GitHub, AKWF, NSynth, torchsynth, presetpatch, Moog's own
downloads) found no Minimoog material with documented settings anywhere, and
the parameter-labelled research datasets — InverSynth, Sound2Synth, DiffMoog —
are all rendered from *software* synths, so comparing against them would test
our chip against another emulation.

### The structure probe, which does not need settings

A self-oscillating Moog ladder is not a pure sine: the per-stage `tanh`
shapes it, so its harmonic series fingerprints the nonlinear **structure** —
exactly what DR 0001 decided — and does not depend on where the cutoff knob
sat. We built the probe and calibrated it on our own model.

**The fingerprint is not h2.** The ladder's `tanh` is odd-symmetric, so a
ladder ringing alone emits only *odd* harmonics; h2 and h4 are absent by
symmetry in both candidate structures (ours −89…−104 dB, one-tanh
−133…−160 dB), far below any recording's noise floor. The discriminator is
**h5 relative to h3** — how far the distortion spreads up the odd series,
which is precisely what a `tanh` in every stage changes:

| structure | h5 − h3, at 129 / 258 / 516 Hz |
|---|---|
| **ours** (tanh in every stage, DR 0001) | −14.0, −14.1, −14.5 dB |
| **one-tanh** (linear stages, one tanh in feedback) — negative control | −38.4, −39.1, −40.8 dB |

**25 dB of separation.** The probe has real power and is settings-independent.
It needs material.

**The material is not there.** Admission requires both (a) h2 − h3 ≤ −12 dB
(odd-symmetric) and (b) h3 ≤ −25 dB (a near-sine; a square wave is
odd-symmetric too, at h3 = −9.5 dB). Of 222 recordings:

- 80 pass (a) but are oscillator waveforms — median h3 **−19 dB**
- 27 pass (b) but carry even harmonics *at or above* their odd ones — median
  h2 − h3 **+1 dB**, an asymmetric source in the path
- **0 pass both.**

Not one recording in the set is a ladder ringing on its own. The slope and
resonant-peak probes fail for the same reason: they need a broadband source
under an identifiable resonant peak, and the set's steady periodic tones give
spectral lines instead — the two self-documenting files,
`SYNTH-SimpleThinSquareFilterSlope` and `WEIRD-ResonanceZone`, return a
*rising* "rolloff" of +7.6 dB/oct and Q of 92 and 361, which are the
diagnostics of invalid input, not measurements. `model/moog_probe.py` refuses
to report them as results.

**Conclusion.** The available recordings do not support a ladder-structure
probe. **DR 0001 remains supported by circuit derivation alone, which is where
it already was.** The probe is built, calibrated and checked in; it needs one
recording of the filter self-oscillating — a few seconds, resonance past
threshold, all oscillator levels at zero — which anyone with a Model D could
make in a minute.

Patch-fitting was **not run**, within the session's time cap. It would have
supported only the weaker claim.

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
