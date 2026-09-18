#!/usr/bin/env python3
"""Acceptance tests for "is this really a TR-808?".

    .venv/bin/python -m pytest model/test_808_acceptance.py -q

WHAT IS UNDER TEST. `model/drums_fx.py` -- the fixed-point eight-stop drum
section (BD, SD, LT, HT, CH, OH, CP, CB) -- driven through its register
interface and rendered here, in this process. Nothing reads a committed WAV, so
what is measured is the design as it stands and not a stale artefact in
`audio/drums/`.

That implementation lives on the unmerged `drums` branch (PR #14). It is NOT
what `main` ships today: `main`'s `synth_top.v` still instantiates
`drum_section_placeholder`, and `audition/engines.py` still has the old
swept-sine kick and noise hi-hats. This suite says nothing about either of
those -- a swept-sine kick would fail
`test_bd_decay_does_not_move_the_pitch_of_the_ring` and noise hats would fail
`test_hats_inherit_the_oscillator_lines_and_noise_does_not`, which is the
point.

THE REFERENCES are two. `docs/tr808-reference.md`, from the June-1981 Roland
service notes and the Werner/Abel/Smith DAFx papers: section 12 is the
per-voice summary, section 1.6 Roland's tuning chart, section 1.7 the
tolerance statement (+-10 % on f0, +-50 % on Q) behind most tolerances here.
And `docs/drum-verification.md`, which measured this model against recordings
of a real TR-808 (serial 103852, individual voice outputs, every knob at 12
o'clock). The second one supplies numbers the first could not -- the snare's
noise balance, the cowbell's band-pass and its decay -- and those assertions
are tagged `hardware-measured` to keep them distinct from what a schematic
says.

CLAIM STATUS. "Verified in a source" and "validated by our own measurement" are
different claims and are kept apart. Every test's docstring opens with one of

    [source-verified: ...]   a primary source states it; asserted at the
                             reference's own tolerance
    [source-inferred: ...]   the reference derived it; asserted as a justified
                             provisional range, wider than a verified claim
    [hardware-measured: ...] measured off a real TR-808 by this project and
                             written up in `docs/drum-verification.md`; a
                             different claim again from either of the above,
                             and the only one of the three that can close an
                             open item in the reference
    [measured-here: ...]     a property this suite established by measurement,
                             with no source behind the number
    [defect: ...]            a specific tracked implementation defect
    [method] / [meta]        a guard on how something is measured, or on this
                             suite itself

and every non-meta test names the ground-truth test in
`model/test_audio_measure.py` that backs the estimator it uses, on a line
beginning "Ground truth:". `test_meta_every_test_declares_status_and_ground_truth`
enforces both. Properties the reference could not establish are in
NOT_ASSERTED and are asserted nowhere -- see reference section 18. Do not invent
precision the research did not have.

MEASUREMENT. All of it is `model/audio_measure.py`, which has its own ground
truth against closed-form signals. Nothing is measured here by an estimator
that has not been checked against a signal with a known answer: on 2026-09-18
four "defects" in this repository turned out to be measurement errors. The
rules that came out of that, in full, are at the top of `audio_measure.py`.
Four of them shape this file:

  * tau and Roland's "decay time" are different quantities. T20 = ln(10)*tau =
    2.303*tau. Every decay assertion says which convention it is in and
    converts with `t20_from_tau`.
  * a filter's corner is measured from its TRANSFER RESPONSE, driven by a
    controlled probe (`mode_impulse_response`), never from a spectral centroid
    of the finished voice. A centroid is not a corner.
  * a spectral peak count does not prove an oscillator topology. The six
    oscillators are established three independent ways: the increment
    REGISTERS, the line positions of the raw source, and the line STABILITY of
    the voice against a matched noise control that must fail the same test.
  * the control path and the audio path are separate claims. Coefficients are
    read back and converted to (f0, tau) independently of any rendering, so a
    failure says whether the fault is in the control path or downstream of it.
  * which envelope: the analytic signal for a single damped sinusoid (the
    bridged-T voices), the short-time RMS for a broadband one (hats, clap). A
    hi-hat's instantaneous amplitude genuinely beats by tens of dB, so its
    analytic envelope is not monotone and appears to GROW for 50 ms after the
    strike; a moving average of |x| on a 56 Hz carrier ripples instead. Both
    failures are in `test_audio_measure.py`.

THE TESTS THAT FAIL CAN PASS. A red test that could never go green is not
evidence of a defect. `test_meta_bd_attack_check_passes_when_the_attack_window_is_written`
and `test_meta_tom_pitch_check_passes_when_a_drop_is_written` write the missing
feature by hand -- as host register writes, which is all either one needs -- and
require the same measurements to succeed.

EVERY RENDER CARRIES A MANIFEST (`Render.manifest`): each hit's frame, time,
stop and accent, every control setting applied, the noise seed, and the
coefficients actually written to each mode. Assertions read the manifest rather
than assuming what a render contains -- three hits at three levels are not
three DECAY settings, they might be three accents.

NOT COVERED, because the eight-stop section does not have them: MT, the congas
LC/MC/HC, RS, CL, MA and CY. Reference section 12 describes them; when a stop
appears, add its row here.

KNOWN SIMPLIFICATION, not asserted: the six square oscillators run at 50 %
duty, where reference 1.5 measures the HD14584 at 47.98 %. That is a design
choice in `drums_fx.py`, recorded so nobody mistakes it for an untested claim.

KNOWN DEFECTS. Four properties below are not met by the model today, each one
documented before this suite existed. They are marked `xfail(strict=True)` from
the KNOWN_DEFECTS table, which means: the assertion still runs, a green build
does not hide it, and the build goes RED the moment one of them starts passing
-- so fixing a defect forces its entry to be removed rather than quietly
absorbed. Set TR808_STRICT=1 to drop the markers and see them fail outright,
which is how they were first observed:

    TR808_STRICT=1 .venv/bin/python -m pytest model/test_808_acceptance.py -q

RED CONTROL (docs/verification-rules.md rule 1):
`test_meta_red_suite_fails_against_a_stub` re-runs this file against a silent
drum section and against a plausible-but-wrong noise one and requires it to go
red. By hand:

    TR808_STUB=silent .venv/bin/python -m pytest model/test_808_acceptance.py -q
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "audition"))

import audio_measure as am
import modal_fixed
from audio_measure import t20_from_tau

try:
    import drums_fx as dx
except ImportError:                                             # pragma: no cover
    # A collection error is not a red test -- it aborts the whole run and hides
    # every other suite's result, which is strictly worse for verification than
    # a loud skip. Rule 1 ("start red") is about an implemented-but-wrong
    # feature and it was satisfied on the `drums` branch, where drums_fx.py
    # exists and four defects are red. Here the module is absent entirely, so
    # the suite is not applicable rather than failing.
    #
    # This cannot rot silently: .github/workflows/rungs.yml asserts that when
    # model/drums_fx.py EXISTS this suite collects a non-zero number of tests,
    # so deleting the implementation cannot quietly turn the suite green.
    pytest.skip(
        "model/drums_fx.py is absent, so the TR-808 acceptance suite is not "
        "applicable here. It lives on the unmerged `drums` branch (PR #14); "
        "the suite's red was established there. See docs/capability-dag.md.",
        allow_module_level=True,
    )
from dsp import SR, PHASE_BITS

COEF_FRAC = 24                      # mode coefficients are Q2.24 (reference 14)

# Reference section 18: established by no source, so asserted by nothing here.
NOT_ASSERTED = {
    # NO LONGER HERE: the CB band-pass centre. Reference 18 listed it as an open
    # item and told the reader to "fit it against a recording"; that is what
    # docs/drum-verification.md section 4.6 did -- fc 1100 Hz, Q 2.8, fitted to
    # 16 partials of a real machine with 2.8 dB rms residual, which also refutes
    # SOS's 2.64 kHz. It is asserted now, as a hardware-measured claim.
    "clap tail level relative to the bursts":
        "reference 7/18: set by a trimmer and two resistors; no measured figure. The "
        "clap tests assert the tail's time constant and the burst COUNT and SPACING, "
        "never the tail-to-burst ratio.",
    "tom noise absolute level":
        "reference 4/18: no measured figure, and the kit has no tom noise path yet.",
    "exact clap burst period":
        "reference 7/18: bounded to 10-12 ms by Roland's Fig. 13 description; the "
        "comparator threshold that fixes it was not solved. The spacing assertion uses "
        "that bound, not a point value.",
    "which serial numbers have the changed snare capacitors":
        "reference 3/18: both the 238/476 Hz and the 173/336 Hz pairs are legal, so "
        "the snare test accepts whichever preset the kit loads and checks the PAIR.",
    "Roland's definition of 'decay time'":
        "reference 1.6: the chart does not define it; the reference reads it as about "
        "T20 from the voices where the analysis is unambiguous. Chart comparisons here "
        "convert tau to T20 and are given the width that inference deserves.",
}

# Properties the model does not have today. Each was observed failing before it
# was listed here, each is reachable (the two marked "positive control" have a
# meta test that writes the missing feature by hand and requires the same
# measurement to succeed), and each is strict, so the build breaks when one
# starts passing and the entry has to go.
# Every defect this suite was written around is now closed, by contract
# revision 6 (DR 0009, DR 0010) and the coefficient sequences of 15.7.1. The
# entries are kept, commented, as the record of what they were and of what
# closed them -- a suite whose defect list is silently emptied cannot be
# audited. Adding a key here and decorating a test with @known_defect is still
# how a new tracked defect is declared.
#
#   test_bd_attack_window_is_written_into_the_coefficients  } closed: 15.7.1
#   test_bd_attack_window_is_audible_in_the_first_half_cycle}  writes the
#       130 Hz / Q 6 window for 4 ms and back. They had also been asserting
#       the chart's 56 Hz as the steady frequency; DR 0009 makes that 49.4.
#   test_tom_pitch_falls_during_the_ring -- closed: 15.7.1 sweeps the tom's
#       f0 from x1.7 over 60 ms, scaled by accent (reference 4).
#   test_sd_noise_balance_matches_a_real_machine -- closed: the level is set
#       to the SNAPPY knob's measured curve at 5.0. Its MEASUREMENT was also
#       withdrawn; see the test.
#   test_cowbell_decay_matches_a_real_machine -- closed: E_CBB is the
#       measured tau 100 ms, not 30.
KNOWN_DEFECTS = {}

STUB = os.environ.get("TR808_STUB", "")
STRICT = bool(os.environ.get("TR808_STRICT", ""))


def known_defect(name: str):
    """Mark a test as a tracked, documented defect: strict xfail, unless
    TR808_STRICT asks for the bare failure."""
    reason = KNOWN_DEFECTS[name]
    if STRICT:
        return lambda fn: fn
    return pytest.mark.xfail(strict=True, reason=reason)
PRE_ROLL_S = 0.010          # silence before every strike: the analytic envelope needs run-in


@dataclass
class Render:
    """One rendered passage and everything needed to interpret it. `manifest`
    is the record a test asserts against: what was played, at what settings,
    with which coefficients actually in the registers."""
    dmix: np.ndarray
    body: np.ndarray
    mix: np.ndarray
    manifest: dict
    hit_index: int = 0

    def after_hit(self, which: int = 0, seconds: float | None = None, bus: str = "mix"):
        """One hit, sliced from its own onset -- never across two. Keeps
        PRE_ROLL_S of silence in front, which the analytic envelope needs."""
        x = {"mix": self.mix, "body": self.body, "dmix": self.dmix}[bus]
        h = self.manifest["hits"][which]
        i0 = max(0, h["frame"] - int(PRE_ROLL_S * SR))
        i1 = len(x) if seconds is None else min(len(x), h["frame"] + int(seconds * SR))
        return x[i0:i1]


def _stub_buses(n: int):
    """docs/verification-rules.md rule 1: a drum section with the right
    interface and no 808 in it."""
    if STUB == "silent":
        return np.zeros(n), np.zeros(n)
    rng = np.random.default_rng(12345)
    env = np.exp(-np.arange(n) / (0.1 * SR))
    return rng.normal(0, 3000, n) * env, rng.normal(0, 9000, n) * env


_CACHE: dict = {}


def render(hits, seconds: float, *, kit=None, extra_writes=(), controls=None, name="") -> Render:
    """Render `hits` and return the audio WITH its manifest.

    `hits` is [(frame, stop, accent)]; `extra_writes` is [(frame, addr, value)]
    applied alongside; `controls` is the caller's own description of what it
    changed, which goes into the manifest verbatim."""
    key = (name, tuple(map(tuple, hits)), round(seconds, 6),
           tuple(kit) if kit is not None else None, tuple(map(tuple, extra_writes)), STUB)
    if key in _CACHE:
        return _CACHE[key]
    n = int(seconds * SR)
    kit = dx.kit_808() if kit is None else list(kit)
    writes = sorted(list(dx.hit_writes(hits, kit)) + list(extra_writes), key=lambda t: t[0])
    manifest = dict(
        name=name,
        seconds=seconds,
        sr=SR,
        controls=dict(controls or {}),
        hits=[dict(frame=int(f), time_s=int(f) / SR, stop=int(s),
                   stop_name=dx.STOP_NAMES[int(s)], accent=float(a))
              for f, s, a in sorted(hits)],
        n_writes=len(writes),
    )
    if STUB:
        dmix, body = _stub_buses(n)
        manifest["stub"] = STUB
        manifest["coefficients"] = {}
        manifest["osc_hz"] = []
        manifest["noise_seed"] = None
    else:
        d = dx.DrumsFx()
        dm, bd = d.play(writes, n)
        dmix, body = dm.astype(np.float64), bd.astype(np.float64)
        manifest["coefficients"] = {
            m: dict(a1=d.a1[m] / (1 << COEF_FRAC), a2=d.a2[m] / (1 << COEF_FRAC),
                    amp=d.amp[m], num=d.num[m])
            for m in range(dx.N_MODES)}
        manifest["osc_hz"] = [inc * SR / (1 << PHASE_BITS) for inc in d.osc_inc]
        manifest["noise_seed"] = dx.LFSR_SEED
    r = Render(dmix, body, dmix + body, manifest,
               hit_index=manifest["hits"][0]["frame"] if manifest["hits"] else 0)
    _CACHE[key] = r
    return r


def one_hit(stop: int, accent: float = 1.0, seconds: float = 0.8, **kw) -> Render:
    """ONE strike, rendered alone, after PRE_ROLL_S of silence. Renders with
    several hits exist (`test_meta_...`), but no measurement here spans two:
    measuring first-onset-to-global-peak across a multi-hit solo render is what
    invented a 700 ms attack on seven of eight voices."""
    at = int(PRE_ROLL_S * SR)
    return render([(at, stop, accent)], seconds + PRE_ROLL_S,
                  name=kw.pop("name", f"{dx.STOP_NAMES[stop]}@{accent}"), **kw)


def kit_with(*, paths_off=False, keep_mode_amp=None, regs=None):
    """kit_808() with named registers replaced, so a probe measures the kit's
    own coefficients rather than freshly invented ones."""
    out = []
    for a, v in dx.kit_808():
        if keep_mode_amp is not None and dx.A_MODE <= a < dx.A_MODE + dx.N_MODES * dx.MODE_STRIDE \
                and (a - dx.A_MODE) % dx.MODE_STRIDE == 2:
            v = 65535 if (a - dx.A_MODE) // dx.MODE_STRIDE == keep_mode_amp else 0
        if paths_off and dx.A_PATH <= a < dx.A_PATH + dx.N_PATH:
            v = 0
        out.append((a, v))
    for a, v in (regs or {}).items():
        out.append((a, v))
    return out


def mode_impulse_response(mode: int, seconds: float = 0.25) -> np.ndarray:
    """The impulse response of ONE mode, with the coefficients kit_808() loads
    into it: all other modes muted, every kit path off, a one-frame full-scale
    pulse into this mode alone.

    This is the controlled broadband probe every filter claim is measured
    with. Measuring a corner from the finished voice's spectrum -- its
    centroid, say -- is not the same quantity and gave wrong answers twice."""
    regs = {
        dx.A_ENV + dx.E_BDX * dx.ENV_STRIDE + 0: dx.env_ctl(dx.BD),
        dx.A_ENV + dx.E_BDX * dx.ENV_STRIDE + 1: dx.peak_reg(1.0),
        dx.A_ENV + dx.E_BDX * dx.ENV_STRIDE + 2: 65535,             # instant: a one-frame impulse
        dx.A_PATH + 13: dx.path_word(dx.SRC_PULSE, dx.E_BDX, dest=mode),
    }
    r = one_hit(dx.BD, 1.0, seconds, kit=kit_with(paths_off=True, keep_mode_amp=mode, regs=regs),
                name=f"probe-mode-{mode}")
    return r.body[r.hit_index:]


def square_source(seconds: float = 1.0) -> np.ndarray:
    """The raw six-oscillator sum on the mix bus: every kit path off, one path
    carrying SQSUM at full scale. Reference 1.5's "combined square wave outputs
    of six Schmitt triggers"."""
    kit = kit_with(paths_off=True,
                   regs={dx.A_PATH + 13: dx.path_word(dx.SRC_SQSUM, dx.ENV_FULL, dest=dx.DEST_MIX)})
    return render([], seconds, kit=kit, name="square-source").dmix


