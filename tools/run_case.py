#!/usr/bin/env python3
"""Fill the scorecard: render our side, load the reference side, measure, write
the result JSON that `tools/scorecard.py` renders.

    tools/run_case.py D01A                     one case
    tools/run_case.py --batch "First 32"       a batch from docs/scorecard/cases.csv
    tools/run_case.py --list                   what is covered, what is not, and why
    tools/run_case.py --inject REF_F0_20PCT D01A --results /tmp/x   an injected control

`docs/scorecard/cases.csv` names 100 cases and `tools/scorecard.py` renders the
board from `docs/scorecard/results/<case_id>.json`. Until this file existed,
nothing wrote those. This does.

WHAT IT REFUSES TO DO, because each is a way a scorecard starts lying
---------------------------------------------------------------------

**An invalid measurement gets no distance, not zero.** Every estimator here
returns `audio_measure.Estimate`, which may be a refusal. A refusal is written
as `"valid": false` with the reason and **no `error` key at all**. Zero would
read on the board as a perfect match.

**A case we cannot run is not quietly dropped.** It is either written as a
no-verdict with the reason (we tried, the apparatus said no) or listed by
`--list` as deliberately not run with the reason (we did not try, and why).
Both are in `COVERAGE` below; neither is silent.

**Every result names its engine.** `fixed-model` for everything here: the
integer models `model/drums_fx.py` and `model/voice_fx.py`, in this process,
never a committed WAV. No case here has been measured on the integrated RTL,
and `tools/scorecard.py` says so out loud on the board.

**Tolerances are frozen before the measurement, from the reference's own
documentation, and are never per case.** Three classes, chosen before any
number was computed (see `TOLERANCE_POLICY`). Retuning a tolerance after
seeing an error is fitting around a deficiency, and the board would still
look green.

**The apparatus asserts its preconditions at the point of use and REFUSES
rather than reports.** The reference corpus must be present, the named file
must exist, the sound must be in the kit, and the reference clip must not be
silent. Each failure produces a stated no-verdict, never a number.

**And it asserts the premise of the BATCH before any of it runs.** An earlier
run of this file returned eight honest per-case refusals -- "the eight-stop kit
does not implement LC / MT / MC / HC / CL / RS / MA / CY" -- from a worktree
that was two commits behind `origin/main`, where the complete sixteen-sound kit
had already landed. Every one of those records was true of the tree it had and
false about the project, and eight of them together read as a permanent hole in
the instrument. `base_check` now refuses the whole batch when the tree is
behind `origin/main` or its drum-circuit count differs from it, because a stale
premise is a property of the checkout and must never come out looking like a
property of the instrument.

THE CONTROLS (`--inject`)
-------------------------

A runner's only failure mode that matters is a false green, so the two states
that are easy to get wrong are injectable and are checked in
`tools/test_run_case.py` and by `make controls`:

    REF_F0_20PCT   shift the reference pitch by 20 %, which is twice the
                   frequency tolerance: the case MUST come back `fail`
    REF_MISSING    point the reference at a file that is not there: the case
                   MUST come back `no verdict`, with a stated reason

`--inject` refuses to write into `docs/scorecard/results`. A control's output
is not evidence about the instrument and must never be mistaken for it.

PROVENANCE, AND THE EXIT CODE
-----------------------------

Nothing else in this repository records what it ran against -- no verifier here
calls `rev-parse` -- so a result cannot be told apart from a stale one, and with
many worktrees live at once that is not hypothetical. Every result carries a
`provenance` block: the commit AND a hash of the uncommitted tree (a clean SHA
that silently means "plus whatever was in the working tree" is worse than no
SHA), the exact command and configuration, content hashes of every generated
input including the reference recording, the path to the raw artefact so a
number can be re-derived rather than re-trusted, and the engine.
`tools/scorecard.py` gives **no verdict** to a result without one.

The exit status follows the repository's verifier convention, and the same code
is written onto each record as `provenance.outcome_code`:

    0  match         every requested case passed
    1  mismatch      at least one case was measured and scored badly -- a RESULT
    2  did not run   at least one case produced no evidence: no verdict, not run,
                     or an internal error

A case with no evidence and a case that was measured and failed need opposite
responses, so they are never the same code and never the same cell on the board.
`--expect` switches to control semantics: exit 0 exactly when every case landed
in the stated state.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import traceback
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "audition"))

import numpy as np                                                   # noqa: E402
from scipy.io import wavfile                                         # noqa: E402
from scipy.signal import butter, sosfiltfilt                         # noqa: E402

import audio_measure as am                                           # noqa: E402
import drum_verify as dv                                             # noqa: E402

CASES_CSV = ROOT / "docs" / "scorecard" / "cases.csv"
RESULTS = ROOT / "docs" / "scorecard" / "results"
AUDIO_OUT = ROOT / "build" / "scorecard"

ENGINE = "fixed-model"          # the integer model, rendered in this process
SR_OURS = 48000

# The reference corpus. Not committed -- fetch it yourself:
#   git clone --depth 1 https://github.com/tidalcycles/sounds-tr808-fischer /tmp/tr808-ref
REFS_ENV = "GF180_TR808_REFS"
REFS_DEFAULT = "/tmp/tr808-ref"
REF_ID = ("Fischer/Technopolis 1994, CC0-1.0 via TidalCycles, real TR-808 "
          "s/n 103852, individual voice outputs, 16-bit/44.1 kHz")


# ===========================================================================
# 1. The tolerance policy. Frozen here, before any measurement, and sourced.
# ===========================================================================
TOLERANCE_POLICY = {
    "frequency": "10 % of the reference value -- the TR-808's own component "
                 "tolerance on an oscillator's f0 (docs/tr808-reference.md 1.7)",
    "time": "50 % of the reference value -- 1.7 states +-50 % on Q, and for "
            "these bridged-T resonators tau is proportional to Q",
    "energy ratio": "3 dB, the half-power convention. A stated convention, not "
                    "a number derived from any error of ours",
    "event timing": "10 ms -- the positional accuracy audio_measure.onsets "
                    "states for itself; a failure is larger than the estimator's "
                    "own resolution",
    "bus sum": "0.5 dB -- the final output must be the sum of the per-bus stems",
    "rail": "0.01 % of samples at the rail, a stated budget for a render with "
            "no limiter in the path",
}


def tol_frequency(ref: float, ctx: dict) -> tuple:
    return abs(ref) * 0.10, "frequency"


def tol_frequency_of_f0(ref: float, ctx: dict) -> tuple:
    """For a metric that is a DIFFERENCE of two frequencies, 10 % of a
    difference is not the machine's tolerance -- 10 % of the voice's own
    steady f0 is."""
    f0 = ctx.get("ref_f0")
    if f0 is None:
        return abs(ref) * 0.10, "frequency"
    return abs(f0) * 0.10, "frequency (10 % of the reference steady f0)"


def tol_time(ref: float, ctx: dict) -> tuple:
    return abs(ref) * 0.50, "time"


def tol_db(ref: float, ctx: dict) -> tuple:
    return 3.0, "energy ratio"


def tol_fixed(value: float, basis: str):
    def f(ref: float, ctx: dict) -> tuple:
        return value, basis
    return f


# ===========================================================================
# 2. Estimators
#
# Everything that can be is `model/audio_measure.py`, which is ground-truthed
# against closed-form signals in `model/test_audio_measure.py`. The four added
# here are ground-truthed the same way in `tools/test_run_case.py`, named on
# each function -- six estimator bugs were found the day that suite was
# written, and an estimator that has never met a signal with a known answer is
# not a measurement.
# ===========================================================================
def band_ratio_db(x, sr: int, split_hz: float, lo: float = 0.0,
                  hi: float | None = None, *, floor_db: float = -80.0) -> am.Estimate:
    """10*log10(energy above `split_hz` / energy below it), both inside
    [lo, hi]. The dimensionless balance the drum work reports as a body/air or
    body/noise split, in a unit that combines with a dB tolerance.

    The energy comes from `audio_measure.band_energy`, which filters rather
    than summing FFT bins. That is not a detail: `spectrum` applies a Hann
    window, so on a decaying voice it weights the middle of the file and
    reports the TAIL's spectrum instead of the event's energy -- on a real
    TR-808 cymbal the two disagree by a factor of four in the 5-9 kHz band,
    and the windowed answer is the misleading one. This function summed FFT
    bins until that was found.

    Refuses when either side is empty, or when the ratio is past `floor_db`:
    a band with nothing in it has no balance, it has an absence.

    Ground truth: test_band_ratio_db_of_two_sines_is_their_amplitude_ratio."""
    hi = min(sr / 2.0 - 1.0, 20000.0 if hi is None else hi)
    lo = max(lo, 1.0)
    if hi <= split_hz or split_hz <= lo:
        return am.Estimate(None, False, "the split is outside the band",
                           dict(lo=lo, split=split_hz, hi=hi))
    e_lo, e_hi = am.band_energy(x, ((lo, split_hz), (split_hz, hi)), sr)
    if e_lo <= 0.0 or e_hi <= 0.0:
        return am.Estimate(None, False, "one side of the split holds no energy",
                           dict(e_lo=e_lo, e_hi=e_hi))
    r = 10.0 * math.log10(e_hi / e_lo)
    if r < floor_db or r > -floor_db:
        return am.Estimate(None, False, "band ratio past the stated floor",
                           dict(ratio_db=r, floor_db=floor_db))
    return am.Estimate(r, True, "", dict(e_lo=e_lo, e_hi=e_hi))


def band_pair_db(x, sr: int, band_a, band_b, *, floor_db: float = -80.0) -> am.Estimate:
    """10*log10(energy in `band_a` / energy in `band_b`), for a voice whose
    balance is between two named partials rather than either side of one
    split -- the rimshot's two bridged-T modes, the cymbal's bands.

    Ground truth: test_band_pair_db_of_two_sines_is_their_amplitude_ratio."""
    e_a, e_b = am.band_energy(x, (tuple(band_a), tuple(band_b)), sr)
    if e_a <= 0.0 or e_b <= 0.0:
        return am.Estimate(None, False, "one of the two bands holds no energy",
                           dict(e_a=e_a, e_b=e_b))
    r = 10.0 * math.log10(e_a / e_b)
    if r < floor_db or r > -floor_db:
        return am.Estimate(None, False, "band ratio past the stated floor",
                           dict(ratio_db=r, floor_db=floor_db))
    return am.Estimate(r, True, "", dict(e_a=e_a, e_b=e_b))


def pitch_drop_hz(x, sr: int, band, *, early=(0.004, 0.018), late=(0.060, 0.150),
                  smooth_ms: float = 3.0) -> am.Estimate:
    """How far the voice's pitch falls between an early and a late window, in
    Hz, from the analytic phase derivative (`audio_measure.instantaneous_
    frequency`, ground-truthed against a known glide) of the band-limited body.

    NOT two windowed FFTs. A 30 ms window holds under three periods of a 90 Hz
    tom, so a spectrum of it cannot resolve the pitch at all, and the first
    version of this measurement was that -- it read the reference's drop as
    1.2 Hz where a phase derivative reads 7.

    Refuses when either window falls below `-30 dB` of the peak envelope,
    where the phase derivative is noise.

    **Its floor is about 2 Hz** -- the band-pass transient biases the early
    window by that much on a tone that does not move at all
    (`test_pitch_drop_hz_is_zero_for_a_steady_tone`). A reading inside +-2 Hz
    is "no measurable sweep", not "a small sweep".

    Ground truth: test_pitch_drop_hz_on_a_known_exponential_glide."""
    lo, hi = band
    x = np.asarray(x, dtype=np.float64)
    if am.is_silent(x):
        return am.Estimate(None, False, "silent", {})
    from scipy.signal import butter as _butter, sosfiltfilt as _sos
    sos = _butter(4, [max(lo, 5.0) / (sr / 2.0), min(hi, sr / 2.0 - 1.0) / (sr / 2.0)],
                  btype="band", output="sos")
    y = _sos(sos, x)
    env = am.analytic_envelope(y)
    fi = am.instantaneous_frequency(y, sr, smooth_ms=smooth_ms)
    pk = float(env.max())
    out = []
    for name, (t0, t1) in (("early", early), ("late", late)):
        a, b = int(t0 * sr), min(len(fi), int(t1 * sr))
        if b - a < 16:
            return am.Estimate(None, False, f"{name} window too short", dict(n=b - a))
        if float(env[a:b].max()) < pk * 10 ** (-30.0 / 20.0):
            return am.Estimate(None, False,
                               f"{name} window is below -30 dB, where the phase "
                               f"derivative is noise", dict(window=name))
        out.append(float(np.median(fi[a:b])))
    return am.Estimate(out[0] - out[1], True, "", dict(early_hz=out[0], late_hz=out[1]))


def attack_ms(x, sr: int, *, window_ms: float = 4.0,
              onset_frac: float = 0.02) -> am.Estimate:
    """Onset to peak of the short-time RMS envelope, in ms.

    The RMS envelope, never the analytic one: a hi-hat's instantaneous
    amplitude beats by tens of dB and its analytic maximum lands on a beat.
    The window smears the answer by up to about one window, which is why the
    ground-truth test states a window-sized bound rather than an exact value,
    and why `docs/drum-verification.md` compares attack ratios rather than
    absolute attack times across different windows.

    Refuses silence and a record whose envelope peaks on its first sample.
    It does NOT refuse an attack faster than its own window -- it cannot see
    one, and reports about a window instead. That floor is stated rather than
    hidden, and it is why both sides of every comparison below are taken with
    the same window.

    Ground truth: test_attack_ms_finds_a_known_linear_rise,
    test_attack_ms_cannot_resolve_an_attack_shorter_than_its_window."""
    x = np.asarray(x, dtype=np.float64)
    if am.is_silent(x):
        return am.Estimate(None, False, "silent", {})
    env = am.rms_envelope(x, window_ms, sr)
    pk = int(np.argmax(env))
    if pk == 0:
        return am.Estimate(None, False, "envelope peaks on the first sample", dict(pk=pk))
    above = np.nonzero(env[: pk + 1] >= onset_frac * env[pk])[0]
    if not len(above):
        return am.Estimate(None, False, "no onset below the peak", dict(pk=pk))
    ms = (pk - int(above[0])) / sr * 1e3
    if ms <= 0.0:
        return am.Estimate(None, False, "no measurable rise", dict(ms=ms))
    return am.Estimate(ms, True, "", dict(peak_index=pk, window_ms=window_ms))


def tone_ratio_db(x, sr: int, hz_num: float, hz_den: float) -> am.Estimate:
    """Level of the line at `hz_num` over the line at `hz_den`, in dB, by
    coherent projection (`audio_measure.tone_amplitude`) at both frequencies.

    Ground truth: test_tone_ratio_db_of_two_known_sines."""
    a = am.tone_amplitude(x, hz_num, sr)
    b = am.tone_amplitude(x, hz_den, sr)
    if not a.ok:
        return am.Estimate(None, False, f"numerator {hz_num:.0f} Hz: {a.reason}", a.detail)
    if not b.ok:
        return am.Estimate(None, False, f"denominator {hz_den:.0f} Hz: {b.reason}", b.detail)
    if a.value <= 0 or b.value <= 0:
        return am.Estimate(None, False, "a line measured at zero amplitude",
                           dict(num=a.value, den=b.value))
    return am.Estimate(20.0 * math.log10(a.value / b.value), True, "",
                       dict(num=a.value, den=b.value))


def worst_event_offset_ms(x, sr: int, scheduled_s, *, group_s: float = 0.020) -> am.Estimate:
    """Worst |detected onset - scheduled time| over a render, in ms.

    Scheduled hits closer together than `group_s` are one event: two stops
    struck in the same frame produce one onset and counting them as two would
    make a correct render look like a miss. Refuses -- rather than matching
    greedily and reporting a plausible number -- when the detected count does
    not equal the scheduled group count, because then the pairing is a guess.

    The detector's minimum gap is taken from the SCHEDULE, at half the smallest
    interval in it. That is a property of the stimulus we wrote, not of the
    result: without it, a bass drum whose T20 (348 ms) outlasts the gap between
    its own hits (363 ms) beats against its own ring and reads 12 onsets where
    10 were written. It is never allowed below `audio_measure.onsets`'s own
    20 ms default, so it can only ever reject rises closer together than the
    stimulus can contain.

    Ground truth: test_worst_event_offset_ms_on_bursts_at_known_times,
    test_worst_event_offset_ms_survives_hits_that_ring_into_each_other."""
    groups: list[float] = []
    for t in sorted(scheduled_s):
        if not groups or t - groups[-1] > group_s:
            groups.append(float(t))
    gaps = [b - a for a, b in zip(groups, groups[1:])]
    min_gap = max(0.020, 0.5 * min(gaps)) if gaps else 0.020
    found = [i / sr for i in am.onsets(x, sr, min_gap_s=min_gap)]
    if len(found) != len(groups):
        return am.Estimate(None, False,
                           "detected onsets do not match the scheduled events",
                           dict(detected=len(found), scheduled=len(groups),
                                min_gap_s=round(min_gap, 4)))
    worst = max(abs(f - g) for f, g in zip(found, groups)) * 1e3
    return am.Estimate(worst, True, "", dict(events=len(groups),
                                             min_gap_s=round(min_gap, 4)))


# ===========================================================================
# 3. Signal preparation, identical on both sides. Nothing is resampled: the
#    references are 44.1 kHz and our renders 48 kHz, and every metric here is
#    rate-independent.
# ===========================================================================
def prepare(x, sr: int) -> np.ndarray:
    """DC out from the PRE-ONSET region, trimmed to 1 ms before the onset,
    peak-normalised.

    **Not by subtracting the mean of the whole buffer, and that is not a style
    choice.** These are single strikes in a buffer seconds long, so the mean of
    the whole thing is a constant offset left across every silent sample after
    the voice has gone. A
    constant has constant energy density and never decays, so it dominates a
    backward-integrated energy curve: it put 0.19 % of the rimshot's energy in
    a floor that never ended and `schroeder_t20` duly reported a **4.5-second**
    T20 for a 15 ms sound. The raw render has no energy at all in its last
    second; the preparation put it there. A 20 Hz zero-phase high-pass removes
    the references' converter DC without adding anything.

    The level-matched copy is what every metric below is taken on, and that is
    not a convenience: the Fischer set states that LEVEL was pinned at maximum
    for every voice, so its levels between voices are not the machine's. Every
    metric here is a frequency, a time or a ratio, all invariant under the
    normalisation; the original-gain peak and RMS are recorded in the result's
    diagnostics so the discarded information is still on record."""
    x = np.asarray(x, dtype=np.float64)
    if am.is_silent(x):
        return x
    pk = float(np.abs(x).max())
    i = int(np.argmax(np.abs(x) > 0.02 * pk))
    lead = max(0, i - int(1e-3 * sr))
    # DC from the PRE-ONSET region, where there is no voice to bias it. Our
    # renders lead with exact digital silence, so this subtracts nothing from
    # them; the references lead with a 1994 converter's offset, so it subtracts
    # that. A zero-phase high-pass would do the job too and was tried, but
    # filtfilt is not causal: a 20 Hz first-order high-pass puts a precursor
    # tens of ms AHEAD of a sharp strike, which moved the trim point back and
    # read the rimshot's 2 ms attack as 11 ms.
    if lead >= int(5e-3 * sr):
        x = x - float(x[:lead].mean())
    y = x[lead:]
    p = float(np.abs(y).max())
    return y / p if p > 0 else y


def window(y, sr: int, t0: float, t1: float | None) -> np.ndarray:
    a = int(t0 * sr)
    b = len(y) if t1 is None else min(len(y), int(t1 * sr))
    return y[a:b]


def highpass(y, sr: int, hz: float, order: int = 4) -> np.ndarray:
    sos = butter(order, hz / (sr / 2.0), btype="highpass", output="sos")
    return sosfiltfilt(sos, y)


# ===========================================================================
# 4. The reference side
# ===========================================================================
# The Fischer file each of the sixteen sounds is compared against, at Roland's
# own June-1981 tuning chart -- every knob at 12 o'clock, the setting the case
# file calls "the documented reference setting". Taken from `model/drum_verify.py`
# rather than copied: a second copy of a reference mapping is a second thing to
# go stale, and this one gained eight entries while this runner was being written.
REF_MAIN = dv.REF_MAIN

class Refused(Exception):
    """A precondition of the apparatus failed. REFUSED is a first-class
    outcome here, distinct from pass and from fail: the case is written as a
    no-verdict carrying this reason, and never as a number."""


def load_reference(voice: str, refdir: pathlib.Path, inject: str = "") -> tuple:
    rel, setting = REF_MAIN[voice]
    if inject == "REF_MISSING":
        rel = "bd8/NO-SUCH-FILE.WAV"
    path = refdir / rel
    if not refdir.exists():
        raise Refused(f"reference corpus not at {refdir} -- clone "
                      f"tidalcycles/sounds-tr808-fischer or set {REFS_ENV}")
    if not path.exists():
        raise Refused(f"reference recording missing: {rel} under {refdir}")
    sr, x = wavfile.read(str(path))
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x / 32768.0
    if am.is_silent(x):
        raise Refused(f"reference recording {rel} is silent")
    if inject == "REF_F0_20PCT":
        # Resample by 1.2 in time, which moves every frequency in it by -20 %:
        # twice the frequency tolerance, so a correct runner must report fail.
        n = int(len(x) * 1.2)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return x, int(sr), rel, setting


# ===========================================================================
# 5. Our side
# ===========================================================================
# The cymbal and the open hat ring for over a second; a render that ends before
# the decay does cannot have its own decay read off it, and `schroeder_t20`
# refuses exactly that. These are `drums_fx_render.solo_renders`'s own spans.
SOLO_SECONDS = {"CY": 3.6, "OH": 3.6}


def render_drum_solo(sound: str, accent: float = 1.0) -> tuple:
    """One hit of one SOUND from the kit that ships, rendered here and now
    through the register interface -- never a committed WAV, so what is
    measured is the design as it stands.

    Sixteen sounds sit on eleven circuits and five of them are pairs sharing
    one, so the circuit is switched to the named sound with `kit_with_sounds`
    before the hit: rendering LC by striking the LT stop would measure the
    low tom and call it a conga."""
    import drums_fx as dx
    if sound not in dx.SOUND_NAMES:
        raise Refused(f"{sound} is not one of the sixteen sounds the kit implements "
                      f"({', '.join(dx.SOUND_NAMES)})")
    stop = dx.SOUND_STOP[sound]
    seconds = SOLO_SECONDS.get(sound, 2.2)
    n = int(seconds * dx.SR)
    d = dx.DrumsFx()
    dm, bd = d.play(dx.hit_writes([(int(0.01 * dx.SR), stop, accent)],
                                  dx.kit_with_sounds(sound)), n)
    g = dx.accent_reg(0.45)
    out = dx.output_fx(np.zeros(n), 0, dm, g, bd, g)
    return np.asarray(out, dtype=np.float64) / 32768.0, dx.SR


def _bass_line(notes, bpm: float, kw: dict, start_s: float, gate_frac: float = 0.9):
    """The patch's own note list placed on the 16th grid of the case's tempo:
    one note every other 16th, so two bars hold eight notes."""
    step = 60.0 / bpm / 4.0
    return [(start_s + i * 2 * step, n, 2 * step, dict(kw, gate=2 * step * gate_frac))
            for i, n in enumerate(notes)]


# Two bars at 124 BPM, the tempo the ensemble cases state. Sparse is the
# reference 808 groove; dense adds the tom and clap rows of
# model/drums_fx_render.py, which puts several stops in the same frame.
PATTERN_DENSE_EXTRA = {"LT": "....x.x.....xx..", "MT": "..x.......x...x.",
                       "HT": "..x.......x...x.", "CP": "....X.......X...",
                       "CB": "x..x..x...x..x.."}


def render_ensemble(patch_name: str, dense: bool, seconds: float = 6.0,
                    bpm: float = 124.0) -> dict:
    """The final output and the per-bus stems, from one render.

    Stems are the SAME buses through the SAME output stage with the other two
    sources zeroed, so "does the output equal the sum of the stems" is a
    question about `drums_fx.output_fx`'s one hard rail and nothing else."""
    import drums_fx as dx
    import voice_fx as vf
    import patches

    name, seq, _ = next(p for p in patches.MONO if p[0].endswith(patch_name))
    kw = dict(seq[0][3])
    notes = [ev[1] for ev in seq]
    n = int(seconds * dx.SR)

    line = _bass_line(notes, bpm, kw, start_s=0.05)
    v = vf.VoiceFx()
    vf.render_mono_fx(line, seconds, v)
    vca = v.trace["vca"]

    pattern = dict(dx.PATTERN_808)
    if dense:
        for k, row in PATTERN_DENSE_EXTRA.items():
            pattern[k] = row
    hits = [h for h in dx.pattern_hits(pattern, bpm=bpm, bars=2, start_s=0.05) if h[0] < n - 2]
    d = dx.DrumsFx()
    dm, bd = d.play(dx.hit_writes(hits, dx.kit_808()), n)

    g = dx.accent_reg(0.45)
    zero = np.zeros(n, dtype=np.int64)
    mix = dx.output_fx(vca, vf.VOL_REF, dm, g, bd, g)
    stems = {
        "voice": dx.output_fx(vca, vf.VOL_REF, zero, 0, zero, 0),
        "drum-mix": dx.output_fx(zero, 0, dm, g, zero, 0),
        "body": dx.output_fx(zero, 0, zero, 0, bd, g),
    }

    # Event timing is asked PER STOP, each row rendered alone through the same
    # path. On the mixed drum bus it cannot be asked at all: a sum of eight
    # voices beats by several dB, so `audio_measure.onsets` finds rises in the
    # tail that are no strike and misses a hat under a ringing kick -- measured,
    # 19 detections against 18 scheduled events, five of them after the last
    # hit. That is a limit of onset detection on a mixture, not of the render,
    # and the well-posed version of the same question is one stop at a time.
    per_stop = {}
    for stop_name in sorted(pattern):
        s_i = dx.SOUND_STOP[stop_name]
        rows = [h for h in hits if h[1] == s_i]
        if not rows:
            continue
        d1 = dx.DrumsFx()
        dm1, bd1 = d1.play(dx.hit_writes(rows, dx.kit_808()), n)
        one = dx.output_fx(zero, 0, dm1, g, bd1, g)
        per_stop[stop_name] = (np.asarray(one, dtype=np.float64),
                               sorted(h[0] / dx.SR for h in rows))

    return dict(mix=np.asarray(mix, dtype=np.float64),
                stems={k: np.asarray(s, dtype=np.float64) for k, s in stems.items()},
                per_stop=per_stop,
                hits_s=sorted(h[0] / dx.SR for h in hits),
                patch=name, bpm=bpm, sr=dx.SR, n=n,
                render="voice_fx %s + drums_fx %s groove, %.0f BPM, 2 bars, "
                       "buses 0.45/0.45, no limiter"
                       % (name, "dense" if dense else "sparse", bpm))


