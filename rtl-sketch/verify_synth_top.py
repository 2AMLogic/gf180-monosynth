#!/usr/bin/env python3
"""Bit-exact verification of the WHOLE CHIP, at its pins, against
model/synth_top_model.py.

    .venv/bin/python rtl-sketch/verify_synth_top.py

What it does:

  1. builds a write stream -- the voice's patch image (model/voice_fx.py's own
     conversion), the reference drum kit (model/drums_fx.py's kit_808, contract
     Appendix G), then notes, drum hits, a retune while a body rings, ROUTE
     switched to the drum filter mid-run, and a volume change;
  2. runs tb_top_bx.v, which sends every one of those over the SPI PINS as
     48-bit DR 0007 revision 2 frames, reports which frame each write landed
     in, and decodes the I2S wire the way a DAC does -- from BCLK, LRCLK and
     SDATA only, never from inside the DUT;
  3. runs the model on the writes at the frames PREDICTED FROM THE PIN, after
     checking each one arrived with its payload intact, in order, and in the
     frame the prediction named;
  4. compares THE DECODED I2S WORDS against the MODEL, with no tolerance.

The model is driven by the frames PREDICTED FROM THE CS_N PIN (the acceptance
cycle is the pin edge plus DR 0007 section 5's three synchroniser cycles, and
a write received during frame f applies at the start of f+1), and the chip is
separately required to agree with that prediction. Driving the model with the
frame the CHIP reported would have been self-referential: a link that delayed
every write by a frame would move the model with it and no comparison could
see it. `LAST` records what any failure actually was, so a caller can check
that a negative control failed for the reason it was recorded to fail for and
not for some other one.

Point 4 is the whole point. rtl-sketch/tb_synth_top.v compares the I2S stream
against `dut.sample` -- the DUT's own output -- which is circular and cannot
detect a bit shift, a channel swap or a wrong D. The comparison here is
against a number the chip had no part in producing.

Exit status, as verify_ladder.py: 0 identical, 1 differed, 2 did not run.

  --inject NAME   compile with -DINJECT_BUG_<NAME>. Controls that must turn
                  this red: VOICE_MASTER_PRESHIFT (each product floored before
                  the sum instead of contract 12's single shift),
                  VOICE_DRUM_CLAMP16 (the drum buses clipped to 16 bits before
                  their gains), VOICE_OUT_SAT (no rail), I2S_SHIFT (the wire
                  one bit late), I2S_SWAP (channels swapped), I2S_D0 (the
                  sample sent in its own period, D = 0), SPI_ADDR7, SPI_DATA24,
                  SPI_NOSEC, MODAL_NUM_HOLD, DRUM_ENV_FLOOR, DRUM_LFSR_TAP
  --expect-fail   exit 0 only if the comparison gave 1
  --short         a third of the stimulus
  --frames N      override the run length
"""
from __future__ import annotations
import argparse, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np
import voice_fx as vf
import drums_fx as dx
import synth_top_model as stm
from verify_ladder import tool

SEC_V, SEC_D = 0, 1
A = stm
WAVE_CODE = dict(saw=0, square=1, pulse25=2, tri=3, sine=4)
SRCS = ("synth_top.v", "voice_dp.v", "spi_ctl.v", "drum_regs.v", "drum_kit.v",
        "drum_dp.v", "modal_dp.v", "i2s_tx.v", "ladder_dp_n.v", "recip_div.v")


