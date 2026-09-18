#!/usr/bin/env python3
"""Can the control link CARRY the register writes the models perform?

Every register write in this design comes from a model: the voice's patch
image is `model/voice_fx.py`'s own conversion, the drum kit is
`model/drums_fx.py`'s `kit_808()` (contract Appendix G, SHA-pinned). Both
sides of the link have been shown bit-exact against those models at their own
ports, and neither test can see the link in between.

This script closes that. It takes the writes the two models produce, sends
them through `spi_ctl` as an MCU's SPI master would, and compares what reaches
the register write port against what the host INTENDED -- not against
anything the DUT produced.

    .venv/bin/python rtl-sketch/verify_ctl.py                 # revision 2, 48-bit frame
    .venv/bin/python rtl-sketch/verify_ctl.py --link dr7rev1  # revision 1, 32-bit: RED

Exit status, as verify_ladder.py: 0 identical, 1 differed, 2 did not run.

  --link {rev2,dr7rev1}  which receiver: the current one, or the standing
                         negative control (rtl-sketch/stubs/spi_ctl_dr7rev1.v,
                         DR 0007 revision 1's 32-bit frame).
  --inject NAME          compile with -DINJECT_BUG_<NAME>:
                           SPI_ADDR7      keep only A[6:0]      (the rev-1 address field)
                           SPI_DATA24     keep only D[23:0]     (the rev-1 data field)
                           SPI_NOSEC      ignore the section bit
                           SPI_ANYLEN     accept any bit count  (drops DR 0007 section 1)
                           SPI_DRAIN_LATE drain from cycle 8, i.e. at `go`
  --expect-fail          exit 0 only if the comparison gave 1
"""
from __future__ import annotations
import argparse, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "audition"))
import voice_fx as vf
import drums_fx as dx
from verify_ladder import tool

SEC_VOICE, SEC_DRUM = 0, 1
GO_CYCLE = 8            # synth_top: every datapath block starts here (DR 0007 section 5)
AV = dict(INC=0x00, WAVE=0x04, W=0x08, GLIDE=0x0C, VOL=0x0D, DVOL=0x0E, ROUTE=0x0F,
          AMP=0x10, FILT=0x14, CUT_LO=0x18, CUT_HI=0x19, TRACK=0x1A, K=0x1C, GAIN=0x1D, OGAIN=0x1E,
          GATE_ON=0x20, GATE_OFF=0x21, TRIG=0x22, RESET=0x23,
          DCUT=0x28, DK=0x29, DGAIN=0x2A, DOGAIN=0x2B, BVOL=0x2C, NOP=0x3F)
WAVE_CODE = dict(saw=0, square=1, pulse25=2, tri=3, sine=4)


def voice_writes(note: int = 45) -> list:
    """The voice's whole control image, as the reference host writes it."""
    regs = vf.VoiceFx.patch_regs()
    w = [(0, SEC_VOICE, AV["NOP"], 0)]
    for k, s in enumerate(regs["waves"]):   w.append((0, SEC_VOICE, AV["WAVE"] + k, WAVE_CODE[s]))
    for k, g in enumerate(regs["weights"]): w.append((0, SEC_VOICE, AV["W"] + k, g))
    for base, key in ((AV["AMP"], "amp"), (AV["FILT"], "fenv")):
        for j, v in enumerate(regs[key]):   w.append((0, SEC_VOICE, base + j, v))
    for name, key in (("CUT_LO", "cut_lo"), ("CUT_HI", "cut_hi"), ("K", "k"),
                      ("GAIN", "gain"), ("OGAIN", "ogain"), ("GLIDE", "glide"), ("VOL", "vol")):
        w.append((0, SEC_VOICE, AV[name], regs[key]))
    w += [(0, SEC_VOICE, AV["DVOL"], 16384), (0, SEC_VOICE, AV["BVOL"], 16384),
          (0, SEC_VOICE, AV["ROUTE"], 1),
          (0, SEC_VOICE, AV["DCUT"], 1200), (0, SEC_VOICE, AV["DK"], regs["k"]),
          (0, SEC_VOICE, AV["DGAIN"], regs["gain"]), (0, SEC_VOICE, AV["DOGAIN"], regs["ogain"])]
    for k, v in enumerate(vf.VoiceFx.note_incs(note, regs["detune"])):
        w.append((1, SEC_VOICE, AV["INC"] + k, v))                      # flag = jump
    w.append((0, SEC_VOICE, AV["TRACK"], vf.VoiceFx.note_track(note, regs["track"])))
    w.append((0, SEC_VOICE, AV["GATE_ON"], 0))
    return w