# ===========================================================================
# 6. The measurement plans, one per case.
#
# A plan is a list of (metric name, units, estimator, tolerance rule). The
# metric NAMES are exactly the case's `required_measurements`, because
# tools/scorecard.py invalidates a case whose required component is missing --
# and it should: the cheapest route to a better score is to stop measuring the
# inconvenient thing.
# ===========================================================================
# Per-sound analysis settings come from `model/drum_verify.py`'s own tables --
# BAND (where the voice lives), SPLIT_HZ (what separates its body from its air
# or noise) and ENV_WIN_MS (a window spanning several periods of its own
# fundamental). Imported, not copied, for the same reason as REF_MAIN.
BAND, SPLIT_HZ, ENV_WIN_MS = dv.BAND, dv.SPLIT_HZ, dv.ENV_WIN_MS

#: How far the backward-integrated energy curve may depart from a straight line
#: before its T20 is refused: 6 dB over the 20 dB range it is fitted across.
MAX_T20_RESIDUAL_DB = 6.0


def _t20_ms(t0: float = 0.0, t1: float | None = None, band=None):
    """Decay as T20 off the backward-integrated energy curve
    (`audio_measure.schroeder_t20`), for EVERY voice, and never a single
    exponential's tau.

    This was `decay_tau` and it refused five of the eight references outright:
    "not a single exponential", residuals of 4 to 23 dB. It was right to. The
    hats, the cowbell and the cymbal are sums of incommensurate squares whose
    envelope beats by 6-10 dB, and the clap is three bursts over a tail -- two
    exponentials, and a single tau fitted across them is the error that had the
    snare's TONE law withdrawn (`docs/discrimination.md` section 2).

    The right response to a refused precondition is an estimator whose
    precondition holds, not a looser threshold on the first one. T20 off the
    Schroeder curve assumes no model at all: the curve is monotone by
    construction, so beating cannot make it read a trough, and on a signal that
    IS a single exponential it equals ln(10)*tau exactly
    (`test_schroeder_t20_equals_ln10_tau_on_a_damped_sinusoid`). It is also the
    convention Roland's own chart column is comparable to."""
    def f(y, sr):
        seg = window(y, sr, t0, t1) if band is None else _bandpass(y, sr, band, t0, t1)
        e = am.schroeder_t20(seg, sr)
        if not e.ok:
            return e
        # A T20 fitted across a KNEE is not a decay time. The Schroeder curve
        # is monotone but it need not be straight -- a voice that decays and
        # then sits on a floor gives a line fit that is neither. The estimator
        # reports the worst residual; this refuses past MAX_T20_RESIDUAL_DB of
        # it, which is 30 % non-linearity over the 20 dB range and is the same
        # bound on both sides of every comparison.
        r = float(e.detail.get("residual_db", 0.0))
        if r > MAX_T20_RESIDUAL_DB:
            return am.Estimate(None, False,
                               "the energy decay curve is not straight -- a T20 "
                               "fitted across a knee is not a decay time", e.detail)
        return am.Estimate(e.value * 1e3, True, "", e.detail)
    return f


