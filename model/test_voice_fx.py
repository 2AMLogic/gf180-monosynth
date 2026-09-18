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


# ---- register widths: NUMERIC-CONTRACT.md 5.1 against the conversions of 5.5
FULL24 = (1 << 24) - 1
SHAPES = ("saw", "square", "pulse25", "tri", "sine")


def _fits(v, bits) -> bool:
    return 0 <= int(v) < (1 << bits)


def test_attack_increment_clamps_below_two_frames():
    """Open item 17.7, a_inc. ceil(2^24 / frames) is 2^24 -- 25 bits -- for
    an attack of fewer than two frames (attack_s < 2/48000 = 41.67 us,
    attack_s = 0 included). The model now clamps to 2^24 - 1. Clamping, not
    widening: the clamp is unobservable, since either value completes the
    attack in one update from any level, so a 25th bit would buy nothing."""
    two = 2.0 / SR
    for a in (0.0, 1.0 / SR, math.nextafter(two, 0.0)):
        assert -(-(1 << 24) // max(1, int(a * SR))) == 1 << 24      # the raw overflow
        assert vf.AdsrFx(a, 0.25, 0.75, 0.12).a_inc == FULL24
    assert vf.AdsrFx(two, 0.25, 0.75, 0.12).a_inc == 1 << 23          # two frames fits
    assert vf.AdsrFx(3.0 / SR, 0.25, 0.75, 0.12).a_inc == 5592406
    for level in (0, 1, 12345, FULL24 - 1, FULL24):
        got = []
        for a_inc in (FULL24, 1 << 24):
            e = vf.AdsrFx(0.0, 0.25, 0.75, 0.12)
            e.a_inc, e.level = a_inc, level
            got.append((e.render(4, 4, q=24).tolist(), e.level, e.seg))
        assert got[0] == got[1], level
        assert got[0][0][1] == FULL24                                # full after one update


def test_release_rate_clamps_below_seven_microseconds():
    """Open item 17.7, rate. round((1 - exp(-4/(r*48000))) * 2^16) is 2^16
    -- 1.0, which Q0.16 cannot hold -- for r <= 4 / (17 ln 2 * 48000) =
    7.072 us, a third of a frame; and r = 0 divided by zero, a third raise
    the contract had not recorded. The model now clamps to 65535 and treats
    r <= 0 as instant, as the float model's max(1e-9, .) does. The cost of
    clamping rather than widening, pinned: full scale reaches zero in three
    updates (62.5 us) instead of one -- not worth a 17th bit on every rate
    multiply for a release nobody can hear."""
    r_star = 4.0 / (17.0 * math.log(2.0) * SR)
    assert abs(r_star - 7.072e-6) < 1e-9
    for r in (0.0, -1.0, 1e-6, 7.07e-6, r_star):
        assert vf.AdsrFx(0.005, 0.25, 0.75, r).rate == 65535
    for r in (1e-6, 7.07e-6):
        assert round((1 - math.exp(-4 / (r * SR))) * 65536) == 65536   # the raw overflow
    assert round((1 - math.exp(-4 / (7.08e-6 * SR))) * 65536) == 65535  # fits unclamped
    assert vf.AdsrFx(0.005, 0.25, 0.75, 7.08e-6).rate == 65535
    assert vf.AdsrFx(0.005, 0.25, 0.75, 1.0 / SR).rate == 64336
    assert vf.AdsrFx(0.005, 0.25, 0.75, 0.12).rate == 45                # the default patch
    def levels(rate):
        e = vf.AdsrFx(0.005, 0.25, 0.75, 0.12)
        e.rate, e.level = rate, FULL24
        return e.render(5, 0, q=24).tolist()
    assert levels(65535) == [FULL24, 256, 1, 0, 0]                      # three updates
    assert levels(1 << 16) == [FULL24, 0, 0, 0, 0]                      # 1.0 would take one


def test_zero_increment_stalls_the_oscillator():
    """Open item 17.9. inc = 0 is a legal register value -- it is the reset
    value of section 14 -- that no host conversion produces: NOTE_INC's
    smallest entry is 2858, and reaching 0 needs an oscillator below
    0.00143 Hz, a detune under -149 semitones at note 0. The model raised in
    recip_of; the contract's prose (6.3, 6.6.3, 14) was right and the model
    was wrong. Now: the phase stalls, the PolyBLEP is identically zero, and
    the oscillator holds the naive value of its phase -- DC, not silence,
    not a raise."""
    assert vf.recip_of(0) == (0, 0)
    assert min(dsp.phase_inc(dsp.note_hz(n)) for n in range(128)) == 2858
    assert dsp.phase_inc(dsp.note_hz(0) * 2.0 ** (-149 / 12)) == 1
    assert dsp.phase_inc(dsp.note_hz(0) * 2.0 ** (-150 / 12)) == 0
    ph = np.arange(0, 1 << 24, 1 << 10, dtype=np.int64)
    for e, r in ((0, 0), (-16, 0), (8, 65535)):
        assert not vf.blep_fx(ph, 0, e, r).any()                        # whatever (e, r) hold
    for shape in SHAPES:
        for phase in (0, 1, 0x3FFFFF, 0x7FFFFF, 0xC00000, 0xFFFFFF):
            o = vf.OscFx(shape)
            o.phase = phase
            out = o.render(64, 0)
            assert np.all(out == int(vf.naive_fx(shape, np.array([phase]))[0])), (shape, phase)
            assert o.phase == phase
    assert vf.OscFx("saw").render(1, 0)[0] == -32768     # not the 0 of 6.6.4, which needs inc > 0
    assert vf.OscFx("square").render(1, 0)[0] == 32767
    seq = np.array([3, 2, 1, 0, 0, 1, 2], dtype=np.int64)               # a slew through 0
    out = vf.OscFx("square").render(len(seq), seq)
    assert out.min() >= -32768 and out.max() <= 32767


def test_every_host_conversion_fits_its_register():
    """Every conversion of contract 5.5, walked over its full plausible input
    domain, lands inside the width 5.1 declares (vf.REG_BITS), and the clamp
    fires only where this test says it does. Beyond 17.7, the first run of
    this sweep found: inc overflows at note 127 with detune >= +23.24
    semitones (any oscillator at or above 48 kHz, the sample rate); k
    overflows at res >= 2.0; gain at drive >= 6.152; sus at sustain > 1;
    and a mix summing to zero divided by zero. All now clamp (the mix gives
    every weight 0). `wave` is an enum whose encoding is OPEN (17.3) and has
    no numeric conversion; every shape is constructed here for the record."""
    B = vf.REG_BITS
    v = vf.VoiceFx()
    detunes = [float(d) for d in np.arange(-24.0, 24.01, 0.25)]
    clamped = set()
    for note in range(128):
        f0 = dsp.note_hz(note)
        r = v.note_on(note, 0.001, waves=("saw",) * len(detunes), detune=tuple(detunes),
                      mix=(1.0,) * len(detunes))
        for dt, inc in zip(detunes, r["incs"]):
            assert _fits(inc, B["inc"]), (note, dt, inc)
            if inc != dsp.phase_inc(f0 * 2.0 ** (dt / 12.0)):
                clamped.add((note, dt))
        for track in np.linspace(0.0, 1.0, 11):
            r = v.note_on(note, 0.001, track=float(track))
            th = int(round(track * f0 * 4.0))
            assert _fits(r["track_hz"], B["track_hz"]) and r["track_hz"] == th, (note, track)
    assert clamped == {(127, dt) for dt in detunes if dt >= 23.25}
    assert max(int(round(dsp.note_hz(127) * 4.0)), 50175) == 50175          # track 1.0, note 127
    for lo in (0, 30, 100, 1000, 21600, 24000, 65535):
        for hi in (0, 30, 100, 1000, 21600, 24000, 65535):
            r = v.note_on(60, 0.001, cutoff=(lo, hi))
            assert (r["cut_lo"], r["cut_hi"]) == (lo, hi)
            assert _fits(r["cut_lo"], B["cut_lo"]) and _fits(r["cut_hi"], B["cut_hi"])
    for shape in SHAPES:
        vf.OscFx(shape)
    # envelopes: attack, decay x sustain, release, each over 0 .. 30 s
    two = 2.0 / SR
    attacks = [0.0, 1.0 / SR, math.nextafter(two, 0.0), two, 3.0 / SR] + list(np.geomspace(1e-6, 30.0, 300))
    for a in attacks:
        e = vf.AdsrFx(a, 0.25, 0.75, 0.12)
        assert _fits(e.a_inc, B["a_inc"]) and e.a_inc >= 1
        assert (e.a_inc == FULL24) == (a < two), a
    for d in [0.0] + list(np.geomspace(1e-6, 30.0, 60)):
        for sus in np.linspace(0.0, 1.0, 11):
            e = vf.AdsrFx(0.005, d, float(sus), 0.12)
            assert _fits(e.sus, B["sus"]) and e.sus == int(round(sus * FULL24))
            assert _fits(e.d_dec, B["d_dec"]) and e.d_dec == -(-(FULL24 - e.sus) // max(1, int(d * SR)))
    assert vf.AdsrFx(0.005, 0.25, 1.01, 0.12).sus == FULL24                # beyond the domain: clamps
    r_star = 4.0 / (17.0 * math.log(2.0) * SR)
    for rel in [0.0] + list(np.geomspace(1e-7, 30.0, 300)):
        e = vf.AdsrFx(0.005, 0.25, 0.75, rel)
        assert _fits(e.rate, B["rate"]) and e.rate >= 1
        if rel > r_star * (1 + 1e-9):
            assert e.rate == max(1, round((1 - math.exp(-4 / (rel * SR))) * 65536))
        else:
            assert e.rate == 65535
    # mixer weights: every 3-oscillator mix on a quarter grid, plus 1 and 2 oscillators
    grid = (0.0, 0.25, 0.5, 0.75, 1.0)
    for mix in [(a, b, c) for a in grid for b in grid for c in grid] + [(1.0,), (0.3, 1.0), (0.0,)]:
        w = vf.mix_weights(mix)
        assert all(_fits(x, B["w"]) for x in w)
        assert sum(w) <= 32768
        if sum(mix) == 0:
            assert w == [0] * len(mix)
    # ladder: res over 0 .. 1.5 (self-oscillation is at ~1.08), drive over 0 .. 4
    lad = vf.LadderFx(**vf.LADDER_CFG)
    for res in np.linspace(0.0, 1.5, 61):
        k, gain, ogain = lad.regs(float(res), 1.0)
        assert _fits(k, B["k"]) and k == int(round(4 * res * 16384))
        assert _fits(ogain, B["ogain"]) and ogain == int(round(0.05 / 0.13 * (1 + 2 * res) * 65536))
    for drive in np.linspace(0.0, 4.0, 41):
        gain = lad.regs(0.62, float(drive))[1]
        assert _fits(gain, B["gain"]) and gain == int(round(drive * 2.6 * 65536))
    assert lad.regs(0.62, 1.6) == (40632, 272630, 56462)                    # the default patch
    assert lad.regs(1.9999, 1.0)[0] == 131065 and lad.regs(2.0, 1.0)[0] == (1 << 17) - 1
    assert lad.regs(0.5, 6.15)[1] == 1047921 and lad.regs(0.5, 6.16)[1] == (1 << 20) - 1


def test_every_legal_register_value_runs():
    """The other direction of 5.1: whatever a register can hold, the model
    must process -- no raise, no NaN, output in range, state in range. Walks
    each register's extremes (0, 1, max, and the power-of-two edges where the
    PolyBLEP exponent changes) through the per-sample path, checks that the
    ladder's pre-saturation values stay inside the 28-bit datapath the RTL
    sketch carries (11.4) at every coefficient extreme, then runs the whole
    voice on an all-max image and on the all-zero reset image, which must be
    silent (14)."""
    import fixed
    incs = sorted({0, 1, 2, 3, (1 << 15) - 1, 1 << 15, (1 << 15) + 1, (1 << 16) - 1, 1 << 16,
                   153791, (1 << 23) - 1, 1 << 23, (1 << 23) + 1, (1 << 24) - 2, (1 << 24) - 1})
    for inc in incs:
        e, r = vf.recip_of(inc)
        assert -15 <= e <= 8 and 0 <= r < (1 << 16), inc
        for shape in SHAPES:
            for phase in (0, 0x7FFFFF, 0xFFFFFF):
                o = vf.OscFx(shape)
                o.phase = phase
                out = o.render(300, inc)
                assert out.dtype == np.int64 and out.min() >= -32768 and out.max() <= 32767, (shape, inc)
    full = np.full(8, 32767, dtype=np.int64)
    for w in (0, 1, 32768, (1 << 16) - 1):
        for sgn in (1, -1):
            m = vf.mix_fx([sgn * full] * 3, [w] * 3)
            assert m.min() >= -32768 and m.max() <= 32767
    ext24 = (0, 1, 1 << 23, FULL24)
    for a_inc in ext24:
        for d_dec in ext24:
            for sus in ext24:
                for rate in (0, 1, 32768, 65535):
                    e = vf.AdsrFx(0.005, 0.25, 0.75, 0.12)
                    e.a_inc, e.d_dec, e.sus, e.rate = a_inc, d_dec, sus, rate
                    lv = e.render(48, 24, q=24)
                    assert lv.min() >= 0 and lv.max() <= FULL24 and 0 <= e.level <= FULL24
    x = np.where((np.arange(200) // 25) & 1, 32767, -32768).astype(np.int16)
    widest = 0
    orig = fixed.sat
    def spy(v, bits):
        nonlocal widest
        widest = max(widest, abs(v))
        return orig(v, bits)
    fixed.sat = spy
    try:
        for k in (0, 1 << 16, (1 << 17) - 1):
            for gain in (0, 1 << 19, (1 << 20) - 1):
                for ogain in (0, (1 << 20) - 1):
                    for g in (0, 127, 49594, 65535):
                        y = fixed.LadderFx(**vf.LADDER_CFG).process(
                            x, None, 0.0, 0.0, g_q16=np.full(len(x), g), k=k, gain=gain, ogain=ogain)
                        assert y.dtype == np.int16
    finally:
        fixed.sat = orig
    assert widest < (1 << 27), widest
    v = vf.VoiceFx()
    r = v.note_on(60, 0.02)
    r["incs"] = [(1 << 24) - 1] * 3
    r["weights"] = [(1 << 16) - 1] * 3
    for env in (r["amp_env"], r["filt_env"]):
        env.a_inc = env.d_dec = env.sus = FULL24
        env.rate = 65535
    r["cut_lo"] = r["cut_hi"] = r["track_hz"] = 65535
    r["k"], r["gain"], r["ogain"] = (1 << 17) - 1, (1 << 20) - 1, (1 << 20) - 1
    out = v.run(r)
    assert out.dtype == np.int16 and np.abs(out.astype(np.int64)).max() <= 29491
    assert v.trace["cut"].min() >= vf.CUT_MIN and v.trace["cut"].max() <= vf.CUT_MAX
    r = v.note_on(60, 0.02)
    r["incs"], r["weights"] = [0] * 3, [0] * 3
    for env in (r["amp_env"], r["filt_env"]):
        env.a_inc = env.d_dec = env.sus = env.rate = 0
    r["cut_lo"] = r["cut_hi"] = r["track_hz"] = 0
    r["k"] = r["gain"] = r["ogain"] = 0
    assert not v.run(r).any()                                # silent until programmed (14)
    assert v.trace["cut"].min() == v.trace["cut"].max() == vf.CUT_MIN
