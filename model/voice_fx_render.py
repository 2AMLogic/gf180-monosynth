#!/usr/bin/env python3
"""Render the eight monosynth patches through the FULLY integer voice, beside
the float `engines.mono_note`, and say per patch how far apart they are and
why.

    .venv/bin/python model/voice_fx_render.py            # -> model/audio/voice_fx/
    .venv/bin/python model/voice_fx_render.py --out DIR

The float reference is `mono_note(blep=True)`: the float voice as auditioned
uses NAIVE oscillators (the PolyBLEP in dsp.py was never wired in), and the
integer voice band-limits, so against the naive float most of the "difference"
on high notes is aliasing the integer voice removed. The like-for-like number
is the one that measures quantisation.

Per patch the difference is decomposed, because one dB number hides the cause:
  * "vs naive"     integer voice against mono_note as it is today (naive oscs)
  * "vs BLEP"      against mono_note(blep=True): like for like
  * "vs clipped"   the same, with the float's ladder output hard-clipped at
                   +-1.0 the way the integer ladder must. The gap between this
                   and "vs BLEP" is the cost of SATURATION, a gain-staging
                   decision, not a precision one
  * "clip %"       fraction of float samples beyond full scale, and the peak
  * "vs exact-g"   integer voice with its cutoff ROM replaced by the float exp
                   -- what the 128-entry g ROM costs on its own
  * "glide off"    04-lead-glide only: both models with portamento off. The
                   float glides geometrically and the integer voice slews the
                   increment linearly; with glide on the two are uncorrelated
                   (+0.7 dB) because that trajectory difference shifts every
                   sample after it, which says nothing about quantisation
"""
import argparse, math, sys, wave
from pathlib import Path
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import dsp, engines, patches
import voice_fx as vf
from dsp import SR

OUT = Path(__file__).parent / "audio" / "voice_fx"


def write(path: Path, x_i16: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(np.asarray(x_i16, dtype="<i2").tobytes())


def diff_db(y, ref):
    """RMS of the difference after each signal is normalised to unit RMS --
    the figure test_fixed.py and fixed_render.py report."""
    m = min(len(y), len(ref)); y, ref = y[:m], ref[:m]
    a = y / max(np.sqrt((y ** 2).mean()), 1e-12)
    b = ref / max(np.sqrt((ref ** 2).mean()), 1e-12)
    return 20 * math.log10(max(np.sqrt(((a - b) ** 2).mean()), 1e-12))


def level_match(x, ref):
    """Scale float `x` to the RMS of float `ref`, to int16: an A/B pair
    loudness-matched rather than peak-normalised."""
    g = np.sqrt((ref ** 2).mean()) / max(np.sqrt((x ** 2).mean()), 1e-12)
    return np.clip(np.round(x * g * 32767), -32768, 32767).astype(np.int16)


def with_kw(seq, **extra):
    return [(s, n, d, dict(kw, **extra)) for s, n, d, kw in seq]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    out = a.out
    gap = np.zeros(int(0.35 * SR), dtype=np.int16)
    print(f"{'patch':22} {'vs naive':>9} {'vs BLEP':>8} {'vs clipped':>11} {'clip %':>7} {'peak':>5} {'vs exact-g':>11}")
    sheet_ab, sheet_fx = [], []
    for name, seq, total in patches.MONO:
        naive = engines.render_mono(seq, total)                    # float, as auditioned
        fl = engines.render_mono(with_kw(seq, blep=True), total)   # float, like for like
        fx = vf.render_mono_fx(seq, total)                         # int16, the contract
        fxf = fx / 32768.0
        fx_g = vf.render_mono_fx(seq, total, vf.VoiceFx(g_exact=True)) / 32768.0
        clipped = np.clip(fl, -0.9, 0.9)                           # ladder out clipped at +-1, then x0.9
        over = float(np.mean(np.abs(fl) > 0.9)) * 100.0
        line = (f"{name:22} {diff_db(fxf, naive):8.1f}  {diff_db(fxf, fl):7.1f}  {diff_db(fxf, clipped):9.1f}  "
                f"{over:6.1f}  {np.abs(fl).max()/0.9:4.2f}  {diff_db(fxf, fx_g):9.1f}")
        if name == "04-lead-glide":
            fl_ng = engines.render_mono(with_kw(seq, blep=True, glide=False), total)
            fx_ng = vf.render_mono_fx(with_kw(seq, glide=False), total) / 32768.0
            line += f"   glide off: {diff_db(fx_ng, fl_ng):.1f} dB"
        print(line)
        write(out / f"{name}-fixed.wav", fx)                       # raw contract output
        fl16 = dsp.to_wav16(fl)                                    # the audition's own normalisation
        write(out / f"{name}-float.wav", fl16)
        sheet_ab += [fl16, gap, level_match(fxf, fl16 / 32768.0), gap]
        sheet_fx += [fx, gap]
    write(out / "00-float-vs-fixed.wav", np.concatenate(sheet_ab))
    write(out / "00-all-fixed.wav", np.concatenate(sheet_fx))
    # what the band-limiting buys, both integer: the lead line naive then PolyBLEP
    name, seq, total = patches.MONO[2]
    nv = vf.render_mono_fx(seq, total, vf.VoiceFx(blep=False))
    bl = vf.render_mono_fx(seq, total)
    write(out / "00-aliasing-naive-vs-blep.wav", np.concatenate([nv, gap, bl]))
    print(f"\nwrote {out}")
    print(f"listen:  afplay {out}/00-float-vs-fixed.wav          (float, fixed, float, fixed ... loudness-matched)")
    print(f"         afplay {out}/00-all-fixed.wav               (the eight patches, integer voice, raw output level)")
    print(f"         afplay {out}/00-aliasing-naive-vs-blep.wav  (lead line: integer naive oscillators, then integer PolyBLEP)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
