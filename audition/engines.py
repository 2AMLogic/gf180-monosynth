"""The three candidate architectures, as playable models.

Each `render_*` returns float audio at dsp.SR. Each engine's docstring states
what custom silicon would have to do, so a listening choice is also a choice
about area.
"""
from __future__ import annotations
import numpy as np
import dsp
from dsp import SR, note_hz, phase_inc, ramp, osc, osc_bl, ad_env, adsr, ladder, lfsr_noise, onepole_hp


# ============================================================ A. MONOSYNTH ===
def mono_note(note, dur, *, gate=None, waves=("saw", "saw", "square"),
              detune=(0.0, 0.07, -12.0), mix=(1.0, 0.8, 0.5),
              cutoff=(400, 4000), q=0.62, drive=1.6,
              amp=(0.005, 0.25, 0.75, 0.12), fenv=(0.004, 0.30, 0.25, 0.10),
              track=0.35, glide_from=None, _tanh="lut10", blep=False):
    """Minimoog-shaped voice: up to 3 detuned oscillators -> mixer (which can
    overdrive) -> nonlinear 4-pole ladder -> VCA, with a second envelope on
    cutoff and keyboard tracking.

    Silicon: 3 phase accumulators, a 4-stage filter datapath with a saturating
    element, 2 envelope generators, one multiplier per stage. The filter is the
    expensive and the interesting part; it is also the part that must be
    oversampled, which is a clock cost, not an area cost.

    `blep=True` uses the PolyBLEP oscillators (dsp.osc_bl). Off by default so
    the audition renders that chose this architecture do not change; the
    integer voice in model/voice_fx.py always band-limits, and is compared
    against this model with blep=True.
    """
    n = int(dur * SR)
    gate = dur * 0.8 if gate is None else gate
    f0 = note_hz(note)
    sig = np.zeros(n)
    for w, dt, mx in zip(waves, detune, mix):
        f = f0 * 2.0 ** (dt / 12.0)
        if glide_from is not None:                      # portamento
            f_start = note_hz(glide_from) * 2.0 ** (dt / 12.0)
            gl = min(n, int(0.09 * SR))
            inc = np.empty(n, dtype=np.int64)
            inc[:gl] = [phase_inc(f_start * (f / f_start) ** (i / gl)) for i in range(gl)]
            inc[gl:] = phase_inc(f)
            ph = np.cumsum(inc) & dsp.PHASE_MASK
        else:
            inc = phase_inc(f)
            ph = ramp(n, inc)
        sig += mx * (osc_bl(w, ph, inc) if blep else osc(w, ph))
    sig /= sum(mix)

    ae = adsr(n, *amp, gate)
    fe = adsr(n, *fenv, gate)
    lo, hi = cutoff
    cut = lo + (hi - lo) * fe + track * f0 * 4.0
    cut = np.clip(cut, 30.0, SR * 0.45)
    return ladder(sig * ae, cut, np.full(n, q), drive=drive, tanh_impl=_tanh) * 0.9


def render_mono(seq, dur_total):
    """seq: list of (start_s, note, dur_s, kwargs)"""
    out = np.zeros(int(dur_total * SR))
    prev = None
    for start, note, d, kw in seq:
        kw = dict(kw)
        if kw.pop("glide", False) and prev is not None:
            kw["glide_from"] = prev
        v = mono_note(note, d, **kw)
        i = int(start * SR)
        j = min(len(out), i + len(v))
        out[i:j] += v[:j - i]
        prev = note
    return out


