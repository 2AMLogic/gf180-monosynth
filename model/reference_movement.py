#!/usr/bin/env python3
"""Does our filter step audibly when the cutoff MOVES?

    .venv/bin/python model/reference_movement.py --stage control
    .venv/bin/python model/reference_movement.py --stage sweep
    .venv/bin/python model/reference_movement.py --stage plugins --out /tmp/refmove
    .venv/bin/python model/reference_movement.py --stage all --out /tmp/refmove

Every other filter measurement in this repository holds the cutoff STILL.
Zipper noise is by definition a thing that only happens while a control moves,
so none of them can see it -- and the appeal of a Moog filter is largely in
movement: fast envelope sweeps, filter wobble, a hand on the cutoff. This is
issue #46's "movement" criterion, and it had no test at all.

Three measurements, in increasing order of how much can go wrong with them:

  control   EXACT, no audio. Our cutoff control path is `cutoff in integer Hz
            -> g in Q0.16, from a 128-entry ROM read with linear
            interpolation`. Invert the realised g back to an effective cutoff
            and you get the control's resolution in CENTS at every cutoff,
            in closed form. This is the root cause if there is one.
  sweep     DIFFERENTIAL, ours only, and the strongest audio evidence
            available: render the same sweep twice through the same filter,
            once with the shipping integer control path and once with the
            cutoff and g in float. The difference IS the control path's
            contribution -- there is nothing else it can be.
  plugins   DEVICE-INDEPENDENT, all four filters: a steady carrier, the
            cutoff swept across it, and the ripple that survives a high-pass
            of the output's envelope (`audio_measure.envelope_ripple_db`,
            ground-truthed against a staircase of known step size).

What Surge does, for contrast, read from `sst-filters`
`FilterCoefficientMaker_Impl.h`:

    tC[i] = (1 - smooth) * tC[i] + smooth * N[i];    // smooth = 0.2, per block
    dC[i] = (tC[i] - C[i]) * blockSizeInv;           // then a linear ramp
    ...and per oversampled sub-step:  C[i] += dFac * dC[i];

-- a one-pole low-pass on the coefficient TARGET followed by a linear ramp of
the coefficient across the block. At Surge's 32-sample block and 48 kHz that
first stage is a time constant of about 3 ms (a ~53 Hz corner). Surge
deliberately BAND-LIMITS its cutoff control. Ours has no smoothing of any
kind: the cutoff follows the filter envelope exactly, per sample. Neither is
obviously right -- smoothing costs 3 ms of lag on a fast envelope, which is
audible in a different way -- but it is a choice, and ours has not been made
deliberately.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "audition"))

import audio_measure as am                                          # noqa: E402
import reference_rigs as rr                                         # noqa: E402
import voice_fx as vf                                               # noqa: E402
from fixed import LadderFx                                          # noqa: E402

SR = rr.SR
FS_OS = SR * 2                     # the ladder's oversampled rate
G_ROM = vf.make_g_rom()
K_ROM = vf.make_k_rom()


# ===========================================================================
# 1. the control path, in closed form
# ===========================================================================
def g_to_hz(g_q16: float) -> float:
    """Invert g = 1 - exp(-2*pi*f/fs_os). The effective cutoff a given
    coefficient actually realises."""
    g = min(max(float(g_q16) / 65536.0, 1e-12), 1 - 1e-12)
    return -math.log(1.0 - g) * FS_OS / (2.0 * math.pi)


def control_resolution(cut_hz: float) -> dict:
    """At this cutoff: the realised cutoff, the static error against the
    commanded one, and the size of ONE step of the control path -- the
    smallest change in commanded Hz that changes the coefficient at all --
    expressed in cents.

    Both quantisations are in here and neither is separable from the other by
    listening: the commanded cutoff is an INTEGER number of hertz (contract
    5.1, `cut_lo`/`cut_hi`/`track_hz` are 16-bit integer Hz) and `g` is an
    INTEGER in Q0.16. At 30 Hz one LSB of g is 0.78 % of g; at 4 kHz it is
    0.02 %. The staircase is therefore coarse at the bottom of the range and
    invisible at the top, which is the opposite of where a test that sweeps
    the top octave would look."""
    c = int(round(cut_hz))
    g = int(vf.g_from_cut(np.array([c]), G_ROM)[0])
    eff = g_to_hz(g)
    # walk up in commanded Hz until g changes: that is one step of the control
    step_hz, gn = 0, g
    while gn == g and step_hz < 4096:
        step_hz += 1
        gn = int(vf.g_from_cut(np.array([c + step_hz]), G_ROM)[0])
    eff_next = g_to_hz(gn)
    cents = 1200.0 * math.log2(max(eff_next, 1e-9) / max(eff, 1e-9)) if gn != g else float("nan")
    return dict(commanded_hz=c, g=g, effective_hz=eff,
                static_error_cents=1200.0 * math.log2(eff / max(c, 1e-9)),
                step_hz=step_hz, step_cents=cents,
                gain_step_db_at_24_db_oct=cents / 1200.0 * 24.0)


def stage_control():
    rows = [control_resolution(c) for c in
            (30, 40, 60, 80, 120, 200, 300, 500, 800, 1200, 2000, 3200, 6400, 10000, 16000)]
    print(f"{'cut Hz':>7} {'g':>6} {'effective':>10} {'static err':>11} "
          f"{'1 step':>8} {'step':>8} {'gain step':>10}")
    print(f"{'':>7} {'Q0.16':>6} {'Hz':>10} {'cents':>11} {'Hz':>8} {'cents':>8} "
          f"{'dB @24/oct':>10}")
    for r in rows:
        print(f"{r['commanded_hz']:7d} {r['g']:6d} {r['effective_hz']:10.2f} "
              f"{r['static_error_cents']:+11.2f} {r['step_hz']:8d} {r['step_cents']:8.2f} "
              f"{r['gain_step_db_at_24_db_oct']:10.3f}")
    return rows


# ===========================================================================
# 2. the differential sweep -- ours, exact
# ===========================================================================
def _regs(res, cut, drive=1.0, compensated=True):
    ref = LadderFx(**vf.LADDER_CFG)
    k, gain, ogain = ref.regs(res, drive)
    if compensated:
        kc = int(vf.kc_from_cut(np.array([int(cut)]), K_ROM)[0])
        k = int(vf.k_effective(k, kc))
    return k, gain, ogain


def sweep_pair(f_carrier: float, lo: float, hi: float, seconds: float,
               res: float = 0.3, amp: float = 0.25):
    """The same exponential cutoff sweep through the same ladder twice:
    the shipping integer control path, and the same sweep with the cutoff and
    `g` left in float. Returns (shipping, smooth, cut_float)."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    cut_f = lo * (hi / lo) ** (t / seconds)                 # float Hz, per sample
    x = np.round(amp * 32768 * np.sin(2 * math.pi * f_carrier * t)).astype(np.int16)
    k, gain, ogain = _regs(res, math.sqrt(lo * hi))
    # (a) the shipping path: integer Hz, then the Q0.16 ROM read
    cut_i = np.clip(np.round(cut_f), 30, 21600).astype(np.int64)
    g_i = vf.g_from_cut(cut_i, G_ROM)
    kc = vf.kc_from_cut(cut_i, K_ROM)
    k_eff = vf.k_effective(np.full(n, _regs(res, 1000, compensated=False)[0]), kc)
    a = LadderFx(**vf.LADDER_CFG).process(x, None, res, 1.0, g_q16=g_i,
                                          k=None, gain=gain, ogain=ogain, k_q14=k_eff)
    # (b) the smooth reference: the identical filter, float cutoff, float g
    b = LadderFx(**vf.LADDER_CFG).process(x, cut_f, res, 1.0,
                                          k=None, gain=gain, ogain=ogain, k_q14=k_eff)
    return np.asarray(a, float), np.asarray(b, float), cut_f


