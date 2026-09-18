# The capability ladder

One capability at a time. Stamp a version of known-good functionality before
adding the next one. This is how torchsynth was built and it is how this chip
gets built.

## Why, specifically here

Every voice and every routing path multiplies the state space, so the cost of
establishing that a thing works grows faster than the thing itself. Two
concrete data points from this repository:

- Every block is bit-exact against its model. **Two integration bugs still
  shipped** — a drum mix fault and a cowbell gating fault — and both were found
  by listening, not by any test.
- Six measurement claims in this project have been confidently wrong. One
  ("1,917 cells") was quoted three times before anyone noticed every output was
  X.

A stamped rung is a place you can always return to, and a regression suite that
keeps running forever. Lower rungs are never deleted once passed.

## What "stamped" means

A rung is stamped when **all five** hold. Four out of five is not a rung.

1. **Tagged** — an annotated git tag, `rung/<n>-<name>`.
2. **A named test set that is green**, listed here, run in CI on every push.
3. **Negative controls carried** — each property has an injected defect that
   turns it red. A test that has never failed is not evidence.
4. **Area measured**, not extrapolated; labelled *cell*, *synthesized*, or
   *routed*, because those are three different numbers.
5. **An explicit statement of what the rung does NOT do.**

## The rule

> **Do not start rung N+1 until rung N is stamped.**

## The ladder

| rung | capability | status |
|---|---|---|
| R0 | Ladder filter, bit-exact | verifier exists, **unstamped** |
| R1 | One Moog voice — 3 osc, PolyBLEP, 2 env, glide, ladder, VCA | verifier exists, **unstamped** |
| R2 | That voice is musically a Minimoog — 42 acceptance tests | green, **unstamped** |
| R3 | Paraphonic 4 notes, one filter | **BLOCKED — see below** |
| R4 | Drums, 8 voices on the modal bank | PR #14 in flight |
| R5 | That kit is musically an 808 — 50 acceptance tests | PR #18 in flight |
| R6 | Full chip: SPI, I2S, mix bus, master clamp | in flight |
| R7 | Silicon: placed, routed, DRC clean, STA closed | in flight |
| R8 | Shaped excitation — the ~90 % discrimination term | backlog |
| R9 | Complete 808 — all 16 voices | backlog |
| R10 | Paraphonic **and** complete 808 | the target |

## Where we actually are

**We are working on R4 through R7 with R0–R3 unstamped.** That is the rule
violated, and it is worth saying plainly rather than quietly fixing.

R3 is the serious one. `synth_core` with `NV=4` synthesizes and routes (1.079
mm², 0 DRC), so it looks done — but `rtl-sketch/tb_ladder_n.v:59-61` assigns
`x_in` once *outside* the per-channel loop, so **every channel receives
identical stimulus**. A bug where channel 2 leaked into channel 3's state would
still pass, because the channels would agree anyway. Paraphony is the
capability Joseph most wants to keep, and it is the one rung with no evidence
behind it.

R0–R2 are probably fine and merely unstamped; R3 is unstamped *and* untested.

## Backlog beyond the ladder

The target is **paraphonic four-note chords AND a complete 16-voice 808**.
Both, not one. Area is the constraint: first real synthesis of `synth_top` is
925,387 µm² of cells, 55.3 % utilization on the 1.7319 mm² slot die before
placement. R9 and R10 are gated on what R7 measures, not on argument.

The eight 808 voices we have are BD, SD, LT, HT, CH, OH, CP, CB. Missing:
mid tom, three congas, rimshot, claves, maracas, **and the cymbal**. Several
are cheap — maracas need no resonator, the cymbal can share the hats' six
square oscillators — so R9 is plausibly +5 to 7 modes, not double.

## Adding a rung

1. Write the test set first, and watch it fail against a do-nothing stub.
2. Build until green, carrying injected-defect controls.
3. Measure area. Label which kind.
4. Write down what it does not do.
5. Tag, and add the test set to CI permanently.
