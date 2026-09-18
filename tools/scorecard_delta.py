#!/usr/bin/env python3
"""What changed between two directories of scorecard results, case by case and
metric by metric.

    tools/scorecard_delta.py BEFORE_DIR AFTER_DIR
    tools/scorecard_delta.py BEFORE_DIR AFTER_DIR --markdown

Written for the re-run after #101/#103, #118, #119 and #108, because "which
failures survive" is a different question from "what does the board say now",
and a board only ever shows the second. **A pass that became a fail is as
important as the reverse**, so both directions are reported and neither is
summarised away.

A metric that changed VALIDITY is called out separately from one whose number
moved: a metric that stopped being measurable and a metric that got worse need
opposite responses, exactly as `run_case.py`'s own outcome codes do."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import scorecard as sb                                              # noqa: E402


def _cases() -> dict:
    import csv
    with open(ROOT / "docs" / "scorecard" / "cases.csv") as fh:
        return {r["case_id"]: r for r in csv.DictReader(fh)}


def _load(d: pathlib.Path) -> dict:
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}


def _worst(row, res):
    r = sb.evaluate(row, res)
    return r["state"], r["worst"], r["why"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()

    rows = _cases()
    before, after = _load(pathlib.Path(a.before)), _load(pathlib.Path(a.after))
    ids = [c for c in rows if c in before or c in after]

    moved, same = [], []
    for cid in ids:
        row = rows[cid]
        sb_, wb, _ = _worst(row, before.get(cid)) if cid in before else ("absent", None, "")
        sa, wa, why = _worst(row, after.get(cid)) if cid in after else ("absent", None, "")
        (moved if sb_ != sa else same).append((cid, sb_, wb, sa, wa, why))

    bar = "|" if a.markdown else ""
    def line(*c):
        if a.markdown:
            print("| " + " | ".join(str(x) for x in c) + " |")
        else:
            print(f"{c[0]:<7}{c[1]:<12}{c[2]:>8}   {c[3]:<12}{c[4]:>8}   {c[5]}")

    print("\nVERDICTS THAT MOVED" if not a.markdown else "\n### Verdicts that moved\n")
    if a.markdown:
        line("case", "was", "worst", "now", "worst", "note")
        line("---", "---", "---:", "---", "---:", "---")
    for cid, s0, w0, s1, w1, why in moved:
        line(cid, s0, f"{w0:.2f}" if w0 is not None else "--",
             s1, f"{w1:.2f}" if w1 is not None else "--", why[:60])
    if not moved:
        print("   (none)")

    print("\nVERDICTS THAT HELD" if not a.markdown else "\n### Verdicts that held\n")
    if a.markdown:
        line("case", "was", "worst", "now", "worst", "note")
        line("---", "---", "---:", "---", "---:", "---")
    for cid, s0, w0, s1, w1, why in same:
        line(cid, s0, f"{w0:.2f}" if w0 is not None else "--",
             s1, f"{w1:.2f}" if w1 is not None else "--", why[:60])

    print("\nEVERY METRIC" if not a.markdown else "\n### Every metric\n")
    if a.markdown:
        print("| case | metric | before | after | moved | tol | note |")
        print("|---|---|---:|---:|---:|---:|---|")
    for cid in ids:
        mb = (before.get(cid) or {}).get("metrics", {})
        ma = (after.get(cid) or {}).get("metrics", {})
        for name in sorted(set(mb) | set(ma)):
            b, c = mb.get(name, {}), ma.get(name, {})
            vb = b.get("error") if b.get("valid") else None
            va = c.get("error") if c.get("valid") else None
            tol = c.get("tolerance") or b.get("tolerance")
            note = ""
            if b.get("valid") and not c.get("valid"):
                note = "NOW INVALID: " + str(c.get("why", ""))[:70]
            elif c.get("valid") and not b.get("valid"):
                note = "now valid (was: " + str(b.get("why", ""))[:50] + ")"
            f = lambda v: f"{v:+.3f}" if isinstance(v, (int, float)) else "--"
            d = (f"{va - vb:+.3f}" if vb is not None and va is not None else "--")
            if a.markdown:
                print(f"| `{cid}` | {name} | {f(vb)} | {f(va)} | {d} | "
                      f"{tol if tol else '--'} | {note} |")
            else:
                print(f"{cid:<6}{name:<26}{f(vb):>10}{f(va):>10}{d:>10}"
                      f"{(tol if tol else 0):>9.2f}  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
