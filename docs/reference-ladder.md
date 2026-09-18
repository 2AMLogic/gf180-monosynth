# Using the emulators: a ladder with gates

Seven rungs. **Each answers a question and can fail**, and a failure stops work
on everything below it rather than producing data nobody can act on. The point
is to find out early which differences are worth chasing.

The ordering is the load-bearing part. In particular **rung 1 comes before
rung 3**, and that single choice prevents most of the wasted effort: if the
references disagree with each other about a property, then chasing *our*
difference from one of them is a goose chase by construction.

## The reference set, and what each is for

| reference | role | why it is in the set |
|---|---|---|
| **Surge XT** | **readable** | its Vintage Ladder *is* Huovilainen's DAFx-04 — an independent implementation of **our own model**, so a disagreement is a bug in one of us, not a difference of taste. This is what found the omitted `fcr` polynomial. |
| **Moog Model D** | **authority** | the manufacturer's own, by people with the schematics. A disagreement with it means something the others' cannot. |
| **Arturia Mini V3** | **purpose-built** | a third party's dedicated Model D emulation. |
| **Model 72 (FX)** | **isolable** | filter-only processing of *our own* oscillator recordings. Nothing else gives us this. Trial running; buy only if rung 5 succeeds. |
| ~~u-he Diva~~ | **dropped** | not a Minimoog emulation. A general analog modeller with a ladder among several filter models, carrying no authority about a Model D. It was in the set because I mislabelled it. |

---

## Rung 0 — Is the rig trustworthy?

Nothing below means anything until this passes.

- **Reference variance.** Render every configuration several times; report the
  spread. There are currently **zero** repeated renders, so we have quoted
  *"7.92 pp drift against Surge Type 2's 0.62"* without knowing either one's
  run-to-run spread.
- **Every sound-changing setting pinned and recorded** — Mini V3's vintage
  variation, bass compensation and effects; Model 72's automatic gate. A
  comparison against an unknown setting is not a comparison.
- **Level-matching method stated**, and raw levels reported alongside matched.
- **Renders cached**, keyed by plugin version and parameter vector, so ordinary
  CI never needs a licence or an activation.

> **GATE.** If reference variance is comparable to the differences we are
> chasing, no comparison is interpretable. Fix the rig before measuring
> anything.

## Rung 1 — Do the references agree with each other?

**The most important rung, and nobody has done it.** Measure all references on
the same properties and report the spread *between them*.

> **GATE, and it is a fork rather than a stop.**
> Where references agree tightly → that is a **real target** and a difference
> of ours is a defect worth fixing.
> Where they disagree widely → **there is no single truth**, we stop trying to
> match, and the property is chosen by taste with that fact recorded.

This is what stops goose chases. A property where Surge, Moog and Arturia
differ by 20 % is not a property where our 15 % difference is a bug.

## Rung 2 — Can our measurement tell good from bad?

Extend the **blindness matrix** to every new property: inject a defect the
property exists to catch, and confirm it moves.

> **GATE.** A property that cannot distinguish our filter from a deliberately
> broken one has no power and does not belong in the acceptance suite. Delete
> it or fix it; do not ship it as reassurance.

Already earning its keep: a uniform 30 % cutoff error was invisible to the
drift metric **by construction**, because that metric measures non-uniformity.

## Rung 3 — Where do we actually sit?

Our filter against the reference envelope, per property, classified:

- **inside the reference spread** — nothing to do, say so
- **outside, small** — a candidate, ranked by cost
- **outside, large** — a defect

> **GATE.** Output is a **ranked defect list**, not a report. If it does not
> rank, it is not finished.

## Rung 4 — Fix, in cost order

Three are already identified and all are cheap:

| fix | cost | expected |
|---|---|---|
| **`tanh` guard constant** — `tanh(4)·32767 = 32745`, we return 32767 | one constant, no area | past 64 entries this step **is** the entire table error |
| **`fcr` tuning polynomial** — omitted from Huovilainen | ROM contents only | worst tuning error 6.85 % → 0.89 % |
| **integer-hertz cutoff registers** — 1 Hz LSB is 53.7 cents at 30 Hz | register format; touches the contract | removes a 1.07 dB gain step |

> **GATE.** Measure before, fix, measure after. **A fix that does not move the
> measurement gets reverted**, not explained.

## Rung 5 — The isolated filter comparison

Feed **identical oscillator recordings** into a reference's filter and ours.
This removes oscillator differences entirely and makes a filter difference
diagnosable rather than merely observable.

Two candidates: **Model 72's FX version** (trial running) and **Surge XT's
audio input** (free, and the rig already has the graph shape). Test both.

> **GATE, and it is the purchase decision.** If Surge suffices we keep a
> readable reference and save $159. If Model 72 shows something Surge cannot,
> it is worth buying — and we must know before the trial lapses.

## Rung 6 — Beyond the filter

Oscillators, envelopes, glide; and **targets** for noise and the shark-tooth,
which we do not have and therefore cannot compare — for those the job is
measuring the references to produce a specification.

**This is currently the largest body of unrun work.** The estimators are built
and ground-truthed with 28 closed-form tests and no reference has been pointed
at any of them.

## Rung 7 — Does it sound good?

Render the demo set; score **"matches the reference"** and **"sounds better"**
separately and never as one number. A change may legitimately win one and lose
the other — that is allowed, and it must be visible.

Musicians audition at the end, on a working instrument. **Routine debugging
stays in the automated process**; a listening opinion is not a measurement and
"here is a WAV, is it good?" is not a test.

---

## What this ladder refuses to do

- **Chase a difference from one reference without checking the others agree.**
  That is rung 1's entire purpose.
- **Report a difference without knowing the measurement's own variance.** Rung 0.
- **Ship a property that cannot fail.** Rung 2.
- **Keep a fix that did not move the number.** Rung 4.
- **Treat matching a reference as the goal.** The goal is the sound; the
  reference anchors it. Simplification is allowed where it serves a player, and
  is scored separately.
