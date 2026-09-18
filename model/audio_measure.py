#!/usr/bin/env python3
"""Audio measurement estimators, with ground truth.

`model/test_audio_measure.py` exercises every estimator here against signals
whose answer is known analytically. Nothing in this module is trusted until
that file passes: on 2026-09-18 four defect reports in this repository turned
out to be measurement errors, not defects, and each came from analysis code
that had never been checked against a signal with a known answer.

    from audio_measure import decay_tau, damped_sinusoid, spectral_lines

WHAT THIS MODULE REFUSES TO DO

Every estimator returns an `Estimate`, and an `Estimate` may be **not ok**.
That is the point. An estimator that always produces a plausible number is how
a 700 ms attack, a 39.5 ms decay and a 41 %-high centroid all got reported.
Call `.require()` when a test needs a number and should fail loudly without
one; read `.ok` and `.reason` when "no answer" is itself the result.

FIVE RULES LEARNED THE EXPENSIVE WAY

1.  **Envelope: pick the right one, and never a moving average of |x|.** A 5 ms
    moving average spans 0.28 of a cycle at 56 Hz and leaves about 76 % ripple,
    which read every bass-drum decay roughly 3x too fast;
    `moving_average_envelope` exists only so `test_audio_measure.py` can
    demonstrate that error. Of the two real choices, `analytic_envelope` is
    right for a SINGLE damped sinusoid and `rms_envelope` for a BROADBAND
    signal. A hi-hat is a dense inharmonic comb whose instantaneous amplitude
    genuinely beats by tens of dB, so its analytic envelope is not monotone at
    all: the open hat's appears to GROW for 50 ms after the strike and its
    maximum lands on a beat. Choosing wrongly is not a small error.

2.  **tau and "decay time" are different quantities.** For A0*exp(-t/tau) the
    time to -20 dB is ln(10)*tau = 2.303*tau. tau = 39.5 ms is a T20 of 91 ms,
    not a "50 ms decay". Roland's chart convention is undefined; the reference
    (docs/tr808-reference.md section 1.6) reads it as approximately T20. Assert
    in one convention and convert explicitly with `t20_from_tau`.

3.  **A spectral centroid is not a filter's corner or centre.** They are
    different descriptors and neither weighting makes one the other. When the
    property under test is a filter, drive that filter with a controlled
    broadband probe and measure the transfer response (`resonant_peak`,
    `corner_3db`, `bandwidth_q`), never the finished voice.

4.  **A peak count does not prove an oscillator topology.** Filtered noise can
    show many peaks and a dense oscillator mixture can look flat.
    `spectral_lines` counts; `line_stability` asks whether the same lines are
    there in every window, which is what separates oscillators from noise. Both
    want a matched negative control that must fail the same test.

5.  **Know which estimator stops working where.** Three limits are enforced
    rather than documented and forgotten: `decay_tau` refuses a signal with
    fewer than one carrier cycle per tau (there is no envelope to fit);
    `damped_sinusoid` refuses TAU when the fit residual is comparable with the
    per-sample decay, because a least-squares fit of the two-pole recursion is
    biased towards a faster decay and on a quantised high-Q ring that bias is
    the whole answer -- it reported 63 ms for a 127 ms bass drum; and `onsets`
    positions are good to about 10 ms and no better, because the Hilbert
    transform is not causal and puts a precursor ahead of every strike.

Also: never normalise two signals before comparing them (that hides gain
errors). `compare` reports waveform similarity and level difference
separately.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

SR_DEFAULT = 48000

#: time to -20 dB, in units of tau, for a single exponential
TAU_TO_T20 = math.log(10.0)


class InsufficientEvidence(AssertionError):
    """An estimator was asked for a number it cannot honestly supply."""


@dataclass(frozen=True)
class Estimate:
    """One measured quantity, or a refusal to measure it.

    `value` is meaningless unless `ok`. `detail` carries the diagnostics that
    decided it, so a failing test can print why."""
    value: float | None
    ok: bool = True
    reason: str = ""
    detail: dict = field(default_factory=dict)

    def require(self, what: str = "") -> float:
        if not self.ok or self.value is None:
            raise InsufficientEvidence(
                f"{what or 'estimate'}: insufficient evidence -- {self.reason} {self.detail}")
        return float(self.value)

    def __repr__(self) -> str:
        if not self.ok:
            return f"Estimate(insufficient: {self.reason} {self.detail})"
        return f"Estimate({self.value:.6g}, {self.detail})"


def _fail(reason: str, **detail) -> Estimate:
    return Estimate(None, False, reason, detail)


def _as_float(x) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1:
        raise ValueError("expected a 1-D signal")
    return x


# ---------------------------------------------------------------------------
# level, silence, clipping -- the cheap evidence checks every estimator uses
# ---------------------------------------------------------------------------
def rms(x) -> float:
    x = _as_float(x)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def peak(x) -> float:
    x = _as_float(x)
    return float(np.max(np.abs(x))) if len(x) else 0.0


def db(a: float, ref: float = 1.0) -> float:
    return 20.0 * math.log10(max(abs(a), 1e-300) / max(abs(ref), 1e-300))


def is_silent(x, floor: float = 1e-9) -> bool:
    return peak(x) <= floor


def clipped_fraction(x, full_scale: float) -> float:
    """Fraction of samples at or beyond `full_scale`. A clipped signal has a
    flattened envelope and a spread spectrum; every estimator here reports it
    in `detail` so a surprising measurement can be traced to it."""
    x = _as_float(x)
    if not len(x):
        return 0.0
    return float(np.mean(np.abs(x) >= full_scale * (1 - 1e-12)))


def quantisation_floor(x, lsb: float = 1.0) -> float:
    """Peak-to-LSB ratio in dB: how much resolution the signal actually has.
    Below about 20 dB, spectral estimates are quantisation noise."""
    return db(peak(x), lsb)


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------
def analytic_signal(x) -> np.ndarray:
    """x + j*H{x} by the FFT construction, zero-padded to twice the length.

    The padding matters: the FFT Hilbert transform is circular, so without it
    the strike transient at the start wraps round and corrupts the end of the
    envelope. On a 0.6 s two-exponential decay that put the envelope MAXIMUM in
    the last sample, which in turn made a decay fit refuse a signal it should
    have measured. Padding costs one extra FFT and removes it."""
    x = _as_float(x)
    n = len(x)
    if n == 0:
        return np.zeros(0, dtype=complex)
    m = 1 << int(math.ceil(math.log2(2 * n)))
    X = np.fft.fft(x, m)
    h = np.zeros(m)
    h[0] = h[m // 2] = 1.0
    h[1:m // 2] = 2.0
    return np.fft.ifft(X * h)[:n]


def analytic_envelope(x) -> np.ndarray:
    """|analytic signal|: the instantaneous amplitude.

    For a damped sinusoid this is exactly A0*exp(-t/tau) apart from edge
    effects, at every carrier frequency and every tau -- which a moving average
    is not, and that difference is rule 1 at the top of this file."""
    return np.abs(analytic_signal(x))


def rms_envelope(x, ms: float = 5.0, sr: int = SR_DEFAULT) -> np.ndarray:
    """Short-time RMS envelope, scaled so a sinusoid of amplitude A reads A.

    THE right envelope for a BROADBAND signal -- a hi-hat is a dense
    inharmonic comb and a clap is noise, and the instantaneous amplitude of
    either genuinely swings by 20 dB from sample to sample as its components
    beat. `analytic_envelope` reports that swing faithfully and is therefore
    useless for reading the decay of such a voice; on the open hat its maximum
    lands on a beat 2 ms after the strike and the "envelope" then rises again.

    Use `analytic_envelope` for a single damped sinusoid (a bridged-T drum
    voice, a filter ringing at one frequency), `rms_envelope` for anything
    broadband. The window must span several cycles of the lowest component
    present and must be short against the decay being measured -- at 56 Hz
    there is no window that does both, which is why a low-frequency single
    sinusoid gets the analytic envelope and nothing else."""
    x = _as_float(x)
    k = max(1, int(round(ms * 1e-3 * sr)))
    e = np.sqrt(np.convolve(x * x, np.ones(k) / k, mode="same"))
    return e * math.sqrt(2.0)


def moving_average_envelope(x, ms: float, sr: int = SR_DEFAULT) -> np.ndarray:
    """DEPRECATED, kept only as the counter-example in
    `test_moving_average_envelope_is_biased_and_analytic_is_not`. Do not use it
    to measure anything."""
    x = _as_float(x)
    k = max(1, int(round(ms * 1e-3 * sr)))
    return np.convolve(np.abs(x), np.ones(k) / k, mode="same")


def instantaneous_frequency(x, sr: int = SR_DEFAULT, smooth_ms: float = 0.0) -> np.ndarray:
    """Instantaneous frequency in Hz from the analytic phase derivative. Valid
    only where the envelope is well above the floor; callers should mask by
    `analytic_envelope`. Optional smoothing is a centred moving average over
    the unwrapped phase derivative."""
    z = analytic_signal(x)
    ph = np.unwrap(np.angle(z))
    f = np.diff(ph) * sr / (2 * math.pi)
    if smooth_ms > 0 and len(f):
        k = max(1, int(round(smooth_ms * 1e-3 * sr)))
        f = np.convolve(f, np.ones(k) / k, mode="same")
    return f


# ---------------------------------------------------------------------------
# decay
# ---------------------------------------------------------------------------
def t20_from_tau(tau_s: float) -> float:
    """Time to -20 dB of a single exponential: ln(10)*tau = 2.303*tau."""
    return TAU_TO_T20 * tau_s


def tau_from_t20(t20_s: float) -> float:
    return t20_s / TAU_TO_T20


def decay_tau(x, sr: int = SR_DEFAULT, *, start_s: float | None = None,
              end_s: float | None = None, skip_ms: float = 1.0,
              floor_db: float = -35.0, min_range_db: float = 12.0,
              max_residual_db: float = 4.0, min_samples: int = 64,
              is_envelope: bool = False, envelope: str = "analytic",
              rms_window_ms: float = 5.0) -> Estimate:
    """Amplitude time constant to 1/e, in seconds, of a decaying signal.

    `envelope` selects how the envelope is formed: "analytic" (default, right
    for a single damped sinusoid) or "rms" with `rms_window_ms` (right for a
    broadband voice -- hats, cymbal, clap -- whose instantaneous amplitude
    beats). Choosing wrongly is not a small error: the analytic envelope of the
    open hat is not monotone at all.

    Pass `is_envelope=True` when `x` is ALREADY an envelope (for example from
    `average_envelope`): taking the analytic envelope of an envelope measures
    the wrong thing -- a low-pass positive signal is not a modulated carrier,
    and doing it anyway read a 47 ms tail as 89 ms.

    Method: analytic envelope -> log -> weighted least squares over the window
    from the envelope peak (plus `skip_ms`, to clear the strike transient) down
    to `floor_db` below it.

    Refuses when:
      * the signal is silent, or shorter than `min_samples`;
      * the envelope does not fall by `min_range_db` inside the window (so a
        stationary noise or a sustained tone gets no decay time);
      * the envelope is not a single exponential -- the worst residual from the
        log-linear fit exceeds `max_residual_db`. A strong attack over a weak
        long tail is two exponentials, and this is what stops a plausible
        average of the two being returned. Fit the tail with `start_s`.

    `detail` carries `residual_db`, `range_db`, `n`, `t0`, so a refusal says
    which check failed."""
    x = _as_float(x)
    if is_silent(x):
        return _fail("silent", peak=peak(x))
    if is_envelope:
        env = np.abs(_as_float(x))
    elif envelope == "rms":
        env = rms_envelope(x, rms_window_ms, sr)
    elif envelope == "analytic":
        env = analytic_envelope(x)
    else:
        raise ValueError("envelope must be 'analytic' or 'rms'")
    i0 = 0 if start_s is None else int(start_s * sr)
    i1 = len(env) if end_s is None else min(len(env), int(end_s * sr))
    if i1 - i0 < min_samples:
        return _fail("window too short", n=i1 - i0)
    seg = env[i0:i1]
    p = int(np.argmax(seg))
    pk = float(seg[p])
    if pk <= 0:
        return _fail("no envelope peak")
    p += max(0, int(round(skip_ms * 1e-3 * sr)))
    if p >= len(seg) - min_samples:
        return _fail("peak too close to the end", n=len(seg) - p)
    tail = seg[p:]
    below = np.where(tail < pk * 10 ** (floor_db / 20.0))[0]
    end = int(below[0]) if len(below) else len(tail)
    if end < min_samples:
        return _fail("too few samples above the floor", n=end)
    fit = tail[:end]
    range_db = db(fit[0], fit[-1])
    if range_db < min_range_db:
        return _fail("envelope does not decay far enough", range_db=range_db)
    t = np.arange(len(fit)) / sr
    y = np.log(np.maximum(fit, pk * 1e-9))
    w = fit / fit.max()                      # amplitude weighting: the loud part decides
    A = np.vstack([t, np.ones_like(t)]).T
    sol, *_ = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)
    slope = float(sol[0])
    if slope >= 0:
        return _fail("envelope does not decay", slope=slope)
    resid_db = float(np.max(np.abs(y - (A @ sol))) * 20.0 / math.log(10))
    tau = -1.0 / slope
    detail = dict(residual_db=resid_db, range_db=range_db, n=len(fit), t0=(i0 + p) / sr)
    if resid_db > max_residual_db:
        return Estimate(None, False, "not a single exponential", detail)
    # An analytic envelope is only an envelope when the carrier is well above
    # the decay's own bandwidth (1/pi tau). Below about one cycle per tau the
    # positive and negative frequency halves overlap and the "envelope" ripples
    # at twice the carrier -- so refuse and send the caller to
    # `damped_sinusoid`, which is exact there.
    fe = _fail("skipped") if (is_envelope or envelope == "rms") else \
        dominant_frequency(x[i0:i1], 10.0, 0.45 * sr, sr, min_prominence_db=6.0)
    if fe.ok:
        cycles = fe.value * tau
        detail["carrier_hz"] = fe.value
        detail["cycles_per_tau"] = cycles
        if cycles < 0.8:
            return Estimate(None, False,
                            "fewer than one carrier cycle per tau: use damped_sinusoid", detail)
    return Estimate(tau, True, "", detail)


# ---------------------------------------------------------------------------
# damped sinusoid: frequency AND tau from the two-pole recursion
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Damped:
    freq: Estimate
    tau: Estimate
    a1: float
    a2: float
    residual: float


def damped_sinusoid(x, sr: int = SR_DEFAULT, *, max_residual: float = 0.25,
                    min_samples: int = 24) -> Damped:
    """Fit y[n] = a1*y[n-1] + a2*y[n-2] and read off frequency and tau.

    This is the recursion the modal bank runs, so for a bridged-T voice it is
    the exact model; it also works when tau is SHORTER than one carrier period
    and when the window holds less than one cycle, where an FFT or a
    zero-crossing count cannot work at all. That is the case the 4 ms / 130 Hz
    bass-drum attack lives in (section 2 of the 808 reference), and the case
    that produced a wrong answer by short-window FFT.

    Poles r*exp(+-j*w): a1 = 2r cos w, a2 = -r^2, so r = sqrt(-a2),
    f = w*sr/2pi, tau = -1/(sr*ln r). Refuses when the fit residual is a large
    fraction of the signal (i.e. it is not one damped sinusoid), when a2 >= 0,
    when r >= 1 (growing, so no tau), or when |a1/2r| > 1 (real poles: a decay
    with no oscillation)."""
    x = _as_float(x)
    n = len(x)
    if n < min_samples:
        return Damped(_fail("too few samples", n=n), _fail("too few samples", n=n), 0.0, 0.0, 1.0)
    if is_silent(x):
        return Damped(_fail("silent"), _fail("silent"), 0.0, 0.0, 1.0)
    A = np.vstack([x[1:-1], x[:-2]]).T
    b = x[2:]
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    a1, a2 = float(sol[0]), float(sol[1])
    resid = float(np.linalg.norm(b - A @ sol) / max(np.linalg.norm(b), 1e-300))
    d = dict(a1=a1, a2=a2, residual=resid)
    if resid > max_residual:
        e = Estimate(None, False, "not a single damped sinusoid", d)
        return Damped(e, e, a1, a2, resid)
    if a2 >= 0:
        e = Estimate(None, False, "no conjugate pole pair (a2 >= 0)", d)
        return Damped(e, e, a1, a2, resid)
    r = math.sqrt(-a2)
    c = a1 / (2 * r) if r > 0 else 2.0
    if abs(c) > 1.0:
        e = Estimate(None, False, "real poles: no oscillation", d)
        return Damped(e, e, a1, a2, resid)
    f = math.acos(c) * sr / (2 * math.pi)
    fe = Estimate(f, True, "", d)
    if r >= 1.0:
        return Damped(fe, Estimate(None, False, "not decaying (r >= 1)", d), a1, a2, resid)
    # The frequency survives a noisy signal; the decay does not. A least
    # squares fit of the recursion is biased towards a faster decay by its own
    # residual, and for a high-Q pole (1 - r of a few times 1e-4, which is any
    # long 808 ring or any resonant filter near self-oscillation) that bias is
    # the whole answer: on the integer bass drum at tau = 127 ms it reported
    # 63 ms, with a residual that looked excellent. So refuse tau when the
    # per-sample fit error is comparable with the per-sample decay, and send
    # the caller to `decay_tau`, whose envelope fit is unaffected. The 0.2
    # factor is where the ground-truth sweep over quantised rings stops being
    # accurate.
    d = dict(d, one_minus_r=1 - r)
    if resid > 0.2 * (1 - r):
        return Damped(fe, Estimate(None, False,
                                   "fit residual comparable with the per-sample decay: "
                                   "tau unresolvable here, use decay_tau", d), a1, a2, resid)
    return Damped(fe, Estimate(-1.0 / (sr * math.log(r)), True, "", d), a1, a2, resid)


def poles_to_freq_tau(a1: float, a2: float, sr: int = SR_DEFAULT):
    """The CONTROL-path counterpart of `damped_sinusoid`: what the coefficients
    that were actually written mean, independent of any audio. Testing the two
    separately localises a defect -- right coefficients with a short ring means
    the fault is downstream (excitation, envelope, gain, clipping)."""
    if a2 >= 0:
        return _fail("a2 >= 0"), _fail("a2 >= 0")
    r = math.sqrt(-a2)
    c = a1 / (2 * r) if r > 0 else 2.0
    if abs(c) > 1.0:
        return _fail("real poles"), _fail("real poles")
    f = Estimate(math.acos(c) * sr / (2 * math.pi))
    t = Estimate(-1.0 / (sr * math.log(r))) if r < 1.0 else _fail("r >= 1")
    return f, t


# ---------------------------------------------------------------------------
# onsets
# ---------------------------------------------------------------------------
def onsets(x, sr: int = SR_DEFAULT, *, min_gap_s: float = 0.020,
           rise_db: float = 12.0, rise_window_s: float = 0.008,
           floor_db: float = -50.0, smooth_ms: float = 5.0,
           locate_db: float = 6.0) -> list[int]:
    """Sample indices where a new hit starts.

    An onset is a RISE, so that is what is detected: the log analytic envelope's
    gain over `rise_window_s`, wherever it exceeds `rise_db` and arrives
    somewhere above `floor_db` of the loudest point, with accepted onsets at
    least `min_gap_s` apart. Positions are good to about 10 ms, which is set by
    the precursor below and is plenty for telling one hit from another and
    nowhere near enough to measure an attack time with -- do not use it for
    that. Nothing about absolute level enters the detection,
    so a quiet hit after a loud one is found -- a solo render holds the same
    voice at accent 1.4 and then 0.6, and "first onset to global peak" measured
    across such a render is what invented a 700 ms attack on seven of eight
    voices. Analyse each hit separately, between consecutive onsets.

    Two traps, both of which produced wrong answers here:

    * peak-picking the envelope instead of its rise: on a decaying voice every
      masked maximum lands further down the same decay, and the answer is a
      list of points along one hit.
    * the Hilbert transform is not causal, so a sharp strike puts a precursor
      tens of ms AHEAD of itself and flattens the rise being looked for. The
      window is therefore 8 ms rather than 3.
      A short-time RMS envelope has no precursor but ripples hopelessly on a
      56 Hz carrier, so it is not the answer either. The onset is then LOCATED
      as the first point within `locate_db` of the peak the rise leads to --
      locating it where the rise began puts it in the precursor, tens of ms
      early, and that peak must be looked for PAST the end of the rise or the
      same thing happens by a different route.

    The analytic envelope is then smoothed over `smooth_ms` -- not to remove
    carrier ripple, which it does not have, but to remove BEATS: a snare is two
    partials a fifth apart and its instantaneous amplitude swings by 12 dB
    every 6 ms, which reads as a second hit 150 ms after the first."""
    x = _as_float(x)
    if is_silent(x):
        return []
    env = analytic_envelope(x)
    if smooth_ms > 0:
        k = max(1, int(round(smooth_ms * 1e-3 * sr)))
        env = np.convolve(env, np.ones(k) / k, mode="same")
    e = 20 * np.log10(np.maximum(env, peak(env) * 1e-7))
    w = max(1, int(rise_window_s * sr))
    if len(e) <= w + 2:
        return []
    rise = e[w:] - e[:-w]
    level = e[w:]
    gap = max(1, int(min_gap_s * sr))
    hot = (rise > rise_db) & (level > e.max() + floor_db)
    out: list[int] = []
    i, n = 0, len(rise)
    while i < n:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < n and hot[j]:
            j += 1
        lo = i
        hi = min(len(e), j + w + max(w, gap // 2))
        if hi - lo < 2:
            i = j
            continue
        top = float(np.max(e[lo:hi]))
        k = int(lo + np.argmax(e[lo:hi] >= top - locate_db))
        if not out or k - out[-1] >= gap:
            out.append(k)
        i = j
    return out


# ---------------------------------------------------------------------------
# spectrum
# ---------------------------------------------------------------------------
def spectrum(x, sr: int = SR_DEFAULT, *, pad: int = 1, window: bool = True):
    """(frequencies, magnitude). `pad` zero-pads by that factor, which
    interpolates the line shape; it does not add resolution."""
    x = _as_float(x)
    n = len(x)
    w = np.hanning(n) if window else np.ones(n)
    X = np.abs(np.fft.rfft(x * w, n * max(1, pad)))
    return np.fft.rfftfreq(n * max(1, pad), 1.0 / sr), X


def dominant_frequency(x, lo: float, hi: float, sr: int = SR_DEFAULT, *,
                       min_prominence_db: float = 6.0) -> Estimate:
    """Strongest line in [lo, hi], parabolically interpolated on the log
    magnitude. Refuses when that line does not stand `min_prominence_db` above
    the median of the band -- i.e. when the band holds no line at all."""
    x = _as_float(x)
    if is_silent(x):
        return _fail("silent")
    f, X = spectrum(x, sr)
    sel = (f >= lo) & (f <= hi)
    if sel.sum() < 4:
        return _fail("band too narrow for this window", bins=int(sel.sum()))
    band = np.where(sel, X, 0.0)
    i = int(np.argmax(band))
    # Prominence over the LOCAL median, not the band median: the skirt of a
    # strong line elsewhere is a smooth slope, and against a band median a
    # smooth slope's maximum looks like a 14 dB "line". That mistake reported
    # a resonance in a band that held nothing but leakage.
    k = min(129, (sel.sum() // 2) * 2 + 1)
    lo = max(0, i - k // 2)
    med = float(np.median(X[lo:lo + k])) if k >= 3 else float(np.median(X[sel]))
    prom = db(X[i], med)
    if prom < min_prominence_db:
        return _fail("no prominent line in the band", prominence_db=prom)
    if 0 < i < len(X) - 1:
        a, b, c = (math.log(max(X[j], 1e-300)) for j in (i - 1, i, i + 1))
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den else 0.0
        d = max(-0.5, min(0.5, d))
    else:
        d = 0.0
    return Estimate((i + d) * (f[1] - f[0]), True, "", dict(prominence_db=prom))


def line_at(x, hz: float, sr: int = SR_DEFAULT, *, rel_tol: float = 0.05,
            min_prominence_db: float = 6.0) -> Estimate:
    """The strongest line within +-rel_tol of `hz`. `detail['level']` is its
    magnitude, for comparing lines with each other."""
    e = dominant_frequency(x, hz * (1 - rel_tol), hz * (1 + rel_tol), sr,
                           min_prominence_db=min_prominence_db)
    if not e.ok:
        return e
    f, X = spectrum(x, sr)
    w = np.where((f > hz * (1 - rel_tol)) & (f < hz * (1 + rel_tol)))[0]
    k = int(w[np.argmax(X[w])])
    return Estimate(e.value, True, "", dict(e.detail, level=float(X[k])))


@dataclass(frozen=True)
class LineStats:
    count: int
    peak_to_median: float
    freqs: np.ndarray

    def __repr__(self) -> str:
        return f"LineStats(count={self.count}, peak_to_median={self.peak_to_median:.2f})"


def spectral_lines(x, band=(2000.0, 20000.0), sr: int = SR_DEFAULT, *,
                   threshold: float = 4.0, neighbours: int = 3,
                   med_bins: int = 129) -> LineStats:
    """Prominent spectral lines in `band`.

    A bin is a line when it is the largest of its +-`neighbours` and stands
    `threshold` times above the LOCAL median (a running median, so a sloped
    passband neither creates nor hides lines). `peak_to_median` is the 99th
    percentile of magnitude over local median, which is defined whether or not
    any line clears the threshold.

    THIS DOES NOT PROVE A TOPOLOGY. Filtered noise produces lines too; they are
    just different lines in every window. Use `line_stability` for that, and a
    matched noise control that must fail whatever test you write."""
    x = _as_float(x)
    f, X = spectrum(x, sr)
    sel = (f >= band[0]) & (f <= band[1])
    m, fb = X[sel], f[sel]
    if len(m) < med_bins + 2 * neighbours + 2:
        raise InsufficientEvidence(
            f"window too short for a line count: {len(m)} bins in {band} Hz, need "
            f"{med_bins + 2 * neighbours + 2}")
    k = med_bins | 1
    pad = np.pad(m, k // 2, mode="edge")
    loc = np.maximum(np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=-1), 1e-12)
    is_max = np.ones(len(m), bool)
    for d in range(1, neighbours + 1):
        is_max[d:] &= m[d:] > m[:-d]
        is_max[:-d] &= m[:-d] > m[d:]
    is_max[:neighbours] = False
    is_max[-neighbours:] = False
    hits = is_max & (m > threshold * loc)
    return LineStats(int(hits.sum()), float(np.percentile(m / loc, 99.0)), fb[hits])


def line_stability(x, band=(2000.0, 20000.0), sr: int = SR_DEFAULT, *, windows: int = 4,
                   tol_hz: float = 40.0, min_lines: int = 5, **kw) -> Estimate:
    """Fraction of the lines of the first window that reappear, within
    `tol_hz`, in EVERY other window of the signal.

    Free-running oscillators put their lines in the same places in every
    window; filtered noise does not. This is the discriminator a peak count
    alone cannot give, and it wants a matched noise control beside it."""
    x = _as_float(x)
    n = len(x) // windows
    if n < 256:
        return _fail("windows too short", n=n)
    sets = []
    for w in range(windows):
        try:
            sets.append(spectral_lines(x[w * n:(w + 1) * n], band, sr, **kw).freqs)
        except InsufficientEvidence as exc:
            return _fail(str(exc))
    if len(sets[0]) < min_lines:
        # One or two lines that happen to recur are not evidence of anything,
        # and a comb too dense for the sub-window's resolution lands here too:
        # say so rather than returning a confident 1.0 from a sample of one.
        return _fail("too few lines in the first window to judge stability",
                     n_first=len(sets[0]), counts=[len(v) for v in sets])
    keep = 0
    for hz in sets[0]:
        if all(len(s) and np.min(np.abs(s - hz)) <= tol_hz for s in sets[1:]):
            keep += 1
    return Estimate(keep / len(sets[0]), True, "",
                    dict(n_first=len(sets[0]), counts=[len(s) for s in sets]))


def spectral_flatness(x, band=(2000.0, 20000.0), sr: int = SR_DEFAULT) -> float:
    """Geometric over arithmetic mean of the power spectrum. Provided so that
    `test_audio_measure.py` can demonstrate that it does NOT separate a dense
    comb from noise. Do not use it as a discriminator."""
    f, X = spectrum(x, sr)
    p = X[(f >= band[0]) & (f <= band[1])] ** 2 + 1e-30
    return float(np.exp(np.mean(np.log(p))) / np.mean(p))


def spectral_centroid(x, band=(20.0, 20000.0), sr: int = SR_DEFAULT, *, weight: str = "power") -> float:
    """A descriptor of where the energy sits. NOT a filter corner and NOT a
    band-pass centre -- see rule 3 at the top of this file. `weight` is
    "power" or "amplitude"; they answer different questions and neither is the
    corner frequency of anything."""
    f, X = spectrum(x, sr)
    sel = (f >= band[0]) & (f <= band[1])
    w = X[sel] ** 2 if weight == "power" else X[sel]
    return float(np.sum(f[sel] * w) / np.sum(w))


# ---------------------------------------------------------------------------
# transfer response -- the only honest way to measure a filter
# ---------------------------------------------------------------------------
def transfer(ir, sr: int = SR_DEFAULT):
    """(frequencies, magnitude) of an impulse response. No window: the response
    of a stable filter has already decayed, and windowing would widen it."""
    ir = _as_float(ir)
    if is_silent(ir):
        raise InsufficientEvidence("impulse response is silent")
    return np.fft.rfftfreq(len(ir), 1.0 / sr), np.abs(np.fft.rfft(ir))


def resonant_peak(ir, sr: int = SR_DEFAULT, band=None, *, min_peak_db: float = 1.0) -> Estimate:
    """Frequency of the magnitude maximum of a transfer response. Refuses when
    the response has no peak (within `min_peak_db` of its own edges), because
    a first-order or low-Q filter has none and reporting its argmax as a
    "centre frequency" is a wrong answer dressed as a right one."""
    f, X = transfer(ir, sr)
    sel = np.ones(len(f), bool) if band is None else ((f >= band[0]) & (f <= band[1]))
    idx = np.where(sel)[0]
    i = int(idx[np.argmax(X[idx])])
    if i in (idx[0], idx[-1]):
        return _fail("maximum at the edge of the band: no resonance here", f=float(f[i]))
    edge = max(X[idx[0]], X[idx[-1]])
    if db(X[i], edge) < min_peak_db:
        return _fail("no resonant peak", peak_db=db(X[i], edge))
    a, b, c = (math.log(max(X[j], 1e-300)) for j in (i - 1, i, i + 1))
    den = a - 2 * b + c
    d = max(-0.5, min(0.5, 0.5 * (a - c) / den)) if den else 0.0
    return Estimate((i + d) * (f[1] - f[0]), True, "", dict(peak_db=db(X[i], edge)))


def bandwidth_q(ir, sr: int = SR_DEFAULT, band=None) -> Estimate:
    """Q = f_peak / (-3 dB bandwidth) of a resonant transfer response."""
    pk = resonant_peak(ir, sr, band)
    if not pk.ok:
        return pk
    f, X = transfer(ir, sr)
    i = int(round(pk.value / (f[1] - f[0])))
    half = X[i] / math.sqrt(2)
    lo = np.where(X[:i] < half)[0]
    hi = np.where(X[i:] < half)[0]
    if not len(lo) or not len(hi):
        return _fail("response does not fall 3 dB on both sides")
    bw = float(f[i + hi[0]] - f[lo[-1]])
    if bw <= 0:
        return _fail("degenerate bandwidth")
    return Estimate(pk.value / bw, True, "", dict(bandwidth_hz=bw, peak_hz=pk.value))


def corner_3db(ir, kind: str, sr: int = SR_DEFAULT, *, ref_band=None) -> Estimate:
    """-3 dB corner of a high-pass or low-pass transfer response, measured
    against its own passband plateau (`ref_band`, default the top or bottom
    decade). For a resonant filter this is NOT the peak frequency; ask for
    whichever the reference actually specifies."""
    f, X = transfer(ir, sr)
    nyq = f[-1]
    if kind == "highpass":
        rb = ref_band or (0.65 * nyq, 0.95 * nyq)
    elif kind == "lowpass":
        rb = ref_band or (f[1], 0.02 * nyq)
    else:
        raise ValueError("kind must be 'highpass' or 'lowpass'")
    ref = float(np.median(X[(f >= rb[0]) & (f <= rb[1])]))
    if ref <= 0:
        return _fail("no passband energy")
    half = ref / math.sqrt(2)
    above = np.where(X >= half)[0]
    if not len(above):
        return _fail("response never reaches -3 dB of the passband")
    i = int(above[0] if kind == "highpass" else above[-1])
    if i in (0, len(f) - 1):
        return _fail("corner outside the measurable range", f=float(f[i]))
    return Estimate(float(f[i]), True, "", dict(plateau=ref))


# ---------------------------------------------------------------------------
# comparison -- level and shape are two separate claims
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Comparison:
    level_db: float          # peak of a relative to peak of b
    residual_db: float       # residual RMS relative to b's RMS, WITHOUT rescaling
    shape_db: float          # the same after matching gain: waveform similarity alone


def compare(a, b) -> Comparison:
    """Compare two signals without hiding a gain error.

    `residual_db` is the honest one: the difference of the signals as they are.
    `shape_db` rescales `a` to `b` first and so answers only "is the waveform
    the same shape", and `level_db` reports the gain that was removed. Never
    quote `shape_db` on its own."""
    a, b = _as_float(a), _as_float(b)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    rb = rms(b)
    lvl = db(peak(a), peak(b))
    resid = db(rms(a - b), rb)
    g = (float(np.dot(a, b)) / float(np.dot(a, a))) if float(np.dot(a, a)) > 0 else 0.0
    shape = db(rms(a * g - b), rb)
    return Comparison(lvl, resid, shape)


# ---------------------------------------------------------------------------
# envelope shape: bursts
# ---------------------------------------------------------------------------
def envelope_bursts(env, sr: int = SR_DEFAULT, *, window_s: float | None = None,
                    level_frac: float = 0.4, min_sep_s: float = 0.005,
                    min_dip_db: float = 3.0):
    """Re-strikes in an envelope: [(time_s, level_relative_to_peak)].

    A peak counts when it reaches `level_frac` of the envelope peak, is
    `min_sep_s` from the last accepted one, AND the envelope dipped at least
    `min_dip_db` between the two. The dip requirement is what stops a plain
    exponential decay being reported as a train of bursts: numerical ripple
    makes local maxima everywhere, and without it a single hit reads as three.

    Give it an AVERAGED envelope (`average_envelope`) when the signal is
    noise-excited, and give the signal a few ms of PRE-ROLL before the strike
    -- the analytic envelope needs run-in, and without it the first burst reads
    low and the levels come out in the wrong order."""
    env = _as_float(env)
    n = len(env) if window_s is None else min(len(env), int(window_s * sr))
    if n < 3 or env.max() <= 0:
        return []
    pk = float(env.max())
    sep = max(1, int(min_sep_s * sr))
    idx = np.where((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]))[0] + 1
    keep: list[int] = []
    for i in idx:
        if i >= n or env[i] < level_frac * pk:
            continue
        if not keep:
            keep.append(int(i))
            continue
        j = keep[-1]
        if i - j < sep:
            if env[i] > env[j]:
                keep[-1] = int(i)
            continue
        dip = float(np.min(env[j:i + 1]))
        if db(env[i], dip) < min_dip_db:
            continue                      # same decay, not a new strike
        keep.append(int(i))
    return [(i / sr, float(env[i] / pk)) for i in keep]


def natural_frequency_from_peak(f_peak: float, q: float) -> float:
    """A resonant two-pole filter's natural frequency f0 from where its
    magnitude response peaks: f_peak = f0 / sqrt(1 - 1/(2 Q^2)).

    The -3 dB corner, the resonant peak and f0 are three different numbers for
    a resonant filter -- at Q 2.5 the -3 dB point sits about 28 % BELOW f0
    while the peak sits 4 % above it. Reference tables usually quote f0, so
    convert rather than comparing whichever one the measurement produced;
    comparing a measured -3 dB corner with a table's f0 made a hi-hat
    high-pass look 22 % wrong when it was 2 % right."""
    k = 1 - 1 / (2 * q * q)
    if k <= 0:
        raise InsufficientEvidence(f"Q {q} is too low for a resonant peak")
    return f_peak * math.sqrt(k)


def average_envelope(signals, method: str = "rms", window_ms: float = 2.0,
                     sr: int = SR_DEFAULT) -> np.ndarray:
    """Mean envelope of several renders of the same event whose noise is
    differently aligned. Deterministic envelope structure survives; the noise
    averages down. Without this the clap's three bursts are not measurable at
    all. `method` is "rms" (default -- these signals are broadband) or
    "analytic"."""
    if method == "rms":
        envs = [rms_envelope(s, window_ms, sr) for s in signals]
    else:
        envs = [analytic_envelope(s) for s in signals]
    n = min(len(e) for e in envs)
    return np.mean([e[:n] for e in envs], axis=0)


# ===========================================================================
# ADDITIONS FOR THE MONOSYNTH VOICE (model/test_moog_acceptance.py)
#
# Everything above measures a struck, decaying drum. A subtractive voice asks
# different questions -- a filter's transfer response AT A STATED DRIVE, the
# harmonic series of an oscillator, where an alias lands, whether a control
# change steps the signal -- so these estimators are added under the same rule:
# each is exercised against a signal with an analytically known answer in
# `test_audio_measure.py`, and each can refuse.
# ===========================================================================
def tonality_db(x, band=(20.0, 20000.0), sr: int = SR_DEFAULT) -> float:
    """Strongest bin over the MEDIAN bin, in dB: is there a line in here at all.

    Distinct from `spectral_lines(...).peak_to_median`, which is a 99th
    percentile and so answers "is this spectrum full of lines"; a single
    sustained tone leaves that at 1.0. Use this one to tell a self-oscillating
    filter from its own truncation noise, and `spectral_flatness` for neither
    (it is in this module only as the counter-example)."""
    f, X = spectrum(x, sr)
    sel = (f >= band[0]) & (f <= band[1])
    p = X[sel] ** 2
    med = float(np.median(p))
    if med <= 0 or not len(p):
        raise InsufficientEvidence("tonality_db: degenerate spectrum")
    return db(math.sqrt(float(p.max())), math.sqrt(med))


def tone_amplitude(x, hz: float, sr: int = SR_DEFAULT, *,
                   min_periods: float = 8.0) -> Estimate:
    """Amplitude of a sinusoid at exactly `hz`, by coherent projection.

    The primitive for a STEPPED-SINE transfer measurement, which is how a
    nonlinear filter has to be measured: an impulse response (`transfer`)
    presumes linearity and cannot state the drive level it was taken at, and
    the ladder's response depends on level by design. The projection rejects
    broadband noise by 2/sqrt(N) of its amplitude, which is what makes a
    stopband readable at a fraction of an LSB.

    Refuses a record shorter than `min_periods` periods: the projection of
    three cycles is a guess with a plausible value."""
    x = _as_float(x)
    if is_silent(x):
        return _fail("silent")
    n = len(x)
    if hz <= 0 or hz >= sr / 2:
        return _fail("frequency outside (0, Nyquist)", hz=hz)
    periods = n / (sr / hz)
    if periods < min_periods:
        return _fail("too few periods for a coherent projection", periods=periods)
    w = np.exp(-2j * math.pi * hz * np.arange(n) / sr)
    return Estimate(float(2.0 * np.abs((x * w).sum()) / n), True, "",
                    dict(periods=periods, rms=rms(x)))


def zero_crossing_frequency(x, sr: int = SR_DEFAULT, *, min_crossings: int = 5) -> Estimate:
    """Frequency from interpolated upward zero crossings, first to last.

    The estimator for a FREE RING whose amplitude is changing over the record:
    a windowed FFT of a growing or decaying sinusoid is smeared by the
    envelope, while the crossings are not. Wrong for anything with more than
    one component; `dominant_frequency` is for those."""
    x = _as_float(x)
    if is_silent(x):
        return _fail("silent")
    x = x - x.mean()
    s = np.signbit(x)
    up = np.nonzero(s[:-1] & ~s[1:])[0]
    if len(up) < min_crossings:
        return _fail("too few zero crossings", crossings=int(len(up)))
    t = up + (-x[up]) / (x[up + 1] - x[up])
    return Estimate(float((len(t) - 1) / ((t[-1] - t[0]) / sr)), True, "",
                    dict(crossings=int(len(up))))


def harmonic_powers(x, f0: float, ks, sr: int = SR_DEFAULT, *, guard: int = 4) -> np.ndarray:
    """Power in +-`guard` bins around each harmonic `k*f0`.

    The bins are SUMMED, never max'ed: a Hann window spreads a partial over
    three bins, and a partial whose frequency falls between bins reads up to
    1.4 dB low from its peak bin alone. Raises when a requested harmonic is
    above Nyquist or when f0 is so low that neighbouring guards would touch."""
    x = _as_float(x)
    if is_silent(x):
        raise InsufficientEvidence("harmonic_powers: silent")
    n = len(x)
    f, X = spectrum(x, sr)
    p = X ** 2
    if f0 * n / sr < 2 * guard + 1:
        raise InsufficientEvidence(
            f"harmonic_powers: f0 {f0} Hz spans {f0*n/sr:.1f} bins, guards overlap")
    out = []
    for k in ks:
        if k * f0 >= sr / 2:
            raise InsufficientEvidence(f"harmonic_powers: harmonic {k} of {f0} Hz is above Nyquist")
        c = int(round(k * f0 * n / sr))
        out.append(p[max(0, c - guard):c + guard + 1].sum())
    return np.array(out, dtype=np.float64)


def inharmonic_fraction_db(x, f0: float, sr: int = SR_DEFAULT, *, guard: int = 5) -> Estimate:
    """Energy OUTSIDE +-`guard` bins of every harmonic of `f0`, as a fraction
    of total, in dB. DR 0001's aliasing measure, so its numbers compare
    directly with that record's table.

    Its floor is the window's: +-5 Hann bins leave about -54 dB of leakage
    from the harmonics themselves, so a reading near -54 dB means "nothing
    inharmonic is resolvable", not a measured level. Refuses when the guards
    would cover more than half the spectrum, which is where this measure stops
    meaning anything and `foldback_alias_db` (or a higher-rate reference) is
    the estimator to use."""
    x = _as_float(x)
    if is_silent(x):
        return _fail("silent")
    n = len(x)
    f, X = spectrum(x, sr)
    p = X ** 2
    harm = np.zeros_like(p, dtype=bool)
    k = 1
    while k * f0 < sr / 2:
        c = int(round(k * f0 * n / sr))
        harm[max(0, c - guard):c + guard + 1] = True
        k += 1
    harm[:guard + 1] = True
    if harm.mean() > 0.5:
        return _fail("harmonic guards cover the spectrum", covered=float(harm.mean()))
    return Estimate(10.0 * math.log10(max(p[~harm].sum(), 1e-300) / p.sum()), True, "",
                    dict(covered=float(harm.mean())))


def fold_frequency(hz: float, sr: int = SR_DEFAULT) -> float:
    """Where a component at `hz` appears after sampling at `sr`."""
    r = hz % sr
    return sr - r if r > sr / 2 else r


def foldback_alias_db(x, f0: float, sr: int = SR_DEFAULT, *, kmax: int = None,
                      guard: int = 5, max_occupancy: float = 0.60,
                      max_collision: float = 0.25) -> Estimate:
    """Energy at the PREDICTED image frequencies of the harmonics above
    Nyquist, as a fraction of total, in dB.

    Top-octave energy is not aliasing: legitimate harmonics live there and
    aliases land elsewhere. An ideal saw or square has every harmonic `k*f0`,
    and a naive oscillator images the ones above `sr/2` at
    `fold_frequency(k*f0)` -- computable in advance, which is where this looks
    and nowhere else.

    Refuses when too many predicted images fall within a guard of a real
    harmonic (they cannot be attributed) or when the image bins cover more
    than `max_occupancy` of the spectrum, which is what happens at a low f0
    where the images are dense. `detail['images']` is how many were used."""
    x = _as_float(x)
    if is_silent(x):
        return _fail("silent")
    n = len(x)
    f, X = spectrum(x, sr)
    p = X ** 2
    bins_per_hz = n / sr
    kn = int(sr / 2 / f0)
    if kn < 1:
        return _fail("no harmonic below Nyquist", f0=f0)
    kmax = kmax if kmax is not None else int(6 * sr / f0)
    real = np.array([k * f0 for k in range(1, kn + 1)])
    images, collided = [], 0
    for k in range(kn + 1, kmax + 1):
        fa = fold_frequency(k * f0, sr)
        if fa < 30.0 or fa > sr / 2 - 30.0:
            continue
        if np.abs(real - fa).min() < (2 * guard + 1) / bins_per_hz:
            collided += 1
            continue
        images.append(fa)
    if len(images) < 5:
        return _fail("too few usable images", images=len(images), collided=collided)
    if collided > max_collision * (len(images) + collided):
        return _fail("predicted images collide with real harmonics",
                     images=len(images), collided=collided)
    mask = np.zeros_like(p, dtype=bool)
    for fa in images:
        c = int(round(fa * bins_per_hz))
        mask[max(0, c - guard):c + guard + 1] = True
    if mask.mean() > max_occupancy:
        return _fail("image bins cover the spectrum", occupancy=float(mask.mean()),
                     images=len(images))
    return Estimate(10.0 * math.log10(max(p[mask].sum(), 1e-300) / p.sum()), True, "",
                    dict(images=len(images), collided=collided,
                         occupancy=float(mask.mean())))


def max_sample_step(x) -> float:
    """Largest sample-to-sample jump: a click detector. A control write that
    steps the signal is audible however small the spectral change, and a step
    is invisible to every spectral estimator in this module."""
    x = _as_float(x)
    if len(x) < 2:
        raise InsufficientEvidence("max_sample_step: fewer than two samples")
    return float(np.abs(np.diff(x)).max())


def longest_plateau(x) -> int:
    """Longest run of identical consecutive values -- a stair-step detector.
    An envelope that holds still for 500 frames and then jumps is a staircase
    whatever its average slope."""
    x = np.asarray(x)
    if x.size == 0:
        return 0
    change = np.nonzero(np.diff(x))[0]
    edges = np.concatenate([[-1], change, [len(x) - 1]])
    return int(np.diff(edges).max())


def event_slices(gate) -> list:
    """(start, stop) of each run of a non-zero gate.

    Analyse events separately. The statistics of a whole render are the
    statistics of whichever note was loudest, and a tail that never ends hides
    behind the next note's attack -- which is how a self-oscillating patch
    that never went silent was auditioned for weeks without anyone hearing
    it."""
    g = np.asarray(gate).astype(bool).astype(np.int8)
    if g.size == 0:
        return []
    d = np.diff(np.concatenate([[0], g, [0]]))
    return list(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))
