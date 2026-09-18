# Testing a player's instrument: software references and deliberate faults

Version 0.25 · 2026-09-18 · Companion to minimoog-research-v0.24.md

## Recommendation

Use one software Minimoog-style instrument as an external benchmark, a small set of independent DSP probes, and targeted fault injection. Keep the current fixed-point-model-to-RTL comparison. Generate reference recordings once and reuse them in ordinary CI. Obtain a small physical-reference recording set from a friend when convenient; defer buying a Minimoog until a specific recurring measurement need justifies it.

The product remains a great-sounding mono instrument plus the complete 808, with paraphony later. A software or physical reference helps us understand the sound. Deliberate improvements in bass, controls or response remain legitimate even when they increase distance from that reference.

This document verifies available software capabilities and proposes a testing workflow. No commercial plugin was installed or run, no hardware was measured, and the current repository was not inspected in this turn. Compatibility with the selected plugin must pass a short practical trial.

## Highest return, in order

| Priority | Work | Why it helps now | Finish line |
|---|---|---|---|
| 1 | Regressions for demonstrated defects and trustworthy test outcomes | Stops failures already seen from returning or being falsely declared caught | A healthy baseline; each chosen injected fault causes its intended assertion to fail |
| 2 | Small, deterministic DSP probe suite | Explains why a sound changed | Pitch, envelope, spectral, filter and output reports with validated measurements |
| 3 | One plugin benchmark with saved states and common stimuli | Adds an independently developed musical reference | Eight useful patch comparisons and a reproducible reference manifest |
| 4 | Filter-specific common-input comparisons | Supports the ladder-algorithm decision | Current/tuned/candidate models receive identical signals; report sound differences and cost |
| 5 | Small borrowed-hardware recording session | Checks whether software agreement reflects the intended physical sound | Documented model, settings, gain and repeated takes |
| 6 | A second plugin, larger MIR study, or hardware purchase | Resolves particular uncertainty remaining after the first five steps | A named decision that the extra evidence can change |

Priorities 1–4 can proceed without owning an analog synthesizer. References should be developed alongside the playable instrument, not become a prerequisite to every implementation improvement.

## Which software reference?

Start with a suitable plugin already installed and licensed. That often saves more time than debating small differences between emulations. Manufacturer fidelity claims are not independent evidence that a plugin is the most accurate.

| Option | Useful role | Setup considerations |
|---|---|---|
| Arturia Mini V | Convenient whole-instrument reference, especially if already owned | Save its vintage, drive, bass-compensation, effects and polyphony settings explicitly |
| Softube Model 72 | Strong candidate when filter comparison is central: includes both instrument and FX versions | Requires Softube/iLok accounts; verify host support and audio-plus-MIDI routing |
| Synapse The Legend HZ | Another whole-instrument comparator if already available | Reduce its extended architecture to the chosen comparison patch; verify state recall with the installed edition |