def _bandpass(y, sr, band, t0, t1):
    from scipy.signal import butter as _b, sosfiltfilt as _s
    lo, hi = band
    sos = _b(4, [max(lo, 5.0) / (sr / 2.0), min(hi, sr / 2.0 - 1.0) / (sr / 2.0)],
             btype="band", output="sos")
    return _s(sos, window(y, sr, t0, t1))


def _f0(sound: str, t0: float, t1: float):
    lo, hi = BAND[sound]

    def f(y, sr):
        return am.dominant_frequency(window(y, sr, t0, t1), lo, hi, sr)
    return f


def _pitch_drop(sound: str):
    band = (BAND[sound][0], SPLIT_HZ[sound])

    def f(y, sr):
        return pitch_drop_hz(y, sr, band)
    return f


def _split_db(sound: str, t0: float, t1: float | None, lo: float | None = None,
              hi: float | None = None):
    b_lo, b_hi = BAND[sound]
    split = SPLIT_HZ[sound]

    def f(y, sr):
        return band_ratio_db(window(y, sr, t0, t1), sr, split,
                             b_lo if lo is None else lo, b_hi if hi is None else hi)
    return f


def _attack(sound: str, t1: float = 0.250):
    ms = ENV_WIN_MS[sound]

    def f(y, sr):
        return attack_ms(window(y, sr, 0.0, t1), sr, window_ms=ms)
    return f


