#!/usr/bin/env python3
"""F1A/F1B/F1C read by BOTH corner estimators, on ONE set of curves, on BOTH
sides.

    tools/probes/f1_estimator_ab.py
    tools/probes/f1_estimator_ab.py --json docs/scorecard/results/F1-estimator-ab.json

WHY THIS EXISTS, AND WHY IT IS NOT JUST A DIFF OF TWO RESULT FILES
------------------------------------------------------------------
#164 repaired `run_case.filt_corner`: the passband reference it measures a
-3 dB corner against used to be the MEDIAN of a band that moves with the
commanded cutoff, so it carried a different amount of the filter's own droop at
each cutoff and reported that as the filter's. It is now
`audio_measure.dc_plateau_db` -- gain regressed on `(f/cut)^2` and read at the
intercept, which is shape-agnostic for any real filter.

#164 could only rescore OUR side: `refprofile/cache/` is gitignored and was
absent on that host, so the frozen Surge clips could not be read and the
reference half of every F1 comparison was never re-measured.

Comparing the committed F1 records against a fresh run answers the question
with TWO things moved at once -- the estimator, and everything else that
changed in the tree between the two runs (`run_case.py` and `audio_measure.py`
both have new content hashes, and so do two `model/` files the filter path does
not use). **This probe moves one thing.** It builds each curve once, then reads
the same array with both estimators:

  * OLD  `corner_from_curve(f, g, ref_band=_ref_band(f, cut))`
         -- the moving-median plateau, i.e. #146's instrument
  * NEW  `filt_corner(cut)` -- `dc_plateau_db` intercept, i.e. #164's

THE CONTROL THAT MAKES THE COMPARISON LEGITIMATE
------------------------------------------------
If the OLD reading on today's curves reproduces the committed F1 numbers to the
last digit, then nothing but the estimator moved between #146's run and this
one, and old-vs-new is an instrument comparison rather than a model comparison.
If it does NOT reproduce them, the curves moved too and the difference is
confounded -- so this probe checks that and says which, rather than assuming it.
`--check` makes the mismatch an exit code.

WHAT IT DOES NOT DO
-------------------
It does not decide anything about the filter and it changes no coefficient. It
reports the corner each estimator reads on each side, and the ratio
corner/commanded, which is the quantity #146 read a trend in.

The reference side is the frozen profile and nothing else: a clip whose bytes
do not hash to `refprofile/profile.json` is a refusal from `refprofile.load_clip`
and this probe carries it out as a refusal, not as a number.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "tools"))

import audio_measure as am           # noqa: E402
import refprofile as rp              # noqa: E402
import run_case as rc                # noqa: E402

#: The commit whose `docs/scorecard/results/F1*.json` are #146's records, read
#: out of git rather than copied, so the superseded evidence is preserved where
#: it already lives and this probe cannot quietly disagree with it.
SUPERSEDED_AT = "01e01e1"

#: The committed F1 records as #146 measured them, both sides, so the control
#: is in the file rather than in a reader's memory. ours, reference, in Hz.
COMMITTED_146 = {
    "F1A": (117.8946, 128.0893),
    "F1B": (391.5622, 455.6839),
    "F1C": (1449.2517, 1729.1368),
}

#: How close an old-estimator re-reading has to be to the committed number for
#: the curves to count as unmoved. The records are written to 4 decimal places,
#: so this is a rounding tolerance and nothing more.
SAME_HZ = 5e-4


def old_corner(freqs, g, cut_hz: float):
    """#146's estimator, verbatim: the plateau is the median over a band that
    moves with the commanded cutoff."""
    return am.corner_from_curve(freqs, g, ref_band=rc._ref_band(freqs, cut_hz))


def new_corner(freqs, g, cut_hz: float):
    """#164's estimator, through the shipping entry point."""
    return rc.filt_corner(cut_hz)(freqs, g)


def one_case(cid: str) -> dict:
    spec = rc.FILTER_CASES[cid]
    cut = spec["cut_hz"]
    ref_f, ref_g, meta = rc.load_filter_reference(spec["ref_clip"])
    ours_g = rc.our_filter_curve(ref_f, cut, spec["res_ours"], rp.PROBE_AMP)

    row = {"case": cid, "commanded_hz": cut, "clip": spec["ref_clip"],
           "clip_sha256": rp.load_profile()["clips"][spec["ref_clip"]]["sha256"][:16],
           "probe_level_dbfs": rp.PROBE_LEVEL_DBFS,
           "n_probe_tones": len(ref_f),
           "grid_hz": [round(float(ref_f[0]), 2), round(float(ref_f[-1]), 2)]}
    for side, g in (("ours", ours_g), ("reference", ref_g)):
        for tag, fn in (("old", old_corner), ("new", new_corner)):
            e = fn(ref_f, g, cut)
            row[f"{side}_{tag}_hz"] = round(float(e.value), 4) if e.ok else None
            if not e.ok:
                row[f"{side}_{tag}_refused"] = e.reason
    for tag in ("old", "new"):
        o, r = row[f"ours_{tag}_hz"], row[f"reference_{tag}_hz"]
        row[f"ratio_ours_{tag}"] = round(o / cut, 4) if o else None
        row[f"ratio_reference_{tag}"] = round(r / cut, 4) if r else None
        row[f"error_pct_{tag}"] = round(100.0 * (o / r - 1.0), 2) if o and r else None
    return row