def stimulus() -> list:
    """(flag, sec, addr, data) in send order: both models' images, then the
    corners of the frame -- every field at its width, both sections, the flag
    on and off, and the two RESET addresses."""
    w = voice_writes()
    w += [(0, SEC_DRUM, a, v) for a, v in dx.kit_808()]
    # the widest value of every drum register class, at the top and bottom address of each
    bits = dx.REG_BITS
    corners = [
        (dx.A_STOPS,               (1 << bits["stops"]) - 1),
        (dx.A_ACCENT,              (1 << bits["accent"]) - 1),
        (dx.A_ACCENT + 7,          0),
        (dx.A_OSC,                 (1 << bits["osc_inc"]) - 1),
        (dx.A_OSC + 5,             1),
        (dx.A_ENV,                 (1 << bits["env_ctl"]) - 1),      # 27 bits
        (dx.A_ENV + 1,             (1 << bits["peak"]) - 1),
        (dx.A_ENV + 2,             (1 << bits["rate"]) - 1),
        (dx.A_ENV + 11 * 4,        (1 << bits["env_ctl"]) - 1),
        (dx.A_PATH,                (1 << bits["path"]) - 1),
        (dx.A_PATH + 15,           0),
        (dx.A_MODE,                (1 << bits["a1"]) - 1),           # 26 bits
        (dx.A_MODE + 1,            (1 << bits["a2"]) - 1),
        (dx.A_MODE + 2,            (1 << bits["amp"]) - 1),
        (dx.A_MODE + 3,            3),
        (dx.A_MODE + 11 * 4,       (1 << bits["a1"]) - 1),
        (dx.A_MODE + 11 * 4 + 3,   3),
        (dx.A_RESET,               0),                                # 0xFF, the drum page's reset
    ]
    w += [(0, SEC_DRUM, a, v) for a, v in corners]
    w += [(0, SEC_VOICE, AV["RESET"], 0), (1, SEC_VOICE, AV["INC"], (1 << 24) - 1),
          (0, SEC_VOICE, AV["NOP"], 0)]
    return w


def write_stream(path: str, writes: list, gap: int = 2) -> None:
    """[63:48] wait_frames  [47:44] flag  [43:40] sec  [39:32] addr  [31:0] data"""
    with open(path, "w") as fh:
        for i, (f, s, a, d) in enumerate(writes):
            fh.write(f"{gap if i else 0:04x}{f:01x}{s:01x}{a & 0xFF:02x}{d & 0xFFFFFFFF:08x}\n")


def expected_stream(writes: list) -> list:
    out = []
    for f, s, a, d in writes:
        out += [int(f), int(s), int(a) & 0xFF, int(d) & 0xFFFFFFFF]
    return out


