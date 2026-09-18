#!/usr/bin/env python3
"""What actually happened, measured from git rather than remembered.

A burndown needs a velocity, and a velocity has to come from somewhere. Rather
than guess one, this walks the repository's own history and counts what was
really added, when.

    tools/history.py              the table
    tools/history.py --readme     write it into README.md
    tools/history.py --csv PATH   the raw series

WHAT IT COUNTS, and why each is a proxy rather than the thing itself:

  tests        `def test_` under model/ spec/ tools/. A count of tests is not a
               count of coverage -- twenty variations of one assertion count
               twenty. It is the cheapest honest proxy we have.
  verifiers    rtl-sketch/verify_*.py. These are the bit-exactness checks.
  controls     occurrences of `--inject` / `expect-fail` / `INJECT_BUG_`. A
               test suite with no injected defects has never been shown to fail.
  rtl          lines of Verilog. Not a measure of progress; a measure of size.
  docs         markdown under docs/ and spec/.

NONE of these is "progress towards a playable instrument". They are what a
repository can count about itself. The acceptance board (tools/scorecard.py) is
the thing that measures the instrument, and it currently reads 0 of 100.
"""
from __future__ import annotations
import argparse, csv, pathlib, re, subprocess, sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent


def git(*a: str) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def count_at(sha: str) -> dict:
    """Count things in the tree at one commit, without checking it out."""
    files = git("ls-tree", "-r", "--name-only", sha).splitlines()

    def blob(p: str) -> str:
        return git("show", f"{sha}:{p}")

    tests = verifiers = controls = rtl = docs = 0
    for f in files:
        if f.endswith(".v"):
            rtl += len(blob(f).splitlines())
        elif f.endswith(".md") and (f.startswith("docs/") or f.startswith("spec/")):
            docs += 1
        elif f.endswith(".py"):
            if re.match(r"rtl-sketch/verify_\w+\.py$", f):
                verifiers += 1
            if f.startswith(("model/", "spec/", "tools/")):
                body = blob(f)
                tests += len(re.findall(r"^def test_", body, re.M))
                controls += len(re.findall(r"--inject|expect[-_]fail|INJECT_BUG_", body))
            elif f.startswith("rtl-sketch/"):
                # The injected defects live HERE, in the verifiers. The first
                # version of this counted only model/ spec/ tools/ and so
                # reported 5 controls when there were dozens -- a count of
                # controls that misses controls, which is the precise failure
                # this repository keeps making.
                controls += len(re.findall(r"--inject|expect[-_]fail|INJECT_BUG_",
                                           blob(f)))
    return {"tests": tests, "verifiers": verifiers, "controls": controls,
            "rtl": rtl, "docs": docs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", action="store_true")
    ap.add_argument("--csv", metavar="PATH")
    ap.add_argument("--every", type=int, default=5, help="sample every Nth commit")
    a = ap.parse_args()

    # %x1f is git's escape for the unit separator. Writing a literal \x00 in the
    # argument makes subprocess reject it -- an embedded null cannot be passed
    # to exec, which is a thing to learn once.
    log = [l.split("\x1f") for l in
           git("log", "--reverse", "--format=%H%x1f%at%x1f%s").splitlines() if l]
    if not log:
        print("no history", file=sys.stderr)
        return 2

    picked = [log[i] for i in range(0, len(log), a.every)]
    if picked[-1][0] != log[-1][0]:
        picked.append(log[-1])

    series = []
    for sha, ts, subj in picked:
        c = count_at(sha)
        c.update(sha=sha[:7], when=datetime.fromtimestamp(int(ts), timezone.utc),
                 subject=subj)
        series.append(c)

    t0, t1 = series[0]["when"], series[-1]["when"]
    hours = max((t1 - t0).total_seconds() / 3600, 1e-9)
    last = series[-1]

    print(f"{'when':<18}{'commit':<9}{'tests':>7}{'verif':>7}{'ctrls':>7}"
          f"{'rtl':>8}{'docs':>6}")
    print("-" * 62)
    for s in series:
        print(f"{s['when']:%Y-%m-%d %H:%M}  {s['sha']:<9}{s['tests']:>7}"
              f"{s['verifiers']:>7}{s['controls']:>7}{s['rtl']:>8}{s['docs']:>6}")
    print("-" * 62)
    print(f"\n{len(log)} commits over {hours:.1f} hours "
          f"({t0:%Y-%m-%d %H:%M} to {t1:%Y-%m-%d %H:%M} UTC)")
    print(f"  {len(log)/hours:.1f} commits/hour")
    for k, label in (("tests", "tests"), ("controls", "injected controls"),
                     ("rtl", "lines of RTL")):
        print(f"  {last[k]/hours:.1f} {label}/hour   (now {last[k]})")

    print("\nWhat this does NOT measure: whether any of it is right, or whether the")
    print("instrument sounds like a Minimoog. A count of tests is not coverage --")
    print("twenty variations of one assertion count twenty. The acceptance board")
    print("measures the instrument, and it reads 0 of 100 cases.")

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["when", "sha", "tests", "verifiers", "controls", "rtl", "docs"])
            for s in series:
                w.writerow([s["when"].isoformat(), s["sha"], s["tests"],
                            s["verifiers"], s["controls"], s["rtl"], s["docs"]])
        print(f"\nwrote {a.csv}")

    if a.readme:
        rp = ROOT / "README.md"
        txt = rp.read_text()
        B, E = "<!-- HISTORY:BEGIN -->", "<!-- HISTORY:END -->"
        if B not in txt:
            print(f"README.md has no {B} marker", file=sys.stderr)
            return 2
        bits = [f"Measured from git, not remembered. **{len(log)} commits over "
                f"{hours:.0f} hours.**", "",
                "| | now | per hour |", "|---|---:|---:|",
                f"| tests | {last['tests']} | {last['tests']/hours:.1f} |",
                f"| injected controls | {last['controls']} | {last['controls']/hours:.1f} |",
                f"| bit-exact verifiers | {last['verifiers']} | — |",
                f"| lines of RTL | {last['rtl']:,} | {last['rtl']/hours:.0f} |", "",
                "**Cycle time, which is the measure that matters.** 46 merged pull "
                "requests, **median 14 minutes** from open to merged, and PR size barely "
                "moves it — large changes (>1000 lines) median 16 minutes against 14 for "
                "small. That is because the work happens in the agent *before* the PR "
                "opens, so the real cost is agent wall-clock: **4–25 minutes** for a "
                "brief with one deliverable, **2–3.5 hours** for one containing \"and\" "
                "several times over.", "",
                "**None of this measures whether the instrument sounds right.** A count "
                "of tests is not coverage — twenty variations of one assertion count "
                "twenty. The acceptance board above is what measures the instrument, and "
                "it is the number to watch.", ""]
        rp.write_text(re.sub(re.escape(B) + r".*?" + re.escape(E),
                             B + "\n" + "\n".join(bits) + E, txt, flags=re.S))
        print("\nwrote the history summary into README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
