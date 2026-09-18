"""Fully integer voice -- monophonic, or paraphonic when the host assigns held
keys to oscillators: oscillators with an on-chip glide, PolyBLEP, mixer,
envelopes and the cutoff path (g and resonance-compensation ROMs), around
`fixed.LadderFx`, with the VCA after the filter and a host volume. No float
anywhere in the per-sample signal path, so that RTL can be bit-exact against
it. One continuous voice: `VoiceFx.play` applies control writes at frame
boundaries to state that persists between notes (DR 0003).

This closes the gap `fixed_render.py` describes: the ladder was integer, but the
oscillators and envelopes were float, quantised to Q1.15 at the filter input.

Signal chain (the Minimoog's order, DR 0005; the audition's `engines.mono_note`
applied the amplitude envelope before the filter):

    3 x (glide -> phase accumulator -> waveform -> PolyBLEP)   Q1.15
      -> mixer (Q0.15 weights, saturating)                     Q1.15
      -> ladder, g and kc from the cutoff ADSR via ROMs        Q4.15   (19-bit output word)
      -> x amplitude ADSR (the VCA)                            Q4.15
      -> x vol, saturated                                      Q1.15

Where float is still allowed -- and this is the only place: computing NOTE-ON
REGISTER VALUES and ROM CONTENTS from the patch's physical units. Hz -> phase
increment (`dsp.phase_inc`), seconds -> envelope rate, the tanh/sine/g tables.
In hardware those are the host's job or a ROM's; the same convention `fixed.py`
already uses for its coefficient. Everything evaluated per sample is integer.

Every one of those conversions clamps its result to the width of the register
it lands in (`REG_BITS`, NUMERIC-CONTRACT.md 5.1, via `fixed.usat`), so the
model can never hold a value a register-limited implementation cannot. The two
that can hit the clamp with musically plausible input are a_inc (attacks
shorter than two frames) and rate (releases shorter than ~7 us); the sweep in
test_voice_fx.py walks every conversion over its input domain and pins where
each clamp fires. And every LEGAL register value is handled per sample: inc = 0
stalls its oscillator with the PolyBLEP at zero rather than raising.

Formats:
    phase           24-bit accumulator (dsp.PHASE_BITS)
    waveform        Q1.15
    PolyBLEP        increment normalised at note-on to a 16-bit mantissa m and
                    exponent e (inc = m * 2^e); reciprocal r = floor(2^31 / m),
                    16 bits. Per sample the fraction ph/inc in Q0.16 is one
                    16x16 multiply: ((ph >> e) * r) >> 15. Polynomial in Q0.16,
                    correction in Q1.15. Both widths are parameters, so the
                    sizing can be measured (`voice_fx_sweep.py`).
    mixer           Q0.15 weights, floor-normalised so they sum to <= 1.0;
                    32-bit accumulator, >> 15, saturated to Q1.15
    envelope        24-bit unsigned level, Q0.24. Attack and decay are linear
                    ramps (an increment per frame), matching the float model
                    that was auditioned. Release is exponential: subtract a
                    fraction of the level each frame, L -= max(1, (L*rate)>>16)
                    with rate in Q0.16. The max(1, .) is load-bearing -- without
                    it the shifted product truncates to zero below
                    2^16/rate and the note never ends. Output Q0.15 = L >> 9.
    glide           Q0.24 register, the ratio per frame minus 1 (0 = off);
                    the increment slews in a Q24.8 accumulator by
                    max(1, (acc * glide) >> 24) per frame toward its target:
                    constant cents per frame, exact landing (DR 0004)
    cutoff          integer Hz, 15 bits, clamped to [30, 21600]
    g ROM           128 entries x Q0.16, edge-sampled every 256 Hz, linearly
                    interpolated on the low 8 bits of the cutoff (same read
                    convention as the tanh table)
    kc ROM          32 entries x Q1.15, every 1024 Hz, the same interpolation:
                    the loop gain at which the linearised ladder starts to
                    self-oscillate, over 4. k_eff = (k * kc) >> 15 per frame,
                    so res = 1 is the onset at every cutoff (DR 0006)
    ladder          fixed.LadderFx: 24-bit state, 20 fraction bits, 16-entry
                    interpolated tanh, 19-bit output (Q4.15) so that the
                    resonant peak has headroom and nothing clips before the
                    output stage (DR 0005)
    VCA, vol        (y * ae) >> 15, then (v * vol) >> 15 saturated to Q1.15:
                    the one output clamp, reached only if the host raises vol
                    past the reference 0.45

Note-on (DR 0003): GATE_ON and TRIG re-enter ATTACK from the current level;
no write resets a phase or the ladder. Key priority, single/multi trigger,
glide policy and paraphonic allocation are the host's: `KeyHost` is the
reference host, informative in the contract.
"""
from __future__ import annotations
import math
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import dsp
from dsp import SR, PHASE_BITS, PHASE_MASK, note_hz, phase_inc
import fixed
from fixed import LadderFx, sat, shl, usat

