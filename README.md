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
| 3 | RTL, bit-exact against (2) | **ladder and modal bank: done, in simulation** — `rtl-sketch/ladder_dp.v` is identical to `model/fixed.py` on 28,800 samples across five patches, `rtl-sketch/modal_dp.v` to `model/modal_fixed.py` on 48,000, and both benches are shown to fail on injected defects. The modal model's sizing is proposed, not ratified. Touch sketch: unverified |
| 4 | FPGA bitstream on real hardware | not started |
| 5 | gf180mcu ASIC | not started |

Nothing here has been synthesized to a PDK, so there is **no area in mm², no
timing and no power number**. The cell counts below are PDK-neutral yosys
output. The ladder's and the modal bank's are from RTL that is bit-exact
against their models; the touch sketch's is from a datapath that has never
been simulated for correctness.

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
| cutoff `g` | Q0.16, unsigned | reaches 61,659 at the 0.45·fs clamp: bit 15 is data, not sign |
| resonance `k` | Q3.14, 17 bits | 4·res; res = 1.0 is exactly 65,536 |
| `gain`, `ogain` | Q4.16, 20 bits | drive·vpu/2Vt = 2.6·drive; 2Vt/vpu·(1+2·res). Not Q0.16, whatever the model's older comment said |
| `tanh` table | **16 entries, edge-sampled, interpolated — 272 ROM bits** | 16 scores identically to 256 on every patch; the +1 top word is the model's 32767 |

The interpolation is a multiply, and it goes through the one shared multiplier
(two clocks per `tanh`), so the table costs no second multiplier. The RTL that
is bit-exact against this model synthesises to **5,725 cells with the 16-entry
table and 7,058 with 256**, 24 clocks per sample. The multiplier is 24 × 20 —
it has to carry `k·fb` at full state precision and the two 20-bit gains — and
is 3,299 of those cells, 58 %. Against `gf180-polysynth`'s 19,049-cell core
the filter is about **+30 %**.

The figures this README quoted before — *1,917 cells with a 16-entry table,
6,165 with 256* — were wrong, and not by a rounding error. They were the area
of a sketch that computed nothing: its 16-entry variant read the `tanh` ROM
out of range on every lookup (so every output was X, and yosys was free to
optimise most of the datapath away), and both variants had no interpolation,
no input or output gain, a 16 × 16 multiplier, an integrator shift 8× too
large, a wrapping 16-bit stage difference, and a second oversample pass that
reused the first pass's feedback. See `rtl-sketch/verify_ladder.py` and the
history of `ladder_dp.v`. The claim that odd symmetry "saved 4 %" was measured
on that sketch and is withdrawn with it.

### Verifying the RTL

The model is the specification and the RTL is compared against it sample for
sample with no tolerance. `rtl-sketch/verify_ladder.py` runs `LadderFx` on
five patches (the saw above with a 60 Hz → 12 kHz sweep; near-silence at
resonance 1.08; a full-scale square at 15 kHz and drive 3; LFSR noise; a
silent limit-cycle tail — 28,800 samples that reach the input clamp 61 times,
the output clamp 4,835 times, the `tanh` clamp 2,148 times, `g ≥ 2¹⁵` on
5,084 samples and `k ≥ 2¹⁶` on 9,600), drives `ladder_dp.v` with the same
integers under iverilog, and reports the first mismatch and the worst error.

```bash
export OSS_CAD_SUITE=/path/to/oss-cad-suite      # or put iverilog/vvp on PATH
.venv/bin/python rtl-sketch/verify_ladder.py                     # 16-entry table
.venv/bin/python rtl-sketch/verify_ladder.py --tanh-n 256
.venv/bin/python rtl-sketch/verify_ladder.py --inject FB --expect-fail   # negative control
.venv/bin/python rtl-sketch/verify_modal.py                      # the modal bank, same contract
.venv/bin/python -m pytest model/ rtl-sketch/ -q                 # all of the above
rtl-sketch/synth_count.sh                                        # the cell counts
```

