# 0012: The fourth mixer source, oscillator 3 as a modulator, and the Model D waveform set

- **Status**: proposed
- **Date**: 2026-09-18
- **Decided by**: voice agent, from `docs/minimoog-reference.md` (the Minimoog Model 204D service manual and R. A. Moog drawings 1431 and 1448) and the measurements in `model/test_moog_acceptance.py` §5

## Context

The voice had three oscillators, a ladder, two envelopes and a glide, and it
was verified to the last bit against its own decision records. What it had
never been asked is whether those records describe a **Minimoog**. Three things
were missing, and `docs/minimoog-reference.md` is the reference that names each
of them against a primary source rather than against our own opinion:

1. **No noise source at all** — zero references in `model/voice_fx.py`. The
   Model D's mixer has five sources: three oscillators, noise, and an external
   input [verified: SM Specifications]. Noise through the ladder is a signature
   sound of the instrument.
2. **Oscillator 3 could not be used as a modulation source.** This is not an
   extra; it is how a Minimoog makes vibrato, filter wobble and the slow sweeps
   it is known for [verified: SM 2.4, 2.18, 5.19, 5.37].
3. **The waveform set was four shapes where the instrument has six**
   [verified: drawing 1448].

## The decisions

### 1. The noise source: one LFSR, three colours, a two-position selector

The Model D's generator is a transistor in avalanche breakdown, amplified into
white, pink and red, with a switch that selects **white or pink for audio and
pink or red for modulation** [verified: SM 2.5] — one bit, two destinations.

- **The generator** is a 31-bit maximal-length LFSR, `x^31 + x^15 + x^13 +
  x^11 + 1`, 16 steps per frame — **the drum section's polynomial** (contract
  15.4), where it is separately justified against a trinomial. Duplicated in
  `voice_fx.py` rather than imported, so the voice model does not depend on the
  drum model; the acceptance suite asserts the two step functions agree bit for
  bit from a common seed, which is what makes the duplication safe.
- **The seed is NOT shared.** Sharing one generator between voice and drums
  would have been nearly free — 31 flip-flops and 48 XOR gates — and would have
  made the two noises the *same signal*, which sums at +6 dB where two
  independent ones sum at +3. The voice seeds with the drums' state advanced
  1 060 921 steps (`0x7F215FF7`), a lag deliberately not a multiple of 16.
  Sharing would also have required editing `rtl-sketch/drum_dp.v` and
  `rtl-sketch/synth_top.v`, which another agent owns.
- **Pink is drawing 1431's own network**, not a generic pink filter: a 10 k
  series resistor with two shunt R-C legs (3.3 k + 0.12 µF, 240 Ω + 0.033 µF),
  which the drawing labels "−3 db/OCTAVE FILTER" and which evaluates to
  −3.10 dB/octave over 20 Hz .. 20 kHz. Implemented as its bilinear transform,
  a biquad in Q21/Q14 with a 32-bit Q5.27 state (the pole at 0.9889 would
  otherwise amplify its own truncation noise by 39 dB). It tracks the analog
  network within 0.03 dB below 2 kHz and 2.5 dB at 20 kHz.
- **Red is one more pole at 106 Hz** — R914 10 k with C908 0.15 µF, the section
  the drawing labels "100 Hz Lowpass Filter" [verified: 1431; SM 2.5 says one R
  and one C].
- **The three colours are level-matched**, because the instrument's are:
  drawing 1431 labels all three outputs −4 dBm and SM 5.27 specifies white and
  pink at the same "−5 ± 3 dB". Ours land within 0.07 dB of each other.
- **`NOISE_SHIFT = 2` is ours and is a deviation.** Equal-RMS colours and a
  hard rail fight: the pink network's crest factor is 4.6, so equal-RMS pink at
  white's natural level peaks at 2.6 × full scale. Dividing all three by four
  keeps them equal and keeps pink's measured peak at 0.66. It costs white 12 dB
  against an oscillator at the same mixer weight, recoverable with the noise
  weight (the register reaches 2.0). The alternative was clipping 0.05 % of
  pink's samples on a chip whose whole gain structure (DR 0005) is built so
  that nothing clips before the output stage.

**What is not taken**: the fifth mixer source, the external input, because
there is no audio input pin.

### 2. Oscillator 3 as a modulation source

- **MOD MIX is a PAN, not two levels**: "the wiper of R23 is connected to
  ground and, therefore, when the MODULATION MIX potentiometer is rotated, it
  pans between the two modulation signals" [verified: SM 2.4]. The two weights
  sum to 32768, so a fully-panned bus is never louder than either source alone.
