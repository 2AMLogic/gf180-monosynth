#!/usr/bin/env python3
"""Validation cases for `tools/measure_repeatability.py`.

The tool's whole output is a REFUSAL plus a set of spreads, so the two ways it
can lie are: calling a knob sweep "repeats" (a false green on the refusal), and
reporting a spread that came from the estimator rather than the machine. Both
are tested against signals whose answer is constructed, not observed.

    .venv/bin/python -m pytest tools/test_measure_repeatability.py -q
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import measure_repeatability as mr                                 # noqa: E402

SR = 44100


# ---------------------------------------------------------------------------
# longest_true_run -- the precondition that decides clipping
# ---------------------------------------------------------------------------
def test_longest_true_run_counts_only_true():
    assert mr.longest_true_run(np.array([0, 1, 1, 0, 1], dtype=bool)) == 2
    assert mr.longest_true_run(np.zeros(9, dtype=bool)) == 0
    assert mr.longest_true_run(np.ones(4, dtype=bool)) == 4


def test_a_single_full_scale_sample_is_normalisation_not_clipping():
    """57 of the legacy pack's 144 bass drums have exactly one sample at
    exactly 1.0 and are not clipped. A run of one must not refuse."""
    x = 0.5 * np.sin(2 * np.pi * 50 * np.arange(SR) / SR)
    x[100] = 1.0
    assert mr.longest_true_run(np.abs(x) >= 1.0 - 1e-9) == 1


# ---------------------------------------------------------------------------
# spearman -- the statistic the refusal rests on
# ---------------------------------------------------------------------------
def test_spearman_is_one_on_a_monotone_sequence():
    assert mr.spearman([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) == pytest.approx(1.0)
    assert mr.spearman([6.0, 5.0, 4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_spearman_is_not_one_on_a_shuffled_sequence():
    assert abs(mr.spearman([3.0, 1.0, 6.0, 2.0, 5.0, 4.0])) < 1.0


# ---------------------------------------------------------------------------
# rank1_fraction -- the physical half of the refusal.
#
# START RED, in the sense verification-rules.md means: the discriminator is
# shown BOTH cases and must separate them. A test that only ever sees the knob
# would pass on a function that returns 1.0 unconditionally.
# ---------------------------------------------------------------------------
def _voice(seed: int) -> np.ndarray:
    t = np.arange(int(0.3 * SR)) / SR
    return np.exp(-t / 0.05) * np.sin(2 * np.pi * 50 * t + 0.0 * seed)


def _click(scale: float) -> np.ndarray:
    n = int(0.3 * SR)
    k = int(0.002 * SR)
    y = np.zeros(n)
    y[:k] = scale * np.exp(-np.arange(k) / (0.0004 * SR))
    return y


def test_rank1_finds_a_knob_sweep():
    """Six recordings that are one voice plus c_k times one fixed additive
    term ARE rank 1, with a monotone loading. That is a knob."""
    sigs = [_voice(0) + _click(0.05 * (k + 1)) for k in range(6)]
    frac, loading = mr.rank1_fraction(sigs)
    assert frac > 0.95
    assert abs(mr.spearman(loading)) == pytest.approx(1.0)


def test_rank1_does_not_find_a_knob_in_independent_repeats():
    """Six repeats differing by independent noise and independent jitter are
    not rank 1 and their loading is not monotone. If this passes with the
    previous test, the discriminator separates the two cases rather than
    answering the same way to everything."""
    rng = np.random.default_rng(7)
    sigs = []
    for _ in range(6):
        y = _voice(0) + _click(0.15)
        y = y + rng.normal(0.0, 0.01, len(y))
        sigs.append(np.roll(y, int(rng.integers(-3, 4))))
    frac, loading = mr.rank1_fraction(sigs)
    assert frac < 0.60, f"independent repeats read as rank {frac:.2f}"


# ---------------------------------------------------------------------------
# truncation_sensitivity -- the #118 length criterion
# ---------------------------------------------------------------------------
def test_truncation_probe_is_quiet_on_a_record_with_enough_tail():
    x = mr.synthetic_bd(SR, tau=0.05, seconds=3.0)
    assert abs(mr.truncation_sensitivity(x, SR)) < 1.0


def test_truncation_probe_fires_on_a_record_cut_while_it_is_still_sounding():
    """The case #118 is about: schroeder_t20's tail_db guard passes, and the
    answer is badly wrong. A probe that never fires is not a probe."""
    import audio_measure as am
    import run_case as rc
    x = mr.synthetic_bd(SR, tau=0.40, seconds=4.0)
    cut = x[: int(0.5 * SR)]
    guard = am.schroeder_t20(rc.window(cut, SR, 0.005, None), SR)
    assert guard.ok, "the level guard must PASS here; that is the defect"
    assert abs(guard.value * 1e3 - am.t20_from_tau(0.40) * 1e3) > 100.0
    assert abs(mr.truncation_sensitivity(cut, SR)) > 5.0


# ---------------------------------------------------------------------------
# the estimators, on a signal whose answer is closed form
# ---------------------------------------------------------------------------
def test_synthetic_bd_reads_back_its_own_f0_and_t20():
    import audio_measure as am
    import run_case as rc
    plan = mr.metrics()
    y = rc.prepare(mr.synthetic_bd(SR, f0=50.0, tau=0.120), SR)
    assert plan["Pitch trajectory"][1](y, SR).require() == pytest.approx(50.0, abs=0.1)
    assert (plan["decay"][1](y, SR).require()
            == pytest.approx(am.t20_from_tau(0.120) * 1e3, rel=0.01))


def test_measure_all_keeps_a_refusal_as_a_refusal():
    """An estimator that cannot answer must come back None, never 0.0 -- zero
    reads as a perfect match and is how a scorecard starts lying."""
    plan = mr.metrics()
    out = mr.measure_all(np.zeros(SR), SR, plan)
    assert all(v is None for v in out.values()), out


# ---------------------------------------------------------------------------
# the windowing defect, #101, on a synthetic signal
# ---------------------------------------------------------------------------
def test_the_shipped_band_split_moves_when_the_head_trim_moves():
    """Four samples of head trim cannot change what the machine did. The
    shipped split moves anyway; the padded one does not. This is the control
    that says the 0.57 dB measured on the corpus is the apparatus."""
    import run_case as rc
    plan = mr.metrics()
    # Eight samples of leading silence, as the corpus has: its onsets land on
    # sample 5 to 9. Every trim below is taken out of that silence, so the
    # EVENT is bit-identical in all four and any movement is the apparatus.
    x = np.concatenate([np.zeros(8),
                        mr.synthetic_bd(SR, tau=0.12, seconds=1.0, click=0.4)])
    shipped = [plan["body spectrum"][1](rc.prepare(x[h:], SR), SR).require()
               for h in (0, 2, 4, 6)]
    padded = [plan["body spectrum (padded)"][1](rc.prepare(x[h:], SR), SR).require()
              for h in (0, 2, 4, 6)]
    assert max(padded) - min(padded) < 0.01
    assert max(shipped) - min(shipped) > 10 * (max(padded) - min(padded))
