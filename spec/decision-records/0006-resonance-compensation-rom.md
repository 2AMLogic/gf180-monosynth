# 0006: Resonance compensation — a 32-entry ROM so that res = 1 is the onset of self-oscillation at every cutoff

- **Status**: proposed
- **Date**: 2026-09-17
- **Decided by**: block agent, from the analysis and measurements in `model/k_comp_sweep.py` and `model/test_voice_fx.py` (the DR 0006 tests)

## Context

With `k = 4 res` fixed, self-oscillation tracks the cutoff within ±2 % from
200 Hz to 1.6 kHz at `res` ≈ 1.08 and is **not sustained above about
3 kHz** (README, DR 0001's consequences, contract 11.5, open item 17.5).
Huovilainen's §5.3 says why: with the feedback delay "the attenuation at
resonance frequency is no longer exactly 3 dB. This means that the feedback
amount required to produce the desired resonance varies with frequency",
and recommends a table: "With two times oversampling, the remaining tuning
error can be eliminated by using a tuning table. Since the error is so small,
the resonance tuning compensation can be combined with the tuning for scaled
impulse invariant transformed one-pole filter into a single table." —
<https://www.dafx.de/paper-archive/2004/P_061.PDF>. The paper's own caveat
is that a *tuning* table is two-dimensional (tuning at zero resonance
differs from tuning at self-oscillation); a *resonance* table is not, and it
is the one this record designs.

## The analysis

Inside its tanh table's first bin the fixed-point ladder is exactly linear
apart from truncation: every stage is `Y += g (s0·X − s0·Y)` with `s0 =
TANH16[1] / 2^13 = 0.9796` the table's slope there, i.e. a one-pole `H1 =
G / (1 − (1 − G) z⁻¹)` with `G = g · s0 / 2^16`, and the feedback is the
half-sample delay `Hfb = (z⁻¹ + z⁻²)/2 = e^{−1.5jω} cos(ω/2)` at 96 kHz.
The loop gain is `k · H1⁴ · Hfb`; self-oscillation starts at the frequency
where its phase is −180° and the `k` at which its magnitude is 1 there. The
phase, `−4 atan2((1−G) sin ω, 1 − (1−G) cos ω) − 1.5 ω`, falls monotonically
from 0 to below −π, so one bisection finds it (`voice_fx.k_onset`). The
input stage sees `k · fb`, four times the output, so "inside the first bin"
means an output under about 1200 LSB; the measurement below keeps its ring
there.

## The measurement

`model/k_comp_sweep.py` bisects the onset on the fixed-point filter itself
(the ROM'd `g`, the 16-entry table, every truncation): a 20-cycle sine burst,
then the free ring's growth or decay over two 20-cycle windows, the burst
scaled so the ring stays between 150 and 1200 LSB. A float replica of the
same difference equations with the same piecewise-linear tanh was run first
to confirm the sign flips at ±1 % of the predicted `k` at 30, 200 and
3000 Hz — it does, in float and in fixed point alike, and adding the
integrator's floor to the float changes nothing.

| cut Hz | g | k onset, linearised | k onset, measured | meas / lin | f_osc / cut, measured |
|---:|---:|---:|---:|---:|---:|
| 30 | 127 | 4.0038 | 4.0009 | 0.9993 | 0.968 |
| 50 | 212 | 4.0063 | 4.0034 | 0.9993 | 0.970 |
| 100 | 425 | 4.0127 | 4.0101 | 0.9993 | 0.975 |
| 200 | 850 | 4.0255 | 4.0224 | 0.9992 | 0.979 |
| 300 | 1273 | 4.0383 | 4.0356 | 0.9993 | 0.983 |
| 400 | 1691 | 4.0510 | 4.0489 | 0.9995 | 0.984 |
| 600 | 2521 | 4.0764 | 4.0738 | 0.9994 | 0.987 |
| 800 | 3342 | 4.1017 | 4.0977 | 0.9990 | 0.990 |
| 1000 | 4150 | 4.1268 | 4.1241 | 0.9993 | 0.993 |
| 1200 | 4948 | 4.1517 | 4.1494 | 0.9994 | 0.996 |
| 1600 | 6514 | 4.2011 | 4.1933 | 0.9981 | 1.001 |
| 2000 | 8039 | 4.2496 | 4.2422 | 0.9983 | 1.007 |
| 2500 | 9890 | 4.3090 | 4.3041 | 0.9989 | 1.014 |
| 3000 | 11682 | 4.3666 | 4.3622 | 0.9990 | 1.020 |
| 4000 | 15093 | 4.4758 | 4.4721 | 0.9992 | 1.032 |
| 5000 | 18288 | 4.5750 | 4.5722 | 0.9994 | 1.043 |
| 6000 | 21282 | 4.6625 | 4.6586 | 0.9992 | 1.051 |
| 8000 | 26712 | 4.7949 | 4.7855 | 0.9980 | 1.065 |
| 10000 | 31476 | 4.8619 | 4.8506 | 0.9977 | 1.072 |
| 12000 | 35655 | 4.8589 | 4.8474 | 0.9976 | 1.071 |
| 15000 | 40981 | 4.7332 | 4.7226 | 0.9978 | 1.058 |
| 18000 | 45359 | 4.4982 | 4.4891 | 0.9980 | 1.027 |
| 21600 | 49594 | 4.1460 | 4.1385 | 0.9982 | 0.906 |

The measured onset is 0.05–0.25 % below the linearised one everywhere, so
the analysis is the generator and the measurement is its check. `res =
1.08` (k = 4.32) is exactly enough at 2.5 kHz and not at 3 kHz, which is
the "above ~3 kHz" of rev 1. The required `k` peaks at 1.215 × 4 near
11 kHz and falls back toward 4 at the clamp, where the half-sample delay's
phase compensation runs out (the paper's Figure 5).

## Decision

**`K_ROM32`** (contract Appendix E, normative): 32 entries plus a guard,
unsigned Q1.15, edge-sampled every 1024 Hz at the cutoff clamped to
30..21600 Hz, `K_ROM32[i] = round(k_onset(clamp(1024 i, 30, 21600)) / 4 ·
32768)`; 32799 at the bottom, a peak of 39879 (1.217) at entry 11, flat at
33964 above the clamp. Read like the g ROM, with the low 10 bits of the
cutoff as the interpolation fraction (contract 10.2):

```
i     = cut >> 10                                  0..21
frac  = cut & 1023
kc    = K_ROM32[i] + (((K_ROM32[i+1] − K_ROM32[i]) · frac) >> 10)     Q1.15, signed product, arithmetic shift
k_eff = min( (k · kc) >> 15, 2^17 − 1 )                                Q3.14, the ladder's k for this frame
```

`k` stays the host's `round(4 res · 2^14)`; **`res = 1.0` is the onset of
self-oscillation at every cutoff**, within the residual below. `ogain` is
unchanged. The RTL ladder is unchanged: its `k` port is per-frame already.

### Residual with the ROM applied

`res` at the measured onset, i.e. `k_meas / (4 kc)`; 1.0000 is perfect:

| entries | ROM bits | worst residual (measured) | interpolation alone | rounding-tie margin |
|---:|---:|---:|---:|---:|
| 8 | 144 | 2.12 % | 1.94 % | 0.168 LSB |
| 16 | 272 | 1.40 % | 1.22 % | 0.162 |
| **32** | **528** | **0.39 %** | **0.21 %** | **0.053** |
| 64 | 1040 | 0.37 % | 0.19 % | 0.006 |
| 128 | 2064 | 0.32 % | 0.14 % | 0.002 |

With 32 entries the residual is under 0.2 % everywhere except at the
21.6 kHz clamp edge (0.39 %); 64 and 128 buy nothing measurable and the
128-entry table has an entry 0.002 LSB from a rounding tie, which the
contract's convention (3.9) forbids. The tests: the ring decays at `res =
0.995` and grows at `1.005` at 200 Hz, 3 kHz and 10 kHz
(`test_self_oscillation_starts_at_res_1_everywhere`); uncompensated `res =
1.08` sustains at 800 Hz and not at 6 kHz, compensated it sustains at both
(`test_uncompensated_k_stops_sustaining_above_3_khz`).

## Alternatives considered

- **No ROM; the host compensates** — the host does not have the cutoff: it
  is modulated per frame by the filter envelope and tracking on the chip.
- **128 entries, the g ROM's index** — sharing the address decode is
  convenient but the residual is the same and the tie margin is 0.002 LSB.
- **16 entries** — 1.4 %; audible as a resonance that depends on cutoff at
  the top of the range, which is the defect being fixed.
- **A two-dimensional table** (the paper's tuning caveat) — needed for
  tuning, not for the onset, which is a small-signal property with one
  dimension.
- **Fold the correction into `g`** (the paper's "single table") — that
  retunes the cutoff at zero resonance too; deferred to the tuning item
  below.

## Consequences

- Contract 2, 5.1, 10, 11.2, 11.5 and Appendix E change; revision 3. Two
  more multiplies per frame (the interpolation and `k · kc`) on the shared
  multiplier; 528 ROM bits.
- The meaning of `res` changes above ~1 kHz: the same host value gives up
  to 1.216 × the feedback of rev 1 at 11 kHz. The eight audition patches
  are affected only at their brightest moments (`k_eff` peaks at 1.19 × k on
  the filter sweep).
- **A new open item, the tuning**: the frequency the filter self-oscillates
  at is 0.968 × the cutoff at 30 Hz (the tanh slope `s0` and the g ROM's
  rounding at the bottom), 1.072 × at 10 kHz (the delay's phase, the paper's
  <10 % figure), 0.906 × at the clamp. Below 2 kHz that is within 14 cents;
  at 3 kHz it is 34 cents. A retuned g ROM would fix the resonant frequency
  and move the zero-resonance corner by the same amount — the paper's
  two-dimensional caveat — and is its own decision, after listening.
- `voice_fx.k_onset` (float, ROM-building only) joins the host-side
  conversions; `k_comp_sweep.py` is the reproducible measurement (107 s).
