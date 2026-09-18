"""Per-partial amplitude TRAJECTORY estimator for a decaying percussive hit.

The quantity a 'partial balance' should name is the ratio of the partials'
amplitudes AT THE STRIKE (A0), together with how that ratio evolves, because
partials with different decay constants make a single-window ratio a function
of the window rather than of the voice.

Method, per partial:
  1. frequency by peak of the coherent projection magnitude on a fine grid
     (a damped sinusoid's DTFT magnitude is a Lorentzian centred on f0);
  2. amplitude trajectory A(t) by a sliding Hann-windowed coherent projection
     at that frequency, normalised by the window's coherent gain;
  3. A0 and tau by a weighted log-linear fit of A(t), with the Hann window's
     own exponential-averaging bias divided out (it is a constant factor for an
     exponential, so it biases A0 and not tau; solved by one fixed-point pass);
  4. a FLOOR measured on the same record and the same window, by projecting at
     guard frequencies that hold no partial. Any point within `floor_margin_db`
     of it is dropped, and a fit with too few surviving points REFUSES.
"""
import math
import numpy as np


def _hann(n):
    return np.hanning(n + 2)[1:-1] if n > 2 else np.ones(n)


def project(x, f, sr, w=None):
    """Amplitude of a sinusoid at f over the whole of x, window-corrected.
    For a stationary tone of amplitude A this returns exactly A."""
    n = len(x)
    if w is None:
        w = np.ones(n)
    k = np.exp(-2j * math.pi * f * np.arange(n) / sr)
    return 2.0 * abs(np.sum(w * x * k)) / np.sum(w)


def find_partial(x, sr, f_lo, f_hi, *, seconds=None, df=0.05):
    """Frequency of the strongest line in [f_lo, f_hi], by a fine grid search of
    the coherent projection over the first `seconds` of the record."""
    y = x if seconds is None else x[: int(seconds * sr)]
    n = len(y)
    grid = np.arange(f_lo, f_hi + df, df)
    t = np.arange(n) / sr
    # chunked so the grid x n outer product stays small
    best_f, best_v = None, -1.0
    for i in range(0, len(grid), 256):
        g = grid[i:i + 256]
        k = np.exp(-2j * math.pi * np.outer(g, t))
        v = np.abs(k @ y)
        j = int(np.argmax(v))
        if v[j] > best_v:
            best_v, best_f = float(v[j]), float(g[j])
    return best_f


def trajectory(x, sr, f, *, win_ms=20.0, hop_ms=2.0, t_end=None):
    """Sliding Hann-windowed projection at f. Returns (t_centres, amplitude)."""
    W = int(win_ms * 1e-3 * sr)
    H = max(1, int(hop_ms * 1e-3 * sr))
    w = _hann(W)
    n = len(x) if t_end is None else min(len(x), int(t_end * sr))
    ts, amps = [], []
    for a in range(0, n - W + 1, H):
        seg = x[a:a + W]
        amps.append(project(seg, f, sr, w))
        ts.append((a + W / 2.0) / sr)
    return np.asarray(ts), np.asarray(amps)


def floor_at(x, sr, f, guards, *, win_ms=20.0, hop_ms=2.0, t_end=None):
    """The estimator's own floor for this record, this window and this f: the
    LARGEST trajectory found at frequencies that hold no partial. Leakage from
    the real partials is inside this number by construction, which is the point
    -- issue #92 asks for a floor measured from the same record, not a quoted
    constant."""
    worst = None
    for g in guards:
        _, a = trajectory(x, sr, g, win_ms=win_ms, hop_ms=hop_ms, t_end=t_end)
        worst = a if worst is None else np.maximum(worst, a)
    return worst


def _hann_exp_gain(W, tau, sr):
    """Hann-weighted mean of exp(-t/tau) about the window centre. A constant
    factor for an exponential, so it shifts A0 and not tau."""
    w = _hann(W)
    d = (np.arange(W) - W / 2.0) / sr
    return float(np.sum(w * np.exp(-d / tau)) / np.sum(w))


def fit_decay(ts, amps, *, floor=None, floor_margin_db=6.0, sr=None, win_ms=20.0,
              min_points=5, min_span_ms=4.0):
    """A0 and tau from a log-linear fit, dropping every point inside the floor.

    Returns dict(ok, A0, tau_ms, n_points, span_ms, resid_db, reason)."""
    keep = np.ones(len(ts), dtype=bool)
    if floor is not None:
        keep &= amps > floor * (10.0 ** (floor_margin_db / 20.0))
    keep &= amps > 0
    if keep.sum() < min_points:
        return dict(ok=False, reason=f"only {int(keep.sum())} points clear the floor "
                                     f"by {floor_margin_db:.0f} dB (need {min_points})")
    t, a = ts[keep], amps[keep]
    # contiguous run from the peak onward -- the decay, not the attack
    pk = int(np.argmax(a))
    t, a = t[pk:], a[pk:]
    if len(t) < min_points:
        return dict(ok=False, reason=f"only {len(t)} points after the peak (need {min_points})")
    span_ms = (t[-1] - t[0]) * 1e3
    if span_ms < min_span_ms:
        return dict(ok=False, reason=f"decay spans {span_ms:.1f} ms (need {min_span_ms})")
    A0, tau = None, None
    for _ in range(12):                       # fixed point on the window bias
        c = np.polyfit(t, np.log(a), 1)
        tau_new = -1.0 / c[0] if c[0] < 0 else None
        if tau_new is None or not np.isfinite(tau_new) or tau_new <= 0:
            return dict(ok=False, reason="fitted envelope does not decay")
        g = _hann_exp_gain(int(win_ms * 1e-3 * sr), tau_new, sr) if sr else 1.0
        A0_new = math.exp(c[1]) / g
        if tau is not None and abs(tau_new - tau) < 1e-9 and abs(A0_new - A0) < 1e-12:
            A0, tau = A0_new, tau_new
            break
        A0, tau = A0_new, tau_new
    pred = np.log(A0 * _hann_exp_gain(int(win_ms*1e-3*sr), tau, sr) * np.exp(-t / tau)) if sr \
        else np.log(A0 * np.exp(-t / tau))
    resid_db = float(np.sqrt(np.mean((20.0 / math.log(10)) ** 2 * (np.log(a) - pred) ** 2)))
    return dict(ok=True, A0=float(A0), tau_ms=float(tau * 1e3), n_points=int(len(t)),
                span_ms=float(span_ms), resid_db=resid_db, t0=float(t[0]), reason="")


def measure(x, sr, f_lo_range, f_hi_range, *, win_ms=20.0, hop_ms=2.0,
            search_s=None, t_end=None, guards=None, floor_margin_db=6.0):
    """Both partials of a two-mode voice: frequency, A0, tau, and the balance."""
    f_lo = find_partial(x, sr, *f_lo_range, seconds=search_s)
    f_hi = find_partial(x, sr, *f_hi_range, seconds=search_s)
    out = {"f_lo": f_lo, "f_hi": f_hi}
    for tag, f in (("lo", f_lo), ("hi", f_hi)):
        ts, a = trajectory(x, sr, f, win_ms=win_ms, hop_ms=hop_ms, t_end=t_end)
        g = guards.get(tag) if guards else None
        fl = floor_at(x, sr, f, g, win_ms=win_ms, hop_ms=hop_ms, t_end=t_end) if g else None
        fit = fit_decay(ts, a, floor=fl, floor_margin_db=floor_margin_db, sr=sr, win_ms=win_ms)
        out[tag] = dict(f=f, ts=ts, amp=a, floor=fl, fit=fit)
    return out
