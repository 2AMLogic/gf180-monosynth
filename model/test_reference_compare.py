#!/usr/bin/env python3
"""Ground truth for the reference-comparison harness, and its controls.

    .venv/bin/python -m pytest model/test_reference_compare.py -q     # ~2 min

Two jobs, in the order `docs/verification-rules.md` requires them:

  1. **Every estimator is checked against a closed-form signal** whose answer
     is known exactly, BEFORE any number it produces is quoted anywhere. Seven
     measurement claims in this repository were wrong from unvalidated
     methods; the withdrawn 700 Hz Hann-windowed split returned 1.25 % on a
     render whose true answer was exactly 18.55 %.

  2. **The comparison is shown to have power.** Three deliberately-wrong
     ladders -- a dropped pole, the linearised one-tanh structure DR 0001
     rejected, and a cutoff ROM read at the wrong frequency -- must each be
     separated from the real one BY THE SAME MEASUREMENT that is used on the
     references. If a broken model and ours both land inside the reference
     spread, the comparison proves nothing and these tests say so.

The plugin rigs are NOT exercised here: they need the VST3s and take minutes
per render. `model/reference_compare.py --stage validate` is their check, and
it cross-checks the two excitation methods against each other on Surge, where
both are possible.
"""
import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "audition"))

import audio_measure as am                                          # noqa: E402
import reference_rigs as rr                                         # noqa: E402
import voice_fx as vf                                               # noqa: E402

SR = rr.SR


# =============================================================================
# 1. the estimators, against signals whose answer is known in closed form
# =============================================================================
def test_slope_recovers_an_exact_minus_24_db_per_octave_line():
    """A response that IS -24 dB/oct must measure -24.000, and the fit's
    residual must say it was a straight line."""
    f = np.geomspace(500.0, 8000.0, 24)
    g = -24.0 * np.log2(f / 500.0)
    e = am.slope_db_oct(f, g, (800.0, 6400.0))
    assert e.ok, e.reason
    assert abs(e.value + 24.0) < 1e-9, e.value
    assert e.detail["residual_db"] < 1e-9


def test_slope_refuses_a_curve_that_is_not_a_straight_line():
    """The resonant skirt is not a slope. A band that straddles the peak has
    to be refused, not averaged -- that is how a 'rolloff' of +7.6 dB/oct got
    reported once (docs/discrimination.md section 8)."""
    f = np.geomspace(100.0, 8000.0, 40)
    g = 20 * np.log10(1.0 / np.abs(1 - (f / 1000.0) ** 2 + 1j * f / (8 * 1000.0)))
    e = am.slope_db_oct(f, g, (300.0, 6000.0))
    assert not e.ok, f"accepted a fit with residual {e.detail.get('residual_db')}"


def test_corner_recovers_the_closed_form_of_four_cascaded_one_poles():
    """Four identical one-poles at f_p are -3 dB at f_p * sqrt(2**(1/4) - 1)
    = 0.434995 * f_p. Exactly, by algebra."""
    fp = 1000.0
    exact = fp * math.sqrt(2.0 ** 0.25 - 1.0)
    f = np.geomspace(20.0, 12000.0, 120)
    g = -4 * 10 * np.log10(1 + (f / fp) ** 2)
    e = am.corner_from_curve(f, g, ref_band=(20.0, 60.0))
    assert e.ok, e.reason
    assert abs(e.value - exact) / exact < 0.005, (e.value, exact)


def test_corner_refuses_a_response_that_never_falls_3_db():
    f = np.geomspace(20.0, 12000.0, 60)
    e = am.corner_from_curve(f, np.zeros_like(f), ref_band=(20.0, 60.0))
    assert not e.ok