def noise_source_kit():
    """kit_808 with the hats' six-square source replaced by the machine's own
    white noise: the MATCHED NEGATIVE CONTROL. Same filter, same envelope, same
    window, same measurement -- only the source differs, and it must fail
    whatever test the real voice passes."""
    return [(a, dx.path_word(dx.SRC_NOISE, dx.ENV_FULL, dest=dx.M_HATBP) if a == dx.A_PATH + 7 else v)
            for a, v in dx.kit_808()]


def coef_freq_tau(r: Render, mode: int):
    """(f0, tau) implied by the coefficients actually in a mode's registers --
    the CONTROL-path claim, computed with no audio at all."""
    c = r.manifest["coefficients"]
    if mode not in c:
        pytest.fail("the render carries no coefficient manifest (stubbed model)")
    return am.poles_to_freq_tau(c[mode]["a1"], c[mode]["a2"], SR)


# ===========================================================================
# control path -- registers, independent of any rendering
# ===========================================================================
# Reference 2's DECAY table: knob -> (Q, tau). Roland's chart (1.6) gives
# 50 / 300 / 800 ms for short / mid / long -- those are T20-like figures, not
# taus, and reference 2's own table gives tau 33 / 144 / 408 ms at these Q.
#
# The taus are DERIVED here rather than written down, from the resonator
# identity tau = Q / (pi f0) at the f0 the kit ships. Revision 5 wrote them as
# 29 / 127 / 352 ms, which is that identity at Roland's chart's 56 Hz -- and
# reference 2's own table is only self-consistent at its computed 49.4 Hz
# (1.5 % against 12.8 %). DR 0009 resolves that; deriving them here means this
# table cannot drift from the law again.
BD_DECAY = tuple((knob, dx.bd_decay_q(knob * 10), dx.bd_decay_q(knob * 10) / (math.pi * dx.BD_HZ))
                 for knob in (0.1, 0.5, 0.9))


def bd_at_decay(knob: float, q: float, tau_ref: float) -> Render:
    """A DECAY setting is a KIT setting, so it goes into the register image
    rather than alongside it. Since contract 15.7.1 the reference host also
    emits the BD's 4 ms attack window per hit, and that window restores the
    coefficients it found IN THE IMAGE -- as Q43 releases back to whatever the
    DECAY knob currently sets. Writing the setting as `extra_writes` instead
    would have it restored away 4 ms later, which is what a real host would
    also suffer, so the test drives the real path."""
    seconds = max(0.5, 9 * tau_ref)
    at = int(PRE_ROLL_S * SR)
    kit = [(a, dict(dx.mode_writes(dx.M_BD, dx.BD_HZ, q, 0.0)[:2]).get(a, v))
           for a, v in dx.kit_808()]
    return render([(at, dx.BD, 1.0)], seconds + PRE_ROLL_S, kit=kit,
                  controls=dict(decay_knob=knob, decay_q=q, f0_hz=dx.BD_HZ),
                  name=f"BD-decay-{knob}")


