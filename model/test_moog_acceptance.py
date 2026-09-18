#!/usr/bin/env python3
"""Acceptance suite: does this behave like the instrument we said we were building?

Every other test in `model/` asks whether the integer model matches the float
model, or whether the RTL matches the integer model. None of them asks whether
the thing we are building is the thing the decision records describe. This file
does, one test per claimed musical property, each citing its source and its
tolerance, so that a claim in a DR cannot quietly stop being true.

    .venv/bin/python -m pytest model/test_moog_acceptance.py -q      # ~75 s

Sources of truth, in the repository:

  DR 0001  the ladder model -- Huovilainen, the nonlinearity in every stage,
           the aliasing table PolyBLEP was adopted from
  DR 0004  glide: constant rate, linear in pitch, 90 ms per octave
  DR 0005  gain structure: the tanh is the designed saturation, the VCA is
           after the filter, exactly one hard rail
  DR 0006  resonance compensation: res = 1 is the onset everywhere within 0.39 %
  spec/NUMERIC-CONTRACT.md  6 (oscillators), 8 (envelopes), 11 (the ladder),
           12 (the output stage and every clamp)
  docs/DESIGN.md  sections 5 and 6, the measured behaviour

Method: every estimator comes from `model/audio_measure.py`, the shared,
ground-truthed module (`model/test_audio_measure.py`), and every one of them
can answer "insufficient evidence" instead of a plausible number. The voice's
additions to that module -- `tone_amplitude`, `harmonic_powers`,
`inharmonic_fraction_db`, `foldback_alias_db`, `zero_crossing_frequency`,
`tonality_db`, `max_sample_step`, `longest_plateau`, `event_slices` -- are in
its last section with their own ground truth. What that buys here:

  * **The filter is measured with a controlled probe**, never inferred from the
    finished voice's spectrum. A spectral centroid is not a cutoff: it moves
    with the excitation, the envelope and the nonlinearity as much as with the
    filter. Frequency response, passband gain, resonance and rolloff all come
    from a stepped sine at a stated drive and a coherent projection -- an
    impulse response would presume linearity, and this filter's response
    depends on level by design. Finished-voice renders are for acceptance
    (does a note end, does anything clip), never for diagnosis.
  * **Aliasing is measured where the aliases land** -- at the predicted
    fold-back frequency of each harmonic above Nyquist -- and cross-checked
    against DR 0001's own inharmonic-energy measure. Waveform accuracy is a
    separate property from aliasing, with its own test.
  * **Events are analysed separately**, and an envelope is the analytic one,
    not a moving average.
  * **Tonality is max-over-median**, not spectral flatness.
  * **Levels are reported absolutely**; no A/B normalises both sides, which
    would hide a gain error by construction.

What this suite does NOT claim: that the filter sounds like a Moog ladder.
It shows our structure is not the linearised one (test_the_nonlinearity_is_in
_every_stage), which is what DR 0001 decided. Matching a real circuit would
need an independently derived circuit response or a documented reference
recording, and this repository has neither.

The last group, "the suite can fail", injects the four defects most likely to
be silently wrong -- the resonance-compensation ROM, the square's PolyBLEP
sign, the envelope release floor, the VCA's position -- plus a dropped pole and
an all-silent stub, and requires the corresponding property to go red
(`docs/verification-rules.md`, rules 1 and 2).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
import dsp                                                          # noqa: E402
import voice_fx as vf                                               # noqa: E402
import audio_measure as am                                          # noqa: E402
from audio_measure import InsufficientEvidence      # noqa: E402,F401  (the stub controls below rely on it being an AssertionError)
from dsp import SR                                                  # noqa: E402

FS = 32768.0                     # Q1.15 full scale
_REAL_LADDER = vf.LadderFx       # captured before any test monkeypatches the name
G_ROM = vf.make_g_rom()
K_ROM = vf.make_k_rom()


# =============================================================================
# probes: how the filter is driven, and how the voice is played
# =============================================================================
def _ladder_regs(res, drive, cut, compensated=True):
    """The register image the host would write for this operating point
    (contract 5.5 and 10.2), including the per-frame k_eff of DR 0006."""
    ref = _REAL_LADDER(**vf.LADDER_CFG)
    k, gain, ogain = ref.regs(res, drive)
    g = int(vf.g_from_cut(np.array([cut]), G_ROM)[0])
    if compensated:
        kc = int(vf.kc_from_cut(np.array([cut]), K_ROM)[0])
        k = int(vf.k_effective(k, kc))
    return g, k, gain, ogain


def ladder_render(x_q15, cut, res, drive, compensated=True, ladder=None, **cfg):
    """`x_q15` through one ladder at a fixed operating point. `vf.LadderFx` is
    looked up at call time so an injected defect is seen."""
    g, k, gain, ogain = _ladder_regs(res, drive, cut, compensated)
    lad = ladder if ladder is not None else vf.LadderFx(**{**vf.LADDER_CFG, **cfg})
    n = len(x_q15)
    return lad.process(np.asarray(x_q15, dtype=np.int16), None, res, drive,
                       g_q16=np.full(n, g, dtype=np.int64),
                       k=k, gain=gain, ogain=ogain).astype(np.float64)


def probe_gain_db(f, cut, res, drive, amp=30000, dur=0.6, settle=0.2, **kw):
    """Steady-state gain at one frequency, from a stepped sine and a coherent
    projection: the transfer measurement. The projection is what lets the
    stopband be read at 0.6 LSB peak (-94 dB), 25 dB under the truncation
    noise (ground truth: test_tone_amplitude_recovers_a_known_amplitude...)."""
    n = int(dur * SR)
    x = np.round(amp * np.sin(2 * math.pi * f * np.arange(n) / SR)).astype(np.int16)
    y = ladder_render(x, cut, res, drive, **kw)[int(settle * SR):]
    a = am.tone_amplitude(y, f).require(f"probe at {f:.0f} Hz, cutoff {cut}")
    return 20.0 * math.log10(max(a, 1e-12) / amp)


def _ring_windows(cut):
    """Burst, settle and analysis windows for a free ring at this cutoff --
    20 cycles each, so that at a high cutoff the windows close before the
    oscillation reaches its limit cycle (model/k_comp_sweep.py)."""
    ncyc = SR / cut
    return (max(int(0.02 * SR), int(20 * ncyc)),
            max(int(0.005 * SR), int(10 * ncyc)),
            max(int(0.01 * SR), int(20 * ncyc)))


def ring_growth(cut, res, compensated=True):
    """Growth rate (nepers/s) of the filter's FREE ring: a short sine burst at
    the predicted oscillation frequency, then silence. Positive means the loop
    sustains, negative means it decays; the sign is the onset test.

    The burst amplitude is adapted so the tail sits between 150 and 1200 LSB --
    inside the tanh table's first bin, where the loop is linear apart from
    truncation and the sign is amplitude-independent, and above the truncation
    floor. Returns (rate, tail)."""
    n_burst, n_settle, n_win = _ring_windows(cut)
    _, f_lin = vf.k_onset(cut, G_ROM)
    for amp in (100.0, 25.0, 6.0, 1.5, 400.0, 1600.0):
        n = n_burst + n_settle + 2 * n_win
        x = np.zeros(n, dtype=np.int16)
        x[:n_burst] = np.round(
            amp * np.sin(2 * math.pi * f_lin * np.arange(n_burst) / SR)).astype(np.int16)
        tail = ladder_render(x, cut, res, 1.0, compensated)[n_burst:]
        a = tail[n_settle:n_settle + n_win]
        b = tail[n_settle + n_win:n_settle + 2 * n_win]
        peak = float(np.abs(tail[n_settle:n_settle + 2 * n_win]).max())
        rate = math.log(max(am.rms(b), 1e-9) / max(am.rms(a), 1e-9)) / (n_win / SR)
        if 150.0 <= peak <= 1200.0:
            return rate, tail[n_settle:]
        if peak > 1200.0 and amp <= 1.5:
            return 100.0, tail[n_settle:]          # sustains even from nothing
    return (100.0 if peak > 1200.0 else -100.0), tail[n_settle:]


def onset_res(cut, compensated=True, lo=0.95, hi=1.05, iters=10):
    """The host `res` at which the ring stops decaying and starts growing,
    bisected on the fixed-point filter itself. 10 iterations over a 0.1-wide
    bracket resolve 1e-4, well inside DR 0006's 0.39 % tolerance."""
    assert ring_growth(cut, lo, compensated)[0] < 0, f"{cut} Hz already sustains at res {lo}"
    assert ring_growth(cut, hi, compensated)[0] > 0, f"{cut} Hz does not sustain at res {hi}"
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if ring_growth(cut, mid, compensated)[0] > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def sustained_tail(cut, res=1.05, dur=0.5, kick=3000.0, compensated=True):
    """Kick the filter once and let it sing; returns the last 60 % of the
    render -- the steady self-oscillation, well after the excitation."""
    n = int(dur * SR)
    n_kick = int(0.005 * SR)
    x = np.zeros(n, dtype=np.int16)
    x[:n_kick] = np.round(
        kick * np.sin(2 * math.pi * cut * np.arange(n_kick) / SR)).astype(np.int16)
    return ladder_render(x, cut, res, 1.0, compensated)[int(0.4 * n):]