def _noise_t20_ms(sound: str, t0: float):
    """The T20 of the voice's ABOVE-split content alone -- the snare's noise,
    separated from its two body modes by a band-pass before the curve is
    integrated, so the number is the noise's decay and not a blend."""
    return _t20_ms(t0, None, band=(SPLIT_HZ[sound], min(BAND[sound][1], 20000.0)))


def _burst_span_ms(sound: str):
    ms = ENV_WIN_MS[sound]

    def f(y, sr):
        env = am.rms_envelope(window(y, sr, 0.0, 0.120), ms, sr)
        bursts = am.envelope_bursts(env, sr, min_sep_s=0.006, min_dip_db=2.0)
        if len(bursts) < 2:
            return am.Estimate(None, False, "fewer than two bursts in the flam",
                               dict(bursts=len(bursts)))
        return am.Estimate((bursts[-1][0] - bursts[0][0]) * 1e3, True, "",
                           dict(bursts=len(bursts)))
    return f


def _early_late_db(t_split: float, t_end: float):
    def f(y, sr):
        e_early = float(np.sum(window(y, sr, 0.0, t_split) ** 2))
        e_late = float(np.sum(window(y, sr, t_split, t_end) ** 2))
        if e_early <= 0 or e_late <= 0:
            return am.Estimate(None, False, "one half of the window holds no energy",
                               dict(early=e_early, late=e_late))
        return am.Estimate(10.0 * math.log10(e_early / e_late), True, "",
                           dict(early=e_early, late=e_late))
    return f


