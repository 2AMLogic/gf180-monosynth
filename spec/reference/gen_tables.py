#!/usr/bin/env python3
"""Regenerate, FROM THE COMMITTED MODEL, every lookup table that
spec/NUMERIC-CONTRACT.md pins by SHA-256, and check that the contract and the
committed table images are still the model's.

The model is the specification; this script is what stops the prose from
drifting away from it. It does three things:

  1. Evaluates the four tables exactly as model/voice_fx.py and model/fixed.py
     build them (same functions, no re-derivation here):
        NOTE_INC   128 x 24-bit    dsp.phase_inc(dsp.note_hz(n))
        SINE_Q256  256 x Q1.15     dsp._QUARTER (midpoint-sampled quarter wave)
        TANH16      16 x Q1.15     fixed.LadderFx(tanh_entries=16, interp=True).tbl
        G_ROM128   129 x Q0.16     voice_fx.make_g_rom()  (128 entries + guard)
     plus two derived images the contract also states hashes for:
        SINE_FULL1024   the 1024-entry expansion via voice_fx.sine_fx
        TANH16_ROM      the 17-word ROM image ladder_dp.v reads (TANH16 + 32767)
  2. Writes each table as one hex word per line to spec/reference/tables/, and
     rewrites the appendix block of the contract between the two marker lines
     <!-- BEGIN GENERATED APPENDICES --> / <!-- END GENERATED APPENDICES -->.
  3. With --check, writes nothing: exits 1 if any committed hex image, the
     appendix block, rtl-sketch/tanh16.hex, or any hash the contract states
     differs from what the model produces right now.

    .venv/bin/python spec/reference/gen_tables.py           # regenerate
    .venv/bin/python spec/reference/gen_tables.py --check   # CI freshness

Hash encoding, the same as gf180-polysynth's contract: the decimal values
joined by commas with no spaces, SHA-256, lower-case hex.
"""
from __future__ import annotations
import hashlib, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "audition"))
import numpy as np                      # noqa: E402
import dsp, fixed, voice_fx as vf       # noqa: E402

CONTRACT = os.path.join(ROOT, "spec", "NUMERIC-CONTRACT.md")
TABLE_DIR = os.path.join(HERE, "tables")
RTL_TANH_HEX = os.path.join(ROOT, "rtl-sketch", "tanh16.hex")
BEGIN = "<!-- BEGIN GENERATED APPENDICES -->"
END = "<!-- END GENERATED APPENDICES -->"


def sha(vals) -> str:
    return hashlib.sha256(",".join(str(int(v)) for v in vals).encode()).hexdigest()


# ---- the tables, evaluated by the model's own code ---------------------------
def note_inc() -> list[int]:
    return [dsp.phase_inc(dsp.note_hz(n)) for n in range(128)]


def sine_q256() -> list[int]:
    return [int(v) for v in dsp._QUARTER]


def sine_full1024() -> list[int]:
    ph = np.arange(1024, dtype=np.int64) << (dsp.PHASE_BITS - 10)
    return [int(v) for v in vf.sine_fx(ph)]


def tanh16() -> list[int]:
    return list(fixed.LadderFx(**vf.LADDER_CFG).tbl)


def tanh16_rom() -> list[int]:
    return tanh16() + [32767]           # the top word tanh_fx interpolates toward


def g_rom128() -> list[int]:
    return [int(v) for v in vf.make_g_rom(vf.GROM_BITS, vf.LADDER_CFG.get("oversample", 2))]


# name, values, hex digits per word, signed?, hex file (None = derived only)
def tables():
    return [
        ("NOTE_INC", note_inc(), 6, False, "note_inc.hex"),
        ("SINE_Q256", sine_q256(), 4, True, "sine_q256.hex"),
        ("SINE_FULL1024", sine_full1024(), 4, True, None),
        ("TANH16", tanh16(), 4, True, "tanh16.hex"),
        ("TANH16_ROM", tanh16_rom(), 4, True, None),
        ("G_ROM128", g_rom128(), 4, False, "g_rom128.hex"),
    ]


def hex_image(vals, digits, signed) -> str:
    mask = (1 << (4 * digits)) - 1
    return "".join(f"{(v & mask) if signed else v:0{digits}x}\n" for v in vals)


