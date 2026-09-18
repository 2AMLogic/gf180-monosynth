# Monosynth Voice — Numeric Contract

**Revision 4 — 2026-09-17 — status: PROPOSED. Not ratified.**

This document is a proposal for the complete, bit-exact specification of the
gf180-monosynth voice: three band-limited oscillators with an on-chip glide, a
saturating mixer, Huovilainen's nonlinear ladder with a resonance-compensation
ROM, two integer ADSRs and a VCA, producing one signed 16-bit sample per
frame. It is written from the committed reference model and claims
nothing the model does not do. It becomes the specification RTL is verified
against only when ratified through the two-key process this fleet uses; until
then it is revision 4, proposed, and the status line above must not be read as
anything else (the rule is gf180-drone-fc DR-0005's: the status field must not
claim ratification before that act has happened).

**The model wins.** The normative text below is derived from these files, at
the commit this revision was written against, and where prose and code could be
read differently the code is what "bit-exact" means:

| file | what it is the specification of |
|---|---|
| `model/voice_fx.py` | the voice: oscillators, glide, PolyBLEP, mixer, envelopes, cutoff path, resonance compensation, VCA and output (sections 6–10, 12); `KeyHost`, the reference host (5.6, informative) |
| `model/fixed.py` | `LadderFx`, the ladder filter (section 11) |
| `audition/dsp.py` | the tables the voice imports: `phase_inc`, `note_hz`, `_QUARTER` (Appendices A, B) |
| `model/modal_fixed.py` | the modal resonator bank — **proposed sizing, not ratified** (section 15) |

Their tests (`model/test_voice_fx.py`, `model/test_fixed.py`,
`model/test_modal_fixed.py`, `spec/reference/test_tables.py`, 68 tests) lock the sizing decisions; the RTL
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

A monophonic — or, with a host that assigns held keys to oscillators, a
three-voice paraphonic — subtractive voice. Three phase-accumulator
oscillators, each with an on-chip glide and a PolyBLEP correction on its
discontinuous shapes, are mixed with saturation, filtered by a four-pole
nonlinear ladder whose cutoff is driven by a second envelope plus keyboard
tracking and whose resonance is compensated by cutoff, scaled by an amplitude
envelope, then by a host volume. A host writes the voice's control registers
over a serial link (SPI register writes, section 5.4, DR 0007); the host owns
all musical time. One sample leaves per frame, as I2S.

```
                 control image (section 5), applied at frame boundaries
                          │
   ┌──────────────────────┼─────────────────────────────────────────────────┐
   │ osc 0: glide ─► phase acc ─► wave ─► PolyBLEP ─► ×w0 ─┐                                      │
   │ osc 1:   "          "           "         "      ×w1 ─┼─► Σ ─► sat16 ─► ladder ─► sat19 ─► × amp env ─► × vol ─► sat16 ─► s16
   │ osc 2:   "          "           "         "      ×w2 ─┘   (mixer)     (§10,11)      (§8,9)         (§12)
   │                                cutoff = clamp(lo + span·filt env + track) ─► g ROM, kc ROM ─┘      │
   └──────────────────────────────────────────────────────────────────────────┘
```

The block's observable behaviour is exactly two things: the sequence of output
samples, and how that sequence depends on the sequence of control writes and
the frames in which they arrived. Everything below defines those two things.

The order of the chain is the Minimoog's — mixer, filter, VCA, volume — and
not `engines.mono_note`'s as auditioned, which put the amplitude envelope
before the filter (DR 0005): a note ends when its VCA closes whatever the
filter is doing, and the filter is driven at the mixer's level whatever the
envelope.

---

## 2. Fixed numbers

| Quantity | Value |
|---|---|
| Nominal frame rate | 48 000 frames/s (`dsp.SR`) |
| Core clock | 12.288 MHz = 256 × 48 000 |
| Cycles per frame | 256 |
| Output sample | signed 16-bit two's complement, mono, one per frame, saturated (section 12) |
| Oscillators | 3, numbered 0..2 |
| Phase accumulator / increment | 24-bit unsigned per oscillator (`dsp.PHASE_BITS`) |
| Waveform sample | Q1.15, signed 16-bit |
| PolyBLEP mantissa / reciprocal | 16 bits / 16 bits (`MANT_BITS`, `RECIP_BITS`) |
| Mixer weight | Q0.15, 16-bit unsigned register; a weight of 32768 is 1.0 |
| Envelope level | 24-bit unsigned, Q0.24 (`ENV_BITS`) |
| Envelope release rate | Q0.16 (`RATE_Q`) |
| Cutoff | integer Hz, clamped to 30..21600 (`CUT_MIN`, `CUT_MAX`) |
| Cutoff → g ROM | 128 entries + 1 guard, Q0.16, linear interpolation (`GROM_BITS` = 7) |
| Cutoff → kc ROM | 32 entries + 1 guard, unsigned Q1.15, linear interpolation (`KROM_BITS` = 5) — DR 0006 |
| Ladder state | 24-bit signed, 20 fraction bits, in units of 2·Vt (`LADDER_CFG`) |
| Ladder coefficients | g Q0.16 (16 bits); k_eff Q3.14 (17 bits, per frame from `k` and `kc`); gain, ogain Q4.16 (20 bits) |
| Ladder output word | Q4.15 signed, 19 bits, saturated (`LADDER_OUT_BITS`) — DR 0005 |
| Ladder tanh table | 16 entries, edge-sampled, interpolated |
| Ladder oversampling | 2 passes per frame |
| Volume | `vol`, unsigned Q0.15, 16 bits; the reference host writes 14746 = 0.45 (`VOL_REF`) — DR 0005 |
| Tuning | A4 (MIDI note 69) = 440 Hz |
| Glide | `glide`, unsigned Q0.24, 24 bits, the ratio per frame minus 1; increment accumulator Q24.8 (`GLIDE_BITS`, `INC_FRAC`); the reference host writes 2692 = 90 ms per octave (`GLIDE_REF_S`) — DR 0004 |

---

## 3. Arithmetic conventions

1. All signed quantities are two's complement.
2. `x >> k` on a signed value is an **arithmetic** shift: `floor(x / 2^k)`,
   rounding toward −∞. `−1 >> 15 = −1`; `−7123 >> 15 = −1`.
