#!/usr/bin/env python3
"""The scorecard, rendered from evidence. Readable in a console, diffable in a PR.

`docs/scorecard/cases.csv` is the source: 100 cases, 80 development and 20
holdout. Results are JSON under `docs/scorecard/results/<case_id>.json`, one
per case, written by whatever produced the measurement.

    tools/scorecard.py                 the whole board
    tools/scorecard.py --family Drums  one family
    tools/scorecard.py --batch "First 32"
    tools/scorecard.py --check         exit 1 if the report is internally wrong

RULES THIS ENFORCES, because each of them is a way a scorecard starts lying:

  * **An invalid measurement has NO distance, not zero distance.** Zero would
    read as a perfect match. It is `no verdict`, and it counts against coverage.
  * **A missing required component invalidates the case** rather than being
    dropped from the maximum -- otherwise the cheapest way to improve a score is
    to stop measuring the inconvenient thing.
  * **Distances are never averaged across units.** Milliseconds, cents and
    decibels do not combine. Each is normalised by ITS OWN tolerance and the
    case reports the worst, which is dimensionless.
  * **Coverage is reported separately and always.** "20 passing, 4 failing,
    6 without verdicts" -- never "83 % passing", which conceals the missing
    verification.
  * **Every result names the engine that produced it.** A float-model
    measurement and an integrated-RTL measurement are not interchangeable, and
    optimising 80 cases against a model the instrument does not reproduce is
    the failure this column exists to prevent.
  * **Every result says what it was measured against.** A commit, a hash of the
    uncommitted tree, the command, and content hashes of the generated inputs.
    Without that a stale result is indistinguishable from a current one -- and
    many worktrees are live on this repository at once, so an earlier green run
    does not cover a later change to a dependency it does not own. A result
    without provenance gets NO VERDICT: it is a number nobody can re-derive.
"""
from __future__ import annotations
import argparse, csv, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "docs" / "scorecard" / "cases.csv"
RESULTS = ROOT / "docs" / "scorecard" / "results"

# Which thing actually produced the audio. Not interchangeable.
ENGINES = ["float-model", "fixed-model", "integrated-rtl", "board-digital", "board-analog"]

NOT_RUN, PASS, FAIL, NO_VERDICT = "not run", "pass", "fail", "no verdict"


def load_cases() -> list[dict]:
    if not CASES.exists():
        print(f"no case file at {CASES}", file=sys.stderr)
        raise SystemExit(2)
    with open(CASES) as fh:
        return list(csv.DictReader(fh))


def load_result(case_id: str) -> dict | None:
    p = RESULTS / f"{case_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:
        return {"_broken": f"{type(e).__name__}: {e}"}


