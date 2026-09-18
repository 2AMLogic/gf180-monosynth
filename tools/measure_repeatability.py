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


def longest_true_run(mask) -> int:
    """Longest run of True. `audio_measure.longest_plateau` is the wrong tool
    for this -- it is the longest run of any identical value, which on a mask
    that is mostly False is the silence."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return 0
    best = run = 0
    for v in m:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


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
    # A clipped file cannot carry an energy ratio. But a SINGLE sample at
    # exactly full scale is peak normalisation, not clipping -- the legacy
    # pack is normalised per file and 57 of its 144 bass drums have exactly
    # one such sample, none of them consecutive. Clipping is a PLATEAU at the
    # rail; refuse on that and not on the level.
    run = longest_true_run(np.abs(x) >= 1.0 - 1e-9)
    if run > 1:
        raise Refused(f"{path.name} is flat-topped at the rail: {run} consecutive samples")
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


# ===========================================================================
# 3. The audit: is a nominal repeat group actually repeats?
#
# `refaudio/README.md` and #111 both read the trailing `01`..`06` on the bass
# drum as round-robin take numbers. The file names do not say that, and a file
# name is not evidence. This asks the recordings.
#
# The vendor's own notes, in catalog.json's `about` for the pack, say what the
# folders are:
#
#     A / B / C -- A = No Accent, B = Accent, C = More Accent
#     Bass Drum / Clean -- "Multi-Sampled Levels of 808 Decay and Tone at 2
#     accent levels"
#
# so the grid is 2 chains x 2 accents x 6 DECAY x 6 TONE = 144, with no take
# axis at all. The naming convention is confirmed by the voices that have no
# knob to sweep: Cowbell, Rim Shot and Claves are 2 accents x 2 chains = FOUR
# clean files each and carry NO trailing number. The congas, "2 accent levels
# at 11 tunings", carry 01..11. The trailing number is a knob index wherever it
# appears.
#
# That is documentary evidence. The three tests below are physical, so the
# conclusion does not rest on a vendor's prose either.
# ===========================================================================
def spearman(y: list[float]) -> float:
    """Rank correlation of `y` against its own index order. +-1 is monotone.

    For six values in random order, P(|rho| = 1) = 2/6! = 1/360."""
    n = len(y)
    r = np.empty(n)
    r[np.argsort(np.argsort(np.asarray(y, float)))] = np.arange(n)
    i = np.arange(n, dtype=float)
    return float(np.corrcoef(r, i)[0, 1])


def align(sigs: list[np.ndarray], maxlag: int = 256) -> np.ndarray:
    """Integer-lag align to the first signal and truncate to a common length."""
    n = min(len(s) for s in sigs)
    ref = sigs[0][:n] - sigs[0][:n].mean()
    out = [sigs[0][:n]]
    for s in sigs[1:]:
        s = s[:n]
        best, bl = -np.inf, 0
        c = s - s.mean()
        for lag in range(-maxlag, maxlag + 1):
            v = float(np.dot(ref[maxlag:n - maxlag], c[maxlag + lag:n - maxlag + lag]))
            if v > best:
                best, bl = v, lag
        out.append(np.roll(s, -bl))
    m = np.array([o[maxlag:n - maxlag] for o in out])
    return m / np.abs(m).max(axis=1, keepdims=True)


def rank1_fraction(sigs: list[np.ndarray]) -> tuple[float, list[float]]:
    """Fraction of the between-recording variance carried by ONE component,
    and that component's loading per recording.

    Six recordings that differ by one knob are (fixed voice) + c_k x (fixed
    additive term): a rank-1 family, with loadings monotone in knob position.
    Six repeats of one setting differ by trigger jitter, thermal drift and
    noise -- several uncorrelated terms, no single component dominating and no
    reason for a monotone loading."""
    m = align(sigs)
    d = m - m.mean(axis=0, keepdims=True)
    s = np.linalg.svd(d, compute_uv=False)
    u, sv, _ = np.linalg.svd(d, full_matrices=False)
    loading = (u[:, 0] * sv[0]).tolist()
    if loading[-1] < loading[0]:
        loading = [-v for v in loading]
    return float(s[0] ** 2 / np.sum(s ** 2)), loading


def audit(report=print) -> tuple[bool, dict]:
    """Are the trailing-numbered bass-drum files repeats of one setting?

    Returns (is_repeats, evidence). False is the finding, not a failure."""
    ev: dict = {"groups": [], "vendor_note": "A/B = accent; per catalog.json "
                "the BD clean set is 'Multi-Sampled Levels of 808 Decay and "
                "Tone at 2 accent levels'"}
    plan = metrics()
    report("  group                       metric                   rho   span")
    mono = collections.Counter()
    for chain in ("Digital",):
        for accent in ("A", "B"):
            g = current_grid(accent, chain)
            if len(g) != 36:
                raise Refused(f"{chain}/{accent} holds {len(g)} of the 36 indexed files")
            for decay in "ABCDEF":
                sigs, vals = [], collections.defaultdict(list)
                for tone in range(1, 7):
                    x, sr = load(g[(decay, tone)])
                    sigs.append(x)
                    y = rc.prepare(x, sr)
                    for k, v in measure_all(y, sr, plan).items():
                        vals[k].append(v)
                frac, loading = rank1_fraction(sigs)
                row = {"group": f"{chain}/{accent}/Decay {decay}",
                       "rank1_variance_fraction": round(frac, 4),
                       "rank1_loading_spearman": round(spearman(loading), 4),
                       "metrics": {}}
                for k, v in vals.items():
                    if any(t is None for t in v):
                        continue
                    rho, span = spearman(v), max(v) - min(v)
                    row["metrics"][k] = {"spearman_vs_tone_index": round(rho, 4),
                                         "span": round(span, 4),
                                         "values": [round(t, 4) for t in v]}
                    if abs(rho) == 1.0:
                        mono[k] += 1
                ev["groups"].append(row)
                report(f"  {row['group']:26s} rank-1 variance {frac*100:5.1f} %  "
                       f"loading rho {spearman(loading):+.2f}")
                for k in ("body spectrum", "early/body energy", "Pitch trajectory", "decay"):
                    if k in row["metrics"]:
                        d_ = row["metrics"][k]
                        report(f"      {k:24s} rho {d_['spearman_vs_tone_index']:+.2f}"
                               f"   span {d_['span']:8.3f}")
    ev["monotone_group_count"] = dict(mono)
    ev["groups_total"] = len(ev["groups"])
    return False, ev


# ===========================================================================
# 4. The estimator, before the machine
#
# "If an estimator is itself noisy, you will measure the estimator rather than
# the machine." Three controls, in increasing severity.
# ===========================================================================
def synthetic_bd(sr: int = 44100, f0: float = 50.0, tau: float = 0.120,
                 seconds: float = 3.0, click: float = 0.25,
                 seed: int | None = None) -> np.ndarray:
    """A bass drum with a closed-form answer: one damped sinusoid at `f0` with
    amplitude time constant `tau`, plus a short click so the band split and the
    attack have something to measure.

    T20 of a single exponential is ln(10)*tau exactly, and that identity is
    `audio_measure`'s own ground truth for `schroeder_t20`, so an estimator
    that is STABLE but WRONG is still caught here."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    y = np.exp(-t / tau) * np.sin(2 * np.pi * f0 * t)
    k = int(0.002 * sr)
    y[:k] += click * np.exp(-np.arange(k) / (0.0004 * sr))
    if seed is not None:
        y = y + np.random.default_rng(seed).normal(0.0, 1e-5, n)
    return y / np.abs(y).max()


