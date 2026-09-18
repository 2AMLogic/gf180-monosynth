#!/usr/bin/env python3
"""Runs synth_top through its pins: the model's default patch (contract 5.5,
converted by model/voice_fx.py itself) is sent as DR 0007 writes over the SPI
bench, a note is played, a drum is triggered, and the bench reports the frame
schedule and checks the I2S stream against the sample stream (contract 13,
D = 1). This is a plumbing-and-schedule check of the top level; the voice's
bit-exactness is verify_voice.py's job.

    .venv/bin/python rtl-sketch/verify_top.py            # exit 0 = every check passed

Exit status: 0 all checks pass; 1 a check failed; 2 it did not run.
"""
from __future__ import annotations
import argparse, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model")); sys.path.insert(0, os.path.join(ROOT, "audition"))
import voice_fx as vf
from verify_ladder import tool

A = dict(INC=0x00, WAVE=0x04, W=0x08, GLIDE=0x0C, VOL=0x0D, DVOL=0x0E, ROUTE=0x0F,
         AMP=0x10, FILT=0x14, CUT_LO=0x18, CUT_HI=0x19, TRACK=0x1A, K=0x1C, GAIN=0x1D, OGAIN=0x1E,
         GATE_ON=0x20, GATE_OFF=0x21, TRIG=0x22, RESET=0x23, DCUT=0x28, DK=0x29, DGAIN=0x2A, DOGAIN=0x2B,
         NOP=0x3F, DRUM_TRIG=0x40, MODAL_PRESET=0x41)
WAVE_CODE = dict(saw=0, square=1, pulse25=2, tri=3, sine=4)


def patch_writes(regs: dict, note: int, dvol: int = 8192) -> list:
    """The register image as (flag, addr, data) writes, from the model's own
    conversion (VoiceFx.patch_regs / note_incs / note_track)."""
    out = [(0, A["NOP"], 0)]
    for k, s in enumerate(regs["waves"]):
        out.append((0, A["WAVE"] + k, WAVE_CODE[s]))
    for k, wgt in enumerate(regs["weights"]):
        out.append((0, A["W"] + k, wgt))
    for base, key in ((A["AMP"], "amp"), (A["FILT"], "fenv")):
        for j, v in enumerate(regs[key]):
            out.append((0, base + j, v))
    out += [(0, A["CUT_LO"], regs["cut_lo"]), (0, A["CUT_HI"], regs["cut_hi"]),
            (0, A["K"], regs["k"]), (0, A["GAIN"], regs["gain"]), (0, A["OGAIN"], regs["ogain"]),
            (0, A["GLIDE"], regs["glide"]), (0, A["VOL"], regs["vol"]), (0, A["DVOL"], dvol),
            (0, A["MODAL_PRESET"], 2),
            (0, A["DCUT"], 1200), (0, A["DK"], regs["k"]), (0, A["DGAIN"], regs["gain"]), (0, A["DOGAIN"], regs["ogain"])]
    for k, v in enumerate(vf.VoiceFx.note_incs(note, regs["detune"])):
        out.append((1, A["INC"] + k, v))                                   # jump
    out.append((0, A["TRACK"], vf.VoiceFx.note_track(note, regs["track"])))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    ap.add_argument("--frames", type=int, default=1200)
    ap.add_argument("--note", type=int, default=45)
    a = ap.parse_args(argv)
    a.outdir = os.path.abspath(a.outdir)              # the benches run with cwd = rtl-sketch
    os.makedirs(a.outdir, exist_ok=True)
    regs = vf.VoiceFx.patch_regs()
    cmds = [(0,) + w for w in patch_writes(regs, a.note)]
    cmds.append((2, 0, A["GATE_ON"], 0))
    cmds.append((200, 0, A["DRUM_TRIG"], 0x01))
    cmds.append((300, 0, A["DRUM_TRIG"], 0x00))
    cmds.append((300, 0, A["ROUTE"], 1))                    # the drum filter on
    cmds.append((10, 0, A["DRUM_TRIG"], 0x01))
    # the longest frame: three squares gliding (three reciprocals per frame) with the drum filter on
    for k in range(3):
        cmds.append((0, 0, A["WAVE"] + k, WAVE_CODE["square"]))
    cmds.append((0, 0, A["GLIDE"], vf.glide_reg(0.02)))
    for k, v in enumerate(vf.VoiceFx.note_incs(a.note + 12, regs["detune"])):
        cmds.append((0, 0, A["INC"] + k, v))                                   # no jump: slew
    cmds.append((600, 0, A["GATE_OFF"], 0))
    cmd_file = os.path.join(a.outdir, "top_cmds.txt")
    with open(cmd_file, "w") as f:
        for c in cmds:
            f.write("%d %d %d %d\n" % c)
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_top: iverilog/vvp not found"); return 2
    srcs = ["tb_synth_top.v", "synth_top.v", "spi_ctl.v", "voice_dp.v", "recip_div.v", "ladder_dp_n.v",
            "i2s_tx.v", "modal_dp_rom.v", "modal_coef_rom_p8.v"]
    vvp_file = os.path.join(a.outdir, "tb_synth_top.vvp")
    r = subprocess.run([iverilog, "-g2012", "-o", vvp_file] + srcs, cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_top: iverilog failed:\n" + r.stdout + r.stderr); return 2
    out_file = os.path.join(a.outdir, "top_out.txt")
    r = subprocess.run([vvp, "-n", vvp_file, f"+cmd={cmd_file}", f"+out={out_file}", f"+frames={a.frames}"],
                       cwd=HERE, capture_output=True, text=True, timeout=900)
    log = r.stdout
    sys.stdout.write("".join("  " + l + "\n" for l in log.splitlines() if l.startswith("tb_synth_top")))
    if r.returncode != 0:
        print("verify_top: vvp failed:\n" + r.stdout + r.stderr); return 2
    ok = True
    def grab(pat):
        m = re.search(pat, log); return None if m is None else [int(x) for x in m.groups()]
    busy = grab(r"busy at a tick: (\d+) times.*overrun flag (\d+); overflow (\d+)")
    i2s = grab(r"I2S words decoded (\d+), mismatches.*?(\d+), L/R differ (\d+)")
    sched = grab(r"voice sample ready at cycle mean (\d+) worst (\d+) of 256; drum bus ready at mean (\d+) worst (\d+)")
    status = re.search(r"status word on MISO = ([0-9a-f]{8})", log)
    if busy is None or busy != [0, 0, 0]:
        print("verify_top: FAIL: datapath not idle at a tick, overrun or overflow"); ok = False
    if i2s is None or i2s[0] < a.frames // 2 or i2s[1] != 0 or i2s[2] != 0:
        print("verify_top: FAIL: I2S decode does not match the sample stream"); ok = False
    if sched is None or sched[1] > 255:
        print("verify_top: FAIL: schedule exceeds the frame"); ok = False
    if status is None or not status.group(1).startswith("4d1"):
        print("verify_top: FAIL: status word ID/version not read back"); ok = False
    samples = [int(l.split()[1]) for l in open(out_file) if len(l.split()) >= 3 and l.split()[1].lstrip('-').isdigit()]
    peak = max(abs(s) for s in samples) if samples else 0
    print(f"verify_top: {len(samples)} frames captured, peak |sample| {peak}")
    if peak == 0:
        print("verify_top: FAIL: the output is silent"); ok = False
    print("verify_top: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
