"""Shared primitives for the audition engines.

Deliberately silicon-shaped, even though this is float-first Python:
integer phase accumulators, a fixed 256-entry quarter-sine table, an LFSR for
noise, no unbounded memory anywhere. The point of an audition model is to let
you choose an ARCHITECTURE by ear; a model that quietly uses resources the
chip cannot have is auditioning something we could not build.

What this does NOT model: fixed-point word growth, saturation behaviour, or
coefficient quantisation. Those change the sound, sometimes a lot (a ladder
filter's resonance is sensitive to coefficient precision). They are the first
thing to pin down AFTER an architecture wins, not before.
"""
from __future__ import annotations
import math
import numpy as np

SR = 48_000
PHASE_BITS = 24
PHASE_MASK = (1 << PHASE_BITS) - 1

# ---- fixed sine table: 256-entry quarter wave, the shape already in the contract
_QUARTER = np.array([int(round(32767 * math.sin(math.pi / 2 * (i + 0.5) / 256)))
                     for i in range(256)], dtype=np.int32)

def sine_from_phase(ph: np.ndarray) -> np.ndarray:
    """Full sine from a 24-bit phase, via the quarter table + symmetry."""
    idx = (ph >> (PHASE_BITS - 10)) & 1023          # 10-bit index into full cycle
    quad, i = idx >> 8, idx & 255
    q = np.where(quad & 1, _QUARTER[255 - i], _QUARTER[i])
    return np.where(quad & 2, -q, q).astype(np.float64) / 32768.0

def phase_inc(freq_hz: float) -> int:
    return int(round(freq_hz * (1 << PHASE_BITS) / SR))

def ramp(n: int, inc: int, start: int = 0) -> np.ndarray:
    """n samples of a free-running 24-bit phase accumulator."""
    return (start + inc * np.arange(n, dtype=np.int64)) & PHASE_MASK

def note_hz(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)

# ---- oscillator shapes from an integer phase -------------------------------
def osc(shape: str, ph: np.ndarray) -> np.ndarray:
    u = ph.astype(np.float64) / (1 << PHASE_BITS)        # 0..1
    if shape == "saw":    return 2.0 * u - 1.0
    if shape == "square": return np.where(u < 0.5, 1.0, -1.0)
    if shape == "tri":    return np.where(u < 0.5, 4.0 * u - 1.0, 3.0 - 4.0 * u)
    if shape == "sine":   return sine_from_phase(ph)
    if shape == "pulse25":return np.where(u < 0.25, 1.0, -1.0)
    raise ValueError(shape)

# ---- LFSR noise: a 16-bit maximal-length shift register, cheap in silicon ---
def lfsr_noise(n: int, seed: int = 0xACE1) -> np.ndarray:
    out = np.empty(n, dtype=np.float64)
    s = seed
    for i in range(n):
        bit = ((s >> 0) ^ (s >> 2) ^ (s >> 3) ^ (s >> 5)) & 1
        s = (s >> 1) | (bit << 15)
        out[i] = (s & 0xFF) / 127.5 - 1.0
    return out

# ---- envelopes -------------------------------------------------------------
def ad_env(n: int, attack_s: float, decay_s: float, curve: float = 3.0) -> np.ndarray:
    """Percussive attack/decay. Exponential decay, which is what an integer
    'subtract a fraction each frame' does in hardware."""
    a = max(1, int(attack_s * SR))
    e = np.empty(n)
    e[:a] = np.linspace(0.0, 1.0, a, endpoint=False)[:n]
    if n > a:
        t = np.arange(n - a) / max(1e-9, decay_s * SR)
        e[a:] = np.exp(-curve * t)
    return e

def adsr(n: int, a_s: float, d_s: float, sus: float, r_s: float, gate_s: float) -> np.ndarray:
    a, d = max(1, int(a_s * SR)), max(1, int(d_s * SR))
    g = min(n, max(1, int(gate_s * SR)))
    e = np.zeros(n)
    seg = np.linspace(0, 1, a, endpoint=False)
    e[:min(a, g)] = seg[:min(a, g)]
    if g > a:
        t = np.arange(min(d, g - a)) / d
        e[a:a + len(t)] = 1.0 + (sus - 1.0) * t
        if g > a + d:
            e[a + d:g] = sus
    tail = n - g
    if tail > 0:
        e[g:] = e[g - 1] * np.exp(-4.0 * np.arange(tail) / max(1e-9, r_s * SR))
    return e

# ---- the Minimoog-shaped part: Huovilainen's nonlinear ladder -------------
#
# Antti Huovilainen, "Non-Linear Digital Implementation of the Moog Ladder
# Filter", DAFx-04, Naples. https://www.dafx.de/paper-archive/2004/P_061.PDF
#
# The structure that matters, and the reason a one-tanh filter sounds wrong:
# the nonlinearity is in EVERY stage, not only the feedback path. Each stage is
# a transistor differential pair, and the paper's equation (22) for one stage is
#
#     y(n) = y(n-1) + 2*Vt*g*( tanh(x(n)/(2*Vt)) - tanh(y(n-1)/(2*Vt)) )
#
# Equation (17) is the cascade's saving: each stage takes as input the tanh of
# the PREVIOUS stage's output, and that same value is what the previous stage
# needs next sample. Store it and the whole 4-pole filter costs FIVE tanh per
# sample, not eight -- the paper's own count. It adds that these "can be
# implemented efficiently with table lookups or polynomial approximations",
# which is why `tanh_impl` below is a parameter you can audition rather than a
# detail: it is the filter's dominant silicon cost.
#
# Two more things from the paper, both audible:
#   - The unit delay in the feedback path adds phase shift (eq 23), moving the
#     resonant peak off the cutoff. The fix is a half-unit delay, "realized by
#     averaging two samples" -- so the feedback tap is (y[n-1] + y[n-2]) / 2.
#   - "Some oversampling is required to avoid aliasing" because of the
#     nonlinearities; the paper runs 2x (88.2 kHz). Oversampling also brings the
#     resonant frequency back onto the cutoff, "requiring only modest tuning and
#     resonance gain compensation".
VT = 0.025            # transistor thermal voltage, volts; the paper scales by 2*Vt


