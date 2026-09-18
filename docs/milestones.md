# Milestones

Six, in order. Each names its **evidence**, its **blockers**, and what it does
**not** claim. No aggregate "quality" number — progress is cells and milestones
moving, not a score going up.

**Coverage is reported alongside results, always.** *"20 passing, 4 failing,
6 without verdicts"* is honest; *"83 % passing"* conceals the missing
verification. A milestone needs **both** sufficient valid coverage **and**
passing critical requirements, or the cheapest route to green is to make rows
unmeasurable.

---

## 1. Reference rig qualified · **IN PROGRESS**

Every comparison downstream is worthless until the rig is known to produce what
it claims. We have already had three instances of it not doing so.

| | |
|---|---|
| ✅ | Diva identified as an **unlicensed demo** — 20 broadband clicks in 360 s — and every Diva number withdrawn |
| ✅ | Parameter **name check at construction**, which caught Surge renaming 259–267 by oscillator type (265 is "Unison Voices" or **"High Cut"**) |
| ✅ | **Run-to-run variance** measured: ours 0.000 pp, Surge 0.000, Mini V3 0.003 |
| ✅ | **Surge works as an FX path** — flat to 0.07 dB above 100 Hz, so Model 72 is not needed |
| ✅ | **Model D renders via REAPER** (`rms 0.346`, 130.14 Hz for note 60) after failing headlessly |
| 🔴 | **Waveform mapping bug** — the driver appears to request one shape while labelling another |
| ⬜ | Qualification as an **automated preflight** (#77), with deliberately-wrong setups proving it rejects |
| ⬜ | Plugin state saved **with the audio**, not a patch name |

**Does not claim:** that our oscillator comparison figures are trustworthy. They
are not, until the mapping is fixed and re-rendered.

## 2. Analyser ground truth · **DONE, and it keeps earning**

| | |
|---|---|
| ✅ | Every estimator validated against a **closed-form** signal; six estimator bugs found the day it was written |
| ✅ | Injected defects required to move each property, with a **blindness matrix** showing which properties *cannot* see each defect |
| ✅ | That matrix found a real hole: a **uniform 30 % cutoff error is invisible to a non-uniformity metric by construction** |

**Does not claim:** that an estimator validated on synthetic signals behaves on
real recordings. Five measurements in one session were wrong before they were
right; all five were caught by a control rather than by inspection.

## 3. Complete instrument integrated · **NOT DONE**

| | |
|---|---|
| ✅ | Complete Minimoog voice merged — noise, oscillator-3 modulation, full waveform set, 369 tests |
| ✅ | Complete 808 built — **all 16 sounds on 11 circuits, 102 acceptance tests under STRICT** |
| 🔴 | The 808 is **on a branch**, not on main |
| 🔴 | **`synth_top.v` still instantiates `drum_section_placeholder`** — the shipping top level does not contain the complete kit |
| ⬜ | RTL reproduces the complete kit bit-exactly |
| ⬜ | Playable access: the FPGA needs its SPI host, **including the timed writes the kick attack and tom pitch movement depend on** |

**Branch-local success and integrated completion are separate status fields**,
and conflating them is how "the 808 is complete" became misleading.

## 4. Acceptance cases measured · **DESIGNED, NOT POPULATED**

Scorecard design in #75: five cell states, per-sound and per-property, never
aggregated, every row naming a **specific** target.

**Three axes kept separate**, because merging them is how a scorecard starts
lying:

- **reference fidelity** — how closely we reproduce a named reference
- **digital quality** — aliasing, noise, numerical behaviour
- **functional correctness** — bit-exact model ↔ RTL

*Lower aliasing can be an improvement without being more faithful to any
reference. Bit-exact RTL agreement establishes neither musical property.*

**Blocked on milestone 1**, for reference-comparison cells only. Cases for
functional correctness and digital quality can be built now.

## 5. Critical discrepancies resolved · **NOT STARTED**

| discrepancy | status |
|---|---|
| **Aliasing 19–32 dB worse**, worsening with pitch | largest known defect; magnitudes provisional pending milestone 1 |
| **2× oversampling made aliasing worse** (−42.7 → −33.1 dB) | *unexplained*; first question to a DSP expert |
| Excitation shape — machine 41.2 % of first 4 ms in 80–150 Hz vs our 22.3 % | measured, not built |
| Integer-hertz cutoff registers — **53.7 cents/LSB at 30 Hz** | reaches the control interface; needs coordination |

## 6. Held-out cases and regression controls · **NOT STARTED**

Tolerances chosen **before** tuning to pass them, with settings held out so
matching the calibration examples does not become the objective.

---

## What this dashboard refuses to do

- **Produce one number.** There is no "synth quality" score and there will not be.
- **Let coverage hide.** A milestone with high pass rates and low coverage is not
  advancing.
- **Merge the three axes.** See milestone 4.
- **Treat "no verdict" as harmless.** It is not evidence we are wrong; it *is*
  missing verification, and it is counted as such.