# ========================================================== B. DRUM MACHINE ===
def kick(dur=0.6, f_start=180.0, f_end=46.0, sweep=0.045, click=0.5):
    """Pitch-swept sine + a short click. Silicon: one accumulator whose
    increment is itself enveloped, one AD envelope, a noise burst."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f_end + (f_start - f_end) * np.exp(-t / sweep)
    ph = (np.cumsum([phase_inc(x) for x in f]).astype(np.int64)) & dsp.PHASE_MASK
    body = dsp.sine_from_phase(ph) * ad_env(n, 0.001, 0.13, curve=4.0)
    clk = lfsr_noise(n, seed=0x1234) * ad_env(n, 0.0002, 0.004, curve=8.0) * click
    return np.tanh((body + clk) * 1.4) * 0.95


def snare(dur=0.4, tone=185.0, noise_mix=0.72):
    """Two detuned tone oscillators + filtered noise, separate envelopes."""
    n = int(dur * SR)
    t1 = osc("tri", ramp(n, phase_inc(tone))) * 0.6
    t2 = osc("tri", ramp(n, phase_inc(tone * 1.47))) * 0.4
    body = (t1 + t2) * ad_env(n, 0.0008, 0.055, curve=5.0)
    nz = lfsr_noise(n, seed=0xBEEF)
    nz = onepole_hp(nz, 1100.0) * ad_env(n, 0.0005, 0.10, curve=3.2)
    return np.tanh((body * (1 - noise_mix) + nz * noise_mix) * 1.6) * 0.85


def hat(dur=0.14, open_=False):
    """Noise through a high-pass, short envelope. The cheapest voice here."""
    n = int(dur * SR)
    nz = onepole_hp(lfsr_noise(n, seed=0x5EED), 5200.0)
    return nz * ad_env(n, 0.0003, 0.22 if open_ else 0.030, curve=4.0) * 0.55


def fm_perc(dur=0.5, carrier=320.0, ratio=2.41, index=7.0, decay=0.14):
    """One FM pair with an index envelope: tom, bell, cowbell, wood block --
    all the same hardware, different constants. This is the row of the memo's
    ladder with the best variety-per-area."""
    n = int(dur * SR)
    mod = dsp.sine_from_phase(ramp(n, phase_inc(carrier * ratio)))
    ie = ad_env(n, 0.0005, decay * 0.55, curve=4.0)
    ph = (ramp(n, phase_inc(carrier)) + (mod * ie * index * (1 << 20)).astype(np.int64)) & dsp.PHASE_MASK
    return dsp.sine_from_phase(ph) * ad_env(n, 0.0008, decay, curve=3.0) * 0.8


DRUM_VOICES = {"K": kick, "S": snare, "h": lambda: hat(open_=False),
               "H": lambda: hat(open_=True)}


def render_groove(pattern, bpm=112.0, swing=0.0, bars=2, fm_hits=None):
    """pattern: dict of voice-char -> 16-char step string ('x' = hit, '.' = rest).
    Uppercase 'X' = accent. swing delays every odd 16th by that fraction."""
    step = 60.0 / bpm / 4.0
    total = step * 16 * bars + 1.0
    out = np.zeros(int(total * SR))
    for rep in range(bars):
        for ch, row in pattern.items():
            for s, c in enumerate(row):
                if c == ".":
                    continue
                gain = 1.0 if c.islower() or ch in "KS" else 1.0
                gain = 1.25 if c == "X" else (0.62 if c == "o" else gain)
                t = (rep * 16 + s) * step + (swing * step if s % 2 else 0.0)
                v = DRUM_VOICES[ch]() * gain
                i = int(t * SR); j = min(len(out), i + len(v))
                out[i:j] += v[:j - i]
    for (t, kw) in (fm_hits or []):
        v = fm_perc(**kw)
        i = int(t * SR); j = min(len(out), i + len(v))
        out[i:j] += v[:j - i]
    return np.tanh(out * 0.8)


# =============================================================== C. FM VOICE ===
def fm_note(note, dur, *, algo="2op", ratios=(1.0, 2.0, 3.0, 1.0), index=(5.0, 2.0, 0.0),
            idx_env=(0.002, 0.5, 0.25, 0.2), amp=(0.004, 0.4, 0.6, 0.25), gate=None,
            feedback=0.0):
    """Two- or four-operator phase modulation with a fixed sine table.

    Silicon: one phase accumulator and one envelope per operator, one table
    (shared), one adder per modulation path. No filter, no oversampling -- PM
    with a bounded index is band-limited enough to behave at 48 kHz, which is
    why this row is cheap. Variety comes from constants, not gates.
    """
    n = int(dur * SR)
    gate = dur * 0.75 if gate is None else gate
    f = note_hz(note)
    ie = adsr(n, *idx_env, gate)
    ae = adsr(n, *amp, gate)
    SC = 1 << 20

    m3 = dsp.sine_from_phase(ramp(n, phase_inc(f * ratios[2]))) * ie * index[2] if algo == "4op" else 0.0
    ph2 = (ramp(n, phase_inc(f * ratios[1])) + (np.asarray(m3) * SC).astype(np.int64)) & dsp.PHASE_MASK if algo == "4op" \
        else ramp(n, phase_inc(f * ratios[1]))
    m2 = dsp.sine_from_phase(ph2)
    if feedback:
        m2 = np.tanh(m2 * (1.0 + feedback))
    m2 = m2 * ie * index[0]
    ph1 = (ramp(n, phase_inc(f * ratios[0])) + (m2 * SC).astype(np.int64)) & dsp.PHASE_MASK
    car = dsp.sine_from_phase(ph1)
    if algo == "4op" and index[1]:
        ph4 = (ramp(n, phase_inc(f * ratios[3])) + (m2 * SC * 0.5).astype(np.int64)) & dsp.PHASE_MASK
        car = 0.65 * car + 0.45 * dsp.sine_from_phase(ph4)
    return car * ae * 0.85


def render_fm(seq, dur_total):
    out = np.zeros(int(dur_total * SR))
    for start, note, d, kw in seq:
        v = fm_note(note, d, **kw)
        i = int(start * SR); j = min(len(out), i + len(v))
        out[i:j] += v[:j - i]
    return np.tanh(out * 0.9)
