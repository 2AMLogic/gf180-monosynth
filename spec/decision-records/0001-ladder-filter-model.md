# 0001: Huovilainen's ladder, and why not the more accurate models

- **Status**: proposed
- **Date**: 2026-09-17
- **Decided by**: block agent, from measurements in `model/` and a literature survey

## Context

The filter is the block. Choosing its model determines the datapath, the clock
budget and most of the area, and changing it after RTL exists is expensive, so
it is decided here, first. Four candidates were considered.

| model | tuning accuracy | solver | per-sample cost |
|---|---|---|---|
| Stilson & Smith (1996) | poor at high resonance | explicit | cheapest |
| **Huovilainen (DAFx-04)** | measured ±2 % to 1.6 kHz | **explicit** | 5 tanh + ~5 mult, ×2 oversample |
| Zavalishin ZDF/TPT (2012) + Newton-Raphson (D'Angelo & Välimäki, 2014) | best available | **iterative** | unbounded worst case |
| Levien matrix (2013) | exact on the linear part | explicit | 4×4 matrix multiply = 16 mult |

## Decision

**Huovilainen.** Not as a compromise — it is the model whose *structure* fits
this target, and the reason is the solver column, not the accuracy column.

Silicon has a fixed clock budget per sample: 12.288 MHz over 48 kHz is 256
clocks, and the sequenced ladder spends 10–20 of them deterministically. An
iterative solver has no such guarantee, and the literature is explicit that
Newton-Raphson for this filter "converges slower and slower as you raise the
feedback and the cutoff" — i.e. its worst case coincides exactly with high
resonance and an open filter, which is the setting a Minimoog is played in. A
fixed-latency pipeline would have to cap the iteration count, reintroducing
error precisely where the filter is supposed to be at its best. ZDF is the
right answer for a plugin, where an extra iteration costs microseconds and
nobody notices; it is the wrong answer for a fixed-budget datapath.

Levien's matrix form is exact on the linear fragment and beautiful on a SIMD
CPU, where a 4×4 multiply is a single tuned primitive. In silicon it is 16
multiplies against Huovilainen's ~5, and the nonlinearity — the part that makes
it sound like the circuit — remains a separate problem on top.

**What would reverse this:** a fixed 2- or 3-iteration Newton solve, measured
stable at resonance ≥ 1.0 across the full cutoff range and inside the clock
budget. That is an experiment, not a matter of taste, and it is worth running
if tuning accuracy above 3 kHz ever becomes the limiting complaint.

## The measurement that matters more than this decision

Aliasing from the oscillators is currently a **larger** defect than any
difference between these filter models, and it was found while surveying them.
The naive sawtooth carries inharmonic energy at:

| note | f0 | aliased energy |
|---:|---:|---:|
| 40 | 82 Hz | −27.7 dB |
| 64 | 330 Hz | −20.8 dB |
| 88 | 1319 Hz | −14.8 dB |

Inharmonic energy is far more perceptually objectionable than the harmonic
differences between filter models, which measured −2.8 to −11 dB *as a
difference*, not as distortion. A PolyBLEP correction — a comparison and about
three multiplies per sample, applied only near the discontinuity, with no
iteration and fixed latency — removes about **16 dB of it uniformly**:

| note | naive | PolyBLEP | improvement |
|---:|---:|---:|---:|
| 40 | −27.7 dB | −42.8 dB | 15.1 dB |
| 64 | −20.8 dB | −36.7 dB | 15.9 dB |
| 88 | −14.8 dB | −31.0 dB | 16.2 dB |

So: band-limited oscillators are a higher-priority work item than any further
filter-model refinement. Recorded here because the survey that produced this
decision is what surfaced it.

## Alternatives considered

- **Stilson & Smith linearised model** — cheapest, and the structure most
  "Moog filter" code actually uses: four *linear* one-poles with a single
  saturating element in the feedback path. Rejected on measurement: against
  Huovilainen it differs by −2.8 dB with the filter open and resonance high,
  sitting 5–8 dB hotter on harmonics 6–10, because it hard-limits once at the
  input and lets four linear stages pass the result. Driving it brightens;
  driving the real structure thickens.
- **ZDF/TPT with Newton-Raphson** — see above. Best tuning, wrong solver shape.
- **Levien matrix** — see above. Exact linear behaviour, 3× the multiplies,
  nonlinearity still unsolved.

## Consequences

- The datapath is a sequencer plus one multiplier and one `tanh` unit, not four
  parallel stages, and its latency is a constant.
- Tuning error is accepted at ±2 % to 1.6 kHz, and self-oscillation is **not**
  sustained above ~3 kHz at fixed resonance — the paper's own caveat that
  required feedback varies with frequency. A small compensation ROM is the
  intended fix and is not yet designed.
- 2× oversampling is mandatory, because the per-stage nonlinearities alias
  without it. That is a clock cost on the filter datapath, not an area cost.
- Anyone reimplementing this must not "simplify" to a single feedback-path
  `tanh`. That is a different filter, and the difference is the point.
