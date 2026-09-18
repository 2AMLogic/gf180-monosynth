#!/usr/bin/env python3
"""Render the eight monosynth patches through the FULLY integer voice, beside
the float `engines.mono_note`, and say per patch how far apart they are and
why.

    .venv/bin/python model/voice_fx_render.py            # -> model/audio/voice_fx/
    .venv/bin/python model/voice_fx_render.py --out DIR

The float reference is `mono_note(blep=True, vca_post=True)`: the float voice
as auditioned uses NAIVE oscillators and applies the amplitude envelope before
the filter; the integer voice band-limits (DR 0001) and applies it after (DR
0005), so the like-for-like float is the one with both opt-in flags. The
integer voice here is rendered note by note and summed, as the float harness
is, so that the comparison measures quantisation and not the continuous
voice's retrigger and glide (DR 0003/0004), which the float harness cannot
do; the continuous voice's own output is written separately.

Per patch the difference is decomposed, because one dB number hides the cause:
  * "vs naive"     integer voice against mono_note as it is today (naive
                   oscillators, VCA before the filter): the audition
  * "vs BLEP+VCA"  against mono_note(blep=True, vca_post=True): like for like,
                   with the integer voice's resonance compensation OFF (the
                   float has none)
  * "k comp"       the same integer voice with DR 0006's compensation on,
                   against the same float: what the compensation changes
  * "peak"         the float's peak in units of full scale at the reference
                   volume; nothing clips on either side now (DR 0005)
  * "vs exact-g"   integer voice with its cutoff ROM replaced by the float exp
                   -- what the 128-entry g ROM costs on its own
  * "glide off"    04-lead-glide only: both models with portamento off. With
                   glide on the two are uncorrelated by design: the float
                   glides geometrically over a constant time and the integer
                   voice at a constant rate (DR 0004)
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


VOL = vf.VOL_REF / 32768.0 / 0.9        # the float's 0.9 master -> the reference volume


def render_summed(seq, dur_total, voice_kw=None):
    """The float harness's method on the integer voice: every note from
    reset, overlaps summed with saturation. A harness artefact kept ONLY for
    the like-for-like quantisation number; the voice itself is render_mono_fx."""
    out = np.zeros(int(dur_total * SR), dtype=np.int64)
    prev = None
    for start, note, d, kw in seq:
        kw = dict(kw); kw.pop("blep", None)
        if kw.pop("glide", False) and prev is not None:
            kw["glide_from"] = prev
        v = vf.VoiceFx(**(voice_kw or {})).note(note, d, **kw)
        i = int(start * SR); j = min(len(out), i + len(v))
        out[i:j] += v[:j - i]
        prev = note
    return np.clip(out, -32768, 32767).astype(np.int16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    out = a.out
    gap = np.zeros(int(0.35 * SR), dtype=np.int16)
    print(f"{'patch':22} {'vs naive':>9} {'vs BLEP+VCA':>12} {'k comp':>7} {'peak':>5} {'vs exact-g':>11}")
    sheet_ab, sheet_fx = [], []
    for name, seq, total in patches.MONO:
        naive = engines.render_mono(seq, total)                    # float, as auditioned
        fl = engines.render_mono(with_kw(seq, blep=True, vca_post=True), total) * VOL   # float, like for like
        fx = render_summed(seq, total, dict(k_comp=False))         # int16, note by note, no k comp
        fxf = fx / 32768.0
        fx_c = render_summed(seq, total) / 32768.0                 # with DR 0006's compensation
        fx_g = render_summed(seq, total, dict(g_exact=True, k_comp=False)) / 32768.0
        line = (f"{name:22} {diff_db(fxf, naive):8.1f}  {diff_db(fxf, fl):11.1f}  {diff_db(fx_c, fl):6.1f}  "
                f"{np.abs(fl).max():4.2f}  {diff_db(fxf, fx_g):9.1f}")
        if name == "04-lead-glide":
            fl_ng = engines.render_mono(with_kw(seq, blep=True, vca_post=True, glide=False), total) * VOL
            fx_ng = render_summed(with_kw(seq, glide=False), total, dict(k_comp=False)) / 32768.0
            line += f"   glide off: {diff_db(fx_ng, fl_ng):.1f} dB"
        print(line)
        cont = vf.render_mono_fx(seq, total)                       # the voice: continuous, DR 0003-0006
        write(out / f"{name}-fixed.wav", cont)                     # raw contract output
        fl16 = dsp.to_wav16(fl)                                    # the audition's own normalisation
        write(out / f"{name}-float.wav", fl16)
        sheet_ab += [fl16, gap, level_match(cont / 32768.0, fl16 / 32768.0), gap]
        sheet_fx += [cont, gap]
    write(out / "00-float-vs-fixed.wav", np.concatenate(sheet_ab))
    write(out / "00-all-fixed.wav", np.concatenate(sheet_fx))
    # what the band-limiting buys, both integer: the lead line naive then PolyBLEP
    name, seq, total = patches.MONO[2]
    nv = vf.render_mono_fx(seq, total, vf.VoiceFx(blep=False))
    bl = vf.render_mono_fx(seq, total)
    write(out / "00-aliasing-naive-vs-blep.wav", np.concatenate([nv, gap, bl]))
    print(f"\nwrote {out}")
    print(f"listen:  afplay {out}/00-float-vs-fixed.wav          (float, fixed, float, fixed ... loudness-matched)")
    print(f"         afplay {out}/00-all-fixed.wav               (the eight patches, the continuous integer voice, raw output level)")
    print(f"         afplay {out}/00-aliasing-naive-vs-blep.wav  (lead line: integer naive oscillators, then integer PolyBLEP)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
