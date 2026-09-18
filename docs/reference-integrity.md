# Can these references be trusted? Licensing, pinned settings, and what renders at all

Three questions that had never been asked about the plugins
`docs/discrimination.md` §8 measured against, and that had to be settled
before any number measured against a commercial plugin could mean anything.

Reproduce: `.venv/bin/python model/reference_integrity.py --stage demo --source smooth --seconds 360`

---

## 1. ⚠️ u-he Diva is running UNLICENSED, and every Diva number is withdrawn

**Three independent pieces of evidence, and they agree.**

**(a) Diva says so.** On every instantiation, to stdout:

```
ERROR: Could not read lic from file.
```

There is no `com.u-he.Diva.Preferences.txt` in the user's u-he directory
although Zebra2, ZebraHZ and Zebralette all have one. The
`Native Instruments/Service Center/u-he-Diva.xml` present on disk is an
NKS product hint installed with the plugin regardless of licence
(`<AuthSystem>None</AuthSystem>`) and is not evidence either way.

**(b) It inserts periodic broadband clicks, and they are not there at first.**
360 s, one held note, a triangle source (no per-cycle discontinuity), first
0.5 s skipped. Detector: block-wise high-band level, threshold at 12 × the
median absolute deviation, demonstrated on the same render with an injected
click train at 0.25 × peak.

| | events | per minute (1…6) | first event |
|---|---|---|---|
| **Diva** | **20** | **0, 0, 1, 6, 3, 10** | **167.3 s** |
| Surge XT (control: free, open source, no demo mode) | **0** | 0, 0, 0, 0, 0, 0 | — |

Nothing for the first 2.8 minutes, then clusters at **~33 s intervals**
(167.3, 200.1, 235.8, 268.6, 302.4), increasing in density.

**(c) The events are clicks on top of an untouched note.** Taking three of
them and comparing with a quiet stretch of the same render:

| | 200 Hz – 2 kHz | 6 kHz – 20 kHz | max sample step |
|---|---|---|---|
| quiet baseline | 41.6 dB | **−45.8 dB** | 0.0118 |
| t = 200.06 s | 41.7 | **−13.3** | |
| t = 235.75 s | 41.6 | **−4.3** | |
| t = 302.39 s | 41.8 | **−3.1** | 0.0348 |

The note's own band is unchanged to 0.2 dB while the high band jumps by
**32 to 43 dB**, in a burst lasting about **0.1 ms**. That is a click added on
top of the signal, not any behaviour of a filter or an oscillator. A repeat
render is bit-identical, so it is deterministic and time-locked to
instantiation.

### What is withdrawn

**Every Diva number in `docs/discrimination.md` §8 and in
`docs/surge-source-notes.md` §3.** Including **h5 − h3 = −41.2 dB at matched
h3**, which has been quoted in a status report and a published page.

The measurement runs held **one** Diva instance and rendered many times on it,
accumulating well past 167 s of processed audio in a session, so
contamination cannot be ruled out for any individual figure without a re-run
that instantiates per render. Even if it could, an unlicensed instrument may
differ from a licensed one in ways other than the crackle, and none of that is
knowable from outside.

**Diva is removed from the reference set until a licence is present.** What is
*not* affected: Surge XT (free and open source) and Arturia Mini V3, which
showed **zero** events over the same test and are licensed as far as this test
can tell.

---

## 2. Settings that change the sound and were never written down

A comparison against a setting nobody recorded is not a comparison. Each rig
now pins every sound-changing control that is not the thing under test, **by
index, value, and expected parameter NAME**, and `check_pins()` verifies all
three after a render.

**The name check is not decoration — it caught a total loss of signal.**
Surge renames parameters 259–267 when oscillator 1's type changes. Index 265
is *"Osc 1 Unison Voices"* for a Classic oscillator and **"Osc 1 High Cut"**
for an Audio In one. Pinning it to 0 as "1 voice" sets a **13.75 Hz high
cut**, which would have silenced the audio input that every Surge measurement
in §8 depends on. The mismatch was caught on the first run of the check.

Newly pinned, having previously been left at whatever the plugin defaulted to:

| plugin | now pinned |
|---|---|
| **Surge XT** | **`Character`** (a pre-filter tone control on the oscillators), `Osc Drift`, `Osc 2/3 Unison Voices`, `FX Chain Bypass`, `Global Volume`, `Pre-Filter Gain`, `VCA Gain`, `Filter Balance`, `Waveshaper Drive`, `Portamento`, `Noise Color`, and the Audio In oscillator's `Channel` and `Gain` |
| **Arturia Mini V3** | **`Unison`**, **`Soft Clipping`**, **`Voices/Osc detune`**, `Chorus` (enable, type, speed, depth, mix), `Delay` (enable, sync, times, feedbacks, wet), `Vocal Filter` (enable, X, Y, resonance, wet, LFO), `Pink Noise`, `Tune` |
| **u-he Diva** | `Revision`, `SlnKyRevision` (both filter MODEL revisions), **`VCA Mode`** (lin / simple moog / complex moog), `FineTuneCents`, `TuningMode`, `ShapeModel`, `Post-HPF Freq`, `ShapeMix` — on top of the `TuneSlop`/`CutoffSlop`/`EnvrateSlop`, `Accuracy: divine` and `MultiCore: Off` already set |
| **Moog Model D** | `Legato`, `Polyphonic`, `Contour Shape`, `Tune`, `Modulation Mix`, all three modulation routings, `Filter Modulation`, `Keyboard Control 1/2`, `Amount Of Contour`, `Glide`, `Decay`, `Arp`, `Key Hold`, `Bender` |

