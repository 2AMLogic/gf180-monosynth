#!/usr/bin/env python3
"""The voice past the filter: oscillators, and the waveforms we do not have.

    .venv/bin/python model/reference_voice.py --stage osc --out /tmp/refvoice

`docs/discrimination.md` section 8 measured the FILTER against three
references and found two real defects. The oscillators, envelopes, glide and
noise had never been compared to anything. This is the oscillator half.

Two different jobs, kept apart:

  COMPARE   where we have the thing. Harmonic amplitudes against the
            closed-form ideal waveform, and aliasing at high notes, ours
            against Surge XT and Arturia Mini V3 at matched pitch.
  TARGET    where we do not. The Model D has six waveforms per oscillator and
            we have four of them; the SHARK-TOOTH (saw/triangle hybrid) has no
            counterpart on our side, so the job there is not comparison but
            producing a declared target someone can build against.

Diva is not in this study: it is a general analogue-modelling synth, not a
Minimoog emulation, and it was additionally found to be running unlicensed
(`docs/reference-integrity.md` section 1).

**What is and is not comparable.** Ours is measured with `voice_fx.OscFx`
alone -- no filter, no envelope, nothing else in the path. Surge is measured
with its filter set to Off, which is a true bypass. **Mini V3's filter cannot
be bypassed**, so it is measured with the cutoff knob at maximum and its
residual response is a systematic that is stated rather than corrected. That
asymmetry is CONSERVATIVE for us on aliasing: a filter in the path can only
remove aliases, so if ours aliases less than Mini V3's it does so against a
handicap, and if it aliases more the margin is a lower bound.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "audition"))

import audio_measure as am                                          # noqa: E402
import reference_rigs as rr                                         # noqa: E402
import voice_fx as vf                                               # noqa: E402

SR = rr.SR
KMAX = 12
NOTES = [33, 45, 57, 69, 81, 93]          # A1 .. A6


def ideal_db(shape: str, k: int, duty: float = 0.5) -> float | None:
    """Closed-form harmonic amplitude relative to the fundamental, in dB."""
    def a(n):
        if shape == "saw":
            return 1.0 / n
        if shape == "tri":
            return 1.0 / n ** 2 if n % 2 else 0.0
        return abs(math.sin(math.pi * n * duty)) / n      # pulse, duty 0.5 = square
    return None if abs(a(k)) < 1e-12 else 20 * math.log10(abs(a(k)) / a(1))


def ours_tone(wave, note, seconds=0.5, blep=True):
    o = vf.OscFx(wave, blep=blep)
    inc = vf.phase_inc(vf.note_hz(note))
    return np.asarray(o.render(int(seconds * SR), inc), dtype=np.float64) / 32768.0


def duty_from_harmonics(sig, kmax=KMAX, dip_db=12.0):
    """A pulse's duty cycle from where its harmonic nulls fall: a duty of 1/m
    has a null at every m-th harmonic. Measured, not taken from a knob with no
    units.

    A real instrument's null is a DIP, not an absence -- an analogue-modelled
    pulse is never exactly 1/m -- so a harmonic counts as a null if it is
    `dip_db` below both of its neighbours, as well as if the estimator refused
    it outright. **A spectrum cannot tell duty d from 1 - d**: they are
    identical, so the answer is always reported as a pair."""
    def lv(k):
        v = sig.get(f"h{k}")
        return -200.0 if v is None else v
    nulls = [k for k in range(2, kmax) if lv(k) < lv(k - 1) - dip_db and lv(k) < lv(k + 1) - dip_db]
    present = [k for k in range(2, kmax + 1) if sig.get(f"h{k}") is not None]
    if not nulls:
        return None, present, nulls
    return 1.0 / min(nulls), present, nulls


def measure(y, f0, tag):
    s = am.harmonic_signature(y, SR, f0=f0, kmax=KMAX)
    # A saw, pulse or triangle cannot have a harmonic ABOVE its fundamental:
    # every one of them has |a_n| <= |a_1|. A row that does is not a
    # measurement of that waveform -- it means the commanded f0 is not the
    # signal's f0, i.e. the rig is not making the waveform it was asked for.
    # Refuse the row rather than print it; the first run published a Surge
    # "square" with h2 at +79.6 dB.
    bad = [k for k in range(2, KMAX + 1)
           if s.get(f"h{k}") is not None and s[f"h{k}"] > 0.0]
    s["valid"] = not bad
    s["invalid_harmonics"] = bad
    al = am.inharmonic_fraction_db(y, f0, SR)
    s["inharmonic_db"] = al.value if al.ok else None
    s["tag"] = tag
    return s


def stage_osc(out):
    devices = {}
    rows = []
    surge = rr.SurgeRig("Type 2")
    mini = rr.MiniV3Rig()
    try:
        plan = [("ours", None, ["saw", "square", "pulse25", "tri", "sine"]),
                ("surge", surge, ["saw", "square", "pulse25", "sine"]),
                ("miniv3", mini, list(rr.MiniV3Rig.WAVES))]
        for name, dev, waves in plan:
            for w in waves:
                for note in NOTES:
                    f0 = vf.note_hz(note)
                    if f0 * 2 >= SR / 2:
                        continue
                    y = ours_tone(w, note) if dev is None else dev.osc_tone(w, note)
                    r = measure(y, f0, f"{name}/{w}/{note}")
                    r.update(device=name, wave=w, note=note, f0_cmd=f0)
                    rows.append(r)
            print(f"  {name}: {len(waves)} waveforms x {len(NOTES)} pitches", flush=True)
    finally:
        del surge, mini
    json.dump(rows, open(os.path.join(out, "osc.json"), "w"), indent=1, default=str)
    report_osc(rows)
    return rows


def _fmt(v, w=7):
    return (" " * (w - 3) + "---") if v is None else f"{v:{w}.1f}"


def report_osc(rows):
    print("\n" + "=" * 100)
    print("1. HARMONIC SERIES at A2 (110 Hz), dB relative to the fundamental")
    print("=" * 100)
    print(f"{'device/wave':22s} " + " ".join(f"{'h'+str(k):>7s}" for k in range(2, 10)))
    for shape, duty, lbl in (("saw", 0.5, "IDEAL saw"), ("pulse", 0.5, "IDEAL square"),
                             ("pulse", 0.25, "IDEAL 25% pulse"), ("tri", 0.5, "IDEAL triangle")):
        print(f"{lbl:22s} " + " ".join(_fmt(ideal_db(shape, k, duty)) for k in range(2, 10)))
    print("-" * 100)
    for r in [r for r in rows if r["note"] == 45]:
        if not r.get("valid", True):
            print(f"{r['device'] + '/' + r['wave']:22s} "
                  f"REFUSED: harmonics above the fundamental at {r['invalid_harmonics']}"
                  f" -- this rig is not making the waveform it was asked for")
            continue
        print(f"{r['device'] + '/' + r['wave']:22s} "
              + " ".join(_fmt(r.get(f"h{k}")) for k in range(2, 10)))

    print("\n" + "=" * 100)
    print("2. WHICH RECTANGULAR IS OURS?  duty cycle read from the harmonic nulls")
    print("=" * 100)
    for r in [r for r in rows if r["note"] == 45 and r.get("valid", True) and
              r["wave"] in ("square", "pulse25", "wide_rect", "narrow_rect")]:
        duty, present, absent = duty_from_harmonics(r)
        print(f"  {r['device'] + '/' + r['wave']:22s} nulls at harmonics {absent[:6]}"
              f"   -> duty {'unknown' if duty is None else f'{duty * 100:.1f} % (or {100 - duty * 100:.1f} %)'}")

    print("\n" + "=" * 100)
    print("3. ALIASING: inharmonic energy, dB of total, at rising pitch")
    print("=" * 100)
    notes = sorted({r["note"] for r in rows})
    print(f"{'device/wave':22s} " + " ".join(f"{vf.note_hz(n):7.0f}" for n in notes))
    keys = sorted({(r["device"], r["wave"]) for r in rows})
    for dv, w in keys:
        vals = []
        for n in notes:
            m = [r for r in rows if r["device"] == dv and r["wave"] == w and r["note"] == n]
            vals.append(m[0].get("inharmonic_db") if m else None)
        print(f"{dv + '/' + w:22s} " + " ".join(_fmt(v) for v in vals))
    print("  less negative = more inharmonic energy. Mini V3 carries its own filter at maximum")
    print("  cutoff (it cannot be bypassed), which can only REMOVE aliases, so its column is a")
    print("  best case for it and the margin against ours is a lower bound.")

    print("\n" + "=" * 100)
    print("4. TARGET: the shark-tooth we do not have (Mini V3's 'saw-triangular')")
    print("=" * 100)
    sh = [r for r in rows if r["device"] == "miniv3" and r["wave"] == "shark"]
    for r in sorted(sh, key=lambda r: r["note"]):
        print(f"  {vf.note_hz(r['note']):7.1f} Hz  "
              + " ".join(f"h{k} {_fmt(r.get(f'h{k}'), 6)}" for k in range(2, 8))
              + f"   inharmonic {_fmt(r.get('inharmonic_db'), 6)}")
    print("  A saw has h_n = 1/n (-6.0, -9.5, -12.0 dB) and a triangle 1/n^2 on odd harmonics")
    print("  only (-19.1 at h3). A hybrid sits between them and has BOTH an amplitude and a")
    print("  slope discontinuity, so a generator needs BLEP and BLAMP; we have PolyBLEP only.")


# ===========================================================================
# NOISE: target-setting, because we have no noise source at all
# ===========================================================================
def noise_report(y, ref_rms, tag):
    """Everything the mono-synth agent needs to build a noise source to, from
    a reference that has one. No comparison side exists on our part."""
    y = np.asarray(y, dtype=np.float64)
    out = dict(tag=tag, rms=float(am.rms(y)), peak=float(am.peak(y)),
               crest_db=float(am.db(am.peak(y), am.rms(y))),
               vs_osc_db=float(am.db(am.rms(y), ref_rms)) if ref_rms else None,
               seconds=len(y) / SR)
    sl = am.psd_slope_db_oct(y, (100.0, 15000.0), SR)
    out["slope_db_oct"] = sl.value if sl.ok else None
    out["slope_why"] = None if sl.ok else sl.reason
    out["slope_resid_db"] = sl.detail.get("residual_db") if sl.ok else None
    rp = am.repeat_period(y, SR, max_lag_s=min(5.0, len(y) / SR / 2 - 0.1))
    out["repeat_s"] = rp.value if rp.ok else None
    out["repeat_corr"] = rp.detail.get("corr") if rp.ok else rp.detail.get("best_corr")
    out["repeat_why"] = None if rp.ok else rp.reason
    # Gaussian or not: a 1-bit LFSR is +-1 and has a crest factor of 0 dB,
    # true Gaussian noise about 12 dB over a long record.
    n = y / (am.rms(y) or 1.0)
    out["kurtosis"] = float(np.mean(n ** 4))
    out["frac_within_1sd"] = float(np.mean(np.abs(n) < 1.0))
    return out


def stage_noise(out, seconds=8.0):
    rows = []
    surge, mini = rr.SurgeRig("Type 2"), rr.MiniV3Rig()
    try:
        for name, dev, colours in (("surge", surge, {"white(0%)": 0.5, "dark(-100%)": 0.0,
                                                     "bright(+100%)": 1.0}),
                                   ("miniv3", mini, {"white": 0.0, "pink": 1.0})):
            ref = float(am.rms(dev.osc_level_ref()))
            for cname, cv in colours.items():
                y = dev.noise_tone(seconds, cv)
                r = noise_report(y, ref, f"{name}/{cname}")
                r.update(device=name, colour=cname)
                rows.append(r)
                print(f"  {name}/{cname}: rms {r['rms']:.4f} slope "
                      f"{r['slope_db_oct'] if r['slope_db_oct'] is None else round(r['slope_db_oct'],2)}"
                      f" dB/oct", flush=True)
    finally:
        del surge, mini
    json.dump(rows, open(os.path.join(out, "noise.json"), "w"), indent=1, default=str)
    report_noise(rows)
    return rows


def report_noise(rows):
    print("\n" + "=" * 100)
    print("NOISE TARGETS -- we have no noise source, so none of this is a comparison")
    print("=" * 100)
    print(f"{'source':22s} {'slope':>10} {'resid':>7} {'vs saw':>8} {'crest':>7} "
          f"{'kurtosis':>9} {'repeats at':>12}")
    print(f"{'':22s} {'dB/oct':>10} {'dB':>7} {'dB':>8} {'dB':>7} {'':>9} {'':>12}")
    for r in rows:
        rep = ("no repeat" if r["repeat_s"] is None
               else f"{r['repeat_s']:.4f} s")
        print(f"{r['tag']:22s} {_fmt(r.get('slope_db_oct'), 10)} "
              f"{_fmt(r.get('slope_resid_db'), 7)} {_fmt(r.get('vs_osc_db'), 8)} "
              f"{_fmt(r.get('crest_db'), 7)} {r['kurtosis']:9.2f} {rep:>12}")
    print("  slope: white is 0.00, pink is -3.01 dB/oct, both exactly.")
    print("  vs saw: the noise's RMS relative to that instrument's own sawtooth at the SAME")
    print("     mixer setting -- the number a mix balance is built from.")
    print("  crest: peak over RMS. Gaussian noise is about 12 dB over a long record; a 1-bit")
    print("     LFSR output is exactly 0 dB.  kurtosis: Gaussian is 3.0, a +-1 square is 1.0.")
    print("  repeats at: the lag where the record repeats itself, or a refusal. A maximal")
    print("     16-BIT LFSR AT 48 kHz REPEATS AT 1.365313 s, which is audibly a loop on a held")
    print("     note; the estimator recovers that to 2 samples (test_reference_voice.py).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="osc", choices=["osc", "noise"])
    ap.add_argument("--out", default="/tmp/refvoice")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    (stage_osc if a.stage == "osc" else stage_noise)(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
