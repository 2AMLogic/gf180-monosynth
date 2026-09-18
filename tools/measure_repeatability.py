#!/usr/bin/env python3
"""How much does a real TR-808 differ from itself? -- issue #111.

    tools/measure_repeatability.py --self-test    estimator noise, first
    tools/measure_repeatability.py --audit        is the corpus repeats at all?
    tools/measure_repeatability.py --measure      the machine's own spread
    tools/measure_repeatability.py --all [--json OUT]

Every tolerance on the scorecard -- 3.0 dB on an energy ratio, 10 % on an f0,
50 % on a time -- is a *convention*. None has a measurement of the machine's
own variation behind it, so nobody knows whether a case that fails at 1.036 is
a defect or a tolerance finer than the machine. This tool answers that with
recordings, or REFUSES and says why.

THREE OUTCOMES, kept apart, the repository's verifier convention:

    exit 0   the spread was measured
    exit 1   it was measured and something it asserts is false
    exit 2   REFUSED -- a precondition is unmet, so nothing was measured

WHAT IT REFUSES, AND THE ONE THAT FIRED
---------------------------------------
`refaudio/README.md` and issue #111 both state that the 808 From Mars clean
bass drum is **24 settings x 6 takes = 144 files** and is "the only place in
the corpus where the same machine plays the same thing more than once."

**It is not. The trailing `01`..`06` is the TONE knob, not a take index.**
`--audit` establishes that from the files rather than from the file names, and
`--measure` therefore refuses the take-to-take question and answers the one the
corpus *can* answer: the same machine, the same nominal knob positions, two
independent recording sessions years apart (the vendor's current edition and
its superseded legacy edition), which is session-to-session reproducibility --
a strictly larger and more relevant quantity than take-to-take, because it is
what anyone comparing against a single recorded reference is actually exposed
to.

ORDER OF OPERATIONS, AND WHY
----------------------------
The estimator is measured before the machine is. An estimator with its own
scatter measures itself, and the ratio of the two is the only thing that says
whether a machine number means anything. `--self-test` runs three controls:

  1. DETERMINISM -- the same array six times must give bit-identical answers.
     Zero, or every number below is contaminated by the estimator's own RNG.
  2. GROUND TRUTH -- a synthetic bass drum whose f0 and T20 are known in closed
     form, so an estimator that is stable but wrong is still caught.
  3. EDITING NOISE -- one real recording, six copies differing only by what the
     vendor's *editor* did and the machine did not: the start-trim and
     end-trim jitter actually observed in the corpus. That spread is the floor;
     a machine spread beneath it is not a measurement.

The estimators are IMPORTED from `tools/run_case.py`, never re-implemented, so
what is characterised here is the path the board actually scores through --
including its known defects. Where a defect biases a spread, the defect is
measured rather than described: see `--audit`'s windowing column (#101) and
`truncation_sensitivity` (#118).

WHAT THIS CANNOT DO
-------------------
It bounds ONE machine. Every real-808 recording reachable from this repository
descends from a single unit, and nominally different "808" sets cross-correlate
at 1.000 -- the same events re-pressed. Unit-to-unit is the larger term and
there is no data for it here at all. So the result is a FLOOR on the machine's
variation. A tolerance already tighter than the floor is definitely wrong; one
wider than it is merely unproven.
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import pathlib
import re
import sys

import numpy as np

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "model"))
sys.path.insert(0, str(REPO / "tools"))

import audio_measure as am                                        # noqa: E402
import run_case as rc                                             # noqa: E402

MEASURED, FALSE, REFUSED = 0, 1, 2

CACHE = REPO / "refaudio" / "cache"
CURRENT = (CACHE / "808-from-mars" / "808 From Mars" / "WAV" /
           "01. Individual Hits" / "01. Bass Drum" / "Clean")
LEGACY = (CACHE / "808_from_mars_legacy" / "808 From Mars - Legacy" / "WAV" /
          "1. Individual Hits" / "01. Bass Drum" / "1. Clean")

FETCH = ("tools/refaudio_local.py --prefix 808-from-mars.zip "
         "'808 From Mars/WAV/01. Individual Hits/01. Bass Drum/Clean/'")


class Refused(Exception):
    """A precondition of the apparatus failed. Nothing was attempted."""


# ===========================================================================
# 1. Loading, with the preconditions asserted at the point of use
# ===========================================================================
def load(path: pathlib.Path) -> tuple[np.ndarray, int]:
    """One recording as float64 mono, or a REFUSAL.

    24-bit files, so NOT `scipy.io.wavfile` + /32768 the way `run_case.py`
    reads the 16-bit Fischer set: that divisor is wrong by 256 here and would
    read every file 48 dB hot. Level is normalised away downstream, which is
    exactly why a scaling error of this kind survives unnoticed -- so it is
    asserted here instead: a correctly read 24-bit file peaks below 1.0."""
    import soundfile as sf
    if not path.is_file():
        raise Refused(f"{path.name} is not in refaudio/cache -- run:\n         {FETCH}")
    x, sr = sf.read(str(path), dtype="float64", always_2d=False)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if am.is_silent(x):
        raise Refused(f"{path.name} is silent")
    pk = float(np.abs(x).max())
    if not (0.0 < pk <= 1.0):
        raise Refused(f"{path.name} peaks at {pk:.4f}: not a correctly scaled float read")
    if am.clipped_fraction(x, 1.0) > 0.0:
        raise Refused(f"{path.name} has samples at the rail")
    if int(sr) != 44100:
        raise Refused(f"{path.name} is {sr} Hz; the indexed corpus is 44.1 kHz")
    return x, int(sr)


#: (decay letter, tone index) -> path, for one chain/accent folder.
def grid(folder: pathlib.Path, pattern: re.Pattern) -> dict[tuple[str, int], pathlib.Path]:
    out: dict[tuple[str, int], pathlib.Path] = {}
    for p in sorted(folder.glob("*.wav")):
        m = pattern.match(p.name)
        if m:
            out[(m.group("decay"), int(m.group("tone")))] = p
    return out


CUR_RE = re.compile(r"BD (?P<accent>[AB]) 808 (?:Tape )?Decay (?P<decay>[A-F]) (?P<tone>\d\d)\.wav$")
LEG_RE = re.compile(r"BD_(?:Clean|Tape)_(?:NoAcc|Acc)_(?P<decay>[A-F])_808_(?P<tone>\d\d)\.wav$")


def current_grid(accent: str = "A", chain: str = "Digital"):
    return grid(CURRENT / chain / accent, CUR_RE)


def legacy_grid(accent: str = "1. No Accent", chain: str = "1. Digital"):
    return grid(LEGACY / chain / accent, LEG_RE)


# ===========================================================================
# 2. The metrics -- the board's own estimators, imported, not re-implemented
# ===========================================================================
#: name -> (units, estimator(y, sr) -> Estimate, tolerance rule, on_the_board)
#
# The first three ARE case D01A's `required_measurements`, taken straight off
# `run_case.DRUM_PLAN["BD"]` so they cannot drift from what the board scores.
# The rest are board estimator FAMILIES that other drum cases use, pointed at
# the bass drum, because #111 asks for the spread of "every metric the board
# scores" and the bass drum is the only voice that can supply one.
def metrics() -> dict:
    m = {}
    for name, units, est, tol in rc.DRUM_PLAN["BD"]:
        m[name] = (units, est, tol, "D01A")
    m["body spectrum"] = ("dB", rc._split_db("BD", 0.0, 0.150), rc.tol_db,
                          "D03A-D08A family")
    m["body spectrum (padded)"] = ("dB", _split_db_padded("BD", 0.150), rc.tol_db,
                                   "#101 control")
    m["attack"] = ("ms", rc._attack("BD"), rc.tol_time, "D02A/D09A family")
    m["pitch drop"] = ("Hz", rc._pitch_drop("BD"), rc.tol_frequency_of_f0,
                       "D03A/D05A/D07A family")
    m["band energy 20-200"] = ("dB", _band_frac_db("BD", 0, 0.150), rc.tol_db,
                               "band energies")
    m["band energy 200-2000"] = ("dB", _band_frac_db("BD", 1, 0.150), rc.tol_db,
                                 "band energies")
    return m


def _split_db_padded(sound: str, t1: float):
    """`_split_db` with 10 ms of silence in front of the strike.

    The #101 control. `band_energy` filters with `sosfiltfilt`, whose odd
    extension manufactures an edge when the window opens ON the strike -- worth
    up to 6.07 dB against a 3.0 dB tolerance, and every file in this corpus
    opens on the strike (its first sample above 2 % of peak is sample 5 to 9).
    Prepending silence cannot change what the machine did, so any difference
    between this and `body spectrum` is the apparatus. Reported side by side:
    what matters for #111 is not the bias, which is common to both sides of a
    comparison, but whether the bias *varies* between recordings and so inflates
    the spread."""
    inner = rc._split_db(sound, 0.0, t1 + 0.010)

    def f(y, sr):
        return inner(np.concatenate([np.zeros(int(0.010 * sr)), y]), sr)
    return f


def _band_frac_db(sound: str, which: int, t1: float):
    """The two band energies of `body spectrum`, each as its own fraction of
    total energy in dB, rather than only their ratio. A ratio hides which side
    moved; #111 asks for band ENERGIES."""
    b_lo, b_hi = rc.BAND[sound]
    split = rc.SPLIT_HZ[sound]

    def f(y, sr):
        seg = rc.window(y, sr, 0.0, t1)
        e = am.band_energy(seg, ((b_lo, split), (split, b_hi)), sr)
        v = float(e[which])
        if v <= 0:
            return am.Estimate(None, False, "band holds no energy", dict(frac=v))
        return am.Estimate(10.0 * math.log10(v), True, "", dict(frac=v))
    return f