Surge's Audio In `Low Cut` and `High Cut` read 29.14 Hz and 13.75 Hz — the
extremes of their ranges, which is how Surge displays a *deactivated* cut.
They are pinned **by name only, with no value written**, and §3 measures that
the path really is flat rather than taking the readback's word for it.

---

## 3. Surge XT works as an FX: the audio-input path is flat

The point of an FX-version filter is to put **identical** oscillator material
through the reference's filter and ours, so an oscillator difference cannot
masquerade as a filter difference. Surge already does this — the rig has used
`make_playback_processor` → `load_graph([(pb, []), (p, ["src"])])` with
oscillator 1 set to **Audio In** for every Surge measurement in §8.

Measured end to end with **Filter 1 set to Off**, stepped tone, coherent
projection:

| band | result |
|---|---|
| 40 Hz – 15 kHz | **0.52 dB peak-to-peak** |
| 100 Hz – 15 kHz | **0.07 dB peak-to-peak** |
| gain | a constant **−9.03 dB** |

The only deviation is −0.5 dB at 40 Hz, consistent with the deactivated Low
Cut's residual or a DC blocker. **Surge is a usable, flat, headless FX path,
and it is the reference whose source we can read** — which for diagnosis beats
a closed plugin.

**Softube Model 72 is not installed.** No `Model 72` in `/Library/Audio/Plug-Ins/VST3`
or `Components`, and no `/Library/Application Support/Softube`. Softube Central
and iLok License Manager are present but the plugin is not. **No 20-day trial
clock is running**, so the buy/not decision is not time-boxed, and on present
evidence the capability it would buy is already available free from Surge.

---

## 5. Run-to-run variance: the differences we have quoted ARE interpretable

There were no repeated renders anywhere in this harness, so
"7.92 percentage points against Surge Type 2's 0.62" had been quoted without
anyone knowing what a difference of *zero* looks like. Five repeats of the
self-oscillation tracking measurement, **a fresh plugin instance each time**:

| | 100 Hz | 400 Hz | 1.6 kHz | 6.4 kHz | drift statistic | run-to-run spread of it |
|---|---|---|---|---|---|---|
| **ours** | −8.301 % | −7.453 | −5.650 | −0.380 | **7.92 pp** | **0.000 pp** |
| Surge Type 1 (RK) | −2.178 | −2.240 | −2.488 | −3.457 | **1.28 pp** | **0.000 pp** |
| Mini V3 | +0.043 | +0.543 | −0.470 | −0.250 | **1.01 pp** | **0.003 pp** |

Per-cutoff spread is **exactly 0.0000 pp** for ours and for Surge — both are
deterministic with drift pinned off — and **0.006–0.010 pp** for Mini V3,
whose analogue-variation modelling is not quite deterministic.

`ours` is the control here: it is a deterministic integer model, so a nonzero
spread would have meant the harness rather than the instrument. It is zero.

**So the 6.6 pp gap between ours and either reference is about two thousand
times the measurement's own noise.** The comparison stands, and now it stands
with an error bar rather than without one.

---

## 4. ⚠️ Moog's own Model D instantiates but renders digital silence

`/Library/Audio/Plug-Ins/VST3/Model D.vst3` and
`Components/Model D.component` both load, expose their parameters (2150 VST3 /
68 AU), accept parameter writes and read them back correctly — and produce
**exact digital silence**, rms 0.00000000, under every configuration tried:
oscillator 1 enabled at volume 0.9, filter cutoff at maximum, emphasis 0,
master volume 1.0, loudness contour attack 0 / sustain 1.0, note 60 at
velocity 127, all six oscillator ranges, with `enable_all_buses()`.

Surge and Mini V3 render normally in the same harness, so this is not the
harness. The likely cause is an **authorisation check that fails in a headless
host** — the plugin reports no error and simply outputs nothing, where Diva
prints a licence error and Surge needs no licence. **Opening it in a GUI host does not fix it.** `Model D.app` was launched and
left running (confirmed, PID 56816) and the headless render was retried
immediately: still `rms 0.00000000`, in both VST3 and AU. No preferences or
Application Support files appeared. Whatever authorisation the standalone app
holds is not visible to the plugin in a host called "Python".

**Model D is therefore not usable headlessly**, and a reference that needs a
manual step before every session could not go in a nightly job anyway. The rig
(`reference_rigs.ModelDRig`) is written and its pin check passes; it is left
in place so that if a future version or a licensed plugin host changes this,
nothing needs rebuilding.

The rig is complete and its pin check passes; only audio is missing. Model D
has **0 audio input channels**, so when it does run it is an
oscillator-and-noise reference, not an FX path, and its parameters are bare
0..1 values with no units — its cutoff knob will be calibrated against its own
self-oscillation, exactly as Mini V3's is. **When it works it gets its own
verdict and is never averaged into a reference spread**: it is Moog's own, and
a disagreement with it is a different kind of finding from a disagreement with
a third-party interpretation.