def one_note(note=45, dur=0.5, **patch):
    """One note from reset through the whole voice; returns (out, trace)."""
    v = vf.VoiceFx()
    out = v.note(note, dur, **patch)
    return out, v.trace


# =============================================================================
# deliberately-wrong ladders: the negative controls of DR 0001's argument
# =============================================================================
class _LadderVariant(_REAL_LADDER):
    """A ladder that is NOT the model, for controls and comparisons.

    `stages`   how many one-poles are in the cascade (4 is the model)
    `nonlin`   'every'    tanh in every stage -- the model (DR 0001)
               'feedback' ONE saturating element, on the feedback signal, with
                          a hard-limited input stage and four LINEAR poles:
                          the Stilson & Smith shape DR 0001 rejected
               'input'    ONE tanh at the input stage, four linear poles

    This duplicates the model's inner loop (contract 11.4) with two knobs, so
    `test_the_negative_control_is_the_model_when_it_is_not_defective` checks it
    bit for bit against `LadderFx` in its non-defective setting. If that test
    goes red, this class has drifted and every comparison below is void.
    """

    def __init__(self, *a, stages=4, nonlin="every", **kw):
        super().__init__(*a, **kw)
        self.stages, self.nonlin = stages, nonlin

    def process(self, x_q15, cutoff_hz, res, drive=1.0, *, g_q16=None,
                k=None, gain=None, ogain=None, k_q14=None):
        from fixed import sat, shl
        os_, SQ, SB, OB = self.os, self.SQ, self.SB, self.OB
        n = len(x_q15)
        g_tab, k_tab, gain, ogain = self.coefficients(
            cutoff_hz, res, drive, g_q16=g_q16, n=n, k=k, gain=gain, ogain=ogain, k_q14=k_q14)
        k_per_sample = np.ndim(k_tab) > 0
        k = None if k_per_sample else int(k_tab)
        out = np.empty(n, dtype=np.int16 if OB <= 16 else np.int32)
        y, w = self.y, self.w
        d1, d2 = self.d1, self.d2
        TQ = SQ - 15
        S, nl = self.stages, self.nonlin
        for i in range(n):
            xi = int(x_q15[i])
            g = int(g_tab[i])
            if k_per_sample:
                k = int(k_tab[i])
            for _ in range(os_):
                fb = (d1 + d2) >> 1
                if nl == "feedback":
                    fb = shl(self.tanh_fx(fb), TQ)          # the one saturating element
                u = sat(shl(xi * gain, TQ - 16) - ((k * fb) >> 14), SB)
                w0 = self.tanh_fx(u) if nl != "feedback" else sat(shl(u, -TQ), 16)
                for s in range(S):
                    prev = w0 if s == 0 else w[s - 1]
                    diff = prev - w[s]
                    y[s] = sat(y[s] + ((g * shl(diff, TQ)) >> 16), SB)
                    w[s] = self.tanh_fx(y[s]) if nl == "every" else sat(shl(y[s], -TQ), 16)
                d2, d1 = d1, y[S - 1]
            out[i] = sat((shl(y[S - 1], -TQ) * ogain) >> 16, OB)
        self.y, self.w, self.d1, self.d2 = y, w, d1, d2
        return out


def test_the_negative_control_is_the_model_when_it_is_not_defective():
    """`_LadderVariant(stages=4, nonlin='every')` must be the model bit for
    bit. Every comparison in this file rests on that: a control that has
    drifted from the model measures the drift, not the structure."""
    n = int(0.2 * SR)
    x = np.round(0.9 * FS * np.sin(2 * math.pi * 220.0 * np.arange(n) / SR)).astype(np.int16)
    a = ladder_render(x, 3000, 0.8, 2.0, ladder=_REAL_LADDER(**vf.LADDER_CFG))
    b = ladder_render(x, 3000, 0.8, 2.0, ladder=_LadderVariant(**vf.LADDER_CFG))
    assert np.array_equal(a, b)


# =============================================================================
# 1. THE FILTER
# =============================================================================
ONSET_CUTS = [30, 200, 1600, 3000, 10000, 21600]


@pytest.mark.parametrize("cut", ONSET_CUTS)
def test_res_1_is_the_onset_of_self_oscillation_at_every_cutoff(cut):
    """**DR 0006, tolerance 0.39 %.** The compensation ROM exists so that the
    resonance knob means the same thing everywhere: `res = 1` is the edge of
    self-oscillation at 30 Hz and at 21.6 kHz alike. DR 0006's residual table
    gives a worst case of 0.39 % (at the 21.6 kHz clamp edge) and under 0.2 %
    elsewhere.

    Measured here by bisecting the sign of the free ring's growth on the
    fixed-point filter: 0.9984 at 30 Hz, 0.9985 at 200 Hz, 0.9983 at 1.6 kHz,
    0.9990 at 3 kHz, 0.9982 at 10 kHz, 0.9962 at 21.6 kHz.

    This is the ONSET only. The pitch it oscillates at is a separate property
    with its own error, and its own test below."""
    r = onset_res(cut)
    assert abs(r - 1.0) <= 0.0039, f"{cut} Hz: onset at res {r:.5f} ({(r-1)*100:+.3f} %)"


# f_osc / cutoff at the onset, DR 0006's own table. Locked here so the tuning
# error stays visible: it is open item 17.12, measured and NOT corrected.
TRACKING = {200: 0.979, 400: 0.984, 800: 0.990, 1600: 1.001, 3000: 1.020, 10000: 1.072}


