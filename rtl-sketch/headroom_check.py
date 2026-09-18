#!/usr/bin/env python3
"""Headroom between the voice bus and the drum bus at the master mix
(docs/ARCHITECTURE.md section 4), measured on the material that exists:

  * the voice: the eight audition patches through the integer voice
    (render_mono_fx, contract 16's reference material) at the reference
    volume 0.45 -- the peak of each patch's contribution (v * vol) >> 15;
  * the drums: the modal bank (model/modal_fixed.py, the only drum body model
    in this repository) struck with the model's full-scale 1.6 ms burst at
    each preset note -- the peak of the bank's output word;
  * the sum: the loudest patch's sample stream plus a drum pattern (a bar at
    note 40 every 0.5 s, one at note 64 every 0.25 s), at candidate drum
    levels, counting samples the chip's one rail would clip.

The drum sources of the `drums` branch are not in this measurement; when they
exist the same script should be run on them (--drum-wav is the hook).

    .venv/bin/python rtl-sketch/headroom_check.py
"""
from __future__ import annotations
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model")); sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np
import voice_fx as vf, modal_fixed as mf, patches
from dsp import SR


def voice_peaks():
    rows = []
    for name, seq, dur in patches.MONO:
        v = vf.VoiceFx()
        y = vf.render_mono_fx(seq, dur, voice=v)
        rows.append((name, int(np.abs(y).max()), y))
    return rows


def drum_peaks():
    m = mf.ModalFx()
    rows = []
    for note in (28, 40, 52, 64, 76, 88):
        m.reset()
        y = m.process(mf.f2q15(mf.strike(0.5, amount=1.0)), m.coefficients(note))
        rows.append((note, int(np.abs(y).max())))
    return rows


def drum_pattern(n):
    m = mf.ModalFx()
    out = np.zeros(n, dtype=np.int64)
    for note, period, phase in ((40, 0.5, 0.0), (64, 0.25, 0.125)):
        m.reset()
        exc = np.zeros(n)
        hit = mf.strike(0.5, amount=1.0)
        t = phase
        while int(t * SR) < n:
            s = int(t * SR); e = min(n, s + len(hit))
            exc[s:e] += hit[:e - s]
            t += period
        out += m.process(mf.f2q15(np.clip(exc, -1, 1)), m.coefficients(note)).astype(np.int64)
    return np.clip(out, -32768, 32767)


def main():
    print("voice bus at the reference vol 0.45 (contract 12): peak of (v * vol) >> 15, per audition patch")
    vp = voice_peaks()
    for name, pk, _ in vp:
        print(f"  {name:18s} {pk:6d}  ({pk / 32768:.2f} FS, {20 * np.log10(max(pk, 1) / 32768):6.1f} dBFS)")
    print("drum bodies: the modal bank's peak output for a full-scale strike, per preset note (headroom 10 bits)")
    dp = drum_peaks()
    for note, pk in dp:
        print(f"  note {note:3d}          {pk:6d}  ({pk / 32768:.2f} FS, {20 * np.log10(max(pk, 1) / 32768):6.1f} dBFS)")
    loud = max(vp, key=lambda r: r[1])
    n = len(loud[2])
    d = drum_pattern(n)
    print(f"sum: '{loud[0]}' (the loudest patch) + the drum pattern, {n} frames, clipped samples at the rail:")
    for dvol in (0.125, 0.25, 0.35, 0.5, 0.71):
        dq = int(round(dvol * 32768))
        s = loud[2].astype(np.int64) + ((d * dq) >> 15)
        clipped = int(np.sum((s > 32767) | (s < -32768)))
        print(f"  dvol {dvol:5.3f} ({dq:5d}): drum peak {int(np.abs((d * dq) >> 15).max()) / 32768:.2f} FS, "
              f"sum peak {int(np.abs(s).max()) / 32768:.2f} FS, clipped {clipped} ({100 * clipped / n:.3f} %)")


if __name__ == "__main__":
    main()
