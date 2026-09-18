"""Fully integer monophonic voice: oscillators, PolyBLEP, mixer, envelopes and
the cutoff-coefficient path, in front of `fixed.LadderFx`. No float anywhere in
the per-sample signal path, so that RTL can be bit-exact against it.

This closes the gap `fixed_render.py` describes: the ladder was integer, but the
oscillators and envelopes were float, quantised to Q1.15 at the filter input.

Signal chain (the order is `engines.mono_note`'s, which is the auditioned one):

    3 x (phase accumulator -> waveform -> PolyBLEP)   Q1.15
      -> mixer (Q0.15 weights, saturating)            Q1.15
      -> x amplitude ADSR                             Q1.15   (BEFORE the filter)
      -> ladder, g from the cutoff ADSR via a ROM     Q1.15   (hard-saturated output)
      -> x 0.9 master gain                            Q1.15

Where float is still allowed -- and this is the only place: computing NOTE-ON
REGISTER VALUES and ROM CONTENTS from the patch's physical units. Hz -> phase
increment (`dsp.phase_inc`), seconds -> envelope rate, the tanh/sine/g tables.
In hardware those are the host's job or a ROM's; the same convention `fixed.py`
already uses for its coefficient. Everything evaluated per sample is integer.

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
    cutoff          integer Hz, 15 bits, clamped to [30, 21600]
    g ROM           128 entries x Q0.16, edge-sampled every 256 Hz, linearly
                    interpolated on the low 8 bits of the cutoff (same read
                    convention as the tanh table)
    ladder          fixed.LadderFx: 24-bit state, 20 fraction bits, 16-entry
                    interpolated tanh. Its output is HARD-SATURATED to Q1.15;
                    that is where four of the eight patches clip.

What this does NOT decide: note-on retrigger semantics. Like the float
harness, `render_mono_fx` renders each note independently and sums the
overlaps; a hardware voice is one state machine that retriggers. Legato,
envelope restart-from-current-level and phase reset are design decisions that
belong in a decision record, and neither model makes them yet.
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
from fixed import LadderFx, sat, shl

CYCLE = 1 << PHASE_BITS
ENV_BITS = 24
RATE_Q = 16
MANT_BITS = 16
RECIP_BITS = 16
GROM_BITS = 7                    # 128-entry cutoff -> g ROM
CUT_MIN, CUT_MAX = 30, 21600     # Hz; the float model clips to [30, 0.45*SR]
OUT_GAIN = 29491                 # 0.9 in Q0.15, engines.mono_note's master gain
GLIDE_SAMPLES = int(0.09 * SR)   # engines.mono_note's portamento time
LADDER_CFG = dict(state_bits=24, state_q=20, tanh_entries=16, interp=True)

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
    clamp, a 1-LSB error). One integer division per note-on."""
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
        self.shape, self.blep = shape, blep and shape in ("saw", "square", "pulse25")
        self.MB, self.RB = mant_bits, recip_bits
        self.phase = 0
        self._cache = {}

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
    """Q0.q weights, floor-normalised: they sum to at most 1.0, so a normalised
    mixer cannot clip. Unnormalised weights are allowed and saturate."""
    tot = float(sum(mix))
    return [int(math.floor(m / tot * (1 << q))) for m in mix]


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
    `state_q` does."""
    ATTACK, DECAY, SUSTAIN = 0, 1, 2

    def __init__(self, a_s, d_s, sus, r_s, env_bits: int = ENV_BITS, rate_q: int = RATE_Q):
        self.EB, self.RQ = env_bits, rate_q
        self.full = (1 << env_bits) - 1
        a, d = max(1, int(a_s * SR)), max(1, int(d_s * SR))
        self.a_inc = -(-(1 << env_bits) // a)
        self.sus = int(round(sus * self.full))
        self.d_dec = -(-(self.full - self.sus) // d)
        self.rate = max(1, int(round((1.0 - math.exp(-4.0 / (r_s * SR))) * (1 << rate_q))))
        self.level, self.seg = 0, self.ATTACK

    def render(self, n: int, gate_n: int, q: int = 15) -> np.ndarray:
        """n frames with the gate on for the first gate_n. Q0.q out (int64)."""
        out = np.empty(n, dtype=np.int64)
        L, seg = self.level, self.seg
        full, sus, a_inc, d_dec, rate, RQ = (self.full, self.sus, self.a_inc,
                                             self.d_dec, self.rate, self.RQ)
        sh = self.EB - q
        for i in range(n):
            out[i] = L >> sh
            if i < gate_n:
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


# ---- the voice --------------------------------------------------------------
class VoiceFx:
    def __init__(self, blep: bool = True, mant_bits: int = MANT_BITS,
                 recip_bits: int = RECIP_BITS, env_bits: int = ENV_BITS,
                 grom_bits: int = GROM_BITS, ladder_cfg: dict = None,
                 g_exact: bool = False):
        """`g_exact=True` bypasses the ROM and lets LadderFx compute g from Hz in
        float. NOT integer -- exists only to measure what the ROM costs."""
        self.blep, self.MB, self.RB = blep, mant_bits, recip_bits
        self.EB, self.GB = env_bits, grom_bits
        self.ladder_cfg = dict(LADDER_CFG if ladder_cfg is None else ladder_cfg)
        self.g_exact = g_exact
        self.g_rom = make_g_rom(grom_bits, self.ladder_cfg.get("oversample", 2))
        self.trace = {}

    def note_on(self, note, dur, *, gate=None, waves=("saw", "saw", "square"),
                detune=(0.0, 0.07, -12.0), mix=(1.0, 0.8, 0.5),
                cutoff=(400, 4000), q=0.62, drive=1.6,
                amp=(0.005, 0.25, 0.75, 0.12), fenv=(0.004, 0.30, 0.25, 0.10),
                track=0.35, glide_from=None) -> dict:
        """Same signature and defaults as engines.mono_note. Turns the patch's
        physical units into REGISTER VALUES: the one place float is allowed.
        In hardware this is the host's job."""
        n = int(dur * SR)
        gate = dur * 0.8 if gate is None else gate
        gate_n = min(n, max(1, int(gate * SR)))
        f0 = note_hz(note)
        incs = []
        for dt in detune:
            f = f0 * 2.0 ** (dt / 12.0)
            if glide_from is None:
                incs.append(phase_inc(f))
            else:
                # Linear slew of the increment over GLIDE_SAMPLES frames, in a
                # Q24.8 accumulator. The float model glides GEOMETRICALLY (a
                # constant ratio per frame); this is a different curve for the
                # 90 ms of the glide and identical after it. See the PR.
                i0 = phase_inc(note_hz(glide_from) * 2.0 ** (dt / 12.0))
                i1 = phase_inc(f)
                gl = min(n, GLIDE_SAMPLES)
                step = ((i1 - i0) << 8) // gl
                seq = np.full(n, i1, dtype=np.int64)
                seq[:gl] = (i0 * 256 + step * np.arange(gl, dtype=np.int64)) >> 8
                incs.append(seq)
        return dict(
            n=n, gate_n=gate_n,
            oscs=[OscFx(s, self.blep, self.MB, self.RB) for s in waves],
            incs=incs, weights=mix_weights(mix),
            amp_env=AdsrFx(*amp, env_bits=self.EB),
            filt_env=AdsrFx(*fenv, env_bits=self.EB),
            cut_lo=int(round(cutoff[0])), cut_hi=int(round(cutoff[1])),
            track_hz=int(round(track * f0 * 4.0)),
            ladder=LadderFx(**self.ladder_cfg), res=q, drive=drive)

    def run(self, r: dict) -> np.ndarray:
        """The per-sample signal path. Integer only. Returns int16."""
        n, gate_n = r["n"], r["gate_n"]
        sig = [o.render(n, inc) for o, inc in zip(r["oscs"], r["incs"])]
        mixed = mix_fx(sig, r["weights"])
        ae = r["amp_env"].render(n, gate_n)
        fe = r["filt_env"].render(n, gate_n)
        x = (mixed * ae) >> 15                                   # Q1.15, cannot overflow
        span = r["cut_hi"] - r["cut_lo"]
        cut = np.clip(r["cut_lo"] + ((span * fe) >> 15) + r["track_hz"], CUT_MIN, CUT_MAX)
        lad = r["ladder"]
        if self.g_exact:   # measurement only: float exp inside LadderFx
            y = lad.process(x.astype(np.int16), cut.astype(np.float64), r["res"], r["drive"])
        else:
            g = g_from_cut(cut, self.g_rom, self.GB)
            y = lad.process(x.astype(np.int16), None, r["res"], r["drive"], g_q16=g)
        out = (y.astype(np.int64) * OUT_GAIN) >> 15
        self.trace = dict(osc=sig, mixed=mixed, amp_env=ae, filt_env=fe, cut=cut,
                          ladder=y.astype(np.int64), incs=r["incs"])
        return out.astype(np.int16)

    def note(self, note, dur, **kw) -> np.ndarray:
        return self.run(self.note_on(note, dur, **kw))


def render_mono_fx(seq, dur_total, voice: VoiceFx = None) -> np.ndarray:
    """engines.render_mono's harness on the integer voice: notes rendered
    independently, overlaps summed with saturation. int16 out."""
    voice = VoiceFx() if voice is None else voice
    out = np.zeros(int(dur_total * SR), dtype=np.int64)
    prev = None
    for start, note, d, kw in seq:
        kw = dict(kw)
        kw.pop("blep", None)            # the float voice's flag; here it is a VoiceFx option
        if kw.pop("glide", False) and prev is not None:
            kw["glide_from"] = prev
        v = voice.note(note, d, **kw)
        i = int(start * SR)
        j = min(len(out), i + len(v))
        out[i:j] += v[:j - i]
        prev = note
    return sat16(out).astype(np.int16)