def test_the_self_oscillation_pitch_tracks_the_cutoff_with_a_recorded_error():
    """**DR 0006's tracking table; DESIGN.md section 5; DR 0001 consequences.**

    The filter used as an oscillator has to play in tune with its cutoff. It
    does not, exactly, and the error is a recorded open item (contract 17.12),
    so this test locks the measured ratio rather than asserting the error away:
    each ratio must match DR 0006's table within 0.005.

    Two claims in the documentation are checked against it, and one of them is
    wrong:

      * DR 0001 and DESIGN.md say "+-2 % from 200 Hz to 1.6 kHz". Measured, the
        worst point in that band is 200 Hz at 0.9794 -- **2.06 % low, so the
        +-2 % claim is 0.06 pp optimistic at its own endpoint.** It holds from
        400 Hz up (1.64 % at 400 Hz), and that is asserted strictly.
      * DR 0006 says the error is "within 14 cents below 2 kHz". Measured, it
        is 14 cents only above about 1 kHz; at 200 Hz it is -36 cents and at
        30 Hz -57 cents.

    At 10 kHz the filter sings 7.2 % sharp. That is asserted as PRESENT, not
    as absent: DR 0006 fixes the onset, not the tuning."""
    ratios = {}
    for cut, expect in TRACKING.items():
        rate, tail = ring_growth(cut, onset_res(cut))
        f = am.zero_crossing_frequency(tail).require(f"the ring at {cut} Hz")
        ratios[cut] = f / cut
        assert abs(ratios[cut] - expect) < 0.005, \
            f"{cut} Hz: f_osc/cut {ratios[cut]:.4f}, DR 0006 says {expect}"
    # DESIGN.md's band, at the tolerance that actually holds
    band = [ratios[c] for c in (200, 400, 800, 1600)]
    assert max(abs(r - 1.0) for r in band) <= 0.021, band
    # ... and the +-2 % as claimed, from 400 Hz up
    assert max(abs(ratios[c] - 1.0) for c in (400, 800, 1600)) <= 0.020
    # the uncorrected high-cutoff error, asserted present (open item 17.12)
    assert 1.05 < ratios[10000] < 1.09, ratios[10000]


def test_it_still_self_oscillates_at_10_khz():
    """**DR 0006, the regression guard for the whole decision record.** Before
    the compensation ROM the filter would not sustain above about 3 kHz at a
    fixed `k = 4 res` -- DR 0001 recorded that as a consequence, and it is the
    defect DR 0006 was written to remove.

    At 10 kHz and `res = 1.05`, kicked once and then left alone: the tail is a
    sustained tone (rms 2966 LSB, peak-to-median 111 dB) within 8 % of the
    cutoff. Uncompensated, the same patch decays to rms 3 -- silence."""
    tail = sustained_tail(10000, res=1.05)
    assert am.rms(tail) > 500.0, f"rms {am.rms(tail):.1f}: not sustaining"
    assert am.tonality_db(tail) > 40.0, "sustaining, but not as a tone"
    f = am.dominant_frequency(tail, 5000.0, 20000.0).require("the 10 kHz whistle")
    assert 0.9 < f / 10000.0 < 1.12, f"{f:.0f} Hz at a 10 kHz cutoff"
    dead = sustained_tail(10000, res=1.05, compensated=False)
    assert am.rms(dead) < 50.0, f"uncompensated rms {am.rms(dead):.1f}: the ROM changed nothing"


def test_the_stopband_falls_at_24_db_per_octave():
    """**Four poles, contract 11.4: ~24 dB/octave.** Measured between 4x and 8x
    the cutoff, which is the band where a cascade of four scaled
    impulse-invariant one-poles is asymptotic (the ideal falls 23.3 dB there
    against the 24 dB asymptote, and only 21.2 dB between 2x and 4x) and is
    still far from Nyquist: with a 500 Hz cutoff the band is 2-4 kHz, i.e.
    2-4 % of the 96 kHz rate the filter runs at.

    Probed at res = 0 and drive 0.1 so the tanh is in its linear region.
    Measured: -48.57 dB at 2x, -70.02 at 4x, -93.67 at 8x -- 21.45 and
    23.65 dB/octave. Tolerance 21..26 dB/octave on the asymptotic band; a
    three-pole cascade measures 17.4 there, a five-pole 29, so the band
    separates a dropped stage by more than 3 dB."""
    cut = 500.0
    g2 = probe_gain_db(2 * cut, cut, 0.0, 0.1)
    g4 = probe_gain_db(4 * cut, cut, 0.0, 0.1)
    g8 = probe_gain_db(8 * cut, cut, 0.0, 0.1)
    assert 21.0 <= g4 - g8 <= 26.0, f"4x->8x {g4-g8:.2f} dB/oct (gains {g4:.2f}, {g8:.2f})"
    assert 19.5 <= g2 - g4 <= 23.5, f"2x->4x {g2-g4:.2f} dB/oct"


@pytest.mark.parametrize("cut,drive", [(8000, 3.0), (12000, 2.5)])
def test_the_nonlinearity_is_in_every_stage(cut, drive):
    """**DR 0001: "Anyone reimplementing this must not simplify to a single
    feedback-path tanh. That is a different filter, and the difference is the
    point." Tolerance: 5 dB on harmonics 6-10, DR 0001's own figure.**

    Driven hard, with the filter open and the resonance high, the linearised
    structure -- one saturating element on the feedback, a hard-limited input
    stage and four LINEAR poles -- flat-tops, and a flat top is high harmonics.
    Ours rounds over instead, because every stage's tanh compresses what the
    stage before it made. DR 0001 measured the linearised shape "5-8 dB hotter
    on harmonics 6-10"; at these operating points it is 30.6 dB and 37.8 dB
    hotter, so the direction reproduces and the margin is large.

    A pure tone in the bass register (110 Hz, A2), res 0.9, so that every
    partial in the output is the filter's own work. The stimulus that produced
    DR 0001's 5-8 dB is not in the repository, which is why the assertion is
    the DR's floor and not its exact number.

    What this does NOT show: that our filter matches a Moog ladder. It shows it
    is not the linearised alternative. Matching the circuit needs an
    independently derived response or a reference recording; we have neither."""
    f0, n = 110.0, int(0.5 * SR)
    x = np.round(0.95 * FS * np.sin(2 * math.pi * f0 * np.arange(n) / SR)).astype(np.int16)
    ours = ladder_render(x, cut, 0.9, drive, ladder=_REAL_LADDER(**vf.LADDER_CFG))
    lin = ladder_render(x, cut, 0.9, drive,
                        ladder=_LadderVariant(nonlin="feedback", **vf.LADDER_CFG))
    h_ours = am.harmonic_powers(ours, f0, range(6, 11)).sum() / am.harmonic_powers(ours, f0, [1])[0]
    h_lin = am.harmonic_powers(lin, f0, range(6, 11)).sum() / am.harmonic_powers(lin, f0, [1])[0]
    hotter = 10 * math.log10(h_lin / h_ours)
    assert hotter >= 5.0, (f"the linearised structure is only {hotter:.1f} dB hotter on "
                           f"harmonics 6-10 (ours {10*math.log10(h_ours):.1f} dB, "
                           f"linearised {10*math.log10(h_lin):.1f} dB)")


