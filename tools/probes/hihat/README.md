# Hi-hat and cymbal high-band probes

**These were rescued from a scratchpad.** The agent that wrote them reported an
excellent result and committed nothing; its branch has zero commits. The
findings survived only because they were transcribed by hand into a docstring
(PR #97). The scripts themselves were one `rm -rf /tmp` from gone.

They are committed here **verbatim**, with exactly one change: they were written
against a worktree at `/tmp/wt-hihat` that no longer exists, so that path now
resolves from `__file__`. Nothing else was touched — not the logic, not the
numbers, not the comments.

## What they established

The 808 cymbal's missing 9–13 kHz shoulder is **a mistuned filter, not a missing
one**. `M_CYHI` already sits at 10.5 kHz; raising its Q from 2.5 to 4.0 takes the
five-band cost from **18.1 to 6.0**. Restoring the filter that was *hypothesised*
to be missing (Hh1) closed **0.4 of the shoulder's 8.0 points** and moved 5–9 kHz
the wrong way — the hypothesis was refuted at the first step. Adding a second
2-pole reaches only 10.3, so **more filtering is not the lever**.

Whether that retune should ship is **not settled** — see #99, where it improves
one measure threefold while the scorecard score gets worse, and #101, where the
measurement path itself is shown to carry a 6 dB windowing artefact.

## The files

| file | what it does |
|---|---|
| `hh_probe.py` | the main sweep — every number labelled DERIVED (a formula on schematic component values) or MEASURED (a render). Prints a provenance block: commit, dirty flag, per-file SHA-256, numpy version |
| `hh_probe2.py` | Hh1 with its numerator actually enabled; the CY low-band residual; the same question for CH and OH |
| `hh_probe3.py` | confirms the offline sweep on the **real fixed-point block**, as ordinary register writes |
| `hh_probe4.py` | **the correction.** Part 2's "cost 7.2, every band green" used the offline emulator for a knob it was never validated for — the low band's envelope peak. The fixed-point run gave **30.6, not 7.2** |
| `combo.py`, `patch_q.py` | small harnesses for running the acceptance suite against a patched `CY_HI_Q` |

`hh_probe4.py` is the most valuable file here and the one most likely to have
been thrown away: it is the record of a result that looked good and was wrong.

## Status

These are **probes, not a harness**. They have overlapping helpers, they are
numbered rather than named, and the general parts belong in a shared module
alongside the conga tool's `validate_known_answer`, `floor_for_these_signals`
and `windowed_alike`. That consolidation is **#104**. Committing them unpolished
beats losing them polished.