CYCLE = 1 << PHASE_BITS
ENV_BITS = 24
RATE_Q = 16
MANT_BITS = 16
RECIP_BITS = 16
GROM_BITS = 7                    # 128-entry cutoff -> g ROM
KROM_BITS = 5                    # 32-entry cutoff -> resonance compensation ROM (DR 0006)
K_BITS = LadderFx.K_BITS         # the ladder's k port: Q3.14, 17 bits; k_eff saturates there
CUT_MIN, CUT_MAX = 30, 21600     # Hz; the float model clips to [30, 0.45*SR]
VOL_REF = 14746                  # reference host's output volume, 0.45 in Q0.15 (DR 0005)
LADDER_OUT_BITS = 19             # ladder output word Q4.15, +-8.0: headroom for the peak (DR 0005)
GLIDE_BITS = 24                  # glide register: ratio per frame - 1, Q0.24; 0 = off (DR 0004)
INC_FRAC = 8                     # the slewed increment carries 8 fraction bits, Q24.8
GLIDE_REF_S = 0.09               # reference host: 90 ms per octave (engines.mono_note's 90 ms glide)
LADDER_CFG = dict(state_bits=24, state_q=20, tanh_entries=16, interp=True, out_bits=LADDER_OUT_BITS)
INC_BITS = PHASE_BITS            # the increment register is as wide as the phase
WEIGHT_BITS = 16                 # Q0.15 mixer weight; 1.0 = 32768 needs the 16th bit
CUT_BITS = 16                    # cut_lo, cut_hi, track_hz: integer Hz (proposed width)
VOL_BITS = 16                    # vol: Q0.15 (DR 0005)

# Register widths of the control image, NUMERIC-CONTRACT.md 5.1. Each host
# conversion below clamps to the width named here; the sweep test walks them.
REG_BITS = dict(inc=INC_BITS, w=WEIGHT_BITS,
                a_inc=ENV_BITS, d_dec=ENV_BITS, sus=ENV_BITS, rate=RATE_Q,
                cut_lo=CUT_BITS, cut_hi=CUT_BITS, track_hz=CUT_BITS,
                k=LadderFx.K_BITS, gain=LadderFx.GAIN_BITS, ogain=LadderFx.GAIN_BITS,
                glide=GLIDE_BITS, vol=VOL_BITS)

_SINE = dsp._QUARTER.astype(np.int64)   # 256-entry quarter wave, midpoint-sampled


def sat16(v):
    return np.clip(v, -32768, 32767)


# ---- waveforms from a 24-bit phase, Q1.15 -----------------------------------
def sine_fx(ph: np.ndarray) -> np.ndarray:
    """Same table and symmetry as dsp.sine_from_phase, without the final /32768."""
    idx = (ph >> (PHASE_BITS - 10)) & 1023
    quad, i = idx >> 8, idx & 255
    q = np.where(quad & 1, _SINE[255 - i], _SINE[i])
    return np.where(quad & 2, -q, q)


