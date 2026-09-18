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


def _single(voice, note, dur, **kw):
    """One note through play(); returns (out, trace)."""
    out = voice.note(note, dur, **kw)
    return out, voice.trace


# ---- glide (DR 0004) --------------------------------------------------------
def test_glide_is_constant_rate_and_lands_exactly():
    """DR 0004: the increment moves by a constant RATIO per frame (a constant
    number of cents per frame), so a two-octave glide takes twice as long as
    a one-octave one, and it lands on the target exactly -- after which the
    oscillator is the held-note oscillator bit for bit."""
    v = vf.VoiceFx()
    r = v.note_on(64, 0.5, glide_from=52, waves=("saw",), detune=(0.0,), mix=(1.0,))
    v.run(r)
    seq = v.trace["incs"][0]
    i0, i1 = dsp.phase_inc(dsp.note_hz(52)), dsp.phase_inc(dsp.note_hz(64))
    assert seq[0] == i0 and seq[-1] == i1
    land = int(np.argmax(seq == i1))
    assert 0 < land < len(seq) and np.all(seq[land:] == i1)
    # constant cents per frame: log(inc) is linear in time within 1 LSB of rounding
    lg = np.log2(seq[:land].astype(float))
    step = np.diff(lg)
    assert step.max() - step.min() < 1e-3
    # one octave at the reference rate takes 90 ms within 1 %
    assert abs(land / SR - vf.GLIDE_REF_S) / vf.GLIDE_REF_S < 0.01, land / SR
    # the held-note oscillator after landing, bit for bit
    o = vf.OscFx("saw"); o.phase = int(seq[:land].sum()) & dsp.PHASE_MASK
    held = o.render(len(seq) - land, i1)
    assert np.array_equal(v.trace["osc"][0][land:], held)


def test_glide_time_is_proportional_to_the_interval():
    """Constant rate: two octaves take twice as long as one, up or down."""
    def land(a, b):
        v = vf.VoiceFx()
        v.run(v.note_on(b, 1.0, glide_from=a, waves=("saw",), detune=(0.0,), mix=(1.0,)))
        seq = v.trace["incs"][0]
        return int(np.argmax(seq == seq[-1]))
    one, two = land(52, 64), land(40, 64)
    assert abs(two / one - 2.0) < 0.02, (one, two)
    down = land(64, 52)
    assert abs(down / one - 1.0) < 0.02, (one, down)


def test_glide_preserves_the_detune_and_recomputes_the_reciprocal():
    """Every oscillator glides at the same rate, so the interval between two
    detuned oscillators is constant through the glide; and the PolyBLEP's
    (e, r) follow the increment (a stale reciprocal is LSB garbage at the
    wraps, which the exact-landing test above would catch)."""
    v = vf.VoiceFx()
    v.run(v.note_on(64, 0.4, glide_from=52, waves=("saw", "saw"), detune=(0.0, -12.0), mix=(1.0, 1.0)))
    a, b = v.trace["incs"][:2]
    land = int(np.argmax(a == a[-1]))
    ratio = a[:land].astype(float) / b[:land]
    assert ratio.min() > 1.99 and ratio.max() < 2.01
    for o, inc in zip(v.oscs, (a, b)):
        for u in np.unique(inc):
            assert o._er(int(u)) == vf.recip_of(int(u))


def test_glide_off_and_jump_take_effect_at_once():
    """glide = 0 snaps to the target; jump = 1 snaps whatever the rate."""
    v = vf.VoiceFx()
    v.run(v.note_on(64, 0.1, glide_from=52, glide_s=0.0))
    assert np.all(v.trace["incs"][0] == dsp.phase_inc(dsp.note_hz(64)))
    v = vf.VoiceFx()
    regs = vf.VoiceFx.patch_regs()
    i0, i1 = dsp.phase_inc(dsp.note_hz(40)), dsp.phase_inc(dsp.note_hz(52))
    v.play(regs, [(0, "INC", 0, i0, True), (0, "GATE", 1), (100, "INC", 0, i1, True)], 200)
    assert np.all(v.trace["incs"][0][:100] == i0) and np.all(v.trace["incs"][0][100:] == i1)


def test_glide_register_conversion():
    """One octave in 90 ms: 2^(1/4320) - 1 in Q0.24 is 2692; 0 s is off."""
    assert vf.glide_reg(0.09) == 2692
    assert vf.glide_reg(0.0) == 0
    assert vf.glide_reg(10.0) >= 1