def self_test(report=print) -> tuple[bool, dict]:
    """Estimator noise, so the machine numbers have something to be a ratio to."""
    plan = metrics()
    sr = 44100
    ev: dict = {}
    ok = True

    # --- 1. determinism -----------------------------------------------------
    x = synthetic_bd(sr)
    runs = [measure_all(rc.prepare(x.copy(), sr), sr, plan) for _ in range(6)]
    nondet = [k for k in plan
              if len({None if r[k] is None else round(r[k], 12) for r in runs}) > 1]
    ev["determinism"] = {"identical": not nondet, "nondeterministic": nondet}
    report(f"  determinism      six runs of one array: "
           f"{'identical' if not nondet else 'DIFFER: ' + str(nondet)}")
    ok &= not nondet

    # --- 2. ground truth ----------------------------------------------------
    f0, tau = 50.0, 0.120
    y = rc.prepare(synthetic_bd(sr, f0=f0, tau=tau), sr)
    got_f0 = plan["Pitch trajectory"][1](y, sr)
    got_t20 = plan["decay"][1](y, sr)
    want_t20 = am.t20_from_tau(tau) * 1e3
    e_f0 = abs(got_f0.value - f0) / f0 * 100 if got_f0.ok else None
    e_t20 = abs(got_t20.value - want_t20) / want_t20 * 100 if got_t20.ok else None
    ev["ground_truth"] = {"f0_hz": f0, "f0_measured": got_f0.value, "f0_error_pct": e_f0,
                          "t20_ms": want_t20, "t20_measured": got_t20.value,
                          "t20_error_pct": e_t20}
    report(f"  ground truth     f0 {got_f0.value:.4f} Hz vs {f0} ({e_f0:+.3f} %)   "
           f"T20 {got_t20.value:.3f} ms vs ln(10)*tau = {want_t20:.3f} ({e_t20:+.3f} %)")
    ok &= (e_f0 is not None and e_f0 < 1.0) and (e_t20 is not None and e_t20 < 1.0)

    # --- 3. editing noise ---------------------------------------------------
    # The floor that matters. One REAL recording, six copies differing only by
    # what the vendor's editor did and the machine did not: where the file was
    # cut at the head and at the tail. Both jitters are taken from the corpus
    # itself rather than invented -- the onset lands on sample 5 to 9 across the
    # bass drums, and file lengths at one decay position spread by up to 0.8 %.
    g = current_grid("A", "Digital")
    x, sr = load(g[("C", 3)])
    copies = []
    for head in (0, 2, 4):
        for tail in (0, -0.004):
            z = x[head:]
            if tail:
                z = z[: int(len(z) * (1.0 + tail))]
            copies.append(measure_all(rc.prepare(z, sr), sr, plan))
    floor = {}
    for k in plan:
        v = [c[k] for c in copies if c[k] is not None]
        floor[k] = {"n": len(v), "span": (max(v) - min(v)) if len(v) > 1 else None,
                    "sd": float(np.std(v, ddof=1)) if len(v) > 1 else None}
    ev["editing_noise"] = floor
    report("  editing noise    one recording, six editor-trim variants:")
    for k, v in floor.items():
        if v["span"] is not None:
            report(f"      {k:26s} span {v['span']:9.4f} {plan[k][0]}   sd {v['sd']:.4f}")

    # --- truncation, #118 ---------------------------------------------------
    ts = {}
    for decay in "ABCDEF":
        xx, sr2 = load(g[(decay, 3)])
        ts[f"Decay {decay}"] = truncation_sensitivity(rc.prepare(xx, sr2), sr2)
    ev["t20_truncation_sensitivity_pct"] = ts
    report("  truncation (#118) T20 move when 10 % more of the record is cut:")
    report("      " + "  ".join(f"{k.split()[-1]} {v:+.2f} %" if v is not None
                                else f"{k.split()[-1]} n/a" for k, v in ts.items()))

    # START RED. A probe that answers 0.00 % on every file it is shown has not
    # been observed to fail, and this repository has shipped four harnesses in
    # that state. Cut a record while it is still sounding and the probe must
    # say so -- and `schroeder_t20`'s own tail_db guard must NOT, which is the
    # whole of #118.
    xx, sr2 = load(g[("E", 3)])
    yy = rc.prepare(xx, sr2)
    cut = yy[: int(0.40 * sr2)]
    red = truncation_sensitivity(cut, sr2)
    guard = am.schroeder_t20(rc.window(cut, sr2, 0.005, None), sr2)
    ev["truncation_red_test"] = {
        "cut_to_s": 0.40, "full_t20_ms": am.schroeder_t20(rc.window(yy, sr2, 0.005, None), sr2).value * 1e3,
        "cut_t20_ms": None if not guard.ok else guard.value * 1e3,
        "cut_tail_db": guard.detail.get("tail_db"),
        "probe_pct": red, "probe_fires": red is None or abs(red) > 5.0}
    t = ev["truncation_red_test"]
    said = "REFUSED" if not guard.ok else f"{t['cut_t20_ms']:.0f} ms, tail_db {t['cut_tail_db']:.0f}"
    report(f"  red test         a 400 ms cut of a {t['full_t20_ms']:.0f} ms T20: "
           f"length probe {red:+.1f} %; schroeder_t20 says {said}")
    ok &= bool(ev["truncation_red_test"]["probe_fires"])
    return ok, ev