def naive_fx(shape: str, ph: np.ndarray) -> np.ndarray:
    ph = np.asarray(ph, dtype=np.int64)
    if shape == "saw":
        return (ph >> (PHASE_BITS - 16)) - 32768
    if shape == "square":
        return np.where(ph < CYCLE // 2, 32767, -32768)
    if shape == "pulse25":
        return np.where(ph < CYCLE // 4, 32767, -32768)
    if shape == "tri":
        v = ph >> (PHASE_BITS - 17)                       # 0 .. 131071
        return np.where(v < 65536, v - 32768, 98303 - v)
    if shape == "sine":
        return sine_fx(ph)
    raise ValueError(shape)


# ---- PolyBLEP ---------------------------------------------------------------
def recip_of(inc: int, mant_bits: int = MANT_BITS, recip_bits: int = RECIP_BITS):
    """Note-on: inc = m * 2^e with m in [2^(MB-1), 2^MB). Returns (e, r) with
    r = floor(2^(RB+MB-1) / m), clamped to RB bits (only m = 2^(MB-1) hits the
    clamp, a 1-LSB error). One integer division per note-on.

    inc = 0 is a legal register value (it is the reset value, and any 24-bit
    write is accepted) and has no mantissa to divide by. It returns (0, 0),
    the reset value of the (e, r) state. Neither is observable: with inc = 0
    the phase never enters either PolyBLEP window, so `blep_fx` is identically
    zero whatever (e, r) hold, and the oscillator outputs the naive waveform
    at its stalled phase (DC)."""
    if inc == 0:
        return 0, 0
    e = inc.bit_length() - mant_bits
    m = shl(inc, -e)
    r = min((1 << (recip_bits + mant_bits - 1)) // m, (1 << recip_bits) - 1)
    return e, r


def frac_q16(x: np.ndarray, e, r, mant_bits: int = MANT_BITS, recip_bits: int = RECIP_BITS):
    """x / inc in Q0.16, for 0 <= x <= inc. `e` and `r` may be per-sample
    arrays (glide). ((x >> e) * r) >> (RB-1) = x * 2^MB / inc."""
    e = np.asarray(e); r = np.asarray(r)
    p = np.where(e >= 0, x >> np.maximum(e, 0), x << np.maximum(-e, 0))
    u = (p * r) >> (recip_bits - 1)
    u = np.minimum(u, (1 << mant_bits) - 1)
    return u << (16 - mant_bits) if mant_bits <= 16 else u >> (mant_bits - 16)


def blep_fx(ph: np.ndarray, inc, e, r, mant_bits=MANT_BITS, recip_bits=RECIP_BITS):
    """Correction to SUBTRACT from a naive saw at its wrap, Q1.15. Same sign
    convention as dsp._blep: -(1-t/dt)^2 just after the wrap, +(1-(1-t)/dt)^2
    just before it. `inc`, `e`, `r` scalar or per-sample."""
    inc = np.asarray(inc); e = np.asarray(e); r = np.asarray(r)
    c = np.zeros_like(ph)
    a = ph < inc
    if a.any():
        ea = e if e.ndim == 0 else e[a]; ra = r if r.ndim == 0 else r[a]
        s = 65536 - frac_q16(ph[a], ea, ra, mant_bits, recip_bits)      # 1 .. 65536
        c[a] = -((s * s) >> 17)                                          # -32768 .. 0
    q = CYCLE - ph
    b = q < inc
    if b.any():
        eb = e if e.ndim == 0 else e[b]; rb = r if r.ndim == 0 else r[b]
        s = 65536 - frac_q16(q[b], eb, rb, mant_bits, recip_bits)       # 1 .. 65535
        c[b] = (s * s) >> 17                                             # 0 .. 32767
    return c


class OscFx:
    """One oscillator: 24-bit phase accumulator, waveform, PolyBLEP on the
    discontinuous shapes. `inc` may be an int (held note) or an int array
    (glide); the reciprocal is then recomputed whenever inc changes -- an
    integer divide per changed sample, which in hardware is a sequential
    divider (24 clocks of the 256-clock frame) or a Newton step. The spec is
    the exact floor quotient either way."""

    def __init__(self, shape: str, blep: bool = True,
                 mant_bits: int = MANT_BITS, recip_bits: int = RECIP_BITS):
        self.set_shape(shape, blep)
        self.MB, self.RB = mant_bits, recip_bits
        self.phase = 0
        self.inc_tgt = 0                 # SET_INC's value: where the glide is going
        self.inc_acc = 0                 # the increment now, Q24.8 (contract 6.7)
        self._cache = {}

    def set_shape(self, shape: str, blep: bool = True):
        self.shape, self.blep = shape, blep and shape in ("saw", "square", "pulse25")

    def set_inc(self, v: int, jump: bool = False, glide: int = 0):
        """SET_INC k, v [, jump]: the target increment. The current increment
        follows at once when `jump` is set or the glide register is 0;
        otherwise the slew of 6.7 walks it there frame by frame."""
        self.inc_tgt = int(v)
        if jump or glide == 0:
            self.inc_acc = int(v) << INC_FRAC

    def slew(self, n: int, glide) -> np.ndarray:
        """The increment for each of the next n frames (DR 0004). Frame j uses
        inc_acc >> 8 as it stands at the start of the frame; at the end of the
        frame the accumulator moves toward the target by a fixed RATIO of
        itself -- a constant number of cents per frame, so a two-octave glide
        takes twice as long as a one-octave one and lands exactly:

            d       = max(1, (inc_acc * glide) >> 24)
            inc_acc = min(tgt, inc_acc + d)   if tgt > inc_acc
                    = max(tgt, inc_acc - d)   if tgt < inc_acc

        `glide` is the Q0.24 register (an int) or a per-frame array; 0 snaps
        to the target. The max(1, .) is the envelope's lesson: without it a
        small increment times a small rate truncates to no motion at all."""
        out = np.empty(n, dtype=np.int64)
        gl = np.broadcast_to(np.asarray(glide, dtype=np.int64), (n,))
        acc, tgt = self.inc_acc, self.inc_tgt << INC_FRAC
        for j in range(n):
            out[j] = acc >> INC_FRAC
            if acc != tgt:
                g = int(gl[j])
                if g == 0:
                    acc = tgt
                else:
                    d = max(1, (acc * g) >> GLIDE_BITS)
                    acc = min(tgt, acc + d) if tgt > acc else max(tgt, acc - d)
        self.inc_acc = acc
        return out

    def _er(self, inc: int):
        er = self._cache.get(inc)
        if er is None:
            er = self._cache[inc] = recip_of(inc, self.MB, self.RB)
        return er

    def render(self, n: int, inc) -> np.ndarray:
        """n samples, Q1.15 as int64. Phase is output before it is incremented."""
        if np.ndim(inc) == 0:
            inc = int(inc)
            ph = (self.phase + inc * np.arange(n, dtype=np.int64)) & PHASE_MASK
            self.phase = (self.phase + inc * n) & PHASE_MASK
            e, r = self._er(inc)
            inc_a = inc
        else:
            inc = np.asarray(inc, dtype=np.int64)
            assert len(inc) == n
            ph = (self.phase + np.concatenate([[0], np.cumsum(inc[:-1])])) & PHASE_MASK
            self.phase = int((self.phase + inc.sum()) & PHASE_MASK)
            er = np.array([self._er(int(v)) for v in inc], dtype=np.int64)
            e, r = er[:, 0], er[:, 1]
            inc_a = inc
        out = naive_fx(self.shape, ph)
        if not self.blep:
            return out
        if self.shape == "saw":
            return sat16(out - blep_fx(ph, inc_a, e, r, self.MB, self.RB))
        duty = CYCLE // 2 if self.shape == "square" else CYCLE // 4
        ph2 = (ph + (CYCLE - duty)) & PHASE_MASK
        return sat16(out + blep_fx(ph, inc_a, e, r, self.MB, self.RB)
                         - blep_fx(ph2, inc_a, e, r, self.MB, self.RB))


# ---- mixer ------------------------------------------------------------------
def mix_weights(mix, q: int = 15) -> list:
    """Q0.q weights, floor-normalised: for non-negative mix levels they sum
    to at most 1.0, so a normalised mixer cannot clip. Unnormalised weights
    are allowed and saturate. A mix that sums to zero (every oscillator off)
    has nothing to normalise by and gives every weight 0. Each weight is
    clamped to its q+1-bit register (16 bits at q = 15)."""
    tot = float(sum(mix))
    if tot <= 0.0:
        return [0] * len(mix)
    return [usat(int(math.floor(m / tot * (1 << q))), q + 1) for m in mix]


def mix_fx(signals, weights, q: int = 15) -> np.ndarray:
    """Sum of Q1.15 signals x Q0.q weights, >> q, saturated to Q1.15."""
    acc = np.zeros_like(signals[0], dtype=np.int64)
    for s, w in zip(signals, weights):
        acc += s * int(w)
    return sat16(acc >> q)


# ---- envelope ---------------------------------------------------------------
class AdsrFx:
    """Integer ADSR, mirroring dsp.adsr's segment shapes.

    Level L is ENV_BITS unsigned. Per frame the level is OUTPUT, then updated:
      attack   L += a_inc (ceil(2^EB / attack_frames)); clamps at full
      decay    L -= d_dec (ceil((full - sus) / decay_frames)); clamps at sus
      sustain  L = sus
      release  L -= max(1, (L * rate) >> RATE_Q); clamps at 0
    rate = round((1 - exp(-4 / (release_s * SR))) * 2^RATE_Q), min 1, so the
    exponential matches the float's exp(-4 t / release). The `env_bits`
    parameter exists to measure the dead zone, exactly as fixed.LadderFx's
    `state_q` does.

    Every register is clamped to its width (a_inc, d_dec, sus to env_bits;
    rate to rate_q bits). Two conversions reach the clamp: an attack shorter
    than two frames (< 41.67 us) gives a_inc = 2^24, clamped to 2^24 - 1,
    which still completes the attack in one update from any level; a release
    of 7.07 us or less (release_s <= 4 / (17 ln 2 * SR)), including 0, gives
    rate = 2^16 = 1.0, clamped to 65535, which releases full scale to zero in
    three updates instead of one. release_s <= 0 means instant, as the float
    model's max(1e-9, .) does; the model no longer divides by it."""
    ATTACK, DECAY, SUSTAIN = 0, 1, 2

    def __init__(self, a_s, d_s, sus, r_s, env_bits: int = ENV_BITS, rate_q: int = RATE_Q):
        self.EB, self.RQ = env_bits, rate_q
        self.full = (1 << env_bits) - 1
        self.level, self.seg = 0, self.ATTACK
        self.set(a_s, d_s, sus, r_s)

    @staticmethod
    def regs_from(a_s, d_s, sus, r_s, env_bits: int = ENV_BITS, rate_q: int = RATE_Q) -> tuple:
        """The host's conversion of seconds and a level to the four registers
        (contract 5.5): (a_inc, d_dec, sus, rate), each clamped to its width
        (see the class docstring for where the clamps fire). Float; host side."""
        full = (1 << env_bits) - 1
        a, d = max(1, int(a_s * SR)), max(1, int(d_s * SR))
        a_inc = usat(-(-(1 << env_bits) // a), env_bits)
        sus_r = usat(int(round(sus * full)), env_bits)
        d_dec = usat(-(-(full - sus_r) // d), env_bits)
        decay = math.exp(-4.0 / (r_s * SR)) if r_s > 0.0 else 0.0
        rate = max(1, usat(int(round((1.0 - decay) * (1 << rate_q))), rate_q))
        return a_inc, d_dec, sus_r, rate

    def set(self, a_s, d_s, sus, r_s):
        self.set_regs(*self.regs_from(a_s, d_s, sus, r_s, self.EB, self.RQ))

    def set_regs(self, a_inc: int, d_dec: int, sus: int, rate: int):
        """SET_ENV: the four registers. Level and segment are state, untouched."""
        self.a_inc, self.d_dec, self.sus, self.rate = int(a_inc), int(d_dec), int(sus), int(rate)

    def render(self, n: int, gate, trig=None, q: int = 15) -> np.ndarray:
        """n frames. `gate` is an int (on for the first `gate` frames, the
        single-note form) or a per-frame 0/1 array; `trig` a per-frame 0/1
        array of frames at whose START the segment is set to ATTACK with the
        level unchanged (GATE_ON and TRIG, DR 0003). Q0.q out (int64)."""
        out = np.empty(n, dtype=np.int64)
        if np.ndim(gate) == 0:
            gate_a = (np.arange(n) < int(gate)).astype(np.int64)
        else:
            gate_a = np.asarray(gate, dtype=np.int64)
        trig_a = None if trig is None else np.asarray(trig, dtype=np.int64)
        L, seg = self.level, self.seg
        full, sus, a_inc, d_dec, rate, RQ = (self.full, self.sus, self.a_inc,
                                             self.d_dec, self.rate, self.RQ)
        sh = self.EB - q
        for i in range(n):
            if trig_a is not None and trig_a[i]:
                seg = self.ATTACK
            out[i] = L >> sh
            if gate_a[i]:
                if seg == self.ATTACK:
                    L += a_inc
                    if L >= full:
                        L, seg = full, self.DECAY
                elif seg == self.DECAY:
                    L -= d_dec
                    if L <= sus:
                        L, seg = sus, self.SUSTAIN
                else:
                    L = sus
            else:
                dec = (L * rate) >> RQ
                L -= dec if dec else 1
                if L < 0:
                    L = 0
        self.level, self.seg = L, seg
        return out

    @property
    def floor_level(self) -> int:
        """Below this level the exponential step truncates to zero and the
        release continues at 1 LSB per frame (linear). 2^RQ / rate."""
        return (1 << self.RQ) // self.rate + 1


# ---- cutoff -> coefficient ROM ---------------------------------------------
def make_g_rom(bits: int = GROM_BITS, oversample: int = 2) -> np.ndarray:
    """2^bits + 1 entries of g = 1 - exp(-2*pi*f/fs) in Q0.16, EDGE-sampled at
    f = i * (32768 >> bits) Hz. fs is the ladder's oversampled rate. The +1 is
    the interpolation guard entry."""
    fs = SR * oversample
    step = (1 << 15) >> bits
    f = np.arange((1 << bits) + 1) * step
    return np.clip(np.round((1.0 - np.exp(-2.0 * math.pi * f / fs)) * 65536), 0, 65535).astype(np.int64)


def g_from_cut(cut_hz: np.ndarray, rom: np.ndarray, bits: int = GROM_BITS) -> np.ndarray:
    """Q0.16 coefficient from integer Hz, linear interpolation between entries."""
    cut = np.asarray(cut_hz, dtype=np.int64)
    fb = 15 - bits
    i = cut >> fb
    frac = cut & ((1 << fb) - 1)
    return rom[i] + (((rom[i + 1] - rom[i]) * frac) >> fb)


# ---- cutoff -> resonance compensation ROM (DR 0006) -------------------------
def tanh_bin0_slope(ladder_cfg: dict = None) -> float:
    """Slope of the ladder's interpolated tanh table in its first bin, in
    state units: the small-signal gain every stage sees. TANH16[1] / 2^13 for
    the 16-entry table over [0, 4): 8025 / 8192 = 0.9796."""
    cfg = dict(LADDER_CFG if ladder_cfg is None else ladder_cfg)
    tbl = LadderFx(**cfg).tbl
    n = len(tbl)
    return tbl[1] / (32768.0 * fixed.TANH_DOMAIN / n)


def k_onset(cut_hz: int, g_rom: np.ndarray = None, bits: int = GROM_BITS,
            oversample: int = 2, slope: float = None):
    """Small-signal onset of self-oscillation at one integer cutoff, from the
    linearised loop the fixed-point ladder is inside its tanh table's first
    bin: four one-poles H1 = G / (1 - (1-G) z^-1) with G = g(cut)/2^16 * s0
    (g from the g ROM as the hardware reads it, s0 the bin-0 tanh slope), and
    the half-sample feedback delay Hfb = (z^-1 + z^-2)/2, at the oversampled
    rate. The loop gain is k * H1^4 * Hfb; oscillation starts where its phase
    is -180 degrees and its magnitude 1. Returns (k, f_osc_hz): the k at
    which the loop gain is exactly 1 there, and the frequency it oscillates
    at. Float, for ROM building and measurement only.

    phase(H1) = -atan2((1-G) sin w, 1 - (1-G) cos w), phase(Hfb) = -1.5 w:
    the total is continuous and decreasing from 0 at w = 0 to below -pi at
    w = pi, so one bisection finds the crossing."""
    rom = make_g_rom(bits, oversample) if g_rom is None else g_rom
    s0 = tanh_bin0_slope() if slope is None else slope
    g = int(g_from_cut(np.array([cut_hz]), rom, bits)[0])
    G = g / 65536.0 * s0
    a = 1.0 - G
    fs = SR * oversample

    def phase(w):
        return -4.0 * math.atan2(a * math.sin(w), 1.0 - a * math.cos(w)) - 1.5 * w
    lo, hi = 0.0, math.pi
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if phase(mid) > -math.pi:
            lo = mid
        else:
            hi = mid
    w = 0.5 * (lo + hi)
    h1 = G / abs(1.0 - a * complex(math.cos(w), -math.sin(w)))
    mag = h1 ** 4 * abs(math.cos(0.5 * w))
    return 1.0 / mag, w * fs / (2.0 * math.pi)


def make_k_rom(bits: int = KROM_BITS, g_bits: int = GROM_BITS, oversample: int = 2) -> np.ndarray:
    """2^bits + 1 entries of k_onset(cut) / 4 in unsigned Q1.15, EDGE-sampled
    at cut = i * (32768 >> bits) Hz, with the guard entry. Read by
    kc_from_cut with the same interpolation as the g ROM. 1.0 (32768) means
    'k = 4 * res', the uncompensated filter; the table is 1.001 at 30 Hz and
    peaks at 1.216 near 11 kHz. Each entry is evaluated at its cutoff clamped
    to [CUT_MIN, CUT_MAX]: entry 0 at 30 Hz because g(0) = 0 has no resonance
    at all, and the entries above 21600 Hz (never read) at the clamp."""
    rom = make_g_rom(g_bits, oversample)
    step = (1 << 15) >> bits
    out = []
    for i in range((1 << bits) + 1):
        cut = min(max(CUT_MIN, i * step), CUT_MAX)
        k, _ = k_onset(cut, rom, g_bits, oversample)
        out.append(int(round(k / 4.0 * 32768)))
    return np.array(out, dtype=np.int64)


def kc_from_cut(cut_hz: np.ndarray, rom: np.ndarray, bits: int = KROM_BITS) -> np.ndarray:
    """Q1.15 resonance compensation from integer Hz, linear interpolation
    between entries: the g ROM's read, with fewer index bits."""
    return g_from_cut(cut_hz, rom, bits)


def k_effective(k_q14, kc_q15) -> np.ndarray:
    """The k the ladder runs on this frame: (k * kc) >> 15, saturated to the
    ladder's 17-bit port (8.0 in Q3.14). k is the host's 4*res in Q3.14; kc
    is the ROM's Q1.15 factor for this frame's cutoff."""
    k_q14 = np.asarray(k_q14, dtype=np.int64); kc_q15 = np.asarray(kc_q15, dtype=np.int64)
    return np.minimum((k_q14 * kc_q15) >> 15, (1 << K_BITS) - 1)


# ---- the voice --------------------------------------------------------------
class VoiceFx:
    """One voice: three oscillators, two envelopes, one ladder, and the state
    they keep between notes. `play` is the per-frame contract; `note` renders
    one note from reset (contract 16's reference sequences); `KeyHost` below
    is the reference host that turns key events into control writes."""

    def __init__(self, blep: bool = True, mant_bits: int = MANT_BITS,
                 recip_bits: int = RECIP_BITS, env_bits: int = ENV_BITS,
                 grom_bits: int = GROM_BITS, krom_bits: int = KROM_BITS,
                 ladder_cfg: dict = None, g_exact: bool = False, k_comp: bool = True):
        """`g_exact=True` bypasses the ROM and lets LadderFx compute g from Hz in
        float. NOT integer -- exists only to measure what the ROM costs.
        `k_comp=False` runs the ladder on the host's k with no compensation,
        rev 1's behaviour -- exists only to measure what DR 0006 changes."""
        self.blep, self.MB, self.RB = blep, mant_bits, recip_bits
        self.EB, self.GB, self.KB = env_bits, grom_bits, krom_bits
        self.ladder_cfg = dict(LADDER_CFG if ladder_cfg is None else ladder_cfg)
        self.g_exact, self.k_comp = g_exact, k_comp
        self.g_rom = make_g_rom(grom_bits, self.ladder_cfg.get("oversample", 2))
        self.k_rom = make_k_rom(krom_bits, grom_bits, self.ladder_cfg.get("oversample", 2))
        self.trace = {}
        self.reset()

    def reset(self):
        """RESET: every state register of contract 14 to zero."""
        self.oscs = [OscFx("saw", self.blep, self.MB, self.RB) for _ in range(3)]
        self.amp_env = AdsrFx(0.005, 0.25, 0.75, 0.12, env_bits=self.EB)
        self.filt_env = AdsrFx(0.004, 0.30, 0.25, 0.10, env_bits=self.EB)
        self.ladder = LadderFx(**self.ladder_cfg)
        self.track_hz, self.gate, self.glide = 0, 0, 0
        for o in self.oscs:
            o.phase = o.inc_tgt = o.inc_acc = 0

    # ---- host-side conversions (contract 5.5): float in, registers out ----
    @staticmethod
    def patch_regs(*, waves=("saw", "saw", "square"), detune=(0.0, 0.07, -12.0),
                   mix=(1.0, 0.8, 0.5), cutoff=(400, 4000), q=0.62, drive=1.6,
                   amp=(0.005, 0.25, 0.75, 0.12), fenv=(0.004, 0.30, 0.25, 0.10),
                   track=0.35, vol=None, glide_s=GLIDE_REF_S, **_ignored) -> dict:
        """The patch's physical units as the control image, less the per-note
        registers (inc, track_hz, gate). Same names and defaults as
        engines.mono_note. `vol` in 0..1 (reference 0.45); `glide_s` is the
        time per octave at the constant-rate glide of DR 0004."""
        waves = tuple(waves) + ("saw",) * (3 - len(waves))     # a patch with fewer than
        detune = tuple(detune) + (0.0,) * (3 - len(detune))      # three oscillators leaves
        weights = mix_weights(mix) + [0] * (3 - len(mix))        # the rest silent: w = 0
        k, gain, ogain = LadderFx(**LADDER_CFG).regs(q, drive)     # clamped to 17 / 20 / 20 bits
        return dict(waves=waves, detune=detune, weights=weights,
                    cut_lo=usat(int(round(cutoff[0])), CUT_BITS),
                    cut_hi=usat(int(round(cutoff[1])), CUT_BITS),
                    res=q, drive=drive, k=k, gain=gain, ogain=ogain,
                    amp=AdsrFx.regs_from(*amp), fenv=AdsrFx.regs_from(*fenv), track=track,
                    vol=VOL_REF if vol is None else usat(int(round(vol * 32768)), VOL_BITS),
                    glide=glide_reg(glide_s))

    @staticmethod
    def note_incs(note, detune) -> list:
        """inc[k] for a note at each oscillator's detune (contract 6.3),
        clamped to the 24-bit register (it fires only at or above 48 kHz)."""
        f0 = note_hz(note)
        return [usat(phase_inc(f0 * 2.0 ** (dt / 12.0)), INC_BITS) for dt in detune]

    @staticmethod
    def note_track(note, track) -> int:
        return usat(int(round(track * note_hz(note) * 4.0)), CUT_BITS)

    # ---- the per-frame contract --------------------------------------------
    def play(self, regs: dict, writes: list, n: int) -> np.ndarray:
        """n frames of the voice from its current state, with `writes` --
        (frame, op, *args) -- applied at the start of their frames in list
        order (contract 4.3). Ops: ("INC", k, v, jump), ("TRACK", hz),
        ("GATE", 0|1), ("TRIG",), ("GLIDE", v). The patch registers in `regs`
        are applied at frame 0. Returns int16."""
        self._apply_patch(regs)
        ev = {}
        for w in writes:
            f = int(w[0])
            assert 0 <= f < n, f"write {w} outside 0..{n-1}"
            ev.setdefault(f, []).append(w[1:])
        frames = sorted(ev)
        incs = [np.empty(n, dtype=np.int64) for _ in self.oscs]
        track = np.empty(n, dtype=np.int64)
        gate = np.empty(n, dtype=np.int64)
        trig = np.zeros(n, dtype=np.int64)
        glide = np.empty(n, dtype=np.int64)
        bounds = [0] + [f for f in frames if f > 0] + [n]
        for f0, f1 in zip(bounds, bounds[1:]):
            for op, *args in ev.get(f0, []):            # step 1: apply control, in order
                if op == "INC":
                    k, v, jump = args[0], args[1], (args[2] if len(args) > 2 else False)
                    self.oscs[k].set_inc(v, jump, self.glide)
                elif op == "TRACK":
                    self.track_hz = int(args[0])
                elif op == "GATE":
                    self.gate = int(args[0])
                    if self.gate:
                        trig[f0] = 1                     # GATE_ON restarts the attack
                elif op == "TRIG":
                    trig[f0] = 1
                elif op == "GLIDE":
                    self.glide = int(args[0])
                else:
                    raise ValueError(op)
            m = f1 - f0
            for o, arr in zip(self.oscs, incs):
                arr[f0:f1] = o.slew(m, self.glide)
            track[f0:f1] = self.track_hz
            gate[f0:f1] = self.gate
            glide[f0:f1] = self.glide
        return self._render(incs, track, gate, trig, n)

    def _apply_patch(self, r: dict):
        for o, shape in zip(self.oscs, r["waves"]):
            o.set_shape(shape, self.blep)
        self.weights = list(r["weights"])
        self.amp_env.set_regs(*r["amp"]); self.filt_env.set_regs(*r["fenv"])
        self.cut_lo, self.cut_hi = int(r["cut_lo"]), int(r["cut_hi"])
        self.res, self.drive = r["res"], r["drive"]
        self.k_reg, self.gain, self.ogain = int(r["k"]), int(r["gain"]), int(r["ogain"])
        self.vol = int(r["vol"])
        self.glide = int(r["glide"])
        self.regs = r

    def _render(self, incs, track, gate, trig, n) -> np.ndarray:
        """Steps 2..8 of contract 4.2 for n frames, vectorised. Integer only."""
        sig = [o.render(n, inc) for o, inc in zip(self.oscs, incs)]
        mixed = mix_fx(sig, self.weights)                        # step 3
        ae = self.amp_env.render(n, gate, trig)                  # step 4
        fe = self.filt_env.render(n, gate, trig)
        span = self.cut_hi - self.cut_lo                         # step 5: cutoff
        cut = np.clip(self.cut_lo + ((span * fe) >> 15) + track, CUT_MIN, CUT_MAX)
        lad = self.ladder
        kc = kc_from_cut(cut, self.k_rom, self.KB)
        k_eff = k_effective(self.k_reg, kc) if self.k_comp else np.full(n, self.k_reg, dtype=np.int64)
        regs = dict(k=self.k_reg, gain=self.gain, ogain=self.ogain, k_q14=k_eff)
        if self.g_exact:   # measurement only: float exp inside LadderFx
            y = lad.process(mixed.astype(np.int16), cut.astype(np.float64), self.res, self.drive, **regs)
            g = None
        else:                                                    # step 6: ladder
            g = g_from_cut(cut, self.g_rom, self.GB)
            y = lad.process(mixed.astype(np.int16), None, self.res, self.drive, g_q16=g, **regs)
        y = y.astype(np.int64)
        v = (y * ae) >> 15                                       # step 7: VCA, after the filter
        out = sat16((v * self.vol) >> 15)                        # step 8: volume, the one output clamp
        self.trace = dict(osc=sig, mixed=mixed, amp_env=ae, filt_env=fe, cut=cut, g=g,
                          kc=kc, k_eff=k_eff, ladder=y, vca=v, incs=incs, gate=gate, trig=trig)
        return out.astype(np.int16)

    # ---- one note from reset: the reference sequences of contract 16 --------
    def note_on(self, note, dur, *, gate=None, glide_from=None, **patch) -> dict:
        """Register image and writes for one note of `dur` seconds, the gate
        on for `gate` seconds (default 0.8 dur). `glide_from`: the increment
        starts at that note's and glides. Same patch keywords as
        engines.mono_note plus `vol` and `glide_s`."""
        n = int(dur * SR)
        gate = dur * 0.8 if gate is None else gate
        gate_n = min(n, max(1, int(gate * SR)))
        regs = self.patch_regs(**patch)
        writes = []
        if glide_from is not None:
            for k, v in enumerate(self.note_incs(glide_from, regs["detune"])):
                writes.append((0, "INC", k, v, True))
            for k, v in enumerate(self.note_incs(note, regs["detune"])):
                writes.append((0, "INC", k, v, False))
        else:
            for k, v in enumerate(self.note_incs(note, regs["detune"])):
                writes.append((0, "INC", k, v, True))
        writes.append((0, "TRACK", self.note_track(note, regs["track"])))
        writes.append((0, "GATE", 1))
        if gate_n < n:
            writes.append((gate_n, "GATE", 0))
        return dict(n=n, gate_n=gate_n, regs=regs, writes=writes)

    def run(self, r: dict) -> np.ndarray:
        return self.play(r["regs"], r["writes"], r["n"])

    def note(self, note, dur, **kw) -> np.ndarray:
        self.reset()
        return self.run(self.note_on(note, dur, **kw))


def glide_reg(seconds_per_octave: float) -> int:
    """Host conversion for the glide register (DR 0004): the Q0.24 ratio per
    frame that covers one octave in `seconds_per_octave`; 0 for off."""
    if not seconds_per_octave or seconds_per_octave <= 0:
        return 0
    return usat(max(1, int(round((2.0 ** (1.0 / (seconds_per_octave * SR)) - 1.0) * (1 << GLIDE_BITS)))),
                GLIDE_BITS)


# ---- the reference host ------------------------------------------------------
class KeyHost:
    """Turns key events into the voice's control writes. This is the host
    firmware's job in the product (DR 0002) and is INFORMATIVE in the
    contract; the policies are parameters so that DR 0003 / 0004 can state
    a default and keep the alternatives measurable.

      priority  'last' | 'low' | 'high'   which held key sounds (mono)
      trigger   'single' | 'multi'        TRIG on every new key while one is
                                          held (multi) or only when no key
                                          was held (single: legato)
      glide     'off' | 'always' | 'legato'
                                          slew never / on every new pitch /
                                          only when a key was already held
      mode      'mono' | 'para'           para: held keys go to oscillators
                                          0..2 in press order, the rest
                                          double the newest key
    """
    def __init__(self, priority="last", trigger="single", glide="always", mode="mono"):
        assert priority in ("last", "low", "high") and trigger in ("single", "multi")
        assert glide in ("off", "always", "legato") and mode in ("mono", "para")
        self.priority, self.trigger, self.glide, self.mode = priority, trigger, glide, mode

    def sounding(self, held: list) -> list:
        """Which note each oscillator plays, from the held list (press order)."""
        if self.mode == "para":
            if not held:
                return None
            return [held[i] if i < len(held) else held[-1] for i in range(3)]
        if not held:
            return None
        n = {"last": held[-1], "low": min(held), "high": max(held)}[self.priority]
        return [n, n, n]

    def writes(self, events: list, regs: dict, first_from_reset: bool = True) -> list:
        """events: (frame, 'on'|'off', note), any order. Returns the write list
        for VoiceFx.play. From reset the first pitch is always a jump: there
        is no previous pitch to glide from."""
        held, out, prev = [], [], None
        cur = None                                           # per-osc notes sounding
        for f, kind, note in sorted(events, key=lambda e: (e[0], e[1] == "on")):
            was_held = bool(held)
            if kind == "on":
                if note in held:
                    held.remove(note)
                held.append(note)
            else:
                if note not in held:
                    continue
                held.remove(note)
            new = self.sounding(held)
            if new is None:                                  # last key up
                out.append((f, "GATE", 0))
                cur = None
                continue
            if new != cur:
                jump = (self.glide == "off") or (self.glide == "legato" and not was_held) \
                       or (prev is None and first_from_reset)
                for k, (nt, dt) in enumerate(zip(new, regs["detune"])):
                    if cur is None or nt != cur[k] or jump:
                        out.append((f, "INC", k, phase_inc(note_hz(nt) * 2.0 ** (dt / 12.0)), jump))
                lead = new[-1] if self.mode == "para" else new[0]
                out.append((f, "TRACK", VoiceFx.note_track(lead, regs["track"])))
                cur = new
                prev = lead
            if kind == "on":
                if not was_held:
                    out.append((f, "GATE", 1))               # GATE_ON restarts the attack
                elif self.trigger == "multi":
                    out.append((f, "TRIG",))
        return out


def render_mono_fx(seq, dur_total, voice: VoiceFx = None, host: KeyHost = None) -> np.ndarray:
    """engines.render_mono's sequence format -- (start_s, note, dur_s, kwargs),
    the gate on for kwargs['gate'] or 0.8 dur -- through ONE continuous voice
    from reset, the reference host turning it into writes. A note's `glide`
    flag selects the host's 'always' glide; the patch is the first note's
    kwargs (one patch per sequence). int16 out."""
    voice = VoiceFx() if voice is None else voice
    n = int(dur_total * SR)
    kw0 = dict(seq[0][3]); kw0.pop("blep", None)
    glide_on = bool(kw0.pop("glide", False))
    kw0.pop("gate", None)
    regs = VoiceFx.patch_regs(**kw0)
    host = KeyHost(glide="always" if glide_on else "off") if host is None else host
    events = []
    for start, note, d, kw in seq:
        g = kw.get("gate", None)
        g = d * 0.8 if g is None else g
        on = int(start * SR)
        off = min(n - 1, on + max(1, int(g * SR)))
        if on < n:
            events.append((on, "on", note)); events.append((off, "off", note))
    voice.reset()
    return voice.play(regs, host.writes(events, regs), n)