def _line_ratio(hz_num: float, hz_den: float, t1: float = 0.100):
    def f(y, sr):
        return tone_ratio_db(window(y, sr, 0.0, t1), sr, hz_num, hz_den)
    return f


def _band_pair(band_a, band_b, t1: float | None = None):
    def f(y, sr):
        return band_pair_db(window(y, sr, 0.0, t1), sr, band_a, band_b)
    return f


# The sixteen sounds, and the drum case that anchors each.
DRUM_CASE_VOICE = {
    "D01A": "BD", "D02A": "SD", "D03A": "LT", "D04A": "LC", "D05A": "MT",
    "D06A": "MC", "D07A": "HT", "D08A": "HC", "D09A": "CL", "D10A": "RS",
    "D11A": "MA", "D12A": "CP", "D13A": "CB", "D14A": "CY", "D15A": "OH",
    "D16A": "CH",
}


def _tom_plan(sound: str, drop: bool):
    """The six tom/conga sounds differ only in whether the case asks for the
    pitch DROP or the pitch. Three tunings of one circuit twice over."""
    first = (("Pitch drop", "Hz", _pitch_drop(sound), tol_frequency_of_f0) if drop
             else ("Pitch", "Hz", _f0(sound, 0.010, 0.200), tol_frequency))
    return [first,
            ("body spectrum", "dB", _split_db(sound, 0.0, 0.150), tol_db),
            ("decay", "ms", _t20_ms(0.005), tol_time)]


# name -> (units, estimator, tolerance rule). Names match cases.csv exactly,
# because scorecard.py invalidates a case whose required component is missing --
# and it should: the cheapest route to a better score is to stop measuring the
# inconvenient thing.
DRUM_PLAN = {
    "BD": [
        ("Pitch trajectory", "Hz", _f0("BD", 0.010, 0.500), tol_frequency),
        # A TIME split, not a frequency one. The first version asked for the
        # energy above 300 Hz inside a 10 ms window, and 10 ms is three periods
        # of a 49 Hz kick: too short for a spectrum to resolve the split and
        # too short for a 4th-order filter to settle. Early-against-body is
        # what "no attack, no harmonics" (docs/drum-verification.md 4.1) is a
        # statement about anyway, and it needs no filter at all.
        ("early/body energy", "dB", _early_late_db(0.010, 0.200), tol_db),
        ("decay", "ms", _t20_ms(0.005), tol_time),
    ],
    "SD": [
        ("Body/noise balance", "dB", _split_db("SD", 0.0, 0.100), tol_db),
        ("attack", "ms", _attack("SD"), tol_time),
        ("noise decay", "ms", _noise_t20_ms("SD", 0.002), tol_time),
    ],
    "LT": _tom_plan("LT", drop=True),
    "MT": _tom_plan("MT", drop=True),
    "HT": _tom_plan("HT", drop=True),
    "LC": _tom_plan("LC", drop=False),
    "MC": _tom_plan("MC", drop=False),
    "HC": _tom_plan("HC", drop=False),
    "CL": [
        ("Pitch", "Hz", _f0("CL", 0.002, 0.060), tol_frequency),
        ("attack duration", "ms", _attack("CL", 0.060), tol_time),
        ("tail decay", "ms", _t20_ms(0.002), tol_time),
    ],
    "RS": [
        # Two bridged-T networks on one circuit: reference section 5 gives the
        # low mode at 455 Hz Q 6.7 and the high at 1786 Hz Q 13.5, so the
        # balance is asked as the energy in a band around each.
        ("Partial balance", "dB", _band_pair((1500, 2100), (380, 560), 0.060), tol_db),
        ("attack", "ms", _attack("RS", 0.060), tol_time),
        ("tail decay", "ms", _t20_ms(0.002), tol_time),
    ],
    "MA": [
        ("Rise time", "ms", _attack("MA", 0.060), tol_time),
        ("band energy", "dB", _split_db("MA", 0.0, 0.150), tol_db),
        ("decay", "ms", _t20_ms(0.001), tol_time),
    ],
    "CP": [
        ("Burst timing", "ms", _burst_span_ms("CP"), tol_time),
        ("burst/tail ratio", "dB", _early_late_db(0.030, 0.200), tol_db),
        ("decay", "ms", _t20_ms(0.002), tol_time),
    ],
    "CB": [
        ("Partial balance", "dB", _line_ratio(800.0, 540.0), tol_db),
        ("unwanted difference tone", "dB", _line_ratio(260.0, 800.0), tol_db),
        ("decay", "ms", _t20_ms(0.005), tol_time),
    ],
    "CY": [
        ("Band energy", "dB", _split_db("CY", 0.0, 0.400), tol_db),
        ("band decay", "ms", _t20_ms(0.002, None, band=(SPLIT_HZ["CY"], 20000.0)), tol_time),
        ("total decay", "ms", _t20_ms(0.002), tol_time),
    ],
    "OH": [
        ("Band energy", "dB", _split_db("OH", 0.0, 0.200), tol_db),
        ("attack", "ms", _attack("OH"), tol_time),
        ("decay", "ms", _t20_ms(0.002), tol_time),
    ],
    "CH": [
        ("Band energy", "dB", _split_db("CH", 0.0, 0.100), tol_db),
        ("attack", "ms", _attack("CH"), tol_time),
        ("decay", "ms", _t20_ms(0.001), tol_time),
    ],
}

ENSEMBLE_CASES = {
    "E1A": ("01-bass-classic", False),
    "E1B": ("01-bass-classic", True),
    "E2A": ("03-lead-line", False),
}

# Deliberately not run, with the reason. `--list` prints this table and the PR
# carries it: a case nobody attempted has to say so, or "not run" and "we
# forgot" become the same entry.
NOT_RUN = {}
for _c in ("F1A", "F2A", "F3A", "F5A", "F1B", "F1C", "F1D", "F2B", "F2C", "F2D",
           "F3B", "F3C", "F3D", "F4A", "F4B", "F4C", "F4D", "F5B", "F5C", "F5D",
           "F6A", "F6B", "F6C", "F6D"):
    NOT_RUN[_c] = ("no frozen reference profile and no filter plan in this "
                   "runner: nothing maps these subjects to Surge parameter "
                   "settings, and docs/scorecard/README.md requires that frozen "
                   "before results are collected. (The waveform-mapping repair "
                   "these were blocked on has since landed in #87, so the rig "
                   "itself is no longer the blocker.)")
for _c in ("M1A", "M2A", "M3A", "M4A", "M5A", "M6A", "M7A", "M8A"):
    NOT_RUN[_c] = ("no frozen reference profile: nothing in the repository maps "
                   "these subjects to Mini V3 patch and parameter settings, and "
                   "docs/scorecard/README.md requires that mapping to be frozen "
                   "before results are collected. The rig is also under repair.")
NOT_RUN["E3A"] = ("no shipped patch uses the noise source or oscillator-3 "
                  "modulation, so the stimulus cannot be built from frozen "
                  "material without inventing a patch.")


def plan_for(case_id: str) -> str:
    """What this runner will do with a case: 'drum', 'ensemble', 'not-run' or
    'unplanned'."""
    if case_id in NOT_RUN:
        return "not-run"
    if case_id in DRUM_CASE_VOICE:
        return "drum"
    if case_id in ENSEMBLE_CASES:
        return "ensemble"
    return "unplanned"


# ===========================================================================
# 7. Running one case
# ===========================================================================
def _sha(*paths) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(pathlib.Path(p).read_bytes())
    return h.hexdigest()[:12]


