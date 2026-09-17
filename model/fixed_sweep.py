#!/usr/bin/env python3
"""How many bits does the ladder actually need? Measured, not assumed.

Three things are checked, because they fail independently:
  1. agreement with the float model on ordinary material
  2. the DEAD ZONE -- at a low cutoff, g is tiny, and if the state has too few
     fraction bits the increment truncates to zero and the filter stops
     responding entirely
  3. LIMIT CYCLES -- after the input goes silent, does the output actually
     reach zero and stay there, or does truncation sustain a buzz forever
"""
import math, sys
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import dsp, fixed
from dsp import SR


def diff_db(y, ref):
    m = min(len(y), len(ref)); y, ref = y[:m], ref[:m]
    a = y / max(np.sqrt((y ** 2).mean()), 1e-12)
    b = ref / max(np.sqrt((ref ** 2).mean()), 1e-12)
    return 20 * math.log10(max(np.sqrt(((a - b) ** 2).mean()), 1e-12) /
                           max(np.sqrt((b ** 2).mean()), 1e-12))


def dead_zone(SB, SQ, N, interp):
    """Drive a 40 Hz cutoff -- the hardest case for the increment -- and report
    output level relative to the float model. Near zero means the filter died."""
    n = int(0.35 * SR)
    x = dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(55.0))) * 0.8
    f = fixed.LadderFx(state_bits=SB, state_q=SQ, tanh_entries=N, interp=interp)
    y = fixed.q15f(f.process(fixed.f2q15(x), np.full(n, 40.0), 0.5, drive=2.0))
    ref = dsp.ladder(x, np.full(n, 40.0), np.full(n, 0.5), drive=2.0)
    ry = np.sqrt((y[n // 2:] ** 2).mean()); rr = np.sqrt((ref[n // 2:] ** 2).mean())
    return 20 * math.log10(max(ry, 1e-12) / max(rr, 1e-12))


def limit_cycle(SB, SQ, N, interp):
    """Half a second of signal, then half a second of digital silence in.
    Returns the peak |output| in the last 0.2 s, in LSBs of a 16-bit sample."""
    n1, n2 = int(0.4 * SR), int(0.5 * SR)
    x = np.concatenate([dsp.osc("saw", dsp.ramp(n1, dsp.phase_inc(55.0))) * 0.9,
                        np.zeros(n2)])
    f = fixed.LadderFx(state_bits=SB, state_q=SQ, tanh_entries=N, interp=interp)
    y = f.process(fixed.f2q15(x), np.full(len(x), 600.0), 0.85, drive=2.5)
    tail = y[-int(0.2 * SR):]
    return int(np.abs(tail.astype(np.int32)).max())


def main():
    n = int(0.35 * SR)
    x = dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(110.0))) * 0.8
    xq = fixed.f2q15(x)
    ref = dsp.ladder(x, np.full(n, 900.0), np.full(n, 0.8), drive=2.0)

    print("STATE WIDTH  (tanh 128 entries, interpolated; range fixed at +-8.0)")
    print(f"  {'bits':>5} {'frac':>5} {'vs float':>9} {'dead zone':>11} {'limit cycle':>12}")
    for SB in (16, 18, 20, 22, 24, 28, 32):
        SQ = SB - 4
        f = fixed.LadderFx(state_bits=SB, state_q=SQ)
        y = fixed.q15f(f.process(xq, np.full(n, 900.0), 0.8, drive=2.0))
        lc = limit_cycle(SB, SQ, 128, True)
        print(f"  {SB:5} {SQ:5} {diff_db(y, ref):8.1f} dB {dead_zone(SB,SQ,128,True):8.1f} dB "
              f"{lc:9} LSB")

    print("\nTANH TABLE  (state 24-bit / 20 fraction)")
    print(f"  {'entries':>8} {'interp':>7} {'ROM bits':>9} {'vs float':>9}")
    for N in (16, 32, 64, 128, 256):
        for it in (True, False):
            f = fixed.LadderFx(tanh_entries=N, interp=it)
            y = fixed.q15f(f.process(xq, np.full(n, 900.0), 0.8, drive=2.0))
            print(f"  {N:8} {str(it):>7} {N*16:9} {diff_db(y, ref):8.1f} dB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
