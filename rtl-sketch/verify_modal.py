#!/usr/bin/env python3
"""Bit-exact verification of modal_dp.v against model/modal_fixed.py (ModalFx).

Same contract as verify_ladder.py: the model runs a stimulus, the RTL is
driven with the identical integers under iverilog, every output sample is
compared with no tolerance. Exit 0 identical / 1 mismatch / 2 did not run;
--inject NAME compiles -DINJECT_BUG_MODAL_<NAME>, --expect-fail inverts.
"""
from __future__ import annotations
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np
import modal_fixed
from modal_fixed import ModalFx, strike, f2q15
from dsp import SR, note_hz
from verify_ladder import tool, compare


def stimulus():
    """(name, exc_q15, note). State carries across segments: the second hit
    lands while the first still rings."""
    segs = [("note 28, strike 1.0",                    f2q15(strike(0.30, seed=2)), 28),
            ("note 52, strike 0.5, while ringing",      f2q15(strike(0.20, seed=3, amount=0.5)), 52),
            ("note 88, strike 1.0",                     f2q15(strike(0.15, seed=4)), 88),
            ("note 100: top mode above 0.45 fs, zero coefficients",
                                                        f2q15(strike(0.10, seed=5)), 100)]
    n = int(0.10 * SR)
    sq = np.sign(np.sin(2 * np.pi * note_hz(40) * np.arange(n) / SR))
    segs.append(("note 40, full-scale square AT f0: drives the state to the rail", f2q15(sq), 40))
    segs.append(("note 40, silence: ring-down from the rail", np.zeros(int(0.15 * SR), np.int16), 40))
    return segs


class Coverage:
    def __init__(self, m: ModalFx):
        self.m = m; self.y_sat = self.out_sat = 0
        self._sat = modal_fixed.sat; modal_fixed.sat = self._count
    def _count(self, v, bits):
        r = self._sat(v, bits)
        if r != v:
            if bits == 16: self.out_sat += 1
            else:          self.y_sat += 1
        return r
    def restore(self): modal_fixed.sat = self._sat


def generate(outdir: str, verbose=True):
    m = ModalFx()                                   # the proposed defaults
    cov = Coverage(m)
    lines, expected = [], []
    zero_modes = 0
    for name, xq, note in stimulus():
        coefs = m.coefficients(note)
        zero_modes += sum(1 for c in coefs if c == (0, 0, 0)) * len(xq)
        y = m.process(xq, coefs)
        for i in range(len(xq)):
            s = f"{int(xq[i]) & 0xffff:04x}"
            for a1, a2, amp in coefs:
                s += f"{a1 & 0xfffffff:07x}{a2 & 0xfffffff:07x}"
            s += "".join(f"{amp:04x}" for _, _, amp in coefs)
            s += f"{int(y[i]) & 0xffff:04x}\n"
            lines.append(s); expected.append(int(y[i]))
        if verbose:
            print(f"  segment: {name}: {len(xq)} samples, a1_0={coefs[0][0]} a2_0={coefs[0][1]}")
    cov.restore()
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "modal_vectors.hex"), "w").writelines(lines)
    open(os.path.join(outdir, "modal_expected.txt"), "w").writelines(f"{v}\n" for v in expected)
    if verbose:
        print(f"  {len(expected)} samples; model corners reached: state saturated {cov.y_sat}x, "
              f"output saturated {cov.out_sat}x, zero-coefficient mode on {zero_modes} mode-samples")
    return expected, cov


def simulate(rtl, tb, defines, outdir):
    """As verify_ladder.simulate, with this bench's file names and no parameter overrides."""
    import subprocess
    iverilog, vvp = tool("iverilog"), tool("vvp")
    if not iverilog or not vvp:
        print("verify_modal: iverilog/vvp not on PATH (or set OSS_CAD_SUITE)"); return None
    vvp_file = os.path.join(outdir, "tb_modal_fx.vvp"); out_file = os.path.join(outdir, "modal_rtl_out.txt")
    if os.path.exists(out_file): os.remove(out_file)
    r = subprocess.run([iverilog, "-g2012", "-o", vvp_file] + [f"-D{d}" for d in defines] + [tb, rtl],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print("verify_modal: iverilog failed:\n" + r.stdout + r.stderr); return None
    try:
        r = subprocess.run([vvp, "-n", vvp_file, f"+vec={os.path.join(outdir, 'modal_vectors.hex')}",
                            f"+out={out_file}"], cwd=HERE, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print("verify_modal: simulation timed out"); return None
    sys.stdout.write("".join("  sim: " + l + "\n" for l in r.stdout.splitlines() if l.startswith("tb_modal_fx")))
    if r.returncode != 0 or not os.path.exists(out_file):
        print("verify_modal: vvp failed:\n" + r.stdout + r.stderr); return None
    return out_file


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inject", default=None); ap.add_argument("--expect-fail", action="store_true")
    ap.add_argument("--compare-only", default=None, metavar="FILE")
    ap.add_argument("--rtl", default=os.path.join(HERE, "modal_dp.v"))
    ap.add_argument("--tb", default=os.path.join(HERE, "tb_modal_fx.v"))
    ap.add_argument("--outdir", default=os.path.join(HERE, "build"))
    a = ap.parse_args(argv)
    m = ModalFx()
    print(f"verify_modal: model ModalFx(coef Q2.{m.CF}, state {m.SB}-bit/{m.SQ} fraction, "
          f"headroom {m.HR}, {'rounding' if m.RND else 'floor'})")
    expected, _ = generate(a.outdir)
    if a.compare_only:
        status = compare(expected, a.compare_only, "verify_modal")
    else:
        defines = [f"INJECT_BUG_MODAL_{a.inject}"] if a.inject else []
        print(f"verify_modal: simulating {os.path.relpath(a.rtl, HERE)}{' with ' + defines[0] if defines else ''}")
        out = simulate(a.rtl, a.tb, defines, a.outdir)
        status = 2 if out is None else compare(expected, out, "verify_modal")
    if a.expect_fail:
        if status == 1:
            print(f"verify_modal: negative control {a.inject or ''} CAUGHT (comparison failed as required)"); return 0
        print(f"verify_modal: NEGATIVE CONTROL NOT CAUGHT (status {status})"); return 1 if status == 0 else 2
    return status


if __name__ == "__main__":
    sys.exit(main())
