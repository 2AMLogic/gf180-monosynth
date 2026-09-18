#!/usr/bin/env python3
"""Regression tests for the integer drum section (model/drums_fx.py) and the
modal bank's extension for it (per-mode excitation, numerators). They lock
the numbers the design was sized from and the semantics the contract's
section 15 states, in the spirit of test_voice_fx.py.
"""
import os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pytest
import drums_fx as dx
import modal_fixed
from modal_fixed import ModalFx, RAW, BP, HP, pole_regs
import voice_fx as vf
import fixed
from dsp import SR

FULL24 = (1 << 24) - 1


def _solo(stop, seconds=0.3, accent=1.0, kit=None, extra=()):
    d = dx.DrumsFx()
    n = int(seconds * SR)
    w = sorted(dx.hit_writes([(10, stop, accent)], dx.kit_808() if kit is None else kit) + list(extra), key=lambda t: t[0])
    dm, bd = d.play(w, n)
    return d, dm, bd


# ---- the noise source (15.4) -------------------------------------------------
def test_lfsr_polynomial_is_primitive_and_the_leap_equals_the_serial_form():
    """x^31 + x^15 + x^13 + x^11 + 1 (delays 31, 16, 18, 20: state bits 30,
    15, 17, 19) is irreducible over GF(2) -- x^(2^31) = x mod p and no root
    -- and 2^31 - 1 is prime, so it is primitive: the period is 2^31 - 1
    bits. The 16-bits-at-once form the RTL uses is the serial form, step
    for step, and needs only the old state because every tap is at bit 15
    or above."""
    P = (1 << 31) | (1 << 15) | (1 << 13) | (1 << 11) | 1
    assert dx.LFSR_TAPS == (30, 15, 17, 19) and min(dx.LFSR_TAPS) >= dx.NOISE_BITS - 1

    def mulmod(a, b):
        r = 0
        while b:
            if b & 1:
                r ^= a
            b >>= 1
            a <<= 1
            if (a >> 31) & 1:
                a ^= P
        return r
    y = 2
    for _ in range(31):
        y = mulmod(y, y)
    assert y == 2 and P & 1 and bin(P).count("1") % 2 == 1
    s = dx.LFSR_SEED
    for _ in range(4000):
        a, b = dx.lfsr_frame(s), dx.lfsr_frame_leap(s)
        assert a == b
        s = a[0]
    assert dx.lfsr_frame(dx.LFSR_SEED)[1] == 1          # the seed's bit reaches tap 15 on step 16


def test_noise_is_white_and_full_scale():
    """Two seconds of words from reset: mean within 150 of 0 (a uniform
    source's standard error is 61 over 96 000 words; the trinomial the
    strawman used measured +351 here, its sparse-seed recovery), RMS that
    of a uniform Q1.15 variable (32768 / sqrt 3), and no autocorrelation
    above 2 % at lags 1..64 -- what a 16-bit window of an m-sequence per
    frame gives, and what reading the low bits of a once-per-frame LFSR
    (dsp.lfsr_noise) does not."""
    n = 2 * SR
    s, out = dx.LFSR_SEED, np.empty(n)
    for i in range(n):
        s, out[i] = dx.lfsr_frame(s)
    assert abs(out.mean()) < 150
    assert abs(out.std() / (32768 / math.sqrt(3)) - 1.0) < 0.02
    x = out - out.mean()
    for lag in (1, 2, 3, 7, 16, 64):
        assert abs(np.dot(x[:-lag], x[lag:]) / np.dot(x, x)) < 0.02, lag


# ---- stops (15.2) ----------------------------------------------------------------
def test_stops_fire_on_the_edge_between_frames_only():
    """A stop fires when its bit is 1 at a frame's start and was 0 at the
    previous frame's start: a held bit fires once, 1-0-1 fires twice, a
    rewrite of 1 does not fire, and two writes in one frame are one value."""
    d = dx.DrumsFx()
    kit = dx.kit_808()
    w = [(0, a, v) for a, v in kit]
    w += [(5, dx.A_STOPS, 1), (6, dx.A_STOPS, 1), (7, dx.A_STOPS, 1), (20, dx.A_STOPS, 0),
          (30, dx.A_STOPS, 1), (31, dx.A_STOPS, 0), (32, dx.A_STOPS, 1), (33, dx.A_STOPS, 0),
          (40, dx.A_STOPS, 0), (40, dx.A_STOPS, 1), (41, dx.A_STOPS, 0),
          (50, dx.A_STOPS, 1), (50, dx.A_STOPS, 0)]
    d.play(w, 60)
    fires = [f for f in range(60) if d.trace["fire"][f] & 1]
    assert fires == [5, 30, 32, 40]


