"""Eight patches per engine. The memo's gate: eight you actually enjoy."""
from dsp import SR

# ---------------------------------------------------------------- MONOSYNTH --
# A Minimoog-ish riff vocabulary. Each entry: (name, notes, per-note kwargs)
_BASS = dict(waves=("saw", "saw", "square"), detune=(0.0, 0.06, -12.0), mix=(1.0, 0.9, 0.6),
             cutoff=(180, 2100), q=0.70, drive=1.9, track=0.25,
             amp=(0.003, 0.18, 0.72, 0.09), fenv=(0.002, 0.16, 0.18, 0.08))
_LEAD = dict(waves=("saw", "saw", "saw"), detune=(0.0, 0.10, -0.09), mix=(1.0, 0.8, 0.8),
             cutoff=(700, 6200), q=0.66, drive=1.5, track=0.5,
             amp=(0.02, 0.5, 0.80, 0.30), fenv=(0.05, 0.9, 0.35, 0.30))
_SWEEP = dict(waves=("saw", "square", "saw"), detune=(0.0, -12.0, 0.08), mix=(1.0, 0.7, 0.9),
              cutoff=(120, 7000), q=0.92, drive=1.4, track=0.1,
              amp=(0.01, 1.2, 0.95, 0.6), fenv=(0.9, 1.6, 0.10, 0.9))
_PLUCK = dict(waves=("square", "saw", "square"), detune=(0.0, 0.05, -12.0), mix=(1.0, 0.7, 0.5),
              cutoff=(300, 5200), q=0.80, drive=1.3, track=0.4,
              amp=(0.001, 0.14, 0.0, 0.10), fenv=(0.001, 0.10, 0.0, 0.08))
_GROWL = dict(waves=("saw", "saw", "pulse25"), detune=(0.0, 0.25, -12.0), mix=(1.0, 1.0, 0.8),
              cutoff=(150, 1500), q=0.97, drive=3.6, track=0.2,
              amp=(0.004, 0.3, 0.85, 0.12), fenv=(0.01, 0.35, 0.30, 0.15))
_WHISTLE = dict(waves=("sine",), detune=(0.0,), mix=(1.0,),
                cutoff=(200, 2600), q=1.06, drive=0.5, track=0.9,
                amp=(0.03, 0.4, 0.85, 0.4), fenv=(0.25, 1.0, 0.5, 0.5))

def _riff(notes, step, dur, kw, glide=False):
    return [(i * step, n, dur, dict(kw, glide=glide)) for i, n in enumerate(notes)]

MONO = [
    ("01-bass-classic",  _riff([28,28,40,28,31,28,35,28], 0.25, 0.24, _BASS),            2.6),
    ("02-bass-octave",   _riff([26,38,26,38,29,41,29,41,31,43,31,43,26,38,26,38], 0.15, 0.14, _BASS), 2.7),
    ("03-lead-line",     _riff([64,67,71,74,71,67,69,64], 0.30, 0.34, _LEAD),            3.0),
    ("04-lead-glide",    _riff([52,64,52,59,55,67], 0.45, 0.50, _LEAD, glide=True),      3.2),
    ("05-filter-sweep",  [(0.0, 33, 3.6, dict(_SWEEP, gate=3.0))],                       4.2),
    ("06-pluck-seq",     _riff([45,52,57,52,45,57,60,52], 0.18, 0.17, _PLUCK),           1.9),
    ("07-growl-bass",    _riff([26,26,33,26,24,24,31,24], 0.28, 0.27, _GROWL),           2.8),
    ("08-self-osc-whistle", _riff([69,76,72,79], 0.60, 0.62, _WHISTLE),                   3.2),
]

