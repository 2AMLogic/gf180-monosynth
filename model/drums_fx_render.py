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
    00-solo-<nn>-<SOUND>.wav ONE HIT OF EACH OF THE SIXTEEN at accent 1.0, then 1.4,
                             then 0.6 -- the pair sounds (LC, MC, HC, RS, MA) render with
                             their circuit switched to that position, which is what the
                             panel switch does and what `kit_with_sounds` writes
    01-all-eleven-at-once.wav every CIRCUIT in one frame at accent 1.4: the loudest hit
    10-roll-call.wav         the sixteen in order, named in the order of SOUND_NAMES
    11-groove-full-808.wav   a groove that uses the three new circuits: congas, claves,
                             cymbal, over the kick/snare/hats
    12-groove-rimshot-maracas.wav the OTHER half of three pairs -- rimshot, maracas and
                             the mid tom -- so every one of the sixteen has been heard
                             in a musical context across the two
    13-before-after-808.wav  11-groove-full-808 as revision 8 could play it (no mid
                             circuit, no claves, no cymbal, congas back to toms), a bar
                             of silence, then the same bars complete. Nothing else moves
    02-groove-808.wav        a two-bar 808 pattern with accents, closed/open hats and the choke
    03-groove-toms.wav       toms and congas-style fills against the kick
    04-groove-claps.wav      clap, cowbell and hats
    05-combined.wav          the DR 0008 milestone (05-combined-drums-at-0.30.wav: the same with the drum buses at 0.30): a bass line through the voice (the
                             growl-bass patch) with the drums, through output_fx at the
                             reference gains, unnormalised: bass release while drums ring,
                             every drum soloed, simultaneous hits, the loudest combination
    06-bd-decay-short-mid-long.wav  the BD at the three DECAY presets of the reference
    07-bd-plain-then-attack-shift.wav  the BD with and without the 4 ms / 130 Hz attack window, as host writes
    08-sd-rev6-then-rev7.wav  the snare before and after contract revision 7, three accents, A then B
    09-groove-sd-rev6-then-rev7.wav  the 808 groove twice with only the snare changed
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
    """Each of the SIXTEEN alone at accent 1.0: its peak on each bus and the
    factor its amps (or, for the mix-bus sounds, its envelope peaks) need to
    land on the target -- Roland's chart's proportions (reference 1.6, the
    "normal Vpp" column) with the loudest at 0.5 x full scale on the bus."""
    n = int(1.0 * SR)
    print("sound   dmix peak (FS)   body peak (FS)   state peak (FS)   target   scale to it")
    for name in dx.SOUND_NAMES:
        d = dx.DrumsFx()
        dm, bd = d.play(dx.hit_writes([(10, dx.SOUND_STOP[name], 1.0)], dx.kit_with_sounds(name)), n)
        pk_m, pk_b = np.abs(dm).max() / 32768, np.abs(bd).max() / 32768
        st = max(abs(v) for v in d.bank.y1) / 32768
        pk = max(pk_m, pk_b)
        t = dx.BUS_TARGET[name]
        print(f"  {name:4s}  {pk_m:12.3f}    {pk_b:12.3f}    {st:12.1f}   {t:7.4f}   x {t / max(pk, 1e-9):.4f}")


def solo_renders():
    """All sixteen, each with its circuit switched to that sound. The three
    hit times are the ones `model/drum_verify.py` segments on, so these files
    drop straight into the comparison against the real machine."""
    for i, name in enumerate(dx.SOUND_NAMES):
        s = dx.SOUND_STOP[name]
        long = name in ("CY", "OH")
        span = 3.6 if long else 2.2
        step = 1.2 if long else 0.7
        hits = [(int((0.05 + k * step) * SR), s, a) for k, a in enumerate((1.0, 1.4, 0.6))]
        out, _ = drums_only(hits, span, kit=dx.kit_with_sounds(name))
        write_wav(f"00-solo-{i:02d}-{name}.wav", out)