def test_driving_it_thickens_where_the_linearised_structure_flat_tops():
    """**DR 0001: "Driving it brightens; driving the real structure thickens."**

    The structural reason, measured as a level. Each stage integrates toward
    `tanh(y) = prev`, so as the drive rises the state keeps climbing (atanh
    diverges) and the waveform rounds over: peak output 0.63 -> 1.56 x full
    scale from drive 1 to 6, +7.9 dB. The linearised structure's state is
    pinned by its one limiter, so its output stops dead at 0.615 x full scale
    and every further dB of drive becomes harmonics instead of level: its peak
    at drive 6 is the same number as at drive 1, to the LSB.

    Tolerance: ours must grow by at least 4 dB over that range, theirs by less
    than 0.5 dB. res 0.3, cutoff 8 kHz, a 110 Hz tone at 0.95 full scale."""
    f0, n = 110.0, int(0.25 * SR)
    x = np.round(0.95 * FS * np.sin(2 * math.pi * f0 * np.arange(n) / SR)).astype(np.int16)

    def peak_at(drive, ladder):
        return am.peak(ladder_render(x, 8000, 0.3, drive, ladder=ladder)) / FS

    lo_ours = peak_at(1.0, _REAL_LADDER(**vf.LADDER_CFG))
    hi_ours = peak_at(6.0, _REAL_LADDER(**vf.LADDER_CFG))
    lo_lin = peak_at(1.0, _LadderVariant(nonlin="feedback", **vf.LADDER_CFG))
    hi_lin = peak_at(6.0, _LadderVariant(nonlin="feedback", **vf.LADDER_CFG))
    assert 20 * math.log10(hi_ours / lo_ours) > 4.0, (lo_ours, hi_ours)
    assert 20 * math.log10(hi_lin / lo_lin) < 0.5, (lo_lin, hi_lin)


def test_resonance_lifts_a_peak_at_the_cutoff():
    """**Contract 11.5 / DR 0006: the resonance control is a resonance.**
    Probed at the cutoff and a decade below it, at res 0, 0.3, 0.6 and 0.9.
    The peak above the passband rises monotonically -12.2, -2.8, +4.6,
    +10.4 dB: a 22.6 dB swing across the knob. Tolerances: monotone, at most
    -10 dB at res 0 (no peak at all) and at least +8 dB at res 0.9."""
    cut, drive = 500.0, 0.1
    peaks = []
    for res in (0.0, 0.3, 0.6, 0.9):
        low = probe_gain_db(0.1 * cut, cut, res, drive)
        at = probe_gain_db(cut, cut, res, drive)
        peaks.append(at - low)
    assert all(b > a + 2.0 for a, b in zip(peaks, peaks[1:])), peaks
    assert peaks[0] <= -10.0, peaks
    assert peaks[-1] >= 8.0, peaks


def test_the_passband_compensation_is_partial_and_is_the_one_in_the_contract():
    """**DR 0005 item 5 and contract 11.5: `ogain`'s `(1 + 2 res)` term is a
    PARTIAL passband-loss compensation** -- what the audition heard, not a
    flat response. The ladder's passband loses `1/(1 + 4 res)`; `ogain` gives
    back `(1 + 2 res)`, so the net is `(1 + 2 res)/(1 + 4 res)`.

    Probed a decade below a 500 Hz cutoff, relative to res = 0:

        res    measured    (1+2r)/(1+4r)   uncompensated 1/(1+4r)
        0.25   -2.30 dB      -2.50 dB          -6.02 dB
        0.50   -3.34         -3.52             -9.54
        0.75   -3.92         -4.08            -12.04
        1.00   -4.29         -4.44            -13.98

    Tolerance 0.5 dB against the closed form, which also refutes the
    uncompensated law by 9 dB at res = 1."""
    cut, drive = 500.0, 0.1
    ref = probe_gain_db(0.1 * cut, cut, 0.0, drive)
    for res in (0.25, 0.5, 0.75, 1.0):
        got = probe_gain_db(0.1 * cut, cut, res, drive) - ref
        want = 20 * math.log10((1 + 2 * res) / (1 + 4 * res))
        assert abs(got - want) < 0.5, f"res {res}: {got:.2f} dB, closed form {want:.2f} dB"
        uncomp = 20 * math.log10(1.0 / (1 + 4 * res))
        assert got > uncomp + 2.0, f"res {res}: no compensation is visible"


def test_opening_the_cutoff_makes_a_note_brighter():
    """**Acceptance, not diagnosis.** The cutoff control has to do the one
    thing a player expects: open it and the note gets brighter. Measured on
    the finished voice as a POWER-weighted spectral centroid, which is an
    ordering of brightness and NOT a measurement of the cutoff -- it moves
    with the excitation, the envelope and the nonlinearity as well (amplitude
    weighting would give a number four times larger and equally meaningless).
    The filter itself is measured with a probe, above.

    A held saw at 110 Hz, res 0.3, no tracking, filter envelope pinned open:
    105, 134, 162, 195, 233 Hz for cutoffs 300..4800. Tolerance: strictly
    increasing, and at least 1.5 x from end to end."""
    cents = []
    for cut in (300, 600, 1200, 2400, 4800):
        out, _ = one_note(45, 0.5, waves=("saw",), detune=(0.0,), mix=(1.0,),
                          cutoff=(cut, cut), q=0.3, drive=1.0, track=0.0,
                          amp=(0.005, 0.1, 1.0, 0.05), fenv=(0.001, 0.01, 1.0, 0.01),
                          gate=0.45)
        seg = out[int(0.1 * SR):int(0.4 * SR)].astype(np.float64)
        assert am.rms(seg) > 100.0, f"cutoff {cut}: the note is inaudible, nothing is proved"
        cents.append(am.spectral_centroid(seg, weight="power"))
    assert all(b > a for a, b in zip(cents, cents[1:])), cents
    assert cents[-1] / cents[0] > 1.5, cents


# =============================================================================
# 2. THE OSCILLATORS
# =============================================================================
def _osc(shape, note, n, blep=True):
    inc = dsp.phase_inc(dsp.note_hz(note))
    f0 = inc * SR / (1 << 24)
    return vf.OscFx(shape, blep).render(n, inc).astype(np.float64) / FS, f0


@pytest.mark.parametrize("note", [40, 64, 88])
@pytest.mark.parametrize("shape", ["saw", "square"])
def test_polyblep_suppresses_aliasing_at_every_register(shape, note):
    """**DR 0001's table, tolerance 14 dB (measured ~16).** Inharmonic energy
    was the largest defect in the survey that chose the filter -- -27.7 dB at
    note 40 and -14.8 dB at note 88 for a naive saw -- and PolyBLEP was adopted
    to remove about 16 dB of it uniformly.

    Measured with DR 0001's own estimator (energy outside +-5 bins of every
    harmonic, as a fraction of total), so the numbers compare directly:

        note 40  saw -27.9 -> -43.0 (15.0 dB)   square -29.5 -> -44.5 (15.0)
        note 64  saw -20.8 -> -36.6 (15.9 dB)   square -22.5 -> -38.2 (15.7)
        note 88  saw -14.8 -> -31.0 (16.2 dB)   square -16.5 -> -32.1 (15.7)

    All are at least 10 dB above the estimator's own -54 dB leakage floor."""
    n = int(0.5 * SR)
    naive, f0 = _osc(shape, note, n, blep=False)
    blep, _ = _osc(shape, note, n, blep=True)
    a = am.inharmonic_fraction_db(naive, f0).require(f"{shape} note {note}, naive")
    b = am.inharmonic_fraction_db(blep, f0).require(f"{shape} note {note}, PolyBLEP")
    assert a - b >= 14.0, f"{shape} note {note}: naive {a:.1f}, PolyBLEP {b:.1f}"
    assert b < -28.0, f"{shape} note {note}: PolyBLEP leaves {b:.1f} dB"