# ---- envelopes (15.3) --------------------------------------------------------------
@pytest.mark.parametrize("tau", [0.004, 0.02, 0.15, 0.25])
def test_envelope_reaches_exactly_zero_and_the_dead_zone_is_closed(tau):
    """The voice's release rule (8.3) and its dead zone: below level = 2^16 /
    rate the product truncates to zero. Without the max(1, .) the level
    stalls there forever; with it the tail is one LSB per frame and reaches
    exactly 0, and the floor is below -60 dBFS for every tau up to 0.25 s."""
    for floor in (True, False):
        e = dx.EnvFx(floor=floor)
        e.peak, e.rate = FULL24, dx.rate_reg(tau)
        e.set_ctl(dx.env_ctl(0))
        e.frame(1, [32768] * 8)
        levels = []
        for _ in range(int(20 * tau * SR) + 200000):
            e.frame(0, [0] * 8)
            levels.append(e.level)
            if e.level == 0:
                break
        if floor:
            assert e.level == 0
            assert 20 * math.log10(e.floor_level / (1 << 24)) < -60.0
            assert min(l for l in levels if l) == 1                 # the linear tail ends at 1 then 0
        else:
            assert e.level > 0 and e.level < e.floor_level           # stalled inside the dead zone
            assert levels[-1] == levels[-1000]


def test_envelope_hold_bursts_and_choke():
    """hold = 48 keeps the fired level for 48 frames (the 1 ms pulse); bursts
    re-strike at period and 2 x period at 13/16 of the last strike, whatever
    the level has decayed to; a choke zeroes the level at once."""
    acc = [32768] * 8
    e = dx.EnvFx(); e.peak, e.rate = FULL24, 65535; e.set_ctl(dx.env_ctl(0, hold=48))
    e.frame(1, acc)
    lv = [e.level]
    for _ in range(60):
        e.frame(0, acc); lv.append(e.level)
    assert lv[:48] == [FULL24] * 48 and lv[48] == 256 and lv[49] == 1 and lv[50] == 0   # 65535: three updates
    e = dx.EnvFx(); e.peak, e.rate = FULL24, dx.rate_reg(0.004); e.set_ctl(dx.env_ctl(0, bursts=2, period=480))
    e.frame(1, acc)
    lv = [e.level]
    for _ in range(1500):
        e.frame(0, acc); lv.append(e.level)
    assert lv[480] == (FULL24 * 53248) >> 16 and lv[960] == (((FULL24 * 53248) >> 16) * 53248) >> 16
    assert lv[479] < lv[480] // 8 and lv[1440] < lv[960]                    # decayed in between; no fourth
    assert e.n_restrike == 2
    e = dx.EnvFx(); e.peak, e.rate = FULL24, 9; e.set_ctl(dx.env_ctl(5, choke=4))
    e.frame(1 << 5, acc); e.frame(0, acc)
    assert e.level > FULL24 // 2
    e.frame(1 << 4, acc)
    assert e.level == 0 and e.n_choke == 1


def test_accent_scales_the_strike_and_clamps_at_24_bits():
    """level = usat24((peak * accent) >> 15): accent 1.0 is the peak, 0.5
    half, and 2.0 on a full peak clamps to 2^24 - 1."""
    for accent, expect in ((32768, FULL24), (16384, FULL24 >> 1), (65535, FULL24), (0, 0)):
        e = dx.EnvFx(); e.peak = FULL24; e.set_ctl(dx.env_ctl(3))
        e.frame(1 << 3, [0, 0, 0, accent, 0, 0, 0, 0])
        assert e.level == expect, accent
    e = dx.EnvFx(); e.peak = 1000; e.set_ctl(dx.env_ctl(0))
    e.frame(1, [65535] * 8)
    assert e.level == (1000 * 65535) >> 15


