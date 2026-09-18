#!/usr/bin/env python3
"""Check the checking machinery. Workflow files are the one artifact nothing checks.

WHY. Four CI defects landed in one session, every one of them inside a workflow
file, every one from the same cause: the YAML was committed without ever being
executed.

  dag.yml       invalid YAML -- GitHub does not fail a PR for an unparseable
                workflow, it silently does not register it
  nightly.yml   scheduled only, so it had never run at all
  rungs.yml     a step written against `origin/main`, which the runner does
                not fetch
  nightly.yml   a step written against `sound_report.py --all --out`, an
                interface that did not exist

**An invalid workflow is indistinguishable from a workflow that passed.** That
is the same failure as a check that cannot run looking like a check that
passes -- rebuilt one level up, in the machinery that does the checking.

This parses every workflow, and asserts the properties that silently break one.
"""
from __future__ import annotations
import pathlib, re, sys

try:
    import yaml
except ImportError:
    print("pyyaml not installed; cannot check workflows", file=sys.stderr)
    raise SystemExit(2)          # no evidence, not "no problem"

WF = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"


def main() -> int:
    files = sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))
    if not files:
        print("no workflow files found", file=sys.stderr)
        return 2
    bad: list[str] = []

    for f in files:
        text = f.read_text()
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:
            bad.append(f"{f.name}: INVALID YAML -- {str(e).splitlines()[0]}")
            continue
        if not isinstance(doc, dict):
            bad.append(f"{f.name}: does not parse to a mapping")
            continue

        # `on:` is parsed by YAML 1.1 as the boolean True. Accept either.
        triggers = doc.get("on", doc.get(True))
        if triggers is None:
            bad.append(f"{f.name}: no triggers")
        elif isinstance(triggers, dict):
            # A workflow that ONLY runs on a schedule has never run when you
            # commit it, so it cannot have been tested. Require a manual
            # trigger so it can be exercised on demand.
            if set(triggers) <= {"schedule"}:
                bad.append(f"{f.name}: schedule-only -- add workflow_dispatch "
                           f"so it can be run before it is trusted")

        for jname, job in (doc.get("jobs") or {}).items():
            steps = (job or {}).get("steps") or []
            run_text = "\n".join(s.get("run", "") for s in steps if isinstance(s, dict))
            uses = [s.get("uses", "") for s in steps if isinstance(s, dict)]
            checkout = any(u.startswith("actions/checkout") for u in uses)

            # A step comparing against origin/<branch> needs the remote ref,
            # which a default shallow single-branch checkout does not provide.
            if re.search(r"\borigin/\w+", run_text):
                co = next((s for s in steps if isinstance(s, dict)
                           and s.get("uses", "").startswith("actions/checkout")), None)
                depth = ((co or {}).get("with") or {}).get("fetch-depth")
                if str(depth) != "0" and "git fetch" not in run_text:
                    bad.append(f"{f.name}:{jname}: uses origin/<ref> but the checkout "
                               f"is shallow and nothing fetches it")
            if run_text and not checkout:
                bad.append(f"{f.name}:{jname}: runs commands without actions/checkout")

    for b in bad:
        print(f"  {b}", file=sys.stderr)
    if bad:
        print(f"\n{len(bad)} workflow problem(s). These do not surface as a failed "
              f"build -- an unregistered workflow simply never runs.", file=sys.stderr)
        return 1
    print(f"{len(files)} workflow(s) parse and declare a usable trigger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
