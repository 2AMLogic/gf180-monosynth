# Monosynth Voice — Numeric Contract

**Revision 1 — 2026-09-17 — status: PROPOSED. Not ratified.**

This document is a proposal for the complete, bit-exact specification of the
gf180-monosynth voice: three band-limited oscillators, a saturating mixer, two
integer ADSRs, and Huovilainen's nonlinear ladder, producing one signed 16-bit
sample per frame. It is written from the committed reference model and claims
nothing the model does not do. It becomes the specification RTL is verified
against only when ratified through the two-key process this fleet uses; until
then it is revision 1, proposed, and the status line above must not be read as
anything else (the rule is gf180-drone-fc DR-0005's: the status field must not
claim ratification before that act has happened).

**The model wins.** The normative text below is derived from these files, at
the commit this revision was written against, and where prose and code could be
read differently the code is what "bit-exact" means:

| file | what it is the specification of |
|---|---|
| `model/voice_fx.py` | the voice: oscillators, PolyBLEP, mixer, envelopes, cutoff path, output gain (sections 6–10, 12) |
| `model/fixed.py` | `LadderFx`, the ladder filter (section 11) |
| `audition/dsp.py` | the tables the voice imports: `phase_inc`, `note_hz`, `_QUARTER` (Appendices A, B) |
| `model/modal_fixed.py` | the modal resonator bank — **proposed sizing, not ratified** (section 15) |

Their tests (`model/test_voice_fx.py`, `model/test_fixed.py`,
`model/test_modal_fixed.py`, 40 tests) lock the sizing decisions; the RTL
sketches `rtl-sketch/ladder_dp.v` and `rtl-sketch/modal_dp.v` are already
bit-exact against `LadderFx` and `ModalFx` respectively
(`rtl-sketch/test_rtl.py`). Every table in the appendices is regenerated from
the model by `spec/reference/gen_tables.py`, and `gen_tables.py --check` fails
if any hash or table image in this document is no longer the model's.

If two readers could interpret a sentence differently, that is a defect in
this document. File it; do not resolve it by picking one reading. Any change to
a normative statement bumps the revision number.

Words: **MUST** is normative. *Informative* paragraphs explain, motivate or
show a host-side derivation and carry no obligation on the implementation.
**OPEN** marks something this revision deliberately does not specify; every
OPEN item is collected in section 17. Numbers written `0x..` are hexadecimal.

---

## 1. What the block is

A monophonic subtractive voice. Three phase-accumulator oscillators, each with
a PolyBLEP correction on its discontinuous shapes, are mixed with saturation,
scaled by an amplitude envelope, filtered by a four-pole nonlinear ladder whose
cutoff is driven by a second envelope plus keyboard tracking, and scaled by a
fixed output gain. A host writes the voice's control registers over a serial
link (the physical layer is OPEN, section 5.4); the host owns all musical
time. One sample leaves per frame, as I2S.

```
                 control image (section 5), applied at frame boundaries
                          │
   ┌──────────────────────┼─────────────────────────────────────────────────┐
   │ osc 0: phase acc ─► wave ─► PolyBLEP ─► ×w0 ─┐                         │
   │ osc 1:   "           "         "       ×w1 ─┼─► Σ ─► sat16 ─► × amp env ─► ladder ─► sat16 ─► ×29491>>15 ─► s16
   │ osc 2:   "           "         "       ×w2 ─┘   (mixer)       (§8,9)     (§10,11)              (§12)
   │                                     cutoff = clamp(lo + span·filt env + track) ─► g ROM ─┘      │
   └──────────────────────────────────────────────────────────────────────────┘
```

The block's observable behaviour is exactly two things: the sequence of output
samples, and how that sequence depends on the sequence of control writes and
the frames in which they arrived. Everything below defines those two things.

The order of the chain is `engines.mono_note`'s, the one that was auditioned:
the amplitude envelope is applied **before** the filter, so the filter is
driven harder on loud notes; there is no VCA after the ladder.

---

## 2. Fixed numbers

| Quantity | Value |
|---|---|
| Nominal frame rate | 48 000 frames/s (`dsp.SR`) |
| Core clock | 12.288 MHz = 256 × 48 000 |
| Cycles per frame | 256 |
| Output sample | signed 16-bit two's complement, mono, one per frame; range after the output gain is −29491..+29490 (section 12) |
| Oscillators | 3, numbered 0..2 |
| Phase accumulator / increment | 24-bit unsigned per oscillator (`dsp.PHASE_BITS`) |
| Waveform sample | Q1.15, signed 16-bit |
| PolyBLEP mantissa / reciprocal | 16 bits / 16 bits (`MANT_BITS`, `RECIP_BITS`) |
| Mixer weight | Q0.15, 16-bit unsigned register; a weight of 32768 is 1.0 |
| Envelope level | 24-bit unsigned, Q0.24 (`ENV_BITS`) |
| Envelope release rate | Q0.16 (`RATE_Q`) |
| Cutoff | integer Hz, clamped to 30..21600 (`CUT_MIN`, `CUT_MAX`) |
| Cutoff → g ROM | 128 entries + 1 guard, Q0.16, linear interpolation (`GROM_BITS` = 7) |
| Ladder state | 24-bit signed, 20 fraction bits, in units of 2·Vt (`LADDER_CFG`) |
| Ladder coefficients | g Q0.16 (16 bits); k Q3.14 (17 bits); gain, ogain Q4.16 (20 bits) |
| Ladder tanh table | 16 entries, edge-sampled, interpolated |
| Ladder oversampling | 2 passes per frame |
| Output gain | 29491 = 0.9 in Q0.15 (`OUT_GAIN`) |
| Tuning | A4 (MIDI note 69) = 440 Hz |
| Glide time (model, proposed) | 4320 frames = 90 ms (`GLIDE_SAMPLES`) |

---

## 3. Arithmetic conventions

1. All signed quantities are two's complement.
2. `x >> k` on a signed value is an **arithmetic** shift: `floor(x / 2^k)`,
   rounding toward −∞. `−1 >> 15 = −1`; `−7123 >> 15 = −1`.
3. `x >> k` on an unsigned value is a logical shift; the result is the same.
4. `x << k` is multiplication by 2^k, computed exactly (widen as needed).
5. Products and sums MUST be computed exactly and then shifted or saturated
   as stated. Nothing in this document truncates an intermediate. Every
   product fits in 64 signed bits; the widest is 24 × 20 bits in the ladder.
6. Only the phase accumulators wrap (modulo 2^24). Every other addition is
   either provably in range or explicitly saturated. The saturation points are
   listed in section 12.
7. `sat16(v)` clamps to −32768..+32767. `sat24(v)` clamps to −8388608..+8388607
   (`fixed.sat(v, 24)`).
8. `floor(a / b)` for integers is Python's `//`: rounding toward −∞ for a
   negative dividend. It is used with a negative dividend in exactly one place,
   the glide step (section 6.7).