3. `x >> k` on an unsigned value is a logical shift; the result is the same.
4. `x << k` is multiplication by 2^k, computed exactly (widen as needed).
5. Products and sums MUST be computed exactly and then shifted or saturated
   as stated. Nothing in this document truncates an intermediate. Every
   product fits in 64 signed bits; the widest is the glide's 32 × 24 (6.7);
   the ladder's is 24 × 20.
6. Only the phase accumulators wrap (modulo 2^24). Every other addition is
   either provably in range or explicitly saturated. The saturation points are
   listed in section 12.
7. `sat16(v)` clamps to −32768..+32767. `sat24(v)` clamps to −8388608..+8388607
   (`fixed.sat(v, 24)`).
8. `floor(a / b)` for integers is Python's `//`: rounding toward −∞ for a
   negative dividend. No run-time operation of this revision divides; the
   floors at run time are the arithmetic shifts of rule 2 (the glide slew's
   operands are non-negative, 6.7). Division appears only in the note-on
   reciprocal (6.6.1), with a non-negative dividend.
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
   *before* it is advanced, `inc_k = inc_acc_k >> 8`, and the reciprocal
   state `(e_k, r_k)`.
3. **Mixer** (section 7): `mixed = sat16((Σ osc_k · w_k) >> 15)`.
4. **Envelopes** (section 8): `ae = level_amp >> 9`, `fe = level_filt >> 9`,
   both from the levels *before* this frame's update, after a GATE_ON or
   TRIG applied in step 1 has set the segment (8.3).
5. **Cutoff** (section 10): `cut = clamp(cut_lo + ((cut_hi − cut_lo) · fe >> 15) + track_hz, 30, 21600)`;
   `g = G(cut)` and `kc = KC(cut)` from the ROMs; `k_eff = min((k · kc) >> 15, 2^17 − 1)`.
6. **Ladder** (section 11): two oversampling passes on `mixed` with `g,
   k_eff, gain, ogain`, producing `y`, saturated to 19 bits.
7. **Amplitude** (section 9): `v = (y · ae) >> 15`.
8. **Output** (section 12): `sample_f = sat16((v · vol) >> 15)`.
9. **Advance.** For each oscillator `phase_k ← (phase_k + inc_k) mod 2^24`,
   then the glide slew of 6.7 moves `inc_acc_k` toward its target. Each
   envelope's level is updated by the rule of 8.3. The ladder's state was
   already advanced in step 6 (it is recursive; its state after step 6 is the
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
slower. *Informative:* revision 3 adds six multiplies per frame to the front
end — three glide slews, the kc interpolation, `k · kc` and the VCA — all on
a shared multiplier. The whole voice as sequenced in `rtl-sketch/voice_dp.v`
(one multiplier, one divider, the ladder inside) measures 150 cycles in its
worst frame — three reciprocals, three squares, the drum filter of
`docs/ARCHITECTURE.md` on — and 66 in a steady one (`tb_synth_top.v`).

---

## 5. Control interface

This revision specifies the **semantics** of control — which registers exist,
what each does, and when a write takes effect — and, since revision 4, the
physical layer (5.4, DR 0007): an SPI slave carrying one register write per
32-bit transaction, applied at the next frame tick. The product's host (DR
0002) is a microcontroller translating USB-MIDI into those writes.

### 5.1 The control image

The voice's control state is the following registers. "Width" is the register
width an implementation MUST hold; "model" says where the value comes from in
the reference model, whose `VoiceFx.note_on` computes the whole image from a
patch's physical units in float — the one place float is allowed, and in the
product the host's job (5.5).

| Register | Width | Per | Meaning | Model |
|---|---:|---|---|---|
| `inc_tgt[k]` | 24 u | osc | phase-increment target; `inc[k] = inc_acc[k] >> 8` is what the phase accumulator adds (6.7) | `OscFx.inc_tgt` |
| `wave[k]` | 3 | osc | one of saw, square, pulse25, tri, sine (encoding in 5.2) | `waves[k]` |
| `w[k]` | 16 u | osc | mixer weight, Q0.15 | `weights[k]` |
| `a_inc`, `d_dec`, `sus` | 24 u | env ×2 | attack increment, decay decrement, sustain level, Q0.24 | `AdsrFx.a_inc`, `.d_dec`, `.sus` |
| `rate` | 16 u | env ×2 | release rate, Q0.16 | `AdsrFx.rate` |
| `gate` | 1 | voice | envelope gate (both envelopes) | `VoiceFx.gate` |
| `glide` | 24 u | voice | glide rate, Q0.24, the ratio per frame minus 1; 0 = off (6.7) | `VoiceFx.glide` |
| `vol` | 16 u | voice | output volume, Q0.15 (12) | `VoiceFx.vol` |
| `cut_lo`, `cut_hi`, `track_hz` | 16 u | voice | cutoff floor, ceiling and keyboard-tracking offset, integer Hz | `cut_lo`, `cut_hi`, `track_hz` |
| `k` | 17 u | voice | ladder resonance, 4·res in Q3.14, before the compensation of 10.2 | `LadderFx.regs`, `VoiceFx.k_reg` |
| `gain` | 20 u | voice | ladder input gain, drive·2.6 in Q4.16 | same |
| `ogain` | 20 u | voice | ladder output gain, (1+2·res)/2.6 in Q4.16 | same |

The two envelopes are `amp` (section 9) and `filt` (section 10); each has its
own `a_inc`, `d_dec`, `sus`, `rate`.

**Every conversion of 5.5 clamps its result to the width in this table**
(`voice_fx.REG_BITS`, through `fixed.usat`), so the model never holds a value
a register-limited implementation cannot, and the two cannot differ on any
input a host might send. (Rev 2; this was OPEN 17.7. Where each clamp fires
is recorded in 5.5.) Conversely the model accepts every value every register
can hold — `test_every_legal_register_value_runs` walks the extremes of each
through the per-sample path — so a legal write never makes the model raise
or misbehave.

The widths of `cut_lo`, `cut_hi` and `track_hz` are 16 bits unsigned (DR
0007, closing 17.10): derived from the largest value any audition patch
produces (`track_hz` = 45 158 at MIDI note 127 with `track` = 0.9; `cut_hi`
= 7000), from full keyboard tracking (`track` = 1.0 at note 127 gives
50 175) and from the clamp in section 10, past which larger values change
nothing; and fixed by the write format, which carries 16 bits for them. The
sum in section 10 MUST be computed exactly (19 bits signed) before the clamp. `k`, `gain` and
`ogain` are the RTL's port widths, and the RTL is bit-exact against the model
within them; the model clamps to them (`LadderFx.regs`), the ladder runs on
`k_eff`, which 10.2 saturates to `2^17 − 1`, and at every extreme of all three
and of `g` every pre-saturation value in the ladder stays below 2^27, inside
the datapath width of 11.4.