@pytest.mark.parametrize("knob,q,tau_ref", BD_DECAY)
def test_control_bd_decay_coefficients_carry_the_intended_decay(knob, q, tau_ref):
    """[source-inferred: reference 2's DECAY table and reference 14's presets]
    The CONTROL path on its own: the Q2.24 coefficients that the DECAY setting
    actually wrote, converted back to (f0, tau) with no audio involved. tau
    reference 2's own 33 / 144 / 408 ms at knob 0.1 / 0.5 / 0.9, f0 unchanged
    at the kit's 49.4 Hz (DR 0009).

    Asserted separately from the rendered ring so a failure localises: right
    coefficients with a short ring means the fault is downstream -- excitation,
    envelope, gain or clipping -- and not in the control path.

    Ground truth: test_audio_measure.test_damped_sinusoid_matches_the_coefficients_that_generated_it
    """
    r = bd_at_decay(knob, q, tau_ref)
    assert r.manifest["controls"]["decay_q"] == q, "the manifest does not describe this render"
    f, t = coef_freq_tau(r, dx.M_BD)
    assert abs(f.require("coefficient f0") / dx.BD_HZ - 1) <= 0.01
    got = t.require("coefficient tau")
    assert abs(got / tau_ref - 1) <= 0.05, \
        f"knob {knob}: coefficients mean tau {got*1e3:.1f} ms, reference {tau_ref*1e3:.0f} ms"


def test_control_six_oscillator_increments_are_the_reference_frequencies():
    """[source-verified: reference 1.5 / 13 hypothesis 2, W14b 3 + SN p.13]
    "205.3, 369.6, 304.4, 522.7, 800 (trimmed), 540 (trimmed) Hz" from one
    HD14584 hex Schmitt trigger. The first of the three independent checks that
    there are SIX oscillators at these frequencies: the phase increments in the
    registers, read back and converted to Hz. No audio, no spectrum, no
    inference from a peak count.

    Ground truth: none needed -- this is arithmetic on a register, not an estimate.
    """
    hz = render([], 0.01, name="osc-registers").manifest["osc_hz"]
    if not hz:
        pytest.fail("the render carries no oscillator manifest (stubbed model)")
    assert len(hz) == 6, f"{len(hz)} oscillators, reference 6"
    for ref, got in zip(dx.OSC_HZ, hz):
        assert abs(got / ref - 1) <= 0.005, f"oscillator register says {got:.2f} Hz, reference {ref} Hz"


# Reference 12 and 14: the bridged-T bodies the kit loads.
MODE_PRESETS = (
    # DR 0009: the circuit's f0, and the tau reference 2's own table gives for
    # the Q the kit writes at DECAY mid -- not the chart's 56 Hz / 127 ms pair,
    # which is that table's Q read at the chart's frequency.
    ("BD", dx.M_BD, dx.BD_HZ, dx.bd_decay_q(5.0) / (math.pi * dx.BD_HZ), 0.10),
    ("SD low", dx.M_SDLO, 173.0, 0.030, 0.15),  # reference 3, later units [inferred]
    ("SD high", dx.M_SDHI, 336.0, 0.0094, 0.20),
    ("LT", dx.M_LT, 90.0, 0.088, 0.15),        # reference 4
    ("HT", dx.M_HT, 185.0, 0.043, 0.15),
)


@pytest.mark.parametrize("name,mode,f0_ref,tau_ref,tau_tol", MODE_PRESETS)
def test_control_body_presets_match_the_reference_table(name, mode, f0_ref, tau_ref, tau_tol):
    """[source-inferred: reference 14's preset table, computed from reference
    2-4's component values] The control path for every bridged-T body the kit
    loads. f0 to +-2 % (these are exact conversions, not measurements of a
    physical unit); tau to the per-voice tolerance, which is wider where the
    reference itself inferred the value.

    Ground truth: test_audio_measure.test_damped_sinusoid_matches_the_coefficients_that_generated_it
    """
    r = one_hit(dx.BD, 1.0, 0.05, name="kit-registers")
    f, t = coef_freq_tau(r, mode)
    assert abs(f.require(f"{name} f0") / f0_ref - 1) <= 0.02, \
        f"{name}: coefficients mean {f.value:.1f} Hz, reference {f0_ref} Hz"
    got = t.require(f"{name} tau")
    assert abs(got / tau_ref - 1) <= tau_tol, \
        f"{name}: coefficients mean tau {got*1e3:.1f} ms, reference {tau_ref*1e3:.1f} ms"


# ===========================================================================
# BD -- bass drum
# ===========================================================================
def test_bd_fundamental_of_the_rendered_ring():
    """[source-verified: reference 2 and the chart in 1.6] 49-56 Hz. Werner
    computes 49.4 Hz from the component values, Roland's chart says 56 Hz, and
    reference 2 says "treat 50-56 Hz as the target". +-10 % per reference 1.7,
    applied to that band. Measured from the AUDIO, as the counterpart of
    test_control_body_presets_match_the_reference_table.

    Ground truth: test_audio_measure.test_dominant_frequency_on_known_tones
    """
    r = one_hit(dx.BD, 1.0, 1.0)
    f0 = am.dominant_frequency(r.after_hit(0, 1.0, "body"), 20.0, 400.0, SR).require("BD f0")
    assert 49.0 * 0.9 <= f0 <= 56.0 * 1.1, f"BD fundamental {f0:.1f} Hz outside 44.1-61.6 Hz"
    # and, since DR 0009 chose within that band, the tighter statement:
    assert abs(f0 / dx.BD_HZ - 1) <= 0.05, \
        f"BD fundamental {f0:.1f} Hz against the kit's {dx.BD_HZ} Hz (DR 0009)"


@pytest.mark.parametrize("knob,q,tau_ref", BD_DECAY)
def test_bd_rendered_decay_at_each_setting(knob, q, tau_ref):
    """[source-inferred: reference 2's DECAY table] The AUDIO counterpart of
    test_control_bd_decay_coefficients_carry_the_intended_decay: the ring
    actually decays with the tau the coefficients promised. tau 29 / 127 /
    352 ms, +-20 % -- well inside reference 1.7's +-50 % on a Q, and loose
    enough that the estimator is never the limiting factor.

    The bass drum is one damped sinusoid, so the analytic envelope is the
    envelope and the fit is on that. The two-pole fit is NOT used for tau here:
    on a 16-bit integer ring with 1 - r of a few times 1e-4 its least-squares
    bias is the whole answer, and `damped_sinusoid` refuses it for that reason.
    Its FREQUENCY survives, and is checked.

    The rendered tau is also compared with what the coefficients promised: if
    they agree, the control path and the audio path tell the same story, and if
    they do not, the fault is downstream of the registers.

    Ground truth: test_audio_measure.test_decay_tau_recovers_a_known_time_constant,
    test_audio_measure.test_damped_sinusoid_refuses_a_tau_its_residual_cannot_resolve
    """
    r = bd_at_decay(knob, q, tau_ref)
    body = r.after_hit(0, min(9 * tau_ref, 3.0), "body")
    env = am.decay_tau(body, SR).require("envelope tau")
    assert abs(env / tau_ref - 1) <= 0.20, \
        f"knob {knob}: rendered tau {env*1e3:.1f} ms, reference {tau_ref*1e3:.0f} ms"
    coef = coef_freq_tau(r, dx.M_BD)[1].require("coefficient tau")
    assert abs(env / coef - 1) <= 0.20, \
        (f"knob {knob}: the ring decays in {env*1e3:.1f} ms but its coefficients say "
         f"{coef*1e3:.1f} ms -- the fault is downstream of the registers")
    # measured from AFTER the 4 ms attack window of 15.7.1, not from the strike:
    # during the window the mode really is at ~130 Hz, and at the shortest
    # DECAY that window is a large fraction of the whole hit, so a fit that
    # starts at the strike reads the two frequencies mixed (55 Hz at knob 0.1)
    # and would be measuring the window rather than the body.
    after = int((PRE_ROLL_S + dx.BD_ATTACK_MS * 1e-3) * SR) + 8
    f = am.damped_sinusoid(body[after:], SR).freq.require("two-pole frequency")
    assert abs(f / dx.BD_HZ - 1) <= 0.03, \
        f"knob {knob}: two-pole frequency {f:.2f} Hz, reference {dx.BD_HZ} Hz"


def test_bd_decay_control_spans_roland_s_chart_range():
    """[source-verified: chart 1.6, BD decay 50 / 300 / 800 ms] The RANGE, not a
    point: a DECAY control that does nothing passes any single-setting test,
    and that is the shape of the defect reported on 2026-09-17.

    Roland's chart does not define "decay time"; reference 1.6 reads it as
    about T20, so tau is converted with T20 = ln(10)*tau = 2.303*tau and the
    chart values are treated as a RANGE to fall inside rather than as three
    points to hit. Monotone in the knob, and at least 8x from shortest to
    longest against the chart's own 16x.

    Ground truth: test_audio_measure.test_t20_is_ln10_times_tau,
    test_audio_measure.test_decay_tau_recovers_a_known_time_constant
    """
    taus = []
    for knob, q, tau_ref in BD_DECAY:
        r = bd_at_decay(knob, q, tau_ref)
        taus.append(am.decay_tau(r.after_hit(0, min(9 * tau_ref, 3.0), "body"), SR)
                    .require(f"tau at knob {knob}"))
    assert taus == sorted(taus), f"not monotone in the knob: {[round(t*1e3, 1) for t in taus]} ms"
    assert taus[-1] / taus[0] >= 8.0, (
        f"DECAY spans only {taus[-1] / taus[0]:.2f}x ({taus[0]*1e3:.1f} -> {taus[-1]*1e3:.1f} ms); "
        f"Roland's chart spans 50 -> 800 ms, 16x. A control that does nothing measures 1.0x.")
    for (knob, _, _), tau, chart in zip(BD_DECAY, taus, (0.050, 0.300, 0.800)):
        t20 = t20_from_tau(tau)
        # +-60 % against the chart, because that is the reference's OWN
        # disagreement with it: reference 2's table computes 2.3 tau = 76 / 330
        # / 940 ms from the component values where the chart says 50 / 300 /
        # 800, and reference 1.6 tags the chart's definition of "decay time"
        # as something it could not establish. Inventing a tighter bound here
        # would be inventing precision the research did not have.
        assert abs(t20 / chart - 1) <= 0.60, \
            f"knob {knob}: T20 {t20*1e3:.0f} ms against Roland's chart decay {chart*1e3:.0f} ms"


