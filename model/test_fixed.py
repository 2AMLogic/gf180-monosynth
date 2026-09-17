#!/usr/bin/env python3
"""Regression tests for the fixed-point ladder.

These lock the numbers the design was sized from. They are not a bit-exact
contract yet -- that arrives when the oscillators and envelopes are integers
too -- but they stop the sizing decisions from silently rotting.
"""
import os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pytest
import dsp, fixed
from dsp import SR


def _saw(n, hz=110.0, amp=0.8):
    return dsp.osc("saw", dsp.ramp(n, dsp.phase_inc(hz))) * amp


def _diff_db(y, ref):
    m = min(len(y), len(ref)); y, ref = y[:m], ref[:m]
    a = y / max(np.sqrt((y ** 2).mean()), 1e-12)
    b = ref / max(np.sqrt((ref ** 2).mean()), 1e-12)
    return 20 * math.log10(max(np.sqrt(((a - b) ** 2).mean()), 1e-12))


def test_tracks_the_float_model():
    """Fixed point must stay within 20 dB of float on ordinary material."""
    n = int(0.3 * SR)
    x = _saw(n)
    f = fixed.LadderFx(tanh_entries=16, interp=True)
    y = fixed.q15f(f.process(fixed.f2q15(x), np.full(n, 900.0), 0.8, drive=2.0))
    ref = dsp.ladder(x, np.full(n, 900.0), np.full(n, 0.8), drive=2.0)
    assert _diff_db(y, ref) < -20.0


@pytest.mark.parametrize("entries", [16, 32, 128])
def test_small_table_is_enough(entries):
    """16 interpolated entries must be as good as 128. This is the finding the
    RTL's 256-bit ROM depends on; if it stops holding, the area claim changes."""
    n = int(0.3 * SR)
    x = _saw(n)
    ref = dsp.ladder(x, np.full(n, 900.0), np.full(n, 0.8), drive=2.0)
    f = fixed.LadderFx(tanh_entries=entries, interp=True)
    y = fixed.q15f(f.process(fixed.f2q15(x), np.full(n, 900.0), 0.8, drive=2.0))
    assert _diff_db(y, ref) < -30.0


def test_interpolated_beats_nearest_at_the_same_size():
    """Table values sit at bin EDGES when interpolating and MIDPOINTS when not.
    Mixing them costs ~8 dB and reads as 'interpolation made it worse'."""
    n = int(0.3 * SR)
    x = _saw(n)
    ref = dsp.ladder(x, np.full(n, 900.0), np.full(n, 0.8), drive=2.0)
    q = fixed.f2q15(x)
    interp = _diff_db(fixed.q15f(fixed.LadderFx(tanh_entries=16, interp=True)
                                 .process(q, np.full(n, 900.0), 0.8, drive=2.0)), ref)
    near = _diff_db(fixed.q15f(fixed.LadderFx(tanh_entries=16, interp=False)
                               .process(q, np.full(n, 900.0), 0.8, drive=2.0)), ref)
    assert interp < near - 10.0


def test_no_dead_zone_at_low_cutoff():
    """At 40 Hz the coefficient is ~0.0026; too few fraction bits and the
    increment truncates to zero and the filter stops responding."""
    n = int(0.3 * SR)
    x = _saw(n, 55.0)
    f = fixed.LadderFx(state_bits=24, state_q=20, tanh_entries=16)
    y = fixed.q15f(f.process(fixed.f2q15(x), np.full(n, 40.0), 0.5, drive=2.0))
    ref = dsp.ladder(x, np.full(n, 40.0), np.full(n, 0.5), drive=2.0)
    ry = np.sqrt((y[n // 2:] ** 2).mean()); rr = np.sqrt((ref[n // 2:] ** 2).mean())
    assert abs(20 * math.log10(max(ry, 1e-12) / max(rr, 1e-12))) < 3.0


def test_limit_cycle_stays_below_the_noise_floor():
    """Truncation sustains a small oscillation forever. It must stay tiny."""
    n1, n2 = int(0.3 * SR), int(2.0 * SR)
    x = np.concatenate([_saw(n1, 55.0, 0.9), np.zeros(n2)])
    f = fixed.LadderFx(state_bits=24, state_q=20, tanh_entries=16)
    y = f.process(fixed.f2q15(x), np.full(len(x), 600.0), 0.85, drive=2.5)
    tail = np.abs(y[-int(0.3 * SR):].astype(np.int32)).max()
    assert tail < 64, f"limit cycle {tail} LSB (> -54 dBFS)"


def test_self_oscillation_tracks_cutoff():
    """The half-sample feedback delay is what keeps the resonant peak on the
    cutoff. If it regresses, this drifts."""
    n = int(0.5 * SR)
    for fc in (200.0, 400.0, 800.0):
        f = fixed.LadderFx(tanh_entries=16)
        y = f.process(fixed.f2q15(np.full(n, 1e-3)), np.full(n, fc), 1.08, drive=1.0)
        tail = y[int(0.3 * SR):].astype(float)
        zc = np.sum(np.diff(np.signbit(tail)) != 0)
        got = zc / 2 / (len(tail) / SR)
        assert abs(got - fc) / fc < 0.12, f"cutoff {fc} -> {got:.0f} Hz"