# ---- paths, sources, nonlinearities, taps (15.5) --------------------------------------
def test_path_sums_are_exact_and_bounded():
    """Sixteen paths of PULSE x (FULL + FULL) into the mix bus: 16 x 65533,
    exact, no clamp; into one mode: the same into that mode's excitation,
    and the bank's 28-bit state clamp catches it, not a bus."""
    d = dx.DrumsFx()
    w = [(0, dx.A_PATH + p, dx.path_word(dx.SRC_PULSE, dx.ENV_FULL, dx.ENV_FULL, dest=dx.DEST_MIX)) for p in range(16)]
    dm, bd = d.play(w, 3)
    assert dm[0] == 16 * ((32767 * 65534) >> 15) == 16 * 65532 < (1 << 20)
    d = dx.DrumsFx()
    w = [(0, dx.A_PATH + p, dx.path_word(dx.SRC_PULSE, dx.ENV_FULL, dx.ENV_FULL, dest=3)) for p in range(16)]
    dm, bd = d.play(w, 3)
    assert d.trace["exc"][0, 3] == 16 * 65532 and dm[0] == 0
    assert d.bank.y1[3] == 16 * 65532                                         # a1 = a2 = 0: y = x, each frame                                     # a1 = a2 = 0: the sum, three frames


def test_nonlinearities_are_the_ladders_tanh_on_the_swing_and_plain():
    """LIN passes the source; TANH is tanh(x) with 1.0 at tanh(1.0) = 0.76
    (the ladder's table, Appendix C, on x << 5); SWING is x4 on the positive
    half -- 32767 x 4 is one LSB short of the clamp and interpolates to
    32766 -- and /8 on the negative, so the two halves differ by 32x in
    small-signal gain."""
    d = dx.DrumsFx()
    lad = fixed.LadderFx(**vf.LADDER_CFG)
    for x in (0, 1, 100, 4096, 8192, 16384, 32767, -1, -100, -4096, -32768):
        assert d._nonlinear(x, dx.NL_LIN) == x
        assert d._nonlinear(x, dx.NL_TANH) == lad.tanh_fx(x << 5)
        u = (x << 2) if x > 0 else (x >> 3)
        assert d._nonlinear(x, dx.NL_SWING) == lad.tanh_fx(fixed.sat(u << 5, 24))
    assert d._nonlinear(32767, dx.NL_SWING) == 32766 and d._nonlinear(-32768, dx.NL_SWING) == lad.tanh_fx(-4096 << 5)
    assert d._nonlinear(32768 // 2, dx.NL_TANH) == lad.tanh_fx(1 << 19)      # 0.5 -> tanh(0.5) = 0.46
    assert abs(d._nonlinear(1000, dx.NL_SWING)) > 30 * abs(d._nonlinear(-1000, dx.NL_SWING))


def test_tap_is_the_mode_state_over_eight_with_a_rail():
    """TAP m reads sat16(y1[m] >> 3): a mode ringing at 8.0 x full scale
    reads as the rail. Set the state directly and read it through a path
    with the full-scale envelope (index 15 = 32767, so v = tap * 32767 >> 15)."""
    for y1, tap in ((32768, 4096), (-32768 * 8, -32768), (32767 * 8 + 7, 32767), (32767 * 64, 32767),
                    (-(1 << 27), -32768), (-9, -2), (16, 2)):
        d = dx.DrumsFx()
        d.write(dx.A_PATH, dx.path_word(dx.SRC_TAP + 7, dx.ENV_FULL, dest=dx.DEST_MIX))
        d.bank.y1[7] = y1
        dm, _, *_ = d.frame()
        assert dm == (tap * 32767) >> 15, y1


def test_sources_are_what_the_contract_says():
    """PULSE is 32767; SQSUM is the six squares at +-5461 each (a 7-level
    staircase from 0 phases = +32766); SQPAIR is squares 4 and 5 at +-16383;
    OFF and every unassigned code are 0; envelope index 15 reads full scale
    (32767, so a path value is the source x 32767 >> 15) and 12..14 zero."""
    d = dx.DrumsFx()
    for p, (src, e1) in enumerate(((dx.SRC_PULSE, 15), (dx.SRC_SQSUM, 15), (dx.SRC_SQPAIR, 15), (dx.SRC_OFF, 15),
                                   (5, 15), (dx.SRC_PULSE, 13), (dx.SRC_PULSE, 12), (dx.SRC_NOISE, 15))):
        d.write(dx.A_PATH + p, dx.path_word(src, e1, dest=p))
    d.phase[5] = 1 << 23                                                      # square 5 low
    _, _, _, noise, sqsum, exc, vals = d.frame()
    assert vals[:7] == [(v * 32767) >> 15 for v in (32767, 4 * 5461)] + [0] * 5 and sqsum == 4 * 5461
    assert noise == 1 and vals[7] == (noise * 32767) >> 15 == 0             # the seed's first word, x 32767 >> 15


# ---- the bank's extension (15.6) -----------------------------------------------------
def test_numerators_reject_dc_and_the_resonator_passes_it():
    """BP (1 - z^-2) and HP (1 - z^-1)^2 on a DC excitation settle to 0
    within the floor rounding's residue (the recursion floors toward minus
    infinity, so a few LSB of state, -13 here, persist); RAW settles to
    DC gain 1 / (1 - a1 - a2). Modes at or above `nums` are RAW whatever
    num says."""
    m = ModalFx(modes=4, nums=2, headroom=0)
    coefs = [pole_regs(2000.0, 2.0) + (65535,)] * 4
    y = m.process(np.full(2000, 4096, np.int16), coefs, [BP, HP, HP, RAW])
    y1 = list(m.y1)
    assert abs(y1[0]) <= 16 and abs(y1[1]) <= 16
    a1, a2 = coefs[0][:2]
    dc = 4096 / (1 - (a1 + a2) / (1 << 24))
    assert abs(y1[2] - dc) < 0.01 * dc and abs(y1[3] - dc) < 0.01 * dc
    # a broadcast excitation equals the per-mode form, step for step
    m2 = ModalFx(modes=4, nums=2, headroom=0)
    exc = np.random.default_rng(1).integers(-32768, 32767, 500).astype(np.int16)
    a = ModalFx(modes=4, nums=2, headroom=0).process(exc, coefs, [BP, HP, RAW, RAW])
    b = m2.process(np.repeat(exc[:, None], 4, axis=1), coefs, [BP, HP, RAW, RAW])
    assert np.array_equal(a, b)


def test_pole_regs_reproduce_the_808_reference_table():
    """docs/tr808-reference.md section 14's Q2.24 pairs, from the same
    formula: r = exp(-pi f0 / (Q fs)), w = 2 pi f0 / fs."""
    assert pole_regs(56.0, 22.3) == (33548016, -16771702)      # BD, decay mid
    a1, a2 = pole_regs(56.0, 5.1519)                           # BD, short: the row prints Q as 5.2; its r is Q 5.152
    assert abs(a1 - 33529659) <= 16 and abs(a2 + 16753353) <= 16   # the row's own rounding of f0 and r
    assert pole_regs(173.0, 16.3) == (33522534, -16753924)     # SD low, later units
    assert pole_regs(336.0, 9.9) == (33447602, -16702846)      # SD high
    assert pole_regs(90.0, 25.0) == (33544199, -16769312)      # LT
    assert pole_regs(2500.0, 200.0) == (31747718, -16749787)   # CL


def test_bank_headroom_zero_and_nineteen_bits_hold_the_kits_loudest_hit():
    """All eight stops in one frame at accent 1.4, then 2.0: the body word
    (Q4.15, +-8.0) never saturates and no mode's 28-bit state does -- the
    kit's amps keep the loudest legal combination inside the width, so the
    only clamp on the way to the DAC is the output stage's (12)."""
    class Cov:
        def __init__(self): self.n = 0; self.s = modal_fixed.sat; modal_fixed.sat = self.c
        def c(self, v, b): r = self.s(v, b); self.n += (r != v); return r
        def off(self): modal_fixed.sat = self.s
    for accent in (1.4, 2.0):
        cov = Cov()
        d = dx.DrumsFx()
        dm, bd = d.play(dx.hit_writes([(10, s, accent) for s in range(8)], dx.kit_808()), int(0.3 * SR))
        cov.off()
        assert cov.n == 0, accent
        assert np.abs(bd).max() < (1 << 18) and np.abs(dm).max() < 65536


# ---- the output stage (12) ---------------------------------------------------------------
def test_output_stage_is_the_voice_formula_when_the_drums_are_silent():
    v = np.random.default_rng(2).integers(-(1 << 19), 1 << 19, 1000)
    ref = np.clip((v * vf.VOL_REF) >> 15, -32768, 32767).astype(np.int16)
    z = np.zeros(1000, dtype=np.int64)
    assert np.array_equal(dx.output_fx(v, vf.VOL_REF, z, 14746, z, 14746), ref)
    assert np.array_equal(dx.output_fx(v, vf.VOL_REF, v, 0, v, 0), ref)
    # the one rail: full buses at full gains clip, never wrap
    full = np.full(4, 1 << 20)
    assert np.all(dx.output_fx(full, 65535, full, 65535, full, 65535) == 32767)
    assert np.all(dx.output_fx(-full, 65535, -full, 65535, -full, 65535) == -32768)


# ---- the reference kit (Appendix G) ----------------------------------------------------
def test_kit_writes_fit_their_registers():
    B = dx.REG_BITS
    for a, v in dx.kit_808():
        assert 0 <= v < (1 << 32)
        if a == dx.A_STOPS: assert v < (1 << B["stops"])
        elif dx.A_ACCENT <= a < dx.A_ACCENT + 8: assert v < (1 << B["accent"])
        elif dx.A_OSC <= a < dx.A_OSC + 6: assert v < (1 << B["osc_inc"])
        elif dx.A_ENV <= a < dx.A_ENV + 48: assert v < (1 << (B["env_ctl"], B["peak"], B["rate"])[(a - dx.A_ENV) % 4])
        elif dx.A_PATH <= a < dx.A_PATH + 16: assert v < (1 << B["path"])
        elif dx.A_MODE <= a < dx.A_MODE + 48: assert v < (1 << (B["a1"], B["a2"], B["amp"], B["num"])[(a - dx.A_MODE) % 4])
        else: raise AssertionError(a)


def test_kit_voices_sit_at_the_chart_levels():
    """Each voice alone at accent 1.0 peaks at its target on its bus:
    Roland's chart proportions with the loudest at 0.5 x full scale
    (drums_fx_render.py --balance), within 12 %."""
    target = dict(BD=0.5, SD=0.43, LT=0.5, HT=0.5, CH=0.43, OH=0.5, CP=0.5, CB=0.5)
    for s, name in enumerate(dx.STOP_NAMES):
        d, dm, bd = _solo(s, 0.4)
        pk = (np.abs(dm) if name == "CP" else np.abs(bd)).max() / 32768
        assert abs(pk / target[name] - 1.0) < 0.12, (name, pk)


def test_bd_is_a_56_hz_resonator_with_the_reference_decay():
    """The BD is mode 6 ringing at 56 Hz with tau 127 ms (reference 2,
    decay mid), pinged by the 0.1 ms exponential kick: zero crossings over
    0.1..0.4 s give 56 Hz within 3 %, and the envelope's 1/e time is 127 ms
    within 20 %."""
    d, dm, bd = _solo(dx.BD, 0.6)
    x = bd.astype(float)
    a, b = int(0.1 * SR) + 10, int(0.4 * SR) + 10
    zc = np.sum(np.diff(np.signbit(x[a:b])) != 0)
    assert abs(zc / 2 / ((b - a) / SR) - 56.0) / 56.0 < 0.03
    env = np.abs(x)
    p0 = env[a:a + 2000].max(); t = a + 2000
    while env[t:t + 1000].max() > p0 / math.e:
        t += 100
    assert abs((t - a - 1000) / SR - 0.127) / 0.127 < 0.2


def test_snare_has_two_partials_and_a_snap():
    """Spectral peaks at the SD's 173 and 336 Hz modes (later units,
    reference 3), and noise energy above 2 kHz from the snappy path that is
    absent with SNAPPY (the noise envelope's peak) at zero."""
    d, dm, bd = _solo(dx.SD, 0.4)
    x = bd.astype(float)[10:]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / SR)
    for target in (173.0, 336.0):
        band = (f > target * 0.9) & (f < target * 1.1)
        assert f[band][np.argmax(spec[band])] == pytest.approx(target, rel=0.05)
    hi = spec[f > 2000].sum()
    kit = [(a, (0 if a == dx.A_ENV + dx.E_SDN * 4 + 1 else v)) for a, v in dx.kit_808()]
    d2, _, bd2 = _solo(dx.SD, 0.4, kit=kit)
    x2 = bd2.astype(float)[10:]
    spec2 = np.abs(np.fft.rfft(x2 * np.hanning(len(x2))))
    assert spec2[f > 2000].sum() < 0.05 * hi


