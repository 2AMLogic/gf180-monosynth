# A concrete ladder from software references to instrument audio

Version 0.27 · 2026-09-18 · Supersedes the execution priorities in v0.25 and v0.26

**Decision: freeze the reference choices for one milestone and use them to deliver one measured sound improvement through the real output path.** The milestone is a playable mono instrument with credible Moog-like bass, leads and filter movement, alongside the existing 808 work. Exact reproduction of every Model D behavior remains optional. Paraphony follows a working mono instrument.

The supplied report says that a DawDreamer driver and property estimators already exist, Moog's app has been bought, Mini V3 is owned, and Model 72 is being trialled. Treat these as reported status. This document is an execution plan, not a claim that I ran the rig or verified its private code. Public emulator capabilities were checked against the linked documentation.

**Lock the roles now**

| Reference | Decision for this milestone | What its evidence means |
| --- | --- | --- |
| Moog Model D app | Preferred musical target. Qualify automation within one 60-minute setup budget. | A chosen software interpretation of the instrument whose sound the user likes; agreement is not proof of physical Minimoog equivalence. |
| Mini V3 | Use immediately through the reported working driver. If Moog automation misses the setup budget, make Mini V3 the primary automated reference for this milestone. | A practical whole-instrument comparison. Use the installed V3's actual controls and state. |
| Surge XT | Retain for targeted filter diagnosis and source inspection. | Useful implementation evidence. Matching a related algorithm can reproduce its approximations; a difference is not automatically a bug. |
| Model 72 FX | One bounded external-audio trial when the filter comparison needs it. Use it if it works; buy only if it contributes useful measurements. | A further modeled filter path, including surrounding stages. |
| Diva | Remove from this milestone's reference runs. Preserve the adapter and quarantine demo-derived results. | Potentially useful later, but redundant now; not invalid simply because it is a modular analog-modeling synth. |

Do not average all plugins into a synthetic “true Minimoog.” Freeze one musical target. Use another implementation to investigate a named discrepancy, not to reopen the choice after every result.