State registers (not host-writable except by RESET): `phase[k]` (24),
`inc_acc[k]` (32, section 6.7), `e[k]` and `r[k]` (section 6.6.1), `level`
and `seg` per envelope (section 8.1), the ladder's `y[0..3]`, `w[0..3]`,
`d1`, `d2` (section 11.2).

### 5.2 Writes and their semantics

| Write | Effect at the next frame boundary (4.3) |
|---|---|
| SET_INC k, v, jump | `inc_tgt[k] ← v`. If `jump = 1` or `glide = 0`, `inc_acc[k] ← v << 8` at once; otherwise the slew of 6.7 walks it there frame by frame. Whenever `inc_acc[k] >> 8` changes, `(e[k], r[k])` MUST be recomputed by 6.6.1 before it is next used, i.e. before the next sample's PolyBLEP. `phase[k]` is not touched. |
| SET_WAVE k, s | `wave[k] ← s`. Takes effect from the next sample, mid-note. |
| SET_WEIGHT k, v | `w[k] ← v`. |
| SET_ENV e, a_inc/d_dec/sus/rate | the named parameter of envelope e ← v. The envelope update at the end of the frame in which the write was applied already uses it. |
| SET_CUT lo/hi/track | the named cutoff register ← v. |
| SET_LADDER k/gain/ogain | the named coefficient ← v. Held for the whole frame (both passes). |
| SET_GLIDE v | `glide ← v`. |
| SET_VOL v | `vol ← v`. |
| GATE_ON | `gate ← 1`, and for both envelopes `seg ← ATTACK` with `level` unchanged (8.5, DR 0003). Nothing else changes: no phase, no ladder state. |
| TRIG | for both envelopes `seg ← ATTACK` with `level` and `gate` unchanged (8.5): the multi-trigger retrigger while a key is held. |
| GATE_OFF | `gate ← 0`. Both envelopes take the release branch of 8.3 from wherever their level is. |
| RESET | every register of section 14 ← its reset value. |

Each of these is one 32-bit SPI transaction (5.4): a flag bit, a 7-bit
address and 24 data bits, `{F, A[6:0], D[23:0]}` MSB first. The addresses
(DR 0007 section 3): `INC_TGT[k]` 0x00–0x02 with `F` = jump; `WAVE[k]`
0x04–0x06; `W[k]` 0x08–0x0A; `GLIDE` 0x0C; `VOL` 0x0D; amp envelope
`a_inc, d_dec, sus, rate` 0x10–0x13 and filter envelope 0x14–0x17;
`CUT_LO, CUT_HI, TRACK_HZ` 0x18–0x1A; `K, GAIN, OGAIN` 0x1C–0x1E; `GATE_ON`
0x20, `GATE_OFF` 0x21, `TRIG` 0x22, `RESET` 0x23 (data ignored); `NOP` 0x3F.
A register narrower than 24 bits takes the low bits of `D`; the rest MUST be
zero. **`wave[k]`: 0 saw, 1 square, 2 pulse25, 3 tri, 4 sine, and 5–7 also
sine** (bit 2 set selects sine, so every 3-bit value is defined). The chip
adds registers outside this voice — the drum bus level, the drum routing
and the drum filter, 0x0E, 0x0F, 0x28–0x2B, and the drum section's 0x40–0x7F
— which `docs/ARCHITECTURE.md` and the drum section's own record define.

Any register value is legal; nothing is rejected for range. Consequences of
out-of-range values follow from the formulas (an `inc` ≥ 2^23 is above
Nyquist; `inc` = 0 stalls its oscillator at DC, 6.3; weights summing above
32768 saturate in the mixer; `a_inc` = 0 holds the attack at its current
level forever; `rate` = 0 releases at one LSB per frame).

### 5.3 The unit of work: a sequence of writes to one voice

The model's unit of work is a sequence of writes applied at frame boundaries
to **one continuous voice** — `VoiceFx.play(regs, writes, n)` — from reset or
from whatever state the previous sequence left (DR 0003). A note from reset,
`VoiceFx.note`, is the special case: RESET, the patch registers, SET_INC with
`jump = 1` for each oscillator, SET_CUT track, GATE_ON at frame 0 and
GATE_OFF at `gate_n`. `render_mono_fx` turns a note list into writes through
the reference host `KeyHost` (5.6) and plays them through one voice; it no
longer sums overlapping notes. Reference sequences (section 16) are sequences
of writes.

### 5.4 Physical layer — DR 0007

**SPI, register writes, applied at the frame tick.** The full record, with
its reasons against the UART event stream and the SPI time-slice packets, is
`spec/decision-records/0007-control-interface-spi-register-writes.md`; the
normative content:

- SPI slave, mode 0 (MOSI sampled on SCK's rising edge, MISO changes on the
  falling edge), MSB first; pins `SCK`, `MOSI`, `CS_N`, `MISO`. The receiver
  samples the pins in the core clock domain, so SCK MUST be ≤ 2.0 MHz, and
  `CS_N` MUST be high for ≥ 4 core cycles between transactions.
- One transaction is **exactly 32 bits** between a falling and a rising edge
  of `CS_N` and is one write of 5.2; a transaction of any other length is
  discarded and applies nothing.
- **The unit of 4.3 is the transaction, and its acceptance cycle is the core
  cycle in which the synchronised rising edge of `CS_N` is registered with a
  bit count of 32.** Accepted writes enter a queue of depth 4 in acceptance
  order; at each tick the queue's occupancy is snapshotted and that many
  writes are applied, one per cycle, before any datapath block reads a
  control register. At the specified SCK at most two writes can complete in
  a frame, so the queue cannot overflow; a host outside the specification
  that overflows it loses the write and sets a sticky status flag.
- During every transaction the chip returns a 32-bit status word on `MISO`:
  `{0x4D, version 0x1, flags[3:0], frame[15:0]}`, loaded at the falling edge
  of `CS_N` — the flags are `overrun`, `queue non-empty`, `overflow` and
  `fresh` (no write since hardware reset); `frame` is the 16-bit frame
  counter of 4.1, wrapping.
