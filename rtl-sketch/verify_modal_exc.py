#!/usr/bin/env python3
"""The excitation-hold property of the modal bank (docs/ARCHITECTURE.md 4.4),
verified against model/modal_fixed.py with no tolerance.

THE HAZARD.  A four-mode pass is 15 cycles and the strike enters the state
once per MODE, three cycles apart (mode m at cycle sample_valid + 2 + 3m).
Whatever value is on `exc` at that cycle is what that mode receives.  Every
existing modal bench -- tb_modal.v, tb_modal_fx.v, tb_modal_rom.v -- holds
`exc` constant for the whole pass, so a module that reads `exc`
combinationally is indistinguishable there from one that registers it.  The
hazard is invisible exactly where it matters.

THIS BENCH changes `exc` partway through the pass and requires the output the
model computes for the value present when `sample_valid` was accepted.

    --mode hold      exc_after == exc_at_sv; must pass against anything
    --mode change    exc_after != exc_at_sv; passes only if exc is latched
    --delay N        cycles after sample_valid at which exc changes (default 4:
                     after mode 0 has read it, before mode 1 does)
    --inject NAME    compile with -DINJECT_BUG_MODAL_<NAME>
    --expect-fail    invert the verdict: exit 0 only if the comparison gave 1

Exit status: 0 identical, 1 ran and differed, 2 did not run.
"""
from __future__ import annotations
import argparse, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model")); sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np
from modal_fixed import ModalFx
from verify_ladder import tool

PRESET_NOTES = [28, 40, 52, 64, 76, 88, 100, 112]     # gen_modal_rom.py's P=8 table


def stimulus(n_per_preset: int = 240, presets=(0, 2, 5)) -> list:
    """(preset, exc_at_sv, exc_after): a strike then a long ring, per preset.
    exc_after is a value no mode should ever see -- large and of the opposite
    sign, so a mode that reads it is unmistakable."""
    out = []
    rng = np.random.default_rng(7)
    for p in presets:
        for i in range(n_per_preset):
            if i < 77:                                  # 1.6 ms burst at 48 kHz
                e = int(rng.integers(-32768, 32767))
            else:
                e = 0
            after = -32768 if e >= 0 else 32767
            out.append((p, e, after))
    return out


def generate(outdir: str, mode: str, verbose=True):
    m = ModalFx()
    rows, expected = [], []
    last_p = None
    for p, e, after in stimulus():
        if p != last_p:
            coefs = m.coefficients(PRESET_NOTES[p]); last_p = p   # state persists, as the RTL's does
        y = int(m.process(np.array([e], dtype=np.int16), coefs)[0])
        a = e if mode == "hold" else after
        rows.append(f"{e & 0xffff:04x}{a & 0xffff:04x}{p:02x}00{y & 0xffff:04x}\n")
        expected.append(y)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "modal_exc_vectors.hex"), "w") as fh:
        fh.writelines(rows)
    if verbose:
        nz = sum(1 for r in rows if r[:4] != "0000")
        print(f"verify_modal_exc: {len(expected)} samples over presets "
              f"{sorted(set(p for p, _, _ in stimulus()))} (notes "
              f"{[PRESET_NOTES[p] for p in sorted(set(p for p, _, _ in stimulus()))]}), "
              f"{nz} non-zero strikes; mode={mode}")
    return expected


def simulate(outdir: str, delay: int, defines: list, timeout_s: float = 600.0):
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_modal_exc: iverilog/vvp not on PATH"); return None
    vvp_file = os.path.join(outdir, "tb_modal_exc.vvp")
    out_file = os.path.join(outdir, "modal_exc_rtl_out.txt")
    if os.path.exists(out_file): os.remove(out_file)
    cmd = [iverilog, "-g2012", "-o", vvp_file] + [f"-D{d}" for d in defines] + \
          ["tb_modal_exc.v", "modal_dp_rom.v", "modal_coef_rom_p8.v"]
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_modal_exc: iverilog failed:\n" + r.stdout + r.stderr); return None
    try:
        r = subprocess.run([vvp, "-n", vvp_file,
                            f"+vec={os.path.join(outdir, 'modal_exc_vectors.hex')}",
                            f"+out={out_file}", f"+delay={delay}"],
                           cwd=HERE, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print("verify_modal_exc: simulation timed out"); return None
    for l in r.stdout.splitlines():
        if l.startswith("tb_modal_exc") or "EXC NOT HELD" in l:
            print("  sim: " + l)
    if r.returncode != 0 or not os.path.exists(out_file):
        print("verify_modal_exc: vvp failed:\n" + r.stdout + r.stderr); return None
    return out_file


def compare(expected, out_file, name="verify_modal_exc") -> int:
    try:
        toks = open(out_file).read().split()
    except OSError:
        print(f"{name}: no RTL output at {out_file}"); return 2
    got = []
    for t in toks:
        try: got.append(int(t))
        except ValueError: got.append(None)
    if len(got) < len(expected):
        print(f"{name}: RTL produced {len(got)} of {len(expected)} samples -- did not run to completion")
        return 2
    got = got[:len(expected)]
    mism = xs = maxerr = 0
    first = None
    for i, (e, r) in enumerate(zip(expected, got)):
        if r is None:
            xs += 1; mism += 1
            if first is None: first = (i, e, "x")
            continue
        if r != e:
            mism += 1; maxerr = max(maxerr, abs(r - e))
            if first is None: first = (i, e, r)
    if mism == 0:
        print(f"{name}: PASS -- {len(expected)} samples, RTL identical to the model")
        return 0
    print(f"{name}: FAIL -- {mism} of {len(expected)} samples differ ({xs} undefined/X), worst |error| {maxerr} LSB")
    print(f"  first mismatch at sample {first[0]}: model {first[1]}, RTL {first[2]}")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("hold", "change"), default="change")
    ap.add_argument("--delay", type=int, default=4)
    ap.add_argument("--inject", default=None)
    ap.add_argument("--expect-fail", action="store_true")
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    a = ap.parse_args(argv)
    a.outdir = os.path.abspath(a.outdir)
    expected = generate(a.outdir, a.mode)
    defines = ["MODAL_EXC_CHECK"] + ([f"INJECT_BUG_MODAL_{a.inject}"] if a.inject else [])
    print(f"verify_modal_exc: simulating modal_dp_rom.v (delay={a.delay}"
          + (f", INJECT_BUG_MODAL_{a.inject}" if a.inject else "") + ")")
    out = simulate(a.outdir, a.delay, defines)
    status = 2 if out is None else compare(expected, out)
    if a.expect_fail:
        if status == 1:
            print(f"verify_modal_exc: negative control {a.inject or a.mode} CAUGHT (comparison failed as required)")
            return 0
        print(f"verify_modal_exc: NEGATIVE CONTROL NOT CAUGHT (status {status})")
        return 1 if status == 0 else 2
    return status


if __name__ == "__main__":
    sys.exit(main())