def stage_sweep(seconds_list=(0.1, 0.4, 1.6, 4.0)):
    rows = []
    print(f"{'sweep':>7} {'octaves/s':>10} {'range Hz':>13} {'residual':>10} "
          f"{'ripple ours':>12} {'ripple smooth':>14} {'rate':>8}")
    for lo, hi in ((60.0, 960.0), (500.0, 8000.0)):
        for s in seconds_list:
            a, b, _ = sweep_pair(2000.0 if lo > 100 else 220.0, lo, hi, s)
            resid = am.db(am.rms(a - b), am.rms(b))
            lp = (220.0 if lo < 100 else 800.0)
            ea = am.analytic_envelope(a)
            eb = am.analytic_envelope(b)
            ra = am.envelope_ripple_db(ea, SR, lp_hz=lp)
            rb = am.envelope_ripple_db(eb, SR, lp_hz=lp)
            r = dict(lo=lo, hi=hi, seconds=s, oct_per_s=math.log2(hi / lo) / s,
                     residual_db=resid,
                     ripple_shipping_db=ra.value if ra.ok else None,
                     ripple_smooth_db=rb.value if rb.ok else None,
                     ripple_rate_hz=ra.detail.get("ripple_rate_hz") if ra.ok else None)
            rows.append(r)
            print(f"{s:7.2f} {r['oct_per_s']:10.1f} {lo:6.0f}-{hi:<6.0f} {resid:10.1f} "
                  f"{(ra.value if ra.ok else float('nan')):12.1f} "
                  f"{(rb.value if rb.ok else float('nan')):14.1f} "
                  f"{(r['ripple_rate_hz'] or float('nan')):8.0f}", flush=True)
    return rows


