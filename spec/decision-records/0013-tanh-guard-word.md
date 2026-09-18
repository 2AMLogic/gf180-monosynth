# 0013: The tanh table's guard word is wrong, and this records why it is not corrected here

- **Status**: proposed — **measured, NOT taken**
- **Date**: 2026-09-18
- **Decided by**: voice agent, from a request routed through the coordinator, and the measurements below

## Context

The ladder's tanh is a 16-entry table over [0, 4) with linear interpolation.
Two places need a value at the top of that domain: the word the last bin
interpolates *toward*, and the value the clamp returns for |v| ≥ 4. Both are
**32767**. `tanh(4) · 32767` is **32745**.

The contract's own Appendix C has always said so — "the guard word… is 32767
and is NOT tanh(4.0) (which would round to 32745)" — and
`rtl-sketch/ladder_dp_n.v`'s header repeated it. A wrong constant that everyone
has written down and nobody has changed is exactly the failure mode this
repository keeps paying for, so it was implemented, measured, and then backed
out. Both halves of that are the record.

## What correcting it buys, measured

| | guard 32767 (shipped) | guard 32745 |
|---|---|---|
| worst \|error\| over the state's whole range [0, 8] | 5.968e−03 at x = 0.625 | **5.968e−03 at x = 0.625** |
| worst \|error\| in the top bin [3.75, 4) | 6.494e−04 | **5.406e−05** |
| worst \|error\| above 4.0 | 6.707e−04 | 6.712e−04 |
| h2 / h3 / h5 / h7 at self-oscillation, 1 kHz, res 1.05 | −107.7 / −56.1 / −82.5 / −99.0 dB | **−107.7 / −56.1 / −82.5 / −99.0 dB** |

**The top bin gets twelve times more accurate. Nothing else moves at all.**

The request that prompted this said the clamp step "is the entire error" past
64 entries, that fixing it "may resolve most of the excess 5th harmonic" issue
#54 was opened for, and — correctly — asked for h5 to be re-measured rather
than assumed. Re-measured: **h5 does not move by as much as 0.05 dB.** At
self-oscillation the ladder state never reaches the top bin; the measured final
state magnitudes on a loud patch are 0.002 to 0.567 in state units, against a
bin that starts at 3.75. And the 16-entry table's own interpolation error,
5.97e−03 at x = 0.625, is **nine times larger** than the guard error it would
replace.

So the finding is correct *and* conditional on the 64 entries it was measured
at. On the table we ship, the table's width remains the lever and this constant
is not one. Issue #54 stays open on its own terms.

## Why it is not taken here

**`rtl-sketch/drum_dp.v` reads the same ROM image** (`tanh16.hex`, line 43)
**and clamps with its own hardcoded literal** (line 208,
`tr_mag = tsat_q ? 16'd32767 : …`). The word cannot move in the image without
that literal moving with it, or the drum section's RTL stops being bit-exact
against `model/drums_fx.py` — silently, on the paths that use `NL_TANH` and
`NL_SWING`, which is most of the kit. `model/test_drums_fx.py` also pins the
resulting value (`d._nonlinear(32767, NL_SWING) == 32766`).

That is a one-line change in a file the voice does not own, plus a literal in
its test. **Correcting the guard word is therefore a cross-section change, not
a voice change**, and it is worth about nothing on the shipped table. Landing
it unilaterally would have traded a measured benefit of zero for a real risk of
breaking another section quietly.

## What IS taken from this investigation

Two structural fixes that are behaviour-identical today and remove the way the
constant was able to be wrong in two places at once:

1. **`fixed.TANH_GUARD`** is now a named constant with the reason attached,
   used both as the interpolation target and as the clamp, instead of two bare
   `32767` literals in the model.
2. **`ladder_dp.v` and `ladder_dp_n.v` clamp to `rom[2^n]`** instead of a
   second hardcoded literal, so in the ladder the table and the clamp are one
   value and cannot drift apart again.
3. **`spec/reference/gen_tables.py` now WRITES `rtl-sketch/tanh16.hex`**
   instead of only checking it. Nothing wrote that file, which is the other
   half of how a guard word could drift from the model in the first place.

None of the three changes a single output sample, so no pinned table moves and
the contract stays at revision 9.

## To land it

One change in `rtl-sketch/drum_dp.v` (line 208, `16'd32767` → `rom[16]`), one
literal in `model/test_drums_fx.py`, `fixed.TANH_GUARD` set to
`round(tanh(TANH_DOMAIN) · 32767)`, a contract revision for `TANH16_ROM`
(`TANH16` itself does not move — only the image's 17th word), and a re-run of
`verify_voice --set full`, `verify_drums`, `verify_synth_top` and
`verify_ladder`. Best done with the table-size decision of issue #54, where the
guard actually becomes the limiting error, rather than on its own.
