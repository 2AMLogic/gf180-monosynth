#!/usr/bin/env python3
"""Regression tests for the integer voice: oscillators, PolyBLEP, mixer,
envelopes and the cutoff ROM in front of the fixed-point ladder.

With these, the whole per-sample signal path is integer and these tests lock
the numbers it was sized from, in the same spirit as test_fixed.py.
"""
import os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pytest
import dsp, engines
import voice_fx as vf
from voice_fx_sweep import inharmonic_db
from dsp import SR


def _diff_db(y, ref):
    m = min(len(y), len(ref)); y, ref = y[:m], ref[:m]
    a = y / max(np.sqrt((y ** 2).mean()), 1e-12)
    b = ref / max(np.sqrt((ref ** 2).mean()), 1e-12)
    return 20 * math.log10(max(np.sqrt(((a - b) ** 2).mean()), 1e-12))


def _note(note):
    inc = dsp.phase_inc(dsp.note_hz(note))
    return inc, inc * SR / (1 << 24)


# ---- oscillators -----------------------------------------------------------
@pytest.mark.parametrize("shape", ["saw", "square", "pulse25", "tri", "sine"])
def test_oscillators_track_the_float_model(shape):
    """Every shape within 4 LSB (Q1.15) of the float PolyBLEP oscillator at
    every note. Catches a sign flip, a wrong branch, or a wrong shift in the
    BLEP arithmetic, which show up as tens or thousands of LSB."""
    n = int(0.3 * SR)
    for note in (12, 40, 64, 88, 100):
        inc, _ = _note(note)
        ref = dsp.osc_bl(shape, dsp.ramp(n, inc), inc) * 32768
        got = vf.OscFx(shape).render(n, inc)
        assert np.abs(got - ref).max() <= 4.0, (shape, note)


@pytest.mark.parametrize("note", [40, 64, 88])
def test_fixed_polyblep_suppresses_aliasing(note):
    """The integer PolyBLEP must reach the float one's suppression (~16 dB
    below naive, DR 0001) within half a dB."""
    n = int(0.5 * SR)
    inc, f0 = _note(note)
    naive = inharmonic_db(vf.OscFx("saw", blep=False).render(n, inc) / 32768.0, f0)
    fl = inharmonic_db(dsp.osc_bl("saw", dsp.ramp(n, inc), inc), f0)
    fx = inharmonic_db(vf.OscFx("saw").render(n, inc) / 32768.0, f0)
    assert fx <= naive - 14.0, f"note {note}: naive {naive:.1f}, fixed {fx:.1f}"
    assert fx <= fl + 0.5, f"note {note}: float {fl:.1f}, fixed {fx:.1f}"


def test_square_correction_has_the_right_sign():
    """A square steps UP at the wrap where a saw steps DOWN. With the sign
    inverted the square measures ~5 dB WORSE than naive."""
    n = int(0.5 * SR)
    inc, f0 = _note(88)
    naive = inharmonic_db(vf.OscFx("square", blep=False).render(n, inc) / 32768.0, f0)
    fx = inharmonic_db(vf.OscFx("square").render(n, inc) / 32768.0, f0)
    assert fx <= naive - 12.0


def test_reciprocal_width_is_set_by_waveform_accuracy_not_aliasing():
    """The finding the sizing rests on: 8 reciprocal bits already reach the
    float's aliasing suppression, but 16 are needed to track its waveform
    within Q1.15. If either half stops holding, the width decision changes."""
    n = int(0.5 * SR)
    inc, f0 = _note(88)
    ref = dsp.osc_bl("saw", dsp.ramp(n, inc), inc)
    fl = inharmonic_db(ref, f0)
    coarse = vf.OscFx("saw", True, 16, 8).render(n, inc)
    fine = vf.OscFx("saw", True, 16, 16).render(n, inc)
    assert inharmonic_db(coarse / 32768.0, f0) <= fl + 0.5
    assert np.abs(coarse - ref * 32768).max() > 32
    assert np.abs(fine - ref * 32768).max() <= 4