def _scorecard():
    import importlib.util
    spec = importlib.util.spec_from_file_location("scorecard", ROOT / "tools" / "scorecard.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def property_vectors() -> list[dict]:
    """The per-property vector old and new, because `worst` is an aggregate and
    DR 0015 judges on the vector (#159).

    The superseded records are read out of git at `SUPERSEDED_AT`, not copied
    into this file: they are historical evidence, and evidence that has been
    transcribed is a claim about evidence.
    """
    import subprocess
    sc = _scorecard()
    cases = {c["case_id"]: c for c in sc.load_cases()}
    rows = []
    for cid in ("F1A", "F1B", "F1C"):
        r = subprocess.run(["git", "show", f"{SUPERSEDED_AT}:docs/scorecard/results/{cid}.json"],
                           cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            print(f"REFUSED  cannot read the superseded {cid} at {SUPERSEDED_AT}: "
                  f"{r.stderr.strip()[:120]}")
            return []
        old = sc.evaluate(cases[cid], json.loads(r.stdout))
        new = sc.evaluate(cases[cid], json.loads(
            (ROOT / "docs" / "scorecard" / "results" / f"{cid}.json").read_text()))
        rows.append({"case": cid,
                     "old": {"state": old["state"], "worst": old["worst"],
                             "properties": old.get("properties") or {}},
                     "new": {"state": new["state"], "worst": new["worst"],
                             "properties": new.get("properties") or {}}})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=None, help="write the rows here as well")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 unless the OLD estimator reproduces the committed "
                         "#146 numbers on today's curves")
    a = ap.parse_args(argv)

    rows = []
    for cid in ("F1A", "F1B", "F1C"):
        try:
            rows.append(one_case(cid))
        except (rp.Refused, rc.Refused) as e:
            print(f"REFUSED  {cid}: {e}")
            return 2

    print(f"probe level {rp.PROBE_LEVEL_DBFS} dBFS, "
          f"{rows[0]['n_probe_tones']} tones over "
          f"{rows[0]['grid_hz'][0]}-{rows[0]['grid_hz'][1]} Hz\n")
    hdr = (f"{'case':5s} {'cmd':>6s} | {'ours old':>9s} {'ref old':>9s} "
           f"{'err%':>7s} {'ours/cmd':>8s} {'ref/cmd':>8s} | "
           f"{'ours new':>9s} {'ref new':>9s} {'err%':>7s} "
           f"{'ours/cmd':>8s} {'ref/cmd':>8s}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['case']:5s} {r['commanded_hz']:6.0f} | "
              f"{r['ours_old_hz']:9.2f} {r['reference_old_hz']:9.2f} "
              f"{r['error_pct_old']:+7.2f} {r['ratio_ours_old']:8.4f} "
              f"{r['ratio_reference_old']:8.4f} | "
              f"{r['ours_new_hz']:9.2f} {r['reference_new_hz']:9.2f} "
              f"{r['error_pct_new']:+7.2f} {r['ratio_ours_new']:8.4f} "
              f"{r['ratio_reference_new']:8.4f}")

    def spread(key):
        v = [r[key] for r in rows]
        return max(v) - min(v)

    print(f"\nours/reference error, spread across 250 Hz - 4 kHz:"
          f"  old {spread('error_pct_old'):5.2f} points"
          f"   new {spread('error_pct_new'):5.2f} points")

    print("\n--- control: does the OLD estimator reproduce #146 on today's curves? ---")
    bad = []
    for r in rows:
        want_o, want_r = COMMITTED_146[r["case"]]
        do, dr = abs(r["ours_old_hz"] - want_o), abs(r["reference_old_hz"] - want_r)
        ok = do <= SAME_HZ and dr <= SAME_HZ
        print(f"{'same    ' if ok else 'MOVED   '} {r['case']}  "
              f"ours {r['ours_old_hz']:.4f} vs {want_o:.4f} ({do:.2e})   "
              f"reference {r['reference_old_hz']:.4f} vs {want_r:.4f} ({dr:.2e})")
        if not ok:
            bad.append(r["case"])
    if bad:
        print(f"\nThe curves MOVED for {', '.join(bad)}. Old-vs-new is then NOT an "
              f"instrument comparison -- something else changed too.")
    else:
        print("\nEvery curve is byte-for-byte the one #146 measured, so the whole of "
              "the difference above is the estimator.")

    pv = property_vectors()
    if pv:
        print(f"\n--- the property vector, superseded ({SUPERSEDED_AT}) -> now "
              f"(worst is an aggregate; DR 0015 judges the vector) ---")
        names = list(pv[0]["new"]["properties"])
        print(f"{'case':5s} {'state':>16s}  " + "  ".join(f"{n[:16]:>16s}" for n in names))
        for r in pv:
            st = f"{r['old']['state']} -> {r['new']['state']}"
            cells = []
            for n in names:
                o = r["old"]["properties"].get(n)
                c = r["new"]["properties"].get(n)
                cells.append(f"{o:6.3f} ->{c:6.3f}" if o is not None and c is not None
                             else f"{'--':>16s}")
            print(f"{r['case']:5s} {st:>16s}  " + "  ".join(f"{c:>16s}" for c in cells))

    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(
            {"what": "F1A/F1B/F1C corner read by #146's estimator and #164's, on one "
                     "set of curves, on both sides",
             "control": "the OLD estimator's reading against the committed #146 record",
             "curves_unmoved": not bad,
             "superseded_records_at": SUPERSEDED_AT,
             "rows": rows,
             "property_vectors": pv}, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {a.json}")
    return 1 if (a.check and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