def test_bd_decay_does_not_move_the_pitch_of_the_ring():
    """[source-verified: reference 13 hypothesis 1] "The BD DECAY knob raises
    negative feedback into the resonator's foot node, cancelling its damping;
    f0 does not move." Reference 1.2 derives it: the feedback subtracts from
    the damping term and leaves f0 unchanged to first order. +-3 %.

    This is the assertion that separates a bridged-T ring-down from a swept
    oscillator, and it is the one `audition/engines.py`'s old swept-sine kick
    on `main` would fail.

    Ground truth: test_audio_measure.test_dominant_frequency_on_known_tones
    """
    f = []
    for knob, q, tau_ref in BD_DECAY:
        r = bd_at_decay(knob, q, tau_ref)
        f.append(am.dominant_frequency(r.after_hit(0, min(9 * tau_ref, 3.0), "body"),
                                       20.0, 400.0, SR).require(f"f0 at knob {knob}"))
    assert max(f) / min(f) <= 1.03, f"BD pitch moves with DECAY: {[round(v, 2) for v in f]} Hz"


def test_bd_attack_window_is_written_into_the_coefficients():
    """[source-verified: reference 2 "attack frequency shift", W14a 8.1 + SN p.6]

    **Was a tracked defect; closed in contract revision 6** -- the coefficient
    sequence of 15.7.1 writes this window, and the steady frequency it returns
    to is the circuit's 49.4 Hz rather than the chart's 56 (DR 0009).

    For the duration of the envelope generator's pulse, Q43 shorts R165, the
    foot resistance drops from 53.8 k to 6.8 k, and f0 rises to about 130 Hz
    with Q about 6 for ~4 ms before falling back. Reference 12 carries it in
    the BD row: "49-56 (attack ~130 for 4 ms)".

    This is the CONTROL-path half: within the first 4 ms of a hit the bass
    drum's mode must be carrying attack coefficients, and 4 ms later the steady
    ones. Checked here rather than by a short-window FFT because 4 ms is less
    than one cycle at 130 Hz -- the frequency is simply not in the spectrum of
    that window, and asking an FFT for it gets an answer about something else.

    Ground truth: none needed -- register read-back and arithmetic.
    """
    at = int(PRE_ROLL_S * SR)
    early = render([(at, dx.BD, 1.0)], PRE_ROLL_S + 0.002, name="BD-attack-early")
    late = render([(at, dx.BD, 1.0)], PRE_ROLL_S + 0.020, name="BD-attack-late")
    f_early = coef_freq_tau(early, dx.M_BD)[0].require("BD f0 at +2 ms")
    f_late = coef_freq_tau(late, dx.M_BD)[0].require("BD f0 at +20 ms")
    assert abs(f_late / dx.BD_HZ - 1) <= 0.10, \
        f"BD settles at {f_late:.1f} Hz, reference {dx.BD_HZ} Hz"
    assert 130.0 * 0.75 <= f_early <= 130.0 * 1.25, (
        f"2 ms after the strike the bass drum's coefficients are still {f_early:.1f} Hz; "
        f"reference 2 requires about 130 Hz for the first 4 ms. kit_808() writes one "
        f"coefficient set per voice and never switches it, so the attack window is absent.")


def test_bd_attack_window_is_audible_in_the_first_half_cycle():
    """[source-verified: reference 2]

    **Was a tracked defect; closed in contract revision 6** -- the same window,
    seen in the audio rather than the registers.

    The AUDIO half of the same claim, and the
    localisation: if the coefficients are right and this fails, the fault is in
    the excitation or the switch timing.

    4 ms at 130 Hz is half a cycle, so it is measured with the two-pole fit,
    which is exact on less than one cycle where an FFT cannot work at all.

    Ground truth: test_audio_measure.test_damped_sinusoid_works_on_less_than_one_cycle
    """
    r = one_hit(dx.BD, 1.0, 0.6)
    i = r.hit_index
    window = r.body[i:i + int(0.004 * SR)]
    f = am.damped_sinusoid(window, SR).freq.require("BD attack frequency")
    steady = am.damped_sinusoid(r.body[i + int(0.010 * SR):i + int(0.30 * SR)], SR) \
        .freq.require("BD steady frequency")
    assert abs(steady / dx.BD_HZ - 1) <= 0.10, \
        f"BD steady ring {steady:.1f} Hz, reference {dx.BD_HZ} Hz"
    assert 130.0 * 0.75 <= f <= 130.0 * 1.25, (
        f"the bass drum's first 4 ms ring at {f:.1f} Hz, not the reference's ~130 Hz; "
        f"it is already at its steady {steady:.1f} Hz, so there is no attack window.")


# ===========================================================================
# SD -- snare drum
# ===========================================================================
# Reference 3: two legal presets. Which serials got which is section 18's open
# item, so either is accepted -- but the PAIR must be consistent.
SD_PRESETS = {"1981 chart": (238.0, 476.0), "later units": (173.0, 336.0)}


def test_sd_two_resonator_frequencies():
    """[source-verified: SN p.6 "two bridged T-networks", chart 1.6 476/238 Hz.
    The later 173/336 Hz pair is source-inferred, reference 3] Two bridged-T
    resonators about an octave apart, the upper decaying roughly 3x faster.
    +-10 % on f0 per reference 1.7.

    Both partials are measured in the first 60 ms, where both are still
    present; over a longer window the upper one has gone and would be reported
    as absent, and over a much shorter one the window has too few bins to
    resolve it.

    Ground truth: test_audio_measure.test_line_at_resolves_two_close_tones
    """
    r = one_hit(dx.SD, 1.0, 0.5)
    i = r.hit_index
    early = r.body[i:i + int(0.060 * SR)]
    lo = am.dominant_frequency(early, 100.0, 280.0, SR).require("SD low partial")
    name, (ref_lo, ref_hi) = min(SD_PRESETS.items(), key=lambda kv: abs(lo - kv[1][0]))
    assert abs(lo / ref_lo - 1) <= 0.10, f"SD low partial {lo:.1f} Hz, {name} expects {ref_lo}"
    hi = am.dominant_frequency(early, ref_hi * 0.75, ref_hi * 1.3, SR).require("SD high partial")
    assert abs(hi / ref_hi - 1) <= 0.10, f"SD high partial {hi:.1f} Hz, {name} expects {ref_hi}"
    assert 1.8 <= hi / lo <= 2.1, f"SD partials {lo:.0f}/{hi:.0f} Hz, ratio {hi/lo:.2f}, reference ~1.94-2.0"


def test_sd_snappy_sets_the_noise_level_and_nothing_else():
    """[source-verified: SN p.6 "The amplitude of snappy envelope can be
    controlled by VR9", reference 3] SNAPPY is the amplitude of the noise
    envelope and does not touch the resonators -- reference 3 explicitly refutes
    the published account in which the snappy signal is added to the trigger of
    both oscillators.

    Two claims, kept apart: the noise band rises monotonically over a wide
    range, and the tone band does not move at all. Band energies are absolute,
    never normalised, or a change in one would hide as a change in the other.

    Ground truth: test_audio_measure.test_dominant_frequency_on_known_tones
    (band energies are sums of the same spectrum this is validated on)
    """
    tone, noise = [], []
    for snappy in (0.0, 0.25, 0.5, 1.0):
        kit = [(a, dx.peak_reg(snappy) if a == dx.A_ENV + dx.E_SDN * dx.ENV_STRIDE + 1 else v)
               for a, v in dx.kit_808()]
        r = one_hit(dx.SD, 1.0, 0.30, kit=kit, name=f"SD-snappy-{snappy}")
        assert r.manifest["hits"][0]["accent"] == 1.0, "accent must be held while SNAPPY varies"
        x = r.after_hit(0, 0.25)
        f, X = am.spectrum(x, SR)
        tone.append(float(np.sum(X[(f >= 100) & (f <= 700)] ** 2)))
        noise.append(float(np.sum(X[(f >= 2000) & (f <= 12000)] ** 2)))
    assert noise == sorted(noise), f"SNAPPY not monotone: {[round(am.db(v), 1) for v in noise]} dB"
    span = 10 * math.log10(noise[-1] / max(noise[0], 1e-30))
    assert span >= 20.0, f"SNAPPY spans only {span:.1f} dB of noise level"
    spread = 10 * math.log10(max(tone) / min(tone))
    assert spread <= 0.5, f"SNAPPY moves the resonators by {spread:.2f} dB; reference 3 says it must not"


def test_sd_noise_balance_matches_a_real_machine():
    """[hardware-measured: docs/drum-verification.md section 8.1, a real TR-808
    serial 103852 from its individual voice outputs]

    **Both this measurement and its target were replaced in contract revision
    6.** The 51.5 % it used to assert came from a body/air split above and
    below 700 Hz, computed on a Hann-windowed 500 ms span -- which weights
    t = 10 ms by 0.0039 against t = 250 ms by 1.0 and therefore reports
    whichever component decays slowest, not the energy. On our own render,
    where the true share is exact arithmetic (18.55 %), that split returned
    1.25 %. It is withdrawn, and `model/test_drum_fit.py` keeps it as a
    control that must stay wrong.

    The validated separator fits the two body modes as damped sinusoids and
    calls the residual noise. By it, the real machine at SNAPPY 5.0 -- the
    12-o'clock condition the kit's presets are derived from -- carries
    **27.66 %** of the hit's energy as noise, with a spread of +-8.0
    percentage points across the five TONE positions. Asserted as that spread,
    widened to +-10 points: one machine's SNAPPY law is not every machine's.

    Ground truth: test_drum_fit.test_separator_recovers_a_known_noise_share,
    test_drum_fit.test_separator_matches_the_exact_share_of_our_own_render
    """
    import drum_fit as df
    r = one_hit(dx.SD, 1.0, 0.5)
    share = df.noise_share(r.after_hit(0, 0.4, "body"), SR, df.VOICE_MODES["SD"])["share"]
    assert abs(share - 0.2766) <= 0.10, (
        f"the snare carries {share*100:.1f} % of its energy as noise; a real TR-808 at "
        f"the same knob positions carries 27.7 % (docs/drum-verification.md section 8.1). "
        f"The snappy path is {10*math.log10(0.2766/max(share, 1e-9)):+.1f} dB off.")


