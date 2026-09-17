"""Realtime engine: the same math as the offline audition, made stateful.

The offline `dsp.ladder` zeroes its four integrator states on every call, which
is right for rendering a whole patch and catastrophic for block-based realtime
audio -- it would reset the filter 187 times a second and click on every block
boundary. Same for oscillator phase and envelopes. So everything that carries
state across a block boundary lives here as an object, and the arithmetic is
kept identical to `dsp` so what you play matches what you auditioned.
"""
from __future__ import annotations
import math
import numpy as np
import dsp
from dsp import SR, PHASE_MASK, phase_inc, note_hz

BLOCK = 256


class Ladder:
    """Huovilainen ladder with persistent state. See dsp.ladder for the paper."""

    def __init__(self, tanh_impl="lut10", oversample=2, volts_per_unit=0.13):
        self.T, _ = dsp._make_tanh(tanh_impl)
        self.os = oversample
        self.vpu = volts_per_unit
        self.y1 = self.y2 = self.y3 = self.y4 = 0.0
        self.w1 = self.w2 = self.w3 = self.w4 = 0.0
        self.d1 = self.d2 = 0.0

    def process(self, x, cutoff_hz, res, drive=1.0):
        T, os_, vpu = self.T, self.os, self.vpu
        two_vt = 2.0 * dsp.VT
        fs = SR * os_
        xo = np.repeat(x, os_) * drive * vpu
        fo = np.repeat(cutoff_hz, os_)
        g = 1.0 - np.exp(-2.0 * math.pi * np.clip(fo, 20.0, fs * 0.45) / fs)
        k = 4.0 * res
        y1, y2, y3, y4 = self.y1, self.y2, self.y3, self.y4
        w1, w2, w3, w4 = self.w1, self.w2, self.w3, self.w4
        d1, d2 = self.d1, self.d2
        out = np.empty(len(xo))
        for i in range(len(xo)):
            gi = g[i] * two_vt
            u = xo[i] - k * 0.5 * (d1 + d2)        # half-sample delay in feedback
            w0 = T(u / two_vt)
            y1 += gi * (w0 - w1); w1 = T(y1 / two_vt)
            y2 += gi * (w1 - w2); w2 = T(y2 / two_vt)
            y3 += gi * (w2 - w3); w3 = T(y3 / two_vt)
            y4 += gi * (w3 - w4); w4 = T(y4 / two_vt)
            d2, d1 = d1, y4
            out[i] = y4
        self.y1, self.y2, self.y3, self.y4 = y1, y2, y3, y4
        self.w1, self.w2, self.w3, self.w4 = w1, w2, w3, w4
        self.d1, self.d2 = d1, d2
        comp = 1.0 + 0.5 * res * 4.0
        return out[::os_] * comp / vpu


class Env:
    """ADSR as a state machine, because realtime has no idea how long a note is."""
    IDLE, ATK, DEC, SUS, REL = range(5)

    def __init__(self):
        self.stage, self.v = self.IDLE, 0.0
        self.a = self.d = self.s = self.r = 0.0

    def set(self, a, d, s, r):
        self.a, self.d, self.s, self.r = max(a, 1e-4), max(d, 1e-4), s, max(r, 1e-4)

    def gate_on(self):  self.stage = self.ATK
    def gate_off(self): self.stage = self.REL if self.stage != self.IDLE else self.IDLE

    def block(self, n):
        out = np.empty(n)
        v, st = self.v, self.stage
        da = 1.0 / (self.a * SR)
        dd = 1.0 / (self.d * SR)
        kr = math.exp(-4.0 / (self.r * SR))
        for i in range(n):
            if st == self.ATK:
                v += da
                if v >= 1.0: v, st = 1.0, self.DEC
            elif st == self.DEC:
                v -= dd * (1.0 - self.s)
                if v <= self.s: v, st = self.s, self.SUS
            elif st == self.SUS:
                v = self.s
            elif st == self.REL:
                v *= kr
                if v < 1e-4: v, st = 0.0, self.IDLE
            else:
                v = 0.0
            out[i] = v
        self.v, self.stage = v, st
        return out

    @property
    def active(self): return self.stage != self.IDLE


