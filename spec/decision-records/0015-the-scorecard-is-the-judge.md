# DR 0015 — The scorecard is the acoustic acceptance authority

**Status: PROPOSED. Not ratified.** Revised after review; the first draft
contained the error it was written to prevent.

Answers #99.

## Decision

**The versioned per-property scorecard is the acoustic acceptance authority.**

A change is accepted when it

- produces a **meaningful improvement in at least one required property**,
- introduces **no property regression beyond its predefined allowance or the
  measurement's own uncertainty**,
- and **preserves required measurement coverage**.

Baseline and candidate are evaluated on the **same qualified measurement
basis**. `worst` summarises a case's bottleneck; **it does not replace
property-level checks.** A required measurement that is invalid or missing
yields **no verdict**.

### Why the first draft was wrong

It made `worst` authoritative — and `worst` **is an aggregate**, which this
document rejects everywhere else. Two failures follow directly:

| property | before | after |
|---|--:|--:|
| pitch | 2.0 | 1.5 |
| decay | 0.2 | **0.9** |
| `worst` | 2.0 | **1.5** |

`worst` improves while decay degrades 4.5×. And the reverse: decay 0.9 → 0.2
with pitch stuck at 2.0 is **real progress that the first wording forbade**,
because `worst` did not move.

**The property vector is authoritative. `worst` is its bottleneck summary.**
Where a trade-off is deliberate, record it explicitly rather than let an
improved maximum hide it.

## The measurement basis is versioned, and both sides use the same one

"Same qualified reference" is necessary and not sufficient. Both sides need the
same **reference recordings and settings, estimator implementation and
parameters, analysis windows and preprocessing, tolerances, and required
property set.**

**When an estimator is repaired, re-measure the baseline too.** Comparing an old
instrument's old measurement against a new instrument's corrected measurement
confounds two changes, and we have three estimator repairs in flight right now
(#139, #150, #156).

**Removing a broken metric must never improve an authoritative `worst`.** An
incomplete case shows **no verdict**. A clearly-labelled partial maximum may be
displayed for diagnosis; it is not a verdict, and a passing verdict is never
computed over whatever metrics happen to remain.

**A failing hold-out is evidence of a mismatch. A broken estimator is missing
evidence.** That distinction is the one this board exists to keep.

## Two independent questions, two kinds of evidence

| question | evidence |
|---|---|
| does the estimator measure the claimed property? | synthetic ground truth, adversarial inputs, independent calculation |
| does the correction work beyond what developed it? | held-out settings, recordings and machines |

**Running a defective estimator on unseen recordings does not make its
measurements trustworthy.** Estimator qualification and hold-out validation are
separate obligations and neither substitutes for the other.

A fit measured against the reference it was derived from **is** evidence — of
in-sample matching, which is a real development signal. It is not evidence of
generalisation, and the DR's earlier phrasing ("not evidence") overstated it.

**On our own tom correction (#154):** the second machine is external validation
only because neither its data nor its results shaped the law. **Once it is
repeatedly used to guide changes it is no longer held out**, and we should say so
the first time it is consulted for that purpose.

## A surrogate proposes; the exact rule accepts

**Every candidate is evaluated by the exact acceptance rule, whatever the
optimiser's loss.**

That is the whole safeguard, and it is stronger than the first draft's
"same metric" requirement — which was also *wrong*: a soft-max over the same
errors can improve while the true maximum worsens, so choosing an aligned
surrogate guarantees nothing.

Optimising sum-of-squares is **not** a second judge if it only proposes
candidates and cannot approve them. Aligned surrogates are preferred because
they waste fewer proposals, not because they make the acceptance check
redundant. This supersedes both #100 and the first draft's correction of it.

## The blind spots are demonstrated, so they become requirements

A 12 kHz tone, 6-bit requantisation and tail noise **pass every per-property
bass-drum metric** (#144). They are no longer hypothetical, and a judge that
knows about them and accepts them anyway is not defensible.

**Each becomes an analyzer fixture and an explicit artifact-detection
requirement**, with bounds defined from reference behaviour.

`mel_dac` remains a **diagnostic**, not a tolerance: it identifies a question the
interpretable properties have not answered, and firing means *write an
estimator*. Two conditions on it:

- **"Fires" needs a defined decision rule**, and reported ratios must carry
  **their absolute values and the floor's definition.** 71× / 238× / 356× against
  a floor is not interpretable without the denominator — a small one manufactures
  large multipliers.
- **One successful correction does not establish a false-positive rate.** Before
  it gates anything it must be shown not to fire across phase variation,
  stochastic variation and the other differences a legitimate reference is
  allowed to have.

## Scope: acoustic acceptance only

This authority is **acoustic**. It does not replace, and is not replaced by:

- bit-exact model-to-RTL verification
- register-map and timing correctness
- frame-deadline and link-budget checks
- physical implementation constraints

Those are feasibility and implementation requirements. Keeping them separate also
lets experimental changes be committed and measured **without pretending they are
release-qualified.**

## What is rejected as an acoustic judge, and why

- **Spectral distances.** On our real tom defect *all four* multi-scale
  distances rank the rungs **backwards**, and two put ×1.00 — the largest
  possible error — closer than ×1.14. A 2.74 % f0 error reads 0.307 against
  0.747 for a full octave (#144).
- **Knob-equivalents across voices.** On a shared ruler **12 of 16 saturate**
  (#143, #148). They remain useful *within* a voice over time.
- **Any learned or aggregate score**, for the reason this DR had to be revised:
  an aggregate hides the thing you need to see.

## Why decidable now

The alternatives were measured rather than argued. And #154 showed the board
doing what a judge must: **it got worse when a real defect was exposed**, rather
than flattering a change that had genuinely fixed the pitch.

A judge that only ever improves is not measuring anything.