# ------------------------------------------------------------- DRUM MACHINE --
# 16-step rows. 'x' hit, 'X' accent, 'o' ghost, '.' rest.
GROOVES = [
    ("01-four-on-floor", dict(K="X...x...X...x...", S="....X.......X...", h="x.x.x.x.x.x.x.x."), 124, 0.0, None),
    ("02-boom-bap",      dict(K="X.....x...X.....", S="....X.......X..o", h="x.x.x.x.x.x.x.x."), 92, 0.16, None),
    ("03-breakbeat",     dict(K="X..x..x...X.....", S="....X..o..X.X...", h="x.xox.xox.xox.xo"), 168, 0.0, None),
    ("04-half-time",     dict(K="X.......x.......", S="........X.......", h="x...x...x...x..H"), 84, 0.10, None),
    ("05-electro",       dict(K="X...x..xX...x...", S="....X.......X...", h="xxxxxxxxxxxxxxxx"), 132, 0.0, None),
    ("06-shuffle",       dict(K="X..x..X...x..x..", S="....X.......X...", h="x.ox.ox.ox.ox.ox"), 104, 0.22, None),
    ("07-fm-toms",       dict(K="X.......X.......", S="....X.......X...", h="x.x.x.x.x.x.x.x."), 112, 0.0,
     [(0.55, dict(carrier=180, ratio=1.41, index=5.5, decay=0.22)),
      (0.82, dict(carrier=140, ratio=1.41, index=5.5, decay=0.26)),
      (1.62, dict(carrier=110, ratio=1.41, index=6.5, decay=0.30)),
      (2.70, dict(carrier=180, ratio=1.41, index=5.5, decay=0.22)),
      (2.97, dict(carrier=140, ratio=1.41, index=5.5, decay=0.26))]),
    ("08-fm-bell-groove", dict(K="X...x...X...x...", S="....X.......X...", h="..x...x...x...x."), 118, 0.08,
     [(0.0, dict(carrier=520, ratio=3.51, index=8.0, decay=0.9)),
      (1.02, dict(carrier=780, ratio=3.51, index=6.0, decay=0.7)),
      (2.03, dict(carrier=520, ratio=2.01, index=9.0, decay=0.9)),
      (3.05, dict(carrier=660, ratio=3.51, index=7.0, decay=1.1))]),
]

# ----------------------------------------------------------------- FM VOICE --
_EP    = dict(algo="2op", ratios=(1.0, 1.0, 0, 0), index=(4.2, 0, 0), feedback=0.0,
              idx_env=(0.001, 0.35, 0.10, 0.20), amp=(0.002, 0.9, 0.35, 0.35))
_BELL  = dict(algo="2op", ratios=(1.0, 3.51, 0, 0), index=(7.0, 0, 0),
              idx_env=(0.001, 0.7, 0.05, 0.6), amp=(0.001, 1.6, 0.25, 1.2))
_BASSF = dict(algo="2op", ratios=(1.0, 2.0, 0, 0), index=(6.5, 0, 0), feedback=0.35,
              idx_env=(0.001, 0.12, 0.15, 0.10), amp=(0.002, 0.16, 0.70, 0.08))
_BRASS = dict(algo="4op", ratios=(1.0, 1.0, 2.0, 2.0), index=(5.0, 0.8, 2.5),
              idx_env=(0.06, 0.5, 0.55, 0.25), amp=(0.04, 0.4, 0.80, 0.25))
_WOOD  = dict(algo="2op", ratios=(1.0, 4.97, 0, 0), index=(5.5, 0, 0),
              idx_env=(0.0005, 0.10, 0.0, 0.08), amp=(0.001, 0.22, 0.0, 0.10))
_GLASS = dict(algo="4op", ratios=(1.0, 7.0, 3.0, 1.0), index=(3.0, 0.9, 1.5),
              idx_env=(0.002, 1.2, 0.15, 1.0), amp=(0.003, 1.4, 0.30, 1.2))

def _fmriff(notes, step, dur, kw):
    return [(i * step, n, dur, dict(kw)) for i, n in enumerate(notes)]

FM = [
    ("01-e-piano",    _fmriff([60,64,67,72,67,64], 0.32, 0.9, _EP),     2.9),
    ("02-bells",      _fmriff([72,79,76,84], 0.55, 2.0, _BELL),         4.2),
    ("03-fm-bass",    _fmriff([28,28,35,28,31,28,40,28], 0.24, 0.23, _BASSF), 2.6),
    ("04-brass-stab", _fmriff([48,55,60,55], 0.40, 0.42, _BRASS),       2.3),
    ("05-wood-seq",   _fmriff([60,67,63,70,65,72,60,67], 0.17, 0.16, _WOOD), 1.8),
    ("06-glass-pad",  [(0.0, 60, 3.0, dict(_GLASS, gate=2.2)), (0.1, 67, 2.9, dict(_GLASS, gate=2.1))], 3.8),
    ("07-chord-ep",   [(0.0,48,2.2,dict(_EP,gate=1.6)),(0.0,55,2.2,dict(_EP,gate=1.6)),
                       (0.0,60,2.2,dict(_EP,gate=1.6)),(0.0,64,2.2,dict(_EP,gate=1.6))], 2.8),
    ("08-detune-lead",_fmriff([64,67,71,67,64,62], 0.28, 0.55, dict(_BRASS, feedback=0.5)), 2.6),
]