- RESET (0x23) resets the registers of section 14 and leaves the link and
  the queue alone, so writes queued behind it in the same frame still apply,
  in order, after it.

*Informative:* pin to acceptance is three core cycles; a `CS_N` edge within
about one core cycle of a tick may be accepted in either frame, and the
contract is satisfied either way because the frame is defined by the
acceptance cycle. `rtl-sketch/spi_ctl.v` implements this section and
`rtl-sketch/tb_synth_top.v` drives it through the pins.

### 5.5 Host-side conversions (informative)

`VoiceFx.note_on` is the reference for how a patch's physical units become
register values. These formulas are informative — the block never sees Hz,
seconds or `res` — but a host that wants the model's sound uses them:

```
fitN(v)    = clamp(v, 0, 2^N − 1)          N = the register's width in 5.1 (fixed.usat)
inc[k]     = fit24( round(f0 · 2^(detune_k/12) · 2^24 / 48000) )      f0 = 440 · 2^((note−69)/12)
w[k]       = fit16( floor(mix_k / Σmix · 2^15) )     "floor-normalised": Σ w ≤ 32768 for mix_k ≥ 0;
                                                     Σmix = 0 gives every w[k] = 0
a_inc      = fit24( ceil(2^24 / max(1, floor(attack_s · 48000))) )
sus        = fit24( round(sustain · (2^24 − 1)) )
d_dec      = fit24( ceil((2^24 − 1 − sus) / max(1, floor(decay_s · 48000))) )
rate       = fit16( max(1, round((1 − exp(−4 / (release_s · 48000))) · 2^16)) )
                                                     release_s ≤ 0 is instant: rate = 65535
cut_lo/hi  = fit16( round(cutoff_lo/hi_hz) )
track_hz   = fit16( round(track · f0 · 4) )
k          = fit17( round(4 · res · 2^14) )
gain       = fit20( round(drive · 0.13 / 0.05 · 2^16) )  = fit20( round(drive · 2.6 · 65536) )
ogain      = fit20( round(0.05 / 0.13 · (1 + 2 · res) · 2^16) )
glide      = fit24( max(1, round((2^(1 / (T_oct · 48000)) − 1) · 2^24)) )    T_oct = seconds per octave;
                                                     T_oct ≤ 0 → 0, off; clamps below 1.7 µs per octave (DR 0004)
vol        = fit16( round(volume · 2^15) )           reference 0.45 → 14746; clamps at volume ≥ 2 (DR 0005)
```

**Where the clamps fire.** (Rev 2; this was OPEN 17.7.)
`test_every_host_conversion_fits_its_register` walks each conversion over
its full plausible input domain — all 128 notes with detune −24..+24
semitones, attack/decay/release 0..30 s, sustain 0..1, cutoff 0..65 535 Hz,
`track` 0..1, `res` 0..1.5, `drive` 0..4, every mix on a quarter grid, every
waveform — and pins the following:

- `a_inc`: the raw value is 2^24, one bit too wide, for an attack of fewer
  than **two frames**, `attack_s < 2/48000 = 41.67 µs` (`attack_s = 0`
  included); it is clamped to 2^24 − 1. The clamp is unobservable: either
  value completes the attack in one update from any level, so the register
  stays 24 bits rather than growing a bit that changes no sample
  (`test_attack_increment_clamps_below_two_frames`).
- `rate`: the raw value is 2^16 — 1.0, which Q0.16 cannot hold — for
  `release_s ≤ 4 / (17 ln 2 · 48000) = 7.072 µs`, a third of a frame, and
  rev 1's model divided by zero at `release_s = 0`. It is clamped to 65535,
  and `release_s ≤ 0` means instant, as the float model's `max(1e-9, ·)`
  does. The cost of the clamp: full scale reaches zero in three updates
  (16777215 → 256 → 1 → 0; 62.5 µs) where 1.0 would take one. A 17th bit
  on every rate multiply, for a release nobody can hear, is not worth that
  (`test_release_rate_clamps_below_seven_microseconds`).
- `inc`: the raw value exceeds 24 bits only for an oscillator at or above
  48 kHz, the sample rate — note 127 with a detune of +23.24 semitones or
  more; it is clamped to 2^24 − 1, which is already above Nyquist (6.3).
- `k` overflows 17 bits at `res ≥ 2.0`; `gain` overflows 20 bits at
  `drive ≥ 6.152`; `sus` overflows at `sustain > 1`. None is inside the
  range any audition patch uses (`res` ≤ 1.06, `drive` ≤ 3.6); all clamp.
- `w[k]`: a mix summing to zero has nothing to normalise by and rev 1's
  model divided by zero; every weight is 0.
- `d_dec`, `cut_lo`, `cut_hi`, `track_hz` and `ogain` never clamp inside
  their domains.
- `glide` (rev 3) clamps only below 1.7 µs per octave, a ratio of 2 per
  frame; `vol` clamps at a volume of 2.0 and above. Neither is inside any
  host's plausible range.

`a_inc` and `rate` are at least 1 by construction. `d_dec` is 0 only for
`sustain = 1.0`, where DECAY ends at once because `level = FULL ≤ sus`.

Default patch values, for reference (the `note_on` defaults): waves (saw,
saw, square), detune (0, +0.07, −12) semitones, mix (1.0, 0.8, 0.5) → weights
(14246, 11397, 7123), cutoff (400, 4000), res 0.62 → k = 40632, drive 1.6 →
gain = 272630, ogain = 56462, amp ADSR (5 ms, 250 ms, 0.75, 120 ms) → a_inc =
69906, d_dec = 350, sus = 12582911, rate = 45; filter ADSR (4 ms, 300 ms,
0.25, 100 ms); track 0.35; glide 2692 (90 ms per octave); vol 14746.

### 5.6 The reference host (informative)

Which held key sounds, whether a new key retriggers, whether it glides, and
how held keys are assigned to oscillators are the host's decisions in the
product (DR 0002: the MCU sees the MIDI keys). `voice_fx.KeyHost` is the
reference: its policies are parameters and its defaults are what the
audition sequences play with. Nothing here binds an implementation of the
block.