def test_sd_noise_filter_is_a_band_pass_on_the_reference_s_pole():
    """[source-inferred: reference 3, the Sallen-Key on Q49 read from the p.9
    values] f0 about 2.75 kHz, Q about 0.7. Inferred, so +-20 % on the centre.

    **The numerator changed in contract revision 6** (docs/drum-verification.md
    section 8.1). Reference 3 calls this a high-pass; on that pole a high-pass
    is flat to Nyquist, and the real machine's snare noise -- recovered as the
    residual after subtracting the two body modes -- peaks at 3-5 kHz and falls
    above, with 2.9 % of its energy over 12 kHz. The same pole read as a
    BAND-pass fits that spectrum to 1.9 dB weighted rms against the
    high-pass's 5.2, so the kit keeps reference 3's f0 and Q exactly and
    changes only the numerator. Contract 17.22 records that the schematic
    reading is not settled.

    The POLE and the response PEAK are different quantities and are asserted
    separately, because conflating them is how a filter gets "moved" to fix a
    number that was never about its pole. The pole is what reference 3 states
    and what the register holds, so it is asserted tightly; the peak of
    pole x numerator sits above it at this Q, and what matters about the peak
    is only that it lands in the 3-5 kHz band where the real machine's snare
    noise peaks (docs/drum-verification.md section 8.1).

    Ground truth: test_audio_measure.test_resonant_peak_matches_the_closed_form_response
    """
    assert dict(dx.kit_808())[dx.A_MODE + dx.M_SDN * dx.MODE_STRIDE + 3] == modal_fixed.BP, \
        "the snappy mode's numerator register is not BP"
    r = one_hit(dx.SD, 1.0, 0.2)
    f, _ = coef_freq_tau(r, dx.M_SDN)
    pole = f.require("SD snappy pole")
    assert abs(pole / 2750.0 - 1) <= 0.02, \
        f"SD snappy pole {pole:.0f} Hz, reference 3 says 2750 Hz"
    ir = mode_impulse_response(dx.M_SDN)
    fc = am.resonant_peak(ir, SR).require("SD noise band-pass peak")
    assert 3000.0 <= fc <= 5000.0, (
        f"the snappy band-pass peaks at {fc:.0f} Hz; the real machine's snare noise "
        f"peaks in 3-5 kHz (docs/drum-verification.md section 8.1)")


# ===========================================================================
# LT / HT -- toms
# ===========================================================================
TOMS = (("LT", dx.LT, 90.0, 0.088), ("HT", dx.HT, 185.0, 0.043))


@pytest.mark.parametrize("name,stop,f0_ref,tau_ref", TOMS)
def test_tom_fundamental(name, stop, f0_ref, tau_ref):
    """[source-verified: chart 1.6, LT 90 Hz and HT 185 Hz at mid tuning]
    +-10 % per reference 1.7; the TUNING pot spans about that much by itself.

    Ground truth: test_audio_measure.test_dominant_frequency_on_known_tones
    """
    r = one_hit(stop, 1.0, 0.8)
    f0 = am.dominant_frequency(r.after_hit(0, 0.8, "body"), 40.0, 500.0, SR).require(f"{name} f0")
    assert abs(f0 / f0_ref - 1) <= 0.10, f"{name} fundamental {f0:.1f} Hz, chart {f0_ref} Hz"


@pytest.mark.parametrize("name,stop,f0_ref,tau_ref", TOMS)
def test_tom_decay(name, stop, f0_ref, tau_ref):
    """[source-inferred: reference 4, tau computed from the component values --
    LT 92 ms, HT 44 ms; Roland's chart says 200 / 100 ms, which is about 2.2
    tau] Inferred, so +-25 %, and the chart value is checked only as a range in
    the T20 convention.

    Ground truth: test_audio_measure.test_decay_tau_recovers_a_known_time_constant
    """
    r = one_hit(stop, 1.0, 1.2)
    tau = am.decay_tau(r.after_hit(0, 1.2, "body"), SR).require(f"{name} tau")
    assert abs(tau / tau_ref - 1) <= 0.25, f"{name} tau {tau*1e3:.1f} ms, reference {tau_ref*1e3:.0f} ms"
    chart = {"LT": 0.200, "HT": 0.100}[name]
    assert 0.5 * chart <= t20_from_tau(tau) <= 1.6 * chart, \
        f"{name} T20 {t20_from_tau(tau)*1e3:.0f} ms against Roland's chart decay {chart*1e3:.0f} ms"


@pytest.mark.parametrize("name,stop,f0_ref,tau_ref", TOMS)
def test_tom_pitch_falls_during_the_ring(name, stop, f0_ref, tau_ref):
    """[source-verified: SN p.6, quoted in reference 4]

    **Was a tracked defect; closed in contract revision 6** -- 15.7.1 sweeps
    the tom's f0 from x1.7 over 60 ms, scaled by accent, which is this
    section's "accent changes the pitch envelope".
 "While the oscillation is
    large in amplitude immediately after triggering, it is on a higher
    frequency due to conductions of D80 and D81, which reduce time constant of
    the filter. As the resonance is damped, its frequency is lowered..." Roland
    states the fall outright; this is the toms' characteristic doom sweep.

    The EXISTENCE of the fall is source-verified and is asserted. Its 1.7x
    magnitude is source-inferred and reference 4 warns the knee is soft, so the
    provisional bound here is only "at least 5 %" -- the weakest statement that
    still separates "it falls" from "it does not". The magnitude has its own
    test below, as a wider provisional range.

    Ground truth: test_audio_measure.test_instantaneous_frequency_tracks_a_known_glide,
    test_audio_measure.test_instantaneous_frequency_is_flat_for_a_steady_tone
    """
    first, settled = _tom_pitch(stop)
    assert first / settled >= 1.05, (
        f"{name} starts at {first:.1f} Hz and settles at {settled:.1f} Hz "
        f"(ratio {first/settled:.3f}): no diode pitch drop. kit_808() loads one fixed "
        f"coefficient pair per tom and never changes it while the mode rings.")


def _tom_pitch(stop):
    return _pitch_of(one_hit(stop, 1.4, 1.0))


def _pitch_of(r: Render):
    i = r.hit_index
    y = r.body[i:i + int(0.5 * SR)]
    inst = am.instantaneous_frequency(y, SR, smooth_ms=2.0)
    env = am.analytic_envelope(y)
    live = env > env.max() * 0.05
    n = min(len(inst), len(live) - 1)
    inst, live = inst[:n], live[:n]
    early = inst[int(0.001 * SR):int(0.008 * SR)]
    late_mask = live.copy()
    late_mask[:int(0.060 * SR)] = False
    assert late_mask.any(), "the tom did not ring long enough to settle"
    return float(np.median(early)), float(np.median(inst[late_mask]))


@pytest.mark.parametrize("name,stop,f0_ref,tau_ref", TOMS)
def test_tom_pitch_drop_magnitude(name, stop, f0_ref, tau_ref):
    """[source-inferred: reference 4, "f0 up to about 1.7x the small-signal
    value"] The magnitude is inferred from the diode-conducting foot resistance
    and reference 4 says the transition is a soft germanium knee, not a step --
    so this is a wide provisional range, 1.2x to 2.0x on a hard hit, not a
    point value. It is a separate test from the existence of the fall because
    it is a weaker claim, and it must not be able to fail the build for a
    reason the existence test would not.

    Ground truth: test_audio_measure.test_instantaneous_frequency_tracks_a_known_glide
    """
    first, settled = _tom_pitch(stop)
    ratio = first / settled
    if ratio < 1.05:
        pytest.skip(f"{name} has no pitch drop at all -- see test_tom_pitch_falls_during_the_ring")
    assert 1.2 <= ratio <= 2.0, f"{name} pitch drop {ratio:.2f}x, reference up to about 1.7x"


# ===========================================================================
# the six square-wave oscillators -- CB, CY, OH, CH share one bank
# ===========================================================================
SQ_BAND = (2000.0, 16000.0)


def test_square_source_is_a_seven_level_staircase():
    """[source-verified: reference 1.5] "The six outputs are summed passively
    through 120 k each into R53 = 1 k to ground -- a sum of six 0/5 V squares,
    heavily attenuated, i.e. a 7-level staircase." Six two-level sources sum to
    exactly seven levels; noise would take thousands. The second of the three
    independent checks, and the one that no spectral method could give.

    Ground truth: none needed -- counting distinct sample values.
    """
    levels = np.unique(np.round(square_source(0.5)).astype(np.int64))
    assert len(levels) == 7, f"the square sum takes {len(levels)} distinct levels, reference 7"


def test_square_source_lines_sit_on_the_six_oscillator_frequencies():
    """[source-verified: reference 1.5] The six fundamentals in the rendered
    source, each within 2 % of its register value and within 6 dB of the
    strongest -- the six sum equally through equal 120 k resistors.

    Ground truth: test_audio_measure.test_line_at_resolves_two_close_tones,
    test_audio_measure.test_dominant_frequency_on_known_tones
    """
    x = square_source(1.0)
    levels = []
    for ref in dx.OSC_HZ:
        e = am.line_at(x, ref, SR, rel_tol=0.03)
        got = e.require(f"oscillator at {ref} Hz")
        assert abs(got / ref - 1) <= 0.02, f"oscillator {ref} Hz measured {got:.1f} Hz"
        levels.append(e.detail["level"])
    top = max(levels)
    for ref, lv in zip(dx.OSC_HZ, levels):
        assert am.db(lv, top) >= -6.0, f"oscillator {ref} Hz is {am.db(lv, top):.1f} dB down"


