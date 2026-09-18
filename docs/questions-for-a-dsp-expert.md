# Questions for a DSP expert, highest ROI first

Context: a fixed-point Minimoog-style voice and a TR-808 drum section on a
gf180mcu ASIC, 48 kHz, integer arithmetic throughout, bit-exact between a Python
model and RTL. Signal is Q1.15; the ladder's state is 24-bit with 20 fractional
bits in units of 2·Vt; the ladder runs 2× oversampled with the Huovilainen
DAFx-04 structure (`tanh` in every stage). Area and multipliers are the binding
constraints: the FPGA build uses 14 of 28 DSPs and the ASIC is ~2 mm² of cells.

Every number below is measured, not estimated. Where we have been wrong we say
so, because our record of confident wrong measurements is long enough that it
should temper how much weight you give any single figure.

---

## 1. Why did 2× oversampling make our aliasing *worse*?

**This is the one we most want answered, because we do not understand it and it
probably points at a real bug.**

Measured: oscillator aliasing went from **−42.7 dB to −33.1 dB** when we
oversampled the oscillators at 2×. We expected an improvement and got a 9.6 dB
regression, reproducibly enough that we kept it as a test so nobody re-proposes
it.

Our oscillators are integer phase accumulators with PolyBLEP correction. The
ladder is already 2× oversampled; this was about oversampling the *oscillators*.

- Is this the expected consequence of applying a PolyBLEP correction computed
  for one rate at another — i.e. did we invalidate the correction's assumptions
  rather than help?
- Is a naive 2× decimator (we take the last sub-step, zero-order-held input)
  simply folding what we just gained back in?
- Is there a standard way to get this wrong that we have found?

## 2. What is the right anti-aliasing strategy on a multiplier-starved
fixed-point target?

**Our largest measured defect.** We carry **19–32 dB more inharmonic energy
than Arturia Mini V3 and 9–32 dB more than Surge XT**, on every waveform, and
it **degrades with pitch** — ours goes −44 → −29 dB across the range where
Surge is flat at −60 dB over six octaves.

(Caveat we owe you: the rig producing those magnitudes has a waveform-mapping
bug under repair. The *shape* of the finding — worsening with pitch — reproduces
independently. Treat the magnitudes as provisional.)

Degrading with pitch is the worst shape it can take, because that is where a
lead line lives.

- **Higher-order PolyBLEP, more correction samples, minBLEP, BLIT, or
  wavetables** — which of these actually buys the most per multiply and per ROM
  bit at 48 kHz on a 4-octave-plus range?
- Is the right answer to fix the correction, or to change the oscillator
  altogether?
- The literature's long kernels demonstrate convergence rather than proposing
  an implementation. **What length is actually enough**, and how would you
  decide that empirically rather than by convergence plots?

## 3. Are we measuring the things that make a ladder sound like a Moog?

We measure cutoff accuracy, stopband slope, resonant peak, self-oscillation
onset and pitch tracking, drive behaviour, and the harmonic signature at
self-oscillation. We have got our worst tuning error from 6.85 % to 0.90 % by
implementing a term of Huovilainen's paper we had omitted.

But we do not know whether any of that is what a player responds to.

- **Which properties actually determine whether a ladder "sounds like a Moog"?**
  Our suspicion is that the drive and saturation behaviour matters far more than
  cutoff accuracy, and that we have been optimising the measurable rather than
  the audible.
- Reference emulations disagree with each other. **Where they disagree, is
  there a defensible target at all**, or is that the honest boundary of the
  method?
- Is there standard practice for validating a virtual-analog filter that we are
  reinventing badly?

## 4. Where does fixed-point precision actually bite in a ladder?

24-bit state, 20 fractional bits, in units of 2·Vt. Coefficients Q0.16.

- **At high resonance and low cutoff**, what fails first — limit cycles,
  quantisation in the feedback path, state underflow? What would we look for?
- Our self-oscillation tunes to within 0.90 % worst case now. Is there a
  precision floor below which self-oscillation pitch becomes unstable rather
  than merely inaccurate?