def test_hats_are_squares_not_noise():
    """The hats are the six square oscillators through the band-pass, the
    swing VCA and a high-pass: with every oscillator increment 0 the closed
    hat is silent (a noise-based hat would not be), and with the kit the
    energy is above 5 kHz."""
    kit = [(a, (0 if dx.A_OSC <= a < dx.A_OSC + 6 else v)) for a, v in dx.kit_808()]
    d = dx.DrumsFx()                        # the hit well after the band-pass's start-up step has rung down
    dm, bd = d.play(dx.hit_writes([(2000, dx.CH, 1.0)], kit), 4000)
    assert np.abs(bd[1000:]).max() == 0 and np.abs(dm).max() == 0
    d, dm, bd = _solo(dx.CH, 0.2)
    x = bd.astype(float)[10:]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    assert spec[f > 5000].sum() > 5 * spec[f < 5000].sum()


def test_clap_has_three_bursts_and_a_tail():
    """Envelope 8's trace: strikes at 0, 10 and 20 ms at 1, 13/16 and
    (13/16)^2 of the first; envelope 9 the tail at -10 dB that outlasts them."""
    d, dm, bd = _solo(dx.CP, 0.2)
    burst = d.trace["env"][dx.E_CPBURST]
    tail = d.trace["env"][dx.E_CPTAIL]
    P = dx.peak_reg(0.69)
    assert burst[10] == P >> 9 and burst[490] == ((P * 53248) >> 16) >> 9
    assert burst[970] == ((((P * 53248) >> 16) * 53248) >> 16) >> 9
    assert burst[489] < burst[490] // 8 and burst[10 + 3000] == 0
    assert tail[10] == dx.peak_reg(0.22) >> 9 and tail[10 + 4000] > 0