def roll_call():
    """The sixteen in order, one hit each, with the circuit switched between
    them. One file to hear the whole machine in fifteen seconds."""
    outs = []
    for name in dx.SOUND_NAMES:
        span = 2.4 if name in ("CY", "OH") else 0.9
        o, _ = drums_only([(int(0.02 * SR), dx.SOUND_STOP[name], 1.2)], span,
                          kit=dx.kit_with_sounds(name))
        outs.append(o)
    write_wav("10-roll-call.wav", np.concatenate(outs))


def all_at_once():
    """Every circuit in one frame -- the loudest hit the register map allows.
    At the reference 0.45 drum gains this RAILS a few dozen samples, because
    eleven bodies landing together put the body bus at ~3 x full scale before
    its gain; that is the gain choice, not the block (nothing inside it
    saturates -- `test_the_whole_kit_still_fits_its_buses` checks both buses at
    accent 2.0). The 0.30 version is the same hit without the rail, for
    listening."""
    n = dx.N_STOPS
    hits = [(int(0.05 * SR), s, 1.4) for s in range(n)] + [(int(1.4 * SR), s, 1.0) for s in range(n)]
    out, d = drums_only(hits, 3.2)
    write_wav("01-all-eleven-at-once.wav", out)
    out30, _ = drums_only(hits, 3.2, dvol=0.30, bvol=0.30)
    write_wav("01-all-eleven-at-once-drums-at-0.30.wav", out30)
    bd = d.trace["body"]
    print(f"    body bus peak {np.abs(bd).max() / 32768:.3f} x FS (word is +-8.0); "
          f"mix bus peak {np.abs(d.trace['dmix']).max() / 32768:.3f} x FS")


PATTERN_808 = dx.PATTERN_808
PATTERN_TOMS = {"BD": "X.......X.......", "LT": "....x.x.....xx..", "HT": "..x.......x...x.",
                "CH": "x.x.x.x.x.x.x.x.", "SD": "....X.......X..o"}
PATTERN_CLAP = {"CP": "....X.......X...", "CB": "x..x..x...x..x..", "CH": "x.xxx.xxx.xxx.xx",
                "OH": "...x......x.....", "BD": "x...x...x...x..."}


# ---- the grooves that use the three new circuits ------------------------------
# A pattern names SOUNDS, and two sounds of a pair cannot appear in the same
# pattern because they are one circuit: that constraint is the machine's, and
# `groove` enforces it rather than silently letting one overwrite the other.
#
# GROOVE_FULL is a 124 BPM shuffle over sixteen steps -- kick and snare hold the
# floor, the closed hat runs eighths with the open hat answering off the beat,
# and the three NEW circuits carry the music: the mid conga plays the melody
# against the high conga, the claves mark the 3-2 clave, and the cymbal opens
# each bar and rings across it. Nothing in it could be played before revision 10.
GROOVE_FULL = {
    "BD": "X.......X...x...",
    "SD": "....X.......X...",
    "CH": "x.x.x.x.x.x.x.x.",
    "OH": "......x.......x.",
    "CB": "............x...",
    "CY": "X...............",
    "CL": "..x..x..x...x..x",      # 3-2 clave; the RS/CL circuit
    "MC": "...x....x.x....x",      # the MT/MC circuit, in its conga position
    "HC": "x...x......x....",      # the HT/HC circuit, likewise
}
# The other half of three pairs, so all sixteen have been heard in a groove:
# the rimshot instead of the claves, the maracas instead of the clap, and the
# mid TOM instead of the mid conga, over a slower half-time feel.
GROOVE_RS = {
    "BD": "X..x....X.......",
    "SD": "........X.......",
    "RS": "..x...x...x...x.",
    "MA": "x.xxx.xxx.xxx.xx",
    "CH": "..x...x...x...x.",
    "OH": "..............x.",
    "MT": "............x.x.",
    "LT": ".............x..",
}