Three corrections matter. Moog's manufacturer provenance makes it a relevant target, not an infallible oracle; its app also includes departures from the original instrument. Surge's Vintage Ladder Type 2 is based on related published work, but configuration and numerical implementation still affect its output. Diva contains a ladder model; the concrete contamination risk in the reported unlicensed setup is its demo crackling. [Moog app](https://apps.apple.com/us/app/minimoog-model-d-synthesizer/id1339418001), [Surge manual](https://surge-synthesizer.github.io/manual-xt/), [Diva documentation](https://u-he.com/products/diva/).

**The ladder**

| Rung | Work | Required evidence before calling it done |
| --- | --- | --- |
| 0. Preserve a working baseline | Record the commit, build, current presets and two short musical renders. Run existing correctness tests. | Reproducible current audio; failing or unavailable checks explicitly listed. A baseline may contain known defects. |
| 1. Qualify the reference and render driver | Prove note, control, state and audio routing; freeze settings; collect repeated renders. | One qualified automated reference, raw WAVs, complete manifest, repeatability report and a caught driver fault. |
| 2. Run the existing measurements | Apply the existing estimators to reference and current engine outputs. Inspect the largest differences. | A baseline table with units and variability, a small held-out set, and a ranked list of at most three actionable discrepancies. |
| 3. Improve one behavior | Fix a demonstrated defect or the most consequential discrepancy, one cause at a time. | Before/after measurements, expected-failure regression, held-out improvement, and audio rendered from the implemented design. |
| 4. Prove musical interactions | Exercise a bass, a resonant moving sound and a legato lead, including one passage with the drums. | Versioned musical fixtures, no correctness regression, documented sonic trade-offs and a concise audition pack. |
| 5. Prove delivery through the output | Drive the production control interface, check decoded I2S, then capture the board's line output when available. | Exact digital agreement under the specified timing contract; a separate measured analog-output report. |

Keep the two musical fixtures and the short digital-output test running from rung 0 onward. The later rungs expand their coverage; they do not postpone all integration testing until the end.

**Rung 1: trustworthy input and output**

Reuse the existing driver. The Moog setup budget is a stop rule for integration exploration, not permission to accept an unreliable reference. If it does not qualify, proceed with Mini V3. Likewise, allow at most 60 minutes for a new Model 72 external-audio route. Failed integration produces a short blocker record and does not hold up the existing measurement path.

Qualification uses three simple scenarios: an isolated note with an obvious note-off, two substantially different cutoff settings, and a scripted cutoff movement. A pitch change must change measured pitch; a cutoff change must change the appropriate spectral region; a note-off must initiate the configured release. Checking parameter names or readback alone is insufficient: the resulting audio must respond correctly.

Capture a short instance of one scenario in the normal plugin UI/DAW as a one-time sanity check if readily available. Compare the measured behavior with the scripted render, allowing for free-running phase and drift. Do not build a separate DAW automation system for this check.

Use the instrument's intended sample rate, initially 48 kHz, and pin block size, mono mode, effects, gain, random variation controls, note priority and retrigger settings where exposed. Verify the actual controls of the installed edition. Record unavailable controls rather than inventing settings. Render tails long enough for the behavior being measured; do not classify a deliberately long release as a stuck note.

Start with five fresh renders of each qualification scenario and a few repeats in an already-used instance. Distinguish changes caused by instance history from ordinary variability. Five is a pilot, not a reliable estimate of rare failures or a basis for tight population-level claims. Save individual metrics and takes; increase repeats only where uncertainty prevents a decision. Identical files establish determinism only for the tested procedure.

Prove one meaningful driver failure is caught: for example, suppress the intended cutoff automation while leaving the render otherwise valid. Its spectral-motion assertion must fail. A missing plugin, silent license failure, import error or skipped test is no verdict and leaves qualification incomplete.

**The cached reference is a measurement artifact**

Save raw audio plus plugin/build identity, state/preset hash, parameter map and values, source audio, timed notes and controls, sample rate, block size, host version, reset/preroll/tail procedure, and replicate/seed identity. Include audio checksums and the measurement-code version. Separate raw-render identity from analysis identity so corrected estimators can reanalyse existing takes.

Acquisition must bypass the cache to obtain fresh repeats. Changing an event or relevant state must change the render key. A corrupt or mismatched artifact must be rejected. Ordinary CI uses frozen reference recordings; refreshing them is a deliberate measurement operation. Reference assets, fixtures and thresholds are versioned together.

**Rung 2: run the probes before extending the framework**

The reported 28 analytic estimator tests are useful groundwork, not evidence about our synth or any emulator until actual renders pass through them. Begin with the existing estimators and a small fixed set of conditions. Do not build a full Cartesian product of controls.

| Property | First useful probe | Report |
| --- | --- | --- |
| Oscillators | Single saw at low, middle and high notes; square and triangle at the middle note; low drive | Pitch in cents, harmonic levels relative to the fundamental, unexpected spectral components and pulse duty where measurable |
| Envelopes | One short pluck, one slow attack/release, and repeated or legato notes | Attack/decay/release trajectories and times; retrigger behavior; residual output after the expected tail |
| Glide and modulation | Up/down transitions over two intervals; one controlled modulation case | Pitch trajectory, transition duration, direction and modulation depth/rate |
| Filter calibration | Low-level excitation at low/middle/high cutoff with low resonance | Measured cutoff, passband gain and response curve |
| Resonance and drive | A small resonance sweep at fixed cutoff; several input levels | Resonance peak, bass attenuation, output compression and harmonic change |
| Filter movement and noise | One cutoff trajectory; a separate isolated noise render if noise is implemented | Control lag or discontinuities; time-varying spectrum; noise spectrum and level |

A high-cutoff whole-instrument recording is not necessarily an isolated oscillator: its filter and amplifier can still color the signal. Label the measured path honestly. Do not identify every non-harmonic component as aliasing without checking drift, modulation, analysis-window leakage and noise.

Calibrate meanings before comparing numbers. A knob position of 0.5 can mean different cutoff, envelope duration or resonance in two implementations. Save the raw controls, establish a simple mapping on a few calibration points, then test unused points. Do not fit a new arbitrary correction separately to every comparison patch. Keep input drive and output gain distinct; matching output loudness alone does not match the filter's nonlinear operating point.

Reserve at least one unused note or setting per tuned property and one unused control trajectory before fitting. Once examined to guide a change, that case becomes development data and no longer supports a claim of untouched validation.

The report should contain the baseline error, reference repeat range, estimator limitations and a proposed acceptance band for each property. Freeze the bands before tuning, in meaningful units such as cents, milliseconds or dB. These are engineering choices for the intended playable range, not universal thresholds of Minimoog authenticity. If variability is too large to resolve the chosen band, report an unresolved measurement; do not widen the band until it passes.

Avoid sample-by-sample equality against unrelated emulators. Free-running oscillators can have different phases while exhibiting the same useful properties. Equally, a good aggregate spectral score must not hide a bad attack, missing release or broken knob response.

**Rung 3: convert evidence into one audible improvement**

Check the reported tanh guard and cutoff-unit defects first. If they are real and unresolved, write minimal failing regressions and fix them before tuning a new model. If already fixed, preserve the regressions and move on. A known arithmetic or unit error needs no vote from several emulators.

For every subsequent change, record five things: the observed discrepancy; the proposed cause; the targeted measurement; the expected direction of improvement; and the properties that must not regress. Then make the smallest plausible change, render again, and check held-out conditions. Do not let the implementation agent silently rewrite the metric or reference to make the candidate pass.

Use common-input experiments when the filter is implicated. Feed the same stored signal to our filter path and one qualified reference path. Start with quiet excitation for calibration, then a harmonic-rich signal and a few drive levels for nonlinear behavior. Confirm the input, gating and gain path before interpreting a discrepancy.

Model 72 is useful here but external-audio processing is not unique to it. In Surge, use the Audio Input oscillator, which feeds the voice architecture; the similarly named effect is downstream of the voice filters. Model 72 FX has an automatic gate that must be configured explicitly for controlled tests. Both comparisons can include amplifier/input-stage behavior. [Surge routing documentation](https://surge-synthesizer.github.io/manual-xt/), [Model 72 manual](https://www.softube.com/user-manuals/model-72-synthesizer-system).

For the filter itself, the improvement ladder is: correct arithmetic and units; calibrate cutoff, drive and feedback behavior; fix demonstrated numerical artifacts; then consider one alternate algorithm only if a specific residual problem warrants it. Compare the current repaired model with one candidate, not a catalog of filters. Any candidate must also meet the shared sample deadline, fixed-point requirements and measured hardware budget.

A candidate earns promotion when the chosen error falls by more than the unresolved measurement variation on reserved cases, required correctness checks remain green, and material changes elsewhere are disclosed and accepted. An intentional musical trade-off may be valid; record it as a trade-off rather than calling it a fidelity improvement. A saved reference/model/RTL output set accompanies the change.

**Rung 4: establish that the pieces form an instrument**

Use three dry musical fixtures of roughly 8–12 seconds each: a weighty bass phrase across several notes; a resonant phrase with continuous cutoff movement and changing drive; and a legato lead with glide, modulation and note release. Build on existing fixtures wherever possible. One bass passage should also run with the 808 to expose headroom and integration faults.

Each fixture specifies notes, timing and control gestures in musical units, with a recorded mapping into each implementation. Preserve both raw-level recordings and copies matched with one constant gain per clip. Do not use dynamic normalization that conceals envelope or gain problems. Keep delay, chorus and stereo doubling out of the initial dry comparison.

Automated reports should flag missing events, discontinuities, unintended clipping, pitch mistakes, broken releases and regressions in the chosen timbre measurements. Short blind auditions then answer preference and musical usefulness. Listening validates the musical decision after the diagnostic work; it should not be the method for locating a wrong register or envelope equation.

Do not use a low FAD score, classifier confusion or reference agreement as a standalone “sounds great” gate. These may become useful later when a larger, appropriately controlled corpus would change a concrete decision.

**Rung 5: prove that the driver and hardware deliver the sound**

Keep three separate comparisons:

| Comparison | Appropriate requirement |
| --- | --- |
| Emulator audio versus our design | Acoustic measurements with explicit tolerances and control calibration |
| Frozen fixed-point specification versus RTL and decoded I2S | Exact sample agreement for deterministic fixtures, with specified control timing and latency |
| Decoded digital samples versus captured DAC line output | Gain, timing, response, noise and distortion measurements allowing for converter and capture-chain behavior |

Exercise the production host driver and UART/SPI/control path for at least one musical fixture. Directly setting internal model registers is useful for diagnosis, but cannot establish that the product interface works. Compare the documented accepted event timing with output samples so a lost or late control write is visible.

The short digital suite should include signed values spanning positive and negative samples, channel distinction, note-on/off, reset, retrigger, a cutoff movement and a period with drums active. Include an injected serializer timing fault and one suppressed/misdirected control event. The clean run must pass; each active fault must fail the intended assertion. No-test and infrastructure failures remain no verdict.

On a board, capture the actual line output with an audio interface. First characterize the capture path with silence and a known tone. Check for wrong pitch/sample rate, channel errors, distortion, clipping, noise and dropouts. Account for delay and independent sample-clock drift before comparing recordings. Do not require bit equality after analog conversion, and do not normalize away a gain defect.

The speaker gets a separate short usability check. The primary sound-quality target is the proper line output through a good playback system. If no board/capture path is available, publish the completed digital milestone and state that analog-output validation is pending.

**Execution limits and ownership**

Use one owner for reference state, fixtures, measurement validity and reports. A second owner can fix the selected DSP issue once its failing case exists. Integration must use that same frozen fixture set. Additional reference-shopping or estimator-rewrite work requires a specific measured blocker.

Within the first two-hour work block, aim to produce one qualified reference path and a small real baseline report. This is a work budget, not a promise about plugin integration. If it cannot be achieved, report the exact failing operation and use the established fallback; do not spend the whole block silently building another framework.

The next milestone is one demonstrated improvement with before/after audio and a decoded-output regression. Expand coverage afterward. Limit the active discrepancy list to three. After each fix, rerank it from the measurements instead of starting new surveys.

During the ten-day preparation period, qualify hosts, capture references, run controls, establish baselines and rehearse the process. The four-hour hackathon should use pinned tools and cached references. A proposed schedule is: 0–20 minutes reproduce baseline; 20–100 fix the selected discrepancy; 100–160 validate and integrate; 160–210 render and audition; 210–240 stamp and package the working build. If a candidate fails, ship the preserved baseline and its honest report.

Tag only capabilities actually demonstrated. Keep the comparison report, input manifest, raw audio, exact-test results and implementation revision together. The desired outcome is a sequence of working instruments whose sound and delivery become measurably better, with a clear reason for each next change.