def simulate(link: str, defines, outdir: str, bits: int, timeout_s: float = 900.0):
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_ctl: iverilog/vvp not on PATH (or set OSS_CAD_SUITE)"); return None
    src = os.path.join(HERE, "spi_ctl.v") if link == "rev2" else os.path.join(HERE, "stubs", "spi_ctl_dr7rev1.v")
    vvp_file = os.path.join(outdir, f"tb_ctl_{link}.vvp")
    out_file = os.path.join(outdir, f"ctl_rtl_out_{link}.txt")
    if os.path.exists(out_file): os.remove(out_file)
    r = subprocess.run([iverilog, "-g2012", "-o", vvp_file] + [f"-D{d}" for d in defines]
                       + [os.path.join(HERE, "tb_ctl.v"), src], cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_ctl: iverilog failed:\n" + r.stdout + r.stderr); return None
    try:
        r = subprocess.run([vvp, "-n", vvp_file, f"+writes={os.path.join(outdir, 'ctl_writes.hex')}",
                            f"+out={out_file}", f"+bits={bits}"],
                           cwd=HERE, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print("verify_ctl: simulation timed out"); return None
    sys.stdout.write("".join("  sim: " + l + "\n" for l in r.stdout.splitlines() if l.startswith("tb_ctl")))
    if r.returncode != 0 or not os.path.exists(out_file):
        print("verify_ctl: vvp failed:\n" + r.stdout + r.stderr); return None
    return out_file


# What the last run actually found, so a caller can check that a negative
# control failed for the reason it was recorded to fail for. The "intended"
# side of this comparison comes from model/voice_fx.py and model/drums_fx.py --
# never from the RTL -- which is what keeps it from going self-referential.
LAST: dict = {}


def compare_writes(writes: list, rtl_out: str) -> int:
    """0 identical, 1 differed, 2 did not run. Reports per-field, because
    'the address was truncated' and 'the datum was truncated' are different
    defects with different fixes."""
    try:
        rows = [l.split() for l in open(rtl_out).read().splitlines() if l.strip()]
    except OSError:
        print(f"verify_ctl: no RTL output at {rtl_out}"); return 2
    got = [tuple(int(t) if t != "x" else None for t in r[:4]) for r in rows]
    cycs = [int(r[4]) for r in rows if len(r) > 4 and r[4] != "x"]
    n = len(writes)
    count_bad = len(got) != n
    if count_bad:
        print(f"verify_ctl: FAIL -- {len(got)} writes reached the port, the host sent {n}")
        if len(got) < n:
            print(f"  {n - len(got)} write(s) never arrived: the link could not carry them at all")
            if not got:
                return 2
    late = [c for c in cycs if c >= GO_CYCLE]
    if late:
        print(f"verify_ctl: FAIL -- {len(late)} write(s) applied at or after cycle {GO_CYCLE} (`go`), "
              f"worst cycle {max(late)}: the datapath had already read its registers")
    bad_f = bad_s = bad_a = bad_d = 0
    first = None
    for i, (want, have) in enumerate(zip(writes, got)):
        wf, ws, wa, wd = int(want[0]), int(want[1]), int(want[2]) & 0xFF, int(want[3]) & 0xFFFFFFFF
        if have is None or None in have:
            bad_f += 1
            if first is None: first = (i, (wf, ws, wa, wd), have)
            continue
        gf, gs, ga, gd = have
        hit = False
        if gf != wf: bad_f += 1; hit = True
        if gs != ws: bad_s += 1; hit = True
        if ga != wa: bad_a += 1; hit = True
        if gd != wd: bad_d += 1; hit = True
        if hit and first is None: first = (i, (wf, ws, wa, wd), have)
    bad = sum(1 for want, have in zip(writes, got)
              if have != (int(want[0]), int(want[1]), int(want[2]) & 0xFF, int(want[3]) & 0xFFFFFFFF))
    LAST.update(bad=bad, bad_flag=bad_f, bad_sec=bad_s, bad_addr=bad_a, bad_data=bad_d,
                count_seen=len(got), count_sent=n, late=len(late), total=n)
    if bad == 0 and not count_bad and not late:
        print(f"verify_ctl: PASS -- all {n} writes reached the register port exactly as sent, "
              f"every one in the drain window (cycles {min(cycs)}..{max(cycs)}, before `go` at {GO_CYCLE})")
        return 0
    if first is None:
        return 1
    i, want, have = first
    print(f"verify_ctl: FAIL -- {bad} of {n} writes corrupted in the link")
    print(f"  wrong flag {bad_f}, wrong section {bad_s}, wrong address {bad_a}, wrong data {bad_d}")
    print(f"  first at write {i}: host sent flag {want[0]} sec {want[1]} addr 0x{want[2]:02X} data 0x{want[3]:X}"
          f" ({want[3].bit_length()} bits)")
    print(f"                 port saw  flag {have[0]} sec {have[1]} addr 0x{have[2]:02X} data 0x{have[3]:X}")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--link", choices=("rev2", "dr7rev1"), default="rev2")
    ap.add_argument("--inject", default=None)
    ap.add_argument("--expect-fail", action="store_true")
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    a = ap.parse_args(argv)
    a.outdir = os.path.abspath(a.outdir)
    os.makedirs(a.outdir, exist_ok=True)
    writes = stimulus()
    nd = sum(1 for w in writes if w[1] == SEC_DRUM)
    wide_a = sum(1 for w in writes if w[1] == SEC_DRUM and (w[2] & 0xFF) > 0x7F)
    wide_d = sum(1 for w in writes if (w[3] & 0xFFFFFFFF) > 0xFFFFFF)
    print(f"verify_ctl: {len(writes)} writes from the two models ({len(writes) - nd} voice, {nd} drum); "
          f"{wide_a} need an address above 0x7F, {wide_d} a datum wider than 24 bits")
    write_stream(os.path.join(a.outdir, "ctl_writes.hex"), writes)
    bits = 48 if a.link == "rev2" else 32
    defines = [f"INJECT_BUG_{a.inject}"] if a.inject else []
    print(f"verify_ctl: driving the pins of {'spi_ctl.v' if a.link == 'rev2' else 'stubs/spi_ctl_dr7rev1.v'} "
          f"at {bits} bits per transaction{' with ' + defines[0] if defines else ''}")
    out = simulate(a.link, defines, a.outdir, bits)
    status = 2 if out is None else compare_writes(writes, out)
    if a.expect_fail:
        tag = a.inject or a.link
        if status == 1:
            print(f"verify_ctl: negative control {tag} CAUGHT (comparison failed as required)"); return 0
        print(f"verify_ctl: NEGATIVE CONTROL NOT CAUGHT (status {status})"); return 1 if status == 0 else 2
    return status


if __name__ == "__main__":
    sys.exit(main())
