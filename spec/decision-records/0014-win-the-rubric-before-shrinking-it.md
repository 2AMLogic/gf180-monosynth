# DR 0014 — Win the rubric before shrinking it

**Status: PROPOSED. Not ratified.**

## Decision

**Stop optimising for area until the instrument matches its references.** Where
matching needs more modes, more banks, more envelopes or more paths, add them.
Shrink afterwards, against a scorecard that can tell us whether the shrinking
broke anything.

## Why, in one measurement

On the real gf180mcu half-slot template, read from `librelane/slots/slot_1x0p5.yaml`:

| | µm² | of core |
|---|---:|---:|
| half-slot core | 5,020,056 | — |
| **joined chip, routed** | **2,033,110** | **40 %** |
| same with `*_1` cells allowed | 1,510,153 | 30 % |
| **headroom** | **2,986,946** | **147 % of the whole chip** |

**We could double the modal bank and land at 51 % of core.** Completing the
entire sixteen-sound 808 cost **+27,315 µm² — 1.3 % of the chip.**

There is no area problem. There was an area *premise*, inherited from a quarter
slot that turned out to be the wrong target, and it survived long after the
measurement that refuted it.

## What that premise cost

Hours went into whether the modal bank should hold 8 modes or 12. The answer
turned out to be that yosys pads the state to a power of two so 9 through 16
cost identically — and that the variable that mattered was `NUMS`, which nobody
had looked at. Both true, and both beside the point: **at 40 % of core the
question should never have been asked.**

Meanwhile the acceptance board reads **0 of 100 cases**, the largest known
defect is that we alias 19–32 dB more than the references, and the rig that
measures it has a waveform-mapping bug.

## The argument that matters more than the headroom

**A rubric is a prerequisite for optimisation, not a competitor to it.**

Without the scorecard there is no way to tell whether a size reduction changed
the sound. Every optimisation would be a change with no test behind it — which
is how this project has produced its confident wrong answers all along.

So "rubric first" is not a preference about ordering. **Shrinking safely is
impossible until the rubric exists**, and shrinking unsafely is worse than not
shrinking.

## What this permits

- Adding modes, banks, envelopes, paths or oscillators **if matching a reference
  requires them**, without an area justification.
- Choosing the **more accurate** implementation over the cheaper one by default
  while matching, and revisiting after.
- Allowing `*_1` drive-strength cells, which cost 4.2 % of critical path and buy
  22.5 % of area — against 21.2 ns of setup slack at the slow corner and 2.69×
  margin on the FPGA.

## What it does not permit

**Ignoring the sample deadline.** Area is elastic here; time is not. Both
datapaths must finish inside the 256-clock frame, and a change that misses it is
broken regardless of how well it matches.

And it does not license unmeasured growth. Every addition still reports what it
cost, because **the point is that we can afford it, not that we stopped
counting.**

## When this reverses

When the board shows the instrument matching its references across the
development cases, and the held-out cases confirm it generalises. At that point
shrinking becomes a well-defined problem with a regression test — which is the
only condition under which it is worth doing.
