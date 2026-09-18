#!/usr/bin/env python3
"""The separator has to be right before anything measured with it is.

`model/drum_fit.py` decides how much of a struck hit is noise. Every number in
docs/drum-verification.md section 8 rests on it, including the one that
overturned "our snare's noise is 16 dB too quiet", so it is validated here two
ways and the method it replaced is kept as a control that must FAIL:

  1. against synthetic mixtures whose noise share is exact by construction;
  2. against our own renders, where the tonal path and the noise path can be
     rendered separately and the true share is exact arithmetic.

A control that cannot be shown wrong proves nothing, so
`test_the_whole_span_hann_split_is_the_artefact_it_is_recorded_as` asserts the
withdrawn method's error, not just the new method's accuracy.

    .venv/bin/python -m pytest model/test_drum_fit.py -q
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pytest
import drum_fit as df
import drums_fx as dx
from dsp import SR

SHARES = (0.0, 0.011, 0.05, 0.1855, 0.2766, 0.50, 0.80, 0.90)


@pytest.mark.parametrize("target", SHARES)
def test_separator_recovers_a_known_noise_share(target):
    """Two damped sinusoids plus band-limited noise, scaled so the noise
    carries exactly `target` of the energy -- including where the noise decays
    faster than the tone, which is our snare's case.

    The bound is the method's MEASURED accuracy, not a round number: the
    residual is the noise plus whatever of the tone the fit could not take
    out, so the estimate is biased slightly high and the bias grows with the
    noise. Below a 30 % share -- where both our kit and the machine's SNAPPY
    5.0 sit, so where every number in the SD comparison is read -- it is
    within 0.6 percentage points; above, within 1.5."""
    x = df.synthetic_mixture(target)
    got = df.noise_share(x, 44100, df.VOICE_MODES["SD"])["share"]
    bound = 0.006 if target <= 0.30 else 0.015
    assert got >= target - 0.002, f"target {target}, got {got}: an UNDER-estimate is a new failure mode"
    assert abs(got - target) < bound, f"target {target}, got {got}"


def test_separator_recovers_the_modes_it_subtracts():
    """The fitted frequencies and decays must be the ones the mixture was
    built from -- otherwise the residual is not the noise, it is the noise
    plus whatever the fit missed. Every decay reported is a tau."""
    x = df.synthetic_mixture(0.2766)
    m = df.noise_share(x, 44100, df.VOICE_MODES["SD"])["modes"]
    assert m[0]["hz"] == pytest.approx(173.0, rel=0.01)
    assert m[1]["hz"] == pytest.approx(336.0, rel=0.01)
    assert m[0]["tau_ms"] == pytest.approx(30.0, rel=0.10)


def _render_sd(override=None, seconds=0.5, accent=1.0):
    kit = dx.kit_808()
    if override:
        kit = [(a, override.get(a, v)) for a, v in kit]
    d = dx.DrumsFx()
    n = int(seconds * SR)
    dm, bd = d.play(dx.hit_writes([(10, dx.SD, accent)], kit), n)
    return dx.output_fx(np.zeros(n), 0, dm, dx.accent_reg(0.45), bd,
                        dx.accent_reg(0.45)).astype(np.float64) / 32768.0


def _peak_addr(e):
    return dx.A_ENV + e * dx.ENV_STRIDE + 1


def _true_share():
    """Exact: the snare's tonal path and its noise path are separate paths into
    separate modes with LIN nonlinearities, so rendering each alone and summing
    reproduces the full render bit for bit, and the true noise share is
    arithmetic rather than an estimate."""
    full = _render_sd()
    tone = _render_sd({_peak_addr(dx.E_SDN): 0})
    noise = _render_sd({_peak_addr(dx.E_SDX): 0})
    assert np.allclose(full, tone + noise, atol=2e-3), "the two paths are not additive"
    i = max(0, int(np.argmax(np.abs(full) > 0.02 * np.abs(full).max())) - int(5e-4 * SR))
    n = int(0.25 * SR)
    f, nn = full[i:i + n], noise[i:i + n]
    return float((nn @ nn) / (f @ f)), full


def test_separator_matches_the_exact_share_of_our_own_render():
    """The one case where the truth is not a construction but our own
    arithmetic: within 1 percentage point of it."""
    truth, full = _true_share()
    got = df.noise_share(full, SR, df.VOICE_MODES["SD"])["share"]
    assert abs(got - truth) < 0.01, f"truth {truth:.4f}, separator {got:.4f}"


def test_the_whole_span_hann_split_is_the_artefact_it_is_recorded_as():
    """The control. The withdrawn method -- power above and below 700 Hz of a
    Hann-windowed 500 ms span, `drum_verify.measure`'s body/air split -- must
    under-report our snare's noise by more than a factor of five. If this ever
    stops failing, the diagnosis in docs/drum-verification.md section 8 is
    wrong and the numbers there have to be re-derived."""
    truth, full = _true_share()
    x = df.trim_onset(full, SR)[:int(0.5 * SR)]
    S = np.abs(np.fft.rfft(x * np.hanning(len(x)), 1 << 18)) ** 2
    f = np.fft.rfftfreq(1 << 18, 1.0 / SR)
    tot = S[(f > 20) & (f < 16000)].sum()
    split = float(S[(f >= 700) & (f < 16000)].sum() / tot)
    assert split < truth / 5.0, (
        f"the whole-span Hann split reported {split * 100:.2f} % against a true "
        f"{truth * 100:.2f} %; it was supposed to be wrong by more than 5x")


@pytest.mark.parametrize("target", (0.05, 0.2766, 0.50))
def test_the_withdrawn_split_is_wrong_on_synthetic_mixtures_too(target):
    """Not just on our render: on mixtures with a known share, the whole-span
    Hann split under-reports by 5-9x whenever the noise decays faster than the
    tone. This is why the 47.3 % / 1.2 % pair could not be compared."""
    x = df.synthetic_mixture(target)
    y = df.trim_onset(x, 44100)[:int(0.5 * 44100)]
    S = np.abs(np.fft.rfft(y * np.hanning(len(y)), 1 << 18)) ** 2
    f = np.fft.rfftfreq(1 << 18, 1.0 / 44100)
    tot = S[(f > 20) & (f < 16000)].sum()
    split = float(S[(f >= 700) & (f < 16000)].sum() / tot)
    assert split < target / 4.0, f"target {target}, split {split}"


def test_knob_position_reads_a_ratio_off_a_curve_and_refuses_below_it():
    """A measured ratio maps to a knob position by interpolation in dB, and a
    ratio below the curve's own floor returns NaN rather than 0 -- 'quieter
    than the machine is at knob 0' is not 'at knob 0'."""
    law = {0.0: (0.047, 0.212, 0.07), 2.5: (0.050, 0.219, 0.07),
           5.0: (0.277, 0.619, 0.13), 7.5: (0.560, 1.153, 0.21),
           10.0: (0.719, 1.652, 0.30)}
    assert df.knob_position(0.619, law) == pytest.approx(5.0, abs=0.05)
    assert 2.5 < df.knob_position(0.40, law) < 5.0
    assert np.isnan(df.knob_position(0.10, law))