def test_closed_hat_chokes_the_open_hat():
    """OH's envelope is zeroed in the frame CH fires (reference 11)."""
    d = dx.DrumsFx()
    d.play(dx.hit_writes([(10, dx.OH, 1.0), (500, dx.CH, 1.0)], dx.kit_808()), 600)
    oh = d.trace["env"][dx.E_OH]
    assert oh[499] > 30000 and oh[500] == 0 and oh[599] == 0
    assert d.trace["env"][dx.E_CH][500] == 32767


# ---- every legal register value runs (15.1) -------------------------------------------
def test_every_legal_register_value_runs():
    """Whatever a register can hold, the model must process: extremes on
    every address (all-ones words on every register at once, then all
    zeros), random words with a fixed seed, taps of railed modes into
    unstable modes, every source code, hits throughout -- no raise, both
    buses inside their widths, every state inside its width."""
    rng = np.random.default_rng(7)
    d = dx.DrumsFx()
    addrs = ([dx.A_STOPS] + list(range(dx.A_ACCENT, dx.A_ACCENT + 8)) + list(range(dx.A_OSC, dx.A_OSC + 6))
             + list(range(dx.A_ENV, dx.A_ENV + 48)) + list(range(dx.A_PATH, dx.A_PATH + 16))
             + list(range(dx.A_MODE, dx.A_MODE + 48)))
    writes = [(0, a, 0xFFFFFFFF) for a in addrs] + [(50, a, 0) for a in addrs] + [(51, dx.A_STOPS, 0xFF)]
    for f in range(60, 400, 4):
        writes.append((f, int(rng.choice(addrs)), int(rng.integers(0, 1 << 32))))
        if f % 12 == 0:
            writes += [(f, dx.A_STOPS, 0), (f + 1, dx.A_STOPS, 0xFF)]
    writes.append((100, 0x37, 1))                                          # no register there: ignored
    writes.append((200, dx.A_RESET, 0))
    writes += [(201, a, v) for a, v in dx.kit_808()]
    dm, bd = d.play(sorted(writes, key=lambda t: t[0]), 400)
    assert np.abs(dm).max() < (1 << 20) and np.abs(bd).max() < (1 << 18)
    assert all(0 <= e.level <= FULL24 and 0 <= e.t <= 2047 for e in d.envs)
    assert all(-(1 << 27) <= y < (1 << 27) for y in d.bank.y1 + d.bank.y2)
    assert np.abs(d.trace["exc"]).max() < (1 << 20)


def test_signal_path_has_no_transcendentals():
    """After the kit's writes are computed, play() must not call a float
    transcendental, and every traced array is integer."""
    d = dx.DrumsFx()
    w = dx.hit_writes([(5, s, 1.0) for s in range(8)], dx.kit_808())

    def boom(*a, **k):
        raise AssertionError("float transcendental in the signal path")
    saved = [(math, "exp"), (math, "tanh"), (math, "sin"), (math, "cos"), (math, "log"),
             (np, "exp"), (np, "tanh"), (np, "sin"), (np, "log")]
    orig = [(o, n, getattr(o, n)) for o, n in saved]
    try:
        for o, n, _ in orig:
            setattr(o, n, boom)
        dm, bd = d.play(w, 300)
    finally:
        for o, n, f in orig:
            setattr(o, n, f)
    assert dm.dtype == np.int64 and bd.dtype == np.int32
    for k in ("dmix", "body", "fire", "noise", "env", "exc"):
        assert np.issubdtype(d.trace[k].dtype, np.integer), k