| policy | default | alternatives | record |
|---|---|---|---|
| priority | last note | low, high | DR 0003 |
| trigger | single: GATE_ON when no key was held; a legato key changes pitch only | multi: TRIG on every new key while one is held | DR 0003 |
| release to a held key | return to it, no retrigger | — | DR 0003 |
| glide | always (from the last pitch, the Minimoog's switch), `jump` on the first note after reset | off; legato only (`jump = 1` on the first key of a phrase) | DR 0004 |
| paraphonic | held keys to oscillators 0..2 in press order; the rest double the newest key; one shared gate and trigger | — | DR 0003 |

---

## 6. Oscillators

### 6.1 Registers

Per oscillator: `phase` (24-bit unsigned), `inc_tgt` (24-bit unsigned),
`inc_acc` (32-bit unsigned, Q24.8; `inc = inc_acc >> 8`), `wave`, and the
PolyBLEP state `e` (signed, −15..+8 over all 24-bit `inc` ≥ 1 and 0 for
`inc = 0`; −4..+7 over NOTE_INC) and `r` (16-bit unsigned).

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

`inc` may hold any 24-bit value. `inc = 0` stalls the oscillator at its
current phase; the PolyBLEP is then identically zero (6.6.3) and the output
is the naive waveform of that phase (6.4) — DC, not silence: from reset a
stalled saw reads −32768 and a stalled square +32767. No host conversion
produces it (NOTE_INC's smallest entry is 2858, and 0 needs an oscillator
below 0.00143 Hz, a detune under −149 semitones at note 0), but it is the
reset value (14) and a legal write, and
`test_zero_increment_stalls_the_oscillator` checks it for every shape from
several phases. Rev 1's model raised here; the prose was right and the model
was wrong (resolved 17.9). A patch with fewer than three oscillators leaves
the rest at `inc = 0` and `w = 0` (`VoiceFx.patch_regs`), so the reference
sequences of the one-oscillator whistle patch exercise it.

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

Whenever `inc` takes a new value (SET_INC with `jump`, each frame in which
the glide slew changes `inc_acc >> 8`), compute (`voice_fx.recip_of`, with `MANT_BITS = RECIP_BITS = 16`):

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

`inc = 0` has no mantissa: `(e, r) ← (0, 0)`, the reset values of section
14, and no division is performed. Neither is observable — with `inc = 0`
neither window of 6.6.3 can open, so `c = 0` whatever `(e, r)` hold — and an
implementation whose divider yields something else for `m = 0` is still
bit-exact.

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

### 6.7 Glide (DR 0004)

The glide is on the chip and is **constant rate, linear in pitch**: every
frame the increment moves toward its target by a fixed ratio of itself — a
constant number of cents per frame, geometric in the increment — so a
two-octave glide takes twice as long as a one-octave one, every oscillator
keeps its detune through the glide, and it lands exactly. `glide` is the
voice's Q0.24 register (the ratio per frame minus 1; 0 = off); each
oscillator holds `inc_tgt` (24) and `inc_acc` (32, Q24.8) and adds
`inc = inc_acc >> 8` to its phase (6.2).

SET_INC k, v, jump (5.2): `inc_tgt ← v`; if `jump = 1` or `glide = 0`,
`inc_acc ← v << 8`. Then at the end of every frame (step 9 of 4.2), for each
oscillator with `inc_acc ≠ inc_tgt << 8` (`OscFx.slew`):

```
tgt     = inc_tgt << 8
d       = max(1, (inc_acc · glide) >> 24)         exact 56-bit product; both operands non-negative
inc_acc = min(tgt, inc_acc + d)      if tgt > inc_acc
        = max(tgt, inc_acc − d)      if tgt < inc_acc
inc_acc = tgt                        if glide = 0
```

Frame f's oscillator uses `inc_acc >> 8` as it stands at the start of the
frame; `(e, r)` MUST be recomputed whenever that value changes (6.6.1). The
`max(1, ·)` is the release's lesson (8.3): without it a small increment times
a small rate truncates to no motion at all.

*Informative:* the host's conversion is `glide = round((2^(1/(T_oct · 48000))
− 1) · 2^24)` for `T_oct` seconds per octave (5.5); the reference host's 90 ms
is 2692, and one octave then takes 4320 frames within 1 %. Constant-time
glide is a host policy (compute `T_oct` from each interval); legato-only glide
is `jump = 1` on the first key of a phrase. The float audition model glides
geometrically over a constant time, so the two models differ on a glided
patch by design (`voice_fx_render.py`).

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

A GATE_ON or TRIG applied at the start of the frame (step 1 of 4.2) sets
`seg ← ATTACK` with the level untouched, before the output of 8.2 is taken
and before this update. Then exactly one branch executes, chosen by `gate`
then `seg` as they are at the start of the update. Comparisons are on exact
integers.

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
  per frame (2^24 frames = 350 s from full). The host conversions of 5.5
  give `a_inc` and `rate` at least 1; they give `d_dec = 0` only for
  `sustain = 1.0`, where DECAY ends at once because `level = FULL ≤ sus`.
- SUSTAIN re-asserts `level ← sus` every frame, so a change of `sus` while
  sustaining moves the level in one frame (unlike gf180-polysynth's envelope).
- In DECAY, if `sus` is above the current level the level jumps **up** to
  `sus` in one frame.
- A gate that drops during ATTACK releases from the partial level; the attack
  does not complete. The release branch leaves `seg` alone, and GATE_ON sets
  it to ATTACK, so a gate that comes back always attacks from the current
  level (8.5).

*Informative, derived:* ATTACK from 0 takes `ceil(FULL / a_inc)` updates; the
default `a_inc = 69906` reaches FULL at update 240 (5.0 ms) and the output
first reads 32767 in frame 240.

### 8.4 Gate timing in the model

`AdsrFx.render(n, gate, trig)` takes a per-frame `gate` array and a per-frame
`trig` array (1 in the frames at whose start a GATE_ON or TRIG was applied);
`render(n, gate_n)` with an integer is the single-note form, the gate on for
frames `0..gate_n−1`, `gate_n = min(n, max(1, floor(gate_s · 48000)))`, with
`gate_s = 0.8 · dur` by default. In hardware the gate is the register of 5.1
and its timing is the host's.

### 8.5 Retrigger (DR 0003)

- **GATE_ON** and **TRIG** re-enter ATTACK with the level unchanged: the
  attack proceeds from wherever the envelope is — from zero only when it is
  at zero. There is no reset to zero (the Minimoog's contour continues from
  its current level, and so does every modern Moog's by default).
- A pitch change while the gate is on (SET_INC without TRIG) leaves both
  envelopes alone: single triggering, the Minimoog's. A host that wants
  multiple triggering sends TRIG with the new pitch.
- **Nothing else changes at a note.** `phase[k]` and the ladder's state are
  written by RESET only; the oscillators free-run and the filter is
  continuous across notes — a ring, or a self-oscillation, carries into the
  next note, and the note ends because the VCA (9) closes.
- Key priority and paraphonic allocation are the host's (5.6).

Testable, and tested (`test_voice_fx.py`, the DR 0003 tests): no step in the
envelope output at a TRIG and then `a_inc` per frame from the current level;
the envelope constant across a legato pitch change; the oscillator stream
equal to a free-running oscillator's; a phrase split across two `play` calls
identical to the unsplit one.

---

## 9. Amplitude (the VCA)

Step 7 of 4.2 (`VoiceFx._render`):

```
v = (y · ae) >> 15          y the ladder's 19-bit output (11.4), ae = level_amp >> 9, 0..32767
```

`y` is −262144..262143, so `|v| < 2^18` — 19 bits signed — and it cannot
overflow. The amplitude envelope is applied **after** the filter (DR 0005),
so the ladder's input is `mixed` (7) at the mixer's level, and a note ends
when the envelope reaches zero whatever the filter's state.

---

## 10. Cutoff, the g ROM and the kc ROM

### 10.1 Cutoff and g

Step 5 of 4.2:

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

### 10.2 Resonance compensation (DR 0006)

The feedback the loop needs for a given resonance varies with cutoff
(Huovilainen §5.3; measured in 11.5). The host's `k` is scaled per frame by a
second ROM read with the same cutoff (`voice_fx.kc_from_cut`, `k_effective`;
`KROM_BITS = 5`, `K_BITS = 17`):

```
i     = cut >> 10                        0..21
frac  = cut & 1023
kc    = K_ROM32[i] + (((K_ROM32[i+1] − K_ROM32[i]) · frac) >> 10)      unsigned Q1.15; the delta may be negative: arithmetic shift
k_eff = min( (k · kc) >> 15, 2^17 − 1 )                                Q3.14, 17 bits; exact 33-bit product
```

**Appendix E is normative**: `K_ROM32[i] = round(k_onset(clamp(1024 i, 30,
21600)) / 4 · 32768)`, i = 0..32, where `k_onset(cut)` is the loop gain at
which the linearised ladder — four one-poles `G/(1 − (1 − G)z⁻¹)` with `G =
g(cut) · s0 / 2^16`, `s0 = TANH16[1] / 2^13` the tanh table's first-bin
slope, and the half-sample feedback delay `(z⁻¹ + z⁻²)/2` at 96 kHz — has a
phase of −180° and a magnitude of 1 (`voice_fx.k_onset`, a bisection; float,
ROM-building only). `kc = 32768` means `k_eff = k`; the table is 32799 at
30 Hz, peaks at 39879 (1.217) at entry 11 (11 264 Hz) and is 33964 at the
clamp; entries 22..32 are never read. The saturation to `2^17 − 1` is the
ladder's port width and fires only for `res · kc > 2`, above `res` = 1.64 at
the peak; no audition patch reaches it. `kc` and `k_eff` are held for both
oversampling passes.

The consequence, measured (11.5): **`res = 1.0` is the onset of
self-oscillation at every cutoff** within 0.39 %.

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
| `k_eff` | Q3.14 unsigned, per frame (10.2); 65536 is a loop gain of 4 | 17 |
| `gain`, `ogain` | Q4.16 unsigned | 20 |
| output `y_out` | Q4.15 signed, saturated to 19 bits (`out_bits`, DR 0005) | 19 |

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

Step 6 of 4.2, for frame input `x = mixed` and this frame's `g`, `k_eff`,
`gain`, `ogain` (`LadderFx.process`, with `g_q16` and `k_q14` per sample). Two
passes; each pass advances every state register once.

```
xg = (x · gain) >> 11                     exact 36-bit product; the same for both passes

