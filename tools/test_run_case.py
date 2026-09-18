#!/usr/bin/env python3
"""Ground truth for the estimators `tools/run_case.py` adds, and proof that the
runner reports the two states that are easy to get wrong.

    .venv/bin/python -m pytest tools/test_run_case.py -q

TWO JOBS, KEPT APART.

**Ground truth.** Four estimators are not in `model/audio_measure.py` and had
to be written. Each is exercised here against a signal whose answer is known in
closed form, before it is used on anything -- six estimator bugs were found in
this repository the day `model/test_audio_measure.py` was written, and every one
of them looked like a defect in the design until the estimator was checked.

**A runner's only failure mode that matters is a false green.** So the states
this runner must get right are the unhappy ones, and they are tested through
`tools/scorecard.py`'s own `evaluate` -- what the BOARD says, not what the
runner thinks it said:

  * a reference that is not there is `no verdict` with a stated reason, and
    carries no `error` key that could read as a zero distance;
  * a reference shifted by twice the tolerance is `fail`, not a near miss;
  * a voice the kit does not implement is `no verdict`, not a silent absence;
  * a required measurement that is missing invalidates the case rather than
    being dropped from the maximum.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "model"))

import audio_measure as am                                          # noqa: E402
import run_case as rc                                               # noqa: E402
import scorecard as sb                                              # noqa: E402

SR = 48000
REFS = pathlib.Path(rc.REFS_DEFAULT)
have_refs = pytest.mark.skipif(
    not (REFS / "bd8" / "BD5050.WAV").exists(),
    reason=f"the Fischer corpus is not at {REFS}; clone sounds-tr808-fischer")


def sine(hz, seconds, amp=1.0, sr=SR):
    """An integer number of periods, so a spectrum of it has no leakage and
    the closed-form answers below are exact."""
    n = int(round(seconds * hz)) * int(round(sr / hz))
    return amp * np.sin(2 * math.pi * hz * np.arange(n) / sr)


# ===========================================================================
# Ground truth: band_energy and band_ratio_db
# ===========================================================================
def test_band_energy_of_a_sine_is_all_in_its_own_band():
    """A sine of amplitude A over N samples carries N*A^2/2 of energy, all of
    it in a band containing its frequency and none in one that does not."""
    x = sine(1000.0, 0.25, amp=0.5)
    expect = len(x) * 0.5 ** 2 / 2.0
    inside = rc.band_energy(x, SR, 800.0, 1200.0)
    outside = rc.band_energy(x, SR, 2000.0, 8000.0)
    assert inside == pytest.approx(expect, rel=1e-3)
    assert outside < expect * 1e-6


def test_band_ratio_db_of_two_sines_is_their_amplitude_ratio():
    """Two sines either side of the split: the ratio is 20 log10(a_hi/a_lo),
    exactly, and the estimator must not invent a correction."""
    lo = sine(100.0, 0.5, amp=1.0)
    hi = sine(2000.0, 0.5, amp=0.5)
    n = min(len(lo), len(hi))
    e = rc.band_ratio_db(lo[:n] + hi[:n], SR, 700.0)
    assert e.ok
    assert e.value == pytest.approx(20 * math.log10(0.5), abs=0.1)


def test_band_ratio_db_refuses_a_band_with_nothing_in_it():
    """An absence is not a balance. A single low sine has no high-band energy,
    and the honest answer is a refusal, not a very negative number."""
    e = rc.band_ratio_db(sine(100.0, 0.5), SR, 700.0, hi=600.0)
    assert not e.ok and e.value is None


# ===========================================================================
# Ground truth: attack_ms
# ===========================================================================
def test_attack_ms_finds_a_known_linear_rise():
    """A 1 kHz carrier under an envelope that rises linearly over exactly
    20 ms and then decays. The short-time RMS window smears the peak by up to
    about one window, so the bound asserted is the window, not zero -- which
    is the honest statement of what this estimator can resolve."""
    rise_ms, win_ms = 20.0, 2.0
    n = int(0.30 * SR)
    t = np.arange(n) / SR
    k = int(rise_ms * 1e-3 * SR)
    env = np.concatenate([np.linspace(0, 1, k), np.exp(-(t[k:] - t[k]) / 0.05)])
    x = env * np.sin(2 * math.pi * 1000.0 * t)
    e = rc.attack_ms(x, SR, window_ms=win_ms)
    assert e.ok
    assert abs(e.value - rise_ms) <= win_ms


def test_attack_ms_cannot_resolve_an_attack_shorter_than_its_window():
    """A signal with no rise in it at all -- an exponential from sample zero.
    The estimator does not refuse; it reports about one window, because a
    short-time RMS cannot see anything faster than its own window. That is the
    resolution floor, and it is the reason every comparison this is used in
    takes BOTH sides with the same window, and the reason
    docs/drum-verification.md compares attack ratios rather than absolute
    attack times measured with different windows."""
    n = int(0.2 * SR)
    t = np.arange(n) / SR
    x = np.exp(-t / 0.02) * np.sin(2 * math.pi * 1000.0 * t)
    for win_ms in (2.0, 4.0):
        e = rc.attack_ms(x, SR, window_ms=win_ms)
        assert e.ok
        assert e.value <= win_ms


def test_attack_ms_refuses_silence():
    """An estimator that always produces a plausible number is how a 700 ms
    attack got reported on seven of eight voices."""
    assert not rc.attack_ms(np.zeros(SR // 10), SR).ok


# ===========================================================================
# Ground truth: tone_ratio_db
# ===========================================================================
def test_tone_ratio_db_of_two_known_sines():
    a, b = sine(800.0, 0.2, amp=1.0), sine(540.0, 0.2, amp=0.5)
    n = min(len(a), len(b))
    e = rc.tone_ratio_db(a[:n] + b[:n], SR, 800.0, 540.0)
    assert e.ok
    assert e.value == pytest.approx(20 * math.log10(1.0 / 0.5), abs=0.2)


def test_tone_ratio_db_refuses_a_record_too_short_to_project():
    """Three cycles is a guess with a plausible value, so the projection
    refuses it rather than returning one."""
    e = rc.tone_ratio_db(sine(800.0, 0.003), SR, 800.0, 540.0)
    assert not e.ok


# ===========================================================================
# Ground truth: worst_event_offset_ms
# ===========================================================================
def _clicks(times, sr=SR, seconds=2.0, tau=0.010):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    x = np.zeros(n)
    for s in times:
        i = int(s * sr)
        env = np.exp(-(t[i:] - t[i]) / tau)
        x[i:] += env * np.sin(2 * math.pi * 900.0 * (t[i:] - t[i]))
    return x


def test_worst_event_offset_ms_on_bursts_at_known_times():
    """Bursts placed at times we wrote down: the worst offset is inside the
    10 ms `audio_measure.onsets` states for itself."""
    times = [0.10, 0.60, 1.10, 1.60]
    e = rc.worst_event_offset_ms(_clicks(times), SR, times)
    assert e.ok
    assert e.value <= 10.0


def test_worst_event_offset_ms_sees_a_moved_event():
    """One burst 40 ms late, and the estimator must report about 40 ms -- not
    an average over the events that were on time."""
    sched = [0.10, 0.60, 1.10, 1.60]
    e = rc.worst_event_offset_ms(_clicks([0.10, 0.60, 1.14, 1.60]), SR, sched)
    assert e.ok
    assert e.value == pytest.approx(40.0, abs=10.0)


def test_worst_event_offset_ms_refuses_when_the_counts_disagree():
    """A missing event makes the pairing a guess, so there is no number."""
    e = rc.worst_event_offset_ms(_clicks([0.10, 0.60]), SR, [0.10, 0.60, 1.10])
    assert not e.ok and e.value is None


def test_coincident_hits_are_one_event():
    """Two stops struck in the same frame produce one onset. Counting them as
    two would make a correct render look like a miss."""
    e = rc.worst_event_offset_ms(_clicks([0.10, 0.60]), SR, [0.10, 0.1001, 0.60])
    assert e.ok


# ===========================================================================
# The runner's unhappy states, judged by the board's own evaluate()
# ===========================================================================
def _case(cid, required, family="Drums"):
    return {"case_id": cid, "family": family, "split": "Development",
            "subject": "test", "reference_target": "test", "batch": "First 32",
            "required_measurements": "; ".join(required)}


def _cases_row(cid):
    with open(rc.CASES_CSV) as fh:
        import csv
        for row in csv.DictReader(fh):
            if row["case_id"] == cid:
                return row
    raise AssertionError(cid)


def _prov():
    """The minimum provenance the board now insists on."""
    return {"worktree": {"commit": "abc1234", "dirty": False,
                         "uncommitted_sha256": "0" * 16},
            "command": "tools/run_case.py X1", "inputs": {"model/drums_fx.py": "sha256:x"},
            "engine": "fixed-model", "outcome_code": 0,
            "outcome_code_meaning": rc.OUTCOME_MEANING}


def test_a_result_without_provenance_gets_no_verdict():
    """A number nobody can re-derive is not evidence. With fourteen worktrees
    live at once, a result that cannot say what it ran against cannot be told
    apart from a stale one."""
    case = _case("X0", ["a"])
    good = {"value": 1.0, "reference": 1.0, "error": 0.0, "tolerance": 1.0,
            "units": "Hz", "valid": True}
    res = {"engine": "fixed-model", "metrics": {"a": good}}
    r = sb.evaluate(case, res)
    assert r["state"] == sb.NO_VERDICT and "no provenance" in r["why"]
    # ... and the same result WITH provenance passes, so the gate is the
    # provenance and not something else about the fixture.
    res["provenance"] = _prov()
    assert sb.evaluate(case, res)["state"] == sb.PASS


def test_a_clean_commit_is_not_enough_when_the_tree_is_dirty():
    """The uncommitted tree is hashed as well as the commit, so two runs at the
    same SHA with different working trees are distinguishable on the record."""
    w = rc.worktree_state()
    assert set(w) >= {"commit", "dirty", "uncommitted_sha256"}
    assert len(w["uncommitted_sha256"]) == 16


def test_the_outcome_code_convention_is_the_repositorys():
    """0 match, 1 mismatch (a result), 2 did not run (no evidence). A case that
    produced no evidence and one that was measured and scored badly need
    opposite responses, so they must never share a code."""
    assert rc.OUTCOME_CODE["pass"] == 0
    assert rc.OUTCOME_CODE["fail"] == 1
    assert rc.OUTCOME_CODE["no verdict"] == 2 and rc.OUTCOME_CODE["not run"] == 2


def test_every_result_this_runner_writes_carries_provenance():
    row = _cases_row("D14A")
    res = rc.run_case(row, REFS, keep_audio=False)
    prov = res["provenance"]
    assert prov["engine"] in sb.ENGINES
    assert prov["worktree"]["commit"] and prov["command"]
    assert "model/drums_fx.py" in prov["inputs"]
    assert prov["outcome_code_meaning"] == rc.OUTCOME_MEANING


def test_an_invalid_metric_carries_no_error_key_at_all():
    """Zero reads on the board as a perfect match. An invalid measurement has
    NO distance, so there must be no `error` to read."""
    m = rc.invalid_metric("Hz", "the reference is not there", 5.0)
    assert m["valid"] is False and "error" not in m and "value" not in m


def test_a_missing_required_measurement_invalidates_the_case():
    """Not dropped from the maximum -- otherwise the cheapest route to a better
    score is to stop measuring the inconvenient thing."""
    case = _case("X1", ["a", "b"])
    res = {"engine": "fixed-model", "provenance": _prov(),
           "metrics": {"a": {"value": 1.0, "reference": 1.0, "error": 0.0,
                             "tolerance": 1.0, "units": "Hz", "valid": True}}}
    r = sb.evaluate(case, res)
    assert r["state"] == sb.NO_VERDICT and "missing required: b" in r["why"]


def test_a_result_without_an_engine_gets_no_verdict():
    case = _case("X2", ["a"])
    res = {"provenance": _prov(),
           "metrics": {"a": {"value": 1.0, "reference": 1.0, "error": 0.0,
                             "tolerance": 1.0, "units": "Hz", "valid": True}}}
    assert sb.evaluate(case, res)["state"] == sb.NO_VERDICT


def test_every_engine_this_runner_writes_is_one_the_board_knows():
    assert rc.ENGINE in sb.ENGINES


def test_an_unimplemented_voice_is_a_stated_no_verdict_not_a_silence():
    """Eight of the sixteen drum cases name voices the eight-stop kit does not
    have. The case must come back with a reason attached, not vanish."""
    row = _cases_row("D14A")               # cymbal: in the corpus, not in the kit
    res = rc.run_case(row, REFS, keep_audio=False)
    r = sb.evaluate(row, res)
    assert r["state"] == sb.NO_VERDICT
    assert "CY" in res["note"] and "REFUSED" in res["note"]
    for m in res["metrics"].values():
        assert m["valid"] is False and "error" not in m


@have_refs
def test_a_missing_reference_is_a_no_verdict_with_a_reason():
    """The control: point the reference at a file that is not there. The board
    must say no verdict and the reason must name the missing recording."""
    row = _cases_row("D01A")
    res = rc.run_case(row, REFS, inject="REF_MISSING", keep_audio=False)
    r = sb.evaluate(row, res)
    assert r["state"] == sb.NO_VERDICT
    assert "missing" in res["note"].lower()
    assert all("error" not in m for m in res["metrics"].values())


@have_refs
def test_a_reference_shifted_by_twice_the_tolerance_fails():
    """The other control: the reference pitch moved 20 %, which is twice the
    frequency tolerance. A runner that reported this as a pass would be
    reporting a false green, which is the only failure mode that matters."""
    row = _cases_row("D01A")
    res = rc.run_case(row, REFS, inject="REF_F0_20PCT", keep_audio=False)
    r = sb.evaluate(row, res)
    assert r["state"] == sb.FAIL, res["metrics"]
    assert r["worst"] > 1.0


@have_refs
def test_the_same_case_without_the_injection_does_not_fail_on_pitch():
    """A control only means something if the uninjected run differs. Without
    the shift, the pitch metric is inside its own tolerance -- so the failure
    above is the injection and not the case."""
    row = _cases_row("D01A")
    res = rc.run_case(row, REFS, keep_audio=False)
    m = res["metrics"]["Pitch trajectory"]
    assert m["valid"] and abs(m["error"]) <= m["tolerance"]


@have_refs
def test_the_injection_refuses_to_write_onto_the_board():
    """A control's output is not evidence about the instrument and must never
    be able to be mistaken for it."""
    assert rc.main(["--inject", "REF_F0_20PCT", "D01A"]) == 2


def test_every_first_32_case_has_a_stated_plan():
    """Honestly accounted for means every case says what happens to it: a
    measurement, a stated refusal, or a stated reason for not running. A case
    with no entry anywhere is the one that quietly disappears."""
    import csv
    with open(rc.CASES_CSV) as fh:
        rows = [r for r in csv.DictReader(fh) if r["batch"] == "First 32"]
    assert len(rows) == 32
    unplanned = [r["case_id"] for r in rows if rc.plan_for(r["case_id"]) == "unplanned"]
    assert not unplanned, f"no stated plan for {unplanned}"


def test_tolerances_are_frozen_in_one_place_and_named_by_every_metric():
    """A per-case tolerance is a tolerance fitted to an error. Every rule here
    names one of the frozen classes."""
    for voice, plan in rc.DRUM_PLAN.items():
        for name, units, est, rule in plan:
            _, basis = rule(10.0, {"ref_f0": 100.0})
            assert basis.split(" (")[0] in rc.TOLERANCE_POLICY, (voice, name, basis)


def test_written_results_are_the_shape_the_board_reads(tmp_path):
    """Round trip: what the runner writes is what scorecard.py loads."""
    row = _cases_row("D14A")
    res = rc.run_case(row, REFS, keep_audio=False)
    p = tmp_path / "D14A.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    back = json.loads(p.read_text())
    assert back["engine"] in sb.ENGINES
    assert sb.evaluate(row, back)["state"] == sb.NO_VERDICT
