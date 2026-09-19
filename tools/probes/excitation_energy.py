#!/usr/bin/env python3
"""Where, in time and in band, our excitation differs from the machine -- and
what the instrument that said so was actually measuring.

    .venv/bin/python tools/probes/excitation_energy.py --floors
    .venv/bin/python tools/probes/excitation_energy.py --map
    .venv/bin/python tools/probes/excitation_energy.py --attribute
    .venv/bin/python -m pytest tools/probes/excitation_energy.py -q

#152 reads `docs/discrimination-trajectory.txt` as "all sixteen voices carry
broadband energy in the first 30 ms that the machine does not have". This file
re-derives that map with the floor of every row stated, because two of the
three things it rests on turn out to be the instrument rather than the design.

THE THREE FLOORS, each measured here and not assumed
----------------------------------------------------

**F1 -- the conditioning creates the thing it is used to measure.**
`test_discrimination.condition()` high-passes at 20 Hz with `sosfiltfilt`.
A zero-phase filter has no causal excuse for an edge, and scipy pads it with
`padlen = 3*(2*len(sos)+1-1) = 6` samples for a filter whose pole is 0.99739
-- a settling time of about 1900 samples. Fed a unit impulse at index 0 it
answers with a near-full-scale NEGATIVE PEDESTAL: the first output samples are
-0.997, -0.995, -0.992 ..., and the first 30 ms integrate to -373 instead of 0.
That pedestal lands exactly on window 0 of every clip, and window 0 is where
#152's entire finding lives.  `condition()`'s own docstring warns about this
("a 20 Hz filter settles over ~50 ms ... right on top of the attack") and then
reaches for the acausal filter, which has the same transient at index 0.

**F2 -- the two sides do not enter the conditioning the same way.**
`_render_raw` returns `out[onset(out):]`: OUR clip is pre-trimmed to its onset
before `condition()` ever sees it. `read_wav` does not trim the machine's. The
pedestal of F1 is therefore placed differently on the two sides, and applying
the same pre-trim to the machine moves its own window-0 sub-120 Hz reading by
up to +32 dB.  "Applied identically to both sides" is true of the code and
false of the measurement.

**F3 -- ten of the fifty-two bands cannot hold a measurement at all.**
The map's windows are 30 ms, so the analysis bin is 33.3 Hz wide (at BOTH
44.1 and 48 kHz -- 0.24 s / 8 is a whole number of samples at each, which is
why the rate-independence test passes). Bands 0-15 are all NARROWER than one
bin, and bands 0,1,2,3,5,6,8,9,11,14 contain NO bin centre at all: they are
pinned to the -75 dB clamp on both sides by construction. The bands that do
appear in the report -- 67, 95, 135, 170, 190, 240 Hz -- are each ONE FFT bin
carrying up to +6.3 dB of band-width attribution bias, and "67 Hz" means bin 2
of a 30 ms Hann window, whose main lobe reaches DC.

WHAT SURVIVES
-------------
Run with `--map`. The excess is real on a named subset and is NOT broadband:
it is a near-DC onset pedestal, and `--attribute` names the path that emits it
by muting one register path at a time.

Provenance is printed by every mode: commit, dirty flag, corpus hash.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import sys

import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "model"))

import discrimination_features as dfx            # noqa: E402
import discrimination_trajectory as dtj          # noqa: E402
import drums_fx as dx                            # noqa: E402
import test_discrimination as td                 # noqa: E402

N_WIN = dtj.N_WIN
HPF_HZ = td.HPF_HZ
FLOOR_DB = dtj.FLOOR_DB
REFS_DEFAULT = "/tmp/tr808-ref"

# A cell is only allowed to carry a claim when the disagreement clears every
# applicable floor by this much. Chosen before the map was read.
MARGIN_DB = 6.0


# ===========================================================================
# Provenance
# ===========================================================================
def provenance(refdir: str) -> str:
    def git(*a):
        try:
            return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True,
                                  text=True, timeout=20).stdout.strip()
        except Exception:                                   # pragma: no cover
            return "?"
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    h = hashlib.sha256()
    n = 0
    for p in sorted(pathlib.Path(refdir).rglob("*.WAV")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
        n += 1
    return (f"commit {commit[:12]}{' DIRTY' if dirty else ''}  "
            f"corpus {refdir} {n} files sha256 {h.hexdigest()[:16]}  "
            f"argv {' '.join(sys.argv[1:]) or '(none)'}")


# ===========================================================================
# F3: what a band can hold at this resolution. Structural, no data needed.
# ===========================================================================
def bin_support(sr: int, n_total: int, n_win: int = N_WIN, edges=None):
    """(bins per band, band width Hz, bin width Hz) for ONE window of the map.

    A band with zero bins is not a low reading, it is NO reading: `trajectory`
    sums an empty mask to 0.0 and clamps to -75 dB on both sides. A band with
    one bin reports that bin's whole 33 Hz of power as if it were the band's,
    which is the +10log10(bin_bw/band_bw) attribution bias."""
    e = dfx.cqt_edges() if edges is None else np.asarray(edges, float)
    b = np.linspace(0, n_total, n_win + 1).astype(int)
    n_seg = b[1] - b[0]
    f = np.fft.rfftfreq(n_seg, 1.0 / sr)
    counts = np.array([int(((f >= e[k]) & (f < e[k + 1])).sum()) for k in range(len(e) - 1)])
    return counts, np.diff(e), float(sr) / n_seg


def attribution_bias_db(counts, band_bw, bin_bw):
    """+dB a band over-reports because its one bin is wider than it is."""
    with np.errstate(divide="ignore"):
        return np.where(counts > 0, 10.0 * np.log10(np.maximum(counts, 1) * bin_bw / band_bw),
                        np.nan)


# ===========================================================================
# F1/F2: conditioning, the study's and a causal one
# ===========================================================================
def _hpf_sos(sr):
    return butter(1, HPF_HZ / (sr / 2.0), btype="highpass", output="sos")


def condition_causal(x, sr, level_match: bool = True, pretrim: bool = True):
    """`td.condition` with the acausal filter replaced by a causal one, and the
    pre-trim made explicit instead of inherited from whoever produced the array.

    A causal 20 Hz high-pass with zero initial state IS what an AC-coupled
    output does to a signal that begins at t = 0, so its step response is
    physics and not an artefact. `sosfiltfilt`'s pedestal is neither."""
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    if pretrim:
        x = x[td.onset(x):]                    # both sides, or neither
    x = sosfilt(_hpf_sos(sr), x)
    i = td.onset(x)
    n = int(round(td.WINDOW_S * sr))
    seg = x[i:i + n]
    if len(seg) < n:
        seg = np.concatenate([seg, np.zeros(n - len(seg))])
    if level_match:
        pk = float(np.abs(seg).max())
        if pk > 0:
            seg = seg / pk
    return seg, len(seg) - min(n, max(0, len(x) - i))       # (segment, samples padded)


