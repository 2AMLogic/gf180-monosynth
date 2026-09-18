#!/usr/bin/env python3
"""Bit-exact verification of voice_dp.v against model/voice_fx.py (VoiceFx).

The model is the specification. Three scenarios are played through ONE
continuous voice (contract 5.3, DR 0003), the model's writes are translated
one-to-one into DR 0007 register writes, tb_voice.v applies them at the
register port in the frames the model applies them, and every output sample
is compared with no tolerance.

  1. the default patch (saw, saw, square), one note from reset;
  2. every remaining waveform (pulse25, tri, sine), res 1.05, drive 3, a
     wide cutoff envelope and full tracking, a glide from a fifth below;
  3. a paraphonic, multi-trigger phrase through the reference host
     (KeyHost: last-note, multi, legato glide), keys pressed and released
     while others are held, a new key during a release.

Exit status: 0 every sample identical; 1 a mismatch; 2 it did not run.
    .venv/bin/python rtl-sketch/verify_voice.py [--outdir DIR] [--short]
"""
from __future__ import annotations
import argparse, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model")); sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np
import voice_fx as vf
from dsp import SR
from verify_ladder import tool

A = dict(INC=0x00, WAVE=0x04, W=0x08, GLIDE=0x0C, VOL=0x0D, AMP=0x10, FILT=0x14,
         CUT_LO=0x18, CUT_HI=0x19, TRACK=0x1A, K=0x1C, GAIN=0x1D, OGAIN=0x1E,
         GATE_ON=0x20, GATE_OFF=0x21, TRIG=0x22)
WAVE_CODE = dict(saw=0, square=1, pulse25=2, tri=3, sine=4)


def patch_to_writes(regs: dict, f0: int) -> list:
    """The register image VoiceFx._apply_patch installs at the first frame of
    a play() call, as (frame, flag, addr, data)."""
    out = []
    for k, s in enumerate(regs["waves"]): out.append((f0, 0, A["WAVE"] + k, WAVE_CODE[s]))
    for k, wgt in enumerate(regs["weights"]): out.append((f0, 0, A["W"] + k, int(wgt)))
    for base, key in ((A["AMP"], "amp"), (A["FILT"], "fenv")):
        for j, v in enumerate(regs[key]): out.append((f0, 0, base + j, int(v)))
    out += [(f0, 0, A["CUT_LO"], int(regs["cut_lo"])), (f0, 0, A["CUT_HI"], int(regs["cut_hi"])),
            (f0, 0, A["K"], int(regs["k"])), (f0, 0, A["GAIN"], int(regs["gain"])), (f0, 0, A["OGAIN"], int(regs["ogain"])),
            (f0, 0, A["VOL"], int(regs["vol"])), (f0, 0, A["GLIDE"], int(regs["glide"]))]
    return out


def model_writes_to_regs(writes: list, f0: int) -> list:
    out = []
    for w in writes:
        f, op, args = int(w[0]) + f0, w[1], w[2:]
        if op == "INC":
            k, v = args[0], int(args[1]); jump = bool(args[2]) if len(args) > 2 else False
            out.append((f, int(jump), A["INC"] + k, v))
        elif op == "TRACK": out.append((f, 0, A["TRACK"], int(args[0])))
        elif op == "GATE":  out.append((f, 0, A["GATE_ON"] if int(args[0]) else A["GATE_OFF"], 0))
        elif op == "TRIG":  out.append((f, 0, A["TRIG"], 0))
        elif op == "GLIDE": out.append((f, 0, A["GLIDE"], int(args[0])))
        else: raise ValueError(op)
    return out