def _make_tanh(impl: str):
    """Return (f, description). Silicon-honest choices, not just math.tanh."""
    if impl == "exact":
        return math.tanh, "float tanh (reference, not buildable as-is)"
    if impl.startswith("lut"):
        bits = int(impl[3:])
        n, span = 1 << bits, 4.0
        tbl = np.tanh(np.linspace(-span, span, n))
        step = (2 * span) / (n - 1)

        def f(v, _t=tbl, _n=n, _s=span, _st=step):
            if v <= -_s: return -1.0
            if v >= _s:  return 1.0
            pos = (v + _s) / _st
            i = int(pos)
            frac = pos - i
            return _t[i] + (_t[i + 1] - _t[i]) * frac if i + 1 < _n else _t[i]
        return f, f"{n}-entry tanh table, linear interpolation ({bits}-bit index)"
    if impl == "poly3":
        # x*(27+x^2)/(27+9x^2), the Pade-style cubic rational often used for tanh
        def f(v):
            if v < -3.0: return -1.0
            if v > 3.0:  return 1.0
            x2 = v * v
            return v * (27.0 + x2) / (27.0 + 9.0 * x2)
        return f, "cubic rational approximation (2 mults, 1 divide)"
    raise ValueError(impl)


def ladder(x: np.ndarray, cutoff_hz: np.ndarray, res: np.ndarray,
           drive: float = 1.0, oversample: int = 2, tanh_impl: str = "lut10",
           gain_comp: float = 0.5, volts_per_unit: float = 0.13):
    """Huovilainen's nonlinear Moog ladder. `res` in (0, 1]; ~1.0 self-oscillates.

    Cost per OUTPUT sample: 5 * oversample tanh evaluations, 4 state registers,
    and one multiply per stage. At 2x that is 10 tanh and ~10 multiplies -- which
    at a 12.288 MHz clock and 48 kHz audio is 128 clocks of budget per output
    sample, comfortably enough to time-share ONE tanh unit and ONE multiplier.
    """
    # The paper's Vt is a physical transistor parameter, so the equation is in
    # VOLTS. Audio of +-1.0 fed in raw sits at tanh(1/0.05) = tanh(20): pinned,
    # permanently. `volts_per_unit` is the missing gain stage -- how hard full
    # scale drives the ladder. At the 0.13 default, full scale reaches
    # tanh(2.6): saturating on peaks, near-linear underneath, which is what the
    # circuit does. Raising it is the `drive` control on the front panel.
    T, _ = _make_tanh(tanh_impl)
    n = len(x)
    xo = np.repeat(x, oversample) * drive * volts_per_unit
    fo = np.repeat(cutoff_hz, oversample)
    ro = np.repeat(res, oversample)
    fs = SR * oversample
    # scaled impulse-invariant one-pole coefficient (paper section 5.1)
    g = 1.0 - np.exp(-2.0 * math.pi * np.clip(fo, 20.0, fs * 0.45) / fs)
    two_vt = 2.0 * VT

    y1 = y2 = y3 = y4 = 0.0
    w1 = w2 = w3 = w4 = 0.0          # stored tanh(y/2Vt) -- eq (17)'s reuse
    y4_d1 = y4_d2 = 0.0
    out = np.empty(len(xo))
    for i in range(len(xo)):
        gi = g[i] * two_vt
        k = 4.0 * ro[i]
        # half-unit delay in the feedback: average of the last two outputs
        fb = 0.5 * (y4_d1 + y4_d2)
        u = xo[i] - k * fb
        w0 = T(u / two_vt)                       # tanh #1 (input)
        y1 += gi * (w0 - w1); w1 = T(y1 / two_vt)   # tanh #2
        y2 += gi * (w1 - w2); w2 = T(y2 / two_vt)   # tanh #3
        y3 += gi * (w2 - w3); w3 = T(y3 / two_vt)   # tanh #4
        y4 += gi * (w3 - w4); w4 = T(y4 / two_vt)   # tanh #5
        y4_d2, y4_d1 = y4_d1, y4
        out[i] = y4
    # passband loss rises with resonance on the real circuit; compensate partly
    comp = 1.0 + gain_comp * float(np.mean(ro)) * 4.0
    return out[::oversample] * comp / volts_per_unit


def onepole_hp(x: np.ndarray, hz: float) -> np.ndarray:
    a = math.exp(-2.0 * math.pi * hz / SR)
    y = np.empty_like(x); prev_x = prev_y = 0.0
    for i, xi in enumerate(x):
        prev_y = a * (prev_y + xi - prev_x); prev_x = xi; y[i] = prev_y
    return y

def to_wav16(x: np.ndarray, peak: float = 0.89) -> np.ndarray:
    m = np.max(np.abs(x)) or 1.0
    return np.clip(x / m * peak * 32767, -32768, 32767).astype("<i2")