def groove(pattern, bpm, bars=2, swing=0.0, start_s=0.05, tail_s=1.4, kit_extra=()):
    """Render a pattern of SOUND names. The kit is switched to every sound the
    pattern uses first, which is where the exclusivity is enforced: two sounds
    of one circuit in one pattern is a caller error, not a last-write-wins."""
    by_stop = {}
    for name in pattern:
        by_stop.setdefault(dx.SOUND_STOP[name], []).append(name)
    clash = {s: v for s, v in by_stop.items() if len(v) > 1}
    if clash:
        raise ValueError("these sounds share one circuit and cannot play together: "
                         + "; ".join("/".join(v) for v in clash.values()))
    kit = dx.kit_with_sounds(*pattern, *kit_extra)
    hits = dx.pattern_hits(pattern, bpm=bpm, bars=bars, swing=swing, start_s=start_s)
    secs = start_s + 60.0 / bpm * 4 * bars + tail_s
    return drums_only(hits, secs, kit=kit)[0], hits, kit, secs


def new_grooves():
    out, _, _, _ = groove(GROOVE_FULL, 124.0, bars=2, swing=0.10)
    write_wav("11-groove-full-808.wav", out)
    out, _, _, _ = groove(GROOVE_RS, 92.0, bars=2, swing=0.0)
    write_wav("12-groove-rimshot-maracas.wav", out)


def before_after():
    """The same two bars, twice: what revision 8 could play, then the whole
    machine. BEFORE drops every hit on a circuit revision 8 did not have (the
    mid circuit, the RS/CL circuit, the cymbal) and switches the high conga
    back to the high TOM, because the conga position is also new. Kick, snare,
    hats, cowbell, the accents and the swing are bit-identical between the
    halves, so everything audible is the three circuits."""
    before = {k: v for k, v in GROOVE_FULL.items() if k not in ("CY", "CL", "MC", "HC")}
    before["HT"] = GROOVE_FULL["HC"]
    a, _, _, _ = groove(before, 124.0, bars=2, swing=0.10)
    b, _, _, _ = groove(GROOVE_FULL, 124.0, bars=2, swing=0.10)
    gap = np.zeros(int(0.7 * SR), dtype=a.dtype)
    write_wav("13-before-after-808.wav", np.concatenate([a, gap, b]))


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
    for i, knob in enumerate((1.0, 5.0, 9.0)):                      # "short", "mid", "long"
        q = dx.bd_decay_q(knob)
        f = int((0.05 + 1.2 * i) * SR)
        extra += [(f - 1, a, v) for a, v in dx.mode_writes(dx.M_BD, dx.BD_HZ, q, 0.0)[:2]]
        hits += [(f, dx.BD, 1.0), (f + int(0.6 * SR), dx.BD, 1.0)]
    kit = dx.kit_808()
    out, _ = drums_only(hits, 3.7, kit=kit, extra_writes=extra)
    write_wav("06-bd-decay-short-mid-long.wav", out)


def bd_attack_shift():
    """Reference 2's BD attack (contract 15.7.1): for the first 4 ms the
    resonator sits at ~130 Hz, Q ~6, then returns to its own f0 -- the
    coefficient sequence `bd_attack_writes` now emits for every BD hit,
    rendered beside the same hit WITHOUT it (coef_seq=False): plain,
    shifted, plain, shifted. The plain pair is the negative control a
    listener can hear."""
    hits = [(int((0.05 + 0.7 * i) * SR), dx.BD, 1.0) for i in range(4)]
    kit = dx.kit_808()
    w = [(int((0.05 + 0.7 * i) * SR), dx.BD, 1.0) for i in (1, 3)]
    writes = dx.hit_writes(hits, kit, coef_seq=False)
    for f, _, _ in w:
        writes += dx.bd_attack_writes(f, dx._kit_poles(kit, dx.M_BD))
    n = int(2.9 * SR)
    d = dx.DrumsFx()
    dm, bd = d.play(sorted(writes, key=lambda t: t[0]), n)
    out = dx.output_fx(np.zeros(n), 0, dm, dx.accent_reg(DVOL), bd, dx.accent_reg(BVOL))
    write_wav("07-bd-plain-then-attack-shift.wav", out)


