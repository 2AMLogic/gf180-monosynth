# 0004: Glide — constant rate, linear in pitch, slewed on the chip

- **Status**: proposed
- **Date**: 2026-09-17
- **Decided by**: block agent, from the circuit evidence below and measurements in `model/` (`test_voice_fx.py`, the DR 0004 tests)

## Context

The float audition glides geometrically over a constant 90 ms whatever the
interval; the rev-1 integer model slews the phase increment linearly over a
constant 4320 frames (contract 6.7). The two curves differ for the whole
glide and, since every later sample is shifted, the models are uncorrelated
on the glide patch (open item 17.2). Neither is what the instrument does.

Two questions decide the curve: is the glide linear in **voltage** (which,
through a volt-per-octave exponential converter, is linear in **pitch** —
a constant number of cents per second, geometric in Hz) or linear in
frequency; and is it **constant rate** (a larger interval takes longer) or
**constant time** (every interval takes the same time)?

### The Minimoog

- The panel control is a **rate**: "When the GLIDE switch is turned on the
  pitch will glide between notes at a rate set by control (2)" and "the
  further to the right control (2) is set, the longer it will take a tone to
  move from one pitch to the next." — owner's manual,
  <https://funkwerkes.com/web/wp-content/techdocs/MixedProAudio/Minimoog-Manual.pdf>.
- The reissue specifies it **per octave**: "Glide Rate (octave): 1
  millisecond to 10 seconds" — 2016/2022 manuals,
  <https://www.moogmusic.com/sites/default/files/Minimoog_Model_D_Users_Manual_Web.pdf>.
  A time per octave is a constant number of cents per second.