@pytest.mark.parametrize("note", [64, 88])
def test_polyblep_removes_the_predicted_fold_back_images(note):
    """The same property measured where the aliases actually are, rather than
    by exclusion: every harmonic above Nyquist images at a computable
    frequency, and only those bins are read (`audio_measure.foldback_alias_db`,
    ground truth: a planted image of known energy is recovered to 0.8 dB).

        note 64  saw -21.0 -> -36.7 (15.6 dB), 800 image bins, no collisions
        note 88  saw -15.2 -> -31.0 (15.8 dB), 199 image bins, no collisions

    Note 40 is deliberately absent: there the images are dense enough to
    collide with real harmonics and the estimator refuses the measurement
    (test_foldback_refuses_a_low_note_where_the_images_are_dense). The test
    above covers note 40 with the complementary measure."""
    n = 1 << 15
    naive, f0 = _osc("saw", note, n, blep=False)
    blep, _ = _osc("saw", note, n, blep=True)
    ea, eb = am.foldback_alias_db(naive, f0), am.foldback_alias_db(blep, f0)
    a = ea.require(f"note {note}, naive")
    b = eb.require(f"note {note}, PolyBLEP")
    assert ea.detail["images"] > 50 and ea.detail["collided"] == 0, ea
    assert a - b >= 14.0, f"note {note}: naive {a:.1f}, PolyBLEP {b:.1f}, {ea.detail}"


def test_the_squares_correction_has_the_opposite_sign_to_the_saws():
    """**DESIGN.md section 6 / contract 6.4: a square steps UP at the wrap
    where a saw steps DOWN, and getting it backwards measures worse than no
    correction at all.** Tolerance: the square must beat naive by 14 dB at
    every register (measured 15.0 / 15.7 / 15.7); inverted it measures 0.0 dB
    of improvement, i.e. the correction buys nothing -- which is the injected
    defect in the last group."""
    n = int(0.5 * SR)
    for note in (40, 64, 88):
        naive, f0 = _osc("square", note, n, blep=False)
        blep, _ = _osc("square", note, n, blep=True)
        a = am.inharmonic_fraction_db(naive, f0).require(f"square {note}, naive")
        b = am.inharmonic_fraction_db(blep, f0).require(f"square {note}, corrected")
        assert a - b >= 14.0, f"note {note}: naive {a:.1f}, corrected {b:.1f}"


def test_the_waveforms_are_the_shapes_the_contract_names():
    """**Contract 6.4, a property of the SHAPE, separate from aliasing.** Each
    naive waveform's harmonic series is what its name means, at 110 Hz:

        saw       every harmonic, falling 1/k          h2 -6.0, h3 -9.5 dB
        square    odd harmonics only, falling 1/k      h2 below -60 dB
        tri       odd harmonics only, falling 1/k^2    h3 -19.1, h5 -28.0 dB
        pulse25   a null at every 4th harmonic         h4 below -60 dB
        sine      no harmonic above -80 dB

    Tolerance 1 dB on the present partials, 60 dB of rejection on the absent
    ones. This catches a shape wired to the wrong formula, a duty cycle that
    is not 50 % or 25 %, and a sine table read with the wrong symmetry."""
    n = 1 << 15
    f0 = dsp.phase_inc(110.0) * SR / (1 << 24)

    def rel_db(shape, ks):
        x, _ = _osc(shape, 45, n, blep=False)
        p = am.harmonic_powers(x, f0, [1] + list(ks))
        return 10 * np.log10(p[1:] / p[0])

    saw = rel_db("saw", [2, 3, 4, 5])
    for i, k in enumerate((2, 3, 4, 5)):
        assert abs(saw[i] - 20 * math.log10(1.0 / k)) < 1.0, ("saw", k, saw[i])
    sq = rel_db("square", [2, 3, 4, 5])
    assert sq[0] < -60.0 and sq[2] < -60.0, sq          # even harmonics absent
    assert abs(sq[1] - 20 * math.log10(1 / 3)) < 1.0 and abs(sq[3] - 20 * math.log10(1 / 5)) < 1.0
    tri = rel_db("tri", [2, 3, 5])
    assert tri[0] < -60.0, tri
    assert abs(tri[1] - 20 * math.log10(1 / 9)) < 1.0, tri
    assert abs(tri[2] - 20 * math.log10(1 / 25)) < 1.5, tri
    p25 = rel_db("pulse25", [2, 3, 4])
    assert p25[2] < -60.0, p25                          # null at the 4th
    assert abs(p25[0] - 20 * math.log10(math.sin(math.pi / 2) / 2
                                        / math.sin(math.pi / 4))) < 1.0, p25
    sine = rel_db("sine", [2, 3, 4, 5, 6, 7])
    assert sine.max() < -80.0, sine


# =============================================================================
# 3. THE VOICE
# =============================================================================
def _glide_incs(a, b, dur=1.0, **kw):
    v = vf.VoiceFx()
    v.run(v.note_on(b, dur, glide_from=a, waves=("saw",), detune=(0.0,), mix=(1.0,), **kw))
    seq = v.trace["incs"][0].astype(np.float64)
    land = int(np.argmax(seq == seq[-1]))
    assert 0 < land < len(seq), "the glide never landed"
    return seq, land


def test_the_glide_is_geometric_and_at_a_constant_rate():
    """**DR 0004: constant rate, linear in pitch, 90 ms per octave +-1 %.**
    The Minimoog's panel control is a RATE ("the further to the right ... the
    longer it will take a tone to move from one pitch to the next"), and the
    reissue specifies it per octave; Moog's and Sequential's current
    instruments default to the same law. So a two-octave glide must take twice
    as long as a one-octave one, and the trajectory must be a straight line in
    log-frequency, not in Hz.

    Measured: one octave 90.0 ms, two octaves 180.1 ms (2.00 x), down the same
    as up; the deviation from a straight line in log2(inc) is 0.097 cents over
    the whole glide, while the best straight line in Hz misses by 593 cents.

    This is OUR specified behaviour, recorded in DR 0004 as a design decision
    with its evidence; it is not to be "fixed" toward some other instrument's
    constant-time law, which remains available as a host policy."""
    one_up, land1 = _glide_incs(52, 64)
    two_up, land2 = _glide_incs(40, 64)
    _, land_dn = _glide_incs(64, 52)
    assert abs(land1 / SR / vf.GLIDE_REF_S - 1.0) < 0.01, land1 / SR
    assert abs(land2 / land1 - 2.0) < 0.02, (land1, land2)
    assert abs(land_dn / land1 - 1.0) < 0.02, (land1, land_dn)

    t = np.arange(land2)
    A = np.vstack([t, np.ones(land2)]).T
    lg = np.log2(two_up[:land2])
    fit_log, *_ = np.linalg.lstsq(A, lg, rcond=None)
    cents_log = 1200.0 * np.abs(lg - A @ fit_log).max()
    fit_hz, *_ = np.linalg.lstsq(A, two_up[:land2], rcond=None)
    cents_hz = 1200.0 * np.abs(np.log2(np.maximum(A @ fit_hz, 1.0) / two_up[:land2])).max()
    assert cents_log < 1.0, f"not linear in pitch: {cents_log:.2f} cents off a straight line"
    assert cents_hz > 100.0, f"indistinguishable from a linear-in-Hz glide ({cents_hz:.1f} cents)"