def test_square_source_line_structure_is_stable_and_noise_is_not():
    """[source-verified: reference 13 hypothesis 2 -- "six square wave
    oscillators, summed, band-passed, high-passed -- confirmed; not noise"]

    The third independent check, and the one that a peak count cannot give: the
    lines must be in the SAME PLACES in every window. Free-running oscillators
    are; filtered noise is not, however many peaks it happens to show. The
    matched control is the machine's own noise source through the same path,
    and it must fail this test.

    Ground truth: test_audio_measure.test_line_stability_separates_oscillators_from_noise,
    test_audio_measure.test_a_peak_count_alone_does_not_prove_an_oscillator_bank
    """
    src = square_source(1.0)
    stable = am.line_stability(src, SQ_BAND, SR, windows=4, tol_hz=40.0,
                               threshold=2.0).require("square source stability")
    kit = kit_with(paths_off=True,
                   regs={dx.A_PATH + 13: dx.path_word(dx.SRC_NOISE, dx.ENV_FULL, dest=dx.DEST_MIX)})
    ctl = render([], 1.0, kit=kit, name="noise-source-control").dmix
    ctl_stable = am.line_stability(ctl, SQ_BAND, SR, windows=4, tol_hz=40.0,
                                   threshold=2.0).require("noise control stability")
    assert stable >= 0.75, f"the oscillator bank's lines were only {stable:.2f} stable"
    assert ctl_stable <= 0.35, f"the matched noise control was {ctl_stable:.2f} stable -- it must fail this"
    assert stable >= 2 * ctl_stable, "the oscillator source and noise are not separated"


def test_hats_inherit_the_oscillator_lines_and_noise_does_not():
    """[source-verified: reference 1.4 "CY, OH and CH do not use noise at all",
    reference 11, reference 13 hypothesis 2] Both hats take the 7.1 kHz
    band-pass of the six-square sum. So the open hat's own output must carry
    stable oscillator lines, and the SAME VOICE with its source swapped for the
    machine's white noise -- same filter, same envelope, same window, same
    measurement -- must not.

    The open hat is used because its 450 ms envelope gives sub-windows long
    enough to resolve the lines; the closed hat's 50 ms does not, and this
    suite does not pretend otherwise.

    Ground truth: test_audio_measure.test_line_stability_separates_oscillators_from_noise
    """
    voice = one_hit(dx.OH, 1.0, 0.40).after_hit(0, 0.40)
    control = one_hit(dx.OH, 1.0, 0.40, kit=noise_source_kit(), name="OH-noise-control").after_hit(0, 0.40)
    v = am.line_stability(voice, SQ_BAND, SR, windows=4, tol_hz=60.0,
                          threshold=2.0).require("OH line stability")
    c = am.line_stability(control, SQ_BAND, SR, windows=4, tol_hz=60.0,
                          threshold=2.0).require("noise control line stability")
    assert v >= 0.60, f"the open hat's lines were only {v:.2f} stable; it should be an oscillator bank"
    assert c <= 0.35, f"the matched noise control was {c:.2f} stable -- the control must fail this test"
    assert v >= 2 * c, f"hat {v:.2f} vs noise control {c:.2f}: not separated"


def test_cowbell_is_oscillators_five_and_six_at_540_and_800_hz():
    """[source-verified: reference 9 / 13 hypothesis 3, SN p.6 + p.13 + p.14
    chart, W14b] The cowbell is oscillators 5 and 6 of the same bank, the two
    factory-trimmed ones: TM2 "COWBELL FREQ.2 1.25 ms" = 800 Hz, TM1 "COWBELL
    FREQ.1 1.85 ms" = 540 Hz, ratio 1.48. +-5 %, tighter than reference 1.7's
    +-10 % because these two are trimmed on the production line instead of
    being left to part spread.

    The band-pass that follows is reference 18's open item and is asserted
    nowhere: the 540 Hz line may sit well below the 800 Hz one, which is what a
    0.9 kHz centre would do, but the reference could not establish that centre.

    Ground truth: test_audio_measure.test_line_at_resolves_two_close_tones
    """
    x = one_hit(dx.CB, 1.0, 0.25).after_hit(0, 0.12)
    lo = am.line_at(x, 540.0, SR, rel_tol=0.05).require("CB 540 Hz")
    hi = am.line_at(x, 800.0, SR, rel_tol=0.05).require("CB 800 Hz")
    assert abs(lo / 540.0 - 1) <= 0.05, f"CB low oscillator {lo:.1f} Hz, reference 540 Hz"
    assert abs(hi / 800.0 - 1) <= 0.05, f"CB high oscillator {hi:.1f} Hz, reference 800 Hz"
    assert abs((hi / lo) / 1.4815 - 1) <= 0.03, f"CB ratio {hi/lo:.3f}, reference 1.48"


def test_cowbell_band_pass_centre():
    """[hardware-measured: docs/drum-verification.md section 4.6] Reference 18
    listed the cowbell's band-pass as an open item -- 0.9 kHz from the topology
    reading against SOS's 2.64 kHz -- and said to fit it against a recording.
    Fitting a 2-pole band-pass to 16 identified partials of a real machine gives
    **fc 1100 Hz, Q 2.8** with a 2.8 dB rms residual, and refutes 2.64 kHz. The
    item is closed, so it is asserted here rather than listed in NOT_ASSERTED.

    +-25 % on the centre and +-60 % on the Q: this is one fit to one machine
    whose capacitors are +-20 % (reference 1.7), and the kit's own 900 Hz Q 4
    is inside that. The tighter consequence -- our magnitude centroid is 14 %
    low -- is in the verification document's fix list, not asserted here as a
    number this suite invented.

    Ground truth: test_audio_measure.test_resonant_peak_matches_the_closed_form_response,
    test_audio_measure.test_bandwidth_q_matches_the_closed_form_response
    """
    ir = mode_impulse_response(dx.M_CBBP)
    fc = am.resonant_peak(ir, SR).require("CB band-pass centre")
    q = am.bandwidth_q(ir, SR).require("CB band-pass Q")
    assert abs(fc / 1100.0 - 1) <= 0.25, f"CB band-pass centre {fc:.0f} Hz, measured 1100 Hz"
    assert abs(q / 2.8 - 1) <= 0.60, f"CB band-pass Q {q:.2f}, measured 2.8"
    assert fc < 1800.0, "SOS's 2.64 kHz centre is refuted by the recording; do not drift back to it"


def test_cowbell_decay_matches_a_real_machine():
    """[hardware-measured: docs/drum-verification.md section 4.6] Roland's chart
    says 50 ms and reference 9 reads the two-slope envelope off the schematic,
    but neither gives a time constant. A real machine, fitted over -3 to -30 dB,
    rings with **tau 98 ms** -- past 700 ms in the tail. Contract revision 6
    sets E_CBB to 100 ms from this measurement (DR 0010), where revision 5 had
    30. +-40 %, which is wide: it is one machine's envelope.

    An 808 cowbell that has stopped in a quarter of a second is not the sound,
    and the chart's 50 ms is the reason nobody noticed: read as T20 it is very
    nearly what the kit produces.

    Ground truth: test_audio_measure.test_rms_envelope_is_the_right_envelope_for_a_broadband_voice,
    test_audio_measure.test_decay_tau_recovers_a_known_time_constant
    """
    y = one_hit(dx.CB, 1.0, 1.0).after_hit(0, 1.0, "body")
    tau = am.decay_tau(y, SR, start_s=PRE_ROLL_S + 0.002, envelope="rms", rms_window_ms=3.0,
                       max_residual_db=8.0).require("CB tau")
    assert abs(tau / 0.098 - 1) <= 0.40, (
        f"cowbell tau {tau*1e3:.1f} ms against a real machine's 98 ms "
        f"(T20 {t20_from_tau(tau)*1e3:.0f} ms against its 76 ms) -- "
        f"docs/drum-verification.md section 4.6")


# ===========================================================================
# CH / OH -- high-pass corners, decays, choke
# ===========================================================================
HATS = (("CH", dx.CH, dx.M_CHHP, 11700.0), ("OH", dx.OH, dx.M_OHHP, 7800.0))


def hat_tau(stop: int, seconds: float, kit=None, name: str = "") -> float:
    """A hat's amplitude time constant: short-time RMS envelope (the voice is a
    dense comb, so its instantaneous amplitude beats), fitted from 5 ms after
    the strike so the attack transient is not mixed into the ring."""
    r = one_hit(stop, 1.0, seconds, kit=kit, name=name or dx.STOP_NAMES[stop])
    x = r.after_hit(0, seconds, "body")
    return am.decay_tau(x, SR, start_s=PRE_ROLL_S + 0.005, envelope="rms", rms_window_ms=3.0,
                        max_residual_db=8.0).require(f"{dx.STOP_NAMES[stop]} tau")


@pytest.mark.parametrize("name,stop,mode,corner", HATS)
def test_hat_highpass_corner(name, stop, mode, corner):
    """[source-inferred: reference 11, the Sallen-Key values read from SN p.13
    with the reading Werner uses for the cymbal's Hh1] CH 11.7 kHz, OH 7.8 kHz,
    both Q 2.5. The corners are what separate the two hats: they share a source
    and differ only in envelope and high-pass.

    Measured from the transfer response of a controlled probe into that mode --
    NOT from the voice's spectrum, and NOT from a centroid, which is a
    different quantity and was read as a corner twice today.

    Which quantity, exactly: reference 11 gives the Sallen-Key's NATURAL
    frequency f0, and for Q 2.5 that is neither the -3 dB point (about 28 %
    below f0) nor the response maximum (about 4 % above it). The peak is
    measured and converted back to f0. Comparing the measured -3 dB corner with
    the table's f0 instead makes this filter look 22 % wrong when it is 2 %
    right. Inferred, so +-15 %.

    Ground truth: test_audio_measure.test_natural_frequency_from_peak_matches_the_closed_form,
    test_audio_measure.test_resonant_peak_matches_the_closed_form_response
    """
    ir = mode_impulse_response(mode)
    p = am.resonant_peak(ir, SR).require(f"{name} resonant peak")
    f0 = am.natural_frequency_from_peak(p, 2.5)
    assert abs(f0 / corner - 1) <= 0.15, \
        f"{name} high-pass f0 {f0:.0f} Hz (peak {p:.0f} Hz at Q 2.5), reference {corner:.0f} Hz"


