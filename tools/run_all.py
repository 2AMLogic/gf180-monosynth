#!/usr/bin/env python3
"""Run every job to completion in ONE turn, then print one combined summary.

WHY THIS EXISTS. An audit of one session found **89 agent wake-ups that
produced nothing** but "still running" or "ending my turn"; one agent alone did
24. Each wake reprocesses the agent's whole context, so for a 200k-token agent
that is 200k tokens spent to say "waiting". It is the largest single waste in
this repository and it is not close.

The cause is always serial jobs -- fire one, wake, fire the next, wake. Four
verifiers become four wakes and roughly a million tokens of nothing.

    BAD   run verify_ladder … wake … run verify_modal … wake … (4 wakes)
    GOOD  tools/run_all.py "verify_ladder" "verify_modal" "verify_voice"

Jobs run in PARALLEL by default -- they are independent simulations. --serial
if they contend. Exit code is the number of failures, so `&& echo ok` works.

WHY PYTHON AND NOT BASH. The first version of this was bash, and it had a bug
that is worth recording because it is the exact failure this repository keeps
making: `eval "cmd; exit 1"` exits the subshell before the wrapper can record
the status, so a genuine FAIL printed as `FAIL(??)` -- **an unknown rendered in
the place where a result belongs.** subprocess.run cannot do that. Everything
else here is Python and is tested; this should be too.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, shlex, subprocess, sys, time


def run_one(cmd: str, timeout: float | None) -> dict:
    t0 = time.time()
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        rc, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        # A timeout is NOT a pass and NOT an ordinary fail -- it is "no verdict".
        # Saying so is the whole point; a timed-out job that prints PASS because
        # nothing checked the status is how a green build hides a hung one.
        got = (e.stdout or b"") + (e.stderr or b"")
        rc, out = None, got.decode("utf8", "replace") if isinstance(got, bytes) else str(got)
    return {"cmd": cmd, "rc": rc, "out": out, "secs": time.time() - t0}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmds", nargs="+", help="shell commands to run")
    ap.add_argument("--serial", action="store_true",
                    help="run in order instead of in parallel")
    ap.add_argument("--timeout", type=float, default=None,
                    help="seconds per job; a timeout reports NO-VERDICT, not FAIL")
    ap.add_argument("--tail", type=int, default=4,
                    help="lines of each job's output to show (default 4)")
    a = ap.parse_args()

    if a.serial:
        results = [run_one(c, a.timeout) for c in a.cmds]
    else:
        with cf.ThreadPoolExecutor(max_workers=len(a.cmds)) as ex:
            results = list(ex.map(lambda c: run_one(c, a.timeout), a.cmds))

    bar = "=" * 78
    print(bar)
    fails = 0
    for r in results:
        if r["rc"] == 0:
            tag = "PASS"
        elif r["rc"] is None:
            tag, fails = "NO-VERDICT", fails + 1      # timed out; not a result
        else:
            tag, fails = f"FAIL({r['rc']})", fails + 1
        print(f"{tag:<11} {r['secs']:6.1f}s  {r['cmd']}")
        for line in [l for l in r["out"].strip().splitlines() if l.strip()][-a.tail:]:
            print(f"            {line}")
    print(bar)
    print(f"{len(results) - fails}/{len(results)} passed"
          + (f"  ({fails} failed)" if fails else ""))
    return fails


if __name__ == "__main__":
    sys.exit(main())