def test_a_high_resonance_note_reaches_exactly_zero_after_its_release():
    """**DR 0005 item 3, tolerance: exactly zero.** The audition applied the
    amplitude envelope BEFORE the filter. With one continuous voice that means
    a self-oscillating patch never ends -- the envelope closes the filter's
    input and the filter keeps singing; measured then at 0.41 x full scale
    half a second after the last gate-off. The VCA is now after the filter, so
    the note ends when the VCA closes, whatever the filter is doing.

    A 600 Hz sine patch at res 1.06, gate off at 0.4 s: the ladder is still
    ringing at 9758 LSB at 1.2 s and the output is exactly 0 -- not small,
    zero -- from the frame the amplitude envelope reaches 0 (contract 8.3's
    `max(1, .)` floor is what makes it reach 0 at all).

    Also the acceptance question behind it: nothing audible after gate-off, no
    DC, no limit cycle at the output."""
    regs = vf.VoiceFx.patch_regs(waves=("sine",), detune=(0.0,), mix=(1.0,),
                                 cutoff=(600, 600), q=1.06, drive=0.5, track=0.0,
                                 amp=(0.005, 0.1, 0.8, 0.05))
    v = vf.VoiceFx()
    gate_off = int(0.4 * SR)
    writes = [(0, "INC", 0, dsp.phase_inc(600.0), True), (0, "GATE", 1), (gate_off, "GATE", 0)]
    out = v.play(regs, writes, int(1.2 * SR))
    ladder, ae = v.trace["ladder"], v.trace["amp_env"]
    assert am.peak(ladder[-int(0.2 * SR):]) > 3000.0, "the filter is not singing; nothing is proved"
    silent = gate_off + int(np.argmax(ae[gate_off:] == 0))
    assert silent > gate_off, "the amplitude envelope never reached zero"
    assert np.all(out[silent:] == 0), \
        f"note does not end: peak {am.peak(out[silent:])} LSB after the envelope closed"
    assert float(np.mean(out[silent:].astype(np.float64))) == 0.0


def test_nothing_clips_at_the_reference_gain_structure():
    """**DR 0005 and contract 12, tolerance: zero samples.** The chain has
    exactly six clamps and at the reference `vol = 0.45` none of the
    undesigned ones fires on any of the eight audition patches. Measured per
    patch (each render analysed as its own event):

        clamp 2  mixer sum sat16        peak |acc >> 15| = 32767, never over
        clamp 5  ladder output sat19    peak 1.94 x full scale (growl-bass),
                                        against the word's 8.0
        clamp 6  output sat16           0 samples at `vol` 0.45; at rev 1's
                                        0.9, growl-bass clips 4.8 %

    The designed saturation -- the ladder's tanh -- is a separate test."""
    import patches
    worst_ladder, worst_out = 0.0, 0.0
    for name, seq, total in patches.MONO:
        v = vf.VoiceFx()
        out = vf.render_mono_fx(seq, total, v)
        t = v.trace
        acc = sum(o * int(w) for o, w in zip(t["osc"], v.weights))
        assert np.abs(acc >> 15).max() <= 32767, f"{name}: the mixer saturates"
        assert np.abs(t["ladder"]).max() < (1 << 18), f"{name}: the ladder output word saturates"
        pre_rail = (t["vca"] * v.vol) >> 15
        assert np.abs(pre_rail).max() <= 32767, f"{name}: the output rail fires"
        assert np.abs(out).max() < 32767, f"{name}: the output reaches full scale"
        worst_ladder = max(worst_ladder, np.abs(t["ladder"]).max() / FS)
        worst_out = max(worst_out, np.abs(out).max() / FS)
        # rev 1's volume is the control: it must still clip, or the patch set has changed
        if name.startswith("07"):
            assert np.mean(np.abs((t["vca"] * 29491) >> 15) > 32767) > 0.03, name
    assert 1.5 < worst_ladder < 2.5, worst_ladder
    assert 0.8 < worst_out < 0.95, worst_out


def test_the_drive_control_engages_the_ladders_saturation():
    """**DR 0005 item 1: the designed saturation is the ladder's tanh, driven
    by `gain`.** The other side of the clipping test -- nothing clips, but the
    thing that is supposed to distort must distort.

    A pure tone through the filter at res 0.2, cutoff 4 kHz. Distortion (all
    partials above the first, relative to the first) against the drive
    control: -73.8 dB at 0.05, -86.2 at 0.2, -37.2 at 0.45, -12.8 at the
    reference patch's 1.6, -9.5 at 3.0. And the level compresses as it does
    it: 60 x the drive buys 21 dB of output, not 36.

    The two lowest drives are AT THE MODEL'S TRUNCATION FLOOR, not on a
    distortion curve -- the output there is a few hundred LSB and the reading
    depends on where truncation noise lands, which is why -86 dB sits below
    -74 dB. So the monotone assertion covers only the engaged region
    (0.45 upward) and the low end is asserted as "clean", which is all the
    measurement supports.

    Tolerances: below -60 dB at drive 0.05 and 0.2 (clean), above -20 dB at
    drive 1.6 (the drive control does something), monotone from 0.45 up with
    at least 20 dB between 0.45 and 3.0, and at least 10 dB of level
    compression from drive 0.1 to 6."""
    f0, n = 220.0, int(0.3 * SR)
    x = np.round(0.9 * FS * np.sin(2 * math.pi * f0 * np.arange(n) / SR)).astype(np.int16)

    def thd_db(drive):
        y = ladder_render(x, 4000, 0.2, drive)[int(0.05 * SR):]
        p = am.harmonic_powers(y, f0, range(1, 40))
        return 10 * math.log10(p[1:].sum() / p[0])

    thd = [thd_db(d) for d in (0.05, 0.2, 0.45, 1.6, 3.0)]
    assert thd[0] < -60.0 and thd[1] < -60.0, thd
    assert thd[3] > -20.0, thd
    assert all(b > a for a, b in zip(thd[2:], thd[3:])), thd
    assert thd[4] - thd[2] > 20.0, thd
    lo = am.peak(ladder_render(x, 4000, 0.2, 0.1))
    hi = am.peak(ladder_render(x, 4000, 0.2, 6.0))
    growth = 20 * math.log10(hi / lo)
    assert growth < 20 * math.log10(60.0) - 10.0, f"no compression: {growth:.1f} dB for 35.6 dB of drive"


