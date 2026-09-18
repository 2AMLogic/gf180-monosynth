# 0007: The control interface — SPI transport, register-write semantics, applied at the frame tick

- **Status**: proposed
- **Date**: 2026-09-17
- **Decided by**: block agent, from the product constraints of DR 0002 (an MCU is the client), the key model of DR 0003, the operator's proposal in gf180-polysynth issue 7 and the analysis posted there, and the measurements in `docs/area-budget.md`
- **Closes**: contract open items 17.3 (physical layer and every encoding), 17.8 (power-on defaults), 17.10 (the widths of `cut_lo`, `cut_hi`, `track_hz`)

## Context

Contract revision 3 specifies *what* control does — the register image of 5.1,
the writes of 5.2, and the timing rule of 4.3 (a write complete during frame
f applies at the start of frame f+1, in order, atomically) — and leaves the
physical layer OPEN (5.4). Two candidates were on the table:

1. **A UART event stream**, gf180-polysynth's contract section 10: 115 200 8N1,
   status/data bytes, one command per opcode, applied at the next frame
   boundary. Designed for a human or a MIDI cable at the other end.
2. **SPI time-slice "stop packets"**, gf180-polysynth issue 7: the host sends
   one packet per slice of N frames carrying the complete control state (the
   *stops*), with a repeat count; percussion stops are edge-triggered on slice
   boundaries; N = 480 (10 ms) as a strawman, and 256 (5.33 ms) argued for in
   the same thread on drum-timing perception.

