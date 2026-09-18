# Instrument execution plan v0.30

**Date:** 2026-09-18. **Target:** a playable complete 808 plus a mono Moog-like voice, improved primarily through automated comparison with software instruments. Paraphony follows a good basic instrument.

This plan incorporates the instruction that measurable imitation is the development process. We should automate many meaningful comparisons and use them to improve the instrument. Musician friends evaluate the remaining sound and feel decisions at the end. Expressiveness belongs in the automated suite too: it includes measurable responses to overlapping notes, glide, release, modulation and moving controls.

The accompanying `instrument-scorecard-v0.30.xlsx` contains 100 proposed cases, calculated verdicts and twelve release requirements. **No new acoustic results have been imported.** Its empty results describe this new benchmark, not the amount of engineering already completed. The workbook is a reporting artifact; this review has not connected it to a runner, repaired the repository or executed its acoustic suite.

## 1. Recommendation

Finish the integrated instrument while establishing a small, trustworthy comparison set. Expand that same runner from 32 to 80 development cases, then evaluate 20 reserved cases. Do not wait for every feature to be finished before comparing sounds, and do not build a second research framework.

The concrete next milestone is **one candidate commit that plays all sixteen 808 sounds and the mono voice through the intended control path, accompanied by reproducible reference comparisons and sample-exact implementation checks.** Reference mismatches may remain; they should be quantified and become the next small development tasks.

## 2. What the repository actually establishes

Snapshot: main `50d7aafc322474de0ad18c9c0a1294f36bba0248`; PR #73 `8c4e11547d7ae1bb80f4b77a5d760dc8c2d04145`; PR #74 `7935e768052c6ebf53631fd379659b52489778a8`. Both PRs remained open at the final check.

