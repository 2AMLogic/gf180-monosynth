# 0013: The tanh table's guard word is tanh(4), not full scale

- **Status**: proposed
- **Date**: 2026-09-18
- **Decided by**: voice agent, from a measurement request routed through the coordinator, and the measurements below

## Context

The ladder's tanh is a 16-entry table over [0, 4) with linear interpolation.
Two places needed a value for the top of that domain: the word the last bin
interpolates *toward*, and the value the clamp returns for |v| ≥ 4. Both were
**32767**. `tanh(4) · 32767` is **32745**.

Contract revision 9's own Appendix C said so out loud — "the guard word... is
32767 and is NOT tanh(4.0) (which would round to 32745)" — and
`rtl-sketch/ladder_dp_n.v`'s header comment repeated it. A wrong constant that
everyone had written down and nobody had changed is precisely the failure mode
this repository keeps paying for.

## What the wrong constant cost, measured

| | guard 32767 | guard 32745 |
|---|---|---|
| worst \|error\| over the state's whole range [0, 8] | 5.968e−03 at x = 0.625 | **5.968e−03 at x = 0.625** |
| worst \|error\| in the top bin [3.75, 4) | 6.494e−04 | **5.406e−05** |
| worst \|error\| above 4.0 | 6.707e−04 | 6.712e−04 |
| h2 / h3 / h5 / h7 at self-oscillation, 1 kHz, res 1.05 | −107.7 / −56.1 / −82.5 / −99.0 dB | **−107.7 / −56.1 / −82.5 / −99.0 dB** |

**Two conclusions, and the second is the one worth carrying.**

The constant is wrong and correcting it makes the top bin **twelve times** more
accurate for zero area, so it is corrected.

But **it is not the limiting error on the shipped table, and it does not move
the fifth harmonic at all.** The request that prompted this said the clamp step
"is the entire error" past 64 entries and that fixing it "may resolve most of
the excess 5th harmonic" issue #54 was opened for, and asked for h5 to be
re-measured rather than assumed. Re-measured: **h5 does not move by as much as
0.05 dB**, because at self-oscillation the ladder state never reaches the top
bin — the measured final state magnitudes on a loud patch are 0.002 to 0.567 in
state units, against a bin that starts at 3.75. And the 16-entry table's own
interpolation error, 5.97e−03 at x = 0.625, is **nine times larger** than the
guard error it replaces.

So the "past 64 entries the clamp step is the entire error" finding is correct
*and* conditional on the 64 entries. On the table we ship, widening remains the
lever and this constant is not. Issue #54 stays open on its own terms, and the
right order is: correct the constant (here, free), then decide the table size
as an area question with a listening test behind it.

## The decision

- `fixed.TANH_GUARD = round(tanh(TANH_DOMAIN) · 32767)` = 32745, used both as
  the top bin's interpolation target and as the clamp's return value.
- **The RTL's clamp now returns `rom[2^n]`** instead of a second literal
  `16'd32767`. The table and the clamp were two independent copies of the same
  constant, which is how they were able to be wrong together; now there is one.
- `spec/reference/gen_tables.py` **writes** `rtl-sketch/tanh16.hex` instead of
  only checking it. Nothing wrote that file, which is the other half of how the
  guard word was able to drift.

`TANH16` — the 16 table entries — does not move. Only `TANH16_ROM`, the 17-word
image the RTL reads, and `spec/reference/test_tables.py` asserts exactly that,
so "the tanh table changed" cannot be confused with "the tanh table's guard word
changed".

## Consequences

Contract revision 10. Every bit-exact expectation that drives the ladder past
\|v\| = 3.75 moves, which in practice is the `extremes` scenarios;
`verify_voice.py --set full`, `verify_synth_top.py` and `verify_ladder.py` are
re-run. No acceptance property's measured value moves, which the h5 row above
predicts and the suite confirms.