def test_glide_increment_reaches_the_target_exactly():
    """The linear slew must land on the target increment and the reciprocal
    must follow it; a stale reciprocal shows as LSB-scale garbage at the
    wraps after the glide."""
    v = vf.VoiceFx()
    r = v.note_on(64, 0.5, glide_from=52, waves=("saw",), detune=(0.0,), mix=(1.0,))
    seq = r["incs"][0]
    assert seq[-1] == dsp.phase_inc(dsp.note_hz(64))
    assert seq[0] == dsp.phase_inc(dsp.note_hz(52))
    out = v.run(r)
    n = len(out); inc = int(seq[-1])
    # after the glide the oscillator must be the held-note oscillator, bit for bit
    o = vf.OscFx("saw"); o.phase = int(seq[:vf.GLIDE_SAMPLES].sum()) & dsp.PHASE_MASK
    held = o.render(n - vf.GLIDE_SAMPLES, inc)
    assert np.array_equal(v.trace["osc"][0][vf.GLIDE_SAMPLES:], held)


# ---- mixer -----------------------------------------------------------------
def test_mixer_saturates_instead_of_wrapping():
    """Unnormalised weights overdrive; the sum must clip, never wrap."""
    full = np.full(4, 32767, dtype=np.int64)
    assert np.all(vf.mix_fx([full, full, full], [32768, 32768, 32768]) == 32767)
    assert np.all(vf.mix_fx([-full, -full, -full], [32768, 32768, 32768]) == -32768)


def test_normalised_mix_cannot_clip():
    for mix in [(1.0, 0.8, 0.5), (1.0, 1.0, 0.8), (1.0,), (1.0, 0.7, 0.9)]:
        assert sum(vf.mix_weights(mix)) <= 32768


# ---- envelopes -------------------------------------------------------------
@pytest.mark.parametrize("release", [0.1, 0.6, 1.0])
def test_release_reaches_exactly_zero(release):
    """The dead zone. `L -= (L*rate) >> 16` truncates to zero below
    2^16/rate and the note never ends; the max(1, .) closes it. The level
    must reach exactly 0 and stay there."""
    e = vf.AdsrFx(0.005, 0.25, 0.75, release)
    g = int(0.2 * SR)
    out = e.render(g + int(3.0 * release * SR), g)
    assert e.level == 0
    tail = out[g:]
    z = int(np.argmax(tail == 0))
    assert tail[z:].max() == 0
    # measured: exactly zero at 2.6-2.7x the release time, where the float
    # reaches about -90 dB
    assert z < 2.9 * release * SR


def test_release_floor_is_below_the_noise_floor():
    """Where the exponential step truncates to 1 LSB/frame the curve turns
    linear. At 24 level bits that floor is below -60 dBFS for any release up
    to 1 s; at 16 bits it is above -35 dBFS and audible. Locks the sizing."""
    for r in (0.1, 0.3, 0.6, 1.0):
        e = vf.AdsrFx(0.005, 0.25, 0.75, r, env_bits=24)
        assert 20 * math.log10(e.floor_level / (1 << 24)) < -60.0, r
        e16 = vf.AdsrFx(0.005, 0.25, 0.75, r, env_bits=16)
        assert 20 * math.log10(e16.floor_level / (1 << 16)) > -36.0, r
    # and measured, not just computed: the first frame whose decrement is 1
    e = vf.AdsrFx(0.005, 0.25, 0.75, 0.6)
    g = int(0.2 * SR)
    lv = e.render(g + int(2.0 * SR), g, q=24)[g:]
    d = -np.diff(lv)
    first_linear = int(np.argmax(d == 1))
    assert 20 * math.log10(lv[first_linear] / (1 << 24)) < -60.0


@pytest.mark.parametrize("env", [(0.005, 0.25, 0.75, 0.12), (0.02, 0.5, 0.80, 0.30),
                                 (0.001, 0.14, 0.0, 0.10), (0.9, 1.6, 0.10, 0.9)])
def test_envelope_tracks_the_float_model(env):
    """Within 0.5 % of full scale wherever the float is above -60 dB. The
    residue is the Q0.16 rate rounding (about 1 % on the release time) and
    the ceil() on the linear increments (under 0.3 % on the attack time)."""
    n, g = int(3.0 * SR), int(2.0 * SR)
    ref = dsp.adsr(n, *env, 2.0)
    got = vf.AdsrFx(*env).render(n, g) / 32768.0
    err = np.abs(got - ref)[ref > 1e-3].max()
    assert err < 0.005, err


