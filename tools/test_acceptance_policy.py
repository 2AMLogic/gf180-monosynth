"""DR 0015's acceptance rule, as tests.

These exist because the DR's FIRST DRAFT made `worst` authoritative -- and
`worst` is an aggregate, so it hides exactly what the DR rejects aggregates for.
External review produced the counterexample in
`test_improving_worst_cannot_hide_a_regression` below, and it is the reason this
file exists.

Each test is a rule someone can otherwise re-introduce by accident.
"""
from __future__ import annotations
import json, pathlib, sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scorecard as sc                                              # noqa: E402

# THE SHAPE run_case.py ACTUALLY WRITES. The first version of this fixture was
# a hybrid nothing in the system produces -- `rubric_version` does not exist,
# `analysis_run` is top level, and `inputs` is keyed by PATH. Twelve tests
# passed against it while the guard was inert on every real record.
BASIS = {"engine": "fixed-model",
         "analysis_run": "run_case@aaaa + audio_measure@bbbb at 2026-01-01T00:00:00Z",
         "provenance": {"command": "tools/run_case.py X",
                        "worktree": {"commit": "abc", "dirty": False},
                        "config": {"refs": "/refs"},
                        "inputs": {"model/audio_measure.py": "sha256:AAAA",
                                   "tools/run_case.py": "sha256:BBBB",
                                   "model/drums_fx.py": "sha256:DEVICE"}}}


def result(props: dict, state=None, **over):
    worst = max(props.values()) if props else None
    r = dict(BASIS)
    r.update({"state": state or (sc.PASS if (worst or 0) <= 1.0 else sc.FAIL),
              "worst": worst, "properties": props, "why": "", **over})
    return r


# --- the counterexample that forced the DR to be rewritten -------------------

def test_improving_worst_cannot_hide_a_regression():
    """pitch 2.0 -> 1.5 improves `worst`; decay 0.2 -> 0.9 degrades 4.5x.
    A rule that reads only the maximum calls this progress."""
    base = result({"pitch": 2.0, "decay": 0.2})
    cand = result({"pitch": 1.5, "decay": 0.9})
    assert cand["worst"] < base["worst"], "the premise: worst really does improve"
    out = sc.compare(base, cand)
    assert out["verdict"] == sc.REJECT
    assert any("decay" in r for r in out["reasons"]), out


def test_improving_a_non_worst_property_is_progress():
    """decay 0.9 -> 0.2 with pitch pinned at 2.0. `worst` does not move at all,
    and the first draft of the DR would have FORBIDDEN shipping this."""
    base = result({"pitch": 2.0, "decay": 0.9})
    cand = result({"pitch": 2.0, "decay": 0.2})
    assert cand["worst"] == base["worst"], "the premise: worst is unchanged"
    assert sc.compare(base, cand)["verdict"] == sc.ACCEPT


# --- coverage cannot be traded for a better number ---------------------------

def test_dropping_a_required_metric_is_not_an_improvement():
    """The cheapest way to improve any aggregate is to stop measuring the thing
    that was failing."""
    base = result({"pitch": 2.0, "decay": 0.2})
    cand = result({"decay": 0.2})
    out = sc.compare(base, cand, required=["pitch", "decay"])
    assert out["verdict"] == sc.REJECT
    assert any("coverage lost" in r for r in out["reasons"]), out


def test_a_no_verdict_cannot_be_compared_in_either_direction():
    """Missing evidence is not a good score and not a bad one."""
    good = result({"pitch": 0.5})
    nv = result({}, state=sc.NO_VERDICT, why="reference is silent")
    assert sc.compare(nv, good)["verdict"] == sc.INCOMPARABLE
    assert sc.compare(good, nv)["verdict"] == sc.INCOMPARABLE


# --- the measurement basis must match ----------------------------------------

def test_a_repaired_estimator_forces_the_baseline_to_be_re_measured():
    """Comparing an old instrument's old number with a new instrument's
    corrected one confounds two changes. Three estimator repairs are in flight
    (#139, #150, #156), so this is live, not hypothetical."""
    base = result({"decay": 2.0})
    cand = result({"decay": 0.4})
    cand["provenance"] = json.loads(json.dumps(BASIS["provenance"]))
    cand["provenance"]["inputs"]["model/audio_measure.py"] = "sha256:REPAIRED"
    out = sc.compare(base, cand)
    assert out["verdict"] == sc.INCOMPARABLE
    assert any("re-measure the baseline" in r for r in out["reasons"]), out