- **The complete 808 has a concrete implementation in [PR #74](https://github.com/2AMLogic/gf180-parasynth/pull/74).** A local merge-tree check against main found conflicts in `model/audio_measure.py` and `spec/NUMERIC-CONTRACT.md`. Resolve the estimator changes and publish one coherent contract revision, then verify the combined candidate. Earlier resource and correctness reports are useful evidence, but cannot substitute for this integrated build.
- **[PR #73's published diff](https://github.com/2AMLogic/gf180-parasynth/pull/73/files) implements part of its description.** It repairs the DAG workflow YAML and adds a workflow checker, alongside a nightly-control change. At the inspected head the Surge mapping, M3 evidence declaration and physical-build dependency coverage remain unchanged; the older silent-stub control also remains. Treat these as bounded finishing tasks. Adding a workflow checker is not evidence that the affected workflows have run successfully.
- #74 reports useful remaining sound targets: maracas attack shape, cymbal high-frequency energy, rimshot intermodulation, and clipping in an eleven-circuit simultaneous-hit test at its default drum gain. These are author-reported findings to reproduce on the combined candidate, not measurements newly performed in this review.

There is enough implemented work to integrate and measure. A new architecture or broader feature search would delay the useful next result.

## 3. A concrete ladder

| Rung | Deliverable | Completion condition |
|---|---|---|
| 0 — Trust the rig | Correct mappings, explicit plugin state, cached reference WAVs, metric controls | Each active reference passes pitch, waveform, path and non-silence checks; failures cannot turn into passing sound results |
| 1 — Integrated baseline | Complete kit plus mono voice, frozen candidate and first 32 cases | Render through the intended host/control schedule; obtain valid measurements for qualified targets; verify short model-to-I2S traces |
| 2 — Measurable improvement | One bounded sound correction per change | Its intended error decreases on fixed cases; adjacent notes/settings and implementation checks do not regress |
| 3 — Broad imitation | 80 development cases and 20 reserved cases | The same runner produces per-family comparisons, continuous error values, coverage and reproducible audio |
| 4 — Physical instrument | Current FPGA build, working host and captured output | Boot, controls, releases, timing and audio output work on the integrated candidate; explain capture differences separately from DSP differences |
| 5 — Player feedback | Compact blind audition pack and live instrument | Friends help resolve the remaining meaningful choices using a stable, already measured instrument |

Rung 1 establishes a baseline; it does not require all 32 sounds to pass before useful work can continue. Rung 3 is benchmark coverage, not an obligation to conceal poor matches or invent references. Physical host work can proceed alongside comparison work.

## 4. The 100-case sheet

| Family | Cases | Automated comparisons |
|---|---:|---|
| Drums | 32 | Sixteen anchor sounds plus documented variations; pitch trajectories, attack shape, spectral balance, decay, burst structure |
| Mono voice | 32 | Eight patch families across notes/settings/gestures; pitch, harmonics, aliasing, envelopes, glide, legato and modulation |
| Filters | 24 | Cutoff response, resonance and bass loss, drive, self-oscillation, moving cutoff and audio-rate modulation |
| Combined instrument | 12 | Identical event sequences; timing, voice/bus balance, headroom, interaction and output artifacts |

**First 32:** sixteen drum anchors, eight mono anchors, four filter probes and four combined performances. This tests the runner across the entire instrument. **Next 48:** broaden notes, control ranges, density and gestures. **Reserved 20:** unseen settings and phrases, selected before tuning.

For a drum without a second documented hardware setting, do not fabricate a variation by scaling its WAV. Use an already available, qualified software reference under a separately named profile, or leave the hardware comparison unscored. A missing corpus entry should not block the rest of the instrument. A different stochastic strike tests repeatability; it is not evidence of generalization to a new knob setting.

The sheet specifies scenarios, not frozen presets. The reference task must record exact plugin states and event vectors. Reserved cases must have exact settings committed or sealed before tuning; once their detailed errors guide development, they become development cases and need replacement for a fresh holdout claim.

## 5. Drive software instruments first

Use the existing DAW/plugin drivers. Start with the working paid Mini V3 setup as the main full-voice comparison. Use Moog Model D for selected cross-checks once its present rendering path is reproducible and cached. Use Surge for readable, diagnostic filter comparisons after correcting and checking its mapping. Give each reference its own versioned profile; never silently average conflicting emulations into an invented target.

For every render, record plugin name/version and binary hash where available, complete preset/state, parameter readback, sound-changing options, sample rate, host and block size, MIDI/automation events, gain, latency, random/vintage settings and renderer revision. Cache the WAV by these inputs. Version the analyzer and tolerance manifest separately so cached audio can be remeasured without rerendering or reactivating plugins.

Pin sound-changing options explicitly. Check behavior through audio as well as parameter names: a parameter with the right name can still have the wrong normalized mapping. Calibrate pitch, cutoff and envelope timing at a few development anchors, then freeze that mapping across notes and held-out settings. Avoid a separate hand-fitted knob mapping for every test sound.

For isolated filters, feed the same stimulus into a qualified external-input path when available. Time-box proving headless external input to one short task. If it fails, continue with a measured internal source and relative filter-response tests, and label the scope correctly. Do not stall the voice suite to buy and integrate another plugin.

Start with three repeated pilot renders per nominally deterministic setup and five for noise, free-running oscillators or vintage variation. These are a cheap check for substantial variance, not enough to claim tight statistical confidence. Add repetitions only where the uncertainty affects a decision.

## 6. Measure imitation and expressiveness directly

| Behavior | Test stimulus | Main quantities |
|---|---|---|
| Oscillator sound | Isolated saw/pulse/triangle at low, middle and high notes | Pitch in cents, harmonic levels in dB, foldback energy; validate the analysis floor on a known band-limited signal |
| Amp/filter envelopes | Notes of several durations and repeated notes | Rise time, decay and release in ms, trajectory error, retrigger behavior |
| Glide and legato | Specified overlapping and separated note pairs | Pitch trajectory, transition time, envelope retrigger, note priority and final release |
| Filter character | Low-level tones, stepped drive, resonance sweeps | Cutoff, peak location/gain, bass retention, harmonics and compression |
| Moving controls | Identical cutoff/wheel/modulation trajectories | Response delay, trajectory, sidebands and discontinuities |
| Drums | Single hits, accents, retriggers and paired-voice switches | Early/body/tail measurements, spectral bands, decay and timing |
| Ensemble | Identical timed phrases and coincident hits | Event timing, per-bus levels, clipping, reset/choke behavior and lingering output |

Only compare dynamics a reference actually implements. Do not reward an extra velocity response as faithful Model D behavior if the selected reference patch does not respond to velocity.

Preserve both raw-level and separately level-matched comparisons. Raw levels expose gain, accent and compression errors; level matching helps diagnose timbre. Correct known host latency once, rather than shifting every note independently and hiding timing defects. Prefer phase-tolerant spectral and envelope measurements for separate emulations; sample-by-sample equality is appropriate for our fixed-point model versus our RTL.

## 7. Scoring that improves before a test passes

For each required metric define an error, its units, analysis window and tolerance in a versioned manifest. A trajectory metric also needs a declared alignment and aggregation rule. Within a case, the sheet records:

`worst normalized error = max(metric error / metric tolerance)`

A value at or below 1 passes that case. The three measurement groups listed in a row may each contain several component measurements; the reported maximum must include every required component. A missing component invalidates the case rather than being omitted from the maximum.

Report four things for each candidate:

1. **Coverage:** valid measured cases out of planned cases, with missing/no-verdict reasons.
2. **Agreement:** cases inside all tolerances out of valid cases, separately by family and reference profile.
3. **Error movement:** continuous errors versus the frozen baseline and previous candidate, including the worst five mismatches and any regressions. This exposes improvement while a case still fails.
4. **Implementation status:** sample-exact agreement, timing, stability and actual output-path checks.

Do not invent universal similarity thresholds. Calibrate the first tolerances on reference repeats and deliberately altered examples, then freeze them before using the score to accept improvements. If a metric cannot distinguish a meaningful injected error from ordinary reference variation, give it no verdict and repair or replace it. Do not expand tolerances merely to make the current design pass.

Every intended difference keeps its original reference error visible. A deliberate product choice may change the release target, but it does not retroactively make the emulation comparison pass. Musician preference is recorded at the final audition, independently of automated reference agreement.

FAD may later provide a supplementary batch comparison. It was introduced for music-enhancement evaluation, and subsequent work emphasizes reference choice, embeddings and sample-size effects. It cannot replace these paired checks: shuffling the same audio clips among the wrong note or patch labels leaves the aggregate audio distribution unchanged. See the [original FAD paper](https://arxiv.org/abs/1812.08466) and [Microsoft's FAD toolkit and evaluation guidance](https://github.com/microsoft/fadtk). A collection of 100 related cases also does not establish human indistinguishability.

## 8. Make failures meaningful and iteration cheap

Each active metric gets a known-answer check and at least one relevant fault that actually runs: wrong pitch, wrong waveform, reduced noise level, altered decay, missing modulation, increased foldback or an I2S shift. The acceptance rule is **clean execution passes, altered execution completes, intended assertion fails**. A syntax error, missing plugin, import error or empty output is no verdict. A control used only at the output level proves analyzer sensitivity; separately retain RTL mutations to test implementation detection.

During development, run the affected cases, neighboring settings and a short integrated trace. Run the full acoustic matrix on frozen release candidates or a scheduled job using cached references. Run the expensive full RTL verifier once per integrated candidate when needed for its release evidence; do not duplicate it through several dependency paths. A sound comparison and a model-to-RTL proof answer different questions and both are necessary.

Keep the runner output simple: candidate commit, case ID, reference profile/hash, event hash, analyzer/tolerance versions, metric values with units, error/tolerance, validity reason, and links to WAVs and plots. Use that one result manifest to generate CI summaries and populate the sheet. Avoid manually maintaining a competing source of results in Excel.

## 9. Three bounded assignments

| Owner | Next assignment | Stop when |
|---|---|---|
| Integrator | Reconcile #73's actual repairs; resolve #74's estimator and contract conflicts; build one candidate | Relevant workflows execute; contract is coherent; short model-to-I2S cases pass and existing full evidence is regenerated where required |
| Reference/comparison owner | Correct mappings, qualify/cache existing plugins and hardware references, implement the first 32 case recipes | One reproducible baseline report exists, with reference repeats, sensitive controls and explicit missing comparisons |
| Host/output owner | Drive the integrated instrument using the exact event/control schedule, including timed drum coefficient writes | Note/trigger/release/parameter actions generate the expected samples; current FPGA and DAC capture demonstrate the same intended performance |

These are ownership recommendations, not newly launched agents. The integrator owns shared estimator interfaces and the numeric contract; other work should avoid simultaneous edits there. Split follow-on corrections into one observable mismatch per task, with a named failing measurement and a clear finish line.

After this baseline, use the measured backlog to choose the next correction. High-note aliasing, the maracas attack and cymbal energy are plausible candidates, but qualify and reproduce their measurements first. Preserve a known working version after each accepted change. The immediate progress artifact should be the first scored baseline and playable integrated candidate, not another expanded feature outline.
