# Why this project keeps producing confident wrong answers

Eight measurement claims, three area projections and two "confirmed defects"
were withdrawn in a single day's work. That is too many to treat as
carelessness, and the incidents have one mechanism in common. This document
names it and says what to automate, because the goal is a design and build
process that does not need a human to notice.

## The root cause

**Internal consistency is cheap to check. External grounding is expensive. So
work drifts toward the cheap check, and the cheap check feels like rigor
because it is rigorous in form.**

Every failure below is a version of that trade:

| what we did | cost | what it could not tell us |
|---|---|---|
| validated estimators against **our own model** | seconds | whether the estimator is right |
| tested the voice against **our own decision records** | seconds | whether the model is a Minimoog |
| verified **blocks** bit-exactly | minutes | whether the blocks talk to each other |
| computed area by **arithmetic** | instant | what routes |
| **argued** about 8 vs 12 modes | free | which variable the objective depends on |

None of those is wrong to do. Each is genuinely rigorous *within its frame*.
The failure is that the frame was never checked, and a suite that cannot see
outside itself reports success in exactly the same voice whether or not the
thing is right.

**The gradient is real and it will act on any agent**, not just a careless one:
internal checks are fast, deterministic and always available; external
grounding is slow, sometimes unavailable, and occasionally blocked entirely. An
agent under time pressure will take the cheap check every time unless the
expensive one is *mandatory and scheduled*, not aspirational.

## Five mechanisms, and what to automate for each

### 1. Measuring without a known answer

Nearly every withdrawn number came from running an estimator on real data and
reporting the output, having never run it on a signal whose answer was known.
A 5 ms moving average on a 56 Hz carrier. A Hann-windowed 700 Hz split that
returned 1.25 % where the true answer was exactly 18.55 %. An
amplitude-weighted centroid. Spectral flatness used as a comb-versus-noise
test.

**Calibrating on our own model does not count.** `moog_probe.py`'s "25 dB of
separation" was calibrated that way and turned out to be window leakage. A
self-comparison establishes repeatability, not correctness.

> **Automate:** an estimator may not be used by an acceptance test unless it
> has a closed-form ground-truth test — a signal whose answer is known
> *independently of the thing being measured*. Enforce with a meta-test that
> every measurement function reachable from an acceptance test appears in the
> ground-truth suite. Partly in place: `model/test_audio_measure.py` exists and
> found six estimator bugs on the day it was written.

### 2. No external referent for a whole class of claim

The drums have `docs/tr808-reference.md` — 110 facts traced to schematics and
service manuals — plus a real recording corpus. The voice has **neither**, and
so accumulated 42 rigorous tests that could all pass on a filter that sounds
nothing like a Moog. The gap was invisible because the test count looked
healthy.

> **Automate:** classify every test as **implementation** (against our model)
> or **fidelity** (against an external reference), and report the two counts
> separately per subsystem. A subsystem with zero fidelity tests is
> **UNVALIDATED** and says so in CI, however many implementation tests pass.
> Then the voice's gap is a visible red state rather than something a person
> has to notice.

### 3. The verified artifact was not the shipped artifact

The FPGA build omitted every drum module while its reports quoted utilization
for "the instrument". `synth_top` instantiated a placeholder while area figures
were quoted for the chip. `drum_kit`'s configuration storage did not exist in
RTL — the values were input ports a testbench drove. And **every bench drove
the register write port rather than the link**, which is why the control path
delivered 37 of 155 writes with every block still bit-exact.

One mechanism: **the thing under test was a different object from the thing
that ships**, and everything passed the whole time.

> **Automate:** every artifact asserts its own provenance against the thing
> that verified it. `make srccheck` is the working example — it fails the build
> if the routed file set differs from what the bench elaborates, and I broke it
> deliberately to confirm it fires. Generalise: reports carry the commit that
> produced them and are marked stale when it is not an ancestor of HEAD; a
> testbench that drives an internal port rather than a pin says so in its own
> output.

### 4. Claims outliving their evidence

The `modal_dp` excitation hazard was cited in briefs and documents for hours
*after* DR 0008 fixed it. The capability DAG carried red on four drum circuits
that had been repaired. A withdrawn snare figure survived into a GitHub issue.
A strict xfail stayed red for an unrelated reason and hid a real closure.

Stale findings are a distinct failure from wrong ones and need a distinct
remedy: being right once is not a property that persists.

> **Automate:** a claim in a document carries the test or commit that justifies
> it, and a checker flags claims whose backing test no longer exists, now
> passes, or predates the file it describes. When a tracked-defect marker
> fires, assert the failure is the recorded one.

### 5. Optimising a variable before measuring whether it matters

Hours went into 8 modes versus 12. The answer was that yosys pads the bank's
state to a power of two, so 9 through 16 cost **identically** — and that the
real variable was `NUMS`, which nobody had looked at. Hours went into the bass
drum, which measurement later ranked our *best* voice. Then into the snare's
noise balance, which was correct; the fault was burst length.

Each was a plausible hypothesis acted on before anyone measured where the
objective was actually sensitive.

> **Automate:** before a parameter debate is allowed to consume time, sweep it.
> A one-line sweep would have ended the modes argument in minutes. Make
> sensitivity analysis a gate on optimisation work, not an afterthought.

## A sixth, different in kind: rejecting imperfect evidence

`docs/discrimination.md` §8 rejected software-synth references because
comparing against them "would test our chip against another emulation". The
reasoning is valid. The consequence was **zero validation instead of imperfect
validation** — and it discarded the one property a hardware corpus cannot
supply: a reference you can set to a known patch.

When that reasoning was overruled, the first run found a term of Huovilainen's
paper that we had omitted (cutoff drift 7.92 pp over six octaves against Surge
Type 2's 0.62; worst error 6.85 % → 0.89 %), correctly diagnosed our excess
5th harmonic as the 16-entry `tanh` table rather than the structure, and
withdrew one of our own false claims.

> **Rule:** reject a reference only when a better one is actually available,
> never on principle. Imperfect evidence with its limitation labelled beats an
> unfalsifiable claim. Purity standards that produce no measurement are not
> rigour; they are the absence of it wearing rigour's clothes.

## What is already mechanical, and what is not

**In place.** Ground-truth estimator suite. Injected-defect controls on every
integration check, including the exact defect that shipped (`SPI_ADDR7`).
`make srccheck`. CI running the integrated verifier, not only block checks. A
negative control that mutates *arithmetic* rather than syntax — which caught
that inflating `rms` by 5 % passed all sixty ground-truth tests.

**Not yet.** The estimator meta-test. Implementation-versus-fidelity test
classification and the UNVALIDATED state. Report staleness. Claim-to-evidence
linking. Sensitivity sweeps as a gate.

Those five are the difference between a process that catches this class of
error and one that relies on someone reading carefully at the right moment.
