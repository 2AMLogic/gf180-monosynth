#!/usr/bin/env python3
"""Render the integer drum section to WAV so a human can judge it, and
balance the reference kit's levels.

    .venv/bin/python model/drums_fx_render.py            # every render below into audio/drums/
    .venv/bin/python model/drums_fx_render.py --balance  # per-voice peaks and the amp scale each needs

Every WAV is the model's own int16 output, UNNORMALISED: what the chip would
put on the I2S bus at the gains stated in the file name. The normalising WAV
writer of the audition (dsp.to_wav16) is deliberately not used here -- it is
what hid the four clipping patches of DR 0005.

Renders (48 kHz, 16-bit mono):
    00-solo-<stop>.wav       one hit of each stop at accent 1.0, then 1.4, then 0.6
    01-all-eight-at-once.wav every stop in one frame at accent 1.4: the loudest intended hit
    02-groove-808.wav        a two-bar 808 pattern with accents, closed/open hats and the choke
    03-groove-toms.wav       toms and congas-style fills against the kick
    04-groove-claps.wav      clap, cowbell and hats
    05-combined.wav          the DR 0007 milestone (05-combined-drums-at-0.30.wav: the same with the drum buses at 0.30): a bass line through the voice (the
                             growl-bass patch) with the drums, through output_fx at the
                             reference gains, unnormalised: bass release while drums ring,
                             every drum soloed, simultaneous hits, the loudest combination
    06-bd-decay-short-mid-long.wav  the BD at the three DECAY presets of the reference
    07-bd-plain-then-attack-shift.wav  the BD with and without the 4 ms / 130 Hz attack window, as host writes
"""
from __future__ import annotations
import argparse, os, sys, wave
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "audition"))
import numpy as np
import drums_fx as dx
import voice_fx as vf
import patches
from dsp import SR

OUT = os.path.join(os.path.dirname(HERE), "audio", "drums")
DVOL = BVOL = 0.45                  # the reference gains of the two drum buses, as the voice's vol (DR 0005)


def write_wav(name: str, samples: np.ndarray):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    peak = np.abs(samples.astype(np.int64)).max() / 32768.0
    clip = int(np.sum(np.abs(samples.astype(np.int64)) >= 32767))
    print(f"  {os.path.relpath(p)}: {len(samples)/SR:.2f} s, peak {peak:.3f} x FS, {clip} samples at the rail")


def drums_only(hits, seconds: float, kit=None, dvol=DVOL, bvol=BVOL, extra_writes=()):
    d = dx.DrumsFx()
    n = int(seconds * SR)
    w = dx.hit_writes(hits, dx.kit_808() if kit is None else kit)
    w = sorted(w + list(extra_writes), key=lambda t: t[0])
    dm, bd = d.play(w, n)
    return dx.output_fx(np.zeros(n), 0, dm, dx.accent_reg(dvol), bd, dx.accent_reg(bvol)), d


def balance():
    """Each voice alone at accent 1.0: its peak on each bus and the factor
    its amps (or, for the mix-bus voices, its envelope peaks) need to land on
    the target -- Roland's chart's proportions (reference 1.6) with the
    loudest at 0.5 x full scale on the bus."""
    target = dict(BD=0.5, SD=0.43, LT=0.5, HT=0.5, CH=0.43, OH=0.5, CP=0.5, CB=0.5)
    d = dx.DrumsFx()
    n = int(0.4 * SR)
    print("voice   dmix peak (FS)   body peak (FS)   state peak (FS)   amp/peak scale to target")
    for s, name in enumerate(dx.STOP_NAMES):
        d.reset()
        dm, bd = d.play(dx.hit_writes([(10, s, 1.0)], dx.kit_808()), n)
        pk_m, pk_b = np.abs(dm).max() / 32768, np.abs(bd).max() / 32768
        st = max(abs(v) for v in d.bank.y1) / 32768
        pk = pk_m if name == "CP" else pk_b
        print(f"  {name:4s}  {pk_m:12.3f}    {pk_b:12.3f}    {st:12.1f}         x {target[name] / max(pk, 1e-9):.4f}")


def solo_renders():
    for s, name in enumerate(dx.STOP_NAMES):
        hits = [(int(0.05 * SR), s, 1.0), (int(0.75 * SR), s, 1.4), (int(1.45 * SR), s, 0.6)]
        out, _ = drums_only(hits, 2.2)
        write_wav(f"00-solo-{s}-{name}.wav", out)


def all_at_once():
    hits = [(int(0.05 * SR), s, 1.4) for s in range(8)] + [(int(1.0 * SR), s, 1.0) for s in range(8)]
    out, d = drums_only(hits, 2.0)
    write_wav("01-all-eight-at-once.wav", out)
    bd = d.trace["body"]
    print(f"    body bus peak {np.abs(bd).max() / 32768:.3f} x FS (word is +-8.0); "
          f"mix bus peak {np.abs(d.trace['dmix']).max() / 32768:.3f} x FS")


PATTERN_808 = dx.PATTERN_808
PATTERN_TOMS = {"BD": "X.......X.......", "LT": "....x.x.....xx..", "HT": "..x.......x...x.",
                "CH": "x.x.x.x.x.x.x.x.", "SD": "....X.......X..o"}