for pass in 0, 1:
    fb  = (d1 + d2) >> 1                  half-sample delay: mean of the last two outputs, 25-bit sum, arithmetic shift
    u   = sat24( xg − ((k_eff · fb) >> 14) )  input stage, state units
    w0  = tanh(u)                         11.3
    for s in 0, 1, 2, 3:                  IN ORDER; stage s uses the w[s−1] just written in this pass
        prev = w0 if s = 0 else w[s−1]
        diff = prev − w[s]                −65534..65534
        y[s] = sat24( y[s] + ((g · (diff << 5)) >> 16) )
        w[s] = tanh(y[s])
    d2 ← d1 ; d1 ← y[3]

y_out = sat19( ((y[3] >> 5) · ogain) >> 16 )     from the state after pass 1; Q4.15, ±8.0
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
and `drive`, and 10.2 turns `k` into the per-frame `k_eff`. Measured
(`model/k_comp_sweep.py`, DR 0006): the loop gain at which the fixed-point
filter starts to self-oscillate rises from 4.00 at 30 Hz through 4.32 at
2.5 kHz to 4.85 near 11 kHz and falls to 4.14 at the clamp — which is why,
at a fixed `k = 4 · 1.08`, rev 1 did not sustain above about 3 kHz — and is
within 0.25 % of the linearised prediction the ROM is built from at every
cutoff. With the ROM, the ring decays at `res = 0.995` and grows at `1.005`
at 200 Hz, 3 kHz and 10 kHz (`test_self_oscillation_starts_at_res_1_everywhere`).
The frequency it oscillates at is 0.968 × the cutoff at 30 Hz, 1.00 at
1.6 kHz, 1.072 × at 10 kHz and 0.906 × at the clamp: a tuning error, not
corrected in this revision (17.12). `ogain`'s `(1 + 2·res)` term is a partial
passband-loss compensation.

### 11.6 Where the ladder saturates

Three clamps, all part of the arithmetic: `u` to 24 bits (input stage), each
`y[s]` to 24 bits (never reached in practice, 11.2), and `y_out` to 19 bits —
a width, not a clip in practice: the eight audition patches peak at 1.94 ×
full scale and the RTL bench's stimulus at 1.96, against the word's 8.0
(section 12).

---

## 12. Output stage and the saturation points (DR 0005)

Step 8 of 4.2, after the VCA of section 9:

```
sample = sat16( (v · vol) >> 15 )        v the VCA's output (9), vol the Q0.15 register; exact 35-bit product
```