# ---- the appendix text ------------------------------------------------------
def _rows(vals, per_row, fmt=lambda v: str(v)):
    out = []
    for i in range(0, len(vals), per_row):
        cells = [fmt(v) for v in vals[i:i + per_row]] + [""] * (per_row - len(vals[i:i + per_row]))
        out.append(f"| {i} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def appendix() -> str:
    ni, sq, sf, th, thr, gr = (note_inc(), sine_q256(), sine_full1024(),
                               tanh16(), tanh16_rom(), g_rom128())
    s = []
    s.append("### Appendix A -- NOTE_INC: MIDI note number -> 24-bit phase increment\n")
    s.append("Normative. `NOTE_INC[n] = round(440 * 2^((n-69)/12) * 2^24 / 48000)`, evaluated by "
             "`dsp.phase_inc(dsp.note_hz(n))`. Nominal frequency for reference only. "
             "Two notes per row.\n")
    s.append("| note | inc (dec) | inc (hex) | nominal Hz | | note | inc (dec) | inc (hex) | nominal Hz |")
    s.append("|---:|---:|---:|---:|---|---:|---:|---:|---:|")
    for n in range(64):
        a, b = n, n + 64
        s.append(f"| {a} | {ni[a]} | 0x{ni[a]:06X} | {dsp.note_hz(a):.3f} | "
                 f"| {b} | {ni[b]} | 0x{ni[b]:06X} | {dsp.note_hz(b):.3f} |")
    s.append(f"\nSHA-256 of the 128 decimal values joined by commas (no spaces): `{sha(ni)}`\n")
    s.append("### Appendix B -- SINE_Q256: quarter-wave sine table, i = 0..255\n")
    s.append("Normative. `SINE_Q256[i] = round(32767 * sin(pi/2 * (i + 0.5) / 256))` -- MIDPOINT "
             "sampled, 256 entries, no interpolation (`dsp._QUARTER`). The full 1024-entry table is "
             "derived by the symmetry rules in section 6.5. Eight entries per row; the first column is "
             "the index of the first entry in the row.\n")
    s.append("| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |")
    s.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    s.append(_rows(sq, 8))
    s.append(f"\nSHA-256 of the 256 decimal values joined by commas: `{sha(sq)}`  ")
    s.append(f"SHA-256 of the derived 1024-entry full table (`voice_fx.sine_fx` at phases `i << 14`), "
             f"same encoding: `{sha(sf)}`\n")
    s.append("### Appendix C -- TANH16: the ladder's tanh table, i = 0..15\n")
    s.append("Normative. `TANH16[i] = round(tanh(i / 16 * 4.0) * 32767)` -- EDGE sampled over [0, 4), "
             "Q1.15, read with linear interpolation (section 11.3). The interpolation's top word, "
             "used above entry 15, is 32767 and is NOT tanh(4.0) (which would round to 32745).\n")
    s.append("| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |")
    s.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    s.append(_rows(th, 8))
    s.append(f"\nSHA-256 of the 16 decimal values joined by commas: `{sha(th)}`  ")
    s.append(f"SHA-256 of the 17-word ROM image (`TANH16` followed by 32767), which is exactly "
             f"`rtl-sketch/tanh16.hex`: `{sha(thr)}`\n")
    s.append("### Appendix D -- G_ROM128: cutoff (Hz) -> ladder coefficient g, i = 0..128\n")
    s.append("Normative. `G_ROM128[i] = clip(round((1 - exp(-2*pi * (256*i) / 96000)) * 65536), 0, 65535)` "
             "-- EDGE sampled every 256 Hz at the ladder's 2x-oversampled rate, Q0.16, 128 entries plus "
             "entry 128 as the interpolation guard (`voice_fx.make_g_rom`). Entries 0..85 are reachable "
             "through the cutoff clamp of section 10; entries 86..128 are part of the table but never "
             "read. Eight entries per row.\n")
    s.append("| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |")
    s.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    s.append(_rows(gr, 8))
    s.append(f"\nSHA-256 of the 129 decimal values joined by commas: `{sha(gr)}`")
    return "\n".join(s) + "\n"


# ---- write / check ----------------------------------------------------------
def _contract_parts(text: str):
    a, b = text.find(BEGIN), text.find(END)
    if a < 0 or b < 0 or b < a:
        raise SystemExit(f"gen_tables: {CONTRACT} lacks the appendix markers")
    return text[:a + len(BEGIN)] + "\n", text[b:]


def write() -> int:
    os.makedirs(TABLE_DIR, exist_ok=True)
    for name, vals, digits, signed, fn in tables():
        print(f"{name:14} {len(vals):4} entries  sha256 {sha(vals)}")
        if fn:
            with open(os.path.join(TABLE_DIR, fn), "w") as fh:
                fh.write(hex_image(vals, digits, signed))
    text = open(CONTRACT).read()
    head, tail = _contract_parts(text)
    new = head + "\n" + appendix() + "\n" + tail
    if new != text:
        open(CONTRACT, "w").write(new)
        print(f"rewrote the appendix block of {os.path.relpath(CONTRACT, ROOT)}")
    else:
        print("contract appendices already current")
    return 0


def check() -> int:
    bad = 0
    def fail(msg):
        nonlocal bad
        bad += 1
        print("FAIL:", msg)
    text = open(CONTRACT).read() if os.path.exists(CONTRACT) else ""
    if not text:
        fail(f"{CONTRACT} missing")
    for name, vals, digits, signed, fn in tables():
        h = sha(vals)
        if h not in text:
            fail(f"contract does not state the model's {name} hash {h}")
        if fn:
            p = os.path.join(TABLE_DIR, fn)
            have = open(p).read() if os.path.exists(p) else None
            if have != hex_image(vals, digits, signed):
                fail(f"{os.path.relpath(p, ROOT)} differs from the model's {name} (stale or missing)")
    if text:
        head, tail = _contract_parts(text)
        want = head + "\n" + appendix() + "\n" + tail
        if want != text:
            fail("the contract's appendix block differs from what the model generates; "
                 "run gen_tables.py and bump the revision")
    rtl = open(RTL_TANH_HEX).read() if os.path.exists(RTL_TANH_HEX) else None
    if rtl != hex_image(tanh16_rom(), 4, True):
        fail(f"{os.path.relpath(RTL_TANH_HEX, ROOT)} is not the model's 17-word tanh ROM image")
    if bad:
        print(f"gen_tables: {bad} problem(s)")
        return 1
    print("gen_tables: every table image and hash matches the model")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        return check()
    if "--print-appendix" in argv:
        sys.stdout.write(appendix())
        return 0
    return write()


if __name__ == "__main__":
    sys.exit(main())