A bench that cannot fail proves nothing, so three defects are compiled in
behind `INJECT_BUG_LADDER_FB` (unit delay instead of the half-sample average),
`INJECT_BUG_LADDER_SAT` (wrap instead of clamp) and
`INJECT_BUG_LADDER_TANH_CLAMP` (the old sketch's index wrap past 4.0). Each
is caught — 23,377, 3,155 and 18,389 mismatching samples respectively — and
`test_negative_control_is_caught` requires it.

One thing the bench cannot reach: the model's ±8.0 state clamp fired **zero**
times, and cannot. Once |y| ≥ 4.0 the stage's own `tanh` is pinned at 32767,
the difference driving the integrator changes sign, and the state turns back;
it peaks at 4.0 + 2g ≈ 5.9. The 24th state bit is still required — 5.9 needs
three integer bits and a sign — but it is not "6 dB of headroom before the
clamp"; the clamp is dead logic in both model and RTL, kept for bit-exactness.

### The modal bank, and the coefficient width it needs

`rtl-sketch/modal_dp.v` — the "something you can hit" engine: four two-pole
resonators, `y[n] = x[n] + a1·y[n−1] + a2·y[n−2]`, no RAM — was an unverified
sketch too, and it had its own version of the same failure. Its 18-bit Q2.16
coefficient ports **cannot tune a low bar**: at MIDI 28 (41 Hz) the pole sits
at `a1 = 1.99992`, its pitch lives in the difference between `a1` and 2, and
rounding that to Q2.16 puts mode 0 **2.4 % (41 cents) off pitch** and leaves
the output at **−1.9 dB SNR against the float** — a different signal, not an
approximation. The float model in `audition/physical.py` cannot show this
because it never quantises a coefficient, and it normalises its output
afterwards, so it fixes neither the precision nor the scale.

`model/modal_fixed.py` is the integer reference the RTL is now bit-exact
against, sized by its own sweep (`python3 model/modal_fixed.py`, locked by
`model/test_modal_fixed.py`): Q2.24 coefficients (0.005 % pitch, 0.04 % decay
at note 28), a 28-bit state with 15 fraction bits, and 10 bits of output
headroom because the bank rings up to **657× the strike** at note 28 — the
chip cannot normalise that away. Rounding in the recursion was measured and
buys nothing, so there is none. **That sizing is proposed, not ratified.**
Beyond the width, the sketch had the accumulator shift two bits too deep
(coefficients effectively ÷ 4), took the level tap before the excitation was
added, and wrapped instead of saturating.

`rtl-sketch/verify_modal.py`: 48,000 samples — six hits from note 28 to 100
(the top mode above 0.45·fs, so its coefficients are zero) and a full-scale
square at f₀ that drives the state to the rail 2,960 times — **0 differ**.
Three negative controls, each caught: `INJECT_BUG_MODAL_SHIFT` (the sketch's
shift, 47,991 mismatches), `_SAT` (wrap, 7,920) and `_PREEXC` (the sketch's
level tap, 552). **7,017 cells, 15 clocks per sample** — the sketch was
4,683 and 18. The 28 × 26 multiplier is most of it; the parallel coefficient
ports are muxed rather than read from a ROM, which overstates a real
implementation by those muxes, as the sketch already said. The modal bank is
not the cheap option it looked like.

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
| `model/` | The fixed-point filter and the proposed fixed-point modal bank, their sizing sweeps, and regression tests |
| `rtl-sketch/` | `ladder_dp.v` and `modal_dp.v`, time-shared datapaths bit-exact against `model/fixed.py` and `model/modal_fixed.py`, with their benches and negative controls. `touch_dp.v` is an area sketch only — never simulated, never verified |
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
.venv/bin/python -m pytest model/ rtl-sketch/ -q
```

The `rtl-sketch/` tests need `iverilog`; without it they skip, and a skip is
not a pass.