# ---- retrigger (DR 0003) ----------------------------------------------------
def _events(*evs):
    return [(int(t * SR), kind, n) for t, kind, n in evs]


def test_legato_note_changes_pitch_without_restarting_the_envelopes():
    """Single trigger (the Minimoog's): a second key while the first is held
    changes the pitch and leaves both envelopes where they are."""
    v = vf.VoiceFx(); regs = vf.VoiceFx.patch_regs()
    host = vf.KeyHost(priority="last", trigger="single", glide="off")
    w = host.writes(_events((0.0, "on", 40), (0.3, "on", 47), (0.5, "off", 47), (0.6, "off", 40)), regs)
    v.play(regs, w, int(0.8 * SR))
    f = int(0.3 * SR)
    assert v.trace["trig"][f] == 0 and v.trace["gate"][f] == 1
    ae = v.trace["amp_env"]
    assert abs(int(ae[f + 1]) - int(ae[f])) <= 1              # sustain: level constant across the change
    assert v.trace["incs"][0][f] == dsp.phase_inc(dsp.note_hz(47))
    # last-note priority: releasing 47 returns to 40 while it is still held
    assert v.trace["incs"][0][int(0.55 * SR)] == dsp.phase_inc(dsp.note_hz(40))
    assert v.trace["gate"][int(0.55 * SR)] == 1 and v.trace["gate"][int(0.7 * SR)] == 0


def test_multi_trigger_restarts_the_attack_from_the_current_level():
    """TRIG: both envelopes re-enter ATTACK with their level unchanged -- no
    step in the output, then a rise of a_inc per frame from where it was."""
    v = vf.VoiceFx(); regs = vf.VoiceFx.patch_regs(amp=(0.05, 0.25, 0.5, 0.12))
    host = vf.KeyHost(trigger="multi", glide="off")
    w = host.writes(_events((0.0, "on", 40), (0.4, "on", 47), (0.6, "off", 47), (0.6, "off", 40)), regs)
    v.play(regs, w, int(0.8 * SR))
    f = int(0.4 * SR)
    assert v.trace["trig"][f] == 1
    ae = v.trace["amp_env"]; a_inc = v.amp_env.a_inc
    assert ae[f] == ae[f - 1]                                   # no jump at the trigger frame
    assert 0 < ae[f + 1] - ae[f] <= (a_inc >> 9) + 1            # then attacking from the current level
    assert ae[f + 1] > ae[f - 1]                                 # from the sustain level, not from zero


def test_gate_on_after_a_release_attacks_from_the_released_level():
    """A new phrase while the release is still audible: the attack starts
    from the current level, never from zero (no click)."""
    v = vf.VoiceFx(); regs = vf.VoiceFx.patch_regs(amp=(0.05, 0.25, 0.5, 0.5))
    host = vf.KeyHost(glide="off")
    w = host.writes(_events((0.0, "on", 40), (0.3, "off", 40), (0.32, "on", 45)), regs)
    v.play(regs, w, int(0.6 * SR))
    f = int(0.32 * SR)
    ae = v.trace["amp_env"]
    assert v.trace["trig"][f] == 1 and 0 < ae[f - 1] < 32767
    assert 0 <= ae[f - 1] - ae[f] <= 4                          # one last release step, no jump
    assert ae[f + 1] > ae[f] and ae[f + 1] > 8000                # attacking from the released level


def test_oscillator_phase_is_not_reset_at_note_on():
    """Free-running: GATE_ON, TRIG and SET_INC never write the phase."""
    v = vf.VoiceFx(); regs = vf.VoiceFx.patch_regs(waves=("saw",), detune=(0.0,), mix=(1.0,))
    host = vf.KeyHost(trigger="multi", glide="off")
    w = host.writes(_events((0.0, "on", 40), (0.2, "off", 40), (0.25, "on", 52), (0.5, "off", 52)), regs)
    v.play(regs, w, int(0.6 * SR))
    incs = v.trace["incs"][0]
    ph = np.cumsum(np.concatenate([[0], incs[:-1]])) & dsp.PHASE_MASK
    o = vf.OscFx("saw")
    assert np.array_equal(v.trace["osc"][0], o.render(len(incs), incs))
    assert int(ph[int(0.25 * SR)]) != 0                          # the second note did not start at phase 0