@pytest.mark.parametrize("release", [0.02, 0.12, 0.5, 1.0])
def test_the_envelope_release_reaches_zero_and_does_not_stair_step(release):
    """**Contract 8.3 and DESIGN.md section 4, tolerances: exactly zero, and a
    floor below -62 dBFS up to a 1 s release.**

    `L -= max(1, (L*rate) >> 16)`. The `max(1, .)` is load-bearing: without it
    the shifted product truncates to zero below `2^16/rate` and the note never
    ends. With it the release is exponential down to that floor and then walks
    to zero at 1 LSB per frame.

    Measured on the 24-bit level: strictly decreasing at every frame above the
    floor, the frame-to-frame ratio constant to 2.1e-3 at the shortest release
    and 4e-5 at the longest (it IS an exponential, not a staircase, and the
    spread is the level's own quantisation near the floor), reaching exactly
    0 at 53 ms / 321 ms / 1.17 s / 2.37 s,
    with the floor at -96.9 / -81.2 / -69.0 / -62.1 dBFS. 24 bits is chosen so
    that the last figure stays under the 16-bit noise floor; at 16 bits the
    same release turns linear at -14 dBFS, which is the staircase this test
    exists to catch."""
    env = vf.AdsrFx(0.005, 0.1, 1.0, release)
    env.render(int(0.3 * SR), int(0.3 * SR))                 # hold at sustain
    level = env.render(int(4 * SR), 0, q=env.EB)             # the 24-bit level per frame
    assert (level == 0).any(), "the release never reaches zero"
    floor_db = 20 * math.log10(env.floor_level / (1 << env.EB))
    assert floor_db < -62.0, f"the exponential gives out at {floor_db:.1f} dBFS"
    above = level[level > env.floor_level]
    assert len(above) > 100
    assert np.all(np.diff(above) < 0), "the release stalls"
    assert am.longest_plateau(above) == 1
    ratio = above[1:] / above[:-1]
    assert ratio.max() - ratio.min() < 3e-3, "the release is not an exponential"