def evaluate(case: dict, res: dict | None) -> dict:
    """Decide one case. Never invents a distance it does not have."""
    required = [m.strip() for m in (case.get("required_measurements") or "").split(";")
                if m.strip()]
    if res is None:
        return {"state": NOT_RUN, "worst": None, "why": "", "engine": ""}
    if "_broken" in res:
        return {"state": NO_VERDICT, "worst": None, "why": res["_broken"], "engine": ""}

    engine = res.get("engine", "")
    if engine and engine not in ENGINES:
        return {"state": NO_VERDICT, "worst": None,
                "why": f"unknown engine {engine!r}", "engine": engine}
    if not engine:
        return {"state": NO_VERDICT, "worst": None,
                "why": "no engine recorded -- which thing produced this audio?",
                "engine": ""}

    # What was this measured against? A result that cannot answer is not
    # evidence; it is a number. It counts against coverage, never towards it.
    prov = res.get("provenance") or {}
    missing_prov = [k for k in ("worktree", "command", "inputs") if not prov.get(k)]
    if missing_prov:
        return {"state": NO_VERDICT, "worst": None, "engine": engine,
                "why": "no provenance: " + ", ".join(missing_prov)}

    metrics = res.get("metrics") or {}

    # A required component that is missing invalidates the case. It is not
    # dropped from the maximum, because that would reward not measuring it.
    missing = [m for m in required if m not in metrics]
    if missing:
        return {"state": NO_VERDICT, "worst": None,
                "why": "missing required: " + ", ".join(missing), "engine": engine}

    worst, worst_name, invalid = None, "", []
    for name, m in metrics.items():
        if not m.get("valid", True):
            invalid.append(name)
            continue                       # NO distance, not zero distance
        tol = m.get("tolerance")
        err = m.get("error")
        if tol in (None, 0) or err is None:
            invalid.append(name)
            continue
        d = abs(err) / abs(tol)            # dimensionless; units never mixed
        if worst is None or d > worst:
            worst, worst_name = d, name
    if invalid:
        return {"state": NO_VERDICT, "worst": None,
                "why": "invalid: " + ", ".join(invalid), "engine": engine}
    if worst is None:
        return {"state": NO_VERDICT, "worst": None, "why": "no valid metrics",
                "engine": engine}
    return {"state": PASS if worst <= 1.0 else FAIL, "worst": worst,
            "why": "" if worst <= 1.0 else f"worst: {worst_name}", "engine": engine}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family"); ap.add_argument("--batch"); ap.add_argument("--split")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the report is internally inconsistent")
    ap.add_argument("--verbose", action="store_true", help="one line per case")
    ap.add_argument("--readme", action="store_true",
                    help="write the summary into README.md between its BOARD markers")
    ap.add_argument("--markdown", metavar="PATH", nargs="?", const="docs/scorecard/BOARD.md",
                    help="write the full board as markdown (default docs/scorecard/BOARD.md)")
    a = ap.parse_args()

    cases = load_cases()
    for key, val in (("family", a.family), ("batch", a.batch), ("split", a.split)):
        if val:
            cases = [c for c in cases if c.get(key) == val]

    rows = [(c, evaluate(c, load_result(c["case_id"]))) for c in cases]

    if a.verbose:
        print(f"{'case':<7}{'family':<10}{'split':<13}{'engine':<16}{'state':<11}worst  why")
        for c, r in rows:
            w = f"{r['worst']:.2f}" if r["worst"] is not None else "  --"
            print(f"{c['case_id']:<7}{c['family']:<10}{c['split']:<13}"
                  f"{r['engine']:<16}{r['state']:<11}{w:>5}  {r['why'][:44]}")
        print()

    def tally(sub):
        n = len(sub)
        st = {s: sum(1 for _, r in sub if r["state"] == s)
              for s in (PASS, FAIL, NO_VERDICT, NOT_RUN)}
        valid = st[PASS] + st[FAIL]
        return n, st, valid

    print("=" * 74)
    print(f"{'':<12}{'cases':>6}{'valid':>7}{'pass':>6}{'fail':>6}"
          f"{'no verdict':>12}{'not run':>9}")
    print("-" * 74)
    for fam in ["Drums", "Mono", "Filters", "Ensemble"]:
        sub = [(c, r) for c, r in rows if c["family"] == fam]
        if not sub:
            continue
        n, st, valid = tally(sub)
        print(f"{fam:<12}{n:>6}{valid:>7}{st[PASS]:>6}{st[FAIL]:>6}"
              f"{st[NO_VERDICT]:>12}{st[NOT_RUN]:>9}")
    n, st, valid = tally(rows)
    print("-" * 74)
    print(f"{'TOTAL':<12}{n:>6}{valid:>7}{st[PASS]:>6}{st[FAIL]:>6}"
          f"{st[NO_VERDICT]:>12}{st[NOT_RUN]:>9}")
    print("=" * 74)

    # Coverage first, and never as a single percentage.
    print(f"\nCoverage: {valid} of {n} cases produced a valid measurement.")
    print(f"Agreement: {st[PASS]} of {valid} valid cases inside all tolerances."
          if valid else "Agreement: no valid cases yet.")
    if st[NO_VERDICT] or st[NOT_RUN]:
        print(f"Missing verification: {st[NO_VERDICT]} no-verdict, "
              f"{st[NOT_RUN]} not run. These are NOT evidence the instrument is "
              f"wrong -- they are evidence we have not checked.")

    engines = sorted({r["engine"] for _, r in rows if r["engine"]})
    if engines:
        print(f"\nEngines represented: {', '.join(engines)}")
        if "integrated-rtl" not in engines:
            print("  NOTE: no case has been measured on the integrated RTL. Results "
                  "describe a model, not the instrument.")

    if a.readme:
        import re
        rp = ROOT / "README.md"
        txt = rp.read_text()
        B, E = "<!-- BOARD:BEGIN -->", "<!-- BOARD:END -->"
        if B not in txt:
            print(f"README.md has no {B} marker", file=sys.stderr)
            return 2
        bits = [f"**{valid} of {n} acceptance cases have a valid measurement.** "
                f"{st[PASS]} pass · {st[FAIL]} fail · {st[NO_VERDICT]} no verdict · "
                f"{st[NOT_RUN]} not run.", ""]
        if "integrated-rtl" not in engines:
            bits += ["> **No case has been measured on the integrated RTL yet**, so these "
                     "describe a model rather than the instrument.", ""]
        bits += ["| | cases | valid | pass | fail | no verdict | not run |",
                 "|---|---:|---:|---:|---:|---:|---:|"]
        for fam in ["Drums", "Mono", "Filters", "Ensemble"]:
            sub = [(c, r) for c, r in rows if c["family"] == fam]
            if not sub:
                continue
            fn, fst, fv = tally(sub)
            bits.append(f"| {fam} | {fn} | {fv} | {fst[PASS]} | {fst[FAIL]} | "
                        f"{fst[NO_VERDICT]} | {fst[NOT_RUN]} |")
        bits += ["", "Every case is in [`docs/scorecard/BOARD.md`](docs/scorecard/BOARD.md). "
                 "**Coverage is reported separately from agreement on purpose** — a case "
                 "without a verdict is missing verification, not evidence the instrument "
                 "is wrong, and it must not be able to flatter a percentage.", ""]
        new = re.sub(re.escape(B) + r".*?" + re.escape(E), B + "\n" + "\n".join(bits) + E,
                     txt, flags=re.S)
        rp.write_text(new)
        print(f"wrote the board summary into README.md")

    if a.markdown:
        out = pathlib.Path(a.markdown)
        if not out.is_absolute():
            out = ROOT / out
        L = ["# The board", "",
             "Generated by `tools/scorecard.py --markdown` and regenerated on every",
             "push. **Do not edit by hand** -- it is a view of",
             "`docs/scorecard/results/`, not a document.", "",
             f"**{valid} of {n} cases have a valid measurement.** "
             f"{st[PASS]} pass, {st[FAIL]} fail, {st[NO_VERDICT]} no verdict, "
             f"{st[NOT_RUN]} not run.", ""]
        if "integrated-rtl" not in engines:
            L += ["> **No case has been measured on the integrated RTL.** "
                  "Everything below describes a model, not the instrument.", ""]
        L += ["| | cases | valid | pass | fail | no verdict | not run |",
              "|---|---:|---:|---:|---:|---:|---:|"]
        for fam in ["Drums", "Mono", "Filters", "Ensemble"]:
            sub = [(c, r) for c, r in rows if c["family"] == fam]
            if not sub:
                continue
            fn, fst, fv = tally(sub)
            L.append(f"| **{fam}** | {fn} | {fv} | {fst[PASS]} | {fst[FAIL]} | "
                     f"{fst[NO_VERDICT]} | {fst[NOT_RUN]} |")
        L += [f"| **total** | {n} | {valid} | {st[PASS]} | {st[FAIL]} | "
              f"{st[NO_VERDICT]} | {st[NOT_RUN]} |", "",
              "## Every case", "",
              "`worst` is the largest metric error divided by its own tolerance, so it is",
              "dimensionless and passes at or below 1. A blank means no distance exists --",
              "an invalid or missing measurement has **no** distance, never zero.", "",
              "| case | family | split | subject | reference | engine | state | worst | note |",
              "|---|---|---|---|---|---|---|---:|---|"]
        icon = {PASS: "✅ pass", FAIL: "❌ fail", NO_VERDICT: "⚠️ no verdict",
                NOT_RUN: "⬜ not run"}
        for c, r in rows:
            w = f"{r['worst']:.2f}" if r["worst"] is not None else ""
            L.append(f"| `{c['case_id']}` | {c['family']} | {c['split']} | "
                     f"{c['subject']} | {c['reference_target']} | {r['engine'] or '—'} | "
                     f"{icon[r['state']]} | {w} | {r['why'][:60]} |")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(L) + "\n")
        print(f"\nwrote {out.relative_to(ROOT)}")

    if a.check:
        bad = [c["case_id"] for c, r in rows
               if r["state"] in (PASS, FAIL) and r["worst"] is None]
        for b in bad:
            print(f"inconsistent: {b} has a verdict but no distance", file=sys.stderr)
        # A verdict whose record does not say what produced it is the other way
        # a board goes quietly wrong, so it is checked here too.
        for c, r in rows:
            if r["state"] not in (PASS, FAIL):
                continue
            res = load_result(c["case_id"]) or {}
            code = (res.get("provenance") or {}).get("outcome_code")
            want = 0 if r["state"] == PASS else 1
            if code is not None and code != want:
                print(f"inconsistent: {c['case_id']} is {r['state']} but its record "
                      f"carries outcome_code {code}", file=sys.stderr)
                bad.append(c["case_id"])
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