def stage_injected():
    """START RED. Coarsen the cutoff control deliberately -- round the
    commanded cutoff to 32 Hz -- and the differential must rise by roughly the
    ratio of the step sizes. If it does not, the measurement has no power and
    nothing above it means anything."""
    print("  injected: the commanded cutoff rounded to 32 Hz steps")
    out = []
    for lo, hi, s in ((60.0, 960.0, 0.1), (500.0, 8000.0, 0.1)):
        n = int(s * SR)
        t = np.arange(n) / SR
        cut_f = lo * (hi / lo) ** (t / s)
        x = np.round(0.25 * 32768 * np.sin(2 * math.pi * (220.0 if lo < 100 else 2000.0)
                                           * t)).astype(np.int16)
        _, gain, ogain = _regs(0.3, math.sqrt(lo * hi))
        k_eff = vf.k_effective(np.full(n, _regs(0.3, 1000, compensated=False)[0]),
                               vf.kc_from_cut(np.clip(np.round(cut_f), 30, 21600).astype(np.int64),
                                              K_ROM))
        ref = LadderFx(**vf.LADDER_CFG).process(x, cut_f, 0.3, 1.0, k=None, gain=gain,
                                                ogain=ogain, k_q14=k_eff)
        res = {}
        for tag, cq in (("shipping (1 Hz)", 1), ("injected (32 Hz)", 32)):
            ci = np.clip(np.round(cut_f / cq) * cq, 30, 21600).astype(np.int64)
            y = LadderFx(**vf.LADDER_CFG).process(x, None, 0.3, 1.0,
                                                  g_q16=vf.g_from_cut(ci, G_ROM),
                                                  k=None, gain=gain, ogain=ogain, k_q14=k_eff)
            res[tag] = am.db(am.rms(np.asarray(y, float) - np.asarray(ref, float)),
                             am.rms(np.asarray(ref, float)))
        out.append(dict(lo=lo, hi=hi, **{k.split()[0]: v for k, v in res.items()}))
        print(f"    {lo:5.0f}-{hi:<6.0f} Hz:  " +
              "   ".join(f"{k} {v:+7.1f} dB" for k, v in res.items()) +
              f"    separation {res['injected (32 Hz)'] - res['shipping (1 Hz)']:+.1f} dB")
    return out


# ===========================================================================
# 3. all four filters, device-independent
# ===========================================================================
CARRIER = 2000.0
SWEEP_LO, SWEEP_HI = 500.0, 8000.0
LP_HZ = 800.0          # below the carrier: excludes the analytic envelope's own
                       # 2*f0 ripple, which read as -32 dB of 'stepping' that was
                       # not there. See audio_measure.envelope_ripple_db.
