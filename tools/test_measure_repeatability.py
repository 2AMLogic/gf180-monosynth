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
    """The case #118 is about. **This test asserted the defect until #118 was
    fixed**: `schroeder_t20` guarded truncation on `tail_db`, the last value of
    the backward-integrated curve, and that curve falls towards -inf at the last
    sample of ANY finite record -- so it passed this cut and returned a badly
    wrong answer. The guard is now a LENGTH criterion and refuses.

    Both halves are asserted. The level criterion is recomputed from the
    estimator's own `tail_db`, so if anyone reinstates it as the truncation test
    this record goes green again and this test goes red -- and the local probe
    must still fire either way, because a probe that never fires is not a
    probe."""
    import audio_measure as am
    import run_case as rc
    x = mr.synthetic_bd(SR, tau=0.40, seconds=4.0)
    cut = x[: int(0.5 * SR)]
    seg = rc.window(cut, SR, 0.005, None)
    guard = am.schroeder_t20(seg, SR)
    assert not guard.ok, \
        f"the length guard must refuse a cut record; it returned {guard.value*1e3:.0f} ms"
    assert "ends before" in guard.reason
    assert guard.detail["tail_db"] < -35.0, \
        ("the LEVEL criterion passes this record comfortably (tail_db "
         f"{guard.detail['tail_db']:.1f} dB) -- which is why the guard is a length")
    # what it would have reported, had it reported
    unguarded = am.schroeder_t20(seg, SR, min_tail_t20=0.0)
    assert abs(unguarded.value * 1e3 - am.t20_from_tau(0.40) * 1e3) > 100.0
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
def _prepare_with_the_clamp(x, sr):
    """`run_case.prepare` EXACTLY as it stood before #101 was fixed, so the
    defect this test was written for stays reproducible after the repair. The
    `max(0, ...)` is the whole of it: an onset closer to the start than 1 ms
    could not be given a 1 ms lead, so it silently got whatever was there --
    0.16 ms on every file in this corpus, inside `sosfiltfilt`'s 27-sample
    pad."""
    import audio_measure as am
    x = np.asarray(x, dtype=np.float64)
    pk = float(np.abs(x).max())
    i = int(np.argmax(np.abs(x) > 0.02 * pk))
    lead = max(0, i - int(1e-3 * sr))
    if lead >= int(5e-3 * sr):
        x = x - float(x[:lead].mean())
    y = x[lead:]
    p = float(np.abs(y).max())
    return y / p if p > 0 else y


def test_the_shipped_band_split_does_not_move_when_the_head_trim_moves():
    """Four samples of head trim cannot change what the machine did.

    **This test asserted the opposite until #101 was fixed** -- that the shipped
    split moved and only the padded control held still, which is what made the
    0.57 dB measured on the corpus the apparatus rather than the machine.
    `prepare` now gives both sides 20 padlens of true silence, so the shipped
    path holds still too, and the two must agree.

    The pre-repair path is reimplemented above and asserted to STILL move, so
    this is a control and not merely an absence."""
    import run_case as rc
    plan = mr.metrics()
    # Eight more samples of leading silence on top of the fixture's own, so
    # every trim below comes out of silence and the EVENT is bit-identical in
    # all four: any movement at all is the apparatus.
    x = np.concatenate([np.zeros(8),
                        mr.synthetic_bd(SR, tau=0.12, seconds=1.0, click=0.4)])
    shipped = [plan["body spectrum"][1](rc.prepare(x[h:], SR), SR).require()
               for h in (0, 2, 4, 6)]
    padded = [plan["body spectrum (padded)"][1](rc.prepare(x[h:], SR), SR).require()
              for h in (0, 2, 4, 6)]
    before = [rc.band_ratio_db(_prepare_with_the_clamp(x[h:], SR)[:int(0.150 * SR)],
                               SR, rc.SPLIT_HZ["BD"], *rc.BAND["BD"]).require()
              for h in (0, 2, 4, 6)]
    assert max(padded) - min(padded) < 0.01, padded
    assert max(shipped) - min(shipped) < 0.01, shipped
    assert abs(shipped[0] - padded[0]) < 0.01, (shipped[0], padded[0])
    assert max(before) - min(before) > 0.1, \
        f"the pre-repair path must still move, or this is not a control: {before}"
