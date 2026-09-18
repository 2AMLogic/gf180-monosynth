#!/usr/bin/env python3
"""Generate (or --check) the tanh ROM images ladder_dp.v reads, FROM THE MODEL.

The table is `LadderFx(tanh_entries=N, interp=True).tbl`: N entries at bin
edges i/N * 4.0, Q1.15, plus one top word of 32767. That top word is the
model's, not tanh(4.0): `tanh_fx` interpolates the last bin up to 32767 so the
curve meets the clamp with no step, and the RTL must do the same or the two
disagree by up to 22 LSB across the top bin. The RTL reads 2^n + 1 words.

    python3 tanh_rom.py            # rewrite tanh16.hex and tanh256.hex
    python3 tanh_rom.py --check    # exit 1 if either file differs from the model
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import fixed

TABLES = {16: "tanh16.hex", 256: "tanh256.hex"}


def words(n: int) -> list[int]:
    f = fixed.LadderFx(tanh_entries=n, interp=True)
    return list(f.tbl) + [32767]


def render(n: int) -> str:
    return "".join(f"{w & 0xffff:04x}\n" for w in words(n))


def main(argv) -> int:
    check = "--check" in argv
    bad = 0
    for n, name in TABLES.items():
        path = os.path.join(HERE, name)
        want = render(n)
        if check:
            have = open(path).read() if os.path.exists(path) else None
            if have != want:
                bad += 1
                hw = have.split() if have else []
                ww = want.split()
                diffs = [i for i in range(max(len(hw), len(ww)))
                         if i >= len(hw) or i >= len(ww) or hw[i] != ww[i]]
                print(f"{name}: differs from model at {len(diffs)} of {len(ww)} words "
                      f"(first: index {diffs[0]}, have "
                      f"{hw[diffs[0]] if diffs[0] < len(hw) else '<missing>'}, want {ww[diffs[0]]})")
            else:
                print(f"{name}: matches model ({len(want.split())} words)")
        else:
            open(path, "w").write(want)
            print(f"wrote {name}: {len(want.split())} words")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
