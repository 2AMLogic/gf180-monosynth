# 0002: The product this block is for — a bus-powered, class-compliant sound module

- **Status**: proposed
- **Date**: 2026-09-17
- **Decided by**: block agent, from market research; endorsed in conversation by the program sponsor

## Context

A block designed without a product ends up with the wrong constraints. This
record fixes the ones that matter, because several are already load-bearing on
the RTL: whether there is a battery decides whether there is power management;
whether the host is a PC or a phone decides the control interface; whether it
fits on a keychain decides pin count and die area.

The market position, researched rather than assumed:

**The gap is not "no good small synths."** There are many and they are
excellent — MicroFreak at €289, Minilogue XD at €555, NTS-1 mkII at ~$149,
monotron at ~$50, Pocket Operators at $59–89. Competing with those on features
is a losing game.

**Two specific things are missing.**

1. **The ladder filter is still priced as a premium analog feature.** In 2026
   the cheapest new Moog with one is the Messenger at €611, and the trade press
   frames that as a breakthrough in affordability.
2. **Bus-powered, class-compliant synth *modules* barely exist.** Controllers
   are bus-powered. Interfaces are bus-powered. Synths are not — they almost
   all want their own supply. That slot is close to empty.

Separately, that a sound chip can hold value for decades is not speculation:
the MOS 6581 SID still sells for up to $40 a chip forty years after production
ended, with an aftermarket large enough to attract counterfeiters, and every
modern replacement (SwinSID, ARMSID, FPGA recreations) is an *emulation*.
Nobody makes new sound-chip silicon.

Hardware synthesizers are roughly a $712M/year market. Note that the market
reports disagree badly with one another across overlapping categories, so that
figure is an order of magnitude, not a measurement.

## Decision

The block targets a **USB-C bus-powered, class-compliant MIDI sound module,
keychain sized**. Plug it into a laptop, a phone or a tablet; it enumerates
with no driver; play it from any MIDI source.

Four constraints follow, and they are binding on the design:

- **No battery.** The chip plus DAC plus USB front end is on the order of tens
  of milliamps against USB 2.0's guaranteed 500 mA — about 3 % of budget. A
  LiPo would add a charge controller, a protection circuit, lithium **shipping
  restrictions** and safety certification, and would buy something only while
  untethered — which is also when there is no MIDI, and therefore no notes. A
  battery would purchase a worse instrument.
- **Class compliant, so a small MCU owns USB.** Our block does not implement a
  USB device stack. A CH552 (~$0.30, native USB, proven class-compliant MIDI
  firmware) or an RP2040/RP2350 ($1.00/$0.80) is the front end; it converts
  USB-MIDI to the block's control interface and does no synthesis.
- **Capacitive touch is a bonus, not the interface.** Since the host supplies
  notes over USB, the 568-cell touch block earns its place only if the board
  has room — filter control without reaching for the computer.
- **Mono or paraphonic, not polyphonic.** Every instrument in this class is
  monophonic, and the instrument being evoked is too. An earlier measurement
  showed four independent filters would fit the clock budget (80 of 256
  cycles); this record says that capacity should not be spent, on musical
  grounds rather than budget ones.

## The honest problem with this decision

**At this volume, a microcontroller alone would be cheaper and sufficient.**
An RP2040 has enough cycles to run this entire instrument in software — the
ladder is about 20 operations per sample, and 48 kHz leaves a lot of room at
133 MHz. It would also handle the USB itself, removing a part rather than
adding one. Anyone evaluating this product honestly will notice.

Three things are actually true in the ASIC's favour, and one commonly-claimed
thing is not:

- **Not true:** that the DSP needs an ASIC. It does not. Claiming so would be
  refuted by anyone with a Pico and an afternoon.
- **Power.** A 12.288 MHz block on gf180mcu is on the order of 10 mW against
  roughly 100 mW for an MCU running flat out. That is a real advantage, and it
  matters more in whatever this becomes next than it does on USB power.
- **The chip is the product; the keychain is the proof.** The durable asset is
  a synth voice someone else can design in, which is exactly what the SID
  aftermarket demonstrates people want and cannot buy.
- **A verified block is the company's actual business.** This block exists to
  exercise `klayout-tools` and produce tier evidence. The instrument is the
  demonstration vehicle, and it should be honest about that rather than pretend
  the economics drive it.

The differentiating claim is therefore **not** performance. It is that this
would be the first sound chip with an **executable specification**: a frozen
numeric contract, SHA-256-pinned tables, a reference model that *is* the spec,
and RTL verified bit-exact against it. SID's behaviour was never specified — it
was discovered, and emulator authors still argue about its filter. Software
could be written and tested against this chip before the silicon exists, and
the silicon would be guaranteed to match.

## Consequences

- No power-management design, no charger, no battery certification, no lithium
  shipping constraints. The board is a regulator, the MCU, the block and a DAC.
- The control interface must suit an MCU bridge rather than a human — which
  makes the SPI time-slice proposal in `gf180-polysynth#7` a better fit than
  rev 1's UART event stream, and that proposal should be read with this
  product in mind.
- Pin count is a hard constraint, not a soft one. A keychain cannot host a
  parallel memory bus, so any delay-line engine must use QSPI (6 pins) or be
  dropped. The modal resonator needs no memory at all and is unaffected.
- The first physical version is an FPGA on a development board, not this. The
  ASIC replaces the FPGA later, running the same RTL against the same contract.
  The MCU stays in both.
- This constrains the block toward an instrument and away from an
  input-driven effect. A microphone-driven toy is a different product and
  would reopen this record.
