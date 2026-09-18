# 0010: One gate per oscillator — `nl(a) + nl(b)`, never `nl(a + b)`

- **Status**: proposed
- **Date**: 2026-09-18
- **Decided by**: block agent, from `docs/tr808-reference.md` §9, with a
  controlled two-tone test and `model/drum_fit.py` against the CC0 reference
  recording

## Context

`docs/tr808-reference.md` §9 describes the cowbell as two square oscillators
each with **its own transistor gate**: "Each oscillator has its own transistor
gate (Q15, Q14, 'exclusive gate (VCA)')." Revision 5's kit routed
`SRC_SQPAIR` — the *sum* of oscillators 5 and 6, formed before any gate —
through **one** `NL_SWING` path.

A nonlinearity does not distribute over a sum. Gating each square and adding
gives `nl(a) + nl(b)`, which contains only harmonics of a and of b; summing
first and gating once gives `nl(a + b)`, which contains their intermodulation
products. Demonstrated in isolation — two squares at this unit's trimmed
frequencies, one swing VCA, nothing else, no filter and no envelope
(`test_gating_the_sum_makes_a_difference_tone_and_gating_each_does_not`):

| | 540 Hz | 800 Hz | 260 Hz (difference) | 1340 Hz (sum) |
|---|---:|---:|---:|---:|
| `nl(a + b)` — one gate on the sum | −1.8 dB | −1.8 dB | **−7.9 dB** | **−7.8 dB** |
| `nl(a) + nl(b)` — one gate each | −8.8 dB | −8.8 dB | **−163.7 dB** | **−168.9 dB** |

At −164 dB the difference and sum tones are the arithmetic floor: they are
not attenuated, they are absent.

In the rendered cowbell the defect measured **−25.6 dB** at 260 Hz relative to
the strongest partial. Establishing that this is a real difference and not the
recording's floor, as the reference recording must be checked before any
rejection figure is quoted (0.5 s Hann, 2^18-point FFT, dB relative to the
824 Hz partial):

| | level |
|---|---:|
| reference unit's difference tone, 264.96 Hz | **−67.8 dB** |
| reference recording's own spectral floor, 230–290 Hz | median **−86.7 dB**, 90th pct −75.6 dB |

The machine's line is **18.9 dB above the median floor**, so it is a real,
measurable line and the comparison is meaningful. Ours was **42.2 dB louder
than the machine's**. A second sample set of undocumented provenance agrees as a *bound*: nothing
within ±10 Hz of its own difference frequency rises above −69.7 dB, so it has
no difference tone worth the name either.

## Decision

1. **Contract 15.4 gains a source: `SQ i`, `src = 5 + i` for i = 0..5** —
   square i **alone** at ±16383, the same step as SQPAIR's terms, so
   `SQ 4 + SQ 5` is SQPAIR term for term and splitting a voice into two paths
   costs no level. `SRC_SQPAIR` is retained and unused by the kit.
2. **The cowbell takes two paths**, `SQ 4` and `SQ 5`, each through its own
   `NL_SWING` with the same two envelopes, summed into mode 5. Fourteen of
   the sixteen paths are now used.
3. `drum_dp.v` decodes src 5..10 from six held sign bits — six flops and a
   mux, no new word — and carries `INJECT_BUG_DRUM_SQ_LONE`, which makes a
   lone-square source return the pair: revision 5's defect, as the control
   that shows a bench can see it.

Two numbers the same measurement settles, taken with it:

- **The band-pass centre**, contract open item 17.16, is **closed**: fitting a
  2-pole band-pass to 16 identified partials of the reference unit with the
  duty cycle and the two gates' relative level free gives **1100 Hz, Q 2.8**
  (rms residual 2.8 dB over 16 partials). Revision 5's 900 Hz / Q 4 was a
  choice; Sound On Sound's 2.64 kHz is refuted.
- **The tail** is the measured **τ = 98 ms** (least-squares fit of the log
  envelope over −3…−30 dB), not 30 ms. Reported as **τ**; its T20 is
  2.303 τ ≈ 226 ms.

## Alternatives considered

- **Leave SQPAIR and put a notch at the difference frequency.** Rejected: it
  treats a structural error as a spectral one, it only works for one pair of
  oscillator frequencies, and it costs a mode where the fix costs six flops.
- **Give every oscillator its own path via SQSUM scaling.** Rejected: SQSUM
  is the six-oscillator staircase the hats need, at a different per-square
  step; a lone source at SQPAIR's step is what keeps the cowbell's level
  unchanged by the split.
- **Take the reference's 900 Hz / Q 4 for the band-pass.** Rejected: §9 and
  §18 explicitly leave the centre open and say "treat the centre frequency as
  a parameter to fit against a recording", which is what this does.

## Consequences

- **A pinned table changes** — Appendix G (KIT808), together with DR 0009;
  see that record and contract revision 6.
- The cowbell has one more path than it had. Two paths remain free.
- `nl(a) + nl(b)` and `nl(a + b)` differ by one LSB on a *linear* path too,
  because `>> 15` floors and floor(a) + floor(b) ≠ floor(a + b) when the
  terms have opposite signs. That is why the cowbell's test measures the
  difference tone rather than sample values, and why
  `test_sources_are_what_the_contract_says` allows one LSB there.
- The same structural question applies to the **hats**, which still gate
  SQSUM — the six squares summed before the swing VCA. The reference says the
  hats' six oscillators are summed *and then* band-passed and gated
  (§10/§11), so this is the circuit for that voice and not a defect; it is
  recorded here so the difference between the two voices is deliberate and
  not an oversight.
- The reference recording's floor was established before the rejection figure
  was quoted, and that floor (−86.7 dB median in 230–290 Hz) is the limit of
  what this corpus can support. A claim below about −87 dB cannot be made
  from it at all.