- **Two destinations, two depths, one wheel.** The service manual pins both
  depths at full wheel: the oscillators "should change **13 to 23 semitones**"
  [verified: SM 5.37], and the cutoff goes from 440 Hz to "**a minimum of
  2.4 kHz**" [verified: SM 5.19] — 2.45 octaves. They differ, so there are two
  depth registers and not one. Reference values 0.75 and 1.30 octaves of peak
  deviation.
- **The exponential is one ROM.** Both destinations are exponential in the
  control voltage, so one 65-entry 2^x table over a single octave serves both:
  the octave word's fraction reads the ROM and its integer part becomes a right
  shift, which is why there is no barrel shifter on the mantissa. Worst error
  0.062 cents. The octave word saturates at ±4 octaves — five times the Model
  D's deepest setting — so the shift is 12..19 places and the shifter is three
  bits wide.
- **OSC-3 CONTROL is split in two.** On the instrument SW2 takes oscillator 3
  off the keyboard *and* off the modulation bus. The keyboard half is the
  host's job (it writes an LO-range increment instead of a note); the
  modulation half is in the datapath and is `MROUTE` bit 2.
- **The LO range needs no hardware.** The 24-bit increment register spans
  0.0029 Hz to 24 kHz, so the 0.2–0.5 Hz SM 5.36 asks for and the 32′ range it
  must overlap are the same register at different values.
- **The modulation value is registered, one frame old.** With OSC-3 CONTROL on,
  oscillator 3 is both the source and a destination — a feedback path. One
  register breaks it: 20.8 µs of delay, four orders of magnitude below the
  fastest rate the instrument reaches. The model and the RTL do this
  identically, so it is a specification and not an artefact, and
  `INJECT_BUG_VOICE_MOD_NODELAY` is the control that says so.
- **The tap is oscillator 3's naive waveform**, before PolyBLEP. The
  modulation path is a control voltage; it is never summed into the mixer and
  never heard. At LO rates the corrected and naive waveforms differ on only the
  single sample that lands on each discontinuity — three samples in 96 000 at
  0.2 Hz — which the acceptance suite measures rather than assumes.

### 3. The waveform set

Six per oscillator [verified: drawing 1448]: triangle, shark-tooth, sawtooth,
square, wide rectangular, narrow rectangular — with a **reverse sawtooth** in
oscillator 3's second position instead of the shark-tooth [verified: SM 2.3,
2.18].

- **The shark-tooth is 10/57 saw + 47/57 triangle**, the R030 (47 k) / R031
  (10 k) divider between two buffered sources of equal amplitude [verified:
  1448, SM 2.3]. 5749 and 27019 in Q0.15, summing to exactly 32768. Its step at
  the wrap is 10/57 of the sawtooth's, so the mix is taken on the
  *already-corrected* saw — exactly as the switch mixes the two buffered
  outputs.
- **The three rectangular widths are 50 %, 29 % and 15 %.** 50 % and 15 % are
  the ends of the pulse-width control range [verified: SM 2.3]; 29 % is the
  middle tap of drawing 1448's ground / 1.5 k / 1 k / 7.5 k / −10 V divider
  (−1.5 V), inferred by linear interpolation, which holds because the ramp the
  comparator sees is linear.
- **`pulse25` stays and is labelled ours.** It is not a Model D width. It is
  kept because contract revision 4 shipped it and every bit-exact expectation
  in the repository references it; the waveform register widened to 4 bits
  rather than quietly reusing one of its codes.
- **The reverse sawtooth is the band-limited sawtooth negated**, because Q20
  inverts the already-shaped waveform [verified: SM 2.3] — not a second
  PolyBLEP.

## Cost

No change to the multiplier, the divider or the ladder. One 65-word ROM, a
31-bit LFSR, a biquad and a one-pole for the noise board, and 38 sequencer
states. The measured worst-case frame latency went from **137 to 150 clocks of
the 248 available**, so the frame still has 40 % of its budget spare. Area is
not quoted here because nothing in this record has been synthesised yet
(`docs/verification-rules.md` rule 3).

## Verification

`rtl-sketch/verify_voice.py` gains three scenario groups — `waves3`, `noise`
and `modulation` — and four injected-defect controls, each demonstrated to turn
the bench red: `LFSR_TAP` (one tap of the polynomial wrong), `NOISE_SEL` (the
colour selector stuck on white), `SHARK_MIX` (R030 and R031 read the wrong way
round) and `MOD_NODELAY` (the pan and the register both gone).
`model/test_moog_acceptance.py` gains 21 properties in a new section 5, each
citing a tag in `docs/minimoog-reference.md`, and 7 more injected defects in
section 6.