PATTERN_CLAP = {"CP": "....X.......X...", "CB": "x..x..x...x..x..", "CH": "x.xxx.xxx.xxx.xx",
                "OH": "...x......x.....", "BD": "x...x...x...x..."}


def grooves():
    for name, pat, bpm, sw in (("02-groove-808", PATTERN_808, 118.0, 0.0),
                               ("03-groove-toms", PATTERN_TOMS, 104.0, 0.0),
                               ("04-groove-claps", PATTERN_CLAP, 124.0, 0.12)):
        hits = dx.pattern_hits(pat, bpm=bpm, bars=2, swing=sw, start_s=0.05)
        secs = 60.0 / bpm * 4 * 2 + 1.0
        out, _ = drums_only(hits, secs)
        write_wav(f"{name}.wav", out)


def bd_decays():
    """The three DECAY positions of reference 2's table, as coefficient
    writes while the previous hit still rings (a host may retune any frame)."""
    hits, extra = [], []
    for i, (q, label) in enumerate(((5.2, "short"), (22.3, "mid"), (62.0, "long"))):
        f = int((0.05 + 1.2 * i) * SR)
        extra += [(f - 1, a, v) for a, v in dx.mode_writes(dx.M_BD, 56.0, q, 0.0)[:2]]
        hits += [(f, dx.BD, 1.0), (f + int(0.6 * SR), dx.BD, 1.0)]
    kit = dx.kit_808()
    out, _ = drums_only(hits, 3.7, kit=kit, extra_writes=extra)
    write_wav("06-bd-decay-short-mid-long.wav", out)


def bd_attack_shift():
    """Reference 2's BD attack: for the first 4 ms the resonator sits at
    ~130 Hz, Q ~6, then returns to 56 Hz -- a host sequence of two
    coefficient writes per hit (open item 17.14), shown beside the plain
    hit: plain, shifted, plain, shifted."""
    hits, extra = [], []
    for i in range(4):
        f = int((0.05 + 0.7 * i) * SR)
        hits.append((f, dx.BD, 1.0))
        if i % 2:
            extra += [(f, a, v) for a, v in dx.mode_writes(dx.M_BD, 130.0, 6.1, 0.0)[:2]]
            extra += [(f + 192, a, v) for a, v in dx.mode_writes(dx.M_BD, 56.0, 22.3, 0.0)[:2]]
    out, _ = drums_only(hits, 2.9, extra_writes=extra)
    write_wav("07-bd-plain-then-attack-shift.wav", out)


def combined(dgain: float = DVOL, suffix: str = ""):
    """The milestone render: bass (growl-bass through the integer voice) and
    drums through the one output stage, unnormalised. `dgain` is the two
    drum buses' gain; the reference 0.45 clips a few samples where all
    eight accented stops land under a bass note, 0.30 does not."""
    total = 12.0
    n = int(total * SR)
    # the bass line: growl-bass's patch, a two-bar riff repeated, gate 80 %
    name, seq, _ = next(p for p in patches.MONO if p[0].endswith("growl-bass"))
    kw = dict(seq[0][3])
    bpm = 118.0; step = 60.0 / bpm / 4.0
    riff = [(0, 33), (3, 33), (6, 40), (8, 33), (11, 31), (12, 33), (14, 35)]
    line = []
    for bar in range(4):
        for st, note in riff:
            line.append(((bar * 16 + st) * step + 0.05, note, step * 2.4, kw))
    v = vf.VoiceFx()
    vf.render_mono_fx(line, total, v)
    vca = v.trace["vca"]
    # drums: two bars of the 808 groove, then every stop soloed with the bass ringing, then all eight
    hits = dx.pattern_hits(PATTERN_808, bpm=bpm, bars=2, start_s=0.05)
    t = 0.05 + 32 * step + 0.5
    for s in range(8):
        hits.append((int(t * SR), s, 1.0)); t += 0.45
    hits += [(int(t * SR), s, 1.4) for s in range(8)]
    t += 1.0
    hits += dx.pattern_hits(PATTERN_808, bpm=bpm, bars=1, start_s=t)
    hits = [h for h in hits if h[0] < n - 2]
    d = dx.DrumsFx()
    dm, bd = d.play(dx.hit_writes(hits, dx.kit_808()), n)
    g = dx.accent_reg(dgain)
    out = dx.output_fx(vca, vf.VOL_REF, dm, g, bd, g)
    write_wav(f"05-combined{suffix}.wav", out)
    print(f"    voice peak {np.abs((vca * vf.VOL_REF) >> 15).max() / 32768:.3f}, "
          f"drum mix {np.abs((dm * g) >> 15).max() / 32768:.3f}, "
          f"body {np.abs((bd.astype(np.int64) * g) >> 15).max() / 32768:.3f} x FS before the sum, "
          f"drum gains {dgain}")


def combined_030():
    combined(0.30, "-drums-at-0.30")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--balance", action="store_true")
    ap.add_argument("--only", default=None, help="solo|all|grooves|bd|combined")
    a = ap.parse_args(argv)
    if a.balance:
        balance(); return 0
    jobs = dict(solo=solo_renders, all=all_at_once, grooves=grooves, bd=bd_decays, bdattack=bd_attack_shift,
                combined=combined, combined030=combined_030)
    for k, fn in jobs.items():
        if a.only is None or a.only == k:
            print(f"{k}:"); fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
