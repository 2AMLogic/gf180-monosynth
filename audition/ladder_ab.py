#!/usr/bin/env python3
"""Huovilainen's ladder against the naive one-tanh ladder, same everything else.

The naive version is the structure most "Moog filter" code uses: four LINEAR
one-pole stages with a single saturating element in the feedback path. It is
the version this harness had before the paper was read. The paper's point is
that the nonlinearity belongs in every stage, because every stage IS a
transistor differential pair.
"""
import sys, wave, math
from pathlib import Path
import numpy as np
import dsp, engines, patches
from dsp import SR, to_wav16

OUT = Path(__file__).parent / "audio" / "ladder-ab"


def naive_ladder(x, cutoff_hz, res, drive=1.0, oversample=2, **_):
    """Four linear one-poles, one tanh in the feedback. NOT the paper."""
    n = len(x)
    xo = np.repeat(x, oversample) * drive
    fo = np.repeat(cutoff_hz, oversample); ro = np.repeat(res, oversample)
    fs = SR * oversample
    g = 1.0 - np.exp(-2.0 * math.pi * np.clip(fo, 20.0, fs * 0.45) / fs)
    s1 = s2 = s3 = s4 = 0.0
    out = np.empty(len(xo))
    for i in range(len(xo)):
        gi, k = g[i], 4.0 * ro[i]
        u = math.tanh(xo[i] - k * s4)     # the only nonlinearity
        s1 += gi * (u - s1); s2 += gi * (s1 - s2)
        s3 += gi * (s2 - s3); s4 += gi * (s3 - s4)
        out[i] = s4
    return out[::oversample]


def write(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(to_wav16(x).tobytes())


def harmonics(x, f0=55.0, n=12):
    """Level of each harmonic of f0, dB relative to the fundamental."""
    S = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / SR)
    out = []
    for h in range(1, n + 1):
        i = np.argmin(np.abs(f - f0 * h))
        out.append(S[max(0, i - 2):i + 3].max())
    ref = out[0] or 1e-12
    return [20 * math.log10(v / ref + 1e-12) for v in out]


def main():
    real, naive = dsp.ladder, naive_ladder
    gap = np.zeros(int(0.4 * SR))

    # 1. a steady driven note: harmonic structure is where the difference lives
    n = int(1.5 * SR)
    src = 0.6 * dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(55.0))) \
        + 0.4 * dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(55.25)))
    cut, rr = np.full(n, 420.0), np.full(n, 0.85)
    a = real(src, cut, rr, drive=2.4)
    b = naive(src, cut, rr, drive=2.4)
    write(OUT / "steady-huovilainen.wav", a)
    write(OUT / "steady-naive.wav", b)
    ha, hb = harmonics(a), harmonics(b)
    print("Driven 55 Hz saw, cutoff 420 Hz, resonance 0.85 -- harmonic levels (dB rel. fundamental)")
    print(f"{'harmonic':>9} {'Huovilainen':>12} {'naive':>8} {'diff':>7}")
    for i, (x, y) in enumerate(zip(ha, hb), 1):
        print(f"{i:>9} {x:11.1f} {y:8.1f} {x-y:+7.1f}")
    odd = sum(ha[i] for i in (2, 4, 6)) / 3 - sum(hb[i] for i in (2, 4, 6)) / 3
    print(f"\nmean level of harmonics 3/5/7: {odd:+.1f} dB (Huovilainen vs naive)")

    # 2. the same three patches, both filters, for listening
    sheet = []
    for name, seq, total in (patches.MONO[0], patches.MONO[4], patches.MONO[6]):
        for label, fn in (("huovilainen", real), ("naive", naive)):
            # engines.py does `from dsp import ladder`, so it holds its OWN
            # reference: patching dsp.ladder alone changes nothing and silently
            # renders the same filter twice. Patch the name engines actually calls.
            engines.ladder = fn
            y = engines.render_mono(seq, total)
            write(OUT / f"{name}-{label}.wav", y)
            sheet += [y, gap]
        engines.ladder = real
    write(OUT / "00-ladder-ab-all.wav", np.concatenate(sheet))
    print("\n00-ladder-ab-all.wav order: bass(H) bass(naive) sweep(H) sweep(naive) growl(H) growl(naive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
