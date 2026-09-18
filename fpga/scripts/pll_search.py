#!/usr/bin/env python3
"""Every core clock an ECP5 EHXPLLL can make from a given board oscillator,
ranked by how far it is from 12.288 MHz = 256 x 48 kHz.

    python3 fpga/scripts/pll_search.py            # the ULX3S's 25 MHz
    python3 fpga/scripts/pll_search.py --fin 12   # an iCEBreaker-style 12 MHz

Why this exists. `ecppll -i 25 -o 12.288` answers 12.5 MHz -- 17,253 ppm out,
30 cents sharp -- because it only uses the PRIMARY output, whose frequency with
FEEDBK_PATH="CLKOP" is Fin x CLKFB_DIV / CLKI_DIV: an integer ratio, and
12.288/25 = 1536/3125 with 3125 = 5^5 is not one. The secondary outputs have
their own divider off the same VCO, which makes the reachable set

    Fout = Fin / CLKI_DIV * CLKFB_DIV * CLKOP_DIV / CLKOS_DIV

and that set contains 725/59 MHz = 12.288135593 MHz, +11 ppm.

Datasheet limits enforced below (Lattice FPGA-DS-02012, ECP5/ECP5-5G):
  CLKI_DIV 1..128, CLKFB_DIV 1..80, CLKOP_DIV / CLKOS_DIV 1..128,
  PFD = Fin/CLKI_DIV in 3.125..400 MHz, VCO in 400..800 MHz,
  output in 3.125..400 MHz.
The design is the I2S master, so fs = Fout / 256 and the pitch error in cents
is 1200*log2(Fout/12.288e6) -- the clock error IS the tuning error.
"""
from __future__ import annotations
import argparse, math

CLKI_MAX, CLKFB_MAX, DIV_MAX = 128, 80, 128
PFD_MIN, PFD_MAX = 3.125, 400.0
VCO_MIN, VCO_MAX = 400.0, 800.0
OUT_MIN, OUT_MAX = 3.125, 400.0
TARGET_MHZ = 12.288          # 256 x 48 kHz


def reachable(fin_mhz: float, target: float = TARGET_MHZ, window: float = 3e-3):
    """Distinct outputs within `window` relative error, best first."""
    best = {}
    for ki in range(1, CLKI_MAX + 1):
        pfd = fin_mhz / ki
        if not (PFD_MIN <= pfd <= PFD_MAX):
            continue
        for kfb in range(1, CLKFB_MAX + 1):
            for kop in range(1, DIV_MAX + 1):
                vco = pfd * kfb * kop
                if vco < VCO_MIN:
                    continue
                if vco > VCO_MAX:
                    break
                # the secondary divider that lands nearest the target
                lo = max(1, int(vco / target) - 1)
                for kos in range(lo, min(DIV_MAX, lo + 3) + 1):
                    fo = vco / kos
                    if not (OUT_MIN <= fo <= OUT_MAX):
                        continue
                    err = abs(fo - target) / target
                    if err > window:
                        continue
                    key = round(fo, 12)
                    cand = (err, fo, ki, kfb, kop, kos, vco, pfd)
                    if key not in best or cand < best[key]:
                        best[key] = cand
    return sorted(best.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fin", type=float, default=25.0, help="oscillator MHz (ULX3S: 25)")
    ap.add_argument("--target", type=float, default=TARGET_MHZ)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    rows = reachable(a.fin, a.target)
    print(f"ECP5 EHXPLLL from {a.fin} MHz, target {a.target} MHz (= 256 x {a.target*1e6/256:.0f} Hz)")
    print(f"{'CLKOS MHz':>14}  {'ppm':>9}  {'cents':>7}  {'fs Hz':>11}   dividers")
    for err, fo, ki, kfb, kop, kos, vco, pfd in rows[:a.top]:
        print(f"{fo:14.9f}  {(fo-a.target)/a.target*1e6:+9.2f}  "
              f"{1200*math.log2(fo/a.target):+7.3f}  {fo*1e6/256:11.3f}   "
              f"CLKI_DIV={ki} CLKFB_DIV={kfb} CLKOP_DIV={kop} CLKOS_DIV={kos} "
              f"(VCO {vco:.4f}, PFD {pfd:.4f})")
    if not rows:
        print("  nothing within 0.3 % -- this oscillator cannot clock the instrument in tune")
        return 1
    err, fo, *_ = rows[0]
    print()
    print(f"best: {fo:.9f} MHz, {(fo-a.target)/a.target*1e6:+.2f} ppm, "
          f"{1200*math.log2(fo/a.target):+.3f} cents, fs = {fo*1e6/256:.3f} Hz")
    print("The ULX3S's own 25 MHz oscillator is specified at +-30 ppm, so at this")
    print("setting the crystal, not the PLL, dominates the tuning error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