- The circuit lives in the keyboard sample-and-hold: "The glide feature is a
  function of the sample-hold circuit." — service manual,
  <https://www.synfo.nl/servicemanuals/Moog/MINIMOOG-D_SERVICE_MANUAL.pdf>.
  That copy omits the schematics ("The circuit schematics are not available
  at this time"), so **RC versus constant-current could not be established
  from a primary source.** The best technical description is from AJH
  Synth, who recreated the circuit for a module: an RC slew "produces an
  exponential glide slope … the pitch does not rise or fall evenly, and
  because of this it sounds nothing like the effect from a vintage Model D";
  the real one's "rise and fall slopes appear to be straight lines but this
  is not true … it still has a slight exponential curve", "it glides up
  rather faster than it glides down", and "the glide effect was only active
  while one or more keys were depressed" — <https://ajhsynth.com/Glide.html>
  (secondary source; the maker of a clone).
- "Lin/Log glide" was an after-factory modification (SOS reissue review,
  <https://www.soundonsound.com/reviews/moog-minimoog-model-d>), i.e. stock
  units had one fixed law.

So: a near-linear ramp in the keyboard CV, at a rate the panel sets, gated
by a key being down. Linear in CV into a V/oct oscillator is linear in
pitch; a rate is a rate.

### Modern instruments

- Moog documents three types and names the Minimoog's as the default and
  the norm: "LCR: The glide rate will depend on the size of the interval
  between notes. The larger the interval, the longer the glide time will be.
  This is the most commonly used type of glide. LCT: The glide time will
  stay the same between notes, regardless of the interval. EXP: The glide
  rate follows an exponential curve that begins with a fast rate and slows
  as it approaches the target note." — Sub 37 manual,
  <https://www.moogmusic.com/sites/default/files/Sub_37_Web_Manual_8_13.pdf>;
  "When LCR is selected, the GLIDE RATE stays the same regardless of the
  interval … Default = LCR" — Minitaur manual,
  <https://api.moogmusic.com/sites/default/files/2018-02/Minitaur_Manual.pdf>;
  Matriarch: "The default setting is LCR."
- Sequential: "Fixed Rate: The time to transition between notes varies with
  the interval between the notes; the greater the interval, the longer the
  transition time. The glide rate is fixed. This is the default glide mode."
  with Fixed Time and legato-only ("A") variants —
  <https://sequential.com/wp-content/uploads/2021/02/Prophet-6-Operation-Manual-2.1.pdf>.
- Arturia MiniBrute 2 is constant time ("it will take 3 seconds to glide
  from the first note to the second note, regardless of the distance between
  them", <https://dl.arturia.net/products/minibrute-2/manual/minibrute-2_Manual_1_0_EN.pdf>);
  MicroFreak offers both. MIDI CC 5 is named "Portamento Time" and defined
  no further (<https://midi.org/midi-1-0-control-change-messages>); Moog
  maps its rate to it.

## Decision

**Constant rate, linear in pitch, slewed on the chip.** The increment moves
toward its target by a fixed ratio of itself every frame — a constant number
of cents per frame — and lands exactly. This is what the panel control of
the Minimoog is, what its reissue specifies, and Moog's and Sequential's
default on every current instrument.

### Registers (contract 5.1)

| register | width | meaning |
|---|---:|---|
| `glide` | 24 u | Q0.24: the ratio per frame minus 1; **0 = off** (the increment follows its target at once) |
| `inc_tgt[k]` | 24 u | per oscillator, SET_INC's value |
| `inc_acc[k]` | 32 u | per oscillator, the increment now, Q24.8; `inc[k] = inc_acc[k] >> 8` is what the phase accumulator adds |

### The rule (contract 6.7, normative)

`SET_INC k, v, jump`: `inc_tgt[k] ← v`; if `jump = 1` or `glide = 0`,
`inc_acc[k] ← v << 8`. Then, at the end of every frame (step 9), for each
oscillator with `inc_acc ≠ inc_tgt << 8`:

```
tgt     = inc_tgt << 8
d       = max(1, (inc_acc · glide) >> 24)             exact 56-bit product, logical shift
inc_acc = min(tgt, inc_acc + d)   if tgt > inc_acc
        = max(tgt, inc_acc − d)   if tgt < inc_acc
```

with `glide = 0` snapping `inc_acc ← tgt`. Frame f's oscillator uses
`inc_acc >> 8` as it stands at the start of the frame, and `(e, r)` are
recomputed whenever that value changes (6.6.1). The `max(1, ·)` is the
envelope release's lesson (8.3): without it a small increment times a small
rate truncates to no motion.

### Host conversion (contract 5.5, informative)

```
glide = round( (2^(1 / (T_oct · 48000)) − 1) · 2^24 )      T_oct = seconds per octave; 0 → 0
```

The reference host uses `T_oct = 0.09` (the audition's 90 ms), `glide =
2692`. Constant-time glide is a host policy: compute `T_oct` from the
interval of each note; the chip needs nothing more. Legato-only glide
(Sequential's "Fixed Rate A", Bass Station II's "Autoglide", Korg's "Auto")
is `jump = 1` on the first key of a phrase; the reference host's `glide`
policy is `off | always | legato`, default `always` when a patch asks for
glide (the Minimoog's switch, which glides from the last pitch even after a
rest).

### Measured (the tests)

- log2 of the increment is linear in time through the glide: the per-frame
  step varies by less than 10⁻³ of a step (`test_glide_is_constant_rate_and_lands_exactly`);
  the oscillator after landing is the held-note oscillator bit for bit.
- One octave takes 90.0 ms ± 1 %; two octaves take 2.00 ± 0.02 × as long;
  down equals up (`test_glide_time_is_proportional_to_the_interval`).
- Two oscillators an octave apart stay within 1.99..2.01 of each other
  through the glide, and every increment's reciprocal is the note-on
  reciprocal for that value (`test_glide_preserves_the_detune_and_recomputes_the_reciprocal`).
- `glide = 0` and `jump = 1` take effect at the frame boundary
  (`test_glide_off_and_jump_take_effect_at_once`); the conversion gives 2692
  for 90 ms (`test_glide_register_conversion`).

## Alternatives considered

- **Linear in the increment over a constant time** (rev 1's model) — linear
  in Hz is front-loaded in pitch (half of an upward octave's cents pass in
  the first 41 % of the time) and constant-time is the MiniBrute's law, not
  the Minimoog's.
- **Geometric over a constant time** (the float audition; Moog's LCT) — the
  right curve with the wrong duration law. It remains available as host
  policy.
- **Exponential approach in pitch** (Moog's EXP; an RC lag) — AJH's evidence
  is that the Model D is not this, and it needs a pitch-domain state and a
  2^x converter on the chip, which the host has and the chip does not.
- **Host-driven, one `inc` write per frame** — the physical layer under
  discussion sends a packet per 256 frames (5.4); at the reference rate that
  is a 71-cent step per packet, a zipper. The slew has to be on the chip.
- **Asymmetric rates and freeze on all-keys-up** — the Model D's quirks per
  AJH. Not adopted: one rate register; the slew continues during a release
  tail (the only time the difference is observable). Either could be added
  later without changing this rule.

## Consequences

- Contract 2, 5.1, 5.2, 5.5, 6.7 and 14 change; revision 2. `GLIDE_SAMPLES`
  and the Q24.8 linear slew are gone from the model.
- Cost: one 32 × 24 multiply per oscillator per frame (three of the 256
  cycles, on the shared multiplier) and 24 + 3 × (24 + 32) register bits.
- The float audition's glide is now the odd one out; `voice_fx_render.py`'s
  lead-glide comparison stays uncorrelated with glide on, by design, and the
  integer voice is the reference.
- In paraphonic mode each oscillator glides at the same rate to its own
  key, which is what a per-voice glide does on the instruments above.
