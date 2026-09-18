#!/usr/bin/env python3
"""Ground truth for the oscillator / envelope / glide / noise estimators.

    .venv/bin/python -m pytest model/test_reference_voice.py -q      # ~40 s

Same discipline as `model/test_reference_compare.py`, and for the same reason:
`docs/discrimination.md` section 8.1 records two published numbers that were a
measurement window rather than a filter. Every estimator here is checked
against a signal whose answer is known in closed form BEFORE it is pointed at
a reference, and each one is also checked to REFUSE the case it cannot answer
-- an estimator that always returns a number is the failure mode, not a
convenience.

The last group is the aliasing control: PolyBLEP switched off must be visible,
or the oscillator comparison has no power.
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
import voice_fx as vf                                               # noqa: E402

SR = 48000


# ===========================================================================
# closed-form waveforms
# ===========================================================================
def ideal(shape: str, f0: float, n: int, sr: int = SR, duty: float = 0.25,
          kmax: int = 200) -> np.ndarray:
    """A band-limited ideal waveform from its Fourier series: no aliasing by
    construction, so it is also the reference an aliasing measurement is
    compared against."""
    t = np.arange(n) / sr
    y = np.zeros(n)
    for k in range(1, kmax + 1):
        if k * f0 >= sr / 2:
            break
        if shape == "saw":
            y += np.sin(2 * math.pi * k * f0 * t) / k
        elif shape == "square":
            if k % 2:
                y += np.sin(2 * math.pi * k * f0 * t) / k
        elif shape == "tri":
            if k % 2:
                y += (-1) ** ((k - 1) // 2) * np.sin(2 * math.pi * k * f0 * t) / k ** 2
        elif shape == "pulse":
            y += math.sin(math.pi * k * duty) * np.cos(2 * math.pi * k * f0 * t) / k
        else:
            raise ValueError(shape)
    return y


def ideal_harmonics(shape: str, kmax: int = 9, duty: float = 0.25) -> dict:
    """h2..hk of each ideal waveform relative to its own fundamental, in dB,
    in closed form. `None` where the harmonic is exactly absent."""
    def a(k):
        if shape == "saw":
            return 1.0 / k
        if shape == "square":
            return 1.0 / k if k % 2 else 0.0
        if shape == "tri":
            return 1.0 / k ** 2 if k % 2 else 0.0
        if shape == "pulse":
            return abs(math.sin(math.pi * k * duty)) / k
        raise ValueError(shape)
    a1 = a(1)
    # `sin(pi*4*0.25)` is 1.2e-16 in floating point, not 0: an exact null has
    # to be recognised by magnitude, not by equality, or the ground truth
    # asks the estimator for a harmonic at -327 dB.
    return {k: (None if abs(a(k)) < 1e-12 else 20 * math.log10(abs(a(k)) / a1))
            for k in range(2, kmax + 1)}


def lfsr16(n: int, seed: int = 0xACE1) -> np.ndarray:
    """A maximal-length 16-bit Galois LFSR, x^16 + x^14 + x^13 + x^11 + 1.
    Period 65535 samples = 1.36531 s at 48 kHz -- the number this repository
    needs a measurement against."""
    st, out = seed, np.empty(n)
    for i in range(n):
        lsb = st & 1
        st >>= 1
        if lsb:
            st ^= 0xB400
        out[i] = 1.0 if lsb else -1.0
    return out


def pink(n: int, seed: int = 3) -> np.ndarray:
    """Exactly -3.01 dB/octave by construction: white shaped by 1/sqrt(f)."""
    rng = np.random.default_rng(seed)
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(X))
    X[1:] /= np.sqrt(f[1:])
    X[0] = 0
    y = np.fft.irfft(X, n)
    return y / np.abs(y).max()


# ===========================================================================
# 1. the harmonic series of a waveform, at a KNOWN fundamental
# ===========================================================================
@pytest.mark.parametrize("shape", ["saw", "square", "tri", "pulse"])
def test_harmonic_series_matches_the_closed_form_of_each_ideal_waveform(shape):
    f0 = 110.0
    x = ideal(shape, f0, SR)
    s = am.harmonic_signature(x, SR, f0=f0, kmax=9)
    want = ideal_harmonics(shape)
    for k, w in want.items():
        got = s[f"h{k}"]
        if w is None:
            assert got is None, f"{shape} h{k}: reported {got} for a harmonic that is absent"
        else:
            assert got is not None, f"{shape} h{k}: refused a harmonic that is present at {w:.2f}"
            assert abs(got - w) < 0.25, (shape, k, got, w)


def test_the_25_percent_pulse_null_is_reported_as_absent_not_as_the_floor():
    """A 25 % pulse has an exact null at every 4th harmonic. An estimator that
    hands back the noise in that bin as a level would make two different duty
    cycles look alike."""
    s = am.harmonic_signature(ideal("pulse", 110.0, SR), SR, f0=110.0, kmax=9)
    assert s["h4"] is None and s["h8"] is None, (s["h4"], s["h8"])
    assert s["h2"] is not None and abs(s["h2"] + 3.01) < 0.25, s["h2"]


# ===========================================================================
# 2. noise: colour, and whether it repeats
# ===========================================================================
def test_psd_slope_reads_white_as_zero_and_pink_as_minus_three():
    rng = np.random.default_rng(11)
    w = am.psd_slope_db_oct(rng.standard_normal(SR * 4), (100.0, 12000.0), SR)
    p = am.psd_slope_db_oct(pink(SR * 4), (100.0, 12000.0), SR)
    assert w.ok and p.ok, (w.reason, p.reason)
    assert abs(w.value) < 0.5, w.value
    assert abs(p.value + 3.01) < 0.6, p.value


def test_psd_slope_refuses_a_tone():
    """A sine is not a noise colour. The straightness check has to reject it,
    or every oscillator in the study reads as some exotic noise."""
    t = np.arange(SR * 4) / SR
    e = am.psd_slope_db_oct(np.sin(2 * math.pi * 1000 * t), (100.0, 12000.0), SR)
    assert not e.ok, e.value


def test_repeat_period_finds_a_16_bit_lfsr_at_its_exact_period():
    """65535 samples at 48 kHz = 1.365313 s. This is the number the noise
    target is written against."""
    e = am.repeat_period(lfsr16(int(3.5 * SR)), SR, max_lag_s=3.0)
    assert e.ok, e.reason
    assert abs(e.value - 65535 / SR) < 2.0 / SR, (e.value, 65535 / SR)
    assert e.detail["corr"] > 0.95, e.detail


def test_repeat_period_refuses_noise_that_does_not_repeat():
    rng = np.random.default_rng(5)
    e = am.repeat_period(rng.standard_normal(int(3.5 * SR)), SR, max_lag_s=3.0)
    assert not e.ok, f"claimed a repeat at {e.value} s in white noise"


# ===========================================================================
# 3. envelope segment shape
# ===========================================================================
def test_segment_shape_has_the_closed_form_index_of_each_candidate_law():
    """linear 0.0000; RC charge and RC discharge both +0.3808 (the index is a
    property of the path, not its direction -- `span`'s sign gives that);
    convex t^2 -0.2500. Those are what the envelope comparison reads."""
    n = 4800
    t = np.linspace(0, 1, n)
    lin = am.segment_shape(t, SR)
    up = am.segment_shape(1 - np.exp(-4 * t), SR)
    dn = am.segment_shape(np.exp(-4 * t), SR)
    cx = am.segment_shape(t ** 2, SR)
    assert lin.ok and up.ok and dn.ok and cx.ok
    assert abs(lin.value) < 0.005, lin.value
    assert abs(up.value - 0.3808) < 0.004, up.value
    assert abs(dn.value - 0.3808) < 0.004, dn.value
    assert abs(cx.value + 0.25) < 0.005, cx.value
    assert up.detail["span"] > 0 and dn.detail["span"] < 0, "span must give the direction"


def test_segment_shape_reports_the_10_to_90_time_of_a_linear_ramp():
    n = SR // 10                                    # 0.1 s ramp
    e = am.segment_shape(np.linspace(0, 1, n), SR)
    assert e.ok
    assert abs(e.detail["t_10_90_s"] - 0.08) < 0.002, e.detail


def test_segment_shape_refuses_a_segment_that_does_not_move():
    assert not am.segment_shape(np.ones(1000), SR).ok


# ===========================================================================
# 4. the glide law
# ===========================================================================
def _traj(law, f0=110.0, f1=440.0, dur=0.4):
    t = np.arange(int(dur * SR)) / SR
    if law == "constant-rate":
        return f0 * (f1 / f0) ** (t / dur)
    if law == "constant-time":
        return f1 + (f0 - f1) * np.exp(-t / (dur / 4))
    if law == "linear-hz":
        return f0 + (f1 - f0) * t / dur
    raise ValueError(law)


@pytest.mark.parametrize("law", ["constant-rate", "constant-time", "linear-hz"])
def test_glide_law_identifies_each_synthesised_law(law):
    e = am.glide_law(_traj(law), SR)
    assert e.ok, e.reason
    assert e.detail["law"] == law, (law, e.detail["r2"])
    others = [v for k, v in e.detail["r2"].items() if k != law]
    assert e.value - max(others) > 0.004, (law, e.detail["r2"])


def test_glide_law_reports_the_rate_of_a_constant_rate_glide():
    """Two octaves in 0.4 s is 6000 cents/s, exactly."""
    e = am.glide_law(_traj("constant-rate", 110.0, 440.0, 0.4), SR)
    assert abs(e.detail["cents_per_s"] - 6000.0) < 30.0, e.detail
    assert abs(e.detail["octaves"] - 2.0) < 0.01


def test_glide_law_refuses_a_static_pitch():
    assert not am.glide_law(np.full(SR // 4, 220.0), SR).ok


# ===========================================================================
# 5. START RED: the aliasing measurement must see PolyBLEP switched off
# ===========================================================================
def _osc(shape, note, seconds=0.3, blep=True):
    from audition.dsp import note_hz                               # noqa: F401
    o = vf.OscFx(shape, blep=blep)
    inc = vf.phase_inc(vf.note_hz(note))
    return np.asarray(o.render(int(seconds * SR), inc), dtype=np.float64) / 32768.0


@pytest.mark.parametrize("shape,note", [("saw", 88), ("square", 88), ("saw", 76)])
def test_polyblep_off_is_visible_in_the_aliasing_measure(shape, note):
    """The injected control for every oscillator number in the study. If the
    measure cannot see the anti-aliasing switched off, it cannot adjudicate
    one synthesiser's oscillator against another's."""
    f0 = vf.note_hz(note)
    on = am.inharmonic_fraction_db(_osc(shape, note, blep=True), f0, SR).require("blep on")
    off = am.inharmonic_fraction_db(_osc(shape, note, blep=False), f0, SR).require("blep off")
    assert off - on > 6.0, (shape, note, on, off)


def test_an_ideal_waveform_has_less_inharmonic_energy_than_ours():
    """Sanity on the direction of the measure: the closed-form band-limited
    saw must read lower than any real oscillator at the same pitch."""
    f0 = vf.note_hz(88)
    a = am.inharmonic_fraction_db(ideal("saw", f0, int(0.3 * SR)), f0, SR).require("ideal")
    b = am.inharmonic_fraction_db(_osc("saw", 88), f0, SR).require("ours")
    assert a < b, (a, b)


# ===========================================================================
# 6. envelope ripple -- the "zipper" measure, against its closed form
# ===========================================================================
def test_envelope_ripple_is_at_the_floor_for_a_smooth_ramp():
    """A smooth envelope must read as having no stepping. If it does not, the
    measure will call every sweep grainy and adjudicate nothing."""
    n = SR
    e = am.envelope_ripple_db(np.linspace(1.0, 4.0, n), SR)
    assert e.ok, e.reason
    assert e.value < -70.0, e.value


@pytest.mark.parametrize("rate", [500.0, 1000.0, 2000.0])
def test_envelope_ripple_matches_the_closed_form_of_a_known_staircase(rate):
    """A staircase of step d on a ramp of mean m, stepping fast compared with
    the high-pass window, has residual RMS d/sqrt(12) -- so the ripple is
    20*log10(d / (sqrt(12) * m)). Checked at three step RATES, because the
    measure under-reads when the steps are slower than its own window and
    that limit has to be pinned, not discovered later."""
    n = SR
    t = np.linspace(0.0, 1.0, n)
    span = 3.0
    d = span / rate                      # `rate` steps per second over the ramp
    steps = np.round((1.0 + span * t) / d) * d
    e = am.envelope_ripple_db(steps, SR, hp_hz=40.0)
    want = 20 * math.log10(d / (math.sqrt(12) * float(np.mean(steps))))
    assert e.ok, e.reason
    assert abs(e.value - want) < 1.0, (rate, e.value, want)
    assert abs(e.detail["ripple_rate_hz"] - rate) / rate < 0.10, e.detail


def test_envelope_ripple_under_reads_when_the_steps_are_slower_than_its_window():
    """The validity condition, asserted rather than assumed: at 15 steps per
    second against a 40 Hz high-pass the moving average partly tracks the
    staircase and the measure reads 4.1 dB LOW. Anyone quoting a ripple checks
    `ripple_rate_hz` against `hp_hz` first, and this test is why."""
    n, span, rate = SR, 3.0, 15.0
    t = np.linspace(0.0, 1.0, n)
    d = span / rate
    steps = np.round((1.0 + span * t) / d) * d
    e = am.envelope_ripple_db(steps, SR, hp_hz=40.0)
    want = 20 * math.log10(d / (math.sqrt(12) * float(np.mean(steps))))
    assert e.ok
    assert e.value < want - 3.0, (e.value, want)   # measured: 4.1 dB low at 15 steps/s


def test_envelope_ripple_band_limit_attenuates_the_hilbert_artefact():
    """The analytic envelope of a real sinusoid is not exactly constant, and
    its residual sits AT AND ABOVE the carrier. Without the band limit the
    measure reports that as stepping -- it read -32.4 dB on a render that had
    none. With `lp_hz` under the carrier it must fall away.

    The artefact is measured at f0 itself, not at the 2*f0 this test first
    asserted; that assertion was wrong and is corrected here rather than
    loosened, because WHERE the artefact sits is what decides where `lp_hz`
    has to go."""
    n = SR
    t = np.arange(n) / SR
    x = np.sin(2 * math.pi * 2000.0 * t) * (1.0 + 0.5 * t)      # smooth swell, no steps
    env = am.analytic_envelope(x)
    raw = am.envelope_ripple_db(env, SR)
    lim = am.envelope_ripple_db(env, SR, lp_hz=800.0)
    assert raw.ok and lim.ok
    assert raw.detail["ripple_rate_hz"] >= 1900.0, raw.detail    # at or above the carrier
    # measured: -75.3 dB unlimited, -93.2 dB at lp_hz = 800 on this signal.
    # A moving-average low-pass ATTENUATES the artefact rather than removing it,
    # so `ripple_rate_hz` can still name the carrier afterwards -- 18 dB smaller.
    assert lim.value < raw.value - 15.0, (raw.value, lim.value)


def test_envelope_ripple_refuses_silence():
    assert not am.envelope_ripple_db(np.zeros(SR), SR).ok
