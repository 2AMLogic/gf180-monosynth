# 0009: The bass drum's frequency is the circuit's 49.4 Hz, not the chart's 56 Hz

- **Status**: proposed
- **Date**: 2026-09-18
- **Decided by**: block agent, from `docs/tr808-reference.md` §2 and §12, with
  `model/drum_fit.py` against the CC0 reference recordings

## Context

`docs/tr808-reference.md` gives the TR-808 bass drum two different
frequencies, and revision 5's kit took one number from each.

- **§2, "Resonator" [verified: W14a §5; computed with §1.2]** derives the
  bridged-T's centre from the schematic's own component values — R1 =
  R161 ‖ (R165+R166) ‖ R170 = 46.1 kΩ, R2 = 1 MΩ, C = 0.015 µF — and gets
  **f0 = 49.4 Hz, open-loop Q = 2.33**. Werner's independent model measures
  ≈49.5 Hz.
- **§12's summary table and Roland's June-1981 tuning chart** say **56 Hz**
  ("18 ms"), which §1.6 labels "typical and variable". §2 concludes: "Treat
  **50–56 Hz** as the target and make it tunable."

`kit_808()` shipped **56 Hz** (the chart) together with **Q = 22.3**, which is
§2's decay table at the 12-o'clock knob. Those two rows are not compatible.
A two-pole resonator's decay is exactly τ = Q/(π f0), and §2's decay table
satisfies that identity **to 1.5 % at f0 = 49.4 Hz and only to 12.8 % at
56 Hz**:

| VR6 k | Q | §2's τ | Q/(π·49.4) | Q/(π·56) |
|---|---:|---:|---:|---:|
| 0 | 2.3 | 15 ms | 14.8 | 13.1 |
| 0.1 | 5.2 | 33 ms | 33.5 | 29.6 |
| 0.5 | 22.3 | **144 ms** | **143.7** | **126.8** |
| 0.9 | 63 | 408 ms | 405.9 | 358.1 |
| 1.0 | 84 | 544 ms | 541.3 | 477.5 |

So §2's whole decay table is computed at ≈49.4 Hz, and shipping its Q at
56 Hz produced τ = 127 ms where the same table says 144. **The bass drum's
reported "45 % short decay" was this pitch error propagating through
τ = Q/(π f0) — not a fault in the DECAY control**, which is the reference's
own table and is correct.

Measurement, corroborating rather than deciding: the primary CC0 reference
unit (s/n 103852) measures **50.70 ± 0.02 Hz** at the chart's own 12-o'clock
condition and 51.11 ± 0.34 Hz over the twenty files with DECAY ≥ 2.5
(damped-sinusoid fit, 20 ms after onset, 300 ms window). A second sample set
of undocumented provenance measures 48.8–51.0 Hz. Four independent lines —
the component values, Werner's model and two machines — agree on 49–51 Hz;
only the chart says 56.

## Decision

`kit_808()` writes **f0 = 49.4 Hz** for the bass drum's body mode
(`drums_fx.BD_HZ`), the value §2 computes from the schematic.

**The DECAY control is not changed.** `drums_fx.bd_decay_q` is §2's own table
(Q = 2.3 / 5.2 / 22.3 / 63 / 84 against VR6 0 / 0.1 / 0.5 / 0.9 / 1.0,
interpolated geometrically), and `kit_808()` still writes Q = 22.3 at the
12-o'clock position — bit for bit what revision 5 wrote. The body's τ becomes
143.7 ms because f0 moved, and that is §2's tabulated 144 ms.

The chart's value stays available as `drums_fx.BD_HZ_CHART = 56.0`; a host
that wants it writes one `mode_writes(M_BD, BD_HZ_CHART, …)`, as 17.18 already
says for per-unit tuning.

Every decay in this record is a **τ** — the single exponential's time
constant. §2's "2.3 τ" column and Roland's chart's "mid 300 ms" are T20-like
figures, and reading the chart's 300 ms as a τ is one of the ways this voice
has already produced false findings.

## Alternatives considered

- **Keep 56 Hz (the chart) and retune Q to restore τ.** Rejected: it keeps
  the inconsistency and hides it, and it would mean changing the DECAY
  control, which is the part of this voice that is demonstrably right.
- **Take the measured 50.7 Hz.** Rejected as the *primary* basis: it is one
  unit, and the standing rule is that the reference document wins over a
  single machine. It is within 2.6 % of 49.4 and is recorded as
  corroboration. Nothing in the contract would differ audibly between the
  two.
- **Ship both and let the host choose.** Rejected as an evasion: the kit is
  the reference kit and has to state one number. The host *can* choose, and
  `BD_HZ_CHART` is how.

## Consequences

- **A pinned table changes.** Appendix G (KIT808) moves from
  `819ef081…db66b3dc` to `06f47f30…b869914a`. This is the first pinned table
  in this contract's history to change; contract revision 6 says so in its
  revision history, and `spec/reference/test_tables.py` keeps revision 5's
  hash as a literal so the change is a visible fact rather than an edited
  constant.
- Any listener's reference for "the 808 kick" moves down 1.72 semitones.
  That is a large, deliberate, audible change and every render in
  `audio/drums/` differs.
- `docs/tr808-reference.md` §2's "What to implement" line, which says
  f0 = 56 Hz, contradicts §2's own derivation four paragraphs above it and is
  amended.
- The residual against the reference unit — its τ is 178.0 ± 29.1 ms where
  the circuit table says 144, +23 % — is **not** tuned away. It is inside the
  ±50 % on Q that §12 says is normal between units, and it is tracked as
  contract 17.21.
- `drum_verify.py`'s `SPEC["BD"]` still carries `f0 = 56.0, tau_ms = 127.0`
  as the figures revision 5 was measured against; it is a reporting table, not
  a specification, and it is updated with this record.