def _git(*args) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True,
                                       stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def source_commit() -> str:
    return (_git("rev-parse", "--short", "HEAD").strip() or "?")


def worktree_state() -> dict:
    """The commit is not enough. Fourteen worktrees are live on this repository
    at once and a clean SHA that silently means "plus whatever was in the tree"
    is worse than no SHA: a stale result is indistinguishable from a current
    one. So the uncommitted diff is hashed too -- tracked modifications from
    `git diff HEAD`, and every untracked file git would not ignore, by content.
    `dirty` says which of the two kinds of record this is."""
    h = hashlib.sha256()
    diff = _git("diff", "HEAD")
    h.update(diff.encode())
    untracked = [f for f in _git("ls-files", "--others", "--exclude-standard").split("\n") if f]
    for rel in sorted(untracked):
        f = ROOT / rel
        try:
            h.update(rel.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
        except OSError:
            h.update(b"?")
    return {"commit": source_commit(),
            "described": _git("describe", "--always", "--dirty").strip() or "?",
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD").strip() or "?",
            "dirty": bool(diff.strip() or untracked),
            "uncommitted_sha256": h.hexdigest()[:16],
            "untracked_files": len(untracked)}


def _file_sha(path) -> str:
    try:
        return "sha256:" + hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


# 0 match, 1 mismatch (a result), 2 did not run (no evidence). The repository's
# verifier convention, kept on the record as well as in the exit status: a case
# that produced no evidence and a case that was measured and scored badly need
# opposite responses, and a scorecard that renders them alike gets the wrong one.
OUTCOME_CODE = {"pass": 0, "fail": 1, "no verdict": 2, "not run": 2}
OUTCOME_MEANING = "0 match, 1 mismatch (a result), 2 did not run (no evidence)"


class StaleBase(Exception):
    """The premise of the whole batch is false. Not a per-case refusal."""


# The inputs a result DEPENDS ON and does not own. If one of these differs from
# `origin/main`, an earlier green run does not cover the tree -- which is
# exactly what happened: eight drum cases refused because this worktree's
# `drums_fx.py` had eight circuits while origin/main's had eleven.
DEPENDENCIES = ("model/drums_fx.py", "model/voice_fx.py", "model/audio_measure.py",
                "model/drum_verify.py", "docs/scorecard/cases.csv")


def base_check(allow_stale: bool = False) -> dict:
    """Assert the premise of the whole batch BEFORE any of it runs.

    This exists because of a specific, expensive shape of wrong answer. Eight
    drum cases came back

        REFUSED: the eight-stop kit does not implement LC / MT / MC / HC /
        CL / RS / MA / CY

    which is exactly what the runner should say about the tree it had -- and
    was a false statement about the project, because the complete sixteen-sound
    kit had landed on `origin/main` two commits earlier. Eight honest per-case
    refusals read as a permanent hole in the instrument, and the next person
    would have re-implemented voices that already existed.

    A stale premise is a property of the BATCH, not of a case, so it refuses
    the batch. Per-case refusals describe the instrument; this describes our
    checkout, and the two must never come out looking alike.

    **What it refuses on is the DEPENDENCIES, not the commit count.** `main`
    moves several times an hour here and most of those commits cannot change a
    measurement; refusing on all of them would train everyone to pass
    `--allow-stale`, and an ignored gate is worse than no gate. So: any of
    `DEPENDENCIES` differing from `origin/main`, or a drum circuit count that
    differs, refuses. Being behind on anything else is recorded and warned
    about, because it is still worth knowing when reading the record."""
    ref = "origin/main"
    have = _git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if not have:
        return {"checked": False,
                "why": f"no {ref} in this clone -- the base could not be checked"}
    behind = int(_git("rev-list", "--count", f"HEAD..{ref}").strip() or 0)
    import drums_fx as dx

    stale_deps = {}
    for rel in DEPENDENCIES:
        theirs = _git("show", f"{ref}:{rel}")
        ours = ""
        try:
            ours = (ROOT / rel).read_text()
        except OSError:
            pass
        if theirs and ours and theirs != ours:
            stale_deps[rel] = {"origin_main": hashlib.sha256(theirs.encode()).hexdigest()[:12],
                               "here": hashlib.sha256(ours.encode()).hexdigest()[:12]}

    theirs_stops = None
    for line in _git("show", f"{ref}:model/drums_fx.py").splitlines():
        if line.startswith("N_STOPS, N_ENV"):
            try:
                theirs_stops = int(line.split("=")[1].split(",")[0])
            except (IndexError, ValueError):
                theirs_stops = None
            break

    state = {"checked": True, "origin_main": have[:12], "behind_commits": behind,
             "n_stops_here": dx.N_STOPS, "n_stops_origin_main": theirs_stops,
             "stale_dependencies": stale_deps, "allow_stale": allow_stale}
    problems = []
    if stale_deps:
        problems.append("these inputs differ from origin/main: " + ", ".join(sorted(stale_deps)))
    if theirs_stops is not None and theirs_stops != dx.N_STOPS:
        problems.append(f"the kit here has {dx.N_STOPS} drum circuits, {ref} has {theirs_stops}")
    state["problems"] = problems
    if problems and not allow_stale:
        raise StaleBase("; ".join(problems) +
                        f" -- rebase onto {ref} and re-run. Refusing the whole batch: "
                        f"per-case refusals from a stale checkout describe our tooling, "
                        f"not the instrument, and read like capability gaps. "
                        f"--allow-stale overrides and records that it did.")
    if behind:
        state["note"] = (f"{behind} commit(s) behind {ref}, none of them touching an "
                         f"input this measurement depends on")
    return state


BASE_STATE: dict = {}


def provenance(inputs: dict, artefacts: dict, config: dict) -> dict:
    """What this result was produced by, in enough detail to re-derive it
    rather than re-trust it."""
    return {
        "engine": ENGINE,
        "worktree": worktree_state(),
        "base_check": BASE_STATE,
        "command": " ".join([os.path.relpath(sys.argv[0], ROOT)] + sys.argv[1:])
                   if sys.argv and sys.argv[0] else "(imported)",
        "config": config,
        "python": sys.version.split()[0],
        "run_at": _now(),
        "inputs": inputs,
        "artefacts": artefacts,
        "outcome_code": None,            # filled in once the board has judged it
        "outcome_code_meaning": OUTCOME_MEANING,
    }


# The generated inputs every result here depends on: change one and an earlier
# green result no longer covers the tree.
MODEL_INPUTS = ("model/drums_fx.py", "model/voice_fx.py", "model/audio_measure.py",
                "tools/run_case.py", "docs/scorecard/cases.csv")


def model_input_hashes(extra: dict | None = None) -> dict:
    d = {rel: _file_sha(ROOT / rel) for rel in MODEL_INPUTS}
    d.update(extra or {})
    return d


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def analysis_run() -> str:
    return (f"run_case@{_sha(__file__)} + audio_measure@{_sha(ROOT / 'model' / 'audio_measure.py')}"
            f" at {_now()}")


def invalid_metric(units: str, why: str, tolerance: float | None = None) -> dict:
    """No distance, not zero distance. There is deliberately no `error` key."""
    m = {"units": units, "valid": False, "why": why}
    if tolerance:
        m["tolerance"] = tolerance
    return m


def measure_pair(name, units, est, ours, ref, tol_rule, ctx) -> dict:
    a = est(*ours)
    b = est(*ref)
    if not b.ok:
        return invalid_metric(units, f"reference: {b.reason} {b.detail}")
    tol, basis = tol_rule(b.value, ctx)
    if not a.ok:
        m = invalid_metric(units, f"ours: {a.reason} {a.detail}", tol)
        m["reference"] = round(float(b.value), 4)
        return m
    if not tol or not math.isfinite(tol):
        return invalid_metric(units, f"no usable tolerance for reference {b.value!r}")
    return {"value": round(float(a.value), 4), "units": units,
            "reference": round(float(b.value), 4),
            "error": round(float(a.value) - float(b.value), 4),
            "tolerance": round(float(tol), 4), "valid": True,
            "tolerance_basis": basis}


def write_wav16(path: pathlib.Path, x, sr: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    y = np.clip(np.asarray(x) * 32768.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())


def run_drum_case(case: dict, refdir: pathlib.Path, inject: str, keep_audio: bool) -> dict:
    voice = DRUM_CASE_VOICE[case["case_id"]]
    required = [m.strip() for m in case["required_measurements"].split(";") if m.strip()]
    base = {"engine": ENGINE, "case_id": case["case_id"], "subject": case["subject"],
            "source_commit": source_commit(), "analysis_run": analysis_run()}

    why = ""
    if voice not in REF_MAIN:
        why = f"the Fischer corpus has no reference recording mapped for {voice}"
    elif voice not in DRUM_PLAN:
        why = f"this runner has no measurement plan for {voice}"
    if why:
        base.update({
            "reference_profile": "none",
            "render_run": "not rendered", "audio": "none",
            "note": (f"REFUSED: {why}. There is nothing to compare, so this case "
                     f"has no distance -- not a zero one."),
            "provenance": provenance(model_input_hashes(), {},
                                     dict(voice=voice, refs=str(refdir), inject=inject or None)),
            "metrics": {m: invalid_metric("", why) for m in required}})
        return base

    ref_x, ref_sr, rel, setting = load_reference(voice, refdir, inject)
    ours_x, ours_sr = render_drum_solo(voice)

    ref_y, ours_y = prepare(ref_x, ref_sr), prepare(ours_x, ours_sr)
    ref, ours = (ref_y, ref_sr), (ours_y, ours_sr)

    ctx = {}
    f0 = _f0(voice, 0.010, 0.200)(*ref)
    if f0.ok:
        ctx["ref_f0"] = f0.value

    metrics = {}
    for name, units, est, tol_rule in DRUM_PLAN[voice]:
        metrics[name] = measure_pair(name, units, est, ours, ref, tol_rule, ctx)
    missing = [m for m in required if m not in metrics]
    for m in missing:
        metrics[m] = invalid_metric("", "this runner has no estimator for it")

    import drums_fx as dx
    audio_path, audio = "not written (--no-audio)", f"reference {rel}; ours not written"
    if keep_audio:
        p = AUDIO_OUT / f"{case['case_id']}-ours.wav"
        write_wav16(p, ours_x, ours_sr)
        audio_path = str(p.relative_to(ROOT))
        audio = f"reference {rel}; ours {audio_path}"

    base.update({
        "provenance": provenance(
            model_input_hashes({f"reference:{rel}": _file_sha(refdir / rel)}),
            {"ours": audio_path, "reference": str(refdir / rel)},
            dict(voice=voice, refs=str(refdir), inject=inject or None,
                 render_seconds=SOLO_SECONDS.get(voice, 2.2), accent=1.0,
                 bus_gain=0.45, level_matched=True)),
        "reference_profile": f"fischer-tr808-103852:{rel} ({setting})",
        "reference_identity": REF_ID,
        "render_run": (f"drums_fx@{_sha(ROOT / 'model' / 'drums_fx.py')} "
                       f"kit_with_sounds({voice!r}) solo, one hit at accent 1.0, "
                       f"{SOLO_SECONDS.get(voice, 2.2):.2f} s, both drum buses 0.45, "
                       f"{dx.SR} Hz, circuit {dx.SOUND_STOP[voice]} of {dx.N_STOPS}"),
        "audio": audio,
        "tolerance_policy": TOLERANCE_POLICY,
        "metrics": metrics,
        "diagnostics": {
            "ours_peak_fs": round(float(np.abs(ours_x).max()), 6),
            "ours_rms_fs": round(float(am.rms(ours_x)), 6),
            "reference_peak_fs": round(float(np.abs(ref_x).max()), 6),
            "reference_rate_hz": ref_sr, "ours_rate_hz": ours_sr,
            "level_matched": True,
            "note": ("levels are not compared: the Fischer set pinned LEVEL at "
                     "maximum for every voice, so its inter-voice levels are not "
                     "the machine's. Original-gain peak and RMS are recorded above."),
        },
    })
    if inject:
        base["INJECTED_CONTROL"] = inject
    return base


def run_ensemble_case(case: dict, keep_audio: bool) -> dict:
    patch, dense = ENSEMBLE_CASES[case["case_id"]]
    required = [m.strip() for m in case["required_measurements"].split(";") if m.strip()]
    r = render_ensemble(patch, dense)
    sr, mix = r["sr"], r["mix"]
    stem_sum = sum(r["stems"].values())

    metrics = {}

    # Event timing: each stop's row alone, against the frames its writes were
    # made at. The reference is the schedule itself, which is why this case
    # needs no external reference at all -- and the worst stop is what is
    # reported, never an average over the stops that were on time.
    tol, basis = tol_fixed(10.0, "event timing")(0.0, {})
    worst, worst_stop, refusal = None, "", ""
    for stop_name, (sig, sched) in r["per_stop"].items():
        e = worst_event_offset_ms(sig / 32768.0, sr, sched)
        if not e.ok:
            refusal = f"{stop_name}: {e.reason} {e.detail}"
            break
        if worst is None or e.value > worst:
            worst, worst_stop = e.value, stop_name
    if refusal or worst is None:
        metrics["Event timing"] = invalid_metric("ms", refusal or "no stop to measure", tol)
    else:
        metrics["Event timing"] = {"value": round(worst, 4), "units": "ms", "reference": 0.0,
                                   "error": round(worst, 4), "tolerance": tol, "valid": True,
                                   "tolerance_basis": basis, "worst_stop": worst_stop}

    # Bus balance: does the one hard rail in output_fx change the sum?
    if am.rms(stem_sum) <= 0 or am.rms(mix) <= 0:
        metrics["bus balance"] = invalid_metric("dB", "a silent render")
    else:
        v = 20.0 * math.log10(am.rms(mix) / am.rms(stem_sum))
        metrics["bus balance"] = {"value": round(v, 4), "units": "dB", "reference": 0.0,
                                  "error": round(v, 4), "tolerance": 0.5, "valid": True,
                                  "tolerance_basis": "bus sum"}

    # Output artifacts: samples on the rail of the unnormalised final output.
    rail = 100.0 * am.clipped_fraction(mix, 32767.0)
    metrics["output artifacts"] = {"value": round(rail, 6), "units": "% of samples",
                                   "reference": 0.0, "error": round(rail, 6),
                                   "tolerance": 0.01, "valid": True,
                                   "tolerance_basis": "rail"}

    for m in required:
        metrics.setdefault(m, invalid_metric("", "this runner has no estimator for it"))

    audio = "not written (--no-audio)"
    if keep_audio:
        p = AUDIO_OUT / f"{case['case_id']}-mix.wav"
        write_wav16(p, mix / 32768.0, sr)
        audio = str(p.relative_to(ROOT))

    return {
        "engine": ENGINE, "case_id": case["case_id"], "subject": case["subject"],
        "source_commit": source_commit(), "analysis_run": analysis_run(),
        "provenance": provenance(model_input_hashes(), {"mix": audio},
                                 dict(patch=patch, dense=dense, bpm=r["bpm"],
                                      seconds=r["n"] / sr, bus_gain=0.45, limiter=False)),
        "reference_profile": ("our own per-bus stems and the written hit schedule; "
                              "no external reference is involved in this case"),
        "render_run": r["render"], "audio": audio,
        "tolerance_policy": TOLERANCE_POLICY,
        "metrics": metrics,
        "diagnostics": {
            "peak_fs": round(float(np.abs(mix).max()) / 32768.0, 6),
            "stem_peaks_fs": {k: round(float(np.abs(s).max()) / 32768.0, 6)
                              for k, s in r["stems"].items()},
            "scheduled_events": len(r["hits_s"]),
            "stops_timed": sorted(r["per_stop"]),
            "dc_offset_fs": round(float(mix.mean()) / 32768.0, 8),
            "patch": r["patch"], "bpm": r["bpm"],
        },
    }


def run_case(case: dict, refdir: pathlib.Path, inject: str = "",
             keep_audio: bool = True) -> dict | None:
    """One case's result dict, or None when the case is deliberately not run."""
    cid = case["case_id"]
    kind = plan_for(cid)
    if kind == "not-run":
        return None
    base = {"engine": ENGINE, "case_id": cid, "subject": case.get("subject", ""),
            "source_commit": source_commit(), "analysis_run": analysis_run(),
            "reference_profile": "", "render_run": "", "audio": "",
            "provenance": provenance(model_input_hashes(), {},
                                     dict(refs=str(refdir), inject=inject or None))}
    required = [m.strip() for m in (case.get("required_measurements") or "").split(";")
                if m.strip()]
    try:
        if kind == "drum":
            return run_drum_case(case, refdir, inject, keep_audio)
        if kind == "ensemble":
            return run_ensemble_case(case, keep_audio)
        base["note"] = "REFUSED: this runner has no plan for this case."
        base["metrics"] = {m: invalid_metric("", "no measurement plan") for m in required}
        return base
    except Refused as e:
        base["note"] = f"REFUSED: {e}"
        base["metrics"] = {m: invalid_metric("", str(e)) for m in required}
        return base
    except Exception as e:                       # pragma: no cover - guard
        base["note"] = f"REFUSED: {type(e).__name__}: {e}"
        base["traceback"] = traceback.format_exc(limit=6)
        base["metrics"] = {m: invalid_metric("", f"{type(e).__name__}: {e}")
                           for m in required}
        return base


# ===========================================================================
# 8. CLI
# ===========================================================================
def load_cases() -> list[dict]:
    with open(CASES_CSV) as fh:
        return list(csv.DictReader(fh))


def verdict_of(case: dict, res: dict | None) -> tuple:
    """The board's own verdict for one result, so the runner reports what the
    board will say rather than its own opinion of it."""
    sys.path.insert(0, str(ROOT / "tools"))
    import scorecard
    r = scorecard.evaluate(case, res)
    return r["state"], r["worst"], r["why"]


def cmd_list(cases: list[dict]) -> int:
    print(f"{'case':<7}{'family':<10}{'batch':<14}{'plan':<11}reason / reference")
    print("-" * 100)
    counts = {}
    for c in cases:
        kind = plan_for(c["case_id"])
        counts[kind] = counts.get(kind, 0) + 1
        why = ""
        if kind == "not-run":
            why = NOT_RUN[c["case_id"]]
        elif kind == "drum":
            v = DRUM_CASE_VOICE[c["case_id"]]
            why = (f"{v} vs {REF_MAIN[v][0]} ({REF_MAIN[v][1]})" if v in REF_MAIN
                   else f"{v} is not implemented by the kit -- no verdict, with the reason")
        elif kind == "ensemble":
            p, d = ENSEMBLE_CASES[c["case_id"]]
            why = f"{p}, {'dense' if d else 'sparse'} 808 groove, stems vs final output"
        else:
            why = "no plan in this runner"
        print(f"{c['case_id']:<7}{c['family']:<10}{c['batch']:<14}{kind:<11}{why[:70]}")
    print("-" * 100)
    print("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="case ids, e.g. D01A")
    ap.add_argument("--batch", help='a batch from cases.csv, e.g. "First 32"')
    ap.add_argument("--family", help="Drums | Mono | Filters | Ensemble")
    ap.add_argument("--all", action="store_true", help="every case in cases.csv")
    ap.add_argument("--list", action="store_true", help="print the plan and stop")
    ap.add_argument("--refs", default=os.environ.get(REFS_ENV, REFS_DEFAULT),
                    help=f"the Fischer TR-808 corpus (default {REFS_DEFAULT}, ${REFS_ENV})")
    ap.add_argument("--results", default=None, help="where result JSON goes")
    ap.add_argument("--inject", default="", choices=["", "REF_F0_20PCT", "REF_MISSING"],
                    help="an injected control; requires --results outside the board")
    ap.add_argument("--expect", default="", choices=["", "pass", "fail", "no verdict"],
                    help="exit 1 unless every case lands in this state (for controls)")
    ap.add_argument("--no-audio", action="store_true", help="do not write the rendered WAVs")
    ap.add_argument("--allow-stale", action="store_true",
                    help="run even though this tree is behind origin/main, and say so "
                         "on every record it writes")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    all_cases = load_cases()
    if a.list:
        sel = all_cases
        if a.batch:
            sel = [c for c in sel if c["batch"] == a.batch]
        if a.family:
            sel = [c for c in sel if c["family"] == a.family]
        return cmd_list(sel)

    by_id = {c["case_id"]: c for c in all_cases}
    chosen: list[dict] = []
    for cid in a.cases:
        if cid not in by_id:
            print(f"no such case: {cid}", file=sys.stderr)
            return 2
        chosen.append(by_id[cid])
    if a.batch:
        chosen += [c for c in all_cases if c["batch"] == a.batch]
    if a.family:
        chosen += [c for c in all_cases if c["family"] == a.family]
    if a.all:
        chosen += all_cases
    if not chosen:
        ap.error("name at least one case, or --batch / --family / --all / --list")
    seen, uniq = set(), []
    for c in chosen:
        if c["case_id"] not in seen:
            seen.add(c["case_id"])
            uniq.append(c)
    chosen = uniq

    outdir = pathlib.Path(a.results) if a.results else RESULTS
    # An injected control's output is not evidence. It must not be able to
    # land on the board, whatever else goes wrong in this invocation.
    if a.inject and outdir.resolve() == RESULTS.resolve():
        print("--inject refuses to write into docs/scorecard/results; pass --results",
              file=sys.stderr)
        return 2

    # The premise of the batch, asserted before any of it runs. A stale
    # checkout produces per-case refusals that read like capability gaps, and
    # that has already happened once here.
    global BASE_STATE
    try:
        BASE_STATE = base_check(a.allow_stale)
    except StaleBase as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    if not BASE_STATE.get("checked"):
        print(f"NOTE: {BASE_STATE.get('why')}")
    elif BASE_STATE.get("problems"):
        print(f"WARNING (--allow-stale): {'; '.join(BASE_STATE['problems'])}")
    elif BASE_STATE.get("note"):
        print(f"base: {BASE_STATE['note']}")

    refdir = pathlib.Path(a.refs)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"reference corpus: {refdir}{'' if refdir.exists() else '   (ABSENT)'}")
    print(f"results into:     {outdir}")
    if a.inject:
        print(f"INJECTED CONTROL: {a.inject} -- this output is a control, not evidence")
    print()
    print(f"{'case':<7}{'state':<12}{'worst':>7}  note")
    print("-" * 96)

    states, errors, code = {}, 0, 0
    for c in chosen:
        cid = c["case_id"]
        if plan_for(cid) == "not-run":
            states["not run"] = states.get("not run", 0) + 1
            code = max(code, OUTCOME_CODE["not run"])
            print(f"{cid:<7}{'not run':<12}{'--':>7}  {NOT_RUN[cid][:60]}")
            continue
        res = run_case(c, refdir, a.inject, keep_audio=not a.no_audio)
        # Judge BEFORE writing, so the outcome code on the record is the board's
        # verdict and not this runner's opinion of it.
        state, worst, why = verdict_of(c, res)
        res.setdefault("provenance", {})["outcome_code"] = OUTCOME_CODE[state]
        if not a.dry_run:
            (outdir / f"{cid}.json").write_text(json.dumps(res, indent=2, sort_keys=False) + "\n")
        states[state] = states.get(state, 0) + 1
        code = max(code, OUTCOME_CODE[state])
        if "traceback" in res:
            errors += 1
        w = f"{worst:.2f}" if worst is not None else "--"
        note = why or res.get("note", "")
        print(f"{cid:<7}{state:<12}{w:>7}  {note[:60]}")

    print("-" * 96)
    print("  ".join(f"{k}: {v}" for k, v in sorted(states.items())))
    if a.expect:
        # Control semantics, not verifier semantics: the question is whether
        # the injected defect turned the board the colour it must.
        bad = {k: v for k, v in states.items() if k != a.expect}
        if bad:
            print(f"CONTROL DID NOT FIRE: expected every case {a.expect!r}, got {bad}",
                  file=sys.stderr)
            return 1
        print(f"control fired: every case came back {a.expect!r}")
        return 0
    if errors:
        print(f"{errors} case(s) hit an unexpected internal error; see the result JSON",
              file=sys.stderr)
    print(f"exit {code}: {OUTCOME_MEANING}")
    return code


if __name__ == "__main__":
    sys.exit(main())