def scenarios(short: bool) -> list:
    d = 0.12 if short else 0.3
    n = int(d * SR)
    v = vf.VoiceFx()
    segs = []
    # 1. one note from reset, the default patch
    r = v.note_on(45, d)
    segs.append(("default patch, note 45 from reset", r["regs"], r["writes"], r["n"]))
    # 2. the other waveforms, hot resonance and drive, glide from a fifth below
    r = v.note_on(69, d, glide_from=62, waves=("pulse25", "tri", "sine"), detune=(0.0, 0.03, -12.0),
                  mix=(1.0, 0.7, 0.9), cutoff=(200, 9000), q=1.05, drive=3.0, track=0.9, glide_s=0.05,
                  amp=(0.002, 0.1, 0.6, 0.08), fenv=(0.001, 0.2, 0.3, 0.05))
    segs.append(("pulse25/tri/sine, res 1.05, drive 3, glide from 62", r["regs"], r["writes"], r["n"]))
    # 3. a paraphonic multi-trigger phrase through the reference host
    regs = v.patch_regs(waves=("square", "saw", "saw"), detune=(0.0, 0.05, -12.0), q=0.9, drive=2.0,
                        cutoff=(300, 5000), glide_s=0.03)
    ev = [(0, "on", 60), (n // 7, "on", 64), (2 * n // 7, "on", 67), (3 * n // 7, "off", 64),
          (4 * n // 7, "off", 60), (9 * n // 14, "on", 48), (5 * n // 7, "off", 67), (6 * n // 7, "off", 48)]
    host = vf.KeyHost(priority="last", trigger="multi", glide="legato", mode="para")
    segs.append(("paraphonic multi-trigger phrase, KeyHost", regs, host.writes(ev, regs, first_from_reset=False), n))
    return segs


def generate(outdir: str, short: bool):
    v = vf.VoiceFx()
    v.reset()
    all_writes, expected, f0 = [], [], 0
    for name, regs, writes, n in scenarios(short):
        y = v.play(regs, writes, n)                     # the voice persists across scenarios
        all_writes += patch_to_writes(regs, f0) + model_writes_to_regs(writes, f0)
        expected += [int(s) for s in y]
        print(f"  scenario: {name}: {n} frames, {len(writes)} writes, peak {int(np.abs(y).max())}")
        f0 += n
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "voice_writes.txt"), "w") as fh:
        fh.writelines("%d %d %d %d\n" % w for w in all_writes)
    with open(os.path.join(outdir, "voice_expected.txt"), "w") as fh:
        fh.writelines(f"{s}\n" for s in expected)
    return expected, all_writes


def compare(expected, out_file, name="verify_voice") -> int:
    got = [l.strip() for l in open(out_file)]
    if len(got) < len(expected):
        print(f"{name}: short output: {len(got)} of {len(expected)} frames"); return 2
    mism = [(i, e, g) for i, (e, g) in enumerate(zip(expected, got)) if str(e) != g]
    if not mism:
        print(f"{name}: PASS -- {len(expected)} frames, RTL identical to model"); return 0
    i, e, g = mism[0]
    worst = max(abs(int(g2) - e2) for _, e2, g2 in mism if g2.lstrip('-').isdigit())
    print(f"{name}: FAIL -- {len(mism)} of {len(expected)} frames differ; first at frame {i}: model {e}, RTL {g}; worst |error| {worst} LSB")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    ap.add_argument("--short", action="store_true", help="0.12 s per scenario instead of 0.3 s")
    ap.add_argument("--compare-only", default=None, metavar="FILE")
    a = ap.parse_args(argv)
    a.outdir = os.path.abspath(a.outdir)              # the benches run with cwd = rtl-sketch
    print("verify_voice: model VoiceFx() (contract rev 3: three oscillators, glide, PolyBLEP, mixer, two ADSRs, "
          "g/kc ROMs, ladder 19-bit, VCA, vol)")
    expected, writes = generate(a.outdir, a.short)
    if a.compare_only:
        return compare(expected, a.compare_only)
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_voice: iverilog/vvp not found"); return 2
    vvp_file = os.path.join(a.outdir, "tb_voice.vvp")
    r = subprocess.run([iverilog, "-g2012", "-o", vvp_file, "tb_voice.v", "voice_dp.v", "recip_div.v", "ladder_dp_n.v"],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_voice: iverilog failed:\n" + r.stdout + r.stderr); return 2
    out_file = os.path.join(a.outdir, "voice_rtl_out.txt")
    tap_file = os.path.join(a.outdir, "voice_taps.txt")
    print(f"verify_voice: simulating voice_dp.v, {len(expected)} frames, {len(writes)} writes at the register port")
    try:
        r = subprocess.run([vvp, "-n", vvp_file, f"+wr={os.path.join(a.outdir, 'voice_writes.txt')}",
                            f"+exp={os.path.join(a.outdir, 'voice_expected.txt')}", f"+out={out_file}", f"+tap={tap_file}"],
                           cwd=HERE, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        print("verify_voice: simulation timed out"); return 2
    sys.stdout.write("".join("  sim: " + l + "\n" for l in r.stdout.splitlines() if l.startswith("tb_voice")))
    if r.returncode != 0 or not os.path.exists(out_file):
        print("verify_voice: vvp failed:\n" + r.stdout + r.stderr); return 2
    return compare(expected, out_file)


if __name__ == "__main__":
    sys.exit(main())