[Mini V's official page](https://www.arturia.com/products/software-instruments/mini-v/overview) documents modern voicing controls and Mac/Windows support. [Softube's product page](https://www.softube.com/plug-ins/model-72-synthesizer-system) documents the separate versions and installation requirements. [Synapse's page](https://www.synapse-audio.com/thelegendhz.html) documents its additional oscillators, effects and mono/poly modes.

My default: use Mini V if it is already on someone's machine. If selecting a new reference specifically for this work, trial Model 72 because its external-audio FX path is experimentally useful. This is a recommendation about testing convenience, not a claim that it wins an emulation-quality contest.

### The useful filter-specific option

Model 72 FX accepts external audio. Its manual describes an automatic gate that responds to input level; when disabled, MIDI gates the envelopes. [Model 72 manual, Getting Started](https://www.softube.com/user-manuals/model-72-synthesizer-system).

For controlled measurements, turn internal sound sources off, hold the amplifier gate open with stable settings, disable unwanted modulation, and explicitly configure input gain. Then feed the same sine, sweep, two-tone signal or saved oscillator render into the plugin and our candidate path. Otherwise a level-dependent gate can masquerade as filter behavior. The comparison still includes the plugin's external-input/amplifier path; do not label it a direct measurement of its isolated ladder core.

### A short automation trial, then a fallback

Try the chosen plugin in a Python host for at most 60–90 minutes of setup effort. This is a proposed time box, not a measured integration estimate. Success means: load, set/read parameters, restore state, render a note and release, reproduce a second render within understood variation, and export the expected audio length.

[Spotify Pedalboard](https://spotify.github.io/pedalboard/examples.html) documents VST3/AU instrument rendering from MIDI and effect processing from audio. Its API presents those as separate processing interfaces; do not assume a simultaneous audio-plus-MIDI FX path is supported. [API documentation](https://spotify.github.io/pedalboard/reference/pedalboard.html).

[DawDreamer](https://github.com/DBraun/DawDreamer) documents plugin state, MIDI, processor graphs and parameter automation. It is a candidate when the comparison needs richer routing or automated sweeps. Verify the exact plugin format, host version and required routing with a smoke test before committing the harness to it.

If the Python route stalls on activation, hosting or MIDI-controlled effects, render a saved project in an existing DAW and automate analysis of its exported WAVs. This preserves most of the testing value. Avoid spending the prep period building a plugin-hosting platform.

Run commercial plugins on a supported Mac or Windows machine. A host having Linux support does not make a Mac/Windows-only plugin load on Linux. Export versioned reference WAVs and manifests for analysis on the normal agent/CI machines.

Plugin state deserves verification: Pedalboard documents possible state leakage and plugin-specific incompatibilities. Repeat renders after a fresh load and with a defined preroll. [Compatibility notes](https://spotify.github.io/pedalboard/compatibility.html). The Legend HZ manual also states that its demo does not recall parameter states; a demo is suitable for a compatibility trial but may not support the intended reproducibility workflow. [Manual, §8.1](https://www.synapse-audio.com/legend/TheLegendHZ21Manual.pdf).

## The smallest useful comparison corpus

Start with eight patch families, using only features both engines support. Each family gets a documented state, a short event sequence and a few notes. Reserve some complete settings for evaluation before any fitting.

1. Single saw at low, middle and high pitch, filter open.
2. Single pulse at the same pitches.
3. Three detuned oscillators held steadily.
4. Short bass pluck with a filter envelope.
5. Resonant sweep with known timing.
6. The same phrase at two mixer-drive levels.
7. Legato/glide and release behavior.
8. A moving or noise-based patch, when implemented in our engine.

Capture three repeated reference renders for representative cases. If the plugin uses free-running phases or random drift, those repeats establish variation rather than bit-identical output. Switch off optional random variation for numerical probes when possible; retain a separately labeled musical variation set if useful.

For comparison, disable chorus, delay, reverb, stereo doubling, unison and extra modulation unless they are intentionally part of the test. Record velocity behavior. Use MIDI note numbers rather than octave labels, which can differ between products. Verify tuning and range from the actual generated frequency.

A normalized knob position of 0.5 need not mean the same cutoff, drive or decay in two engines. For isolated diagnostics, calibrate a small mapping using measurable behavior. Freeze that mapping before evaluating held-out settings. For performance tests, compare the chosen control law as part of the instrument. Do not independently optimize every test patch until it matches.

Reference manifest fields: plugin/version/format; host/OS; sample rate and block size; state file and checksum; all relevant parameter values; MIDI/control events; preroll/tail duration; randomness settings; input and output gain; measurement version; development/holdout designation; audio checksum.

## Four complementary test layers

### 1. Correctness: hard gates

These do not depend on matching a Moog:

- Fixed-point model and RTL agree on the agreed numeric contract, event schedule and decoded I2S samples.
- Note-on/off, note priority, sustain/retrigger and control writes obey our chosen behavior.
- No unintended overflow, wraparound, dropped frames or register collisions.
- Supported worst-case drum and mono workloads meet sample deadlines.
- Required checks executed and produced valid verdicts.

Changing the sound model can intentionally change golden audio. Preserve the old report, explain the model change and regenerate references deliberately. Do not make stale goldens pass by weakening the comparison.

### 2. DSP diagnostics: independent expectations

Use known analytic inputs and independently justified models to test:

| Block | Measurements |
|---|---|
| Oscillator | Frequency error, harmonic ratios, DC, level, high-note aliasing and continuity |
| Envelope | Attack/release timing and shape, rapid retrigger, short-note behavior |
| Filter | Small-signal response, resonance frequency, level-dependent harmonics/intermodulation, self-oscillation and recovery |
| Noise/drums | Spectrum, level, pitch trajectory, attack energy and decay |
| Output/mix | Headroom, intended saturation, channel/bit correctness and timing |

First validate measurement primitives against closed-form signals. A waveform match between two implementations using the same incorrect model is insufficient evidence of correct acoustics. A high-rate reference must converge and be properly low-pass filtered before downsampling; merely running the same faulty equations faster is insufficient.

Only assert properties in the regime where they apply. For example, simple linear-filter scaling and superposition checks are not universally valid in an intentionally saturated ladder.

### 3. External reference comparison: diagnostic evidence

Compare envelopes, pitch trajectories, harmonic structure, multi-resolution spectral representations, and level-dependent behavior. Preserve raw level for drive/response tests; also offer output-level-matched comparisons for timbre. Apply listening normalization after nonlinear processing.

Free-running analog-style oscillators need not match sample by sample. Do not fail a timbre comparison solely because phase differs. Equally, do not align or time-warp away the attack and timing defects being tested.

A reference difference can mean a defect, a parameter mismatch, a different modeled unit or an intentional voicing choice. The report should help distinguish these. A plugin is an external model, not physical ground truth, and a frozen old build is a regression baseline, not proof that the original sound was good.

FAD and a discriminator can be added after these diagnostics are productive. Neither is the first purchase or first engineering task. FAD is sensitive to reference choice, embedding and sample count. [Gui et al., 2024 revision](https://arxiv.org/abs/2311.01616v2). With a small initial corpus, direct probes generally offer more actionable explanations. A classifier near chance does not by itself establish perceptual indistinguishability.

### 4. Musician acceptance

After automated gates, give friends a playable build and a short set of level-matched, randomized comparisons. Ask whether the attacks, bass, resonance, movement and control response feel good. Preserve preference and resemblance as separate questions. This is the final product check; it need not become the repetitive debugging process.

## Fault injection as a general policy

Adopt targeted mutation testing for meaningful behavior and important measurements. Standard mutation testing distinguishes killed, surviving and invalid mutants; compile/runtime failures are not evidence of a successfully tested behavioral defect. [Stryker's state definitions](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/).

Proposed policy:

> Every fixed correctness or DSP defect gets a regression that fails on the broken behavior. Every important new behavioral gate demonstrates sensitivity to at least one valid fault relevant to that gate. The clean baseline must pass; the mutant must execute; the expected assertion must detect it. Harness failures produce no verdict.

This is not a demand for mutation tests on every small UI or documentation change, nor for an arbitrary 100% mutation score. Equivalent mutants and intentional sound choices need judgment. A surviving meaningful mutant exposes a gap in the test's sensitivity, its stimulus, or the stated requirement.

### Initial deliberate faults

| Fault | Expected detector | Why it belongs |
|---|---|---|
| Restore the known I2S bit-timing error | Receiver-style decoded-word test | Recreates a demonstrated interface failure |
| Multiply the RMS result by 1.05 | Closed-form RMS fixtures | Tests the measurement layer itself |
| Reduce snare noise by 16 dB | Body/noise balance and raw-level probe | Recreates a reported sound defect that normalization could hide |
| Bypass the ladder | Small-signal frequency-response test | Proves that a “filter works” gate notices an absent filter |
| Perturb pitch or a cutoff coefficient beyond the declared tolerance | Frequency/response estimator | Tests numeric sensitivity with a controlled error magnitude |
| Break note release | Event trace and tail/silence behavior | Catches a musically obvious failure without a listening request |
| Make the wrong modulation route depend on audio mute | Route-isolation test, if that route is supported | Tests the chosen control contract |
| Drop a scheduled sample update | Deadline and decoded-output comparison | Verifies integrated timing independently of audibility claims |

Use named, buildable variants or explicit test-only switches. Verify that the intended fault is active. A text replacement that produces invalid syntax is an invalid experiment. Run faults one at a time and keep the clean reference/checker unchanged, except when the checker itself is the deliberate mutation target.

### Required outcome handling

| Situation | Verdict |
|---|---|
| Clean baseline fails | Baseline failure; fix before interpreting mutations |
| Active mutant runs; expected behavioral assertion fails | Detected |
| Active mutant runs; expected assertion still passes | Survived; investigate sensitivity or requirement |
| Injection was not activated | Invalid experiment; no verdict |
| Build/import error, missing dependency, required skip, missing result or unexplained timeout | No verdict |
| An unrelated test fails | Does not satisfy the intended mutation gate |

Check collected/executed test counts, named assertion outcomes and stimulus coverage, not just process return codes. A required no-verdict outcome must keep the release gate unsatisfied. Some generic mutation tools count timeouts as detection; for these audio/DSP checks require an attributable assertion. A deliberately tested liveness deadline is a separate, explicitly specified case.

The mutation report should record the fault identifier, application success, build success, executed test, expected assertion, actual failure and result. Keep injected versions out of release artifacts. Retain a small fixed set of known faults, then add cases when new defects teach us something.

## A bounded next work session

The following is a proposed allocation of one working day, not a runtime prediction:

1. Verify current test health and choose four demonstrated defects for regression/mutation checks.
2. Generate known-signal fixtures and validate pitch, RMS, envelope and spectrum measurements.
3. Spend up to 60–90 minutes establishing one plugin render path. Fall back to an existing DAW if necessary.
4. Save the eight patch families and a small filter-input set; generate reference manifests and repeat renders.
5. Compare our current engine and one meaningful candidate; fix the most consequential diagnosed difference.
6. Save a usable instrument version with its report, rather than an unresolved collection of experiments.

Use short deterministic checks on changes, broader parameter/fault sweeps at suitable integration points, and routed worst-case verification for releases. Refresh commercial-plugin renders when the reference set changes; routine CI consumes the cached audio. Benchmark actual test durations before deciding which jobs run on every push.

Minimal deliverables: a probe/event specification, plugin state plus reference manifest, reference WAVs, metric tests, a fault registry, and a generated report separating correctness, reference difference and musical preference. This can be a few scripts and data files in the existing project; a new evaluation platform is unnecessary.

## When would buying a hardware Minimoog make sense?

Buy when repeated physical access is blocking decisions that matter: sustained calibration work, circuit-revision research, or a product promise that requires detailed hardware validation. First write the questions that a purchase will answer and try a friend's unit for the highest-value captures.

The current Model D manual lists MIDI input for notes, velocity, pitch bend and mod wheel, and separate CV inputs. Full panel recall/automation is not part of that listed MIDI interface. Owning the hardware therefore does not automatically provide software-style parameter sweeps. [Moog manual, p. 81](https://cdn.inmusicbrands.com/Moog/Model%20D/Minimoog_Model_D_Manual.pdf).

One physical unit is a valuable reference, with its own calibration and variation. Buying it does not by itself improve the test harness, define the desired sound or prove that our instrument is enjoyable. For the immediate goal, the highest-return combination is one working software benchmark, sensitive automated tests, and a small later physical cross-check.

## Decisions carried forward

- Preserve the player's-instrument goal; accurate emulation is useful evidence and an optional deeper research direction.
- Keep physical references important and prepare their capture without making a purchase a prerequisite.
- Compare the filter candidates from v0.24 under common inputs and gain conditions.
- Freeze and preserve known-good instrument versions.
- Add paraphony after the mono instrument is good.
- Use targeted fault injection to test the tests, with explicit no-verdict outcomes.
