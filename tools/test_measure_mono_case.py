"""Ground truth and refusal controls for measure_mono_case."""
from __future__ import annotations

import numpy as np
import pytest

import measure_mono_case as m


def test_measure_accepts_a_known_saw():
    f0 = 440.0
    t = np.arange(0.7 * m.SR) / m.SR
    x = np.zeros_like(t)
    for k in range(1, int(m.SR / (2 * f0))):
        x += np.sin(2 * np.pi * k * f0 * t) / k
    got = m._measure(x / np.max(np.abs(x)), f0)
    assert abs(got["f0_hz"] - f0) < 0.1
    assert got["inharmonic_db"] < -80


def test_measure_refuses_silence():
    with pytest.raises(m.Refused, match="silent"):
        m._measure(np.zeros(int(0.7 * m.SR)), 440.0)


def test_measure_refuses_nonfinite():
    x = np.ones(int(0.7 * m.SR))
    x[10] = np.nan
    with pytest.raises(m.Refused, match="non-finite"):
        m._measure(x, 440.0)
