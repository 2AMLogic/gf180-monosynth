#!/usr/bin/env python3
"""Bit-exact verification of synth_top.v -- THE CHIP -- against
model/synth_top_model.py, at the pins.

Every block in this design is already bit-exact against a model of that block.
Nothing was checking what happens BETWEEN them, and both integration defects
found so far were found by listening. This script checks the parts that only
exist at the top level:

  * the mix bus and the master clamp -- widths, and SUM THEN CLAMP, not clamp
    then sum. out_v is 20 bits and is NOT saturated before the master mix
    (a real difference from VoiceFx.play(), which saturates because the voice
    alone IS the output); the drum bus arrives at 19 bits; one rail at the end.
  * drum routing: bypass, and ROUTE.DFILT through ladder context 1 with its
    own DCUT/DK/DGAIN/DOGAIN. Through the filter is NOT through the voice's
    VCA (ARCHITECTURE.md 4.1, DR 0005) -- that is a property with a number
    here, not a sentence in a document.
  * SPI writes landing in the right register in the right frame, including
    writes whose CS_N edge falls in the last cycles of a frame, where the
    queue snapshot has already happened and the write belongs to the frame
    after next. The landing frame is PREDICTED from the CS_N pin event and
    checked against the register port the chip actually drove.
  * the I2S stream, decoded from SDATA and compared AGAINST THE MODEL.
    tb_synth_top.v compares it against the DUT's own sample stream, which
    cannot detect a bit shift or a channel swap -- both sides move together.

Exit status (a CI job asserting a negative control fails must require 1):
  0  every sample, every tap, every I2S word and every write landing identical
  1  it ran and something differed
  2  it did not run

  --inject NAME     compile with -DINJECT_BUG_TOP_<NAME>
  --expect-fail     exit 0 only if the comparison gave 1
  --scenario NAME   which stimulus (default 'full')
  --sckh N          SCK half-period in core cycles (4 = clk/8 = 1.536 MHz)
"""
from __future__ import annotations
import argparse, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model")); sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np
import voice_fx as vf
from synth_top_model import SynthTopModel, A, PRESET_NOTES
from verify_ladder import tool

WAVE_CODE = dict(saw=0, square=1, pulse25=2, tri=3, sine=4)
SYNC_CYCLES = 2          # CS_N pin high -> `accept` in spi_ctl: two synchroniser
                         # flops then the edge detector (DR 0007 section 5).
XFER_CYCLES = 68         # core cycles per SPI transaction, in units of SCKH
                         # (2 lead + 64 bit + 2 trail half-periods)

# taps the bench logs, in the order of the SMP line after `frame off`
TAPS = ["sample", "mixed", "ae", "fe", "cut", "k_eff", "y19", "drum_bus", "d19", "out_v", "out_d"]
BUGS = ["MIX_CLAMP_FIRST", "I2S_SHIFT", "I2S_SWAP", "DRUM_ORDER", "SPI_TICK_RACE", "DFILT_COEF"]