def test_ch_and_oh_corners_differ_by_the_reference_ratio():
    """[source-inferred: reference 11] 11700 / 7800 = 1.500. The ratio is far
    more robust than either corner alone -- it survives whatever warping the
    digital filter applies to both -- so it is asserted at +-5 % although the
    corners themselves are inferred. The two hats sharing a source and
    differing in high-pass is reference 11 and reference 13 hypothesis 2.

    Ground truth: test_audio_measure.test_resonant_peak_matches_the_closed_form_response,
    test_audio_measure.test_natural_frequency_from_peak_matches_the_closed_form
    """
    ch = am.resonant_peak(mode_impulse_response(dx.M_CHHP), SR).require("CH peak")
    oh = am.resonant_peak(mode_impulse_response(dx.M_OHHP), SR).require("OH peak")
    assert abs((ch / oh) / 1.5 - 1) <= 0.05, f"CH/OH ratio {ch/oh:.3f}, reference 11700/7800 = 1.500"


def test_ch_and_oh_decays():
    """[source-verified: chart 1.6, CH 50 ms fixed and OH 90 / 450 / 600 ms] The
    closed hat's envelope is fixed and short, the open hat's long and variable,
    and that contrast is most of what makes a hi-hat pattern sound like an 808.

    Roland's chart does not define "decay time"; reference 1.6 reads it as
    about T20, so tau is converted and the chart figures are given the width
    that inference deserves -- +-50 % on the closed hat's single figure, and
    the open hat only has to land inside its own chart RANGE.

    A hat is a dense inharmonic comb, so its instantaneous amplitude beats by
    tens of dB and the envelope is the short-time RMS, not the analytic one --
    on the analytic envelope the open hat appears to grow for 50 ms. The fit
    also starts after the strike transient, which is a separate, much faster
    exponential.

    Ground truth: test_audio_measure.test_t20_is_ln10_times_tau,
    test_audio_measure.test_rms_envelope_is_the_right_envelope_for_a_broadband_voice
    """
    ch = hat_tau(dx.CH, 0.6)
    oh = hat_tau(dx.OH, 1.4)
    t_ch, t_oh = t20_from_tau(ch), t20_from_tau(oh)
    assert abs(t_ch / 0.050 - 1) <= 0.50, f"CH T20 {t_ch*1e3:.0f} ms, chart 50 ms"
    assert 0.090 <= t_oh <= 0.600, f"OH T20 {t_oh*1e3:.0f} ms, chart range 90-600 ms"
    assert t_oh >= 3 * t_ch, f"OH {t_oh*1e3:.0f} ms is not meaningfully longer than CH {t_ch*1e3:.0f} ms"


def test_oh_decay_control_spans_the_chart_range():
    """[source-verified: chart 1.6, OH 90 / 450 / 600 ms; the VR3 RC range of
    47 ms to 0.99 s is reference 11 and is inferred] Like the bass drum, the
    RANGE and not a point. Each chart decay is written as an envelope rate --
    converting with T20 = ln(10)*tau, since that is what the chart is -- and
    measured back at +-30 %.

    Ground truth: test_audio_measure.test_t20_is_ln10_times_tau,
    test_audio_measure.test_rms_envelope_is_the_right_envelope_for_a_broadband_voice
    """
    got = []
    for chart in (0.090, 0.450, 0.600):
        tau_target = chart / am.TAU_TO_T20
        kit = [(a, dx.rate_reg(tau_target) if a == dx.A_ENV + dx.E_OH * dx.ENV_STRIDE + 2 else v)
               for a, v in dx.kit_808()]
        got.append(t20_from_tau(hat_tau(dx.OH, 1.8, kit=kit, name=f"OH-decay-{chart}")))
    assert got == sorted(got), f"OH DECAY not monotone: {[round(v*1e3) for v in got]} ms"
    for chart, d in zip((0.090, 0.450, 0.600), got):
        assert abs(d / chart - 1) <= 0.30, f"OH DECAY at chart {chart*1e3:.0f} ms measured T20 {d*1e3:.0f} ms"
    assert got[-1] / got[0] >= 4.0, f"OH DECAY spans only {got[-1]/got[0]:.1f}x; the chart spans 6.7x"


def test_ch_chokes_oh():
    """[source-verified: SN p.6, reference 11] "When the CLOSED HI-HAT (CH) is
    triggered while the OH circuit is activated, Q23 turns on... At this moment,
    the decay time of the OH circuit terminates." The classic hi-hat choke is
    in the voice circuit, not the sequencer.

    Compared at ABSOLUTE level against the unchoked render -- nothing is
    normalised first, because the whole claim is about level.

    Ground truth: test_audio_measure.test_compare_does_not_hide_a_gain_error,
    test_audio_measure.test_rms_envelope_is_the_right_envelope_for_a_broadband_voice
    """
    at = int(PRE_ROLL_S * SR)
    choked = render([(at, dx.OH, 1.0), (at + int(0.10 * SR), dx.CH, 1.0)], 1.0 + PRE_ROLL_S,
                    name="OH-choked", controls=dict(choke_at_s=0.10))
    free = one_hit(dx.OH, 1.0, 1.0, name="OH-free")
    assert [h["stop_name"] for h in choked.manifest["hits"]] == ["OH", "CH"], \
        "the choked render's manifest does not describe an OH then a CH"
    i = at + int(0.25 * SR)
    e_choked = float(am.rms_envelope(choked.body, 3.0, SR)[i])
    e_free = float(am.rms_envelope(free.body, 3.0, SR)[i])
    drop = am.db(e_choked, e_free)
    assert drop <= -30.0, \
        f"CH choked OH by only {-drop:.1f} dB at 250 ms (absolute levels {e_choked:.1f} vs {e_free:.1f})"


# ===========================================================================
# CP -- handclap
# ===========================================================================
def clap_envelope(reps: int = 12, seconds: float = 0.28):
    """The clap's envelope, averaged over renders whose strike frame is offset
    so the one noise source lands differently each time. The burst structure is
    deterministic and survives; the noise averages down. A single render's
    envelope has maxima everywhere and cannot be read."""
    outs = []
    for k in range(reps):
        at = int(PRE_ROLL_S * SR) + k * 137
        r = render([(at, dx.CP, 1.0)], seconds + PRE_ROLL_S + (k * 137 + 16) / SR,
                   name=f"CP-{k}")
        outs.append(r.mix[at - int(PRE_ROLL_S * SR):at - int(PRE_ROLL_S * SR) + int(seconds * SR)])
    return am.average_envelope(outs)


def test_clap_is_three_bursts_about_ten_ms_apart_inside_thirty_ms():
    """[source-verified: reference 13 hypothesis 4, SN p.6 + Fig. 13] "A 30 ms
    window containing three sawtooth-envelope bursts... plus a separate
    transistor-VCA reverberation tail." Roland's own account: the relaxation
    oscillator is stopped once the process has "advanced to the middle of the
    third time".

    THREE bursts inside 30 ms is source-verified and asserted exactly. The
    10-12 ms period is source-inferred -- reference 18 says the comparator
    threshold that fixes it was not solved -- so the spacing is only required to
    be 8-14 ms. Descending levels are Fig. 13-4 and are asserted as an
    ordering, never as levels: the tail-to-burst ratio is reference 18's open
    item.

    Ground truth: test_audio_measure.test_envelope_bursts_finds_known_restrikes,
    test_audio_measure.test_envelope_bursts_on_a_single_decay_finds_one
    """
    e = clap_envelope()
    bursts = am.envelope_bursts(e, SR, window_s=PRE_ROLL_S + 0.030, level_frac=0.4, min_sep_s=0.005)
    times = [t - PRE_ROLL_S for t, _ in bursts]
    assert len(bursts) == 3, \
        f"{len(bursts)} bursts in the first 30 ms, at {[round(t*1e3, 1) for t in times]} ms; reference 3"
    for gap in [b - a for a, b in zip(times, times[1:])]:
        assert 0.008 <= gap <= 0.014, f"burst spacing {gap*1e3:.1f} ms outside the inferred 8-14 ms"
    levels = [lv for _, lv in bursts]
    assert levels == sorted(levels, reverse=True), f"bursts do not descend: {[round(v, 2) for v in levels]}"
    everything = am.envelope_bursts(e, SR, level_frac=0.4, min_sep_s=0.005)
    late = [t - PRE_ROLL_S for t, _ in everything if t > PRE_ROLL_S + 0.030]
    assert not late, \
        f"bursts at {[round(t*1e3, 1) for t in late]} ms, after the 30 ms window the comparator closes"


def test_clap_tail_time_constant():
    """[source-inferred: reference 7, Q69 charges C138 0.047 uF and it decays
    through R348 1 M] tau about 47 ms, and Roland's chart says 100 ms, which is
    2.1 tau. Inferred, so +-40 %, fitted after the bursts have stopped.

    Fitted with is_envelope=True: this is already an envelope, and taking the
    analytic envelope of an envelope reads a 47 ms tail as 89 ms.

    Ground truth: test_audio_measure.test_decay_tau_on_an_already_made_envelope,
    test_audio_measure.test_envelope_bursts_finds_known_restrikes
    """
    e = clap_envelope()
    tau = am.decay_tau(e, SR, start_s=PRE_ROLL_S + 0.040, is_envelope=True,
                       max_residual_db=9.0).require("clap tail")
    assert abs(tau / 0.047 - 1) <= 0.40, f"clap tail tau {tau*1e3:.1f} ms, reference 47 ms"


def test_clap_band_pass():
    """[source-inferred: reference 7, the IC21 bridged-T read from SN p.9]
    f0 about 1.07 kHz, Q about 1.6, and this one filter feeds both VCAs.
    Inferred, so +-20 % on the centre and +-40 % on the Q -- reference 1.7
    allows +-50 % on any Q. Measured from the transfer response of a controlled
    probe, not from the clap's own spectrum.

    Ground truth: test_audio_measure.test_resonant_peak_matches_the_closed_form_response,
    test_audio_measure.test_bandwidth_q_matches_the_closed_form_response
    """
    ir = mode_impulse_response(dx.M_CPBP)
    peak = am.resonant_peak(ir, SR).require("clap band-pass centre")
    q = am.bandwidth_q(ir, SR).require("clap band-pass Q")
    assert abs(peak / 1071.0 - 1) <= 0.20, f"clap band-pass centre {peak:.0f} Hz, reference 1071 Hz"
    assert abs(q / 1.6 - 1) <= 0.40, f"clap band-pass Q {q:.2f}, reference 1.6"