def test_ladder_state_is_continuous_across_notes():
    """The filter is never reset by a note: its state at the second note's
    first frame is exactly the state the first note left. A resonant ring
    from the first note therefore carries into the second, as it does in a
    circuit."""
    regs = vf.VoiceFx.patch_regs(q=0.95, cutoff=(300, 300), track=0.0)
    host = vf.KeyHost(glide="off")
    ev = _events((0.0, "on", 40), (0.2, "off", 40), (0.3, "on", 40), (0.5, "off", 40))
    v1 = vf.VoiceFx(); out1 = v1.play(regs, host.writes(ev, regs), int(0.6 * SR))
    v2 = vf.VoiceFx(); out2 = v2.play(regs, host.writes(ev[:2], regs), int(0.3 * SR))
    st2 = (list(v2.ladder.y), list(v2.ladder.w), v2.ladder.d1, v2.ladder.d2)
    out3 = v2.play(regs, [(0, "GATE", 1), (int(0.2 * SR), "GATE", 0)], int(0.3 * SR))
    assert np.array_equal(out1, np.concatenate([out2, out3]))
    assert np.abs(v1.trace["ladder"][int(0.3 * SR) - 1]) > 0     # still ringing when the gate returns


def test_paraphonic_keys_go_to_separate_oscillators():
    """Paraphony costs nothing on the chip: the host writes one held key per
    oscillator; the filter and envelopes stay shared. Single trigger."""
    v = vf.VoiceFx(); regs = vf.VoiceFx.patch_regs(waves=("saw", "saw", "saw"), detune=(0, 0, 0), mix=(1, 1, 1))
    host = vf.KeyHost(mode="para", glide="off")
    w = host.writes(_events((0.0, "on", 40), (0.1, "on", 47), (0.2, "on", 52), (0.4, "off", 47), (0.5, "off", 40), (0.6, "off", 52)), regs)
    v.play(regs, w, int(0.7 * SR))
    inc = lambda n: dsp.phase_inc(dsp.note_hz(n))
    f = int(0.3 * SR)
    assert [int(a[f]) for a in v.trace["incs"]] == [inc(40), inc(47), inc(52)]
    f = int(0.05 * SR)
    assert [int(a[f]) for a in v.trace["incs"]] == [inc(40), inc(40), inc(40)]   # one key: all three double it
    assert v.trace["trig"].sum() == 1 and v.trace["gate"][int(0.55 * SR)] == 1 and v.trace["gate"][-1] == 0


def test_single_note_from_reset_is_play_with_one_gate():
    """Contract 16's reference sequences: note() is play() with GATE_ON at
    frame 0 and GATE_OFF at gate_n, from reset."""
    a = vf.VoiceFx().note(40, 0.3)
    v = vf.VoiceFx(); regs = vf.VoiceFx.patch_regs()
    w = [(0, "INC", k, x, True) for k, x in enumerate(vf.VoiceFx.note_incs(40, regs["detune"]))]
    w += [(0, "TRACK", vf.VoiceFx.note_track(40, regs["track"])), (0, "GATE", 1), (int(0.24 * SR), "GATE", 0)]
    b = v.play(regs, w, int(0.3 * SR))
    assert np.array_equal(a, b)


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


# ---- resonance compensation (DR 0006) ---------------------------------------
def test_k_rom_is_the_linearised_onset():
    """32 + 1 entries of k_onset/4 in Q1.15 every 1024 Hz, evaluated at the
    cutoff clamped to 30..21600 Hz: 1.001 at the bottom, a peak of 1.217 at
    11 kHz, and flat at the clamp above entry 21. Spot values the contract
    quotes."""
    rom = vf.make_k_rom()
    assert len(rom) == 33 and rom[0] == 32799 and rom[1] == 33832
    assert rom.max() == 39879 and rom.argmax() == 11
    assert rom[22:].tolist() == [33964] * 11
    for i in (0, 5, 11, 21):
        k, _ = vf.k_onset(max(vf.CUT_MIN, 1024 * i))
        assert rom[i] == round(k / 4 * 32768)


def test_k_effective_saturates_at_the_port_width():
    """(k * kc) >> 15, clamped to the ladder's 17-bit k port."""
    assert int(vf.k_effective(65536, 32768)) == 65536
    assert int(vf.k_effective(65536, 39879)) == (65536 * 39879) >> 15
    assert int(vf.k_effective((1 << 17) - 1, 39879)) == (1 << 17) - 1