class Mono:
    """Monophonic Minimoog-shaped voice. Last-note priority, like the original."""

    def __init__(self):
        self.ph = [0, 0, 0]
        self.filt = Ladder()
        self.aenv, self.fenv = Env(), Env()
        self.note = None
        self.held: list[int] = []
        self.glide_hz = note_hz(48)
        # front panel
        self.waves = ["saw", "saw", "square"]
        self.detune = [0.0, 0.06, -12.0]
        self.mix = [1.0, 0.9, 0.6]
        self.cutoff = 500.0      # Hz, the knob
        self.res = 0.70
        self.drive = 1.9
        self.env_amt = 2200.0    # how far the filter envelope opens it
        self.track = 0.25
        self.glide = 0.0         # seconds; 0 = off
        self.vel = 1.0
        self.aenv.set(0.003, 0.18, 0.72, 0.09)
        self.fenv.set(0.002, 0.16, 0.18, 0.08)

    def note_on(self, n, vel=1.0):
        if n not in self.held: self.held.append(n)
        self.note, self.vel = n, vel
        self.aenv.gate_on(); self.fenv.gate_on()

    def note_off(self, n):
        if n in self.held: self.held.remove(n)
        if self.held:
            self.note = self.held[-1]          # last-note priority
        else:
            self.aenv.gate_off(); self.fenv.gate_off()

    def block(self, n=BLOCK):
        if not self.aenv.active and self.note is None:
            return np.zeros(n)
        target = note_hz(self.note) if self.note is not None else self.glide_hz
        if self.glide > 1e-4:
            a = math.exp(-1.0 / (self.glide * SR / n))
            self.glide_hz = a * self.glide_hz + (1 - a) * target
        else:
            self.glide_hz = target
        f0 = self.glide_hz
        sig = np.zeros(n)
        for i, (w, dt, mx) in enumerate(zip(self.waves, self.detune, self.mix)):
            inc = phase_inc(f0 * 2.0 ** (dt / 12.0))
            ph = (self.ph[i] + inc * np.arange(1, n + 1, dtype=np.int64)) & PHASE_MASK
            self.ph[i] = int(ph[-1])
            sig += mx * dsp.osc(w, ph)
        sig /= sum(self.mix)
        ae = self.aenv.block(n) * self.vel
        fe = self.fenv.block(n)
        cut = np.clip(self.cutoff + self.env_amt * fe + self.track * f0 * 4.0,
                      30.0, SR * 0.45)
        return self.filt.process(sig * ae, cut, self.res, drive=self.drive) * 0.9


class Drums:
    """One-shot voices triggered into a mix buffer. Cheap: no filter, no state
    machine -- each hit is a rendered tail that decays into the output."""

    def __init__(self):
        import engines
        self.E = engines
        self.pending: list[np.ndarray] = []
        self.tail = np.zeros(0)

    def trigger(self, which):
        fn = {"k": self.E.kick, "s": self.E.snare,
              "h": lambda: self.E.hat(open_=False), "H": lambda: self.E.hat(open_=True),
              "t": lambda: self.E.fm_perc(carrier=150, ratio=1.41, index=6.0, decay=0.28),
              "b": lambda: self.E.fm_perc(carrier=520, ratio=3.51, index=8.0, decay=0.9)}[which]
        self.pending.append(fn())

    def block(self, n=BLOCK):
        if self.pending:
            for p in self.pending:
                if len(self.tail) < len(p):
                    self.tail = np.pad(self.tail, (0, len(p) - len(self.tail)))
                self.tail[:len(p)] += p
            self.pending.clear()
        if len(self.tail) < n:
            self.tail = np.pad(self.tail, (0, n - len(self.tail)))
        out, self.tail = self.tail[:n].copy(), self.tail[n:]
        return out


PRESETS = {
    "1": ("bass",    dict(waves=["saw","saw","square"], detune=[0,0.06,-12], mix=[1,.9,.6],
                          cutoff=180, res=.70, drive=1.9, env_amt=1900, track=.25,
                          a=(0.003,0.18,0.72,0.09), f=(0.002,0.16,0.18,0.08))),
    "2": ("lead",    dict(waves=["saw","saw","saw"], detune=[0,0.10,-0.09], mix=[1,.8,.8],
                          cutoff=700, res=.66, drive=1.5, env_amt=5500, track=.5,
                          a=(0.02,0.5,0.80,0.30), f=(0.05,0.9,0.35,0.30))),
    "3": ("sweep",   dict(waves=["saw","square","saw"], detune=[0,-12,0.08], mix=[1,.7,.9],
                          cutoff=120, res=.92, drive=1.4, env_amt=6800, track=.1,
                          a=(0.01,1.2,0.95,0.6), f=(0.9,1.6,0.10,0.9))),
    "4": ("growl",   dict(waves=["saw","saw","pulse25"], detune=[0,0.25,-12], mix=[1,1,.8],
                          cutoff=150, res=.97, drive=3.6, env_amt=1350, track=.2,
                          a=(0.004,0.3,0.85,0.12), f=(0.01,0.35,0.30,0.15))),
    "5": ("whistle", dict(waves=["sine","sine","sine"], detune=[0,0.03,-12], mix=[1,.2,.1],
                          cutoff=200, res=1.06, drive=0.5, env_amt=2400, track=.9,
                          a=(0.03,0.4,0.85,0.4), f=(0.25,1.0,0.5,0.5))),
}


def apply_preset(voice: Mono, key: str) -> str:
    name, p = PRESETS[key]
    voice.waves, voice.detune, voice.mix = list(p["waves"]), list(p["detune"]), list(p["mix"])
    voice.cutoff, voice.res, voice.drive = p["cutoff"], p["res"], p["drive"]
    voice.env_amt, voice.track = p["env_amt"], p["track"]
    voice.aenv.set(*p["a"]); voice.fenv.set(*p["f"])
    return name