def filtfilt_pedestal(sr: int = 48000, ms: float = 30.0):
    """The F1 defect as one number: the first `ms` of `sosfiltfilt`'s answer to
    a unit impulse at index 0, summed. Zero would be a high-pass behaving."""
    n = max(4096, int(sr * 0.5))
    x = np.zeros(n)
    x[0] = 1.0
    a = sosfiltfilt(_hpf_sos(sr), x)
    b = sosfilt(_hpf_sos(sr), x)
    k = int(sr * ms / 1e3)
    return float(a[:k].sum()), float(b[:k].sum()), float(a[1])


# ===========================================================================
# F4: the 16-bit reference's own quantisation floor, per cell
# ===========================================================================
def quantisation_floor_db(x_file, sr, n_win: int = N_WIN, lsb: float = 1.0 / 32768.0):
    """Per (band, window) dB that uniform 16-bit quantisation noise alone would
    put in the map, in the map's own units (band share of the CONDITIONED
    clip's total energy).

    Uniform quantisation error has variance lsb^2/12, white over 0..sr/2. A
    band of width W therefore holds lsb^2/12 * (2W/sr) of it. The conditioning
    peak-normalises, so the LSB grows by 1/peak; that is the whole calculation
    and it is checked against a measured requantisation in the self-tests."""
    seg, _ = condition_causal(x_file, sr)
    scale = 1.0 / (float(np.abs(x_file).max()) + 1e-20)     # peak-normalisation gain
    q_var = (lsb * scale) ** 2 / 12.0
    e = dfx.cqt_edges()
    n_seg = len(seg) // n_win
    tot = float((seg ** 2).sum()) + 1e-20
    # `trajectory` scales P by len(seg)/sum(win^2) and sums bins; white noise of
    # variance v over a band of B bins contributes v * n_seg * B under that
    # scaling (the window normalisation is exactly what makes it so).
    return np.repeat(noise_cell_db(q_var, sr, len(seg), tot, n_win)[:, :1], n_win, axis=1)


def noise_cell_db(var: float, sr: int, n_total: int, clip_energy: float, n_win: int = N_WIN):
    """dB the map reports for WHITE noise of variance `var`, per band.

    `trajectory` scales |rfft(seg*win)|^2 by len(seg)/sum(win^2); white noise of
    variance v has E|X_k|^2 = v*sum(win^2) in every bin, so a band holding B
    bins reads v * n_seg * B before the clip-total division. That is the whole
    derivation and the self-tests check it against a measured requantisation."""
    counts, _, _ = bin_support(sr, n_total, n_win)
    n_seg = n_total // n_win
    with np.errstate(divide="ignore"):
        row = 10.0 * np.log10(var * n_seg * np.maximum(counts, 0) / (clip_energy + 1e-20) + 1e-20)
    return np.repeat(row[:, None], n_win, axis=1)


