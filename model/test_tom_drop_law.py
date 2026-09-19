#!/usr/bin/env python3
"""The pitch-drop law's own bench: the fit, the comparator, and the constants
drums_fx actually ships, each with the refusals demonstrated red.

`model/tom_drop_fit.py` and `model/tom_drop_compare.py` produced the numbers in
`docs/tom-pitch-drop-correction.md`. A tool that produced a number is a
deliverable, so it carries its validation cases here -- including the three
preconditions that must REFUSE rather than answer.
"""
from __future__ import annotations
import json, math, os, pathlib, sys
import numpy as np
import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "audition"))
import drums_fx as dx
import tom_drop_fit as F
import tom_drop_compare as C

REPO = HERE.parent
LAW = json.loads((REPO / "docs" / "tom-pitch-drop-law.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------- the fit ----

def test_the_fit_reproduces_the_committed_law():
    """Re-running the fit on the merged measurement must give back the constants
    the correction was published with. If `docs/tom-pitch-drop-results.json`
    ever changes, this is what notices."""
    r = F.run()
    assert r["tom"]["K"] == pytest.approx(LAW["tom"]["K"], rel=1e-9)
    assert r["tom"]["A0"] == pytest.approx(LAW["tom"]["A0"], rel=1e-9)
    assert r["G"]["tom"] == pytest.approx(LAW["G"]["tom"], rel=1e-9)
    assert r["conga"]["A0"] == pytest.approx(LAW["conga"]["A0"], rel=1e-9)


def test_what_drums_fx_SHIPS_is_what_the_fit_measured():
    """The constants in the block and the constants in the fit are the same
    numbers. Rounding to three or four places is allowed; drifting is not.

    This is the join that matters: a law derived in one file and a coefficient
    typed into another is exactly the shape of defect this repository keeps
    finding."""
    K = LAW["tom"]["K"]
    A0 = LAW["tom"]["A0"]
    assert dx.TOM_DROP_ACCENT_0 == pytest.approx(A0, abs=5e-4)
    assert dx.TOM_DROP_ACCENT_0_CONGA == pytest.approx(LAW["conga"]["A0"], abs=5e-4)
    assert dx.TOM_DROP_TUNING_G == pytest.approx(LAW["G"]["tom"], abs=5e-3)
    assert dx.TOM_DROP_TUNING_G_CONGA == pytest.approx(LAW["G"]["conga"], abs=5e-3)
    # TOM_DROP_RATIO is the law evaluated at the reference setting.
    assert dx.TOM_DROP_RATIO - 1.0 == pytest.approx(K * (1.0 - A0), abs=5e-4)
    # and the block's own function agrees with the fit's, away from the anchor
    for accent in (0.0, 0.5, 1.0, 1.4, 2.0):
        for f0 in (0.93 * 90.0, 90.0, 1.07 * 90.0):
            want = F.predict(accent, f0 / 90.0 - 1.0, K, A0, LAW["G"]["tom"])
            got = dx.tom_drop_excess(dx.M_LT, f0, accent)
            assert got == pytest.approx(want, abs=2e-3), (accent, f0, got, want)


def test_the_fit_refuses_when_the_measurement_is_missing():
    with pytest.raises(F.Refused):
        F.load_rows(REPO / "docs" / "no-such-measurement.json")


def test_the_fit_refuses_an_accent_law_that_shrinks_with_accent():
    """An unsatisfiable law is worse than none. If the levels ever come back
    ordered the other way, the fit must REFUSE rather than ship a negative
    slope that would make a hard hit sweep less than a soft one."""
    centre = {"A": {"mean": 0.24}, "B": {"mean": 0.14}, "C": {"mean": 0.05}}
    with pytest.raises(F.Refused):
        F.fit_accent(centre, F.ACCENT_MAP)


def test_the_conga_threshold_needs_the_level_it_is_fitted_to():
    with pytest.raises(F.Refused):
        F.fit_conga_threshold({"A": {"mean": 0.004}}, 0.18, F.ACCENT_MAP)


# -------------------------------------------------------- the comparator ----

def test_the_comparator_refuses_audio_the_index_does_not_vouch_for():
    """Three preconditions, each demonstrated red: a member that is not in the
    committed index, a member the index knows but the cache does not have, and
    a file whose size is not the size the index states."""
    sizes = C.indexed_sizes()
    assert len(sizes) > 100, "the committed index should list the whole pack"
    with pytest.raises(C.Refused):
        C.reference_wav("LT", "A", 99, sizes)                 # not indexed
    with pytest.raises(C.Refused):
        C.reference_wav("LT", "A", 6, dict(sizes, **{C.member("LT", "A", 6): 1}))  # wrong size
    real = C.member("LT", "A", 6)
    if not (C.CACHE / real).exists():
        with pytest.raises(C.Refused):
            C.reference_wav("LT", "A", 6, sizes)              # indexed, absent


def test_the_resample_control_refuses_a_conversion_that_filters_the_onset(monkeypatch):
    """`validate_resample` is the comparator's own injected-bug control and it
    runs on every comparison. The defect it exists to catch is a conversion that
    damages the SWEEP, so that is what is injected: a band-pass around the
    fundamental, which #110's own validation measured as costing 40 % of the
    excess to `filtfilt` pre-ringing landing on the first retained period.

    Note what does NOT work as an injection, because it says something about the
    estimator: a symmetric moving average is zero-phase and does not move the
    zero crossings of a sinusoid at all, so it changes the amplitude and not the
    measurement. The probe reads times, not levels."""
    from scipy.signal import resample_poly, butter, sosfiltfilt

    def filtered(x):
        y = resample_poly(np.asarray(x, dtype=np.float64), 147, 160)
        sos = butter(4, [0.75 * 90.0 / 22050.0, 2.05 * 90.0 / 22050.0],
                     btype="band", output="sos")
        return sosfiltfilt(sos, y)

    monkeypatch.setattr(C, "to_44100", filtered)
    with pytest.raises(C.Refused):
        C.validate_resample()


def test_a_uniform_rate_error_is_invisible_to_this_control_and_that_is_correct(monkeypatch):
    """Recorded because it is a real blind spot, not because it is a pass.

    Converting to the WRONG rate scales every frequency in the file by the same
    factor, and the measurement is a RATIO of two frequencies from that file, so
    the error cancels exactly. `validate_resample` therefore cannot see it, and
    no tolerance on the ratio ever could. What rules it out instead is that the
    conversion is a fixed 147/160 written once, and that `tom_pitch_probe`
    REFUSES any file whose sample rate is not 44100 -- a precondition, not a
    tolerance."""
    from scipy.signal import resample_poly
    monkeypatch.setattr(C, "to_44100", lambda x: resample_poly(np.asarray(x, float), 140, 160))
    r = C.validate_resample()                       # does NOT refuse
    assert max(c["rel_error_of_excess"] for c in r["cases"]) < 0.01
    assert C.P.SR_EXPECTED == 44100
    bad = P_measure_at_wrong_rate()
    assert bad["verdict"] == "REFUSED" and "sample rate" in bad["why"]


def P_measure_at_wrong_rate():
    import tom_pitch_probe as P
    y = P.synth_tom(90.0, 25.0, P.tau_from_q(90.0, 25.0), ratio=1.24, sr=44100, trim=False)
    return P.measure(y, 48000, label="wrong rate")


def test_the_resample_control_passes_the_conversion_actually_used():
    r = C.validate_resample()
    assert len(r["cases"]) == 3
    for c in r["cases"]:
        assert c["rel_error_of_excess"] < 0.01, c


def test_the_dead_tail_trim_touches_nothing_inside_the_ring():
    x = np.array([0.0, 0.3, -0.2, 0.1, 0.0, 0.0, 0.0])
    y = C.trim_dead_tail(x)
    assert len(y) == 4 and np.array_equal(y, x[:4])
    assert np.array_equal(C.trim_dead_tail(np.zeros(5)), np.zeros(5))


# ------------------------------------------------- the law's own extremes ----

def test_the_tuning_term_is_clamped_to_the_pot_it_was_measured_over():
    """Reference 1.7 puts the TUNING pot at +-10 %, which is also the span the
    99 files cover. A host may write any f0; the law must not extrapolate past
    the audio it came from."""
    inside = dx.tom_drop_excess(dx.M_LT, 90.0 * 1.10, 2.0)
    outside = dx.tom_drop_excess(dx.M_LT, 90.0 * 1.25, 2.0)
    assert outside == pytest.approx(inside, rel=1e-12)
    lo_in = dx.tom_drop_excess(dx.M_LT, 90.0 * 0.90, 2.0)
    assert dx.tom_drop_excess(dx.M_LT, 90.0 * 0.80, 2.0) == pytest.approx(lo_in, rel=1e-12)


def test_the_position_boundary_sits_between_the_two_sounds_not_inside_either():
    """The circuit's position is read off the tuning, so the boundary matters.
    It is the geometric mean of the pair -- 129 Hz for LT/LC -- and both sounds'
    whole pot ranges clear it: a tom detuned +25 % is 112 Hz and a conga
    detuned -25 % is 139 Hz. A host that writes something between them gets the
    nearer position, which is the only answer available."""
    for name, mode in (("LT", dx.M_LT), ("MT", dx.M_MT), ("HT", dx.M_HT)):
        conga = {"LT": "LC", "MT": "MC", "HT": "HC"}[name]
        f_tom, f_conga = dx.TOM_PRESET[name][0], dx.TOM_PRESET[conga][0]
        assert f_conga > 1.7 * f_tom, (name, f_tom, f_conga)
        for k in (0.75, 0.9, 1.0, 1.1, 1.25):
            assert dx.tom_position(mode, f_tom * k) == name, (name, k)
            assert dx.tom_position(mode, f_conga * k) == conga, (conga, k)


def test_a_mode_that_is_not_a_tom_circuit_gets_no_sweep():
    assert dx.tom_position(dx.M_BD, 49.4) is None
    assert dx.tom_drop_excess(dx.M_BD, 49.4, 2.0) == 0.0


def test_each_step_holds_the_intervals_mean_of_the_law():
    """The written coefficient sequence must be the interval-mean staircase,
    not the left-edge one. Checked against the closed form directly, because
    this is the defect that made the delivered sweep 22-38 % larger than the
    law it was delivering."""
    f0, q, amp = 90.0, 25.0, 0.2
    w = dx.tom_pitch_drop_writes(0, dx.M_LT, f0, q, amp, 2.0)
    s = dx.TOM_DROP_STEPS
    e = dx.tom_drop_excess(dx.M_LT, f0, 2.0)
    assert len(w) == 2 * (s + 1)
    for i in range(s + 1):
        a1, a2 = w[2 * i][2], w[2 * i + 1][2]
        got, _ = dx.poles_from_regs(a1, a2)
        shape = ((s / 3.0) * (math.exp(-3.0 * i / s) - math.exp(-3.0 * (i + 1) / s))
                 if i < s else math.exp(-3.0))
        assert got == pytest.approx(f0 * (1.0 + e * shape), rel=2e-3), i
    assert w[0][0] == 0
    assert w[-1][0] == int(round(dx.TOM_DROP_MS * 1e-3 * dx.SR))
