#!/usr/bin/env python3
"""Render the audition. Every patch to its own WAV, plus one contact sheet per
engine so you can listen straight through.

    python3 render.py                 # everything
    python3 render.py --engine mono   # one engine
    python3 render.py --tanh poly3    # audition the filter's cheap tanh
"""
from __future__ import annotations
import argparse, sys, time, wave
from pathlib import Path
import numpy as np
import dsp, engines, patches
from dsp import SR, to_wav16

OUT = Path(__file__).parent / "audio"


def write_wav(path: Path, x: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(to_wav16(x).tobytes())


def gap(sec=0.35):
    return np.zeros(int(sec * SR))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["mono", "drums", "fm", "all"], default="all")
    ap.add_argument("--tanh", default="lut10", help="exact | lut8 | lut10 | poly3")
    ap.add_argument("--suffix", default="", help="tag the output directory")
    a = ap.parse_args()

    out = OUT if not a.suffix else OUT.parent / f"audio-{a.suffix}"
    dsp._AUDITION_TANH = a.tanh
    orig = engines.mono_note

    def mono_with_tanh(*args, **kw):
        kw.setdefault("_tanh", a.tanh)
        return orig(*args, **kw)
    engines.mono_note = mono_with_tanh

    t0 = time.time()
    if a.engine in ("mono", "all"):
        sheet = []
        for name, seq, total in patches.MONO:
            t = time.time()
            x = engines.render_mono(seq, total)
            write_wav(out / "monosynth" / f"{name}.wav", x)
            sheet.append(x); sheet.append(gap())
            print(f"  mono  {name:22} {total:4.1f}s audio  {time.time()-t:5.1f}s render")
        write_wav(out / "00-monosynth-all.wav", np.concatenate(sheet))

    if a.engine in ("drums", "all"):
        sheet = []
        for name, pat, bpm, swing, fm_hits in patches.GROOVES:
            t = time.time()
            x = engines.render_groove(pat, bpm=bpm, swing=swing, bars=2, fm_hits=fm_hits)
            write_wav(out / "drums" / f"{name}.wav", x)
            sheet.append(x); sheet.append(gap(0.2))
            print(f"  drums {name:22} {len(x)/SR:4.1f}s audio  {time.time()-t:5.1f}s render")
        write_wav(out / "00-drums-all.wav", np.concatenate(sheet))

    if a.engine in ("fm", "all"):
        sheet = []
        for name, seq, total in patches.FM:
            t = time.time()
            x = engines.render_fm(seq, total)
            write_wav(out / "fm" / f"{name}.wav", x)
            sheet.append(x); sheet.append(gap())
            print(f"  fm    {name:22} {total:4.1f}s audio  {time.time()-t:5.1f}s render")
        write_wav(out / "00-fm-all.wav", np.concatenate(sheet))

    print(f"\nwrote {out}  ({time.time()-t0:.0f}s total)")
    print("listen:  afplay", out / "00-monosynth-all.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())