`vol` replaces rev 1's fixed gain of 0.9. The reference host writes `vol =
14746` (0.45), at which the loudest audition patch (`growl-bass`) peaks at
0.86 × full scale and none clips; at rev 1's 0.9 `growl-bass` clips 4.8 % of
its samples (`test_reference_volume_clips_no_audition_patch`). The rail is
hard, and the headroom above the reference is the host's to spend — the
policy Sequential states for the Prophet-6 ("rather than limit the outputs
… we allow you to adjust levels", DR 0005) — not a limiter's.

**Saturation is designed, and it is in two places.** The overdrive of the
instrument is the ladder's `tanh` in every stage, driven by `gain` (11.3,
11.4; DR 0001); the mixer's `sat16` is the hard rail of the Q1.15 word, which
weights the host normalises never reach (7). The signal path has exactly
these clamps, in signal order, and no others:

| # | where | clamp | section |
|---|---|---|---|
| 1 | each oscillator, after PolyBLEP | `sat16` | 6.6.4 |
| 2 | mixer sum | `sat16` | 7 |
| 3 | ladder input stage `u` | `sat24` (state units, ±8.0) | 11.4 |
| 4 | ladder state `y[s]` after each integrator | `sat24` | 11.4 |
| 5 | ladder output `y_out` | `sat19` (Q4.15, ±8.0) — never reached on the audition patches or the bench | 11.4 |
| 6 | output sample | `sat16` — reached only if the host raises `vol` past the reference | 12 |

The VCA multiply (9), the cutoff shift (10, before its clamp to Hz), the kc
interpolation and `k · kc` (10.2, saturated only at the port width), the tanh
interpolation and the glide slew cannot overflow and have no clamp.

*Informative:* in the chip the rail is the master mix's, and the drum bus is
added before it — `sample = sat16(((v · vol) >> 15) + ((d · dvol) >> 15))`,
`d` the 19-bit drum bus, `docs/ARCHITECTURE.md` section 4. With `dvol = 0`,
or a silent drum section, that is this section's sample bit for bit, and it
is what `rtl-sketch/verify_voice.py` checks; the drum bus's own contract is
the drum section's. In rev 1
the ladder's output was 16 bits and clamp 5 was where four of the eight
audition patches clipped; with the width, the VCA after the filter and the
volume, the float-versus-fixed gap on `growl-bass` is −32 dB instead of
−13 dB, the ladder's own quantisation (`voice_fx_render.py`).

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
| `phase[k]`, `inc_tgt[k]`, `inc_acc[k]`, `e[k]`, `r[k]` | 0 | `inc = 0` gives `c = 0` by 6.6.3 and `(e, r) = (0, 0)` by 6.6.1; `(e, r)` are recomputed at the first change of `inc` |
| `wave[k]`, `w[k]` | 0 | `wave` = 0 is saw (5.2) |
| `level`, `seg` (both envelopes) | 0, ATTACK | |
| `gate` | 0 | |
| `glide` | 0 | off: SET_INC takes effect at once |
| `vol` | 0 | silent until the host writes a volume (17.8) |
| `a_inc`, `d_dec`, `sus`, `rate` (both) | 0 | |
| `cut_lo`, `cut_hi`, `track_hz` | 0 | the clamp makes the cutoff 30 Hz |
| `k`, `gain`, `ogain` | 0 | |
| ladder `y[0..3]`, `w[0..3]`, `d1`, `d2` | 0 | `LadderFx.reset()` |
| output sample register | 0 | |
| control parser / queue | idle, empty | on hardware reset only: the RESET write leaves the link and its queue alone (5.4) | |

Consequences: from reset the voice outputs 0 every frame until programmed —
the envelope holds at 0 by the release branch, `vol` is 0, and a zero-state
ladder with zero input stays at zero. All-zero control is the model's reset
of *state*; the model has no reset values for *control* because `note_on`
always writes the whole image. **The power-on defaults are these zeros (DR
0007 section 6, closing 17.8): a bare GATE_ON is silent.** The host is a
microcontroller with the patch in flash; it writes the image at boot and
whenever the status word's `fresh` flag reads 1, and non-zero defaults would
be a second, silent copy of a default patch in metal.

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
4. Recommended taps, matching `VoiceFx.trace`: each `osc_k` and `inc_k`,
   `mixed`, `ae`, `fe`, `cut`, `kc`, `k_eff`, the ladder's 19-bit `y_out`,
   and `v`. The ladder alone is checkable through
   `rtl-sketch/verify_ladder.py`'s vector format (`x, g, k, gain, ogain` in,
   `y_out` out, `k` per sample), which drives 28 800 samples that reach
   every clamp and both coefficient MSBs.

A test compares the implementation's sample f with the model's for every f,
for a scripted sequence of (frame, write) deliveries. Any mismatch is a
failure; there is no tolerance. In this revision the reference sequences are
single notes from reset — `VoiceFx().note(note, dur, **patch)` — and the
eight audition patches of `audition/patches.py::MONO` played through one
continuous voice by `render_mono_fx`, whose write lists (from `KeyHost`,
5.6) are the sequences. A bench MUST also be shown to fail: the injected defects of
`rtl-sketch/ladder_dp.v` (`INJECT_BUG_LADDER_FB`, `_SAT`, `_TANH_CLAMP`) are
the pattern.

Table freshness: `spec/reference/gen_tables.py --check` MUST pass; it fails
if any hash in the appendices, any image under `spec/reference/tables/`, or
`rtl-sketch/tanh16.hex` is not what the model generates.

Register widths: `test_every_host_conversion_fits_its_register` walks every
conversion of 5.5 over its input domain and fails if any result leaves the
width of 5.1; `test_every_legal_register_value_runs` walks the extremes of
every register through the model and fails if any legal value raises or
leaves the ranges stated here. A change to a width in 5.1 must change
`voice_fx.REG_BITS` and both tests with it.

---

## 17. Open items

Everything this revision does not decide, in one place. Each needs a decision
record that extends this document; none may be resolved by picking a reading.

1. **Note-on retrigger semantics** (8.5) — **closed in rev 3 by
   DR 0003**: GATE_ON and TRIG re-enter ATTACK from the current level; no
   phase or ladder reset; priority, single/multi trigger and paraphonic
   allocation are the host's, with the reference host's defaults informative
   (5.6).
2. **Glide** (6.7) — **closed in rev 3 by DR 0004**: on the chip, constant rate,
   geometric in the increment (linear in pitch), the `glide` register.
3. **Physical control layer** (5.4) — **closed in rev 4 by DR 0007**: SPI
   register writes, one 32-bit transaction per write of 5.2, accepted at the
   synchronised `CS_N` rising edge and applied at the next tick; the
   encodings of every address and of `wave[k]` (saw 0, square 1, pulse25 2,
   tri 3, sine 4–7) are in 5.2 and DR 0007.
4. **Modal bank** (15): sizing proposed, not ratified; trigger, excitation
   source, mixing and gain staging unspecified.
5. **Resonance compensation above ~3 kHz** (11.5) — **closed in rev 3 by
   DR 0006**: `K_ROM32` (10.2, Appendix E); `res = 1` is the onset within
   0.39 %.
6. **Output gain staging** (12) — **closed in rev 3 by DR 0005**: a 19-bit
   ladder output, the VCA after the filter, the `vol` register and a hard
   rail.
7. **Register-width clamps in the host conversion** (5.5) — **resolved in
   rev 2**: every conversion clamps to its register width; where each clamp
   fires, and why `a_inc` and `rate` clamp rather than widen, is in 5.5. Rev
   3 adds `glide` and `vol` to the clamped set.
8. **Power-on control defaults** (14) — **closed in rev 4 by DR 0007**: all
   zero; a bare GATE_ON is silent; the MCU host writes the image at boot.
9. **`inc = 0`** (6.3) — **resolved in rev 2**: the oscillator stalls at DC
   with `c = 0` and `(e, r) = (0, 0)` (6.6.1); model-checked for every shape.
10. **Widths of `cut_lo`, `cut_hi`, `track_hz`** (5.1) — **closed in rev 4 by
    DR 0007**: 16 bits unsigned, fixed by the write format; the sum of
    section 10 is computed exactly at 19 bits before the clamp.
11. **Ratification itself.** This document is proposed. Ratification is the
    two-key act this fleet uses and is not claimed here.
12. **Self-oscillation tuning** (11.5, DR 0006): the resonant frequency is
    0.968 × the cutoff at 30 Hz and 1.072 × at 10 kHz. A retuned g ROM would
    move the zero-resonance corner by the same amount (Huovilainen's
    two-dimensional caveat); whether to, and how, is a separate decision.

---

## 18. Revision history

- **Rev 1 (2026-09-17)** — initial proposal, written from `model/voice_fx.py`
  and `model/fixed.py` as committed; appendices generated by
  `spec/reference/gen_tables.py`. Not ratified.
- **Rev 2 (2026-09-17)** — resolves 17.7 and 17.9. Every host conversion of
  5.5 clamps to its register width of 5.1: `a_inc` to 2^24 − 1 below two
  frames of attack; `rate` to 65535 at or below 7.072 µs of release and at
  `release_s = 0`, which the rev-1 model divided by (a third raise the rev-1
  prose had not recorded); also `inc` (≥ 48 kHz), `k` (`res` ≥ 2), `gain`
  (`drive` ≥ 6.152), `sus` (`sustain` > 1), and a zero-sum mix, which also
  divided by zero. `inc = 0` is defined and model-checked: the oscillator
  stalls at DC, `(e, r) = (0, 0)` (6.3, 6.6.1) — here the rev-1 prose was
  right and the model was wrong. The model names the ladder registers
  (`LadderFx.regs`) and accepts them directly, and the whole control image
  is walked at its extremes (5.1, 16). Five tests added (45). No table,
  hash or reference sequence changed. Not ratified.
- **Rev 3 (2026-09-17)** — resolves 17.1, 17.2, 17.5 and 17.6. DR 0003
  (note-on: GATE_ON and TRIG re-enter ATTACK from the current level, one
  continuous voice, no phase or ladder reset, the reference host), DR 0004
  (glide: constant rate on the chip, the `glide` register), DR 0005 (gain
  structure: 19-bit ladder output, the VCA after the filter, the `vol`
  register, a hard rail), DR 0006 (resonance compensation: `K_ROM32`,
  Appendix E, `k_eff` per frame). `glide` and `vol` join the clamped
  conversions of 5.5 and the extremes walk of 16. One table added; every
  reference sequence's values change (the chain order, the volume, the
  compensation). Rev 1 and 2 were proposed, not frozen, so their text is
  revised rather than extended. Not ratified.
- **Rev 4 (2026-09-17)** — resolves 17.3, 17.8 and 17.10 by DR 0007 (the
  control interface: SPI register writes applied at the frame tick, the
  register map and the `wave` encoding, all-zero power-on defaults, 16-bit
  cutoff registers; RESET leaves the link and queue alone). No arithmetic,
  table, hash or reference sequence changes. The voice is now implemented
  (`rtl-sketch/voice_dp.v`) and verified bit-exact against the model at the
  register port over the three scenarios of `rtl-sketch/verify_voice.py`
  (43 200 frames); the chip around it is `docs/ARCHITECTURE.md`. Not ratified.

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

### Appendix E -- K_ROM32: cutoff (Hz) -> resonance compensation, i = 0..32

Normative (DR 0006). `K_ROM32[i] = round(k_onset(clamp(1024*i, 30, 21600)) / 4 * 32768)` -- unsigned Q1.15, EDGE sampled every 1024 Hz, 32 entries plus entry 32 as the interpolation guard (`voice_fx.make_k_rom`). `k_onset` is the small-signal onset of self-oscillation of the linearised loop, section 10.2 (`voice_fx.k_onset`); 32768 means k = 4 res, the uncompensated filter. Entries 0..21 are reachable through the cutoff clamp of section 10; entries 22..32 are evaluated at the clamp and never read. Eight entries per row.

| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 32799 | 33832 | 34861 | 35839 | 36748 | 37571 | 38290 | 38890 |
| 8 | 39357 | 39681 | 39856 | 39879 | 39755 | 39489 | 39093 | 38582 |
| 16 | 37971 | 37279 | 36524 | 35722 | 34890 | 34043 | 33964 | 33964 |
| 24 | 33964 | 33964 | 33964 | 33964 | 33964 | 33964 | 33964 | 33964 |
| 32 | 33964 |  |  |  |  |  |  |  |

SHA-256 of the 33 decimal values joined by commas: `514d0ba224df47ab47e4c6b5454666b88568f3172bacdc2e17baba3c5b6c6e1a`

<!-- END GENERATED APPENDICES -->
