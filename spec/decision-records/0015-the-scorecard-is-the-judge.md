# DR 0015 — The scorecard is the judge

**Status: PROPOSED. Not ratified.**

Answers #99, which has blocked every coefficient change since it was filed.

## Decision

**`docs/scorecard/` is the judge. One judge, and it is per-property and
per-case.** A change ships when it improves its case's `worst` without
regressing others, measured on the same qualified reference.

Three things are explicitly **not** the judge:

- **Spectral distances** — measured, not argued: on our real tom defect, *all
  four* multi-scale spectral distances rank the rungs **backwards**, and two put
  ×1.00, the largest possible error, **closer** than ×1.14. A 2.74 % f0 error
  reads 0.307 against 0.747 for a full octave (#144).
- **Knob-equivalents** — the unit does not survive a shared ruler. Frozen on
  one, **12 of 16 voices saturate**: our error is largely not on the machine's
  knob axis at all (#143, #148). They remain useful *within* a voice over time.
- **Any learned or aggregate score.** An embedding distance of 0.3 does not say
  whether the decay or the pitch is wrong, and a design loop needs a metric that
  says what to fix.

## Independence comes from held-out data, not a different formula

**Fit and score with the same metric.** This corrects #100, which said the
opposite and was wrong.

If a smooth surrogate is needed for optimisation, it must be a surrogate for
**that metric** — a soft-max over the same normalised per-metric errors — never
a different quantity. Optimising sum-of-squares while scoring a max is precisely
the two-judges failure #99 was filed about, reintroduced as its own remedy.

Independence comes from **settings and recordings the fit never saw.** Where no
sealed hold-out exists, say so; a fit against a reference it was derived from is
not evidence. The tom correction (#154) is the pattern: the law came from one
corpus and was scored against a different machine's recordings, which were an
**unarranged hold-out**, plus four deliberately unseen splits.

## What the guard is, and is not

`mel_dac` enters as a **blind-spot detector**: no tolerance, not included in any
case's `worst`, and firing means *go write an estimator*, never *adjust a
coefficient*. It earned that role — a 12 kHz tone, 6-bit requantisation and tail
noise **pass every per-property bass-drum metric** with an order of magnitude to
spare, while it flags them at 71×, 238× and 356× its floor (#144).

**It must be shown not to fire on a legitimate correction before it gates
anything.** A guard that penalises fixing the toms is worse than no guard.

## Two standing limits on the judge itself

1. **Do not compare `worst` across cases using different estimators.** `D10A`
   and `D13A` share a name and a tolerance and nothing else — different
   estimator, window and arithmetic (#109).
2. **A board number is only as good as its instruments**, and three are known
   defective right now (#139, #150, and the four decay no-verdicts that rest on
   #139). A case's verdict is provisional while its estimator is under repair,
   and the board says `no verdict` rather than guessing.

## Why this can be decided now

Because the alternatives were measured rather than debated. #144 ranked the
spectral distances against a defect whose true magnitude we know from 99
hardware files. #143 and #148 showed the knob-equivalent's ruler does not hold
across voices. #154 demonstrated the scorecard doing the thing a judge must do:
**it got worse when a real defect was exposed**, rather than flattering a change
that had genuinely fixed the pitch.

A judge that only ever improves is not measuring anything.