def test_a_cutoff_jump_mid_note_does_not_click():
    """**Contract 4.3 and 10.1: a control write takes effect at a frame
    boundary, and nothing else about the voice restarts.**

    An instantaneous 16 x cutoff write is a legitimate level change -- there is
    no smoothing in the contract and none is claimed -- so the property is not
    "no step" but "no step the signal does not already have": the sample-to-
    sample jump at the write must not exceed the largest ordinary jump on
    either side of it. A transient, a state reset or a re-attack would exceed
    both. Measured: 2294 LSB at the write, against 336 LSB before (filter shut)
    and 5307 LSB after (filter open) -- the write is quieter than the waveform
    it lands in.

    Then the continuous case, which is where a zipper would live: the fastest
    filter envelope the registers allow (1 ms attack, 5 ms decay) sweeps the
    cutoff every frame from 200 Hz to 8 kHz, and no sample step may exceed
    8000 LSB.

    Then the resonance, which `play` cannot write mid-note but the chip
    modulates per frame: `k_eff` stepped between 0 and the onset every 5 ms
    for half a second must stay inside the 19-bit output word, with no step
    beyond the signal's own."""
    regs = vf.VoiceFx.patch_regs(waves=("saw",), detune=(0.0,), mix=(1.0,),
                                 cutoff=(400, 400), q=0.7, drive=1.6, track=0.0,
                                 amp=(0.005, 0.2, 1.0, 0.1), fenv=(0.001, 0.01, 1.0, 0.01))
    v = vf.VoiceFx()
    at = int(0.25 * SR)
    out = v.play(regs, [(0, "INC", 0, dsp.phase_inc(110.0), True), (0, "GATE", 1),
                        (at, "TRACK", 6000)], int(0.5 * SR)).astype(np.float64)
    before = am.max_sample_step(out[at - 400:at - 1])
    after = am.max_sample_step(out[at + 200:at + 600])
    at_write = abs(out[at] - out[at - 1])
    assert at_write <= 1.2 * max(before, after), \
        f"click at the write: {at_write:.0f} LSB against {before:.0f} before, {after:.0f} after"

    fast, _ = one_note(45, 0.4, waves=("saw",), detune=(0.0,), mix=(1.0,),
                       cutoff=(200, 8000), q=0.8, drive=1.6, track=0.0,
                       fenv=(0.001, 0.005, 0.2, 0.05))
    env = am.analytic_envelope(fast.astype(np.float64))
    steps = np.abs(np.diff(fast.astype(np.float64)))
    assert steps.max() < 8000.0, f"zipper on the fastest filter envelope: {steps.max():.0f} LSB"
    assert am.peak(env) > 1000.0, "the note is too quiet to prove anything"

    n = int(0.5 * SR)
    saw = vf.OscFx("saw").render(n, dsp.phase_inc(110.0)).astype(np.int16)
    g, k_on, gain, ogain = _ladder_regs(1.0, 1.6, 1200)
    square = (np.arange(n) // int(0.005 * SR)) % 2
    k_mod = np.where(square, k_on, 0).astype(np.int64)
    lad = vf.LadderFx(**vf.LADDER_CFG)
    y = lad.process(saw, None, 1.0, 1.6, g_q16=np.full(n, g, dtype=np.int64),
                    gain=gain, ogain=ogain, k_q14=k_mod).astype(np.float64)
    assert am.peak(y) < (1 << 18), f"a stepped resonance reaches the output word: {am.peak(y)}"
    assert am.max_sample_step(y) < 4.0 * np.abs(np.diff(y)).mean() * 20.0, "resonance steps click"


# =============================================================================
# 4. THE SUITE CAN FAIL
#
# Every property above is green. `docs/verification-rules.md` rule 2: that
# means nothing until each control has been shown to turn it red. Each test
# here injects one defect INTO THE MODEL and requires the property that covers
# it to fail -- the four defects the rules name as most likely to be silently
# wrong, plus a dropped pole and an all-silent stub.
# =============================================================================
def _expect_red(fn, *a, **kw):
    """Run a property check and require it to fail. A defect that leaves the
    property green is a hole in the suite, and this reports it as one."""
    with pytest.raises(AssertionError) as e:
        fn(*a, **kw)
    return str(e.value)


def test_control_removing_the_resonance_compensation(monkeypatch):
    """Defect: `k_eff = k`, the rev-1 filter with no compensation ROM
    (DR 0006). The filter must then stop sustaining above ~3 kHz, and
    test_it_still_self_oscillates_at_10_khz must go red."""
    monkeypatch.setattr(vf, "k_effective", lambda k, kc: np.asarray(k, dtype=np.int64))
    msg = _expect_red(test_it_still_self_oscillates_at_10_khz)
    assert "not sustaining" in msg or "ROM changed nothing" in msg
    # and the onset moves far outside DR 0006's 0.39 %
    _expect_red(test_res_1_is_the_onset_of_self_oscillation_at_every_cutoff, 10000)


def test_control_inverting_the_squares_polyblep_sign(monkeypatch):
    """Defect: the square's correction with the saw's sign (DESIGN.md section
    6). The improvement over naive collapses from 15 dB to 0."""
    real = vf.blep_fx
    monkeypatch.setattr(vf, "blep_fx", lambda *a, **kw: -real(*a, **kw))
    n = int(0.5 * SR)
    naive, f0 = _osc("square", 88, n, blep=False)
    broken, _ = _osc("square", 88, n, blep=True)
    gain = (am.inharmonic_fraction_db(naive, f0).require()
            - am.inharmonic_fraction_db(broken, f0).require())
    assert gain < 1.0, f"the inverted correction still buys {gain:.1f} dB"
    _expect_red(test_the_squares_correction_has_the_opposite_sign_to_the_saws)


class _NoFloorAdsr(vf.AdsrFx):
    """Defect: contract 8.3's release without its `max(1, .)`."""

    def render(self, n, gate, trig=None, q=15):
        out = np.empty(n, dtype=np.int64)
        gate_a = ((np.arange(n) < int(gate)).astype(np.int64) if np.ndim(gate) == 0
                  else np.asarray(gate, dtype=np.int64))
        trig_a = None if trig is None else np.asarray(trig, dtype=np.int64)
        L, seg = self.level, self.seg
        sh = self.EB - q
        for i in range(n):
            if trig_a is not None and trig_a[i]:
                seg = self.ATTACK
            out[i] = L >> sh
            if gate_a[i]:
                if seg == self.ATTACK:
                    L += self.a_inc
                    if L >= self.full:
                        L, seg = self.full, self.DECAY
                elif seg == self.DECAY:
                    L -= self.d_dec
                    if L <= self.sus:
                        L, seg = self.sus, self.SUSTAIN
                else:
                    L = self.sus
            else:
                L -= (L * self.rate) >> self.RQ          # the floor, removed
                if L < 0:
                    L = 0
        self.level, self.seg = L, seg
        return out


def test_control_removing_the_envelope_release_floor(monkeypatch):
    """Defect: no `max(1, .)` in the release. The level stalls at
    `2^16/rate - 1` and the note never ends -- which is exactly what the
    'a note ends' property is for."""
    monkeypatch.setattr(vf, "AdsrFx", _NoFloorAdsr)
    env = vf.AdsrFx(0.005, 0.1, 1.0, 0.12)
    env.render(int(0.3 * SR), int(0.3 * SR))
    assert not (env.render(int(4 * SR), 0, q=env.EB) == 0).any(), "the defect does not stall"
    _expect_red(test_a_high_resonance_note_reaches_exactly_zero_after_its_release)
    _expect_red(test_the_envelope_release_reaches_zero_and_does_not_stair_step, 0.12)


def _render_vca_before_filter(self, incs, track, gate, trig, n):
    """Defect: the auditioned chain order -- amplitude envelope applied to the
    mixer output, ahead of the ladder (DR 0005's rejected alternative)."""
    sig = [o.render(n, inc) for o, inc in zip(self.oscs, incs)]
    mixed = vf.mix_fx(sig, self.weights)
    ae = self.amp_env.render(n, gate, trig)
    fe = self.filt_env.render(n, gate, trig)
    span = self.cut_hi - self.cut_lo
    cut = np.clip(self.cut_lo + ((span * fe) >> 15) + track, vf.CUT_MIN, vf.CUT_MAX)
    kc = vf.kc_from_cut(cut, self.k_rom, self.KB)
    k_eff = vf.k_effective(self.k_reg, kc) if self.k_comp else np.full(n, self.k_reg, dtype=np.int64)
    g = vf.g_from_cut(cut, self.g_rom, self.GB)
    pre = vf.sat16((mixed * ae) >> 15).astype(np.int16)          # the VCA, before the filter
    y = self.ladder.process(pre, None, self.res, self.drive, g_q16=g,
                            k=self.k_reg, gain=self.gain, ogain=self.ogain, k_q14=k_eff)
    y = y.astype(np.int64)
    out = vf.sat16((y * self.vol) >> 15)
    self.trace = dict(osc=sig, mixed=mixed, amp_env=ae, filt_env=fe, cut=cut, g=g,
                      kc=kc, k_eff=k_eff, ladder=y, vca=y, incs=incs, gate=gate, trig=trig)
    return out.astype(np.int16)


def test_control_moving_the_vca_before_the_filter(monkeypatch):
    """Defect: the audition's chain order. A self-oscillating patch then never
    ends -- the envelope closes the filter's input and the filter keeps
    singing -- which is the measurement DR 0005 was written from."""
    monkeypatch.setattr(vf.VoiceFx, "_render", _render_vca_before_filter)
    _expect_red(test_a_high_resonance_note_reaches_exactly_zero_after_its_release)


class _ThreePoleLadder(_LadderVariant):
    """Defect: a stage dropped from the cascade (contract 11.4)."""

    def __init__(self, *a, **kw):
        kw.pop("stages", None)
        super().__init__(*a, stages=3, **kw)


def test_control_dropping_a_pole(monkeypatch):
    """Defect: three one-poles instead of four. The stopband then falls at
    17.4 dB/octave instead of 23.7, which is what the slope property is for."""
    monkeypatch.setattr(vf, "LadderFx", _ThreePoleLadder)
    _expect_red(test_the_stopband_falls_at_24_db_per_octave)


class _SilentLadder(_REAL_LADDER):
    def process(self, x_q15, *a, **kw):
        return np.zeros(len(x_q15), dtype=np.int32)


class _SilentOsc(vf.OscFx):
    def render(self, n, inc):
        return np.zeros(n, dtype=np.int64)


class _SilentVoice(vf.VoiceFx):
    def _render(self, incs, track, gate, trig, n):
        self.trace = dict(osc=[np.zeros(n, dtype=np.int64) for _ in self.oscs],
                          mixed=np.zeros(n, dtype=np.int64),
                          amp_env=np.zeros(n, dtype=np.int64),
                          filt_env=np.zeros(n, dtype=np.int64),
                          cut=np.full(n, self.cut_lo, dtype=np.int64), g=None,
                          kc=np.zeros(n, dtype=np.int64), k_eff=np.zeros(n, dtype=np.int64),
                          ladder=np.zeros(n, dtype=np.int64), vca=np.zeros(n, dtype=np.int64),
                          incs=incs, gate=gate, trig=trig)
        return np.zeros(n, dtype=np.int16)


def test_control_a_silent_stub_passes_nothing(monkeypatch):
    """The anti-vacuous-pass control, `docs/verification-rules.md` rule 1: a
    model with the right ports and no behaviour must fail every property, not
    pass any of them by default. The estimators refuse a silent record
    (`InsufficientEvidence`, itself an AssertionError) rather than returning a
    plausible number, so each of these goes red for a stated reason."""
    monkeypatch.setattr(vf, "LadderFx", _SilentLadder)
    monkeypatch.setattr(vf, "OscFx", _SilentOsc)
    monkeypatch.setattr(vf, "VoiceFx", _SilentVoice)
    checks = [
        (test_res_1_is_the_onset_of_self_oscillation_at_every_cutoff, (200,)),
        (test_it_still_self_oscillates_at_10_khz, ()),
        (test_the_stopband_falls_at_24_db_per_octave, ()),
        (test_resonance_lifts_a_peak_at_the_cutoff, ()),
        (test_the_passband_compensation_is_partial_and_is_the_one_in_the_contract, ()),
        (test_opening_the_cutoff_makes_a_note_brighter, ()),
        (test_polyblep_suppresses_aliasing_at_every_register, ("saw", 64)),
        (test_polyblep_removes_the_predicted_fold_back_images, (88,)),
        (test_the_squares_correction_has_the_opposite_sign_to_the_saws, ()),
        (test_the_waveforms_are_the_shapes_the_contract_names, ()),
        (test_the_drive_control_engages_the_ladders_saturation, ()),
        (test_a_cutoff_jump_mid_note_does_not_click, ()),
    ]
    for fn, args in checks:
        _expect_red(fn, *args)


def test_control_a_silent_stub_is_not_mistaken_for_a_note_that_ended(monkeypatch):
    """The one property a silent stub could pass by accident -- "the output is
    zero after the release" is true of a model that is zero throughout. The
    test guards against it by requiring the filter to be audibly ringing
    first, and that guard is what has to fire."""
    monkeypatch.setattr(vf, "LadderFx", _SilentLadder)
    msg = _expect_red(test_a_high_resonance_note_reaches_exactly_zero_after_its_release)
    assert "not singing" in msg
