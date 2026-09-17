# gf180-monosynth

A Minimoog-shaped monophonic synthesizer voice — three detuned oscillators into
a nonlinear four-pole ladder filter — with a small drum section, targeting
GlobalFoundries **gf180mcu**. A 2AM Logic canary block.

## Status: a model and an area sketch. No chip, no RTL, no PDK.

Being precise about this, because "synth" covers five different things:

| | | |
|---|---|---|
| 1 | Float model, playable in real time | **done** — `audition/` |
| 2 | Fixed-point model of the filter | **done** — `model/`, oscillators and envelopes still float |
| 3 | RTL, bit-exact against (2) | **not started** — `rtl-sketch/` is an area sketch only, never simulated |
| 4 | FPGA bitstream on real hardware | not started |
| 5 | gf180mcu ASIC | not started |

Nothing here has been synthesized to a PDK, so there is **no area in mm², no
timing and no power number**. The cell counts below are PDK-neutral yosys
output from a datapath sketch that has never been simulated for correctness.

## Why this block exists

The sibling block [`gf180-polysynth`](https://github.com/2AMLogic/gf180-polysynth)
is a four-voice synthesizer with four waveforms and an ADSR — and **no filter
at all**, which is most of what makes a subtractive synthesizer sound like an
instrument. This block is the filter, and the architecture that puts one to
use: one fat voice instead of four thin ones.

It is also a deliberately awkward canary. The fleet is mostly analog blocks
plus a modexp and a USB PHY; a *recursive nonlinear feedback datapath* is
unlike any of them, and it lands on three places where a false pass can hide at
once — a critical path that closes through a feedback loop, a ROM, and a
time-shared multiplier running multicycle.

## The filter

`audition/dsp.py` and `model/fixed.py` implement Antti Huovilainen,
*"Non-Linear Digital Implementation of the Moog Ladder Filter"*, DAFx-04
([PDF](https://www.dafx.de/paper-archive/2004/P_061.PDF)) — **not** the
linearised model. The difference is structural: the nonlinearity is in every
stage, because every stage is a transistor differential pair. Equation (22):

```
y(n) = y(n−1) + 2·Vt·g·( tanh(x(n)/2·Vt) − tanh(y(n−1)/2·Vt) )
```

Three things from the paper are load-bearing:

- **Five `tanh` per sample, not eight** (eq 17). Each stage's input is the
  `tanh` of the previous stage's output, which that stage already needs next
  sample. Cache it.
- **A half-sample delay in the feedback**, "realized by averaging two samples",
  or the resonant peak drifts off the cutoff.
- **Oversampling is required**, because of the nonlinearities. 2× here.

`model/fixed.py` holds the state in units of `2·Vt` rather than volts, which
turns the stage into `Y += g·(tanh(X) − tanh(Y))` — the `tanh` argument becomes
the state itself, the table is indexed directly, and a multiply leaves the
inner loop.

## Measured

Self-oscillation tracking the cutoff, which is the test that the resonance path
and the delay compensation are both right:

| cutoff | oscillation | error |
|---:|---:|---:|
| 200 Hz | 197.5 Hz | −1.2 % |
| 400 Hz | 397.5 Hz | −0.6 % |
| 800 Hz | 800.0 Hz | 0.0 % |
| 1600 Hz | 1630.0 Hz | +1.9 % |

Above ~3 kHz it stops self-oscillating at fixed resonance — the paper's own
caveat that required feedback varies with frequency. A small compensation ROM
in silicon; **not implemented**, and the filter's first open work item.

### Fixed-point sizing

| parameter | value | why |
|---|---|---|
| signal | Q1.15 | |
| filter state | 24-bit, 20 fraction | 20 is the floor — below it the low-cutoff dead zone opens |
| coefficient | Q0.16 | |
| `tanh` table | **16 entries, edge-sampled, interpolated — 256 ROM bits** | 16 scores identically to 256 on every patch |

Area follows the table directly. The same sketch synthesises to **6,165 cells
with a 256-entry table and 1,917 with a 16-entry one**. Against
`gf180-polysynth`'s 19,049-cell core, the filter is roughly **+10 %**, not the
+32 % a bigger table implies.

An earlier guess that `tanh`'s odd symmetry would halve the cost was wrong — it
saved 4 %. ABC already compresses a large table's redundancy; the win is
needing *fewer entries*, not exploiting symmetry in more of them.

### Two things fixed point caught that float hid

**Limit cycles are real and irrelevant.** After four seconds of digital silence
the output settles to a flat, permanently nonzero 3–7 LSB at resonance 0.85 — a
true truncation limit cycle that never decays. At 32768 full scale that is
about −73 dBFS, under any DAC's noise floor. (At resonance 1.02 the residual is
~650 LSB, but that is self-oscillation working as intended.)

**Four of the eight audition patches exceed full scale.** `growl-bass` peaks at
1.787 with 7.1 % of samples over. In float this is invisible because the
renderer normalises afterwards; in fixed point it hard-clips, and that clipping
is the entire 13 dB gap between the two models on that patch — no amount of
extra state bits moves it, because it was never a precision problem. Gain
staging is now an open design decision: a ladder saturating on purpose is the
sound, but it should be a designed output stage, not an accident.

## A note worth keeping: table sample points

Interpolating a lookup table requires its values at bin **edges** (`i/N`).
Reading nearest-entry wants them at bin **midpoints** (`(i+0.5)/N`), which
halves the worst-case error. Mixing the two puts a half-bin skew on every
lookup. It cost about 8 dB here and presented as *"interpolation makes accuracy
worse"* — which is impossible, and was the tell that the bug was in the table
and not the filter. `model/test_fixed.py::test_interpolated_beats_nearest_at_the_same_size`
locks it.

## Layout

| | |
|---|---|
| `audition/` | Float models of three candidate architectures, and `play.py`, a real-time playable instrument. This is how the architecture was chosen — by ear, before any RTL |
| `model/` | The fixed-point filter, its sizing sweep, and regression tests |
| `rtl-sketch/` | A time-shared ladder datapath, **for area estimation only** — never simulated, never verified, not a design |
| `spec/decision-records/` | Why things are the way they are |

## Playing it

```bash
python3 -m venv .venv && .venv/bin/pip install numpy sounddevice mido python-rtmidi
.venv/bin/python audition/play.py
```

`a s d f g h j k` is a white-key octave, `w e t y u` the sharps. `SPACE` holds
a note on; `[` `]` sweep the cutoff, `-` `=` resonance, `;` `'` drive. A MIDI
device is auto-detected (CC 74 cutoff, CC 71 resonance, CC 73 drive).

```bash
.venv/bin/python -m pytest model/ -q
```
