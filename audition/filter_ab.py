#!/usr/bin/env python3
"""The filter's own audition: how good does tanh have to be, and how much
oversampling do we have to buy?

Both are the dominant silicon costs of the Huovilainen ladder (5 tanh per
sample per oversample step), so they are worth deciding by ear rather than by
assumption. Renders the same resonant sweep each way, back to back.
"""
import sys, wave
from pathlib import Path
import numpy as np
import dsp, engines
from dsp import SR, to_wav16

OUT = Path(__file__).parent / "audio" / "filter-ab"


def sweep(tanh_impl="lut10", oversample=2, dur=4.0, res=0.93, drive=2.0):
    n = int(dur * SR)
    ph = dsp.ramp(n, dsp.phase_inc(55.0))
    x = 0.6 * dsp.osc("saw", ph) + 0.4 * dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(55.3)))
    t = np.arange(n) / n
    cut = 80.0 * (9000.0 / 80.0) ** t                     # log sweep 80 Hz -> 9 kHz
    return dsp.ladder(x, cut, np.full(n, res), drive=drive,
                      oversample=oversample, tanh_impl=tanh_impl)


def write(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(to_wav16(x).tobytes())


def aliasing_score(x):
    """Crude but honest: energy in the top octave (12-24 kHz), where a
    correctly band-limited ladder on this material should have very little.
    Nonlinear distortion that folds back shows up here first."""
    S = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    hi = S[(f >= 12000) & (f < 24000)].sum()
    return 10 * np.log10(hi / max(S.sum(), 1e-20))


def main():
    gap = np.zeros(int(0.4 * SR))
    print(f"{'variant':34} {'tanh/out-sample':>16} {'HF energy':>11}  {'vs exact':>9}")
    ref = sweep("exact", 2)
    write(OUT / "ref-exact-2x.wav", ref)
    rows, sheet = [], []
    for impl, os_ in [("exact", 2), ("lut10", 2), ("lut8", 2), ("poly3", 2),
                      ("lut10", 1), ("lut10", 4)]:
        y = sweep(impl, os_)
        name = f"{impl}-{os_}x"
        write(OUT / f"{name}.wav", y)
        m = min(len(y), len(ref))
        d = 20 * np.log10(np.sqrt(np.mean((y[:m] - ref[:m]) ** 2)) /
                          max(np.sqrt(np.mean(ref[:m] ** 2)), 1e-12))
        print(f"{name:34} {5*os_:>16} {aliasing_score(y):8.1f} dB  {d:8.1f} dB")
        sheet += [y, gap]
        rows.append(name)
    write(OUT / "00-filter-ab-all.wav", np.concatenate(sheet))
    print("\norder in 00-filter-ab-all.wav:", " | ".join(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