def script(short: bool = False):
    """(wait_frames, flag, sec, addr, data) in send order, and the frames to run
    after the last write. `wait_frames` is how many frame ticks the bench waits
    before starting that transaction; the frame a write LANDS in is the link's
    business and comes back from the bench."""
    S = 0.35 if short else 1.0
    regs = vf.VoiceFx.patch_regs()
    w = []
    def put(wait, flag, sec, addr, data): w.append((wait, flag, sec, addr, data))

    # ---- 1. the voice image, back to back (the MCU's boot-time patch load) ----
    for k, s in enumerate(regs["waves"]):   put(0, 0, SEC_V, A.A_WAVE + k, WAVE_CODE[s])
    for base, key in ((A.A_AMP, "amp"), (A.A_FILT, "fenv")):
        for j, v in enumerate(regs[key]):   put(0, 0, SEC_V, base + j, v)
    for nm, key in (("A_CUT_LO", "cut_lo"), ("A_CUT_HI", "cut_hi"), ("A_K", "k"),
                    ("A_GAIN", "gain"), ("A_OGAIN", "ogain"), ("A_GLIDE", "glide")):
        put(0, 0, SEC_V, getattr(A, nm), regs[key])
    put(0, 0, SEC_V, A.A_VOL,  regs["vol"])
    put(0, 0, SEC_V, A.A_DVOL, dx.accent_reg(0.45))          # DR 0005's reference drum gains
    put(0, 0, SEC_V, A.A_BVOL, dx.accent_reg(0.45))
    put(0, 0, SEC_V, A.A_DCUT, 1800)
    put(0, 0, SEC_V, A.A_DK,     regs["k"])
    put(0, 0, SEC_V, A.A_DGAIN,  regs["gain"])
    put(0, 0, SEC_V, A.A_DOGAIN, regs["ogain"])
    for k, v in enumerate(vf.VoiceFx.note_incs(45, regs["detune"])):
        put(0, 1, SEC_V, A.A_INC + k, v)                     # flag = jump
    put(0, 0, SEC_V, A.A_TRACK, vf.VoiceFx.note_track(45, regs["track"]))
    for k, g in enumerate(regs["weights"]): put(0, 0, SEC_V, A.A_W + k, g)

    # ---- 2. the drum image: the reference kit, plus an accent of 1.0 per stop ----
    for a, v in dx.kit_808():               put(0, 0, SEC_D, a, v)
    for s in range(dx.N_STOPS):             put(0, 0, SEC_D, dx.A_ACCENT + s, dx.accent_reg(1.0))

    # ---- 3. play. The voice first alone, then with drums, then through the filter ----
    gap = max(2, int(14 * S))
    put(8, 0, SEC_V, A.A_GATE_ON, 0)                          # a note, drums silent
    put(gap * 2, 0, SEC_D, dx.A_STOPS, 1 << dx.BD)            # bass drum
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    put(gap, 0, SEC_D, dx.A_STOPS, (1 << dx.CH) | (1 << dx.SD))
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    put(gap, 0, SEC_D, dx.A_STOPS, (1 << dx.OH))              # the OH -> CH choke
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    put(gap, 0, SEC_V, A.A_TRIG, 0)                           # re-trigger the voice under the ring
    put(gap, 0, SEC_D, dx.A_STOPS, 0xFF)                      # every stop in one frame
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    # retune the bass drum WHILE it rings -- a coefficient write mid-decay, which
    # is the write-atomicity case: a1 lands one frame, a2 the next (DR 0008)
    for a, v in dx.mode_writes(dx.M_BD, dx.BD_HZ_CHART, dx.bd_decay_q(1.0), 0.0)[:2]:
        put(gap // 2, 0, SEC_D, a, v)
    put(gap, 0, SEC_D, dx.A_STOPS, 1 << dx.BD)
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    # ---- the drum filter engaged mid-run (ROUTE.DFILT), then a louder master ----
    put(gap, 0, SEC_V, A.A_ROUTE, 1)
    put(gap, 0, SEC_D, dx.A_STOPS, (1 << dx.BD) | (1 << dx.CH))
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    put(gap, 0, SEC_V, A.A_DCUT, 400)                         # sweep the drum filter down
    put(gap, 0, SEC_D, dx.A_STOPS, (1 << dx.OH) | (1 << dx.SD))
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    put(gap, 0, SEC_V, A.A_DVOL, 65535)                       # the gains at their top: the rail
    put(0, 0, SEC_V, A.A_BVOL, 65535)
    put(gap, 0, SEC_D, dx.A_STOPS, 0xFF)
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    put(gap, 0, SEC_V, A.A_GATE_OFF, 0)                       # release: the note ends, drums ring on
    put(gap, 0, SEC_V, A.A_ROUTE, 0)                          # back to bypass, mid-ring
    put(gap, 0, SEC_D, dx.A_STOPS, 1 << dx.CB)
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    # ---- the envelope DEAD ZONE (15.3 / 8.3), reached on purpose -------------
    # Below 2^16/rate the exponential step is zero; without the max(1, .) the
    # level FREEZES there instead of running out at one LSB per frame. From a
    # full-scale strike the open hat takes ~57 000 frames to descend that far,
    # which no run of this length reaches -- so the rule is exercised by
    # striking it from a peak just above its freeze level instead. Without this
    # write INJECT_BUG_DRUM_ENV_FLOOR goes uncaught here, and it did.
    kit = dict(dx.kit_808())
    e = dx.E_OH
    rate = kit[dx.A_ENV + e * 4 + 2]
    freeze = 65535 // rate                       # largest level whose step is zero
    put(gap, 0, SEC_D, dx.A_ENV + e * 4 + 1, freeze + 64)
    put(gap, 0, SEC_D, dx.A_STOPS, 1 << dx.OH)
    put(2, 0, SEC_D, dx.A_STOPS, 0)
    # The tail must outlast the SLOWEST envelope's linear floor, or the dead-zone
    # rule of 15.3 / 8.3 is never exercised and INJECT_BUG_DRUM_ENV_FLOOR goes
    # uncaught: below 2^16/rate the exponential step is zero and the tail runs at
    # one LSB per frame, which is hundreds of frames for the open hat.
    tail = int(1500 * S) if not short else int(260 * S)
    return w, tail


def write_cmds(path: str, w) -> None:
    with open(path, "w") as fh:
        for wait, flag, sec, addr, data in w:
            fh.write(f"{wait} {flag} {sec} {addr} {data}\n")


def simulate(defines, outdir, frames, timeout_s=5400.0):
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_synth_top: iverilog/vvp not on PATH (or set OSS_CAD_SUITE)"); return None
    tag = "_".join(d.replace("INJECT_BUG_", "") for d in defines) or "base"
    vvp_file = os.path.join(outdir, f"tb_top_bx_{tag}.vvp")
    out = {k: os.path.join(outdir, f"top_{k}_{tag}.txt") for k in ("i2s", "samp", "wrs")}
    for f in out.values():
        if os.path.exists(f): os.remove(f)
    srcs = [os.path.join(HERE, f) for f in SRCS] + [os.path.join(HERE, "tb_top_bx.v")]
    r = subprocess.run([iverilog, "-g2012", "-o", vvp_file] + [f"-D{d}" for d in defines] + srcs,
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_synth_top: iverilog failed:\n" + r.stdout + r.stderr); return None
    try:
        r = subprocess.run([vvp, "-n", vvp_file, f"+cmd={os.path.join(outdir, 'top_bx_cmds.txt')}",
                            f"+i2s={out['i2s']}", f"+samp={out['samp']}", f"+wrs={out['wrs']}",
                            f"+frames={frames}"], cwd=HERE, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print("verify_synth_top: simulation timed out"); return None
    sys.stdout.write("".join("  sim: " + l + "\n" for l in r.stdout.splitlines() if l.startswith("tb_top_bx")))
    if r.returncode != 0 or not os.path.exists(out["i2s"]):
        print("verify_synth_top: vvp failed:\n" + r.stdout + r.stderr); return None
    return out


def rows(path):
    return [ln.split() for ln in open(path).read().splitlines() if ln.strip()]


# What the last run actually found. A negative control must be checked against
# the failure it was RECORDED to cause, not merely against a non-zero status:
# an expectation satisfied by the wrong failure is not evidence.
LAST: dict = {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inject", default=None); ap.add_argument("--expect-fail", action="store_true")
    ap.add_argument("--short", action="store_true"); ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    a = ap.parse_args(argv)
    a.outdir = os.path.abspath(a.outdir); os.makedirs(a.outdir, exist_ok=True)

    cmds, tail = script(a.short)
    write_cmds(os.path.join(a.outdir, "top_bx_cmds.txt"), cmds)
    print(f"verify_synth_top: {len(cmds)} writes over the pins "
          f"({sum(1 for c in cmds if c[2] == SEC_V)} voice, {sum(1 for c in cmds if c[2] == SEC_D)} drum), "
          f"{tail} frames after the last")
    defines = [f"INJECT_BUG_{a.inject}"] if a.inject else []
    if defines: print(f"verify_synth_top: simulating with {defines[0]}")
    out = simulate(defines, a.outdir, tail)
    if out is None:
        return 2

    # ---- what the chip says it received, and when --------------------------
    wr = rows(out["wrs"])
    if len(wr) != len(cmds):
        print(f"verify_synth_top: FAIL -- {len(wr)} writes reached the register port, {len(cmds)} were sent")
        if not wr: return 2
    bad = 0
    for (want, got) in zip(cmds, wr):
        if (int(got[1]), int(got[2]), int(got[3]), int(got[4])) != (want[1], want[2], want[3], want[4] & 0xFFFFFFFF):
            bad += 1
    LAST.update(writes_bad=bad, writes_seen=len(wr), writes_sent=len(cmds))
    if bad:
        print(f"verify_synth_top: FAIL -- {bad} of {len(cmds)} writes arrived corrupted "
              f"(run verify_ctl.py: that is the link, not the datapath)")
        return 1
    # the landing frame the PIN predicts, and whether the chip agreed
    pred_bad = sum(1 for g in wr if len(g) > 5 and int(g[5]) >= 0 and int(g[5]) != int(g[0]))
    no_pred = sum(1 for g in wr if len(g) <= 5 or int(g[5]) < 0)
    LAST.update(frame_pred_bad=pred_bad, frame_no_pred=no_pred)
    if pred_bad or no_pred:
        print(f"verify_synth_top: FAIL -- {pred_bad} write(s) landed in a frame the CS_N pin did not "
              f"predict, {no_pred} with no prediction at all: the link's timing is not DR 0007 section 5's")
        return 1
    # drive the model from the PREDICTION, not from what the chip reported
    model_writes = [(int(g[5]), int(g[1]), int(g[2]), int(g[3]), int(g[4])) for g in wr]
    last = max(f for f, *_ in model_writes)
    n = a.frames or (last + tail + 1)
    print(f"verify_synth_top: writes landed in frames {model_writes[0][0]}..{last}; modelling {n} frames")

    # ---- the model, on those frames ----------------------------------------
    m = stm.SynthTopModel().run(model_writes, n)
    exp_i2s, exp_s = m["i2s"], m["sample"]

    # ---- the comparison: the WIRE against the MODEL -------------------------
    i2s = rows(out["i2s"])
    if not i2s:
        print("verify_synth_top: FAIL -- no I2S periods decoded from the wire"); return 2
    nper = min(len(i2s), n)
    mism = swap = width = xs = 0
    first = None
    for r in i2s[:nper]:
        p, left, right, nbl, nbr = (int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]))
        if p >= n: break
        if nbl != 32 or nbr != 32:
            width += 1
        e = int(exp_i2s[p])
        if left != e:
            mism += 1
            if first is None: first = (p, e, left)
        if right != left:
            swap += 1
    # the DUT's own stream, as a DIAGNOSTIC only
    sm = rows(out["samp"])
    core_bad = sum(1 for r in sm if int(r[0]) < n and int(r[1]) != int(exp_s[int(r[0])]))
    core_first = next(((int(r[0]), int(exp_s[int(r[0])]), int(r[1])) for r in sm
                       if int(r[0]) < n and int(r[1]) != int(exp_s[int(r[0])])), None)
    peak = int(np.abs(exp_s).max())
    clipped = int(np.sum(np.abs(exp_s) == 32767) + np.sum(exp_s == -32768))
    print(f"verify_synth_top: model peak |sample| {peak} of 32768 ({clipped} frames at the rail); "
          f"drums |dmix| max {int(np.abs(m['dmix']).max())}, |body| max {int(np.abs(m['body']).max())}, "
          f"DFILT engaged in {int(m['route'].sum())} frames")
    LAST.update(wire_mismatch=mism, swap=swap, width=width, core_bad=core_bad, periods=nper)
    if mism == 0 and swap == 0 and width == 0 and core_bad == 0:
        print(f"verify_synth_top: PASS -- {nper} I2S periods decoded from the wire, every one identical "
              f"to the model; both channels agree; every slot 32 BCLK; the core's own stream matches too")
        return 0
    print(f"verify_synth_top: FAIL -- of {nper} decoded I2S periods: {mism} differ from the model, "
          f"{swap} have L != R, {width} have a slot that is not 32 BCLK")
    if first:
        p, e, g = first
        print(f"  first wire mismatch at period {p}: model {e}, wire {g}, error {g - e:+d} LSB")
    print(f"  the core's own sample stream: {core_bad} of {len(sm)} frames differ from the model"
          + (f"; first at frame {core_first[0]}: model {core_first[1]}, core {core_first[2]}" if core_first else ""))
    if core_bad == 0 and mism:
        print("  the core is right and the wire is wrong: the defect is in i2s_tx or its timing")
    elif core_bad and mism:
        print("  the core is already wrong: the defect is upstream of the serialiser")
    return 1


if __name__ == "__main__":
    st = main()
    ap_fail = "--expect-fail" in sys.argv
    if ap_fail:
        inj = sys.argv[sys.argv.index("--inject") + 1] if "--inject" in sys.argv else "?"
        if st == 1:
            print(f"verify_synth_top: negative control {inj} CAUGHT (comparison failed as required)"); sys.exit(0)
        print(f"verify_synth_top: NEGATIVE CONTROL NOT CAUGHT (status {st})"); sys.exit(1 if st == 0 else 2)
    sys.exit(st)