RATES_S = (0.4, 1.6, 4.0)   # slow enough that the step rate lands under LP_HZ


def stage_plugins(devices, cache):
    rows = []
    for name in devices:
        try:
            dev = _build(name)
        except Exception as e:                                       # noqa: BLE001
            print(f"  {name}: NOT AVAILABLE -- {e}", flush=True)
            continue
        for s in RATES_S:
            try:
                y = dev_sweep(dev, name, CARRIER, SWEEP_LO, SWEEP_HI, s, cache)
            except NotImplementedError as e:
                print(f"  {name}: NOT ANSWERABLE -- {e}", flush=True)
                break
            env = am.analytic_envelope(y)
            e = am.envelope_ripple_db(env, SR, lp_hz=LP_HZ)
            r = dict(device=name, seconds=s,
                     oct_per_s=math.log2(SWEEP_HI / SWEEP_LO) / s,
                     ripple_db=e.value if e.ok else None,
                     host_block=getattr(dev, "block", None),
                     ripple_rate_hz=e.detail.get("ripple_rate_hz") if e.ok else None,
                     why=None if e.ok else e.reason)
            rows.append(r)
            print(f"  {name:12s} {s:5.2f} s ({r['oct_per_s']:5.1f} oct/s)  ripple "
                  f"{(e.value if e.ok else float('nan')):7.1f} dB  at "
                  f"{(r['ripple_rate_hz'] or float('nan')):6.0f} Hz", flush=True)
        del dev
    return rows


# Parameter automation is applied per HOST BLOCK. At dawdreamer's default 512
# samples that is 93.75 Hz, and a swept cutoff then moves in 93.75 Hz steps --
# which is exactly what the first run measured on all three plugins, at
# identical 94 Hz, while ours (which moves per sample) sat at the floor. That
# was the harness stepping, not the plugins. 16 samples puts the automation
# rate at 3 kHz, well above the analysis band.
PLUGIN_BLOCK = 16


def _build(name, block=PLUGIN_BLOCK):
    if name == "ours":
        return None
    return {"surge-huov": lambda: rr.SurgeRig("Type 2", block=block),
            "surge-rk": lambda: rr.SurgeRig("Type 1", block=block),
            "miniv3": lambda: rr.MiniV3Rig(block=block),
            "diva": lambda: rr.DivaRig("rough", block=block)}[name]()


def dev_sweep(dev, name, carrier, lo, hi, seconds, cache):
    """A steady carrier through a cutoff swept exponentially from lo to hi."""
    if name == "ours":
        a, _, _ = sweep_pair(carrier, lo, hi, seconds)
        return a / 32768.0
    return dev.swept_cutoff(carrier, lo, hi, seconds, cache)


# ===========================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="control",
                    choices=["control", "sweep", "injected", "plugins", "all"])
    ap.add_argument("--devices", default="ours,surge-huov,surge-rk,miniv3,diva")
    ap.add_argument("--out", default="/tmp/refmove")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    cp = os.path.join(a.out, "knobs.json")
    cache = json.load(open(cp)) if os.path.exists(cp) else {}
    stages = ["control", "sweep", "injected", "plugins"] if a.stage == "all" else [a.stage]
    out = {}
    if "control" in stages:
        print("\n== 1. our cutoff control path, in closed form ==")
        out["control"] = stage_control()
    if "sweep" in stages:
        print("\n== 2. the differential sweep: shipping control path vs the same filter "
              "with a float one ==")
        out["sweep"] = stage_sweep()
    if "injected" in stages:
        print("\n== 3. START RED ==")
        out["injected"] = stage_injected()
    if "plugins" in stages:
        print(f"\n== 4. all filters, envelope ripple, carrier {CARRIER:.0f} Hz, "
              f"cutoff {SWEEP_LO:.0f}-{SWEEP_HI:.0f} Hz ==")
        out["plugins"] = stage_plugins([d for d in a.devices.split(",") if d], cache)
    for k, v in out.items():
        json.dump(v, open(os.path.join(a.out, f"{k}.json"), "w"), indent=1, default=str)
    json.dump(cache, open(cp, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