def test_peak_recovers_the_closed_form_height_and_q_of_a_known_resonator():
    """For H = 1 / (1 - (f/f0)^2 + j f / (Q f0)) the peak sits at
    f0 * sqrt(1 - 1/(2 Q^2)) and stands 20 log10( Q / sqrt(1 - 1/(4 Q^2)) )
    over the DC plateau. Both are checked, and so is the -3 dB Q."""
    f0, Q = 1000.0, 6.0
    f = np.geomspace(100.0, 10000.0, 400)
    H = 1.0 / (1 - (f / f0) ** 2 + 1j * f / (Q * f0))
    g = 20 * np.log10(np.abs(H))
    exact_f = f0 * math.sqrt(1 - 1 / (2 * Q ** 2))
    # the estimator measures the peak over the PLATEAU it was given, which for
    # this resonator sits 0.17 dB over DC -- so the closed-form comparison is
    # against the closed-form plateau, not against DC.
    exact_plateau = float(np.median(g[(f >= 100.0) & (f <= 200.0)]))
    exact_h = 20 * math.log10(Q / math.sqrt(1 - 1 / (4 * Q ** 2))) - exact_plateau
    e = am.peak_from_curve(f, g, ref_band=(100.0, 200.0))
    assert e.ok, e.reason
    assert abs(e.value - exact_h) < 0.05, (e.value, exact_h)
    assert abs(e.detail["f_peak"] - exact_f) / exact_f < 0.01
    assert abs(e.detail["q"] - Q) / Q < 0.06, (e.detail["q"], Q)


def test_peak_refuses_a_monotonic_response():
    f = np.geomspace(20.0, 12000.0, 80)
    e = am.peak_from_curve(f, -4 * 10 * np.log10(1 + (f / 1000.0) ** 2), ref_band=(20.0, 60.0))
    assert not e.ok, "called the argmax of a monotonic curve a resonance"


@pytest.mark.parametrize("f0", [131.0, 258.0, 997.0])
def test_harmonic_signature_recovers_known_harmonic_levels(f0):
    """A closed-form odd series at -14, -38, -52 dB. This is the estimator
    every structural claim in the write-up rests on, so it is checked at three
    fundamentals and to a tenth of a dB."""
    want = {3: -14.0, 5: -38.0, 7: -52.0}
    n = int(1.0 * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * math.pi * f0 * t)
    for k, dbv in want.items():
        x = x + 10 ** (dbv / 20.0) * np.sin(2 * math.pi * k * f0 * t + 0.3 * k)
    s = am.harmonic_signature(x, SR)
    assert abs(s["f0"] - f0) / f0 < 1e-4, s["f0"]
    for k, dbv in want.items():
        assert s[f"h{k}"] is not None, f"h{k} refused on a signal that has it"
        assert abs(s[f"h{k}"] - dbv) < 0.1, (k, s[f"h{k}"], dbv)
    assert s["h2"] is None, "reported an even harmonic in an odd-symmetric signal"


def test_harmonic_signature_reports_none_rather_than_the_noise_floor():
    """A pure sine under broadband noise has NO third harmonic. The estimator
    must say so, not hand back the noise in that bin as a level -- which is
    exactly the failure that would make two structures look alike."""
    rng = np.random.default_rng(7)
    n = int(1.0 * SR)
    x = np.sin(2 * math.pi * 300.0 * np.arange(n) / SR) + 1e-3 * rng.standard_normal(n)
    s = am.harmonic_signature(x, SR)
    assert s["h3"] is None, s["h3"]
    assert s["floor3"] is not None and s["floor3"] < -50.0, s["floor3"]


def test_harmonic_signature_refuses_harmonics_above_nyquist():
    n = int(0.5 * SR)
    x = np.sin(2 * math.pi * 6000.0 * np.arange(n) / SR)
    s = am.harmonic_signature(x, SR, f_lo=1000.0, f_hi=12000.0)
    assert s["h5"] is None and s["floor5"] is None


def test_the_stepped_tone_rig_agrees_with_the_acceptance_suite_probe():
    """`OurLadder.tone_gain_db` must return what
    `model/test_moog_acceptance.py`'s `probe_gain_db` returns: the harness
    compares the references against OUR filter as the rest of the repository
    already measures it, not against a second opinion about it."""
    from test_moog_acceptance import probe_gain_db
    ours = rr.OurLadder()
    freqs = np.array([100.0, 400.0, 1500.0, 4000.0])
    got = ours.tone_gain_db(freqs, 800.0, 0.5, 30000.0 / rr.FS_Q15)
    want = [probe_gain_db(f, 800, 0.5, 1.0, amp=30000) for f in freqs]
    assert np.allclose(got, want, atol=0.35), list(zip(freqs, got, want))