Both were written before the client was known. It is now known (DR 0002, the
sponsor's decisions on issue 1): **the client is a CH32V203F8U6 microcontroller
that owns USB and translates class-compliant USB-MIDI into whatever this
record decides.** No human types at this link, no MIDI cable plugs into it,
and the host holds the patch in flash. That fact decides most of what follows.

Two more facts bear on it:

- **The key model is a sequence of writes** (DR 0003). Paraphony is the host
  assigning held keys to `inc_tgt[0..2]`; single or multi triggering is
  GATE_ON or TRIG; a legato pitch change is a bare SET_INC. The model's unit
  of work — `VoiceFx.play(regs, writes, n)` — and the verification obligation
  of contract 16 are literally "a scripted sequence of (frame, write)
  deliveries". GATE_ON and TRIG are *events* (they re-enter ATTACK); they
  cannot be expressed as a level.
- **The register image is large.** The voice alone is 451 bits (three
  oscillators 129, two envelopes 176, the voice registers 146); with the
  drum section it is more. In this library a flop under an enable costs
  92 µm² (`area-budget.md` section 0), so a second copy of the image — which
  an atomically applied whole-image packet needs — is on the order of
  0.04 mm² of cells before the drums.

## Decision

**SPI for the wires; register writes for the meaning; the frame tick for the
time.** One 32-bit SPI transaction is one write of contract 5.2, applied at
the next frame tick exactly as 4.3 says. Nothing about the stop/slice model
is adopted except its transport and its CS framing.

### 1. Physical layer

| | |
|---|---|
| Transport | SPI slave, **mode 0** (CPOL = 0, CPHA = 0): MOSI sampled on the rising edge of SCK, MISO changes on the falling edge, MSB first |
| Pins | `SCK`, `MOSI`, `CS_N` (active low) in; `MISO` out. Four pins. |
| Transaction | exactly **32 bits** between a falling and a rising edge of `CS_N`. A transaction with any other bit count is **discarded** — no partial or over-long write is ever applied, and the stream cannot lose byte alignment (a UART can, and needs the status-bit scheme of the sibling's 10.2 to recover). |
| Sampling | the receiver is **synchronous to the 12.288 MHz core clock**: `SCK`, `MOSI` and `CS_N` pass through two-flop synchronisers and edges are detected in the core domain. There is no second clock domain and no CDC. |
| SCK | **≤ 2.0 MHz guaranteed** (the design's limit is f_core / 4 = 3.072 MHz with a 50 % duty cycle; the guaranteed figure leaves margin for duty-cycle distortion and the synchroniser). One transaction is therefore ≥ 16 µs. |
| CS_N | must be high for **≥ 4 core cycles (≥ 0.33 µs)** between transactions; the MCU's SPI peripheral does this by default. |
| Rate | at 2 MHz, one write per 16 µs — 0.77 frames. The whole voice image (34 writes; 40 with the master and drum-filter registers) takes 0.54–0.64 ms; a paraphonic chord (three SET_INC and a GATE_ON) 64 µs. |
| MISO | during every transaction the chip shifts out a **32-bit status word** (section 4), loaded at the falling edge of `CS_N`. A host that does not want it leaves `MISO` unconnected. |

### 2. The write: one transaction, one register

```
bit 31        30 ... 24        23 ... 0
 F            A[6:0]           D[23:0]
 flag         address          data, MSB first, right-aligned
```

- `A` selects a register or an action (section 3). `D` is 24 bits; a
  register narrower than 24 bits takes the low bits and the rest of `D`
  **MUST be zero** (the implementation ignores them; the contract's "any
  register value is legal, nothing is rejected" holds for the bits that
  exist).
- `F` is the **jump** bit of SET_INC (5.2) and is reserved, MUST be zero, on
  every other address.
- Addresses 0x00–0x3F are the voice and the master; 0x40–0x7F are the drum
  section and are **owned by the drum branch**; this record only reserves
  them and fixes that they decode the same way.

### 3. Register map

Every register of contract 5.1 has one address. Widths are 5.1's; the write
carries 24 bits and the register keeps its own width.

| A | name | width | write semantics (contract 5.2) | reset |
|---:|---|---:|---|---:|
| 0x00–0x02 | `INC_TGT[k]`, k = A[1:0] | 24 | SET_INC k, D, jump = F | 0 |
| 0x04–0x06 | `WAVE[k]` | 3 | SET_WAVE k, D[2:0] — **0 saw, 1 square, 2 pulse25, 3 tri, 4 sine; 5–7 also sine** (D[2] set means sine, so every value is defined) | 0 (saw) |
| 0x08–0x0A | `W[k]` | 16 | SET_WEIGHT k, D[15:0] | 0 |
| 0x0C | `GLIDE` | 24 | SET_GLIDE | 0 (off) |
| 0x0D | `VOL` | 16 | SET_VOL — the voice bus level (contract 12) | 0 |
| 0x0E | `DVOL` | 16 | the drum bus level at the master mix, Q0.15 (ARCHITECTURE.md section 4) | 0 |
| 0x0F | `ROUTE` | 1 | bit 0 `DFILT`: the drum bus passes through the **drum filter** — the second context of the ladder, with its own `DCUT`, `DK`, `DGAIN`, `DOGAIN` — before the master mix (ARCHITECTURE.md section 4) | 0 (bypass) |
| 0x10–0x13 | `AMP_A_INC`, `AMP_D_DEC`, `AMP_SUS`, `AMP_RATE` | 24, 24, 24, 16 | SET_ENV amp | 0 |
| 0x14–0x17 | `FILT_A_INC`, `FILT_D_DEC`, `FILT_SUS`, `FILT_RATE` | 24, 24, 24, 16 | SET_ENV filt | 0 |
| 0x18–0x1A | `CUT_LO`, `CUT_HI`, `TRACK_HZ` | **16** | SET_CUT (closes 17.10, below) | 0 |
| 0x1C | `K` | 17 | SET_LADDER k | 0 |
| 0x1D | `GAIN` | 20 | SET_LADDER gain | 0 |
| 0x1E | `OGAIN` | 20 | SET_LADDER ogain | 0 |
| 0x28 | `DCUT` | 16 | the drum filter's cutoff, integer Hz, clamped to 30..21 600 like the voice's; no envelope, no tracking | 0 (30 Hz) |
| 0x29 | `DK` | 17 | the drum filter's resonance, `4·res` in Q3.14, compensated by the same kc ROM at `DCUT` | 0 |
| 0x2A | `DGAIN` | 20 | the drum filter's input gain, Q4.16 | 0 |
| 0x2B | `DOGAIN` | 20 | the drum filter's output gain, Q4.16 | 0 |
| 0x20 | `GATE_ON` | — | `gate ← 1`, both envelopes `seg ← ATTACK`, level unchanged; D ignored | |
| 0x21 | `GATE_OFF` | — | `gate ← 0`; D ignored | |
| 0x22 | `TRIG` | — | both envelopes `seg ← ATTACK`, level and gate unchanged; D ignored | |
| 0x23 | `RESET` | — | every datapath register of contract 14 ← its reset value; D ignored. **The link and the write queue are not touched**: writes queued behind a RESET in the same frame still apply, in order, after it (the sibling's rule, 10.5; it is what makes 4.3's "every write complete during frame f MUST be applied" true through a RESET). | |
| 0x3F | `NOP` | — | no effect; exists so the host can read the status word without changing anything | |
| 0x03, 0x07, 0x0B, 0x1B, 0x1F, 0x24–0x27, 0x2C–0x3E | reserved | | ignored, no effect | |
| 0x40–0x7F | drum section | | reserved for the `drums` branch; decoded by the drum block from the same `A`/`D`/`F` | |

### 4. The status word (MISO)

Loaded at the falling edge of `CS_N` and shifted out MSB first during the
transaction, whatever the transaction writes:

```
bits 31:24  ID       0x4D ('M')            constant; the host checks the link at boot
bits 23:20  VERSION  0x1                   this record's register map
bits 19:16  FLAGS    [3] overrun   the datapath was still busy at a frame tick (sticky; a defect, never expected)
                     [2] queue     the write queue was non-empty when the word was loaded
                     [1] overflow  a write was dropped because the queue was full (sticky, cleared by this load)
                     [0] fresh     no write has been accepted since hardware reset
bits 15:0   FRAME    the 16-bit frame counter (frame 0 = the first frame after reset, contract 4.1), wrapping
```

`fresh` lets the MCU detect an unexpected chip reset (brown-out, a watchdog
on the board) and re-send the image; `FRAME` lets a sequencing host phase
itself to the chip's frames if it wants to, without a tick pin.

### 5. Which frame a write lands in

Contract 4.3 defines a write as *received during frame f* by the cycle in
which the core accepts its last unit. For this link:

- **The unit is the transaction, and its acceptance cycle is the core cycle
  in which the synchronised rising edge of `CS_N` is registered with a bit
  count of exactly 32.** That cycle is `c`; the write is received during
  frame f if `tick_f ≤ c < tick_{f+1}`, a transaction accepted in the tick
  cycle belonging to the frame that starts in that cycle — 4.3 verbatim.
- Accepted writes enter a **queue of depth 4** in acceptance order. At each
  tick the queue's occupancy is snapshotted, and that many writes are applied,
  **one per cycle from cycle 2 of the new frame (cycles 2..5 for four), in
  order**, before any datapath block reads a control register (every block
  starts at cycle 8, `synth_top`'s `GO_CYCLE`). A write accepted in the tick
  cycle or later belongs to the new frame and waits for the next tick.
- **The queue cannot overflow within the specification**: at SCK ≤ 2 MHz a
  32-bit transaction plus the CS_N gap takes ≥ 16.3 µs, so at most two
  writes complete in any 20.83 µs frame, against a depth of four. A host
  outside the specification that does overflow it loses the write and sets
  the sticky `overflow` flag; nothing else is disturbed.
- Each write is applied exactly once and atomically — it names one register
  or one action, so atomicity is a single register write.

*Informative:* pin to acceptance is three core cycles (two synchroniser
stages and the edge detector), a constant. Because the pin is asynchronous
to the core clock, a `CS_N` edge within about one core cycle of a frame tick
may be accepted in either frame; the host cannot tell which and the contract
is satisfied either way, since the frame is defined by the acceptance
cycle. The same is true of any physical layer.

*Informative:* a musical event that is several writes — a chord is three
SET_INC and a GATE_ON, a patch change is 34 writes — may straddle a tick, so
its registers change over consecutive frames, 20.83 µs apart at the maximum
rate. That is the ordering rule of 4.3 working as written. A "group commit"
was considered and rejected (Alternatives).

### 6. Power-on defaults — closes 17.8

**Every control register resets to 0, as contract 14 already lists; a bare
GATE_ON is silent.** The sibling's non-zero envelope defaults (its section 9)
exist so that a human sending only NOTE_ON hears something. Here the client
is an MCU with the patch in flash; it writes the whole image at boot (34
writes, 0.54 ms) and again whenever `fresh` reads 1. Non-zero defaults would
cost a set/reset value per register bit for nothing the product uses, and
would put a second, silent copy of "the default patch" in metal beside the
one in the MCU's flash, to drift apart. `WAVE` = 0 means saw (section 3), so
the reset encoding of `wave[k]` is now defined too.

### 7. The cutoff register widths — closes 17.10

`CUT_LO`, `CUT_HI` and `TRACK_HZ` are **16 bits unsigned**, the width contract
5.1 proposed and the model has clamped to since revision 2. The evidence was
already in 5.1 and 5.5: the largest value any host conversion produces is
50 175 (full keyboard tracking at note 127), which fits, and any larger
value is indistinguishable after the clamp of section 10 (30..21 600 Hz). The
sum of section 10 is computed exactly at 19 bits signed before that clamp:
`cut_lo` (16 u) + `(span · fe) >> 15` (span 17 s, so |·| < 2^16) + `track_hz`
(16 u). This record fixes the width because the write format fixes what the
host can send; the arithmetic is unchanged.

### 8. What the MCU does (informative)

USB-MIDI arrives in 1 ms USB frames. The firmware is the reference host of
contract 5.6 (`voice_fx.KeyHost`) plus the conversions of 5.5:

| MIDI | writes |
|---|---|
| note on, no key held | SET_INC k for each oscillator that changes, TRACK_HZ, GATE_ON (single trigger) |
| note on, keys held | SET_INC for the oscillators that change (paraphonic allocation, DR 0003); TRIG if multi-trigger |
| note off, keys remain | SET_INC back to the remaining keys' pitches |
| last note off | GATE_OFF |
| CC 74 / 71 / 5 / 7 … | SET_CUT, SET_LADDER, SET_GLIDE, SET_VOL through 5.5 |
| program change | the patch image, 34 writes |

Worst-case latency from a MIDI event to the sample that reflects it: ≤ 1 ms
(USB) + firmware + 16 µs (one transaction) + ≤ 20.8 µs (the next tick). The
link adds about 40 µs to a 1 ms budget; a 256-frame slice would add up to
5.33 ms, a 480-frame slice up to 10 ms.

## Why, against the two facts

**The MCU-client fact.** An MCU forwarding MIDI has *events* in hand and a
DMA-capable SPI master. Register writes are a one-to-one translation with no
state to maintain on the host; a slice packet makes the MCU keep the whole
image, resend it 187.5 times a second, keep its slice timer phase-locked to
the chip's frame counter (or the packet lands in the wrong slice), and still
encode GATE_ON and TRIG as per-packet edge flags — i.e. as events. The
firmware for the event interface is smaller and has fewer ways to be wrong,
and every 5.33 ms of slice latency is spent on a product whose whole claim
is a playable instrument. The UART's advantages — a human can type at it, a
DIN-MIDI opto feeds it — are advantages for a client this product does not
have; its costs — a baud rate 12.288 MHz cannot divide to (115 200 needs a
divisor of 106.67; the sibling accepts −0.31 % at 107), no framing so a lost
byte desynchronises until the next status byte, 26× less bandwidth than
2 MHz SPI, and a second pin for any readback — are real.

**The paraphonic key model.** DR 0003 made the chip a mechanism and the host
the policy, and made the model's unit of work a sequence of writes. This
record is that sequence on wires: the reference sequences of contract 16 are
executable on the link exactly as the model plays them, frame for frame, and
the bench of 16.2 drives the same write port the queue drains into. A state
model would need a translation layer between the model's writes and the
packets in both directions — in the firmware and in the testbench — and
the translation would be where the timing was lost.

## Alternatives considered

- **SPI time-slice packets (issue 7) at 256 frames.** Kept: SPI, mode 0,
  CS framing, "the last bit before the boundary lands at the boundary".
  Rejected: the state model. It quantises live timing to 5.33 ms by
  construction (my own analysis on issue 7 — 10–20 ms is perceptible in
  ensemble timing, 5.33 ms is not, but 20.8 µs is better for free); its edge
  semantics for percussion and triggers are events anyway; an atomically
  applied whole-image packet needs a shadow image (≈ 0.04 mm² of cells at
  92 µm² per bit before drums; the sibling's 8-deep 35-bit command FIFO
  alone measured 33 505 µm²); and it needs the host's slice clock locked to
  the chip's. What it bought — explicit host-owned timing and a sequencer's
  repeat count — a sequencing host gets from `FRAME` in the status word and
  from timing its own writes.
- **UART event stream (the sibling's section 10).** Rejected for the client;
  reasons above. The sibling keeps it because its client is a human.
- **Raw MIDI in (31 250 baud) with the mapping on the chip.** Rejected: the
  host conversions of 5.5 are float (Hz to increment, seconds to rate,
  `k_onset`), the key policy is the host's by DR 0003, and the MCU is
  already there.
- **Variable-length transactions (address-dependent byte counts).** Rejected:
  a length table in the receiver for a saving of 1–3 bytes per write when
  the link has 26× the bandwidth it needs; fixed 32 bits is one shift
  register, one counter, and DMA-friendly.
- **A "hold" bit for group commit** (writes marked hold apply together with
  the next unmarked one). Rejected: the queue would have to hold a whole
  patch — 34 × 32 bits, on the order of 0.1 mm² at the FIFO's measured
  120 µm² per bit — to make a 20.8 µs skew that no one can hear atomic.
- **An asynchronous SPI slave clocked by SCK** with a CDC handshake into the
  core. Rejected: a second clock domain, constraints and a synchroniser for
  every completed word, for an SCK ceiling the product does not need; the
  synchronous receiver has none of that and reaches 3 MHz.
- **Non-zero power-on defaults.** Rejected, section 6.
- **A frame-tick output pin.** Rejected: `FRAME` in the status word serves a
  sequencing host, and the I2S `LRCLK` *is* the frame clock on a pin already.

## Consequences

- Contract 5.2 (encodings), 5.4 (physical layer: this record), 14 (`wave`
  reset encoding; RESET leaves the link and queue alone), 17.3, 17.8 and
  17.10 change; revision 4. Sections 4.3 and 16 are unchanged and are what
  this record implements.
- The register-level write port of contract 16.2 is the queue's output:
  `{valid, F, A[6:0], D[23:0]}`, one per cycle from cycle 2 of a frame. A
  bench drives it directly (`rtl-sketch/tb_voice.v`, which is how the voice
  was shown bit-exact); the SPI receiver is exercised separately by driving
  the pins (`tb_synth_top.v`).
- `DVOL`, `ROUTE` and the drum filter's `DCUT`, `DK`, `DGAIN`, `DOGAIN` are
  new registers (the master mix and the drum routing of ARCHITECTURE.md
  section 4); they are not in the revision-3 voice and are proposed with it.
  The drum bus itself is 19 bits, Q4.15, at the master mix (ARCHITECTURE.md
  section 4), so `DVOL` scales a word with headroom, not a clipped one.
- The drum section decodes addresses 0x40–0x7F from the same port; what
  they mean is the `drums` branch's record.
- RTL: `rtl-sketch/spi_ctl.v` (receiver, queue, status word, drain), driven
  by `rtl-sketch/tb_synth_top.v` through the pins. Measured there:
  pin-to-acceptance 3 cycles; a queued write is applied in cycle 2; the
  status word reads back `0x4D110001` on the first transaction after reset.
- Board: the 12.288 MHz core clock cannot come from the MCU's own crystal
  (USB needs 48 MHz and 48 : 12.288 = 125 : 32), so it is a separate
  oscillator or crystal on the board; that is ARCHITECTURE.md's clock
  section, not this record's.