# The snare's three registers exactly as contract revision 6 shipped them.
# Literals, so the A/B below keeps rendering THAT snare after the kit moves
# again -- the same reason `model/test_drum_fit.py` pins them.
SD_REV6 = {"amp_lo": 0.0036, "amp_hi": 0.00369, "noise_tau": 15e-3, "noise_peak": 0.5}


def sd_kit(amp_lo: float, amp_hi: float, noise_tau: float, noise_peak: float):
    """kit_808() with the snare's three revision-7 registers set by hand."""
    base = {a: v for a, v in dx.kit_808()}
    for a, v in dx.mode_writes(dx.M_SDLO, 173.0, 16.3, amp_lo):
        base[a] = v
    for a, v in dx.mode_writes(dx.M_SDHI, 336.0, 9.9, amp_hi):
        base[a] = v
    for a, v in dx.env_writes(dx.E_SDN, dx.SD, noise_tau, noise_peak):
        base[a] = v
    return sorted(base.items())


def sd_before_after():
    """The snare of contract revision 6 against the snare of revision 7, as
    one clip a listener can A/B without touching a knob: three pairs, each
    "before" then "after" at the same accent (1.0, 1.4, 0.6).

    What to listen for, in order of size: the upper partial, 11 dB louder and
    back where the machine puts it (that is the "front end" the T-8 review and
    the volca workaround are both about), and the snappy burst, which now runs
    on past the body instead of stopping under it (T20 34 ms -> 72 ms against
    the machine's 63-78)."""
    before, after = sd_kit(**SD_REV6), dx.kit_808()
    step = 0.55
    outs = []
    for i, accent in enumerate((1.0, 1.4, 0.6)):
        for kit in (before, after):
            o, _ = drums_only([(int(0.02 * SR), dx.SD, accent)], step, kit=kit)
            outs.append(o)
    write_wav("08-sd-rev6-then-rev7.wav", np.concatenate(outs))


def sd_groove_before_after():
    """The same two-bar 808 groove twice, the snare the only thing that moves:
    revision 6's snare, a bar of silence, revision 7's. Everything else --
    kick, hats, clap, cowbell, toms, the accents, the choke -- is
    bit-identical between the halves, so anything audible is the snare."""
    bpm = 118.0
    bars_s = 60.0 / bpm * 4 * 2
    hits = dx.pattern_hits(dx.PATTERN_808, bpm=bpm, bars=2, start_s=0.05)
    outs = []
    for kit in (sd_kit(**SD_REV6), dx.kit_808()):
        o, _ = drums_only(hits, bars_s + 0.6, kit=kit)
        outs.append(o)
        outs.append(np.zeros(int(0.35 * SR), dtype=o.dtype))
    write_wav("09-groove-sd-rev6-then-rev7.wav", np.concatenate(outs))


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
    for s in range(dx.N_STOPS):
        hits.append((int(t * SR), s, 1.0)); t += 0.45
    hits += [(int(t * SR), s, 1.4) for s in range(dx.N_STOPS)]
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
    ap.add_argument("--only", default=None,
                    help="solo|all|grooves|rollcall|newgrooves|beforeafter|bd|bdattack|sdab|sdgroove|combined|combined030")
    a = ap.parse_args(argv)
    if a.balance:
        balance(); return 0
    jobs = dict(solo=solo_renders, all=all_at_once, grooves=grooves, bd=bd_decays, bdattack=bd_attack_shift,
                sdab=sd_before_after, sdgroove=sd_groove_before_after,
                rollcall=roll_call, newgrooves=new_grooves, beforeafter=before_after,
                combined=combined, combined030=combined_030)
    for k, fn in jobs.items():
        if a.only is None or a.only == k:
            print(f"{k}:"); fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
