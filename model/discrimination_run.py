#!/usr/bin/env python3
"""Render, extract, split, classify, report. The reproducible end of
model/test_discrimination.py; the written result is docs/discrimination.md.

    git clone --depth 1 https://github.com/tidalcycles/sounds-tr808-fischer /tmp/tr808-ref
    .venv/bin/python model/discrimination_run.py --refs /tmp/tr808-ref \\
        --out docs/img/discrimination --json /tmp/discrimination.json

Everything the scorecard needs comes out of one invocation: the revision
rendered, the split, the counts (unique recordings and settings, kept
separate from generated comparisons), the held-out balanced accuracies with
grouped uncertainty, the four comparative FD-mel rows, the matched and
unmatched passes, every control including the ones that return no verdict,
the largest differences per voice, and playable reference/candidate pairs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import wave
from concurrent.futures import ProcessPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "audition"))

import test_discrimination as td
from test_discrimination import (ARM_DOC, ARM_VOICES, ARMS, EQUIV_MARGIN, EXP_EMULATION,
                                 EXP_SOUND_MATCHING, FIT_KNOBS, GRADED_CONTROL_ARMS,
                                 POSITIVE_CONTROL_ARMS, TEST_KNOBS, V_NONE, Clip,
                                 balanced_accuracy, clopper_pearson, condition,
                                 corpus_is_level_normalised, counts, cross_voice_control,
                                 discriminate, effect_sizes, features, fit_laws, frechet,
                                 group_bootstrap_ci, group_importance, interpretable_gap,
                                 interpretable_table, knob_equivalent_distance, knob_str,
                                 n_for_margin, paired_abx, permutation_null, read_wav,
                                 real_vs_real_random, ref_clips, render, separation_curve,
                                 summarise, upper_bound_one_sided, verdict, zscore_per_voice)


# ---------------------------------------------------------------------------
def revision() -> dict:
    def git(*a):
        try:
            return subprocess.check_output(["git", "-C", os.path.dirname(HERE), *a],
                                           text=True).strip()
        except Exception:
            return "?"
    h = hashlib.sha256()
    for f in ("drums_fx.py", "modal_fixed.py", "test_discrimination.py"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return dict(commit=git("rev-parse", "HEAD"), described=git("describe", "--always", "--dirty"),
                model_sha256=h.hexdigest()[:16])


def split_hash(clips) -> str:
    key = "|".join(sorted(f"{c.voice}{c.knobs}{c.side}{'T' if c.is_test else 'F'}"
                          for c in clips))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
def _render_one(job):
    voice, knobs, arm, laws, level_match, floor_clamp = job
    x, sr = render(voice, knobs, laws, arm)
    out = {}
    for lm in ({True, False} if level_match is None else {level_match}):
        seg = condition(x, sr, lm)
        for fc in ({True, False} if floor_clamp is None else {floor_clamp}):
            out[(lm, fc)] = features(seg, sr, fc)[0]
    out["interp"] = td.interpretable_features(condition(x, sr, True), sr)
    return (voice, knobs, arm), out


def _real_one(job):
    voice, knobs, path = job
    x, sr = read_wav(path)
    out = {}
    for lm in (True, False):
        seg = condition(x, sr, lm)
        for fc in (True, False):
            out[(lm, fc)] = features(seg, sr, fc)[0]
    out["interp"] = td.interpretable_features(condition(x, sr, True), sr)
    return (voice, knobs, "real"), out


def build_cache(refs, arms, laws, jobs, names_holder):
    """Render and featurise everything once, in parallel, into a cache keyed
    by (voice, knobs, side). Every downstream experiment reads this, so no
    signal is ever conditioned twice and the passes cannot drift apart."""
    work_r = [(c.voice, c.knobs, c.path) for c in refs]
    work_o = []
    for arm in arms:
        vs = ARM_VOICES.get(arm)
        for c in refs:
            if vs is None or c.voice in vs:
                work_o.append((c.voice, c.knobs, arm, laws, None, None))
    cache = {}
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for k, v in ex.map(_real_one, work_r, chunksize=4):
            cache[k] = v
        done = 0
        for k, v in ex.map(_render_one, work_o, chunksize=4):
            cache[k] = v
            done += 1
            if done % 50 == 0:
                print(f"    rendered {done}/{len(work_o)}", flush=True)
    names_holder.append(features(np.zeros(int(td.WINDOW_S * 44100)), 44100)[1])
    return cache


def matrix(clips, cache, level_match, floor_clamp):
    return np.asarray([cache[(c.voice, c.knobs, c.side)][(level_match, floor_clamp)]
                       for c in clips])


# ---------------------------------------------------------------------------
def run_arm(refs, arm, cache, names, level_match=True, floor_clamp=True, seed=0):
    """One arm against the real machine: fit on FIT_KNOBS settings, report on
    TEST_KNOBS settings. Always balanced accuracy, always grouped by setting."""
    vs = ARM_VOICES.get(arm)
    use = [c for c in refs if vs is None or c.voice in vs]
    clips = use + [Clip(c.voice, c.knobs, arm) for c in use]
    X = matrix(clips, cache, level_match, floor_clamp)
    fit = np.array([not c.is_test for c in clips])
    X = zscore_per_voice(X, clips, fit)
    if fit.sum() < 6 or (~fit).sum() < 4:
        return None
    r = discriminate(clips, X, fit, ~fit, seed)
    te = [clips[i] for i in r["idx"]]
    groups = [f"{c.voice}{c.knobs}" for c in te]
    s = summarise(r["y"], r["pred"], arm)
    s["bal_acc"] = balanced_accuracy(r["y"], r["pred"])
    s["group_ci"] = group_bootstrap_ci(r["y"], r["pred"], groups, seed=seed)
    s["n_settings"] = len(set(groups))
    s["counts"] = counts(clips)
    s["abx"] = paired_abx(clips, r["idx"], r["score"])
    s["C"] = r["C"]
    per = {}
    for v in sorted({c.voice for c in te}):
        m = np.array([c.voice == v for c in te])
        if m.sum() == 0:
            continue
        sv = summarise(r["y"][m], r["pred"][m], v)
        sv["bal_acc"] = balanced_accuracy(r["y"][m], r["pred"][m])
        sv["n_settings"] = len({g for g, mm in zip(groups, m) if mm})
        per[v] = sv
    s["per_voice"] = per
    base, imp = group_importance(r["clf"], X, r["y"], r["idx"], names, seed)
    s["importance"] = dict(list(imp.items())[:8])
    s["eff"] = {v: dict(list(effect_sizes(X, clips, names, v, ~fit).items())[:5])
                for v in sorted({c.voice for c in te})}
    return s


def fd_rows(refs, arms, cache, seed=0):
    """FAD's construct, used the only way it is meaningful: comparatively,
    with encoder (this module's 320-d log-mel/MFCC), sample counts, voice
    balance and preprocessing identical across every row. Row 4 is the
    corpus against itself, which is the scale the other three are read on."""
    rng = np.random.default_rng(seed)
    voices = sorted({c.voice for c in refs})

    def bal(clips, per_voice):
        out = []
        for v in voices:
            g = [c for c in clips if c.voice == v]
            if len(g) >= per_voice:
                out += list(rng.permutation(np.array(g, dtype=object))[:per_voice])
        return out

    # Balance over the voices that actually have a knob sweep: CH, CP and CB
    # have one file each, so including them would force one clip per voice and
    # leave nothing to estimate a covariance from.
    voices = [v for v in voices if len([c for c in refs if c.voice == v]) >= 5]
    per = 5
    R = bal(refs, per)
    A = matrix(R, cache, True, True)
    # one basis for every row, so the four numbers are on one scale
    basis = A.copy()
    rows = {}
    for arm in arms:
        vs = ARM_VOICES.get(arm)
        pool = [Clip(c.voice, c.knobs, arm) for c in R if vs is None or c.voice in vs]
        ref_pool = [c for c in R if vs is None or c.voice in vs]
        if len(pool) < 4:
            continue
        rows[f"reference vs {arm}"] = frechet(matrix(ref_pool, cache, True, True),
                                              matrix(pool, cache, True, True), basis=basis)
    # the dataset's own variability: disjoint halves of the reference, same counts
    halves = []
    for _ in range(12):
        p = rng.permutation(len(R))
        halves.append(frechet(A[p[:len(R) // 2]], A[p[len(R) // 2:]], basis=basis))
    rows["reference vs reference subsets"] = float(np.median(halves))
    rows["_n_per_voice"] = per
    rows["_n_total"] = len(R)
    return rows


# ---------------------------------------------------------------------------
def write_pairs(refs, laws, outdir, arm="ours"):
    """Playable reference/candidate pairs: the largest differences, audible.
    Unnormalised on our side, as the chip would put them on the bus."""
    d = os.path.join(outdir, "pairs")
    os.makedirs(d, exist_ok=True)
    made = []
    for c in refs:
        if not c.is_test and c.knobs:
            continue
        x, sr = read_wav(c.path)
        ours, sro = render(c.voice, c.knobs, laws, arm)
        for tag, sig, s in ((f"{c.voice}-{knob_str(c.knobs)}-real", x, sr),
                            (f"{c.voice}-{knob_str(c.knobs)}-{arm}", ours, sro)):
            p = os.path.join(d, tag.replace("/", "_") + ".wav")
            with wave.open(p, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(s)
                w.writeframes(np.clip(sig * 32767, -32768, 32767).astype("<i2").tobytes())
            made.append(p)
    return made


def fmt(s):
    return (f"{s['bal_acc'] if 'bal_acc' in s else s['acc']:.3f} "
            f"[{s['ci'][0]:.2f},{s['ci'][1]:.2f}] n={s['n']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", default="/tmp/tr808-ref")
    ap.add_argument("--out", default="docs/img/discrimination")
    ap.add_argument("--json", default="/tmp/discrimination.json")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--no-pairs", action="store_true")
    a = ap.parse_args(argv)
    arms = [x for x in a.arms.split(",") if x]
    os.makedirs(a.out, exist_ok=True)

    rev = revision()
    print(f"revision {rev['described']} ({rev['commit'][:12]}), model sha {rev['model_sha256']}")

    norm = corpus_is_level_normalised(a.refs)
    print(f"\ncorpus level check: {norm['at_ceiling']}/{norm['n']} files within 1 % of the "
          f"ceiling, total range {norm['range_db']:.1f} dB "
          f"-> {'PEAK-LIMITED' if norm['normalised'] else 'not normalised'}")

    refs = ref_clips(a.refs)
    print(f"reference clips: {len(refs)} over {len({c.voice for c in refs})} voices; "
          f"fit {sum(1 for c in refs if not c.is_test)}, held out "
          f"{sum(1 for c in refs if c.is_test)}")
    print(f"split hash {split_hash(refs)}")

    print("\nfitting the control law on FIT_KNOBS =", FIT_KNOBS, "only")
    laws = fit_laws(a.refs)
    for k, v in sorted(laws.items()):
        if k.startswith("_meas"):
            print(f"  measured {k[6:]:22s} " +
                  "  ".join(f"k={kk}:{vv:.4g}" for kk, vv in zip(FIT_KNOBS, v)))

    print(f"\nrendering {len(arms)} arms on {a.jobs} workers...")
    names_holder = []
    cache = build_cache(refs, arms, laws, a.jobs, names_holder)
    names = names_holder[0]

    results = dict(revision=rev, split_hash=split_hash(refs), corpus_level=norm,
                   fit_knobs=FIT_KNOBS, test_knobs=TEST_KNOBS, equiv_margin=EQUIV_MARGIN,
                   n_for_margin=n_for_margin(), arms={}, arm_doc=ARM_DOC,
                   laws={k: repr(v) for k, v in laws.items() if not k.startswith("_")},
                   law_measurements={k[6:]: v for k, v in laws.items() if k.startswith("_meas")})

    # ---- controls first. If they fail, nothing below is a verdict. ----------
    print("\n== controls ==")
    cv = cross_voice_control(a.refs, {}, True, True)
    for k, v in cv.items():
        print(f"  cross-voice (real vs real, different voice) {k:12s} {fmt(v)}")
    perm_clips = refs + [Clip(c.voice, c.knobs, "ours") for c in refs]
    Xp = zscore_per_voice(matrix(perm_clips, cache, True, True), perm_clips,
                          np.array([not c.is_test for c in perm_clips]))
    fitp = np.array([not c.is_test for c in perm_clips])
    null = permutation_null(perm_clips, Xp, fitp, ~fitp, n_iter=200)
    print(f"  label-permutation null      mean {null['mean']:.3f} "
          f"[{null['p05']:.3f},{null['p95']:.3f}] over {null['n_iter']} shuffles")
    rvr = real_vs_real_random(a.refs, {}, "BD", n_iter=20)
    print(f"  real-vs-real random split   mean {rvr['mean']:.3f} "
          f"[{rvr['p05']:.3f},{rvr['p95']:.3f}] over {rvr['n_iter']} draws")
    curve = separation_curve(a.refs, {}, ("BD", "SD"))
    for k, s in sorted(curve.items()):
        print(f"  real-vs-real separation     {k[0]} {k[1]:7s} delta {k[-1]:4.1f}  {fmt(s)}")
    results["controls"] = dict(cross_voice={k: v for k, v in cv.items()}, null=null,
                               real_vs_real_random=rvr,
                               separation_curve={"|".join(map(str, k)): s
                                                 for k, s in curve.items()})

    cv_ok = all(v["acc"] >= 0.9 for v in cv.values()) if cv else False
    null_ok = null["p95"] < 0.75
    print(f"  -> cross-voice control {'PASS' if cv_ok else 'FAIL'}; "
          f"null calibration {'PASS' if null_ok else 'FAIL'}")

    # ---- the arms ----------------------------------------------------------
    print("\n== arms: held-out (emulation) balanced accuracy, level-matched ==")
    for arm in arms:
        s = run_arm(refs, arm, cache, names, True, True)
        if s is None:
            print(f"  {arm:14s} {V_NONE} (not enough held-out settings)")
            continue
        results["arms"][arm] = s
        print(f"  {arm:14s} {fmt(s)} settings={s['n_settings']} "
              f"recordings={s['counts']['recordings']} ABX {s['abx']['correct']}/{s['abx']['n']}")
    deg_ok = all(results["arms"].get(x, {}).get("bal_acc", 0) >= 0.9
                 for x in POSITIVE_CONTROL_ARMS if x in results["arms"])
    controls_ok = cv_ok and null_ok and deg_ok
    print(f"  -> large-degradation control {'PASS' if deg_ok else 'FAIL'}; "
          f"OVERALL {'usable' if controls_ok else 'NO VERDICT MAY BE DRAWN'}")
    results["controls_ok"] = dict(cross_voice=cv_ok, null=null_ok, degradations=deg_ok,
                                  overall=controls_ok)

    # ---- unmatched level, and the floor-clamp ablation ---------------------
    print("\n== ablations (arm 'ours') ==")
    abl = {}
    for lab, lm, fc in (("level-matched + floor clamp", True, True),
                        ("UNMATCHED level", False, True),
                        ("no floor clamp", True, False)):
        s = run_arm(refs, "ours", cache, names, lm, fc)
        if s:
            abl[lab] = s
            print(f"  {lab:28s} {fmt(s)}")
    if norm["normalised"]:
        print("  NOTE: the reference pack is peak-limited, so the unmatched pass carries no "
              "information about the machine's accent behaviour. Void, not a result.")
    results["ablations"] = abl

    # ---- FD-mel, comparative only -----------------------------------------
    print("\n== FD-mel (comparative; not FAD, not an absolute score) ==")
    fd = fd_rows(refs, arms, cache)
    for k, v in sorted(fd.items(), key=lambda kv: (kv[0].startswith("_"), kv[1] if not kv[0].startswith("_") else 0)):
        if not k.startswith("_"):
            print(f"  {k:42s} {v:9.3f}")
    print(f"  (voice-balanced, {fd['_n_per_voice']} per voice, {fd['_n_total']} clips per side)")
    results["fd_mel"] = fd

    # ---- interpretable diagnostics, on held-out settings only --------------
    print("\n== interpretable diagnostics, HELD-OUT settings only (generalisation) ==")
    rows = interpretable_table(refs + [Clip(c.voice, c.knobs, "ours") for c in refs],
                              laws, a.refs, {("interp", f"real:{c.voice}:{c.knobs}"):
                                             cache[(c.voice, c.knobs, "real")]["interp"]
                                             for c in refs} |
                              {("interp", f"ours:{c.voice}:{c.knobs}"):
                               cache[(c.voice, c.knobs, "ours")]["interp"] for c in refs})
    interp = {}
    for v in sorted({c.voice for c in refs if c.is_test}):
        g = interpretable_gap(rows, v, "ours")
        interp[v] = g
        worst = sorted(g.items(), key=lambda kv: -abs(kv[1]["abs_rel_err"]))[:3]
        print(f"  {v:3s} n={list(g.values())[0]['n'] if g else 0}  " +
              "  ".join(f"{k} {vv['mean_rel_err']*100:+.0f}%" for k, vv in worst))
    results["interpretable"] = interp

    # ---- per-voice verdicts ------------------------------------------------
    print("\n== per-voice verdicts (arm 'ours', emulation, level-matched) ==")
    main_s = results["arms"].get("ours", {})
    ver = {}
    mfn = lambda cl: matrix(cl, cache, True, True)
    for v, sv in sorted(main_s.get("per_voice", {}).items()):
        # the floor proxy is the WEAKEST knob at the smallest step -- the
        # closest two genuinely distinct real recordings ever get, which is
        # the best upper bound on take-to-take variation this corpus allows.
        # Taking the strongest knob instead would make the comparison vacuous.
        fl = min((s["acc"] for k, s in curve.items() if k[0] == v and k[-1] == 2.5),
                 default=None)
        dc = td.distance_curve(a.refs, cache, v, mfn)
        od = td.ours_distance(refs, cache, v, "ours", mfn)
        ke = td.knob_equivalent_distance(od, dc)
        dv = results["arms"].get("docfix", {}).get("per_voice", {}).get(v, {}).get("acc")
        ver[v] = dict(summary=sv, verdict=verdict(sv, controls_ok, fl),
                      knob_equivalent=ke, ours_distance=od,
                      distance_curve={f"{k[0]}|{k[1]}": val for k, val in dc.items()},
                      floor_upper_bound=fl, docfix_acc=dv,
                      top_features=list(main_s.get("eff", {}).get(v, {}).items())[:3])
        print(f"  {v:3s} {fmt(sv)} settings={sv['n_settings']}  dist {od:5.1f} vs "
              f"knob-10 {max(dc.values()) if dc else float('nan'):5.1f}  "
              f"knob-equiv {'>10 (off the dial)' if np.isnan(ke) else f'{ke:.1f}'}"
              f"  -> {ver[v]['verdict']}")
    results["verdicts"] = ver

    print("\n== what carries the discrimination (arm 'ours', held out) ==")
    for g, d in list(main_s.get("importance", {}).items())[:6]:
        print(f"  {g:22s} accuracy drop {d:+.3f} when shuffled")

    if not a.no_pairs:
        made = write_pairs(refs, laws, a.out)
        print(f"\nwrote {len(made)} playable reference/candidate pairs to {a.out}/pairs")

    with open(a.json, "w") as f:
        json.dump(results, f, indent=1, default=lambda o: (list(o) if isinstance(o, tuple)
                                                           else float(o) if isinstance(o, np.floating)
                                                           else int(o) if isinstance(o, np.integer)
                                                           else str(o)))
    print(f"wrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