def test_a_short_window_fft_invents_a_peak_where_band_energy_does_not():
    """The withdrawn claim, reproduced and then refuted on a signal whose
    content is known exactly.

    A 50 Hz damped sinusoid -- one pure tone, nothing else -- gated to its
    first 4 ms and transformed has 250 Hz bins, so its apparent spectral peak
    is bin 1 at 250 Hz, and shortening or lengthening the gate walks that
    "peak" along the bin spacing. `band_energy_interval` filters first and
    integrates over the same interval, and puts the energy where it is."""
    t = np.arange(int(0.5 * SR)) / SR
    x = np.exp(-t / 0.18) * np.sin(2 * np.pi * 50.0 * t)
    peaks = []
    for ms in (4.0, 8.0, 16.0):
        g = x[:int(ms * 1e-3 * SR)]
        S = np.abs(np.fft.rfft(g))
        f = np.fft.rfftfreq(len(g), 1.0 / SR)
        peaks.append(float(f[1:][np.argmax(S[1:])]))
    assert peaks[0] > 200.0, f"the 4 ms gate should read a spurious peak above 200 Hz, got {peaks[0]:.0f}"
    assert peaks[0] > peaks[1] > peaks[2], f"the apparent peak must track the bin spacing: {peaks}"
    assert peaks[0] == pytest.approx(SR / int(4e-3 * SR), rel=0.01), "bin 1, exactly"

    edges = [20, 80, 150, 300, 600, 2000]
    for t1 in (0.004, 0.008, 0.016, 0.100):
        sh = df.band_energy_interval(x, SR, edges, 0.0, t1)
        assert np.argmax(sh) == 0, (t1, sh)         # the 20-80 Hz band, every time
        assert sh[0] > 75.0, (t1, sh)