# ---- stimulus ---------------------------------------------------------------
def scenario(name: str, sckh: int) -> tuple:
    """(commands, n_frames, description). A command is (start_frame,
    start_off, flag, addr, data): the bench begins the transaction at that
    cycle of that frame, so the CS_N rise lands at a chosen point."""
    regs = vf.VoiceFx.patch_regs()
    note = 45
    xfer = XFER_CYCLES * sckh                     # cycles from CS_N fall to CS_N rise
    cmds, f = [], 2
    def send(flag, addr, data, off=0, gap=1):
        """Queue one transaction starting at cycle `off` of the next free frame."""
        nonlocal f
        cmds.append((f, off, flag, addr, data))
        f += max(gap, (off + xfer) // 256 + 1)    # the next transaction cannot overlap

    # 1. the default patch, one register per frame
    for k, s in enumerate(regs["waves"]):     send(0, A["WAVE"] + k, WAVE_CODE[s])
    for k, wgt in enumerate(regs["weights"]): send(0, A["W"] + k, int(wgt))
    for base, key in ((A["AMP"], "amp"), (A["FILT"], "fenv")):
        for j, v in enumerate(regs[key]):     send(0, base + j, int(v))
    for addr, v in ((A["CUT_LO"], regs["cut_lo"]), (A["CUT_HI"], regs["cut_hi"]),
                    (A["K"], regs["k"]), (A["GAIN"], regs["gain"]), (A["OGAIN"], regs["ogain"]),
                    (A["GLIDE"], regs["glide"]), (A["VOL"], regs["vol"]),
                    (A["DVOL"], 16384), (A["MODAL_PRESET"], 2),
                    (A["DCUT"], 1200), (A["DK"], regs["k"]),
                    (A["DGAIN"], regs["gain"]), (A["DOGAIN"], regs["ogain"])):
        send(0, addr, int(v))
    for k, v in enumerate(vf.VoiceFx.note_incs(note, regs["detune"])):
        send(1, A["INC"] + k, int(v))                                  # flag 1 = jump
    send(0, A["TRACK"], vf.VoiceFx.note_track(note, regs["track"]))
    send(0, A["GATE_ON"], 0)
    # 2. drums, bus only (ROUTE.DFILT off): a strike, then the release
    f += 40
    send(0, A["DRUM_TRIG"], 0x01)
    f += 30
    send(0, A["DRUM_TRIG"], 0x00)
    # 3. the drum filter ON -- the second ladder context, another strike
    f += 30
    send(0, A["ROUTE"], 1)
    f += 5
    send(0, A["DRUM_TRIG"], 0x01)
    f += 20
    send(0, A["DRUM_TRIG"], 0x00)
    # 4. WRITES THAT LAND AT EVERY POINT OF THE FRAME, including the last three
    #    cycles, where the queue snapshot has already been taken and the write
    #    belongs to the frame AFTER next. Alternate DVOL between two values so
    #    landing a frame early or late is audible in the output.
    f += 20
    for off in (0, 1, 2, 7, 8, 9, 60, 128, 200, 236, 237, 238, 239, 240, 250, 254, 255):
        send(0, A["DVOL"], 16384 if (off % 2) else 24576, off=off, gap=3)
        f += 3
    # 5. the master rail: push both busses hard at once and make it clip
    f += 10
    send(0, A["DVOL"], 65535)
    f += 3
    send(0, A["VOL"], 65535)
    f += 3
    send(0, A["DRUM_TRIG"], 0x02)
    f += 30
    send(0, A["DRUM_TRIG"], 0x00)
    # 6. RESET (0x23): the whole datapath to zero, then the patch back on
    if name == "full":
        f += 40
        send(0, A["RESET"], 0)
        f += 5
        send(0, A["VOL"], int(regs["vol"]))
        f += 3
        send(0, A["DVOL"], 16384)
        f += 3
        send(0, A["GATE_OFF"], 0)
    f += 40
    n = f + 20
    return cmds, n, f"{len(cmds)} SPI transactions over {n} frames at SCK = clk/{2*sckh}"


# ---- the link's rule: from the CS_N pin edge to the frame the write lands in --
def landing_frame(rise_frame: int, rise_off: int) -> int:
    """DR 0007 section 5 / spi_ctl.v: CS_N's rising edge is seen through two
    synchroniser flops and an edge detector, so the transaction is ACCEPTED
    SYNC_CYCLES core cycles after the pin edge; `tick` snapshots the queue at
    cycle 0, and a write accepted in the tick cycle or later belongs to the
    NEXT frame. So the write is applied in the frame whose tick is the first
    one strictly after the accept."""
    acc = rise_off + SYNC_CYCLES
    return rise_frame + 1 if acc <= 255 else rise_frame + 2


# ---- run ---------------------------------------------------------------------
def simulate(outdir: str, cmds, n: int, sckh: int, defines: list, rtl: str = None, timeout_s=1800.0):
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_synth_top: iverilog/vvp not on PATH"); return None
    os.makedirs(outdir, exist_ok=True)
    cmd_file = os.path.join(outdir, "top_bx_cmds.txt")
    log_file = os.path.join(outdir, "top_bx_log.txt")
    with open(cmd_file, "w") as fh:
        fh.writelines("%d %d %d %d %d\n" % c for c in cmds)
    if os.path.exists(log_file): os.remove(log_file)
    srcs = ["tb_top_bx.v", "synth_top.v", "spi_ctl.v", "voice_dp.v", "recip_div.v",
            "ladder_dp_n.v", "i2s_tx.v", "modal_dp_rom.v", "modal_coef_rom_p8.v"]
    if rtl:
        srcs = [rtl if f == "voice_dp.v" else f for f in srcs]
    vvp_file = os.path.join(outdir, "tb_top_bx.vvp")
    r = subprocess.run([iverilog, "-g2012", "-o", vvp_file] + [f"-D{d}" for d in defines] + srcs,
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_synth_top: iverilog failed:\n" + r.stdout + r.stderr); return None
    try:
        r = subprocess.run([vvp, "-n", vvp_file, f"+cmd={cmd_file}", f"+log={log_file}",
                            f"+frames={n}", f"+sckh={sckh}"],
                           cwd=HERE, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print("verify_synth_top: simulation timed out"); return None
    for l in r.stdout.splitlines():
        if l.startswith("tb_top_bx"): print("  sim: " + l)
    if r.returncode != 0 or not os.path.exists(log_file):
        print("verify_synth_top: vvp failed:\n" + r.stdout + r.stderr); return None
    return log_file


def parse_log(path: str) -> dict:
    smp, i2s, csn, wr, end = {}, [], [], [], None
    for line in open(path):
        t = line.split()
        if not t: continue
        if t[0] == "SMP":   smp[int(t[1])] = (int(t[2]), t[3:])
        elif t[0] == "I2S": i2s.append((int(t[1]), int(t[2]), int(t[3]), int(t[4])))
        elif t[0] == "CSN": csn.append((int(t[1]), int(t[2]), int(t[3]), int(t[4]), int(t[5])))
        elif t[0] == "WR":  wr.append((int(t[1]), int(t[2]), int(t[3]), int(t[4]), int(t[5])))
        elif t[0] == "END": end = [int(x) for x in t[1:]]
    return dict(smp=smp, i2s=i2s, csn=csn, wr=wr, end=end)


def compare(log: dict, n: int, name="verify_synth_top") -> int:
    smp, i2s, csn, wr, end = log["smp"], log["i2s"], log["csn"], log["wr"], log["end"]
    if end is None or not smp:
        print(f"{name}: the bench did not run to completion (no END line or no samples)"); return 2
    frames, n_sent, busy_at_tick, overrun, overflow, xsample = end
    ok = True
    print(f"{name}: {frames} frames, {n_sent} SPI transactions, {len(smp)} samples, "
          f"{len(i2s)} I2S slots, {len(wr)} register writes applied")
    if xsample:
        print(f"{name}: FAIL -- {xsample} samples were X (the datapath did not elaborate or was optimised away)")
        ok = False
    if busy_at_tick or overrun:
        print(f"{name}: FAIL -- datapath busy at {busy_at_tick} ticks, overrun flag {overrun}"); ok = False
    if overflow:
        print(f"{name}: FAIL -- the write queue overflowed"); ok = False

    # ---- 1. the SPI landing check: pin event -> predicted frame vs the port ----
    pred = [(landing_frame(f, off), flag, addr, data) for f, off, flag, addr, data in csn]
    obs = [(f, flag, addr, data) for f, off, flag, addr, data in wr]
    n_late = sum(1 for f, off, *_ in csn if off + SYNC_CYCLES > 255)
    if len(pred) != len(obs):
        print(f"{name}: FAIL -- {len(pred)} CS_N edges at the pin but {len(obs)} writes at the "
              f"register port"); ok = False
    bad = [(i, p, o) for i, (p, o) in enumerate(zip(pred, obs)) if p != o]
    off_range = sorted({off for _, off, *_ in wr})
    if bad:
        print(f"{name}: FAIL -- {len(bad)} of {len(pred)} writes did not land where the link's rule "
              f"says they must")
        for i, p, o in bad[:5]:
            print(f"    write {i}: predicted frame {p[0]} addr 0x{p[2]:02x} data {p[3]}, "
                  f"chip applied in frame {o[0]} addr 0x{o[2]:02x} data {o[3]}")
        ok = False
    else:
        print(f"{name}: SPI landing -- all {len(pred)} writes applied in the predicted frame "
              f"(pin CS_N edge + {SYNC_CYCLES} cycles, then the next tick); "
              f"{n_late} of them landed in the last {SYNC_CYCLES} cycles of a frame and so "
              f"belonged to the frame after next; the drain used cycles {off_range}")

    # ---- 2. the model, driven by the predicted write schedule ----
    m = SynthTopModel()
    res = m.run([(f, flag, addr, data) for f, flag, addr, data in pred if f < n], n)
    mism = {t: 0 for t in TAPS}
    first = {}
    frames_cmp = sorted(f for f in smp if f < n)
    for f in frames_cmp:
        _, vals = smp[f]
        for j, t in enumerate(TAPS):
            g = vals[j]
            e = int(res[t][f]) if t in res else None
            if e is None: continue
            if g == "x" or int(g) != e:
                mism[t] += 1
                if t not in first: first[t] = (f, e, g)
    total = sum(mism.values())
    if total:
        print(f"{name}: FAIL -- {mism['sample']} of {len(frames_cmp)} samples differ from the model; "
              + ", ".join(f"{t} {c}" for t, c in mism.items() if c and t != "sample"))
        for t in TAPS:
            if t in first:
                f, e, g = first[t]
                print(f"    first {t} mismatch at frame {f}: model {e}, chip {g}")
        ok = False
    else:
        print(f"{name}: datapath -- {len(frames_cmp)} frames, every sample and every one of the "
              f"{len(TAPS)-1} taps identical to the model")

    # ---- 3. the I2S stream, decoded from SDATA, against the MODEL ----
    # Period f carries the sample strobed in frame f-1 (contract 13, D = 1),
    # on BOTH channels. Nothing here is compared against the DUT's own stream.
    i2s_cmp = [(f, slot, nbits, w) for f, slot, nbits, w in i2s if 1 <= f < n]
    bad_bits = [(f, slot, nb) for f, slot, nb, _ in i2s_cmp if nb != 32]
    bad_word, bad_lr = 0, 0
    firsti = None
    by_frame = {}
    for f, slot, nb, w in i2s_cmp:
        by_frame.setdefault(f, {})[slot] = w
    for f, slots in sorted(by_frame.items()):
        if len(slots) != 2: continue
        exp = int(res["i2s"][f])
        for slot in (0, 1):
            if slots[slot] != exp:
                bad_word += 1
                if firsti is None:
                    firsti = (f, slot, exp, slots[slot])
        if slots[0] != slots[1]:
            bad_lr += 1
    if bad_bits:
        print(f"{name}: FAIL -- {len(bad_bits)} I2S slots did not carry 32 BCLK"); ok = False
    if bad_word or bad_lr:
        print(f"{name}: FAIL -- {bad_word} I2S words differ from the MODEL, {bad_lr} periods "
              f"where left and right differ")
        if firsti:
            f, slot, e, g = firsti
            print(f"    first at period {f} slot {'LR'[slot]}: model {e}, wire {g}"
                  + (f" (= model << 1)" if g == ((e << 1) & 0xFFFF) else "")
                  + (f" (= model >> 1)" if g == (e >> 1) else ""))
        ok = False
    else:
        print(f"{name}: I2S -- {len(by_frame)} LRCLK periods decoded from SDATA, every word equals "
              f"the MODEL's sample of the previous frame (D = 1) on both channels")

    nz = int(np.count_nonzero(res["sample"]))
    peak = int(np.max(np.abs(res["sample"]))) if len(res["sample"]) else 0
    clip = int(np.count_nonzero(np.abs(res["sample"]) == 32767) + np.count_nonzero(res["sample"] == -32768))
    dfilt_frames = int(np.count_nonzero(res["d19"] != res["drum_bus"]))
    print(f"{name}: coverage -- {nz} non-silent frames, peak |sample| {peak}, {clip} frames at the rail, "
          f"{dfilt_frames} frames with the drum filter engaged, "
          f"drum bus non-zero on {int(np.count_nonzero(res['drum_bus']))} frames")
    if peak == 0:
        print(f"{name}: FAIL -- the model says the chip is silent for the whole run"); ok = False
    print(f"{name}: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    ap.add_argument("--scenario", default="full")
    ap.add_argument("--sckh", type=int, default=4)
    ap.add_argument("--inject", default=None)
    ap.add_argument("--expect-fail", action="store_true")
    ap.add_argument("--rtl", default=None, metavar="FILE",
                    help="simulate FILE in place of voice_dp.v -- the red run of\n"
                         "docs/verification-rules.md: stubs/voice_dp_stub.v, every output X")
    ap.add_argument("--compare-only", default=None, metavar="LOG")
    a = ap.parse_args(argv)
    a.outdir = os.path.abspath(a.outdir)
    cmds, n, desc = scenario(a.scenario, a.sckh)
    print(f"verify_synth_top: model SynthTopModel (whole chip); scenario '{a.scenario}': {desc}")
    defines = [f"INJECT_BUG_TOP_{a.inject}"] if a.inject else []
    if a.compare_only:
        log = a.compare_only
    else:
        print(f"verify_synth_top: simulating synth_top.v through its pins"
              + (f" ({a.rtl} in place of voice_dp.v)" if a.rtl else "")
              + (f" with INJECT_BUG_TOP_{a.inject}" if a.inject else ""))
        log = simulate(a.outdir, cmds, n, a.sckh, defines, rtl=a.rtl)
        if log is None: return 2
    status = compare(parse_log(log), n)
    if a.expect_fail:
        if status == 1:
            print(f"verify_synth_top: negative control {a.inject or ''} CAUGHT (comparison failed as required)")
            return 0
        print(f"verify_synth_top: NEGATIVE CONTROL NOT CAUGHT (status {status})")
        return 1 if status == 0 else 2
    return status


if __name__ == "__main__":
    sys.exit(main())