def test_a_different_engine_is_not_a_comparison():
    """fixed-model against integrated-rtl is two instruments, not a change."""
    base = result({"pitch": 2.0})
    cand = result({"pitch": 0.5}); cand["engine"] = "integrated-rtl"
    assert sc.compare(base, cand)["verdict"] == sc.INCOMPARABLE


# --- an optimiser proposes; it does not approve -------------------------------

def test_a_surrogates_favourite_can_still_be_rejected():
    """A sum-of-squares surrogate prefers the candidate (2.0^2+0.2^2 = 4.04 ->
    1.5^2+0.9^2 = 3.06). The exact rule rejects it anyway. THAT is the
    safeguard -- not choosing an aligned surrogate, which guarantees nothing."""
    base = result({"pitch": 2.0, "decay": 0.2})
    cand = result({"pitch": 1.5, "decay": 0.9})
    sse = lambda r: sum(v * v for v in r["properties"].values())
    assert sse(cand) < sse(base), "the premise: the surrogate prefers the candidate"
    assert sc.compare(base, cand)["verdict"] == sc.REJECT


# --- noise is not progress, and allowances are per-property -------------------

def test_a_change_smaller_than_the_threshold_is_not_an_improvement():
    base = result({"pitch": 1.000})
    cand = result({"pitch": 0.999})
    assert sc.compare(base, cand)["verdict"] == sc.REJECT


def test_a_case_may_widen_one_propertys_allowance_deliberately():
    """A recorded trade-off is allowed. An unrecorded one is what `worst` hid."""
    base = result({"pitch": 2.0, "decay": 0.2})
    cand = result({"pitch": 1.5, "decay": 0.9})
    out = sc.compare(base, cand, allowances={"decay": 0.8})
    assert out["verdict"] == sc.ACCEPT, out
    assert out["regressed"] == []


# --- the three protections evaluate() ALREADY had (regression guards) ---------

def test_an_invalid_metric_still_gets_no_distance_rather_than_zero():
    case = {"required_measurements": "pitch"}
    res = {"engine": "fixed-model",
           # NOTE: these must be TRUTHY. evaluate() refuses on absent provenance,
           # and an empty dict is falsy -- an earlier draft of this fixture used
           # {} and the test failed because the code was working correctly.
           "provenance": {"worktree": {"commit": "abc"}, "command": "x",
                          "inputs": {"refs": "/refs"}},
           "metrics": {"pitch": {"valid": False, "why": "floor"}}}
    out = sc.evaluate(case, res)
    assert out["state"] == sc.NO_VERDICT
    assert out["worst"] is None, "zero would read as a perfect match"


def test_a_missing_required_metric_is_no_verdict_not_a_smaller_maximum():
    case = {"required_measurements": "pitch;decay"}
    res = {"engine": "fixed-model",
           # NOTE: these must be TRUTHY. evaluate() refuses on absent provenance,
           # and an empty dict is falsy -- an earlier draft of this fixture used
           # {} and the test failed because the code was working correctly.
           "provenance": {"worktree": {"commit": "abc"}, "command": "x",
                          "inputs": {"refs": "/refs"}},
           "metrics": {"decay": {"valid": True, "error": 0.1, "tolerance": 1.0}}}
    assert sc.evaluate(case, res)["state"] == sc.NO_VERDICT


def test_evaluate_now_returns_the_property_vector_at_all():
    """It used to compute the per-property distances and throw them away, so
    nothing downstream COULD enforce a no-regression rule."""
    case = {"required_measurements": "pitch;decay"}
    res = {"engine": "fixed-model",
           # NOTE: these must be TRUTHY. evaluate() refuses on absent provenance,
           # and an empty dict is falsy -- an earlier draft of this fixture used
           # {} and the test failed because the code was working correctly.
           "provenance": {"worktree": {"commit": "abc"}, "command": "x",
                          "inputs": {"refs": "/refs"}},
           "metrics": {"pitch": {"valid": True, "error": 0.5, "tolerance": 1.0},
                       "decay": {"valid": True, "error": 2.0, "tolerance": 1.0}}}
    out = sc.evaluate(case, res)
    assert out["properties"] == {"pitch": 0.5, "decay": 2.0}
    assert out["worst"] == 2.0
