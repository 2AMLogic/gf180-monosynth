"""Fixed-point model of the ladder. Integers only -- no float anywhere in the
signal path -- so that RTL can be bit-exact against it.

Why this exists before any Verilog: in a feedback loop rounding error
recirculates, and two failures only appear in integers.

  * **Dead zone.** At a low cutoff `g` is tiny (g = 1-exp(-2*pi*30/96000) is
    about 0.00196). If the state word has too few fraction bits, `g * diff`
    truncates to zero and the filter simply stops responding. A float model
    cannot show you this.
  * **Limit cycles.** Truncation in a recursive loop can sustain a small
    oscillation forever -- a faint buzz that never decays into silence.

Both are width questions, so width is a parameter here and the point of the
module is to find the smallest one that still sounds like the filter.

The state is held in units of 2*Vt rather than in volts. The paper's stage is

    y += 2*Vt*g*( tanh(x/2Vt) - tanh(y/2Vt) )

and dividing through by 2*Vt turns that into

    Y += g*( tanh(X) - tanh(Y) )

so the tanh argument IS the state, the 2*Vt multiply disappears from the inner
loop, and the table is indexed by the state directly. One less multiplier in
the datapath, and no scaling constant to get wrong.

Formats:
    signal      Q1.15   int16, +-1.0
    state       Q(SB-SQ).SQ in units of 2*Vt; default 24-bit, 20 fraction
                bits, so +-8.0 -- tanh saturates by 4.0, leaving 6 dB of
                headroom for the resonant peak before the state clamps
    coefficient Q0.16   uint16
    tanh table  128 entries over [0,4), odd-symmetric, optional interpolation
"""
from __future__ import annotations
import math
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
import numpy as np
import dsp
from dsp import SR

SIG_Q = 15
COEF_Q = 16
VT2 = 0.05                      # 2*Vt, the paper's scaling
TANH_DOMAIN = 4.0               # tanh(4) = 0.9993; beyond this, clamp


def shl(v: int, k: int) -> int:
    """Shift left by k, or right by -k. The state can legitimately have fewer
    fraction bits than the Q1.15 signal; that is a design point to measure, not
    a crash."""
    return v << k if k >= 0 else v >> (-k)


def sat(v: int, bits: int) -> int:
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return lo if v < lo else (hi if v > hi else v)


class LadderFx:
    def __init__(self, state_bits=24, state_q=20, tanh_entries=128,
                 interp=True, volts_per_unit=0.13, oversample=2):
        self.SB, self.SQ = state_bits, state_q
        self.N, self.interp = tanh_entries, interp
        self.vpu, self.os = volts_per_unit, oversample
        self.dom_fx = int(TANH_DOMAIN * (1 << self.SQ))      # state value where tanh clamps
        # Sample points depend on how the table is READ. Interpolating between
        # entries requires them at bin EDGES (i/N); reading nearest-entry wants
        # them at bin MIDPOINTS ((i+0.5)/N), which halves the worst-case error.
        # Mixing the two puts a half-bin skew on every lookup -- measured as an
        # 8 dB penalty, i.e. interpolation appearing to make accuracy worse.
        off = 0.0 if interp else 0.5
        self.tbl = [int(round(math.tanh((i + off) / self.N * TANH_DOMAIN) * 32767))
                    for i in range(self.N)]
        self.reset()

    def reset(self):
        self.y = [0, 0, 0, 0]
        self.w = [0, 0, 0, 0]
        self.d1 = self.d2 = 0

    # ---- tanh(y / 2Vt) from the half table, odd symmetry, Q1.15 out --------
    def tanh_fx(self, y: int) -> int:
        neg = y < 0
        a = -y if neg else y
        if a >= self.dom_fx:
            r = 32767
        else:
            pos = a * self.N
            idx = pos // self.dom_fx
            if self.interp:
                rem = pos - idx * self.dom_fx
                t0 = self.tbl[idx]
                t1 = self.tbl[idx + 1] if idx + 1 < self.N else 32767
                r = t0 + ((t1 - t0) * rem) // self.dom_fx
            else:
                r = self.tbl[idx]
        return -r if neg else r

    def coefficients(self, cutoff_hz: np.ndarray, res: float, drive: float = 1.0):
        """The four integers the loop actually runs on, from the float controls.
        Split out so a testbench can hand the RTL exactly what the model used.

        Widths, since the RTL has to carry them: g is Q0.16 and reaches 61,659
        at the 0.45*fs cutoff clamp (bit 15 set above ~10.6 kHz, so it is NOT
        a signed 16-bit quantity); k is 4*res in Q.14 and needs 17 bits from
        res = 1.0; gain = drive*vpu/2Vt is 2.6*drive in Q.16 (19 bits at drive
        3); ogain = 2Vt/vpu*(1+2*res) in Q.16 is 17 bits to res 1.5."""
        fs = SR * self.os
        # coefficient per sample, Q0.16 -- a real design would ROM this
        g_tab = np.clip(
            np.round((1.0 - np.exp(-2.0 * math.pi * np.clip(cutoff_hz, 20.0, fs * 0.45) / fs))
                     * (1 << COEF_Q)), 1, (1 << COEF_Q) - 1).astype(np.int64)
        k = int(round(4.0 * res * (1 << 14)))          # Q2.14
        # Q1.15 audio -> state units (2*Vt). One constant: drive*vpu/(2*Vt).
        gain = int(round(drive * self.vpu / VT2 * (1 << COEF_Q)))
        # state units -> Q1.15 audio on the way out, with resonance gain comp
        ogain = int(round(VT2 / self.vpu * (1.0 + 0.5 * res * 4.0) * (1 << COEF_Q)))
        return g_tab, k, gain, ogain

    def process(self, x_q15: np.ndarray, cutoff_hz: np.ndarray, res: float,
                drive: float = 1.0):
        """x_q15: int16 samples. Returns int16. Everything between is integer."""
        os_, SQ, SB = self.os, self.SQ, self.SB
        n = len(x_q15)
        g_tab, k, gain, ogain = self.coefficients(cutoff_hz, res, drive)
        out = np.empty(n, dtype=np.int16)
        y, w = self.y, self.w
        d1, d2 = self.d1, self.d2
        TQ = SQ - SIG_Q                                 # shift Q1.15 -> state Q
        for i in range(n):
            xi = int(x_q15[i])
            g = int(g_tab[i])
            for _ in range(os_):
                fb = (d1 + d2) >> 1
                u = sat(shl(xi * gain, TQ - COEF_Q) - ((k * fb) >> 14), SB)
                w0 = self.tanh_fx(u)
                for s in range(4):
                    prev = w0 if s == 0 else w[s - 1]
                    diff = prev - w[s]                     # Q1.15, +-2
                    inc = (g * shl(diff, TQ)) >> COEF_Q    # -> state Q
                    y[s] = sat(y[s] + inc, SB)
                    w[s] = self.tanh_fx(y[s])
                d2, d1 = d1, y[3]
            out[i] = sat((shl(y[3], -TQ) * ogain) >> COEF_Q, 16)
        self.y, self.w, self.d1, self.d2 = y, w, d1, d2
        return out


def f2q15(x: np.ndarray) -> np.ndarray:
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)


def q15f(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float64) / 32768.0