def test_the_variant_is_our_ladder_when_it_is_not_defective():
    """`_Variant(stages=4, nonlin='every')` must be `LadderFx` bit for bit.
    Every injected-defect control below measures the defect only if this
    holds; if it goes red the controls are measuring their own drift."""
    n = int(0.2 * SR)
    x = np.round(0.9 * rr.FS_Q15
                 * np.sin(2 * math.pi * 220.0 * np.arange(n) / SR)).astype(np.int16)
    real = rr.OurLadder()
    a = real._render(x, 3000, 0.8, drive=2.0)
    lad = rr._REAL_LADDER(**vf.LADDER_CFG)
    g, k, gain, ogain = real._regs(0.8, 3000, 2.0)
    b = lad.process(x, None, 0.8, 2.0, g_q16=np.full(n, g, dtype=np.int64),
                    k=k, gain=gain, ogain=ogain).astype(np.float64)
    assert np.array_equal(a, b)


# =============================================================================
# 2. start red: the comparison must be able to see a broken ladder
# =============================================================================
FREQS = np.geomspace(60.0, 9000.0, 26)


def _curve(rig, cut, res, amp=0.25):
    return rig.tone_gain_db(FREQS, cut, res, amp)


def test_a_dropped_pole_is_visible_in_the_measured_slope():
    """The injected defect for the 24 dB/oct claim. Two poles must measure
    near -12 dB/oct and four near -24, with no overlap: if the slope
    estimator cannot tell those apart it cannot adjudicate anything about the
    references either."""
    band = (700.0, 2400.0)   # 1.8 octaves of real stopband above a 300 Hz corner
    good = am.slope_db_oct(FREQS, _curve(rr.OurLadder(), 300.0, 0.3), band)
    bad = am.slope_db_oct(FREQS, _curve(rr.OurLadder("2-pole", stages=2), 300.0, 0.3), band)
    assert good.ok and bad.ok, (good.reason, bad.reason)
    assert good.value < -20.0, good.value
    assert bad.value > -16.0, bad.value
    assert good.value - bad.value < -6.0, (good.value, bad.value)


def test_a_skewed_cutoff_rom_moves_the_measured_corner_by_the_skew():
    """The injected defect for the cutoff-accuracy claim. A ladder whose g is
    looked up 30 % high must measure a corner about 30 % high -- so a real
    30 % cutoff error in any of the four filters could not hide."""
    ref = am.corner_from_curve(FREQS, _curve(rr.OurLadder(), 800.0, 0.2),
                               ref_band=(60.0, 160.0)).require("ours, corner")
    skew = am.corner_from_curve(FREQS, _curve(rr.OurLadder("skew", cut_skew=1.3), 800.0, 0.2),
                                ref_band=(60.0, 160.0)).require("skewed, corner")
    assert 1.18 < skew / ref < 1.45, (ref, skew, skew / ref)


def test_the_one_tanh_structure_is_separated_by_the_harmonic_signature():
    """The injected defect for the structural claim, and the reason the
    fingerprint is h5 relative to h3 rather than h2: the tanh is odd, so h2 is
    absent in BOTH candidate structures. Four linear poles with a single
    saturating element in the feedback must be far away from a tanh in every
    stage."""
    a = am.harmonic_signature(rr.OurLadder().ring(258.0, 1.3, seconds=1.0), SR)
    b = am.harmonic_signature(
        rr.OurLadder("1-tanh", nonlin="feedback").ring(258.0, 1.3, seconds=1.0), SR)
    assert a["h3"] is not None and b["h3"] is not None, (a, b)
    assert a["h5"] is not None, "ours: h5 under its own floor, no fingerprint to compare"
    sa = a["h5"] - a["h3"]
    sb = (b["h5"] - b["h3"]) if b["h5"] is not None else (b["floor5"] - b["h3"])
    assert sa - sb > 8.0, (sa, sb, a, b)
    # ...and the same probe at the TOP of the resonance range does not separate
    # them, because there the one-tanh control's hard input clip dominates. The
    # fingerprint is only usable at a stated resonance; that is a property of
    # the probe and it is reported as one.
    a2 = am.harmonic_signature(rr.OurLadder().ring(258.0, 2.0, seconds=1.0), SR)
    b2 = am.harmonic_signature(
        rr.OurLadder("1-tanh", nonlin="feedback").ring(258.0, 2.0, seconds=1.0), SR)
    near = abs((a2["h5"] - a2["h3"]) - (b2["h5"] - b2["h3"]))
    assert near < 8.0, ("the probe separates them at res 2.0 too; re-word the "
                        "write-up's caveat", near)


def test_a_silent_stub_is_refused_rather_than_measured():
    """The hardware-shaped failure: a rig that produces nothing must raise, not
    return a plausible number (verification rule 1)."""
    with pytest.raises(am.InsufficientEvidence):
        am.harmonic_signature(np.zeros(SR), SR)
