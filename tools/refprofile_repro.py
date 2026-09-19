#!/usr/bin/env python3
"""Is the frozen reference actually frozen? Render it N times, independently,
and compare the bytes.

    tools/refprofile_repro.py                 4 renders, compare, report
    tools/refprofile_repro.py --runs 2        fewer, while iterating
    tools/refprofile_repro.py --accept        ...and install the result as
                                              refprofile/profile.json

WHY THIS EXISTS
---------------
`refprofile/profile.json` is a list of sha256es. A hash says "these are the
bytes that were frozen"; it says NOTHING about whether the rig that made them
would make them again. Those are different claims and only the second one makes
the profile a reference rather than a recording:

  * if a re-render reproduces the hashes, the profile is a REPRODUCIBLE freeze.
    A later mismatch is then evidence that something moved -- the plugin, the
    host, the rig -- and the diff says what.
  * if a re-render does NOT reproduce them, the profile is one take of a
    non-deterministic process. Every hash in it is still honest about what was
    frozen, and the freeze is no longer a control: a mismatch downstream would
    mean nothing, because a match was never guaranteed.

The repository's own rule (CLAUDE.md, docs/failure-modes.md): assert the
apparatus's preconditions at the point of use and REFUSE rather than report.
A clip that does not reproduce is not frozen -- it is a temporary -- and this
tool refuses to install it.

WHAT "INDEPENDENT" MEANS HERE, EXACTLY
--------------------------------------
Each render is a separate `tools/refprofile.py --render` PROCESS. Not a loop
inside one process, because that would share the plugin instance, its allocator
state and dawdreamer's own globals -- which is most of what a determinism check
is trying to vary. Each run therefore reloads the VST3 bundle, re-runs the
rig's qualification, and re-renders every clip from scratch.

It does not vary: the machine, the OS, the plugin build, the sample rate or the
block size. Those are pinned by the rig and recorded in the profile, and a
claim about them needs a second machine, not a second run.

THREE OUTCOMES, the same three `tools/refprofile.py` uses
--------------------------------------------------------
    exit 0  OK       every run agreed with EVERY OTHER RUN *and* with the
                     committed profile
    exit 1  FAIL     either two runs of the same rig disagreed about a clip
                     (not reproducible), or the runs agreed with each other and
                     DIFFERED FROM THE COMMITTED PROFILE (drift). These are two
                     different questions and they used to share one verdict:
                     exit 0 meant only "the rig agrees with itself", so a host
                     reproducibly rendering something else passed.
    exit 2  REFUSED  a render could not be attempted at all (no dawdreamer, no
                     plugin bundle) -- nothing was measured, so nothing is said
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RENDERER = ROOT / "tools" / "refprofile.py"
PROFILE_JSON = ROOT / "refprofile" / "profile.json"

OK, FAIL, REFUSED = 0, 1, 2

#: What has to be identical between two renders for a clip to count as frozen.
#: The hash is the load-bearing one; the other three are carried so a
#: disagreement says WHERE it is rather than only that there is one.
IDENTITY = ("sha256", "bytes", "frames", "peak")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_once(out: pathlib.Path, log: pathlib.Path) -> tuple[int, dict]:
    """One independent render. Returns (exit code, profile dict or {})."""
    cmd = [sys.executable, str(RENDERER), "--render", "--out", str(out)]
    with log.open("w") as fh:
        r = subprocess.run(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode != OK or not out.exists():
        return r.returncode or FAIL, {}
    return OK, json.loads(out.read_text(encoding="utf-8"))


def identity_of(prof: dict) -> dict:
    return {cid: {k: c.get(k) for k in IDENTITY} for cid, c in prof.get("clips", {}).items()}


def compare(runs: list[dict]) -> tuple[dict, list[str]]:
    """Clip by clip across every run. Returns (verdict per clip, lines)."""
    ids = sorted({cid for r in runs for cid in r})
    verdict, lines = {}, []
    for cid in ids:
        seen = [r.get(cid) for r in runs]
        if any(s is None for s in seen):
            verdict[cid] = "MISSING"
            lines.append(f"MISSING  {cid}: rendered by "
                         f"{sum(s is not None for s in seen)}/{len(seen)} runs")
            continue
        first = seen[0]
        differ = [k for k in IDENTITY if any(s[k] != first[k] for s in seen[1:])]
        if differ:
            verdict[cid] = "MOVED"
            lines.append(f"MOVED    {cid}: " + "; ".join(
                f"{k} " + " vs ".join(str(s[k])[:20] for s in seen) for k in differ))
        else:
            verdict[cid] = "IDENTICAL"
            lines.append(f"ok       {cid}  {first['sha256'][:12]}  "
                         f"{first['frames']} frames  {first['bytes']} bytes")
    return verdict, lines


def against_committed(runs0: dict, committed: dict) -> tuple[dict, list[str]]:
    """The other question, and it is NOT the same one: does this host reproduce
    the hashes that are already committed? A host that renders the same thing
    four times and a DIFFERENT thing from the operator who froze the profile
    has a reproducible rig and a moved reference."""
    old = identity_of(committed)
    verdict, lines = {}, []
    for cid in sorted(set(runs0) | set(old)):
        if cid not in old:
            verdict[cid] = "NEW"
            lines.append(f"NEW      {cid}  {runs0[cid]['sha256'][:12]}")
        elif cid not in runs0:
            verdict[cid] = "DROPPED"
            lines.append(f"DROPPED  {cid}: in the committed profile, not rendered now")
        elif runs0[cid]["sha256"] == old[cid]["sha256"]:
            verdict[cid] = "REPRODUCED"
            lines.append(f"same     {cid}  {old[cid]['sha256'][:12]}")
        else:
            verdict[cid] = "CHANGED"
            lines.append(f"CHANGED  {cid}: committed {old[cid]['sha256'][:12]} "
                         f"-> rendered {runs0[cid]['sha256'][:12]}")
    return verdict, lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=4,
                    help="how many independent renders (default 4)")
    ap.add_argument("--accept", action="store_true",
                    help="install the last run as refprofile/profile.json, but "
                         "ONLY if every run agreed")
    ap.add_argument("--allow-drift", action="store_true",
                    help="accept clips that differ from the committed profile; records that it did")
    ap.add_argument("--workdir", default=None,
                    help="where the per-run profiles and logs go (default: a temp dir)")
    ap.add_argument("--report", default=None,
                    help="write the machine-readable verdict here")
    a = ap.parse_args(argv)

    if a.runs < 2:
        print("REFUSED  one render cannot disagree with itself; --runs must be >= 2")
        return REFUSED

    work = pathlib.Path(a.workdir) if a.workdir else pathlib.Path(tempfile.mkdtemp(
        prefix="refprofile-repro-"))
    work.mkdir(parents=True, exist_ok=True)
    committed = json.loads(PROFILE_JSON.read_text(encoding="utf-8")) if PROFILE_JSON.exists() else {}

    print(f"workdir   {work}")
    print(f"renderer  {RENDERER.relative_to(ROOT)}  x{a.runs} independent processes")
    profiles = []
    for i in range(a.runs):
        out, log = work / f"profile.run{i + 1}.json", work / f"render.run{i + 1}.log"
        t0 = datetime.datetime.now()
        code, prof = render_once(out, log)
        dt = (datetime.datetime.now() - t0).total_seconds()
        if code != OK:
            tail = log.read_text(errors="replace").strip().splitlines()[-6:]
            print(f"\nREFUSED  render {i + 1}/{a.runs} did not complete (exit {code}). "
                  f"Nothing is claimed about reproducibility.")
            for ln in tail:
                print(f"         {ln}")
            return REFUSED
        print(f"render {i + 1}/{a.runs}  {len(prof.get('clips', {}))} clips  {dt:.1f} s  "
              f"-> {out.name}")
        profiles.append(prof)

    runs = [identity_of(p) for p in profiles]
    verdict, lines = compare(runs)
    print("\n--- run vs run " + "-" * 60)
    for ln in lines:
        print(ln)
    moved = sorted(c for c, v in verdict.items() if v != "IDENTICAL")
    n = len(verdict)
    print(f"{n - len(moved)}/{n} clips bit-identical across {a.runs} independent renders")

    old_v, old_lines = against_committed(runs[0], committed)
    print("\n--- rendered vs the committed profile " + "-" * 37)
    for ln in old_lines:
        print(ln)
    changed = sorted(c for c, v in old_v.items() if v == "CHANGED")
    new = sorted(c for c, v in old_v.items() if v == "NEW")
    print(f"{sum(1 for v in old_v.values() if v == 'REPRODUCED')} reproduced, "
          f"{len(changed)} changed, {len(new)} new, "
          f"{sum(1 for v in old_v.values() if v == 'DROPPED')} dropped")

    report = {
        "what": "independent re-renders of the frozen reference profile, compared "
                "byte for byte. A clip that does not reproduce is not frozen.",
        "at": _now(),
        "runs": a.runs,
        "independent": "each run is a separate `tools/refprofile.py --render` process: "
                       "the VST3 bundle is reloaded and the rig re-qualified every time. "
                       "The machine, OS, plugin build, sample rate and block size are "
                       "NOT varied and no claim is made about them.",
        "workdir": str(work),
        "clips": n,
        "bit_identical": n - len(moved),
        "not_reproducible": moved,
        "vs_committed": {"reproduced": sorted(c for c, v in old_v.items() if v == "REPRODUCED"),
                         "changed": changed, "new": new,
                         "dropped": sorted(c for c, v in old_v.items() if v == "DROPPED")},
        "built": profiles[-1].get("built", {}),
    }
    if a.report:
        pathlib.Path(a.report).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {a.report}")

    if moved:
        print(f"\nFAIL     {len(moved)} clip(s) did not reproduce. They are NOT frozen "
              f"and must not be installed: " + ", ".join(moved))
        return FAIL

    # REPRODUCIBILITY AND CONTINUITY ARE TWO QUESTIONS AND USED TO SHARE ONE
    # VERDICT. "every run agreed, clip for clip" says the rig renders the same
    # thing twice; it says NOTHING about whether that thing is what the
    # committed profile describes. A host that reproducibly renders something
    # DIFFERENT from the frozen reference exited 0, because the drift was
    # printed above and never reached the exit code.
    #
    # Drift is a mismatch, so it is exit 1 under this repo's convention
    # (0 match / 1 mismatch / 2 did not run). `--allow-drift` is the deliberate
    # override for the case where the profile is MEANT to move -- and it says so
    # in the output, the way run_case.py's --allow-stale records itself.
    drifted = changed + sorted(c for c, v in old_v.items() if v == "DROPPED")
    if drifted and not a.allow_drift:
        print(f"\nFAIL     the runs agree with EACH OTHER but not with the committed "
              f"profile: {len(drifted)} clip(s) changed or dropped -- "
              + ", ".join(drifted))
        print("         reproducible is not the same as unchanged. Pass --allow-drift "
              "if the reference is meant to move, and say why in the commit.")
        return FAIL
    if drifted and a.allow_drift:
        print(f"\nNOTE     --allow-drift: accepting {len(drifted)} clip(s) that differ "
              f"from the committed profile. This IS a reference change.")
    if a.accept:
        PROFILE_JSON.write_text((work / f"profile.run{a.runs}.json").read_text(encoding="utf-8"),
                                encoding="utf-8")
        print(f"\ninstalled run {a.runs} as {PROFILE_JSON.relative_to(ROOT)}. "
              f"Review the diff: that file IS the reference.")
    else:
        print("\n(not installed -- pass --accept to write refprofile/profile.json)")
    return OK


if __name__ == "__main__":
    sys.exit(main())