def measure_all(y: np.ndarray, sr: int, plan: dict) -> dict:
    """Every metric on one prepared recording. A refusal stays a refusal."""
    out = {}
    for name, (_u, est, _t, _w) in plan.items():
        e = est(y, sr)
        out[name] = float(e.value) if e.ok else None
    return out


def truncation_sensitivity(y: np.ndarray, sr: int) -> float | None:
    """How much T20 moves when the record is shortened by 10 %.

    Issue #118: `schroeder_t20`'s guard is a LEVEL criterion (`tail_db`) and
    the backward integral of ANY finite record falls toward -inf at its last
    sample, so the guard cannot see truncation -- a 100 ms cut of a 92 ms T20
    reads -18.4 % while `tail_db` reports a comfortable -79 dB. Every file in
    this corpus is editor-trimmed, so the question is live for all of them.

    A LENGTH criterion, measured rather than asserted: cut 10 % more off and
    re-read. A record with enough decay after the fitting range does not care;
    a truncation-limited one moves. Returned in percent, so a caller can refuse
    on it. `model/audio_measure.py` is owned by another agent for #118, so this
    lives here and does not touch it."""
    full = am.schroeder_t20(rc.window(y, sr, 0.005, None), sr)
    if not full.ok:
        return None
    short = am.schroeder_t20(rc.window(y, sr, 0.005, None)[: int(0.90 * (len(y) - int(0.005 * sr)))], sr)
    if not short.ok:
        return math.inf
    return 100.0 * (short.value - full.value) / full.value
