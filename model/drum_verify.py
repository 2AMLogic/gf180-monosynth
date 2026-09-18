#!/usr/bin/env python3
"""Measure the rendered drum section against recordings of a real TR-808.

    .venv/bin/python model/drum_verify.py --refs <dir> --ours <dir> --out docs/img/drum-verification

Nothing here is a judgement: it reports numbers and draws pictures. The
verdicts live in docs/drum-verification.md.

REFERENCE SET (primary), CC0-1.0, committed nowhere -- fetch it yourself:

    git clone https://github.com/tidalcycles/sounds-tr808-fischer

    Michael Fischer / Technopolis, "Roland TR-808 Rhythm Composer Sound
    Sample Set 1.0.0" (1994), relicensed CC0-1.0 by the TidalCycles project.
    Sampled from a real TR-808, SERIAL NO. 103852, from the INDIVIDUAL VOICE
    OUTPUTS (not the master bus), 16-bit/44.1 kHz. Every knob position is in
    the filename on a 0..10 scale sampled at 00/25/50/75/10, TONE or TUNING
    before DECAY or SNAPPY: BD5050 = bass drum, TONE 5.0, DECAY 5.0 -- which
    is the "all knobs at 12 o'clock" condition of Roland's own June-1981
    tuning chart (docs/tr808-reference.md section 1.6), so it is the setting
    every one of our presets is nominally derived from.

    Caveat the set itself states: LEVEL was pinned at maximum for every
    voice, so RELATIVE LEVELS BETWEEN VOICES ARE NOT THE MACHINE'S. Compare
    shapes and spectra across voices, never loudness.

MEASUREMENT RULES, because the easy versions of these are all wrong:

  * Our solo renders hold THREE hits (0.05 s at accent 1.0, 0.75 s at 1.4,
    1.45 s at 0.6). Segment first. Measuring first-onset to global-peak over
    a whole solo file reports the second hit's peak and yields a spurious
    ~700 ms attack.
  * Decay is a REGRESSION on log-envelope over a stated dB range, not the
    first crossing of 1/e. The hats and cowbell are sums of squares whose
    envelopes beat by several dB; a first-crossing reads the first trough and
    can be 10x low. We report tau_fit, the fit's R^2 and the range it covers,
    plus t(-20 dB) which is comparable to Roland's chart column.
  * Envelope is a moving RMS, not |hilbert| alone, for the same reason.
  * Sample rates differ (refs 44.1 k, ours 48 k). Every metric here is
    rate-independent; nothing is resampled.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks, get_window

warnings.filterwarnings("ignore", message=".*EOF.*")

STOPS = ["BD", "SD", "LT", "HT", "CH", "OH", "CP", "CB"]
HIT_TIMES = (0.05, 0.75, 1.45)          # drums_fx_render.solo_renders
HIT_ACCENTS = (1.0, 1.4, 0.6)

# Our voice -> the Fischer file at the chart's 12-o'clock knob positions.
REF_MAIN = {
    "BD": ("bd8/BD5050.WAV", "TONE 5.0, DECAY 5.0"),
    "SD": ("sd8/SD5050.WAV", "TONE 5.0, SNAPPY 5.0"),
    "LT": ("lt8/LT50.WAV", "TUNING 5.0"),
    "HT": ("ht8/HT50.WAV", "TUNING 5.0"),
    "CH": ("ch8/CH.WAV", "no knob"),
    "OH": ("oh8/OH50.WAV", "DECAY 5.0"),
    "CP": ("cp8/CP.WAV", "no knob"),
    "CB": ("cb8/CB.WAV", "no knob"),
}
# Knob sweeps, for the laws rather than the single points.
REF_SWEEPS = {
    "BD-decay": [("bd8/BD50%s.WAV" % k, lbl) for k, lbl in
                 (("00", "0.0"), ("25", "2.5"), ("50", "5.0"), ("75", "7.5"), ("10", "10.0"))],
    "OH-decay": [("oh8/OH%s.WAV" % k, lbl) for k, lbl in
                 (("00", "0.0"), ("25", "2.5"), ("50", "5.0"), ("75", "7.5"), ("10", "10.0"))],
    "LT-tune": [("lt8/LT%s.WAV" % k, lbl) for k, lbl in
                (("00", "0.0"), ("25", "2.5"), ("50", "5.0"), ("75", "7.5"), ("10", "10.0"))],
    "HT-tune": [("ht8/HT%s.WAV" % k, lbl) for k, lbl in
                (("00", "0.0"), ("25", "2.5"), ("50", "5.0"), ("75", "7.5"), ("10", "10.0"))],
}

# Bands the centroid and the line test are taken over, and what
# docs/tr808-reference.md section 12 says to expect.
BAND = {"BD": (20, 2000), "SD": (20, 16000), "LT": (20, 2000), "HT": (20, 2000),
        "CH": (2000, 20000), "OH": (2000, 20000), "CP": (200, 16000), "CB": (200, 16000)}
LINE_BAND = {"CH": (5000, 15000), "OH": (5000, 15000), "CB": (400, 6000)}
# Envelope RMS window: several periods of the voice's own fundamental, so the
# moving RMS does not ripple at 2*f0 (BD at 50 Hz needs 12 ms; a hat does not).
ENV_WIN_MS = {"BD": 12.0, "SD": 6.0, "LT": 10.0, "HT": 6.0,
              "CH": 3.0, "OH": 4.0, "CP": 4.0, "CB": 6.0}
# Spectrogram / spectrum ceiling: showing a 50 Hz kick on a 16 kHz axis is a
# black rectangle.
PLOT_FMAX = {"BD": 600, "SD": 12000, "LT": 900, "HT": 1200,
             "CH": 16000, "OH": 16000, "CP": 12000, "CB": 8000}
# Bands the energy split is reported over: "body" vs "noise/air".
SPLIT_HZ = {"BD": 200, "SD": 700, "LT": 400, "HT": 600,
            "CH": 9000, "OH": 9000, "CP": 2000, "CB": 1400}

SPEC = {  # docs/tr808-reference.md section 12 + 14, at the chart's knob positions
    "BD": dict(f0=56.0, tau_ms=127.0, chart_ms=300.0, note="attack ~130 Hz for 4 ms"),
    "SD": dict(f0=173.0, tau_ms=30.0, chart_ms=60.0, note="+336 Hz mode, noise HP 2.75 kHz"),
    "LT": dict(f0=90.0, tau_ms=88.0, chart_ms=200.0, note="pink noise, 1-pole LP 400 Hz"),
    "HT": dict(f0=185.0, tau_ms=43.0, chart_ms=100.0, note="pink noise, 1-pole LP 400 Hz"),
    "CH": dict(f0=None, tau_ms=22.0, chart_ms=50.0, note="6 squares -> BP 7.1k -> HP 11.7k Q2.5"),
    "OH": dict(f0=None, tau_ms=196.0, chart_ms=450.0, note="6 squares -> BP 7.1k -> HP 7.8k Q2.5"),
    "CP": dict(f0=1071.0, tau_ms=47.0, chart_ms=100.0, note="3 bursts ~10 ms in 30 ms + tail"),
    "CB": dict(f0=800.0, tau_ms=22.0, chart_ms=50.0, note="squares 540 + 800 -> BP"),
}

# The six Schmitt-trigger oscillators, docs/tr808-reference.md section 1.5.
OSC_NOMINAL = [205.3, 369.6, 304.4, 522.7, 800.0, 540.0]


# ---------------------------------------------------------------- io ----------
def read_wav(path: str) -> tuple[int, np.ndarray]:
    """Mono float64, DC removed, peak-normalised to 1.0. Levels are not
    comparable across the reference set anyway (LEVEL was pinned at max)."""
    sr, x = wavfile.read(path)
    x = np.asarray(x)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype(np.float64)
    if np.issubdtype(np.asarray(wavfile.read(path)[1]).dtype, np.integer):
        x = x / 32768.0
    x = x - x.mean()
    pk = np.abs(x).max()
    return sr, (x / pk if pk > 0 else x)


def segment_hits(x: np.ndarray, sr: int) -> list[np.ndarray]:
    """Our solo renders, cut at the three scheduled hit times. The last runs
    to the end of the file."""
    out = []
    for i, t in enumerate(HIT_TIMES):
        a = int(t * sr)
        b = int(HIT_TIMES[i + 1] * sr) if i + 1 < len(HIT_TIMES) else len(x)
        out.append(x[a:min(b, len(x))])
    return out


def trim_onset(x: np.ndarray, sr: int, frac: float = 0.02) -> np.ndarray:
    """Drop leading silence: back up 1 ms from the first sample above `frac`
    of the peak so no attack is clipped."""
    pk = np.abs(x).max()
    if pk <= 0:
        return x
    idx = np.nonzero(np.abs(x) > frac * pk)[0]
    if not len(idx):
        return x
    return x[max(0, idx[0] - int(1e-3 * sr)):]


# ------------------------------------------------------------ envelope --------
def envelope(x: np.ndarray, sr: int, win_ms: float = 4.0) -> np.ndarray:
    """Moving RMS. A square-sum voice's |hilbert| beats by 6-10 dB between
    partials; an RMS over several periods of the beat does not."""
    k = max(3, int(win_ms * 1e-3 * sr) | 1)
    return np.sqrt(np.convolve(x * x, np.ones(k) / k, mode="same"))


def decay_fit(env: np.ndarray, sr: int, lo_db: float = -3.0, hi_db: float = -30.0) -> dict:
    """Least-squares tau from the log-envelope between lo_db and hi_db below
    the peak. Returns tau in ms, R^2, the dB span actually fitted, and
    t(-20 dB) from the peak."""
    pk = int(np.argmax(env))
    ref = env[pk]
    if ref <= 0:
        return dict(tau_ms=float("nan"), r2=float("nan"), span_db=0.0, t20_ms=float("nan"))
    tail = env[pk:]
    db = 20 * np.log10(np.maximum(tail, ref * 1e-7) / ref)
    # stop at the first point that is clearly the noise floor or a retrigger
    stop = len(db)
    below = np.nonzero(db <= hi_db)[0]
    if len(below):
        stop = below[0] + 1
    sel = np.nonzero((db[:stop] <= lo_db) & (db[:stop] > hi_db))[0]
    t20 = float("nan")
    b20 = np.nonzero(db <= -20.0)[0]
    if len(b20):
        t20 = b20[0] / sr * 1e3
    if len(sel) < 8:
        return dict(tau_ms=float("nan"), r2=float("nan"), span_db=0.0, t20_ms=t20)
    t = sel / sr
    y = db[sel]
    A = np.vstack([t, np.ones_like(t)]).T
    slope, icept = np.linalg.lstsq(A, y, rcond=None)[0]
    resid = y - (slope * t + icept)
    ss = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - np.sum(resid ** 2) / ss if ss > 0 else float("nan")
    tau = -20.0 / np.log(10.0) / slope if slope < 0 else float("nan")   # dB/s -> tau
    return dict(tau_ms=tau * 1e3, r2=float(r2), span_db=float(y.max() - y.min()), t20_ms=t20)


def attack_ms(env: np.ndarray, sr: int) -> float:
    """Onset (2 % of peak) to peak."""
    pk = int(np.argmax(env))
    thr = 0.02 * env[pk]
    idx = np.nonzero(env[:pk + 1] > thr)[0]
    on = idx[0] if len(idx) else 0
    return (pk - on) / sr * 1e3


# ------------------------------------------------------------ spectrum --------
def spectrum(x: np.ndarray, sr: int, nfft: int = 1 << 18) -> tuple[np.ndarray, np.ndarray]:
    w = x * get_window("hann", len(x))
    S = np.abs(np.fft.rfft(w, nfft))
    return np.fft.rfftfreq(nfft, 1.0 / sr), S


def peak_hz(f: np.ndarray, S: np.ndarray, lo: float, hi: float) -> float:
    """Parabolic-interpolated spectral maximum inside [lo, hi]."""
    b = (f >= lo) & (f <= hi)
    if not b.any():
        return float("nan")
    i = np.nonzero(b)[0][np.argmax(S[b])]
    if 0 < i < len(S) - 1:
        a, c = S[i - 1], S[i + 1]
        d = a - 2 * S[i] + c
        off = 0.5 * (a - c) / d if d != 0 else 0.0
        return float(f[i] + off * (f[1] - f[0]))
    return float(f[i])


def centroid_hz(f: np.ndarray, S: np.ndarray, lo: float, hi: float) -> float:
    b = (f >= lo) & (f <= hi)
    P = S[b]
    return float((f[b] * P).sum() / P.sum()) if P.sum() > 0 else float("nan")


def flatness_db(f: np.ndarray, S: np.ndarray, lo: float, hi: float) -> float:
    """10*log10(geometric mean / arithmetic mean of the power spectrum).
    White noise -> about -2 dB; a comb of discrete partials -> -9 dB or
    lower. THE diagnostic for 'six square oscillators or noise?'."""
    b = (f >= lo) & (f <= hi)
    P = S[b] ** 2 + 1e-30
    return float(10 * np.log10(np.exp(np.log(P).mean()) / P.mean()))


def count_lines(f: np.ndarray, S: np.ndarray, lo: float, hi: float,
                prom_db: float = 10.0) -> tuple[int, np.ndarray]:
    """Spectral peaks at least prom_db prominent, inside the band."""
    b = (f >= lo) & (f <= hi)
    fb, Sb = f[b], S[b]
    if not len(Sb) or Sb.max() <= 0:
        return 0, np.array([])
    db = 20 * np.log10(Sb / Sb.max() + 1e-12)
    pk, _ = find_peaks(db, prominence=prom_db)
    return len(pk), fb[pk]


def noise_control(x: np.ndarray, sr: int, lo: float, hi: float, seed: int = 0) -> float:
    """Flatness of white noise band-limited to the same band and given the
    same envelope as x: what a noise-based emulation of this voice would
    measure. The 'noise or squares' test needs this because a short decay
    broadens every line and raises flatness on its own."""
    rng = np.random.default_rng(seed)
    n = rng.normal(size=len(x))
    F = np.fft.rfft(n)
    fr = np.fft.rfftfreq(len(n), 1.0 / sr)
    F[(fr < lo) | (fr > hi)] = 0
    n = np.fft.irfft(F, len(n))
    env_x = envelope(x, sr)
    env_n = envelope(n, sr) + 1e-12
    y = n * (env_x / env_n)
    f, S = spectrum(y, sr)
    return flatness_db(f, S, lo, hi)


def burst_times(x: np.ndarray, sr: int, window_ms: float = 60.0) -> np.ndarray:
    """Envelope maxima in the first window_ms: the clap's burst structure.
    A 1 ms RMS window -- the bursts are ~10 ms apart, so a 4 ms one smears
    them together."""
    n = int(window_ms * 1e-3 * sr)
    e = envelope(x[:n], sr, win_ms=1.0)
    if not len(e) or e.max() <= 0:
        return np.array([])
    pk, _ = find_peaks(e, height=0.2 * e.max(), distance=int(3e-3 * sr))
    return pk / sr * 1e3


# ------------------------------------------------------------- measure --------
def measure(x: np.ndarray, sr: int, voice: str) -> dict:
    x = trim_onset(x, sr)
    if not len(x) or np.abs(x).max() <= 0:
        return dict(silent=True)
    env = envelope(x, sr, win_ms=ENV_WIN_MS[voice])
    lo, hi = BAND[voice]
    # analysis window: the whole hit, capped so a long file does not dilute
    n = min(len(x), int(0.5 * sr))
    f, S = spectrum(x[:n], sr)
    fa, Sa = spectrum(x[:int(4e-3 * sr)], sr, nfft=1 << 15)   # the first 4 ms
    d = decay_fit(env, sr)
    out = dict(
        silent=False,
        dur_ms=len(x) / sr * 1e3,
        attack_ms=attack_ms(env, sr),
        peak_hz=peak_hz(f, S, lo, hi),
        centroid_hz=centroid_hz(f, S, lo, hi),
        attack_peak_hz=peak_hz(fa, Sa, 20, min(hi, sr / 2 - 1)),
        **d,
    )
    # energy split: how much of the voice is body and how much is the
    # noise/air above it. The magnitude centroid alone hides this -- a voice
    # with 98 % of its energy under 700 Hz can still show a 6.5 kHz centroid
    # because magnitude weighting counts a wide, quiet noise floor heavily.
    P = S ** 2
    cut = SPLIT_HZ[voice]
    tot = P[(f > lo) & (f < hi)].sum()
    out["body_pct"] = float(100 * P[(f > lo) & (f < cut)].sum() / tot) if tot else float("nan")
    out["air_pct"] = float(100 * P[(f >= cut) & (f < hi)].sum() / tot) if tot else float("nan")
    out["split_hz"] = cut
    out["power_centroid_hz"] = (float((f[(f >= lo) & (f <= hi)] * P[(f >= lo) & (f <= hi)]).sum()
                                      / P[(f >= lo) & (f <= hi)].sum()) if tot else float("nan"))
    if voice in LINE_BAND:
        blo, bhi = LINE_BAND[voice]
        out["flatness_db"] = flatness_db(f, S, blo, bhi)
        out["noise_flatness_db"] = noise_control(x[:n], sr, blo, bhi)
        nlines, lines = count_lines(f, S, blo, bhi)
        out["n_lines"] = nlines
        out["lines_hz"] = [round(v, 1) for v in sorted(lines)[:40]]
    if voice == "CP":
        out["burst_ms"] = [round(v, 2) for v in burst_times(x, sr)]
    return out


# --------------------------------------------------------------- plots --------
def make_plots(voice: str, ref: tuple, ours: tuple, outdir: str, refname: str, knobs: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    sr_r, xr = ref
    sr_o, xo = ours
    xr, xo = trim_onset(xr, sr_r), trim_onset(xo, sr_o)
    lo, hi = BAND[voice]
    fmax = min(PLOT_FMAX[voice], sr_r / 2, sr_o / 2)
    tmax = max(0.06, min(1.2, min(len(xr) / sr_r, len(xo) / sr_o)))
    ewin = ENV_WIN_MS[voice]

    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle(f"{voice} — real TR-808 (Fischer, s/n 103852, {refname}, {knobs}) "
                 f"vs our render, hit 1 (accent 1.0)", fontsize=12)

    for col, (sr, x, title) in enumerate(
            ((sr_r, xr, f"real 808 · {refname}"), (sr_o, xo, "ours · drums_fx"))):
        a = ax[0][col]
        nper = 512 if fmax > 5000 else 4096
        a.specgram(x, NFFT=nper, Fs=sr, noverlap=int(nper * 0.9),
                   cmap="magma", norm=Normalize(-110, -10), scale="dB")
        a.set_ylim(0, fmax)
        a.set_xlim(0, tmax)
        a.set_title(title, fontsize=10)
        a.set_xlabel("s")
        a.set_ylabel("Hz")

    # envelopes, dB, common time axis
    a = ax[1][0]
    for sr, x, lbl, c in ((sr_r, xr, "real 808", "tab:blue"), (sr_o, xo, "ours", "tab:red")):
        e = envelope(x, sr, win_ms=ewin)
        e = e / e.max()
        t = np.arange(len(e)) / sr
        a.plot(t, 20 * np.log10(np.maximum(e, 1e-5)), color=c, lw=1.2, label=lbl)
    a.axhline(-8.686, color="k", ls=":", lw=0.8)
    a.text(tmax * 0.98, -8.0, "1/e", ha="right", fontsize=8)
    a.axhline(-20, color="k", ls=":", lw=0.8)
    a.text(tmax * 0.98, -19.2, "−20 dB (chart)", ha="right", fontsize=8)
    a.set_xlim(0, tmax)
    a.set_ylim(-70, 2)
    a.set_xlabel("s")
    a.set_ylabel("dB rel. peak")
    a.set_title(f"envelope ({ewin:.0f} ms moving RMS) — straight line = exponential", fontsize=10)
    a.grid(alpha=0.3)
    a.legend(fontsize=8)

    # spectra
    a = ax[1][1]
    for sr, x, lbl, c in ((sr_r, xr, "real 808", "tab:blue"), (sr_o, xo, "ours", "tab:red")):
        n = min(len(x), int(0.5 * sr))
        f, S = spectrum(x[:n], sr)
        S = 20 * np.log10(S / S.max() + 1e-12)
        b = (f >= max(20, lo * 0.3)) & (f <= fmax)
        a.plot(f[b], S[b], color=c, lw=0.7, alpha=0.85, label=lbl)
    sp = SPEC[voice]
    if sp["f0"]:
        a.axvline(sp["f0"], color="k", ls="--", lw=0.9)
        a.text(sp["f0"], 3, f"  spec {sp['f0']:.0f} Hz", fontsize=8)
    if voice in LINE_BAND:
        for k in OSC_NOMINAL:
            for m in range(1, int(fmax / k) + 1):
                if lo <= k * m <= fmax:
                    a.axvline(k * m, color="green", lw=0.3, alpha=0.18)
        a.plot([], [], color="green", lw=1, alpha=0.5, label="square-osc harmonics (nominal)")
    a.set_xscale("log")
    from matplotlib.ticker import LogLocator, ScalarFormatter, NullFormatter
    a.xaxis.set_major_locator(LogLocator(subs=(1.0, 2.0, 5.0)))
    a.xaxis.set_major_formatter(ScalarFormatter())
    a.xaxis.set_minor_formatter(NullFormatter())
    a.set_xlim(max(20, lo * 0.3), fmax)
    a.set_ylim(-80, 8)
    a.set_xlabel("Hz")
    a.set_ylabel("dB rel. peak")
    a.set_title(f"spectrum, first {min(500, int(tmax*1000))} ms", fontsize=10)
    a.grid(alpha=0.3, which="both")
    a.legend(fontsize=8)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    p = os.path.join(outdir, f"{voice}.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def plot_hat_lines(refs: dict, ours: dict, outdir: str):
    """The single most diagnostic picture: is the hat energy at discrete
    inharmonic partials (six squares) or broadband (noise)?"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    fig.suptitle("Hi-hat fine structure, 5–15 kHz — discrete square-oscillator "
                 "partials or noise?", fontsize=12)
    rows = []
    sr_r, xr = refs["OH"]
    sr_o, xo = ours["OH"]
    xr, xo = trim_onset(xr, sr_r), trim_onset(xo, sr_o)
    rng = np.random.default_rng(0)
    nz = rng.normal(size=int(0.3 * sr_o))
    e = envelope(xo, sr_o)
    e = np.pad(e, (0, max(0, len(nz) - len(e))))[:len(nz)]
    nz = nz * e / (envelope(nz, sr_o) + 1e-12)
    rows = [(sr_r, xr, "real TR-808 open hat (OH50)", "tab:blue"),
            (sr_o, xo, "ours (six squares → BP 7.1k → HP 7.8k)", "tab:red"),
            (sr_o, nz, "control: white noise with the same envelope "
                       "(what a noise-based emulation looks like)", "0.45")]
    for a, (sr, x, lbl, c) in zip(ax, rows):
        n = min(len(x), int(0.4 * sr))
        f, S = spectrum(x[:n], sr, nfft=1 << 19)
        b = (f >= 5000) & (f <= 15000)
        a.plot(f[b], 20 * np.log10(S[b] / S[b].max() + 1e-12), color=c, lw=0.6)
        fl = flatness_db(f, S, 5000, 15000)
        nl, _ = count_lines(f, S, 5000, 15000)
        a.set_title(f"{lbl}   —   flatness {fl:.1f} dB, {nl} lines ≥10 dB prominent",
                    fontsize=10)
        a.set_ylim(-70, 3)
        a.set_ylabel("dB")
        a.grid(alpha=0.3)
    ax[-1].set_xlabel("Hz")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    p = os.path.join(outdir, "hat-line-structure.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def plot_clap(refs: dict, ours: dict, outdir: str):
    """Three bursts ~10 ms apart inside 30 ms, then a tail."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(13, 7))
    fig.suptitle("Handclap burst structure — three bursts ≈10 ms apart inside "
                 "30 ms, plus a tail (reference §7)", fontsize=12)
    for col, (sr, x, lbl) in enumerate(
            ((refs["CP"][0], trim_onset(refs["CP"][1], refs["CP"][0]), "real TR-808 clap"),
             (ours["CP"][0], trim_onset(ours["CP"][1], ours["CP"][0]), "ours"))):
        n = int(0.06 * sr)
        e = envelope(x[:n], sr, win_ms=1.0)
        t = np.arange(len(e)) / sr * 1e3
        ax[0][col].plot(t, e / e.max(), lw=1.1,
                        color="tab:blue" if col == 0 else "tab:red")
        bt = burst_times(x, sr)
        for b in bt:
            ax[0][col].axvline(b, color="k", ls=":", lw=0.8)
        ax[0][col].set_title(f"{lbl} — first 60 ms, bursts at "
                             f"{', '.join(f'{v:.1f}' for v in bt)} ms", fontsize=10)
        ax[0][col].set_xlabel("ms")
        ax[0][col].set_ylabel("rel. peak")
        ax[0][col].grid(alpha=0.3)

        m = min(len(x), int(0.4 * sr))
        e2 = envelope(x[:m], sr)
        t2 = np.arange(len(e2)) / sr * 1e3
        ax[1][col].plot(t2, 20 * np.log10(e2 / e2.max() + 1e-6), lw=1.0,
                        color="tab:blue" if col == 0 else "tab:red")
        ax[1][col].set_title(f"{lbl} — tail, 400 ms", fontsize=10)
        ax[1][col].set_xlabel("ms")
        ax[1][col].set_ylabel("dB rel. peak")
        ax[1][col].set_ylim(-60, 3)
        ax[1][col].grid(alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    p = os.path.join(outdir, "clap-bursts.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def plot_knob_laws(refdir: str, outdir: str):
    """What the reference machine's knobs actually do, as laws our presets
    have to reproduce across their range -- not just at one point."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(14, 4.2))
    fig.suptitle("Reference machine knob laws (Fischer set, s/n 103852)", fontsize=12)
    rows = {}
    for key, files in REF_SWEEPS.items():
        xs, ys = [], []
        for rel, lbl in files:
            p = os.path.join(refdir, rel)
            if not os.path.exists(p):
                continue
            sr, x = read_wav(p)
            x = trim_onset(x, sr)
            e = envelope(x, sr)
            if key.endswith("decay"):
                v = decay_fit(e, sr)["tau_ms"]
            else:
                f, S = spectrum(x[:min(len(x), int(0.4 * sr))], sr)
                v = peak_hz(f, S, 30, 900)
            xs.append(float(lbl))
            ys.append(v)
        rows[key] = (xs, ys)

    ax[0].plot(*rows["BD-decay"], "o-", color="tab:blue")
    ax[0].set_title("BD DECAY knob → τ (ms)", fontsize=10)
    ax[0].set_xlabel("knob 0–10")
    ax[0].set_ylabel("τ ms")
    ax[1].plot(*rows["OH-decay"], "o-", color="tab:green")
    ax[1].set_title("OH DECAY knob → τ (ms)", fontsize=10)
    ax[1].set_xlabel("knob 0–10")
    ax[1].set_ylabel("τ ms")
    ax[2].plot(*rows["LT-tune"], "o-", label="LT")
    ax[2].plot(*rows["HT-tune"], "s-", label="HT")
    ax[2].set_title("tom TUNING knob → f0 (Hz)", fontsize=10)
    ax[2].set_xlabel("knob 0–10")
    ax[2].set_ylabel("Hz")
    ax[2].legend(fontsize=8)
    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    p = os.path.join(outdir, "knob-laws.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return rows, p


# ---------------------------------------------------------------- main --------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", required=True,
                    help="root of the Fischer CC0 set (contains bd8/, sd8/, ...)")
    ap.add_argument("--ours", default="/tmp/wt-drums/audio/drums",
                    help="directory holding 00-solo-N-XX.wav")
    ap.add_argument("--out", default="docs/img/drum-verification")
    ap.add_argument("--json", default=None, help="also dump raw metrics here")
    ap.add_argument("--no-plots", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    results, refs_wav, ours_wav = {}, {}, {}

    for i, v in enumerate(STOPS):
        rel, knobs = REF_MAIN[v]
        rp = os.path.join(a.refs, rel)
        op = os.path.join(a.ours, f"00-solo-{i}-{v}.wav")
        if not os.path.exists(rp):
            print(f"!! missing reference {rp}", file=sys.stderr)
            continue
        if not os.path.exists(op):
            print(f"!! missing render {op}", file=sys.stderr)
            continue
        sr_r, xr = read_wav(rp)
        sr_o, xo = read_wav(op)
        hits = segment_hits(xo, sr_o)
        refs_wav[v] = (sr_r, xr)
        ours_wav[v] = (sr_o, hits[0])
        results[v] = dict(
            ref_file=rel, ref_knobs=knobs, spec=SPEC[v],
            ref=measure(xr, sr_r, v),
            ours=[measure(h, sr_o, v) for h in hits],
        )

    # print a table
    hdr = (f"{'voice':5s} {'src':5s} {'peak Hz':>9s} {'centroid':>9s} {'attack ms':>10s} "
           f"{'tau ms':>8s} {'R^2':>6s} {'span dB':>8s} {'t-20dB ms':>10s}")
    print(hdr)
    print("-" * len(hdr))
    for v in STOPS:
        if v not in results:
            continue
        r = results[v]
        for src, m in (("real", r["ref"]), ("ours", r["ours"][0])):
            if m.get("silent"):
                print(f"{v:5s} {src:5s}  SILENT")
                continue
            print(f"{v:5s} {src:5s} {m['peak_hz']:9.1f} {m['centroid_hz']:9.0f} "
                  f"{m['attack_ms']:10.2f} {m['tau_ms']:8.1f} {m['r2']:6.3f} "
                  f"{m['span_db']:8.1f} {m['t20_ms']:10.1f}")
        sp = r["spec"]
        f0txt = "%.1f" % sp["f0"] if sp["f0"] else "—"
        print(f"{'':5s} {'spec':5s} {f0txt:>9s} {'':>9s} {'':>10s} "
              f"{sp['tau_ms']:8.1f} {'':>6s} {'':>8s} {sp['chart_ms']:10.1f}"
              f"   ({sp['note']})")
        print()

    print("energy split (power), and the power centroid the magnitude centroid hides:")
    print(f"{'voice':5s} {'src':5s} {'split at':>9s} {'body %':>8s} {'air %':>8s} {'pow cent':>9s}")
    for v in STOPS:
        if v not in results:
            continue
        for src, m in (("real", results[v]["ref"]), ("ours", results[v]["ours"][0])):
            if m.get("silent"):
                continue
            print(f"{v:5s} {src:5s} {m['split_hz']:8d}  {m['body_pct']:8.2f} "
                  f"{m['air_pct']:8.2f} {m['power_centroid_hz']:9.0f}")
    print()

    for v in STOPS:
        if v not in results or v not in LINE_BAND:
            continue
        for src, m in (("real", results[v]["ref"]), ("ours", results[v]["ours"][0])):
            print(f"{v} {src}: flatness {m['flatness_db']:.1f} dB "
                  f"(noise control {m['noise_flatness_db']:.1f} dB), "
                  f"{m['n_lines']} lines")
    if "CP" in results:
        print(f"CP real bursts at {results['CP']['ref']['burst_ms']} ms")
        print(f"CP ours bursts at {results['CP']['ours'][0]['burst_ms']} ms")

    plots = []
    if not a.no_plots:
        for v in STOPS:
            if v in refs_wav:
                rel, knobs = REF_MAIN[v]
                plots.append(make_plots(v, refs_wav[v], ours_wav[v], a.out,
                                        os.path.basename(rel), knobs))
        if "OH" in refs_wav:
            plots.append(plot_hat_lines(refs_wav, ours_wav, a.out))
        if "CP" in refs_wav:
            plots.append(plot_clap(refs_wav, ours_wav, a.out))
        laws, p = plot_knob_laws(a.refs, a.out)
        plots.append(p)
        results["_knob_laws"] = laws
        print("\nplots:")
        for p in plots:
            print("  " + p)

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(results, fh, indent=1, default=float)
        print(f"\nmetrics: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