9. `round(x)` in table derivations is Python's `round()`: round half to even.
   No table entry lies within 2.7 × 10⁻³ of a tie (the smallest margin is in
   NOTE_INC; `gen_tables.py` does not re-derive the tables, it evaluates the
   model's functions), so any correct evaluation reproduces them and
   round-half-up gives the identical tables. No rounding other than the floors
   above happens at run time.

---

## 4. Frames and the clock

### 4.1 Definition

A **frame** is the production of one output sample. Frames are numbered from
0; frame 0 is the first frame after reset is released, and frame f produces
sample f. Nominally a frame lasts 1/48 000 s. The core clock is divided so that
a **frame tick** occurs once every 256 cycles; the cycle in which the f-th tick
is asserted is **cycle 0 of frame f**, and cycle 255 of frame f is the cycle
before tick f+1.

### 4.2 What happens in a frame

Sample f is a pure function of the register state at the start of frame f
(after step 1). Conceptually, in this order, per frame:

1. **Apply control.** Every control write that became complete during frame
   f−1 (section 4.3) is applied, in order of completion.
2. **Oscillators** (section 6): for each oscillator k, `osc_k` from `phase_k`
   *before* it is advanced, `inc_k`, and the reciprocal state `(e_k, r_k)`.
3. **Mixer** (section 7): `mixed = sat16((Σ osc_k · w_k) >> 15)`.
4. **Envelopes** (section 8): `ae = level_amp >> 9`, `fe = level_filt >> 9`,
   both from the levels *before* this frame's update.
5. **Amplitude** (section 9): `x = (mixed · ae) >> 15`.
6. **Cutoff** (section 10): `cut = clamp(cut_lo + ((cut_hi − cut_lo) · fe >> 15) + track_hz, 30, 21600)`;
   `g = G(cut)` from the ROM.
7. **Ladder** (section 11): two oversampling passes on `x` with `g, k, gain,
   ogain`, producing `y`, saturated to 16 bits.
8. **Output** (section 12): `sample_f = (y · 29491) >> 15`.
9. **Advance.** For each oscillator `phase_k ← (phase_k + inc_k) mod 2^24`.
   Each envelope's level is updated by the rule of 8.3. The ladder's state was
   already advanced in step 7 (it is recursive; its state after step 7 is the
   state for frame f+1).

An implementation may schedule this across the 256 cycles however it likes,
provided the sample sequence is identical. In particular a control write
received during frame f MUST NOT affect sample f.

### 4.3 "Immediately before frame f": control timing

A control write is *received during frame f* if the cycle in which the core
accepts its last unit (byte, or the last bit of a packet — the unit is the
physical layer's, section 5.4) is cycle c with `tick_f ≤ c < tick_{f+1}`; a
unit accepted in the tick cycle itself belongs to the frame that starts in
that cycle. A write is *complete during frame f* when its last unit was
received during frame f.

**Every write complete during frame f MUST be applied at the start of frame
f+1, in order of completion, before sample f+1 is computed, and MUST NOT
affect sample f.** "Immediately before frame f" therefore means: complete
during frame f−1. Each write is applied exactly once and atomically — all the
registers it names change together and no sample is computed from a partially
applied write. A packet that carries several registers is one write.

### 4.4 Cycle budget

An implementation MUST finish steps 1–9 within 256 cycles of the tick. The
measured sequenced ladder (`rtl-sketch/ladder_dp.v`) takes 24 of them per
frame including both oversampling passes, fixed, worst case equal to mean
(`rtl-sketch/tb_cycles.v`). Nothing in the sample sequence depends on the
clock frequency; an implementation that needs fewer cycles MAY be clocked
slower.

---

## 5. Control interface

This revision specifies the **semantics** of control — which registers exist,
what each does, and when a write takes effect — and leaves the physical layer
OPEN (5.4). The product direction (DR 0002) is a host microcontroller driving
this block over a serial link; whether that link is a UART event stream as in
gf180-polysynth's contract or the SPI time-slice packets proposed in
gf180-polysynth issue 7 changes the framing, not anything below.

### 5.1 The control image

The voice's control state is the following registers. "Width" is the register
width an implementation MUST hold; "model" says where the value comes from in
the reference model, whose `VoiceFx.note_on` computes the whole image from a
patch's physical units in float — the one place float is allowed, and in the
product the host's job (5.5).

| Register | Width | Per | Meaning | Model |
|---|---:|---|---|---|
| `inc[k]` | 24 u | osc | phase increment | `incs[k]` |
| `wave[k]` | enum | osc | one of saw, square, pulse25, tri, sine (encoding OPEN, 5.2) | `waves[k]` |
| `w[k]` | 16 u | osc | mixer weight, Q0.15 | `weights[k]` |
| `a_inc`, `d_dec`, `sus` | 24 u | env ×2 | attack increment, decay decrement, sustain level, Q0.24 | `AdsrFx` |
| `rate` | 16 u | env ×2 | release rate, Q0.16 | `AdsrFx.rate` |
| `gate` | 1 | voice | envelope gate (both envelopes) | `gate_n` |
| `cut_lo`, `cut_hi`, `track_hz` | 16 u *(proposed)* | voice | cutoff floor, ceiling and keyboard-tracking offset, integer Hz | `cut_lo`, `cut_hi`, `track_hz` |
| `k` | 17 u | voice | ladder resonance, 4·res in Q3.14 | `LadderFx.coefficients` |
| `gain` | 20 u | voice | ladder input gain, drive·2.6 in Q4.16 | same |
| `ogain` | 20 u | voice | ladder output gain, (1+2·res)/2.6 in Q4.16 | same |

The two envelopes are `amp` (section 9) and `filt` (section 10); each has its
own `a_inc`, `d_dec`, `sus`, `rate`.

The widths of `cut_lo`, `cut_hi` and `track_hz` are **proposed, not in the
model**: the model holds them as unbounded integers. 16 bits unsigned is
derived from the largest value any audition patch produces (`track_hz` =
45 158 at MIDI note 127 with `track` = 0.9; `cut_hi` = 7000) and from the
clamp in section 10, past which larger values change nothing. The sum in
section 10 MUST be computed exactly whatever the width. `k`, `gain` and
`ogain` are the RTL's port widths, and the RTL is bit-exact against the model
within them; the model asserts `k < 2^17` and `gain, ogain < 2^20`.

State registers (not host-writable except by RESET): `phase[k]` (24), `e[k]`
and `r[k]` (section 6.6.1), `level` and `seg` per envelope (section 8.1), the
ladder's `y[0..3]`, `w[0..3]`, `d1`, `d2` (section 11.2).

### 5.2 Writes and their semantics

| Write | Effect at the next frame boundary (4.3) |
|---|---|
| SET_INC k, v | `inc[k] ← v`. The reciprocal state `(e[k], r[k])` MUST be recomputed from the new value by 6.6.1 before it is next used, i.e. before sample f+1's PolyBLEP. `phase[k]` is not touched. |
| SET_WAVE k, s | `wave[k] ← s`. Takes effect from the next sample, mid-note. |
| SET_WEIGHT k, v | `w[k] ← v`. |
| SET_ENV e, a_inc/d_dec/sus/rate | the named parameter of envelope e ← v. The envelope update at the end of the frame in which the write was applied already uses it. |
| SET_CUT lo/hi/track | the named cutoff register ← v. |
| SET_LADDER k/gain/ogain | the named coefficient ← v. Held for the whole frame (both passes). |
| GATE_ON | `gate ← 1`. What else happens — envelope restart, phase reset, ladder state — is **OPEN** (section 8.5). |
| GATE_OFF | `gate ← 0`. Both envelopes take the release branch of 8.3 from wherever their level is, regardless of segment. |
| RESET | every register of section 14 ← its reset value. |

Whether these are individual commands (UART) or fields of one packet (SPI
time-slice) is the physical layer's business; a packet carrying many fields is
one atomic write. **The encoding of `wave[k]` and of every opcode or field is
OPEN**; the model names shapes by string. A proposed encoding is in section
17 for the record and carries no force.

Any register value is legal; nothing is rejected for range. Consequences of
out-of-range values follow from the formulas (an `inc` ≥ 2^23 is above
Nyquist; weights summing above 32768 saturate in the mixer; `a_inc` = 0 holds
the attack at its current level forever; `rate` = 0 releases at one LSB per
frame).

### 5.3 The unit of "a note"

The model's unit of work is one note rendered from reset: `note_on` builds a
fresh control image, fresh oscillators at phase 0, fresh envelopes at level 0
in ATTACK with the gate on, and a fresh ladder with zero state, then `run`
computes `n` frames with the gate on for the first `gate_n` of them. The
harness `render_mono_fx` sums overlapping notes with saturation; **that is a
harness artefact, not a behaviour of the voice**, and it is the reason the
model does not yet define what a second GATE_ON does to a sounding voice.
Reference sequences for bit-exact comparison in this revision are therefore
single notes from reset (section 16); see 8.5.

### 5.4 Physical layer — OPEN

Not specified here. Two candidates are on the table:

- a UART byte protocol as in gf180-polysynth `spec/NUMERIC-CONTRACT.md`
  section 10 (115 200 8N1, status/data bytes, commands applied at the next
  frame boundary), which DR 0002 notes is a fit for a human-facing event
  stream but less so for an MCU bridge;
- SPI time-slice packets, gf180-polysynth issue 7: the host sends one packet
  per slice of N frames carrying the whole control image, with a repeat count;
  N = 256 frames (5.33 ms) is argued for there on live-timing grounds.

Whichever is chosen must satisfy 4.3 exactly as written: the frame in which a
write completes is defined by the acceptance cycle of its last unit, and it
applies at the next tick. A decision record will extend this section.

### 5.5 Host-side conversions (informative)

`VoiceFx.note_on` is the reference for how a patch's physical units become
register values. These formulas are informative — the block never sees Hz,
seconds or `res` — but a host that wants the model's sound uses them:

```
inc[k]     = round(f0 · 2^(detune_k/12) · 2^24 / 48000)     f0 = 440 · 2^((note−69)/12)
w[k]       = floor(mix_k / Σmix · 2^15)                     "floor-normalised": Σ w ≤ 32768
a_inc      = ceil(2^24 / max(1, floor(attack_s · 48000)))
sus        = round(sustain · (2^24 − 1))
d_dec      = ceil((2^24 − 1 − sus) / max(1, floor(decay_s · 48000)))
rate       = max(1, round((1 − exp(−4 / (release_s · 48000))) · 2^16))
cut_lo/hi  = round(cutoff_lo/hi_hz)
track_hz   = round(track · f0 · 4)
k          = round(4 · res · 2^14)
gain       = round(drive · 0.13 / 0.05 · 2^16)  = round(drive · 2.6 · 65536)
ogain      = round(0.05 / 0.13 · (1 + 2 · res) · 2^16)
```

Two of these can exceed their register: `a_inc` = 2^24 when the attack is
shorter than two frames, and `rate` = 65536 when the release is shorter than
about 7 µs. In both cases the value is outside the register width of 5.1. The
observable difference between 2^24 and 2^24 − 1 for `a_inc` is nil (either
completes the attack in one update from any level); for `rate`, 65535 reaches
zero from full scale in 3 frames where 65536 takes 1. **OPEN 17.7**: the
model's conversion should clamp to the register width so that the model and a
register-limited implementation cannot differ even here.

Default patch values, for reference (the `note_on` defaults): waves (saw,
saw, square), detune (0, +0.07, −12) semitones, mix (1.0, 0.8, 0.5) → weights
(14246, 11397, 7123), cutoff (400, 4000), res 0.62 → k = 40632, drive 1.6 →
gain = 272630, ogain = 56462, amp ADSR (5 ms, 250 ms, 0.75, 120 ms) → a_inc =
69906, d_dec = 350, sus = 12582911, rate = 45; filter ADSR (4 ms, 300 ms,
0.25, 100 ms); track 0.35.

---

## 6. Oscillators

### 6.1 Registers

Per oscillator: `phase` (24-bit unsigned), `inc` (24-bit unsigned), `wave`,
and the PolyBLEP state `e` (signed, −15..+8 over all 24-bit `inc` ≥ 1;
−4..+7 over NOTE_INC) and `r` (16-bit unsigned).

### 6.2 Phase advance

Once per frame, step 9 of 4.2: `phase ← (phase + inc) mod 2^24`. The
oscillator sample of a frame is computed from `phase` **before** the advance.
The first sample of a note from reset uses `phase = 0`.

### 6.3 Frequency to increment; NOTE_INC

An increment `inc` produces a nominal frequency `inc × 48 000 / 2^24` Hz
(resolution 0.00286 Hz). MIDI note n has `f(n) = 440 × 2^((n − 69)/12)` Hz and

```
NOTE_INC[n] = round( f(n) × 2^24 / 48000 )        n = 0..127
```

**Appendix A is normative**; the formula is stated so the table can be
re-derived. `NOTE_INC[69] = 153791`, `NOTE_INC[0] = 2858`, `NOTE_INC[127] =
4384395`; every entry is below 2^23. The table is identical, value for value
and hash for hash, to gf180-polysynth's Appendix A. Detuned oscillators use
`round(f(n) · 2^(detune/12) · 2^24 / 48000)`; the block does not compute this
— the host writes `inc` — so NOTE_INC pins the values a host MUST produce at
zero detune and the tuning reference, no more.

`inc` may hold any 24-bit value. `inc = 0` stalls the oscillator; the
PolyBLEP is then identically zero (6.6.3) — but note the model's `recip_of`
raises on 0, so no reference sequence exercises it (17.9).

### 6.4 Naive waveforms

Let `p` be the 24-bit phase before advance. `naive` is signed 16-bit
(`voice_fx.naive_fx`):

| shape | formula |
|---|---|
| saw | `(p >> 8) − 32768` — rising ramp, −32768 at p = 0, +32767 at p ≥ 0xFFFF00 |
| square | `+32767` if `p < 0x800000`, else `−32768` |
| pulse25 | `+32767` if `p < 0x400000`, else `−32768` |
| tri | `q = p >> 7` (0..131071); `q − 32768` if `q < 65536`, else `98303 − q` |
| sine | `SINE(p)`, section 6.5 |

The square and pulse steps **up** at the wrap (p = 0) and **down** at the
duty point; the saw steps **down** at the wrap. That difference fixes the sign
of the correction in 6.6.4.

### 6.5 Sine

`SINE_Q256` (Appendix B, normative) is the 256-entry quarter wave
`round(32767 · sin(π/2 · (i + 0.5) / 256))`, i = 0..255 — sampled at bin
**midpoints**, because it is read nearest-entry with no interpolation. (This
differs from gf180-polysynth's 257-entry edge-sampled table; the two blocks'
sines are not the same values.) From the phase (`voice_fx.sine_fx`):

```
idx  = (p >> 14) & 1023           top 10 bits of the phase
quad = idx >> 8                   0..3
i    = idx & 255
q    = SINE_Q256[255 − i]  if quad is odd, else  SINE_Q256[i]
SINE = −q                  if quad ≥ 2,     else  q
```

Consequences: the full 1024-entry expansion (hash in Appendix B) has
`SINE(0) = 101`, `SINE[255] = SINE[256] = 32767`, `SINE[512] = −101`; there is
no zero and no −32768 in it; it is odd-symmetric about index 512 and
even-symmetric about 255.5.

### 6.6 PolyBLEP

Applied to saw, square and pulse25 only. Triangle and sine are the naive
waveform (the model constructs `OscFx` with `blep = blep and shape in (saw,
square, pulse25)`). The integer model's aliasing suppression equals the float
PolyBLEP's at every note measured (DESIGN.md section 6); the widths below were
set by tracking the float waveform inside Q1.15, not by aliasing.

#### 6.6.1 Reciprocal at increment change

Whenever `inc` takes a new value (note-on, SET_INC, each frame of a glide),
compute (`voice_fx.recip_of`, with `MANT_BITS = RECIP_BITS = 16`):

```
e = bit_length(inc) − 16                  bit_length(v) = number of bits in v, so 2^(bl−1) ≤ v < 2^bl
m = inc >> e         if e ≥ 0             m is 16 bits: 2^15 ≤ m < 2^16
  = inc << (−e)      if e < 0
r = min( floor(2^31 / m), 65535 )         16 bits
```

So `inc = m · 2^e` with a 16-bit mantissa, and `r ≈ 2^31 / m`. The `min`
fires only when `m = 2^15`, i.e. `inc` is a power of two, a 1-LSB error; no
NOTE_INC entry is a power of two. Over NOTE_INC, `e` ranges −4..+7 and `r`
33209..62696. Example: `inc = 153791` (note 69) has 18 bits, `e = 2`,
`m = 38447`, `r = floor(2147483648 / 38447) = 55855`.

This is one integer division per increment change. *Informative:* a
sequential divider takes 24 clocks of the 256-cycle frame; the specification
is the exact floor quotient however it is obtained.

#### 6.6.2 The fraction `x / inc` in Q0.16

For `0 ≤ x < inc` (`voice_fx.frac_q16`):

```
p = x >> e           if e ≥ 0        p ≤ m, 16 bits
  = x << (−e)        if e < 0
u = (p · r) >> 15                    exact 32-bit product
u = min(u, 65535)
```

`u ≈ x · 2^16 / inc`. The `min` cannot fire (`p ≤ m` and `r ≤ 2^31/m` give
`p·r ≤ 2^31`, with equality impossible after the clamp of 6.6.1); an
implementation that omits it is bit-identical. `frac(0) = 0`.

#### 6.6.3 The correction

For phase `p` and increment `inc` (`voice_fx.blep_fx`), the correction `c(p)`
is:

```
c = 0
if p < inc:                        just after the wrap
    s = 65536 − frac(p)            1..65536
    c = −((s · s) >> 17)           −32768..0
q = 2^24 − p
if q < inc:                        just before the wrap  (q is 1..inc−1 here)
    s = 65536 − frac(q)            1..65536
    c = +((s · s) >> 17)           0..+32768
```

`c` ranges **−32768..+32768** — 17 bits signed; the +32768 occurs when
`frac(q) = 0`, which happens for `q < 2^e`. If both conditions hold (possible
only when `inc > 2^23`) the second assignment wins. With `inc = 0` neither
condition can hold and `c = 0` for every `p`.

*Informative:* this is `dsp._blep` in integers: the polynomial `−(1 − t/dt)^2`
just after a downward step and `+(1 − (1−t)/dt)^2` just before it, in Q0.16
squared and shifted to Q1.15. It is the correction to **subtract** from a
naive saw.

#### 6.6.4 Application per shape

With `naive` from 6.4 and `c(·)` from 6.6.3 evaluated with this oscillator's
`inc, e, r` (`voice_fx.OscFx.render`):

```
saw:      osc = sat16( naive − c(p) )
square:   p2 = (p + 0x800000) mod 2^24          duty = 2^23
          osc = sat16( naive + c(p) − c(p2) )
pulse25:  p2 = (p + 0xC00000) mod 2^24          duty = 2^22, so p2 = (p + 2^24 − duty) mod 2^24
          osc = sat16( naive + c(p) − c(p2) )
tri, sine: osc = naive
```

**The square's sign is opposite to the saw's at p = 0**: the saw steps down
there and takes `−c`; the square steps up and takes `+c`. Its second edge, at
`p = duty`, steps down and takes `−c` evaluated at the phase shifted so that
edge lands on the wrap. Getting this backwards measures about 5 dB *worse*
than the naive square (`test_square_correction_has_the_right_sign`).

Consequences: at `p = 0` the band-limited saw is `sat16(−32768 − (−32768)) =
0`, the midpoint of its step, and the square is `sat16(32767 − 32768 − 0) =
−1`. Both differ from the naive values by design.

### 6.7 Glide — OPEN, model behaviour recorded

The model slews the increment **linearly** over `GLIDE_SAMPLES = 4320` frames
in a Q24.8 accumulator (`VoiceFx.note_on`, `glide_from`): with `i0` the
increment of the previous note and `i1` of the new one, both at this
oscillator's detune,

```
step   = floor( ((i1 − i0) << 8) / 4320 )          floor toward −∞ when i1 < i0
inc_j  = (i0 · 256 + step · j) >> 8                 j = 0..4319
inc_j  = i1                                         j ≥ 4320
```

and `(e, r)` are recomputed for every frame in which `inc_j` changes. The
float audition model glides **geometrically** (a constant ratio per frame);
the two curves differ for the 90 ms of the glide and are identical after it,
and the difference shifts every later sample so the models are uncorrelated
on a glided patch (+0.6 dB). Which curve, whether the slew is on-chip or the
host writes `inc` each frame, and whether 90 ms is a constant or a register,
are undecided (17.2). The model's slew is recorded here so that it is
checkable, not because it is chosen.

---

## 7. Mixer

Per frame (`voice_fx.mix_fx`):

```
acc   = osc_0 · w_0 + osc_1 · w_1 + osc_2 · w_2      exact; |acc| < 3 · 2^31
mixed = sat16( acc >> 15 )                           arithmetic shift, then clamp
```

`w_k` are 16-bit unsigned. Weights the host derives by 5.5 sum to at most
32768 and cannot clip (`test_normalised_mix_cannot_clip`); unnormalised
weights are legal and saturate, never wrap (`test_mixer_saturates_instead_of_wrapping`).
With the default weights and oscillators 1 and 2 at the values of 6.6.4's
consequence, `mixed` at the first frame of a note is `(0 + 0 − 7123) >> 15 =
−1`.

---

## 8. Envelopes

Two identical integer ADSRs, `amp` and `filt`, share the `gate`
(`voice_fx.AdsrFx`). Attack and decay are linear ramps, matching the float
model that was auditioned; release is exponential with a floor.

### 8.1 Registers

| Register | Width | Meaning |
|---|---|---|
| `level` | 24-bit unsigned | Q0.24 level, 0..0xFFFFFF; `FULL = 2^24 − 1` |
| `seg` | 2-bit | ATTACK = 0, DECAY = 1, SUSTAIN = 2 |
| `a_inc` | 24-bit unsigned | level increment per frame in ATTACK |
| `d_dec` | 24-bit unsigned | level decrement per frame in DECAY |
| `sus` | 24-bit unsigned | DECAY target and SUSTAIN level |
| `rate` | 16-bit unsigned | Q0.16 release fraction |

There is no IDLE state and no RELEASE state: the gate selects the branch. A
voice from reset has `level = 0`, `seg = ATTACK`, `gate = 0`, and the release
branch holds the level at 0 (8.3), so it is silent.

### 8.2 Output

The envelope's output in a frame is the 15-bit value `level >> 9`, from the
level **before** this frame's update (8.3). It is 0 in the first frame of a
note from reset and is 32767 for `level ≥ 0xFFFE00`, in particular at `FULL`.

### 8.3 Update rule (step 9 of 4.2, once per frame)

Exactly one branch executes, chosen by `gate` then `seg` as they are at the
start of the update. Comparisons are on exact integers.

```
gate = 1:
  ATTACK:   level ← level + a_inc
            if level ≥ FULL:    level ← FULL ; seg ← DECAY
  DECAY:    level ← level − d_dec                     (exact; may be negative before the test)
            if level ≤ sus:     level ← sus ;  seg ← SUSTAIN
  SUSTAIN:  level ← sus

gate = 0 (release, from any seg; seg is NOT changed):
  dec   ← (level · rate) >> 16                        exact 40-bit product
  level ← level − max(1, dec)
  if level < 0:  level ← 0
```

**`max(1, dec)` is load-bearing.** Below `level = 2^16 / rate` the product
truncates to zero and, without it, the level would never move again and the
note would never end; with it the tail below that floor decays at one LSB per
frame and reaches exactly zero (`test_release_reaches_exactly_zero`). The
floor is `floor(2^16 / rate) + 1` levels (`AdsrFx.floor_level`); at 24 level
bits it is below −60 dBFS for every release up to 1 s
(`test_release_floor_is_below_the_noise_floor`), which is why the level is
24 bits and not 20.

Notes that follow from the rule and are intentional:

- `a_inc = 0` holds ATTACK forever at the current level; `d_dec = 0` holds
  DECAY forever unless `level ≤ sus` already; `rate = 0` releases at one LSB
  per frame (2^24 frames = 350 s from full). None of these is reachable
  through the host conversions of 5.5, which give every parameter at least 1.
- SUSTAIN re-asserts `level ← sus` every frame, so a change of `sus` while
  sustaining moves the level in one frame (unlike gf180-polysynth's envelope).
- In DECAY, if `sus` is above the current level the level jumps **up** to
  `sus` in one frame.
- A gate that drops during ATTACK releases from the partial level; the attack
  does not complete. Because `seg` is untouched by the release branch, a gate
  that comes back would resume the segment it was in — which is exactly the
  retrigger question left OPEN in 8.5.

*Informative, derived:* ATTACK from 0 takes `ceil(FULL / a_inc)` updates; the
default `a_inc = 69906` reaches FULL at update 240 (5.0 ms) and the output
first reads 32767 in frame 240.

### 8.4 Gate timing in the model

`render(n, gate_n)` has the gate on for frames `0..gate_n−1` and off from
frame `gate_n`; `gate_n = min(n, max(1, floor(gate_s · 48000)))`, with
`gate_s = 0.8 · dur` by default. In hardware the gate is the register of 5.1
and its timing is the host's.

### 8.5 Retrigger — OPEN

What GATE_ON does to a voice that is already sounding, or still releasing, is
not decided by either model: the float and integer harnesses both render each
note independently from reset and sum the overlaps. Legato (no envelope
restart), restart-from-current-level, restart-from-zero, phase reset, and what
the ladder's state does at note-on are design decisions for a decision record
(17.1). Until then the only checkable behaviour is a single note from reset.

---

## 9. Amplitude

Step 5 of 4.2 (`VoiceFx.run`):

```
x = (mixed · ae) >> 15          ae = level_amp >> 9, 0..32767
```

`mixed` is −32768..32767, so `x` is −32767..32766 and cannot overflow. This is
the ladder's input. The amplitude envelope is applied **before** the filter.

---

## 10. Cutoff and the g ROM

Step 6 of 4.2:

```
span = cut_hi − cut_lo                                 exact, signed
cut  = cut_lo + ((span · fe) >> 15) + track_hz          fe = level_filt >> 9; exact sum
cut  = clamp(cut, 30, 21600)                            integer Hz, 15 bits
```

`span` may be negative (a patch with `cut_hi < cut_lo` is legal), in which
case the shift floors toward −∞. The sum MUST be computed exactly before the
clamp whatever the register widths of 5.1. `21600 = 0.45 × 48000`, the float
model's clamp.

The coefficient (`voice_fx.g_from_cut`, `GROM_BITS = 7`):

```
i    = cut >> 8                        0..84
frac = cut & 255
g    = G_ROM128[i] + (( (G_ROM128[i+1] − G_ROM128[i]) · frac ) >> 8)       Q0.16
```

**Appendix D is normative**: `G_ROM128[i] = round((1 − exp(−2π · 256i / 96000))
· 65536)`, i = 0..128, sampled at bin **edges** because it is interpolated;
`96000` is the ladder's oversampled rate. The table is strictly increasing
(every delta is 129..1089), so the product is non-negative and the shift is a
logical one.
`g(30) = 127`, `g(21600) = 49594`; entries above index 85 are never read.
Against the exact coefficient the ROM is within 4 LSB everywhere and within
1 % relative above 100 Hz (`test_cutoff_rom_tracks_the_float_coefficient`).
Example: `cut = 515` gives `i = 2`, `frac = 3`, `g = 2160 + ((3213 − 2160) · 3
>> 8) = 2172`.

`g` is held for both oversampling passes of the frame.

---

## 11. The ladder filter

Huovilainen, DAFx-04, "Non-Linear Digital Implementation of the Moog Ladder
Filter" — the nonlinear model, not the linearised one (DR 0001). The
nonlinearity is in every stage; the paper's equation (17) reuse gives five
`tanh` per pass rather than eight; the feedback carries a half-sample delay as
the average of the last two outputs; the whole filter runs at 2× the frame
rate. Anyone reimplementing this MUST NOT simplify to a single feedback-path
`tanh`; that is a different filter.

### 11.1 Normalisation (informative)

The paper's stage is `y += 2·Vt·g·(tanh(x/2Vt) − tanh(y/2Vt))`. The model
holds the state in units of 2·Vt, so the stage becomes `Y += g·(tanh(X) −
tanh(Y))`: the tanh argument **is** the state, the table is indexed by it, and
the 2·Vt multiply is gone. `2·Vt = 0.05` and the audio-to-volts scale `0.13`
(`volts_per_unit`) survive only in the two host constants `gain` and `ogain`
of 5.5.

### 11.2 Formats and state

| | format | width |
|---|---|---|
| input `x` | Q1.15 signed | 16 |
| state `y[0..3]`, `d1`, `d2` | Q4.20 signed, units of 2·Vt; ±8.0 | 24 |
| stored tanh `w[0..3]` | Q1.15 signed, −32767..32767 | 16 |
| `g` | Q0.16 unsigned; up to 61659 at a 43.2 kHz cutoff, 49594 at this block's clamp — bit 15 is data | 16 |
| `k` | Q3.14 unsigned; `res = 1.0` is exactly 65536 | 17 |
| `gain`, `ogain` | Q4.16 unsigned | 20 |
| output `y_out` | Q1.15 signed, saturated | 16 |

`TQ = 5` is the shift from Q1.15 to the state's 20 fraction bits. All state is
0 at reset. The ±8.0 state clamp (`sat24`) is part of the arithmetic and MUST
be implemented, although it has been shown never to fire: once |y| ≥ 4.0 the
stage's own tanh is pinned and the state turns back, peaking near 4.0 + 2g
(README, "Verifying the RTL").

### 11.3 tanh from the 16-entry table

`TANH16` (Appendix C, normative): `round(tanh(i/16 · 4.0) · 32767)`, i =
0..15, edge-sampled over [0, 4). For a 24-bit state value `v`
(`LadderFx.tanh_fx` with `N = 16`, `dom_fx = 4 << 20 = 4194304`):

```
neg = v < 0
a   = |v|                                     0..2^23 (|−2^23| = 2^23 is representable as unsigned)
if a ≥ 4194304:                               |v| ≥ 4.0
    t = 32767
else:
    idx  = a >> 18                            0..15   (a · 16 / 2^22)
    fr   = a & 0x3FFFF                        18-bit fraction within the bin
    t0   = TANH16[idx]
    t1   = TANH16[idx + 1]   if idx < 15, else 32767
    t    = t0 + (((t1 − t0) · fr) >> 18)
tanh(v) = −t if neg else t
```

The top word 32767 is **not** tanh(4.0) (which would round to 32745): the last
bin interpolates up to the clamp so the curve meets it with no step. An
implementation that uses tanh(4.0) there differs from the model by up to 22
LSB across the top bin. `tanh(±1) = 0` (the first bin's slope is 8025/2^18 per
LSB), `tanh(262144) = 8025`, `tanh(4194303) = 32766`.

*Informative:* values sit at bin edges because the table is interpolated;
midpoint values (right for nearest-entry reading) would put a half-bin skew on
every lookup, which measured 8 dB worse and read as "interpolation made it
worse" (`test_interpolated_beats_nearest_at_the_same_size`). 16 interpolated
entries score identically to 256 on every patch (`test_small_table_is_enough`);
the 256-entry alternative is not part of this contract.

### 11.4 Per-frame algorithm

Step 7 of 4.2, for frame input `x` and this frame's `g`, `k`, `gain`, `ogain`
(`LadderFx.process`). Two passes; each pass advances every state register once.

```
xg = (x · gain) >> 11                     exact 36-bit product; the same for both passes

for pass in 0, 1:
    fb  = (d1 + d2) >> 1                  half-sample delay: mean of the last two outputs, 25-bit sum, arithmetic shift
    u   = sat24( xg − ((k · fb) >> 14) )  input stage, state units
    w0  = tanh(u)                         11.3
    for s in 0, 1, 2, 3:                  IN ORDER; stage s uses the w[s−1] just written in this pass
        prev = w0 if s = 0 else w[s−1]
        diff = prev − w[s]                −65534..65534
        y[s] = sat24( y[s] + ((g · (diff << 5)) >> 16) )
        w[s] = tanh(y[s])
    d2 ← d1 ; d1 ← y[3]

y_out = sat16( ((y[3] >> 5) · ogain) >> 16 )     from the state after pass 1
```

Every shift is arithmetic. Product widths: `x·gain` 36 bits, `k·fb` 41,
`g·(diff<<5)` 38, `(y[3]>>5)·ogain` 39; every pre-saturation value is under
2^27 in magnitude (`ladder_dp.v`, `AW = 28`). The sequence of operations is
the model's; an implementation that reorders the four stages, uses the
previous pass's `w[s−1]`, computes `fb` once per frame, or averages
differently is not this filter (the injected defect `INJECT_BUG_LADDER_FB`,
a unit delay in place of the average, mismatches 23 377 of 28 800 samples).

### 11.5 Coefficients (informative)

`k`, `gain`, `ogain` are registers; the host derives them by 5.5 from `res`
and `drive`. The measured behaviour they give: self-oscillation tracks the
cutoff within ±2 % from 200 Hz to 1.6 kHz at `res` ≈ 1.08 and is **not**
sustained above about 3 kHz at fixed `k` — the paper's own caveat that the
required feedback varies with frequency. The compensation ROM that would fix
that is not designed and is not part of this contract (17.5). `ogain`'s
`(1 + 2·res)` term is a partial passband-loss compensation.

### 11.6 Where the ladder saturates

Three clamps, all part of the arithmetic: `u` to 24 bits (input stage), each
`y[s]` to 24 bits (never reached in practice, 11.2), and `y_out` to 16 bits.
The last is where the voice's loud patches clip — section 12.

---

## 12. Output gain and the saturation points

Step 8 of 4.2:

```
sample = (y_out · 29491) >> 15          y_out −32768..32767  →  sample −29491..+29490
```

`29491 = round(0.9 · 32768)`, `engines.mono_note`'s master gain. No
saturation is needed here; the range is by construction. A full-scale ladder
output therefore appears at −0.92 dBFS.

**Saturation is designed, not accidental.** Four of the eight audition patches
exceed full scale in float — `growl-bass` peaks at 1.99× and clips 8.7 % of
its samples, the two bass patches at 1.22× — and the float renderer hides
that by normalising afterwards (DESIGN.md section 4, README "Two things fixed
point caught"). In this contract the signal path has exactly these clamps, in
signal order, and no others:

| # | where | clamp | section |
|---|---|---|---|
| 1 | each oscillator, after PolyBLEP | `sat16` | 6.6.4 |
| 2 | mixer sum | `sat16` | 7 |
| 3 | ladder input stage `u` | `sat24` (state units, ±8.0) | 11.4 |
| 4 | ladder state `y[s]` after each integrator | `sat24` | 11.4 |
| 5 | ladder output | `sat16` | 11.4 |

The amplitude multiply (9), the cutoff shift (10, before its clamp to Hz), the
tanh interpolation and the output gain cannot overflow and have no clamp.
Clamp 5 is where the loud patches clip and the whole 13 dB gap on `growl-bass`
between float and fixed lives there; no precision change moves it. Whether a
gain stage belongs between clamp 5 and the output, or the host manages
headroom through `gain`, `w[k]` and the envelopes, is a gain-staging decision
left OPEN (17.6). The harness's summation of overlapping notes
(`render_mono_fx`, `sat16`) is not in this list because it is not the voice's
(5.3).

---

## 13. Output format: I2S

The block's audio leaves as I2S (DESIGN.md section 7; the 1-bit modulator
discussed there is a debug pad, not the output, and is not specified here).
The convention below is the one gf180-polysynth's `fpga/i2s_tx.v` implements
and `fpga/tb_i2s.v` decodes as a PCM5102A does; it is adopted unchanged so
the two blocks are interchangeable at the DAC. No transmitter exists in this
repository yet; this section is what one MUST do.

- **Clocks.** `BCLK = 12.288 MHz / 4 = 3.072 MHz = 64 × fs`. `LRCLK = 12.288
  MHz / 256 = 48 kHz`; one LRCLK period is 256 core cycles, the same length
  as a frame. Both are integer divisions of the core clock; no PLL.
- **Slots.** 32 BCLKs per channel: LRCLK **low = left**, high = right.
- **Word.** The 16-bit sample, MSB first, **left-justified** in the 32-bit
  slot; the remaining 16 bits of the slot are zero. Standard I2S timing: the
  MSB is on the **second** BCLK after the LRCLK edge (one BCLK of delay), and
  SDATA changes on the falling edge of BCLK so a receiver samples it on the
  rising edge. (The prototype defect that put the MSB one BCLK late made
  every negative sample decode positive; `tb_i2s.v` catches it.)
- **Mono.** Both channels carry the **same** sample in one LRCLK period.
- **Which sample lands in which period.** Sample f is transmitted in LRCLK
  period `f + D` for a constant `D ≥ 1` fixed by the implementation, with
  every sample sent exactly once, in order: no sample is skipped or repeated,
  and left and right of one period are never different samples. `D` is a
  latency, not part of the sample sequence, and an implementation MUST state
  it. *Informative:* the sibling latches the core's sample when it is strobed
  and loads it at the last BCLK of the right slot preceding the next period,
  so `D = 1` when the strobe precedes that load.

The DAC side (PCM5102A with SCK tied low, MAX98357A, or a TLV320DAC3100) is
board material and outside the contract.

---

## 14. Reset and initial state

On hardware reset, and on RESET, every register takes the value below. There
is no other observable state.

| Register | Reset | Notes |
|---|---|---|
| `phase[k]`, `inc[k]`, `e[k]`, `r[k]` | 0 | `inc = 0` gives `c = 0` by 6.6.3; `(e, r)` are recomputed at the first SET_INC |
| `wave[k]`, `w[k]` | 0 | encoding of `wave` OPEN |
| `level`, `seg` (both envelopes) | 0, ATTACK | |
| `gate` | 0 | |
| `a_inc`, `d_dec`, `sus`, `rate` (both) | 0 | |
| `cut_lo`, `cut_hi`, `track_hz` | 0 | the clamp makes the cutoff 30 Hz |
| `k`, `gain`, `ogain` | 0 | |
| ladder `y[0..3]`, `w[0..3]`, `d1`, `d2` | 0 | `LadderFx.reset()` |
| output sample register | 0 | |
| control parser / queue | idle, empty | |

Consequences: from reset the voice outputs 0 every frame until programmed —
the envelope holds at 0 by the release branch, so `x = 0`, and a zero-state
ladder with zero input stays at zero. All-zero control is the model's reset
of *state*; the model has no reset values for *control* because `note_on`
always writes the whole image. **Non-zero power-on defaults (so that a
GATE_ON alone sounds, as in gf180-polysynth section 9) are OPEN (17.8)** and
belong with the physical-layer decision, since an SPI time-slice host rewrites
the whole image every slice and needs none.

---

## 15. Modal resonator bank — PROPOSED, not part of the rev-1 voice

`model/modal_fixed.py` (`ModalFx`) and `rtl-sketch/modal_dp.v` are bit-exact
against each other and their sizing is **proposed, not ratified** (the model
says so in its own docstring). This section records what they compute so the
proposal is citeable; it is **informative in revision 1**. How the bank is
triggered, what excites it (the model's strike is a float Hann-windowed noise
burst quantised to Q1.15), how it is mixed with the voice, and its gain
staging are all OPEN (17.4).

Four two-pole resonators, each `y[n] = x[n] + a1·y[n−1] + a2·y[n−2]` with
`a1 = 2r·cos ω`, `a2 = −r²`, no delay line and no RAM. Proposed formats:
coefficients Q2.24 signed (26 bits — Q2.16 cannot tune a low bar: 2.4 %,
41 cents off at MIDI 28), `amp` Q0.16, state 28 bits with 15 fraction bits,
excitation entering as `exc << 0`, and 10 headroom bits on the output because
the bank rings to 657× the strike at note 28. Per sample:

```
e = exc                                        SQ = 15, so no shift
for each mode m:
    acc  = a1_m · y1_m + a2_m · y2_m           exact, no rounding constant (measured to buy nothing)
    y    = sat28( (acc >> 24) + e )            shift, then clamp
    y2_m ← y1_m ; y1_m ← y
    mix += (y · amp_m) >> 16
out = sat16( mix >> 10 )
```

A mode whose frequency exceeds 0.45·fs has `(a1, a2, amp) = (0, 0, 0)`. The
host derives the coefficients in float (`ModalFx.coefficients`), as for the
voice. The sizing evidence is `python3 model/modal_fixed.py`.

---

## 16. Verification obligations

For an implementation to be checked against the model it MUST expose, in
simulation:

1. **The sample stream**: a 16-bit signed output with a one-cycle valid
   strobe asserted exactly once per frame; the f-th strobe after reset carries
   sample f.
2. **The control input** at the register level, bypassing the physical layer,
   so a test bench controls exactly which frame each write completes in (4.3).
3. **The frame tick**.
4. Recommended taps, matching `VoiceFx.trace`: each `osc_k`, `mixed`, `ae`,
   `fe`, `cut`, and the ladder's `y_out` before the output gain. The ladder
   alone is checkable through `rtl-sketch/verify_ladder.py`'s vector format
   (`x, g, k, gain, ogain` in, `y_out` out), which drives 28 800 samples that
   reach every clamp and both coefficient MSBs.

A test compares the implementation's sample f with the model's for every f,
for a scripted sequence of (frame, write) deliveries. Any mismatch is a
failure; there is no tolerance. In this revision the reference sequences are
single notes from reset (5.3) — `VoiceFx().note(note, dur, **patch)` — and
the eight audition patches of `audition/patches.py::MONO` rendered note by
note. A bench MUST also be shown to fail: the injected defects of
`rtl-sketch/ladder_dp.v` (`INJECT_BUG_LADDER_FB`, `_SAT`, `_TANH_CLAMP`) are
the pattern.

Table freshness: `spec/reference/gen_tables.py --check` MUST pass; it fails
if any hash in the appendices, any image under `spec/reference/tables/`, or
`rtl-sketch/tanh16.hex` is not what the model generates.

---

## 17. Open items

Everything this revision does not decide, in one place. Each needs a decision
record that extends this document; none may be resolved by picking a reading.

1. **Note-on retrigger semantics** (8.5): legato, envelope restart policy,
   phase reset, ladder state at note-on. The model renders every note from
   reset.
2. **Glide** (6.7): the float model glides geometrically, the integer model
   slews linearly over a constant 4320 frames; on-chip or host-driven; time
   constant or register.
3. **Physical control layer** (5.4): UART event stream vs SPI time-slice
   packets (gf180-polysynth issue 7); with it, the encodings of `wave[k]` and
   every opcode or field. A placeholder encoding, for discussion only: saw 0,
   square 1, pulse25 2, tri 3, sine 4.
4. **Modal bank** (15): sizing proposed, not ratified; trigger, excitation
   source, mixing and gain staging unspecified.
5. **Resonance compensation above ~3 kHz** (11.5): the compensation ROM is
   not designed.
6. **Output gain staging** (12): the ladder's 16-bit clamp is where loud
   patches clip; whether a designed output stage or host headroom management
   is the answer.
7. **Register-width clamps in the host conversion** (5.5): `a_inc = 2^24`
   and `rate = 65536` are producible by the model's conversions and do not fit
   the registers of 5.1; the model should clamp.
8. **Power-on control defaults** (14).
9. **`inc = 0`** (6.3): the model raises; the contract's `c = 0` is derived
   from 6.6.3, not model-checked.
10. **Widths of `cut_lo`, `cut_hi`, `track_hz`** (5.1): 16 bits is proposed
    from the audition patches, not measured against anything.
11. **Ratification itself.** This document is proposed. Ratification is the
    two-key act this fleet uses and is not claimed here.

---

## 18. Revision history

- **Rev 1 (2026-09-17)** — initial proposal, written from `model/voice_fx.py`
  and `model/fixed.py` as committed; appendices generated by
  `spec/reference/gen_tables.py`. Not ratified.

---

<!-- BEGIN GENERATED APPENDICES -->

### Appendix A -- NOTE_INC: MIDI note number -> 24-bit phase increment

Normative. `NOTE_INC[n] = round(440 * 2^((n-69)/12) * 2^24 / 48000)`, evaluated by `dsp.phase_inc(dsp.note_hz(n))`. Nominal frequency for reference only. Two notes per row.

| note | inc (dec) | inc (hex) | nominal Hz | | note | inc (dec) | inc (hex) | nominal Hz |
|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 0 | 2858 | 0x000B2A | 8.176 | | 64 | 115213 | 0x01C20D | 329.628 |
| 1 | 3028 | 0x000BD4 | 8.662 | | 65 | 122064 | 0x01DCD0 | 349.228 |
| 2 | 3208 | 0x000C88 | 9.177 | | 66 | 129322 | 0x01F92A | 369.994 |
| 3 | 3398 | 0x000D46 | 9.723 | | 67 | 137012 | 0x021734 | 391.995 |
| 4 | 3600 | 0x000E10 | 10.301 | | 68 | 145160 | 0x023708 | 415.305 |
| 5 | 3815 | 0x000EE7 | 10.913 | | 69 | 153791 | 0x0258BF | 440.000 |
| 6 | 4041 | 0x000FC9 | 11.562 | | 70 | 162936 | 0x027C78 | 466.164 |
| 7 | 4282 | 0x0010BA | 12.250 | | 71 | 172625 | 0x02A251 | 493.883 |
| 8 | 4536 | 0x0011B8 | 12.978 | | 72 | 182890 | 0x02CA6A | 523.251 |
| 9 | 4806 | 0x0012C6 | 13.750 | | 73 | 193765 | 0x02F4E5 | 554.365 |
| 10 | 5092 | 0x0013E4 | 14.568 | | 74 | 205287 | 0x0321E7 | 587.330 |
| 11 | 5395 | 0x001513 | 15.434 | | 75 | 217494 | 0x035196 | 622.254 |
| 12 | 5715 | 0x001653 | 16.352 | | 76 | 230426 | 0x03841A | 659.255 |
| 13 | 6055 | 0x0017A7 | 17.324 | | 77 | 244128 | 0x03B9A0 | 698.456 |
| 14 | 6415 | 0x00190F | 18.354 | | 78 | 258645 | 0x03F255 | 739.989 |
| 15 | 6797 | 0x001A8D | 19.445 | | 79 | 274025 | 0x042E69 | 783.991 |
| 16 | 7201 | 0x001C21 | 20.602 | | 80 | 290319 | 0x046E0F | 830.609 |
| 17 | 7629 | 0x001DCD | 21.827 | | 81 | 307582 | 0x04B17E | 880.000 |
| 18 | 8083 | 0x001F93 | 23.125 | | 82 | 325872 | 0x04F8F0 | 932.328 |
| 19 | 8563 | 0x002173 | 24.500 | | 83 | 345249 | 0x0544A1 | 987.767 |
| 20 | 9072 | 0x002370 | 25.957 | | 84 | 365779 | 0x0594D3 | 1046.502 |
| 21 | 9612 | 0x00258C | 27.500 | | 85 | 387529 | 0x05E9C9 | 1108.731 |
| 22 | 10184 | 0x0027C8 | 29.135 | | 86 | 410573 | 0x0643CD | 1174.659 |
| 23 | 10789 | 0x002A25 | 30.868 | | 87 | 434987 | 0x06A32B | 1244.508 |
| 24 | 11431 | 0x002CA7 | 32.703 | | 88 | 460853 | 0x070835 | 1318.510 |
| 25 | 12110 | 0x002F4E | 34.648 | | 89 | 488256 | 0x077340 | 1396.913 |
| 26 | 12830 | 0x00321E | 36.708 | | 90 | 517290 | 0x07E4AA | 1479.978 |
| 27 | 13593 | 0x003519 | 38.891 | | 91 | 548049 | 0x085CD1 | 1567.982 |
| 28 | 14402 | 0x003842 | 41.203 | | 92 | 580638 | 0x08DC1E | 1661.219 |
| 29 | 15258 | 0x003B9A | 43.654 | | 93 | 615165 | 0x0962FD | 1760.000 |
| 30 | 16165 | 0x003F25 | 46.249 | | 94 | 651744 | 0x09F1E0 | 1864.655 |
| 31 | 17127 | 0x0042E7 | 48.999 | | 95 | 690499 | 0x0A8943 | 1975.533 |
| 32 | 18145 | 0x0046E1 | 51.913 | | 96 | 731558 | 0x0B29A6 | 2093.005 |
| 33 | 19224 | 0x004B18 | 55.000 | | 97 | 775059 | 0x0BD393 | 2217.461 |
| 34 | 20367 | 0x004F8F | 58.270 | | 98 | 821146 | 0x0C879A | 2349.318 |
| 35 | 21578 | 0x00544A | 61.735 | | 99 | 869974 | 0x0D4656 | 2489.016 |
| 36 | 22861 | 0x00594D | 65.406 | | 100 | 921705 | 0x0E1069 | 2637.020 |
| 37 | 24221 | 0x005E9D | 69.296 | | 101 | 976513 | 0x0EE681 | 2793.826 |
| 38 | 25661 | 0x00643D | 73.416 | | 102 | 1034579 | 0x0FC953 | 2959.955 |
| 39 | 27187 | 0x006A33 | 77.782 | | 103 | 1096099 | 0x10B9A3 | 3135.963 |
| 40 | 28803 | 0x007083 | 82.407 | | 104 | 1161276 | 0x11B83C | 3322.438 |
| 41 | 30516 | 0x007734 | 87.307 | | 105 | 1230329 | 0x12C5F9 | 3520.000 |
| 42 | 32331 | 0x007E4B | 92.499 | | 106 | 1303488 | 0x13E3C0 | 3729.310 |
| 43 | 34253 | 0x0085CD | 97.999 | | 107 | 1380998 | 0x151286 | 3951.066 |
| 44 | 36290 | 0x008DC2 | 103.826 | | 108 | 1463116 | 0x16534C | 4186.009 |
| 45 | 38448 | 0x009630 | 110.000 | | 109 | 1550118 | 0x17A726 | 4434.922 |
| 46 | 40734 | 0x009F1E | 116.541 | | 110 | 1642292 | 0x190F34 | 4698.636 |
| 47 | 43156 | 0x00A894 | 123.471 | | 111 | 1739948 | 0x1A8CAC | 4978.032 |
| 48 | 45722 | 0x00B29A | 130.813 | | 112 | 1843411 | 0x1C20D3 | 5274.041 |
| 49 | 48441 | 0x00BD39 | 138.591 | | 113 | 1953026 | 0x1DCD02 | 5587.652 |
| 50 | 51322 | 0x00C87A | 146.832 | | 114 | 2069159 | 0x1F92A7 | 5919.911 |
| 51 | 54373 | 0x00D465 | 155.563 | | 115 | 2192197 | 0x217345 | 6271.927 |
| 52 | 57607 | 0x00E107 | 164.814 | | 116 | 2322552 | 0x237078 | 6644.875 |
| 53 | 61032 | 0x00EE68 | 174.614 | | 117 | 2460658 | 0x258BF2 | 7040.000 |
| 54 | 64661 | 0x00FC95 | 184.997 | | 118 | 2606977 | 0x27C781 | 7458.620 |
| 55 | 68506 | 0x010B9A | 195.998 | | 119 | 2761996 | 0x2A250C | 7902.133 |
| 56 | 72580 | 0x011B84 | 207.652 | | 120 | 2926232 | 0x2CA698 | 8372.018 |
| 57 | 76896 | 0x012C60 | 220.000 | | 121 | 3100235 | 0x2F4E4B | 8869.844 |
| 58 | 81468 | 0x013E3C | 233.082 | | 122 | 3284585 | 0x321E69 | 9397.273 |
| 59 | 86312 | 0x015128 | 246.942 | | 123 | 3479896 | 0x351958 | 9956.063 |
| 60 | 91445 | 0x016535 | 261.626 | | 124 | 3686822 | 0x3841A6 | 10548.082 |
| 61 | 96882 | 0x017A72 | 277.183 | | 125 | 3906052 | 0x3B9A04 | 11175.303 |
| 62 | 102643 | 0x0190F3 | 293.665 | | 126 | 4138318 | 0x3F254E | 11839.822 |
| 63 | 108747 | 0x01A8CB | 311.127 | | 127 | 4384395 | 0x42E68B | 12543.854 |

SHA-256 of the 128 decimal values joined by commas (no spaces): `e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4`

### Appendix B -- SINE_Q256: quarter-wave sine table, i = 0..255

Normative. `SINE_Q256[i] = round(32767 * sin(pi/2 * (i + 0.5) / 256))` -- MIDPOINT sampled, 256 entries, no interpolation (`dsp._QUARTER`). The full 1024-entry table is derived by the symmetry rules in section 6.5. Eight entries per row; the first column is the index of the first entry in the row.

| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 101 | 302 | 503 | 704 | 905 | 1106 | 1307 | 1507 |
| 8 | 1708 | 1909 | 2110 | 2310 | 2511 | 2711 | 2911 | 3112 |
| 16 | 3312 | 3512 | 3712 | 3911 | 4111 | 4310 | 4509 | 4708 |
| 24 | 4907 | 5106 | 5305 | 5503 | 5701 | 5899 | 6096 | 6294 |
| 32 | 6491 | 6688 | 6885 | 7081 | 7277 | 7473 | 7669 | 7864 |
| 40 | 8059 | 8254 | 8448 | 8642 | 8836 | 9030 | 9223 | 9416 |
| 48 | 9608 | 9800 | 9992 | 10183 | 10374 | 10564 | 10754 | 10944 |
| 56 | 11133 | 11322 | 11511 | 11699 | 11886 | 12074 | 12260 | 12446 |
| 64 | 12632 | 12817 | 13002 | 13187 | 13370 | 13554 | 13736 | 13919 |
| 72 | 14101 | 14282 | 14462 | 14643 | 14822 | 15001 | 15180 | 15358 |
| 80 | 15535 | 15712 | 15888 | 16063 | 16238 | 16413 | 16586 | 16759 |
| 88 | 16932 | 17104 | 17275 | 17445 | 17615 | 17784 | 17953 | 18121 |
| 96 | 18288 | 18454 | 18620 | 18785 | 18950 | 19113 | 19276 | 19438 |
| 104 | 19600 | 19761 | 19921 | 20080 | 20238 | 20396 | 20553 | 20709 |
| 112 | 20865 | 21019 | 21173 | 21326 | 21479 | 21630 | 21781 | 21930 |
| 120 | 22079 | 22227 | 22375 | 22521 | 22667 | 22812 | 22956 | 23099 |
| 128 | 23241 | 23382 | 23522 | 23662 | 23801 | 23938 | 24075 | 24211 |
| 136 | 24346 | 24480 | 24613 | 24746 | 24877 | 25007 | 25137 | 25265 |
| 144 | 25393 | 25519 | 25645 | 25770 | 25893 | 26016 | 26138 | 26259 |
| 152 | 26378 | 26497 | 26615 | 26732 | 26848 | 26962 | 27076 | 27189 |
| 160 | 27300 | 27411 | 27521 | 27629 | 27737 | 27843 | 27949 | 28053 |
| 168 | 28157 | 28259 | 28360 | 28460 | 28560 | 28658 | 28755 | 28850 |
| 176 | 28945 | 29039 | 29131 | 29223 | 29313 | 29403 | 29491 | 29578 |
| 184 | 29664 | 29749 | 29832 | 29915 | 29997 | 30077 | 30156 | 30234 |
| 192 | 30311 | 30387 | 30462 | 30535 | 30607 | 30679 | 30749 | 30818 |
| 200 | 30885 | 30952 | 31017 | 31082 | 31145 | 31206 | 31267 | 31327 |
| 208 | 31385 | 31442 | 31498 | 31553 | 31607 | 31659 | 31710 | 31760 |
| 216 | 31809 | 31857 | 31903 | 31949 | 31993 | 32036 | 32077 | 32118 |
| 224 | 32157 | 32195 | 32232 | 32267 | 32302 | 32335 | 32367 | 32397 |
| 232 | 32427 | 32455 | 32482 | 32508 | 32533 | 32556 | 32578 | 32599 |
| 240 | 32619 | 32637 | 32655 | 32671 | 32685 | 32699 | 32711 | 32722 |
| 248 | 32732 | 32741 | 32748 | 32755 | 32759 | 32763 | 32766 | 32767 |

SHA-256 of the 256 decimal values joined by commas: `66cfc2e50e0ea6c326d698bd2aa14cc8b67f8e518530c9bb9c3f8f62d0fd19a0`  
SHA-256 of the derived 1024-entry full table (`voice_fx.sine_fx` at phases `i << 14`), same encoding: `41a30c959df1413245a6817c2d398c9d571f33460b34634b433c0717fb3c52ea`

### Appendix C -- TANH16: the ladder's tanh table, i = 0..15

Normative. `TANH16[i] = round(tanh(i / 16 * 4.0) * 32767)` -- EDGE sampled over [0, 4), Q1.15, read with linear interpolation (section 11.3). The interpolation's top word, used above entry 15, is 32767 and is NOT tanh(4.0) (which would round to 32745).

| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 8025 | 15142 | 20812 | 24955 | 27796 | 29659 | 30846 |
| 8 | 31588 | 32047 | 32328 | 32500 | 32605 | 32669 | 32707 | 32731 |

SHA-256 of the 16 decimal values joined by commas: `65a5fa4b38b807735e09eed0eadd49b2a42850151daa47e3abb97a1641542c04`  
SHA-256 of the 17-word ROM image (`TANH16` followed by 32767), which is exactly `rtl-sketch/tanh16.hex`: `3aa73628ec4f1b6eec99e77524a5460813c531dd9703a8fdea6df799dc91efeb`

### Appendix D -- G_ROM128: cutoff (Hz) -> ladder coefficient g, i = 0..128

Normative. `G_ROM128[i] = clip(round((1 - exp(-2*pi * (256*i) / 96000)) * 65536), 0, 65535)` -- EDGE sampled every 256 Hz at the ladder's 2x-oversampled rate, Q0.16, 128 entries plus entry 128 as the interpolation guard (`voice_fx.make_g_rom`). Entries 0..85 are reachable through the cutoff clamp of section 10; entries 86..128 are part of the table but never read. Eight entries per row.

| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 1089 | 2160 | 3213 | 4248 | 5267 | 6268 | 7253 |
| 8 | 8221 | 9174 | 10110 | 11031 | 11937 | 12827 | 13703 | 14564 |
| 16 | 15411 | 16244 | 17063 | 17868 | 18660 | 19439 | 20205 | 20958 |
| 24 | 21699 | 22427 | 23144 | 23848 | 24541 | 25222 | 25892 | 26551 |
| 32 | 27198 | 27835 | 28462 | 29078 | 29683 | 30279 | 30865 | 31441 |
| 40 | 32008 | 32565 | 33113 | 33651 | 34181 | 34702 | 35214 | 35718 |
| 48 | 36214 | 36701 | 37180 | 37651 | 38114 | 38570 | 39018 | 39459 |
| 56 | 39892 | 40318 | 40737 | 41149 | 41554 | 41953 | 42345 | 42730 |
| 64 | 43109 | 43482 | 43848 | 44208 | 44563 | 44911 | 45254 | 45591 |
| 72 | 45922 | 46248 | 46569 | 46884 | 47194 | 47499 | 47798 | 48093 |
| 80 | 48383 | 48668 | 48948 | 49224 | 49495 | 49761 | 50023 | 50281 |
| 88 | 50535 | 50784 | 51029 | 51270 | 51507 | 51740 | 51969 | 52195 |
| 96 | 52416 | 52634 | 52849 | 53060 | 53267 | 53471 | 53671 | 53868 |
| 104 | 54062 | 54253 | 54440 | 54625 | 54806 | 54984 | 55160 | 55332 |
| 112 | 55502 | 55668 | 55832 | 55993 | 56152 | 56308 | 56461 | 56612 |
| 120 | 56760 | 56906 | 57050 | 57191 | 57329 | 57466 | 57600 | 57732 |
| 128 | 57861 |  |  |  |  |  |  |  |

SHA-256 of the 129 decimal values joined by commas: `c5ee86efeffbe3cadd040ca3851b5c90806f05f9fab13d5f3cea1cf7730fbe2a`

<!-- END GENERATED APPENDICES -->