def test_clap_is_noise_and_not_an_oscillator_bank():
    """[source-verified: SN p.6 "White noise passed through the band pass
    filter", and reference 1.4, which lists CP among the noise consumers] The
    complement of the hat test with the same measurement, and the control that
    stops the hats' thresholds being satisfiable by any signal at all: the
    clap's line positions must NOT be stable from window to window.

    Ground truth: test_audio_measure.test_line_stability_separates_oscillators_from_noise
    """
    x = one_hit(dx.CP, 1.0, 0.30).after_hit(0, 0.25)
    stab = am.line_stability(x, (600.0, 4000.0), SR, windows=4, tol_hz=40.0,
                             threshold=2.0).require("clap line stability")
    assert stab <= 0.40, f"the clap's lines were {stab:.2f} stable; it is band-passed white noise"


# ===========================================================================
# meta -- this suite must be able to fail, and must say what it claims
# ===========================================================================
def test_meta_every_test_declares_status_and_ground_truth():
    """[meta] Every test opens with its claim status, and every test that
    measures something names the ground-truth test in
    `model/test_audio_measure.py` that backs the estimator it uses -- and that
    test must exist. "Verified in a source" and "validated by our own
    measurement" are different claims, and an acceptance suite that blurs them
    is how an inference becomes a fact."""
    import test_808_acceptance as mod
    import test_audio_measure as gt
    tags = ("[source-verified:", "[source-inferred:", "[hardware-measured:",
            "[measured-here:", "[defect:", "[method]", "[meta]")
    known = {n for n in vars(gt) if n.startswith("test_")}
    missing_tag, missing_gt, unknown_gt = [], [], []
    for name, fn in sorted(vars(mod).items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        doc = (fn.__doc__ or "").lstrip()
        if not doc.startswith(tags):
            missing_tag.append(name)
            continue
        if name.startswith("test_meta_"):
            continue
        m = re.search(r"Ground truth:\s*(.+)$", doc, re.S)
        if not m:
            missing_gt.append(name)
            continue
        for ref in re.findall(r"test_audio_measure\.(\w+)", m.group(1)):
            if ref not in known:
                unknown_gt.append(f"{name} -> {ref}")
    assert not missing_tag, f"tests without a claim-status tag: {missing_tag}"
    assert not missing_gt, f"tests that name no estimator ground truth: {missing_gt}"
    assert not unknown_gt, f"ground-truth tests that do not exist: {unknown_gt}"
    assert NOT_ASSERTED, "the could-not-establish list must stay in this file"
    live = {n for n in vars(mod) if n.startswith("test_")}
    stale = [n for n in KNOWN_DEFECTS if n not in live]
    assert not stale, f"KNOWN_DEFECTS names tests that no longer exist: {stale}"


def test_meta_render_manifest_describes_what_was_played():
    """[meta] Three hits at three levels are not three DECAY settings -- they
    might be three accents, and reading a file's layout as a control sweep is
    one of the ways today's false reports happened. So every render carries a
    manifest, and assertions read it. This checks the manifest is real: the
    hits it lists are the hits that were asked for, the control settings are
    recorded, and the coefficients are the ones in the registers."""
    at = int(PRE_ROLL_S * SR)
    r = render([(at, dx.BD, 1.0), (at + 24000, dx.BD, 0.6), (at + 48000, dx.SD, 1.4)],
               1.6, controls=dict(example="accents, not decay settings"), name="manifest")
    m = r.manifest
    assert [h["stop_name"] for h in m["hits"]] == ["BD", "BD", "SD"]
    assert [h["accent"] for h in m["hits"]] == [1.0, 0.6, 1.4]
    assert abs(m["hits"][1]["time_s"] - (at + 24000) / SR) < 1e-9
    assert m["controls"]["example"] == "accents, not decay settings"
    if STUB:
        return
    assert len(m["osc_hz"]) == 6 and m["noise_seed"] is not None
    f, t = am.poles_to_freq_tau(m["coefficients"][dx.M_BD]["a1"],
                                m["coefficients"][dx.M_BD]["a2"], SR)
    assert abs(f.require("manifest BD f0") - dx.BD_HZ) < 1.0
    # floor_db is tightened from the -50 default because the bass drum's tail
    # now runs to -48 dB at 1.26 s -- tau is 144 ms since DR 0009, and the
    # attack window of 15.7.1 leaves a small step in it -- and a rise 48 dB
    # down is a tail wobble, not a fourth hit. -40 dB is well clear of both:
    # every hit here peaks within 6 dB of the loudest.
    onsets = am.onsets(r.mix, SR, min_gap_s=0.1, floor_db=-40.0)
    assert len(onsets) == 3, f"the audio holds {len(onsets)} onsets, the manifest lists 3"
    for got, h in zip(onsets, m["hits"]):
        assert abs(got - h["frame"]) < 0.012 * SR, \
            f"onset at {got/SR:.4f} s against manifest {h['time_s']:.4f} s"


def test_meta_decay_range_check_rejects_a_frozen_control():
    """[meta] The injected-bug control for the bass-drum decay range
    (docs/verification-rules.md rule 2), and the exact shape of the defect
    reported on 2026-09-17: a DECAY control wired to do nothing. Three
    "settings" that all load the mid coefficients must be rejected by the same
    check test_bd_decay_control_spans_roland_s_chart_range applies. If this
    passes silently, that test is not a test."""
    if STUB:
        pytest.skip("a negative control is meaningless against a stub")
    taus = []
    for knob, _, tau_ref in BD_DECAY:
        r = bd_at_decay(knob, dx.bd_decay_q(5.0), BD_DECAY[1][2])   # the same Q at every "setting"
        taus.append(am.decay_tau(r.after_hit(0, 1.2, "body"), SR).require("frozen tau"))
    assert max(taus) / min(taus) < 1.05, "the frozen control was not frozen"
    with pytest.raises(AssertionError):
        assert taus[-1] / taus[0] >= 8.0, "the range check must reject a control that does nothing"


def test_meta_bd_attack_check_passes_when_the_attack_window_is_written():
    """[meta] A positive control for the two failing bass-drum attack tests: a
    test that cannot pass is not evidence of a defect, it is a broken test. The
    attack window is written here by hand -- 130 Hz Q 6 for 4 ms, then the
    steady preset, exactly what reference 2 describes and what
    `drums_fx_render.py::bd_attack_shift` already demonstrates a host can do --
    and the same two measurements those tests make must then succeed.

    So when kit_808() grows an attack window, those tests go green; until it
    does, they are red for a real reason."""
    if STUB:
        pytest.skip("a positive control is meaningless against a stub")
    at = int(PRE_ROLL_S * SR)
    attack = [(at, a, v) for a, v in dx.mode_writes(dx.M_BD, 130.0, 6.1, 0.0)[:2]]
    steady = [(at + 192, a, v) for a, v in dx.mode_writes(dx.M_BD, dx.BD_HZ, dx.bd_decay_q(5.0), 0.0)[:2]]
    r = render([(at, dx.BD, 1.0)], 0.6 + PRE_ROLL_S, extra_writes=attack + steady,
               controls=dict(attack_hz=130.0, attack_ms=4.0), name="BD-attack-control")
    f = am.damped_sinusoid(r.body[at:at + int(0.004 * SR)], SR).freq.require("attack frequency")
    assert 130.0 * 0.75 <= f <= 130.0 * 1.25, f"the audio check cannot pass even so: {f:.1f} Hz"
    early = render([(at, dx.BD, 1.0)], PRE_ROLL_S + 0.002, extra_writes=attack,
                   name="BD-attack-control-early")
    cf = coef_freq_tau(early, dx.M_BD)[0].require("attack coefficients")
    assert 130.0 * 0.75 <= cf <= 130.0 * 1.25, f"the control-path check cannot pass even so: {cf:.1f} Hz"


def test_meta_tom_pitch_check_passes_when_a_drop_is_written():
    """[meta] The positive control for the two failing tom pitch-drop tests. A
    coefficient ramp from 1.5x down to the small-signal frequency over about
    two time constants -- reference 4's "a decaying pitch offset of +40 % -> 0
    over about 2 tau", the cheap option it offers -- is written by hand, and
    the same measurement must then see the fall."""
    if STUB:
        pytest.skip("a positive control is meaningless against a stub")
    at = int(PRE_ROLL_S * SR)
    extra = []
    for k in range(17):
        f = 135.0 + (90.0 - 135.0) * k / 16.0
        extra += [(at + int(k * 0.006 * SR), a, v) for a, v in dx.mode_writes(dx.M_LT, f, 25.0, 0.0)[:2]]
    r = render([(at, dx.LT, 1.4)], 1.0 + PRE_ROLL_S, extra_writes=extra,
               controls=dict(pitch_ramp_hz=(135.0, 90.0), ramp_s=0.096), name="LT-drop-control")
    first, settled = _pitch_of(r)
    assert first / settled >= 1.05, f"the pitch-drop check cannot pass even so: {first/settled:.3f}x"
    assert 1.2 <= first / settled <= 2.0, \
        f"the magnitude check cannot pass even so: {first/settled:.3f}x"


@pytest.mark.parametrize("stub", ["silent", "noise"])
def test_meta_red_suite_fails_against_a_stub(stub):
    """[meta] docs/verification-rules.md rule 1: a harness nobody has watched
    fail is not a harness. This re-runs the whole suite, minus the meta tests,
    against a drum section with the right interface and no 808 in it -- silence,
    and plausible-but-wrong enveloped noise -- and requires it to go red.

    By hand:  TR808_STUB=silent .venv/bin/python -m pytest
    model/test_808_acceptance.py -q
    """
    if STUB:
        pytest.skip("already running under a stub")
    env = dict(os.environ, TR808_STUB=stub)
    env.pop("PYTEST_CURRENT_TEST", None)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", os.path.abspath(__file__), "-q", "--tb=no",
         "-p", "no:cacheprovider", "-k", "not meta"],
        capture_output=True, text=True, env=env, cwd=HERE)
    out = r.stdout + r.stderr
    n = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error|errors|skipped)", out)}
    passed = n.get("passed", 0)
    red = n.get("failed", 0) + n.get("error", 0) + n.get("errors", 0)
    assert r.returncode != 0, f"the suite PASSED against a {stub} drum model:\n{out[-2000:]}"
    assert red >= 3 * max(passed, 1), \
        f"{stub} stub: {red} red, {passed} green -- too many tests pass vacuously:\n{out[-2000:]}"