def _rings(cut, res, comp):
    """Growth rate of the fixed-point ladder's free ring at this cutoff and
    host resonance, with or without the compensation ROM (k_comp_sweep)."""
    import k_comp_sweep as ks
    rom = vf.make_g_rom()
    g = int(vf.g_from_cut(np.array([cut]), rom)[0])
    k = int(round(4.0 * res * (1 << 14)))
    if comp:
        k = int(vf.k_effective(k, vf.kc_from_cut(np.array([cut]), vf.make_k_rom())[0]))
    _, f_lin = vf.k_onset(cut, rom)
    n_cyc = SR / cut
    n_burst, n_settle, n_win = max(int(0.02 * SR), int(20 * n_cyc)), max(int(0.005 * SR), int(10 * n_cyc)), max(int(0.01 * SR), int(20 * n_cyc))
    for amp in (100.0, 25.0, 6.0, 1.5):
        tail = ks.ring(k, g, f_lin, amp, n_burst, n_settle + 2 * n_win)
        r, peak = ks.growth(tail, n_settle, n_win)
        if peak <= 1200:
            return r
    return 100.0


@pytest.mark.parametrize("cut", [200, 3000, 10000])
def test_self_oscillation_starts_at_res_1_everywhere(cut):
    """DR 0006's rule: with the ROM applied, res = 1 is the onset of
    self-oscillation at every cutoff within 0.5 % -- the ring decays at
    res 0.995 and grows at 1.005. The measured onset over 30 Hz .. 21.6 kHz
    is in model/k_comp_sweep.py's table."""
    assert _rings(cut, 0.995, True) < 0
    assert _rings(cut, 1.005, True) > 0


def test_uncompensated_k_stops_sustaining_above_3_khz():
    """Rev 1's finding, as a regression: at res 1.08 with no compensation the
    filter self-oscillates at 800 Hz and not at 6 kHz (the onset there is
    res 1.165); compensated, both sustain."""
    assert _rings(800, 1.08, False) > 0
    assert _rings(6000, 1.08, False) < 0
    assert _rings(6000, 1.08, True) > 0


# ---- gain staging (DR 0005) --------------------------------------------------
def test_reference_volume_clips_no_audition_patch():
    """The eight patches through the continuous voice at vol 0.45: the
    ladder's 19-bit output word never saturates (peak 1.94 x full scale on
    growl-bass) and the output's 16-bit clamp never fires; at rev 1's 0.9 it
    would clip growl-bass on 4.8 % of its samples."""
    import patches
    worst, clip45, clip90 = 0.0, 0.0, 0.0
    for name, seq, total in patches.MONO:
        v = vf.VoiceFx()
        vf.render_mono_fx(seq, total, v)
        y, vca = v.trace["ladder"], v.trace["vca"]
        worst = max(worst, np.abs(y).max() / 32768)
        assert np.abs(y).max() < (1 << 18), name                # sat19 never reached
        clip45 = max(clip45, np.mean(np.abs((vca * vf.VOL_REF) >> 15) > 32767))
        clip90 = max(clip90, np.mean(np.abs((vca * 29491) >> 15) > 32767))
    assert 1.5 < worst < 2.5, worst
    assert clip45 == 0.0 and clip90 > 0.03


def test_note_ends_after_gate_off_even_when_the_filter_sings():
    """The VCA is after the filter: a self-oscillating patch is silent
    0.5 s after its last gate-off although the ladder is still ringing."""
    regs = vf.VoiceFx.patch_regs(waves=("sine",), detune=(0.0,), mix=(1.0,), cutoff=(600, 600),
                                 q=1.06, drive=0.5, track=0.0, amp=(0.005, 0.1, 0.8, 0.05))
    v = vf.VoiceFx()
    w = [(0, "INC", 0, dsp.phase_inc(600.0), True), (0, "GATE", 1), (int(0.4 * SR), "GATE", 0)]
    out = v.play(regs, w, int(1.0 * SR))
    assert np.abs(v.trace["ladder"][-2400:]).max() > 3000       # the filter is still singing
    assert np.abs(out[-2400:]).max() <= 1                        # the note has ended


# ---- the voice -------------------------------------------------------------
def test_voice_tracks_the_float_voice():
    """One default-patch note against mono_note(blep=True, vca_post=True), the
    float voice in the integer voice's chain order (DR 0005). Nothing clips
    on either side now; what remains is quantisation, and the ladder owns
    most of it: the front end alone measures below -40 dB on the bass
    patches (voice_fx_render.py)."""
    y = vf.VoiceFx(k_comp=False).note(40, 0.6) / 32768.0      # the float has no k compensation
    ref = engines.mono_note(40, 0.6, blep=True, vca_post=True) * (vf.VOL_REF / 32768.0 / 0.9)
    assert np.abs(y).max() < 1.0 and np.abs(ref).max() < 1.0
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