# ===========================================================================
# F5: the analysis's own leakage floor, measured by substitution
# ===========================================================================
def leakage_floor_db(seg, sr, n_win: int = N_WIN):
    """What the map reports in band k when band k has been REMOVED from the
    signal. Everything left in that cell is leakage from elsewhere -- the
    30 ms Hann skirt and the brick-wall's own time smear, which is why this is
    a floor and not a correction.

    52 notched re-renders per clip; this is the expensive part of the probe."""
    e = dfx.cqt_edges()
    X = np.fft.rfft(seg)
    f = np.fft.rfftfreq(len(seg), 1.0 / sr)
    out = np.full((len(e) - 1, n_win), FLOOR_DB)
    for k in range(len(e) - 1):
        Y = X.copy()
        Y[(f >= e[k]) & (f < e[k + 1])] = 0.0
        y = np.fft.irfft(Y, n=len(seg))
        M, _, _ = dtj.trajectory(y, sr, n_win)
        out[k] = M[k]
    return out


# ===========================================================================
# The map
# ===========================================================================
class Cell:
    __slots__ = ("k", "w", "cent", "ms", "a", "b", "diff", "floor", "why")

    def __init__(self, k, w, cent, ms, a, b, floor, why):
        self.k, self.w, self.cent, self.ms = k, w, float(cent), float(ms)
        self.a, self.b, self.diff, self.floor, self.why = float(a), float(b), float(b - a), float(floor), why


def voice_map(voice, refs, laws, refdir, arm="ours", n_win=N_WIN, leakage=True,
              study_conditioning=False):
    """The 52 x 8 map for one voice, ours minus machine, with a floor per cell.

    Uses the HELD-OUT settings when the voice has a knob, exactly as
    `discrimination_trajectory.compare` does, so the two are comparable."""
    use = [c for c in refs if c.voice == voice and c.is_test]
    held_out = bool(use)
    if not use:
        use = [c for c in refs if c.voice == voice]
    if not use:
        return None
    cond = (lambda x, sr: (td.condition(x, sr, True), 0)) if study_conditioning else condition_causal
    A, B, FA, FB, Q, pads = [], [], [], [], [], 0
    for c in use:
        xr, sr = td.read_wav(c.path)
        sa, pa = cond(xr, sr)
        xo, so = td.render(voice, c.knobs, laws, arm)
        sb, pb = cond(xo, so)
        pads += int(pa > 0) + int(pb > 0)
        A.append(dtj.trajectory(sa, sr, n_win)[0])
        M, cent, ms = dtj.trajectory(sb, so, n_win)
        B.append(M)
        Q.append(quantisation_floor_db(xr, sr, n_win))
        if leakage:
            FA.append(leakage_floor_db(sa, sr, n_win))
            FB.append(leakage_floor_db(sb, so, n_win))
    A, B = np.mean(A, axis=0), np.mean(B, axis=0)
    Q = np.mean(Q, axis=0)
    counts, bw, binbw = bin_support(sr, int(round(td.WINDOW_S * sr)), n_win)
    lk = np.maximum(np.mean(FA, axis=0), np.mean(FB, axis=0)) if leakage else \
        np.full_like(A, FLOOR_DB)
    # the floor a cell must clear: whichever of the three is highest
    floor = np.maximum(np.maximum(Q, lk), FLOOR_DB + 3.0)
    floor[counts == 0] = np.inf                              # F3: no reading exists
    return dict(voice=voice, n=len(use), held_out=held_out, real=A, ours=B, diff=B - A,
                centres=cent, ms=ms, floor=floor, counts=counts,
                bias=attribution_bias_db(counts, bw, binbw), pads=pads)


