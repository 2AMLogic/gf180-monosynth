#!/usr/bin/env python3
"""The four measurement defects of #101/#103, #118, #119 and #108, each shown
producing its WRONG number beside the repaired one.

    .venv/bin/python tools/probes/estimator_defects.py
    .venv/bin/python tools/probes/estimator_defects.py --all-voices

This file exists because of `tools/probes/hihat/hh_probe4.py`, whose whole job
was to record that an earlier result of 7.2 was actually 30.6. **A record of a
result that looked good and was wrong is worth more than one that was right
first time, and it is exactly the file that gets deleted.** Every "shipped"
function below is a faithful reimplementation of the code as it stood before
the repair, so the red number stays reproducible after the red is gone.

It exits non-zero if any repaired invariant fails, so it is a check and not
only a story.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sys

import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "tools"))

import audio_measure as am                                          # noqa: E402
import run_case as rc                                               # noqa: E402

REFS = pathlib.Path(rc.REFS_DEFAULT)
SR = 48000
fails: list[str] = []


def check(ok: bool, what: str):
    print(f"      {'OK  ' if ok else 'FAIL'}  {what}")
    if not ok:
        fails.append(what)


# ===========================================================================
# 1. #101 / #103 -- the lead, and the clamp that was the bug
# ===========================================================================
def prepare_shipped(x, sr):
    """`prepare()` exactly as it stood before the repair. The `max(0, ...)` is
    the defect: an onset closer to the start than 1 ms cannot be given a 1 ms
    lead, so it silently got whatever was there."""
    x = np.asarray(x, dtype=np.float64)
    if am.is_silent(x):
        return x
    pk = float(np.abs(x).max())
    i = int(np.argmax(np.abs(x) > 0.02 * pk))
    lead = max(0, i - int(1e-3 * sr))                       # <-- the clamp
    if lead >= int(5e-3 * sr):
        x = x - float(x[:lead].mean())
    y = x[lead:]
    p = float(np.abs(y).max())
    return y / p if p > 0 else y


def window_shipped(y, sr, t0, t1):
    a = int(t0 * sr)
    b = len(y) if t1 is None else min(len(y), int(t1 * sr))
    return y[a:b]


def split_db_shipped(y, sr, sound, t0, t1):
    lo, hi = rc.BAND[sound]
    return rc.band_ratio_db(window_shipped(y, sr, t0, t1), sr, rc.SPLIT_HZ[sound], lo, hi)


def defect_1(voices):
    print("\n" + "=" * 78)
    print("1. #101 / #103 -- the two sides of every drum comparison were filtered")
    print("   under different boundary conditions, and nothing said so.")
    print("=" * 78)
    for sr in (48000, 44100):
        bp = rc._bandpass_sos(sr, 20.0, 400.0)
        lp = butter(4, 400 / (sr / 2), btype="lowpass", output="sos")
        print(f"   sr {sr}: 4th-order BAND-pass {len(bp)} sections, padlen "
              f"{rc._sosfiltfilt_padlen(bp)} = {rc._sosfiltfilt_padlen(bp)/sr*1e3:.3f} ms"
              f"   |   4th-order low-pass padlen {rc._sosfiltfilt_padlen(lp)}"
              f" = {rc._sosfiltfilt_padlen(lp)/sr*1e3:.3f} ms")
    print("   #101 and #103 both quote the LOW-pass figure. Every lead budget")
    print("   derived from 0.3 ms was half what it should have been.\n")

    print(f"   {'voice':<6}{'ref lead':>10}{'our lead':>10}{'SHIPPED err':>13}"
          f"{'REPAIRED err':>14}{'tol':>7}{'moved':>8}")
    for v in voices:
        ref_x, ref_sr, rel, _ = rc.load_reference(v, REFS)
        our_x, our_sr = rc.render_drum_solo(v)
        name = next(n for n, _u, _e, _t in rc.DRUM_PLAN[v]
                    if "spectrum" in n or "energy" in n.lower() or "balance" in n)
        est = next(e for n, _u, e, _t in rc.DRUM_PLAN[v] if n == name)
        old = [split_db_shipped(prepare_shipped(x, s), s, v, 0.0, 0.150)
               for x, s in ((our_x, our_sr), (ref_x, ref_sr))]
        new = [est(rc.prepare(x, s), s) for x, s in ((our_x, our_sr), (ref_x, ref_sr))]
        ref_lead = int(np.argmax(np.abs(ref_x) > 0.02 * np.abs(ref_x).max())) / ref_sr * 1e3
        our_lead = 1.0
        oe = old[0].value - old[1].value if old[0].ok and old[1].ok else float("nan")
        ne = new[0].value - new[1].value if new[0].ok and new[1].ok else float("nan")
        print(f"   {v:<6}{ref_lead:>9.2f}m{our_lead:>9.2f}m{oe:>13.3f}{ne:>14.3f}"
              f"{3.0:>7.1f}{ne-oe:>8.3f}")
    print("   (lead in ms of TRUE pre-onset silence the SHIPPED path gave each side;")
    print("    the pad it has to clear is 0.562 ms at 48 k and 0.612 ms at 44.1 k)")

    print("\n   The invariance that would have caught it, without knowing any answer.")
    print("   The strike starts 7 samples in, which is where the Fischer references")
    print("   start: inside the clamp. Prepending silence takes it OUT of the clamp,")
    print("   and the shipped number moves although the sound did not.")
    x = np.zeros(int(0.6 * SR))
    t = np.arange(len(x) - 7) / SR
    x[7:] = np.exp(-t / 0.040) * np.sin(2 * math.pi * 220 * t)
    for pad_ms in (0.0, 0.5, 5.0, 500.0):
        p = np.concatenate([np.zeros(int(pad_ms * 1e-3 * SR)), x])
        o = split_db_shipped(prepare_shipped(p, SR), SR, "LC", 0.0, 0.150)
        n = rc.DRUM_PLAN["LC"][1][2](rc.prepare(p, SR), SR)
        print(f"      prepend {pad_ms:6.1f} ms of silence:  shipped {o.value:8.3f} dB"
              f"   repaired {n.value:8.3f} dB")
    base_o = split_db_shipped(prepare_shipped(x, SR), SR, "LC", 0.0, 0.150).value
    worst_o = max(abs(split_db_shipped(prepare_shipped(
        np.concatenate([np.zeros(int(p * 1e-3 * SR)), x]), SR), SR, "LC", 0.0, 0.150).value - base_o)
        for p in (0.5, 5.0, 500.0))
    base_n = rc.DRUM_PLAN["LC"][1][2](rc.prepare(x, SR), SR).value
    worst_n = max(abs(rc.DRUM_PLAN["LC"][1][2](rc.prepare(
        np.concatenate([np.zeros(int(p * 1e-3 * SR)), x]), SR), SR).value - base_n)
        for p in (0.5, 5.0, 500.0))
    print(f"      shipped swings {worst_o:.3f} dB from prepended silence alone;"
          f" repaired {worst_n:.6f} dB")
    print("   On a synthetic strike the swing is under a dB; on the real congas above")
    print("   it is 3.5-4.8 dB, because how much it is worth depends on how little")
    print("   energy the numerator band holds -- which is the sound, not the filter.")
    check(worst_o > 0.1, "the shipped path really was non-invariant (this is the defect)")
    check(worst_n < 0.01, "the repaired path is invariant to prepended silence")


# ===========================================================================
# 2. #119 -- a floor quoted as a constant that is not one
# ===========================================================================
def _addsaw(f0, n):
    t = np.arange(n) / SR
    y = sum(np.sin(2 * math.pi * k * f0 * t) / k for k in range(1, int(SR / 2 / f0)))
    return y / np.abs(y).max()


def _naivesaw(f0, n):
    t = np.arange(n) / SR
    y = 2 * ((f0 * t) % 1.0) - 1.0
    return y / np.abs(y).max()


def inharmonic_shipped(x, f0, sr, guard=5):
    """Hann-windowed, as it stood. The docstring quoted its floor as a constant
    "about -54 dB"; the table below is what that constant actually is."""
    n = len(x)
    p = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
    harm = am._harmonic_mask(n, f0, sr, guard)
    return 10.0 * math.log10(max(p[~harm].sum(), 1e-300) / p.sum())


def defect_2():
    print("\n" + "=" * 78)
    print("2. #119 / #92 -- the aliasing floor is not -54 dB, it is whatever f0 makes it")
    print("=" * 78)
    n = int(0.5 * SR)
    print(f"   {'f0':>10}{'on a bin':>10}{'HANN floor':>12}{'BH4 floor':>12}"
          f"{'HANN answer':>13}{'BH4 answer':>12}{'answer moved':>14}")
    swing = []
    for f0 in (110.0, 111.0, 111.3, 261.626, 440.0, 441.0, 1000.0):
        onbin = abs(f0 / (SR / n) - round(f0 / (SR / n))) < 1e-9
        free, naive = _addsaw(f0, n), _naivesaw(f0, n)
        fh = inharmonic_shipped(free, f0, SR)
        fb = am.inharmonic_fraction_db(free, f0, SR)
        ah = inharmonic_shipped(naive, f0, SR)
        ab = am.inharmonic_fraction_db(naive, f0, SR)
        swing.append(fh)
        print(f"   {f0:>10.3f}{str(onbin):>10}{fh:>12.2f}{fb.value:>12.2f}"
              f"{ah:>13.2f}{ab.value:>12.2f}{ab.value-ah:>14.2f}")
        check(abs(fb.detail["headroom_db"]) < 1.0,
              f"f0 {f0}: the measured floor equals the alias-free reading")
    print(f"   the Hann floor swings {max(swing)-min(swing):.1f} dB across these f0."
          f"  A constant would be a lie.")


# ===========================================================================
# 3. #118 -- a level guard cannot see truncation
# ===========================================================================
def t20_shipped(x, sr, lo_db=-5.0, hi_db=-25.0, margin_db=10.0):
    """The level guard as it stood: refuse when the backward-integrated curve's
    LAST value is above -35 dB. The curve of any finite record falls towards
    -inf at its last sample, so this sees almost nothing."""
    e = np.cumsum((np.asarray(x, float) ** 2)[::-1])[::-1]
    L = 10.0 * np.log10(np.maximum(e / e[0], 1e-30))
    tail = float(L[-1])
    if tail > hi_db - margin_db:
        return None, tail
    i_lo, i_hi = int(np.argmax(L <= lo_db)), int(np.argmax(L <= hi_db))
    if i_hi <= i_lo + 8:
        return None, tail
    t = np.arange(i_lo, i_hi) / sr
    slope = np.polyfit(t, L[i_lo:i_hi], 1)[0]
    return (-20.0 / float(slope) if slope < 0 else None), tail


def defect_3():
    print("\n" + "=" * 78)
    print("3. #118 -- the truncation guard was a level, and truncation is a length")
    print("=" * 78)
    tau = 0.040
    exact = math.log(10) * tau * 1e3
    t = np.arange(SR) / SR
    x0 = np.exp(-t / tau) * np.sin(2 * math.pi * 220 * t)
    print(f"   a single exponential, tau {tau*1e3:.0f} ms, exact T20 {exact:.2f} ms\n")
    print(f"   {'record':>9}{'T20 read':>10}{'error':>9}{'tail_db':>10}"
          f"{'SHIPPED guard':>15}{'in T20s':>9}{'LENGTH guard':>14}")
    for sec in (1.0, 0.5, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05):
        y = x0[:int(sec * SR)]
        old, tail = t20_shipped(y, SR)
        new = am.schroeder_t20(y, SR)
        ratio = (new.detail or {}).get("tail_in_t20s", float("nan"))
        print(f"   {sec*1e3:>8.0f}m{(old or 0)*1e3:>10.2f}"
              f"{100*((old or 0)*1e3/exact-1):>8.1f}%{tail:>10.1f}"
              f"{'passed' if old else 'refused':>15}{ratio:>9.2f}"
              f"{'passed' if new.ok else 'REFUSED':>14}")
    old100, tail100 = t20_shipped(x0[:int(0.1 * SR)], SR)
    check(old100 is not None and abs(old100 * 1e3 / exact - 1) > 0.15,
          f"the shipped guard passed a 100 ms cut at {100*(old100*1e3/exact-1):.1f} % error"
          f" with tail_db {tail100:.1f} (it wanted -35)")
    check(not am.schroeder_t20(x0[:int(0.1 * SR)], SR).ok,
          "the length guard refuses that same record")
    check(am.schroeder_t20(x0[:int(0.3 * SR)], SR).ok,
          "and does not refuse one that does contain its decay")


# ===========================================================================
# 4. #108 -- a rig that names a frequency instead of finding one
# ===========================================================================
def tone_ratio_shipped(x, sr, hz_num, hz_den):
    a, b = am.tone_amplitude(x, hz_num, sr), am.tone_amplitude(x, hz_den, sr)
    return 20.0 * math.log10(a.value / b.value)


def defect_4():
    print("\n" + "=" * 78)
    print("4. #108 -- the cowbell was probed at 540 / 800 Hz. Its lines are elsewhere.")
    print("=" * 78)
    ref_x, ref_sr, rel, _ = rc.load_reference("CB", REFS)
    our_x, our_sr = rc.render_drum_solo("CB")
    for label, x, sr in (("reference " + rel, ref_x, ref_sr), ("ours", our_x, our_sr)):
        y = rc.window(rc.prepare(x, sr), sr, 0.0, 0.100)
        lo, hi = rc.find_line(y, sr, 540.0), rc.find_line(y, sr, 800.0)
        old = tone_ratio_shipped(y, sr, 800.0, 540.0)
        new = rc.tone_ratio_db(y, sr, 800.0, 540.0)
        d_old = tone_ratio_shipped(y, sr, 260.0, 800.0)
        d_new = rc.difference_tone_db(y, sr, 800.0, 540.0)
        print(f"   {label}")
        print(f"      lines found        {lo.value:8.2f} Hz ({lo.detail['offset_pct']:+5.2f} %"
              f" off 540)   {hi.value:8.2f} Hz ({hi.detail['offset_pct']:+5.2f} % off 800)")
        print(f"      partial balance    nominal probe {old:+8.2f} dB"
              f"   measured lines {new.value:+8.2f} dB   moved {new.value-old:+6.2f}")
        print(f"      difference tone    nominal 260 Hz {d_old:+8.2f} dB"
              f"   at {d_new.detail['diff_hz']:6.2f} Hz {d_new.value:+8.2f} dB"
              f"   moved {d_new.value-d_old:+6.2f}")
        print(f"                         its own leakage floor {d_new.detail['floor_db']:+8.2f} dB,"
              f" headroom {d_new.detail['headroom_db']:.1f} dB")
    print("   The difference tone moved by tens of dB on BOTH sides: a rectangular")
    print("   projection at 260 Hz was reading the two partials' leakage, not a tone.")
    t = np.arange(int(0.1 * SR)) / SR
    two = 1.0 * np.sin(2 * math.pi * 823.70 * t) + 0.5 * np.sin(2 * math.pi * 558.35 * t)
    check(abs(tone_ratio_shipped(two, SR, 800.0, 540.0) - 20 * math.log10(2.0)) > 1.0,
          "the nominal probe is wrong on two partials at the machine's own frequencies")
    check(abs(rc.tone_ratio_db(two, SR, 800.0, 540.0).value - 20 * math.log10(2.0)) < 0.2,
          "finding the lines gets the closed-form answer")
    check(not rc.difference_tone_db(two, SR, 800.0, 540.0).ok,
          "and a difference tone that is not there is refused, not reported")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all-voices", action="store_true",
                    help="section 1 over all sixteen sounds (slow: sixteen renders)")
    a = ap.parse_args()
    if not REFS.exists():
        print(f"the Fischer corpus is not at {REFS}", file=sys.stderr)
        return 2
    voices = sorted(rc.REF_MAIN) if a.all_voices else ["LC", "HC", "MC"]
    defect_1(voices)
    defect_2()
    defect_3()
    defect_4()
    print("\n" + "=" * 78)
    if fails:
        print(f"{len(fails)} check(s) FAILED:")
        for f in fails:
            print(f"   {f}")
        return 1
    print("every repaired invariant holds, and every defect is still reproducible above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