def test_long_attack_is_not_truncated():
    """A 0.9 s attack at 24 bits completes within 1 % of 0.9 s. At 16 bits
    the per-frame increment rounds up so far that it finishes 24 % early."""
    n = int(1.2 * SR)
    for bits, tol in ((24, 0.01), (20, 0.05)):
        got = vf.AdsrFx(0.9, 1.6, 0.1, 0.6, env_bits=bits).render(n, n)
        t = np.argmax(got >= 32767) / SR
        assert abs(t - 0.9) / 0.9 < tol, (bits, t)
    got = vf.AdsrFx(0.9, 1.6, 0.1, 0.6, env_bits=16).render(n, n)
    assert abs(np.argmax(got >= 32767) / SR - 0.9) / 0.9 > 0.15


# ---- cutoff ROM ------------------------------------------------------------
def test_cutoff_rom_tracks_the_float_coefficient():
    """128 entries, interpolated: within 4 LSB of Q0.16 everywhere and
    within 1 % relative above 100 Hz."""
    cut = np.arange(vf.CUT_MIN, vf.CUT_MAX + 1)
    ex = np.clip(np.round((1 - np.exp(-2 * math.pi * cut / (2 * SR))) * 65536), 1, 65535)
    g = vf.g_from_cut(cut, vf.make_g_rom())
    assert np.abs(g - ex).max() <= 4
    rel = np.abs(g - ex) / ex
    assert rel[cut >= 100].max() < 0.01


# ---- the voice -------------------------------------------------------------
def test_voice_tracks_the_float_voice():
    """One default-patch note against mono_note(blep=True), with the float's
    ladder output clipped at +-1.0 the way the integer one must be (this
    patch peaks at 1.09). What remains is quantisation, and the ladder owns
    most of it: the front end alone measures below -40 dB on the bass
    patches (voice_fx_render.py)."""
    y = vf.VoiceFx().note(40, 0.6) / 32768.0
    ref = np.clip(engines.mono_note(40, 0.6, blep=True), -0.9, 0.9)
    assert _diff_db(y, ref) < -25.0


def test_signal_path_has_no_transcendentals():
    """Structural: after note_on has produced the register values, run() must
    not call any transcendental. (It cannot catch a stray float multiply;
    the dtype checks below cover the arrays.)"""
    import math as m
    v = vf.VoiceFx()
    r = v.note_on(52, 0.3)

    def boom(*a, **k):
        raise AssertionError("float transcendental in the signal path")
    saved = [(m, "exp"), (m, "tanh"), (m, "sin"), (m, "log"), (m, "pow"),
             (np, "exp"), (np, "tanh"), (np, "sin"), (np, "log"), (np, "power")]
    orig = [(o, name, getattr(o, name)) for o, name in saved]
    try:
        for o, name, _ in orig:
            setattr(o, name, boom)
        out = v.run(r)
    finally:
        for o, name, f in orig:
            setattr(o, name, f)
    assert out.dtype == np.int16
    for key in ("mixed", "amp_env", "filt_env", "cut", "ladder"):
        assert np.issubdtype(v.trace[key].dtype, np.integer), key
    for o in v.trace["osc"]:
        assert np.issubdtype(o.dtype, np.integer)


def test_ladder_accepts_integer_coefficients():
    """LadderFx with g_q16 must equal LadderFx with the float cutoff when the
    integers are the ones the float path would have produced."""
    import fixed
    n = int(0.2 * SR)
    x = fixed.f2q15(dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(110.0))) * 0.8)
    cut = np.full(n, 900.0)
    a = fixed.LadderFx(tanh_entries=16).process(x, cut, 0.8, drive=2.0)
    g = np.clip(np.round((1 - np.exp(-2 * math.pi * cut / (2 * SR))) * 65536), 1, 65535).astype(np.int64)
    b = fixed.LadderFx(tanh_entries=16).process(x, None, 0.8, drive=2.0, g_q16=g)
    assert np.array_equal(a, b)
