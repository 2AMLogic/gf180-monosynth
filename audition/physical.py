"""Delay-line instruments: the multitap idea put where it actually pays.

A delay line is the wrong structure for a resonant lowpass (an FIR matching the
ladder at 200 Hz / res 0.9 needs 15,355 taps against 5 multiplies, and at
res 1.0 it cannot self-oscillate at all -- no feedback, no oscillation). It is
the RIGHT structure for a physically-modelled instrument, where the delay IS
the object: a string's length, a tube's length, a bar's mode.

The cost profile inverts, which is the interesting part. The ladder is
multiplier-bound and memory-free. These are memory-bound and almost
multiplier-free: a Karplus-Strong string is a RAM, one add and one multiply,
whatever its pitch. That makes it cheap in a different currency -- and 2AM
already has a gf180-sram canary, so it is a currency the fleet is working in.
"""
from __future__ import annotations
import math
import numpy as np
import dsp
from dsp import SR, note_hz


def karplus(note, dur, *, damp=0.996, bright=0.5, pluck_pos=0.28, seed=1):
    """Plucked string. Delay line of SR/f0 samples with a one-pole lowpass in
    the loop -- the lowpass is why high harmonics die first, like a real string.
    Silicon: one RAM, one add, two multiplies. Pitch costs memory, not logic."""
    f0 = note_hz(note)
    N = max(2, int(round(SR / f0)))
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    buf = rng.uniform(-1, 1, N)
    # comb the excitation to model where the string was plucked
    k = max(1, int(N * pluck_pos))
    buf = buf - np.roll(buf, k)
    buf *= np.hanning(N) ** 0.25
    out = np.empty(n)
    prev = 0.0
    i = 0
    for t in range(n):
        v = buf[i]
        lp = (1.0 - bright) * prev + bright * v      # one-pole in the loop
        prev = lp
        buf[i] = lp * damp
        out[t] = v
        i = (i + 1) % N
    return out * 0.8, N


def modal(note, dur, *, modes=((1.0, 1.0, 1.0), (2.76, 0.6, 0.7), (5.40, 0.4, 0.5),
                               (8.93, 0.25, 0.35)), strike=1.0, seed=2):
    """Struck bar/plate: a bank of tuned resonators, one per mode. The ratios
    above are a free bar's (1, 2.76, 5.40, 8.93) -- that inharmonicity is why a
    marimba is not a sine. Silicon: two state registers and two multiplies per
    mode, no RAM at all."""
    n = int(dur * SR)
    f0 = note_hz(note)
    rng = np.random.default_rng(seed)
    exc = np.zeros(n)
    hit = max(1, int(0.0016 * SR))
    exc[:hit] = rng.uniform(-1, 1, hit) * np.hanning(hit) * strike
    out = np.zeros(n)
    for ratio, amp, decay in modes:
        f = f0 * ratio
        if f > SR * 0.45:
            continue
        r = math.exp(-1.0 / (decay * 0.9 * SR))
        w = 2 * math.pi * f / SR
        a1, a2 = 2 * r * math.cos(w), -r * r
        y1 = y2 = 0.0
        for t in range(n):
            y = exc[t] + a1 * y1 + a2 * y2
            y2, y1 = y1, y
            out[t] += amp * y
    return out / max(np.abs(out).max(), 1e-9) * 0.85


def memory_table():
    print(f"{'lowest note':>12} {'f0':>8} {'delay taps':>11} {'bytes/voice':>12} {'4 voices':>10}")
    for note in (28, 36, 40, 48):
        f0 = note_hz(note); N = int(round(SR / f0))
        print(f"{note:12} {f0:8.1f} {N:11,} {N*2:11,}B {N*2*4/1024:9.1f}K")