def rows(r, top=8, margin=MARGIN_DB):
    """Reportable cells, largest |difference| first. A cell is reportable when
    BOTH sides clear the floor (a level error) or when OURS clears it and the
    machine's reading is at or under it (an excess we can only bound below)."""
    out = []
    D, A, B, F = r["diff"], r["real"], r["ours"], r["floor"]
    for k in range(D.shape[0]):
        for w in range(D.shape[1]):
            if not np.isfinite(F[k, w]):
                continue
            ours_live = B[k, w] > F[k, w] + margin
            mach_live = A[k, w] > F[k, w] + margin
            if not ours_live and not mach_live:
                continue
            if abs(D[k, w]) < margin:
                continue
            kind = ("level" if (ours_live and mach_live) else
                    "EXCESS" if ours_live else "DEFICIT")
            bound = "" if (ours_live and mach_live) else " (bound: other side at floor)"
            out.append((abs(D[k, w]), kind, k, w, bound))
    out.sort(reverse=True, key=lambda t: t[0])
    seen, keep = set(), []
    for _, kind, k, w, bound in out:
        if (k // 2, w // 2) in seen:
            continue
        seen.add((k // 2, w // 2))
        keep.append((kind, k, w, bound))
        if len(keep) >= top:
            break
    return keep


# ===========================================================================
# Attribution: mute one register path at a time
# ===========================================================================
def render_kit(voice, kit, seconds=None):
    n = int((seconds or td.RENDER_S) * dx.SR)
    d = dx.DrumsFx()
    dmix, body = d.play(dx.hit_writes([(10, dx.SOUND_STOP[voice], 1.0)], kit), n)
    g = dx.accent_reg(td.RENDER_GAIN)
    out = dx.output_fx(np.zeros(n), 0, dmix, g, body, g).astype(np.float64) / 32768.0
    return out[td.onset(out):], dx.SR


def _mutate_paths(kit, fn):
    """kit with every PATH word passed through fn(p, word) -> word or None."""
    out = []
    for a, v in kit:
        if dx.A_PATH <= a < dx.A_PATH + dx.N_PATH:
            nv = fn(a - dx.A_PATH, v)
            out.append((a, dx.path_word(dx.SRC_OFF, dx.ENV_NONE) if nv is None else nv))
        else:
            out.append((a, v))
    return out


def onset_lf_db(x, sr, hz=120.0, ms=30.0):
    """Sub-`hz` energy of the first `ms`, in dB relative to the conditioned
    clip's total. The scalar the map's low bands are actually reporting."""
    seg, _ = condition_causal(x, sr)
    n = int(sr * ms / 1e3)
    w = seg[:n]
    win = np.hanning(len(w))
    P = np.abs(np.fft.rfft(w * win)) ** 2
    P = P / (float((win ** 2).sum()) + 1e-20) * len(w)
    f = np.fft.rfftfreq(len(w), 1.0 / sr)
    return 10.0 * np.log10(P[f < hz].sum() / (float((seg ** 2).sum()) + 1e-20) + 1e-20)


SRC_NAMES = {dx.SRC_OFF: "OFF", dx.SRC_NOISE: "NOISE", dx.SRC_SQSUM: "SQSUM",
             dx.SRC_PULSE: "PULSE", dx.SRC_SQPAIR: "SQPAIR"}
NL_NAMES = ("LIN", "SWING", "TANH", "?")


def describe_path(word):
    src, e1, e2 = word & 31, (word >> 5) & 31, (word >> 10) & 31
    nl, att, dest = (word >> 15) & 3, (word >> 17) & 7, (word >> 20) & 31
    s = SRC_NAMES.get(src, f"SQ{src - dx.SRC_SQ}" if dx.SRC_SQ <= src < dx.SRC_SQ + dx.N_OSC
                      else f"TAP{src - dx.SRC_TAP}")
    return f"{s:7s} e{e1:<2d} {NL_NAMES[nl]:5s} -> {'MIX' if dest == 31 else f'm{dest}'}"


def attribute(voice, laws):
    """Every candidate, each rendered with the others held.

    The candidates #152 names are (1) the excitation pulse shape, (2) the
    envelope attack, (3) the noise source's onset and (4) a coefficient-write
    transient. (1)-(3) are all PATH words, so a per-path mute sweep tests all
    three exhaustively rather than one guess at a time; (4) is `coef_seq`."""
    base_kit = dx.kit_with_sounds(voice)
    x, sr = render_kit(voice, base_kit)
    base = onset_lf_db(x, sr)
    res = [("baseline", base, 0.0, "")]

    # (4) the coefficient sequences (BD attack window, tom pitch drop)
    n = int(td.RENDER_S * dx.SR)
    d = dx.DrumsFx()
    dmix, body = d.play(dx.hit_writes([(10, dx.SOUND_STOP[voice], 1.0)], base_kit,
                                      coef_seq=False), n)
    g = dx.accent_reg(td.RENDER_GAIN)
    out = dx.output_fx(np.zeros(n), 0, dmix, g, body, g).astype(np.float64) / 32768.0
    out = out[td.onset(out):]
    v = onset_lf_db(out, dx.SR)
    res.append(("coef_seq=False", v, v - base, "the BD attack window / tom pitch drop"))

    # (1)(2)(3) one path at a time
    kitd = dict(base_kit)
    for p in range(dx.N_PATH):
        word = kitd.get(dx.A_PATH + p, 0)
        if word == 0:
            continue
        muted = _mutate_paths(base_kit, lambda i, w, p=p: None if i == p else w)
        y, sy = render_kit(voice, muted)
        if float(np.abs(y).max()) <= 0:
            res.append((f"mute p{p}", float("nan"), float("nan"), describe_path(word)))
            continue
        v = onset_lf_db(y, sy)
        res.append((f"mute p{p}", v, v - base, describe_path(word)))

    # the nonlinearity, held: SWING -> LIN everywhere
    lin = _mutate_paths(base_kit, lambda i, w: (w & ~(3 << 15)) | (dx.NL_LIN << 15))
    y, sy = render_kit(voice, lin)
    if float(np.abs(y).max()) > 0:
        v = onset_lf_db(y, sy)
        res.append(("all nl -> LIN", v, v - base, "the swing/tanh VCAs"))
    return base, res


# ===========================================================================
# Reports
# ===========================================================================
def report_floors(refdir):
    print(provenance(refdir))
    print("\n=== F1  the conditioning's own edge transient ===")
    for sr in (44100, 48000):
        ff, ca, first = filtfilt_pedestal(sr)
        print(f"  {sr} Hz: sosfiltfilt(impulse at 0) sums to {ff:+9.2f} over the first 30 ms "
              f"(causal sosfilt: {ca:+.4f}); its second sample is {first:+.5f}")
    print("  A high-pass that answers a unit impulse with a full-scale negative pedestal is\n"
          "  not measuring the signal's low frequencies in window 0. REFUSE window 0 of any\n"
          "  row produced with `td.condition`.")

    print("\n=== F3  bands that cannot hold a reading at 30 ms ===")
    for sr in (44100, 48000):
        counts, bw, binbw = bin_support(sr, int(round(td.WINDOW_S * sr)))
        e = dfx.cqt_edges()
        cent = np.sqrt(e[:-1] * e[1:])
        dead = [k for k in range(len(counts)) if counts[k] == 0]
        print(f"  {sr} Hz: analysis bin {binbw:.2f} Hz; {len(dead)} of {len(counts)} bands hold "
              f"NO bin -> pinned to {FLOOR_DB:.0f} dB on both sides:")
        print("    " + ", ".join(f"{cent[k]:.0f}" for k in dead) + " Hz")
        one = [k for k in range(len(counts)) if counts[k] == 1]
        b = attribution_bias_db(counts, bw, binbw)
        print(f"    {len(one)} bands hold exactly ONE bin; their band-width attribution bias is "
              f"+{np.nanmin(b[one]):.1f} to +{np.nanmax(b[one]):.1f} dB "
              f"({', '.join(f'{cent[k]:.0f}' for k in one)} Hz)")

    print("\n=== F2  the two sides do not enter the conditioning the same way ===")
    print("  `_render_raw` returns out[onset(out):]; `read_wav` does not trim. Sub-120 Hz of")
    print("  window 0 under the STUDY's conditioning, machine side, with and without the")
    print("  pre-trim our side always gets:")
    refs = td.ref_clips(refdir, include_unmodelled=True)
    print(f"    {'voice':6s} {'as read':>9s} {'pre-trimmed':>12s} {'move':>7s}")
    worst = 0.0
    for v in sorted({c.voice for c in refs}):
        c = [c for c in refs if c.voice == v][0]
        x, sr = td.read_wav(c.path)

        def lf(sig):
            s = td.condition(sig, sr, True)
            n = len(s) // N_WIN
            w = s[:n]
            win = np.hanning(len(w))
            P = np.abs(np.fft.rfft(w * win)) ** 2 / (float((np.hanning(len(w)) ** 2).sum())) * len(w)
            f = np.fft.rfftfreq(len(w), 1.0 / sr)
            return 10 * np.log10(P[f < 120].sum() / float((s ** 2).sum()) + 1e-20)
        a, b = lf(x), lf(x[td.onset(x):])
        worst = max(worst, abs(b - a))
        print(f"    {v:6s} {a:9.1f} {b:12.1f} {b - a:+7.1f}")
    print(f"  worst move {worst:+.1f} dB, from a choice of array bounds. REFUSE any window-0 row")
    print("  whose value moves by more than the difference it is being used to claim.")

    print("\n=== F4  the reference's 16-bit quantisation floor ===")
    for v in sorted({c.voice for c in refs})[:4]:
        c = [c for c in refs if c.voice == v][0]
        x, sr = td.read_wav(c.path)
        Q = quantisation_floor_db(x, sr)
        live = np.isfinite(Q[:, 0]) & (Q[:, 0] > -200)
        print(f"    {v:4s} peak {20 * np.log10(np.abs(x).max()):6.2f} dBFS -> quantisation floor "
              f"{np.nanmin(Q[live, 0]):.1f} to {np.nanmax(Q[live, 0]):.1f} dB across the live bands")
    return 0


def report_map(refdir, sounds="16", top=6, leakage=True, study=False):
    print(provenance(refdir))
    all16 = sounds == "16"
    refs = td.ref_clips(refdir, include_unmodelled=all16)
    laws = td.fit_laws(refdir, all_sounds=all16)
    which = "the STUDY's acausal conditioning (F1 ACTIVE)" if study else \
        "a causal 20 Hz high-pass, both sides pre-trimmed (F1/F2 removed)"
    print(f"\nband x time map, ours minus machine, {N_WIN} x 30 ms, {which}")
    print(f"floors: F3 structural, F4 16-bit quantisation, F5 measured leakage; "
          f"margin {MARGIN_DB:.0f} dB\n")
    summary = {}
    for v in sorted({c.voice for c in refs}):
        r = voice_map(v, refs, laws, refdir, leakage=leakage, study_conditioning=study)
        if r is None:
            continue
        tag = f"{r['n']} held-out" if r["held_out"] else f"{r['n']} setting(s), NOT held out"
        dead = int((~np.isfinite(r["floor"][:, 0])).sum())
        print(f"{v}  ({tag}; {dead} of {len(r['counts'])} bands refused structurally"
              f"{'; ZERO-PADDED' if r['pads'] else ''})")
        got = rows(r, top)
        if not got:
            print("    no cell clears its floor by the margin")
        for kind, k, w, bound in got:
            step = r["ms"][1] - r["ms"][0]
            print(f"    {kind:7s} {r['centres'][k]:6.0f} Hz  {r['ms'][w] - step / 2:3.0f}-"
                  f"{r['ms'][w] + step / 2:3.0f} ms  {r['diff'][k, w]:+6.1f} dB "
                  f"(machine {r['real'][k, w]:+6.1f}, ours {r['ours'][k, w]:+6.1f}, "
                  f"floor {r['floor'][k, w]:+6.1f}, bias +{r['bias'][k]:.1f}){bound}")
        summary[v] = (r, got)
        print()
    _verdict(summary)
    return 0


LOW_HZ, HIGH_LO, HIGH_HI = 200.0, 700.0, 5000.0


def _verdict(summary):
    print("=== one mechanism or two ===")
    print(f"    {'voice':6s} {'excess<200Hz w0':>16s} {'net 0.7-5k':>11s} {'excess cells':>13s} "
          f"{'deficit cells':>14s}")
    for v, (r, _) in sorted(summary.items()):
        cent, F, D, A, B = r["centres"], r["floor"], r["diff"], r["real"], r["ours"]
        lowmask = (cent < LOW_HZ) & np.isfinite(F[:, 0])
        lo = float(np.nanmax(D[lowmask, 0])) if lowmask.any() else float("nan")
        hi = (cent >= HIGH_LO) & (cent <= HIGH_HI)
        live = np.isfinite(F) & ((A > F + MARGIN_DB) | (B > F + MARGIN_DB))
        hm = live & hi[:, None]
        net = float(D[hm].mean()) if hm.any() else float("nan")
        exc = int(((D > MARGIN_DB) & live).sum())
        dfc = int(((D < -MARGIN_DB) & live).sum())
        print(f"    {v:6s} {lo:16.1f} {net:11.1f} {exc:13d} {dfc:14d}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", default=REFS_DEFAULT)
    ap.add_argument("--sounds", choices=("8", "16"), default="16")
    ap.add_argument("--floors", action="store_true", help="the instrument's limits, measured")
    ap.add_argument("--map", action="store_true", help="the band x time map with floors")
    ap.add_argument("--attribute", action="store_true", help="per-path mute sweep")
    ap.add_argument("--study-conditioning", action="store_true",
                    help="re-run the map with the acausal filter, to show what it added")
    ap.add_argument("--no-leakage", action="store_true", help="skip the F5 notch sweep (fast)")
    ap.add_argument("--voices", default="")
    ap.add_argument("--top", type=int, default=6)
    a = ap.parse_args(argv)
    if not (a.floors or a.map or a.attribute):
        a.floors = a.map = True
    rc = 0
    if a.floors:
        rc |= report_floors(a.refs)
    if a.map:
        rc |= report_map(a.refs, a.sounds, a.top, not a.no_leakage, a.study_conditioning)
    if a.attribute:
        print(provenance(a.refs))
        laws = td.fit_laws(a.refs, all_sounds=True)
        vs = a.voices.split(",") if a.voices else list(dx.SOUND_NAMES)
        print("\nper-path mute sweep: sub-120 Hz energy of the first 30 ms, dB re clip total\n"
              "a path whose removal DROPS the number is the one emitting the onset excess\n")
        for v in vs:
            base, res = attribute(v, laws)
            print(f"{v}  baseline {base:+.1f} dB")
            for name, val, d, what in res[1:]:
                mark = "  <== " if (np.isfinite(d) and d <= -6.0) else "      "
                print(f"    {name:16s} {val:+7.1f}  {d:+7.1f}{mark}{what}")
            print()
    return rc


# ===========================================================================
# Self-tests. Every number this file prints has one.
# ===========================================================================
def test_the_filtfilt_pedestal_is_the_size_claimed():
    """F1, pinned. If scipy ever fixes its padding this test goes green-to-red
    and the docstring above becomes wrong, which is the point of pinning it."""
    ff, ca, second = filtfilt_pedestal(48000)
    assert ff < -300.0, ff                       # ~-373 in the version measured
    assert abs(ca) < 1.0, ca                     # a causal high-pass integrates to ~0
    assert second < -0.99, second                # a full-scale negative second sample


def test_the_pedestal_creates_low_frequency_where_there_is_none():
    """The injected-bug control for F1, run the other way round: a signal built
    with NO energy under 200 Hz must still come out of the study's conditioning
    with a large window-0 low-frequency reading, and must not out of the
    causal one."""
    sr = 48000
    n = int(sr * 0.4)
    t = np.arange(n) / sr
    rng = np.random.default_rng(0)
    x = rng.standard_normal(n) * np.exp(-t / 0.02)
    X = np.fft.rfft(x)
    X[np.fft.rfftfreq(n, 1.0 / sr) < 400.0] = 0.0            # nothing at all below 400 Hz
    x = np.fft.irfft(X, n=n)

    def w0_lf(seg):
        w = seg[:len(seg) // N_WIN]
        win = np.hanning(len(w))
        P = np.abs(np.fft.rfft(w * win)) ** 2 / float((win ** 2).sum()) * len(w)
        f = np.fft.rfftfreq(len(w), 1.0 / sr)
        return 10 * np.log10(P[f < 120].sum() / float((seg ** 2).sum()) + 1e-20)
    study = w0_lf(td.condition(x, sr, True))
    causal = w0_lf(condition_causal(x, sr)[0])
    assert study > causal + 15.0, (study, causal)
    assert causal < -20.0, causal


def test_bands_with_no_bin_are_refused_not_reported():
    """F3. The named bands must hold no bin at either rate, and `trajectory`
    must pin them to the clamp on a broadband signal that genuinely has energy
    everywhere -- so a -75 there is the instrument, not the sound."""
    for sr in (44100, 48000):
        n = int(round(td.WINDOW_S * sr))
        counts, _, binbw = bin_support(sr, n)
        assert abs(binbw - 33.333) < 0.01, binbw
        dead = set(np.where(counts == 0)[0])
        assert {0, 1, 2, 3, 5, 6, 8, 9, 11, 14} <= dead, sorted(dead)
        rng = np.random.default_rng(1)
        M, _, _ = dtj.trajectory(rng.standard_normal(n), sr)
        for k in sorted(dead):
            assert M[k].max() <= FLOOR_DB + 1e-9, (sr, k, M[k].max())


def test_a_bands_reading_is_its_BIN_count_not_its_width():
    """F3's consequence, on ground truth: white noise, whose true spectral
    density is flat, so a band holding B bins must read 10*log10(B) + const --
    NOT 10*log10(its width). `attribution_bias_db` reports the gap.

    Averaged over 200 realisations because ONE realisation cannot test this: a
    one-bin cell is chi-square with 2 dof and scatters by about 5.6 dB, which
    is larger than the effect. That scatter is itself a floor on any single
    reading of bands 4, 7, 10, 12, 13, 15 and 16 in the shipped map."""
    sr = 48000
    n = int(round(td.WINDOW_S * sr))
    counts, bw, binbw = bin_support(sr, n)
    bias = attribution_bias_db(counts, bw, binbw)
    rng = np.random.default_rng(2)
    acc = []
    for _ in range(200):
        M, cent, _ = dtj.trajectory(rng.standard_normal(n), sr)
        acc.append(10.0 ** (M[:, 0] / 10.0))
    m = 10.0 * np.log10(np.mean(acc, axis=0))
    live = counts > 0
    off = m[live] - 10.0 * np.log10(counts[live].astype(float))
    assert float(off.std()) < 0.5, (float(off.std()), off.min(), off.max())
    width_pred = 10.0 * np.log10(bw[live] / binbw) + off.mean()
    assert np.allclose(m[live] - width_pred, bias[live], atol=1.0), \
        float(np.abs(m[live] - width_pred - bias[live]).max())
    # the three bands the shipped report quotes most -- 67, 95 and 135 Hz --
    # are each one bin, each over-reporting by more than 3 dB
    for k, hz in ((4, 67), (7, 95), (10, 135)):
        assert counts[k] == 1, (k, hz, counts[k])
        assert bias[k] > 3.0, (hz, float(bias[k]))
    assert abs(bias[4] - 6.3) < 0.2, float(bias[4])


def test_a_single_one_bin_cell_scatters_by_more_than_the_effect():
    """The floor a ONE-BIN band carries even when everything else is perfect.
    Reported so no row of the map resting on bands 4/7/10/12/13/15/16 is read
    as if it had the precision of a wide band."""
    sr = 48000
    n = int(round(td.WINDOW_S * sr))
    counts, _, _ = bin_support(sr, n)
    rng = np.random.default_rng(7)
    k = int(np.where(counts == 1)[0][0])
    vals = [dtj.trajectory(rng.standard_normal(n), sr)[0][k, 0] for _ in range(200)]
    assert 4.0 < float(np.std(vals)) < 8.0, float(np.std(vals))


def test_the_noise_floor_closed_form_is_what_the_map_reports():
    """The formula F4 rests on, against a MEASURED requantisation and nothing
    else. Quantise a known signal to 16 bits, isolate the error it made, and
    check that `noise_cell_db` predicts the map the error alone produces."""
    sr = 44100
    n = int(round(td.WINDOW_S * sr))
    t = np.arange(n) / sr
    x = 0.5 * np.sin(2 * np.pi * 220.0 * t)
    err = np.round(x * 32768.0) / 32768.0 - x               # the real quantisation error
    var = float((err ** 2).mean())
    assert abs(10 * np.log10(var * 12 * 32768.0 ** 2)) < 1.0, var   # it IS lsb^2/12
    M, _, _ = dtj.trajectory(err, sr)
    counts, _, _ = bin_support(sr, n)
    pred = noise_cell_db(var, sr, n, float((err ** 2).sum()))
    live = counts > 5
    d = M[live, 0] - pred[live, 0]
    assert abs(float(np.median(d))) < 1.5, (float(np.median(d)), float(d.std()))


def test_the_quantisation_floor_tracks_the_clips_own_headroom():
    """A quiet 16-bit clip has a HIGHER floor once the conditioning normalises
    it, and the floor must move by exactly the headroom."""
    sr = 44100
    n = int(round(td.WINDOW_S * sr)) * 2
    t = np.arange(n) / sr
    loud = np.round(0.9 * np.sin(2 * np.pi * 220.0 * t) * np.exp(-t / 0.08) * 32768) / 32768
    quiet = np.round(0.09 * np.sin(2 * np.pi * 220.0 * t) * np.exp(-t / 0.08) * 32768) / 32768
    a, b = quantisation_floor_db(loud, sr), quantisation_floor_db(quiet, sr)
    counts, _, _ = bin_support(sr, int(round(td.WINDOW_S * sr)))
    live = counts > 5
    gap = float(np.median(b[live, 0] - a[live, 0]))
    assert abs(gap - 20.0) < 1.5, gap


def test_the_leakage_floor_sees_a_tone_that_is_not_there():
    """F5, constructed: one loud tone and nothing else. Every OTHER band's
    reading must be at or under the leakage floor this function measures --
    if it were not, the floor would not be a floor."""
    sr = 48000
    n = int(round(td.WINDOW_S * sr))
    t = np.arange(n) / sr
    x = np.sin(2 * np.pi * 1000.0 * t) * np.exp(-t / 0.05)
    M, cent, _ = dtj.trajectory(x, sr)
    L = leakage_floor_db(x, sr)
    k0 = int(np.argmin(np.abs(cent - 1000.0)))
    bad = [(int(k), float(M[k, 0]), float(L[k, 0])) for k in range(len(cent))
           if abs(k - k0) > 2 and M[k, 0] > L[k, 0] + 6.0 and M[k, 0] > FLOOR_DB + 3]
    assert not bad, bad[:5]


def test_a_known_dc_pedestal_is_reported_as_low_band_excess():
    """The injected-bug control the map itself must catch: add a decaying
    UNIPOLAR pedestal -- the shape `SRC_PULSE * env` puts on the mix bus -- to
    a clean high-band sound, and the map must find it in the low bands of
    window 0 and nowhere else."""
    sr = 48000
    n = int(sr * 0.4)
    t = np.arange(n) / sr
    rng = np.random.default_rng(3)
    clean = rng.standard_normal(n) * np.exp(-t / 0.03)
    X = np.fft.rfft(clean)
    X[np.fft.rfftfreq(n, 1.0 / sr) < 2000.0] = 0.0
    clean = np.fft.irfft(X, n=n)
    dirty = clean + 0.5 * np.abs(clean).max() * np.exp(-t / 0.01)      # the pedestal
    A, cent, ms = dtj.trajectory(condition_causal(clean, sr)[0], sr)
    B, _, _ = dtj.trajectory(condition_causal(dirty, sr)[0], sr)
    counts, _, _ = bin_support(sr, int(round(td.WINDOW_S * sr)))
    D = B - A
    low = (cent < 200.0) & (counts > 0)
    assert D[low, 0].max() > 20.0, D[low, 0].max()
    hi = (cent > 3000.0) & (counts > 0)
    assert abs(D[hi, 0]).max() < 6.0, abs(D[hi, 0]).max()
    assert D[low, N_WIN - 1].max() < D[low, 0].max() - 15.0


def test_muting_a_path_removes_exactly_that_path():
    """The attribution sweep's own control: muting the BD's click path must
    silence the mix bus and leave the body bus bit-exact."""
    kit = dx.kit_with_sounds("BD")
    n = int(0.2 * dx.SR)

    def play(k):
        d = dx.DrumsFx()
        return d.play(dx.hit_writes([(10, dx.SOUND_STOP["BD"], 1.0)], k), n)
    dm0, bd0 = play(kit)
    dm1, bd1 = play(_mutate_paths(kit, lambda i, w: None if i == 1 else w))
    assert np.abs(dm0).max() > 0 and np.abs(dm1).max() == 0, (np.abs(dm0).max(), np.abs(dm1).max())
    assert np.array_equal(bd0, bd1)


def test_a_gain_does_not_move_the_map():
    sr = 48000
    n = int(sr * 0.4)
    t = np.arange(n) / sr
    x = np.sin(2 * np.pi * 400.0 * t) * np.exp(-t / 0.05)
    A, _, _ = dtj.trajectory(condition_causal(x, sr)[0], sr)
    B, _, _ = dtj.trajectory(condition_causal(0.017 * x, sr)[0], sr)
    assert np.allclose(A, B, atol=1e-9)


if __name__ == "__main__":
    sys.exit(main())