- We clamp the output. Is there a standard fixed-point ladder formulation that
  degrades more gracefully than saturation at the rail?

## 5. How should filter coefficients move at sample rate in fixed point?

Our cutoff registers are **integer hertz**, so one LSB is **53.7 cents at
30 Hz** — a 1.07 dB gain step at 24 dB/oct — falling to 0.9 cents at 2 kHz. So
the staircase is coarse at the *bottom* of the range, which is the opposite of
where we first looked.

Under movement we have a 5–9 dB higher ripple floor than Surge and Mini V3 at
every sweep rate, though every filter's ripple falls ~12 dB per octave of sweep
rate and nobody is stepping badly. Surge band-limits its cutoff control at
about 3 ms; we do not.

- **Log-domain cutoff register, fractional hertz, or smoothing?** Which is
  right when the target is a ROM lookup rather than an exp() per sample?
- Is there a reason to prefer interpolating the *coefficient* over interpolating
  the *control*?

## 6. What does `tanh` accuracy actually need to be, in a ladder specifically?

Ours is a **16-entry table, edge-sampled, linearly interpolated**, 256 ROM bits.
The ladder does **10 evaluations per sample**. Measured consequences: our 5th
harmonic at self-oscillation is too strong, and it is the table rather than the
structure — h3 does not move.

Things we measured that surprised us: a **quadratic interpolator on the same 16
entries is worse than linear** (the table is edge-sampled and its guard entry is
the clamp), and **past 64 entries the entire remaining error is one wrong guard
constant** — we return 32767 where tanh(4)·32767 = 32745.

- **Where in the curve does accuracy matter for a ladder?** Near zero for
  small-signal behaviour, or at the knee where the saturation character lives?
- Surge uses a closed-form approximation rather than a table. At 10 evaluations
  per sample that is ~70 multiplies + 10 divides against our 10 multiplies and
  20 ROM reads. **On a multiplier-starved target, is the table the right
  structure with a better sampling scheme?**

## 7. Is there a better fixed-point form for high-Q resonators at low frequency?

The 808's bass drum, toms and congas are bridged-T circuits, which we implement
as two-pole modal resonators. The bass drum is **49.4 Hz at Q 22.3** — high Q,
very low frequency, at 48 kHz. Coefficients are Q2.24 because Q2.16 is **2.4 %
off pitch at MIDI 28**.

- Direct-form two-pole at that Q and frequency is the classic case for
  coefficient-quantisation trouble. **Is a state-variable or coupled form
  materially better here in fixed point**, and what does it cost in multiplies?
- We ping these with an impulse; the real machines use a shaped pulse. The
  machine puts **41.2 % of its first 4 ms in 80–150 Hz against our 22.3 %**.
  How much of a bridged-T's character is the excitation versus the resonator?

## 8. Noise, at audio grade

We have just added a **31-bit LFSR** with a multi-bit slice. We established that
the raw output bit is unusable — **kurtosis 1.0, crest factor 0 dB**, against
references at kurtosis 2.2–3.0 and crest 8–13 dB. A 16-bit LFSR repeats in
**1.365 s**, which is audibly short; neither reference repeats within 8 s.

- **How many bits of slice, and which bits**, to get a usable amplitude
  distribution without a multiply?
- Pink: we implement the bilinear transform of the Model D's actual R-C network
  from the service drawing. Is there a reason to prefer a standard
  pinking filter over the circuit's own?

---

## What would help most

If you only answer one: **question 1**. A 9.6 dB regression from oversampling is
a result we cannot explain, and not understanding it means we cannot trust our
reasoning about question 2 either — which is our largest defect.

## What you can assume about our measurements

Estimators are validated against closed-form signals before use. Injected
defects are required to turn each property red, and the report prints which
properties were **blind** to each defect. Reference variance is measured: our
own model is deterministic at 0.000 pp, Surge 0.000, Mini V3 0.003.

We have also withdrawn a lot: a 25 dB probe separation that was window leakage,
every measurement from an unlicensed plugin that inserted clicks, a snare figure
that was wrong by 15×, and three area projections. **Assume any single number
here could be the next one**, and tell us if something looks implausible.
