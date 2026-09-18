# The target

**A complete TR-808 and a complete monophonic three-oscillator Minimoog-style
synth, with automated sound validation throughout development.**

Versioned intermediate builds — v0.3's three notes and eight drums, and the
ones after it — are **checkpoints toward that instrument, not the goal.**
`docs/v0.3-scope.md` freezes one such checkpoint and should be read as one.

Three oscillators is the target for the voice and is faithful: the Model D has
three VCOs. Paraphony is a separate question and is not part of this.

## The distinction that governs everything below

**Testing the implementation and testing the sound model are different things,
and this project has only ever done the first properly.**

| | question | what we have |
|---|---|---|
| implementation | did we build the model we specified? | **strong** — RTL bit-exact against Python at every block and at the chip's pins |
| sound model | is that model the instrument we want? | **drums: yes. voice: nothing.** |

`model/test_moog_acceptance.py`'s 42 tests check the voice against **our own
decision records**. They prove we built what we said. Nothing has ever checked
that what we said is a Minimoog. The drum side has `docs/tr808-reference.md` —
110 facts traced to schematics and service manuals — plus a real TR-808
recording corpus. **The voice has no equivalent of either.** Closing that is
workstream 1.

## What the automated acceptance suite must cover

| area | what automation checks |
|---|---|
| **Complete 808** | every sound and control works; attack shape, pitch movement, noise/body balance, decay, accent, and voice interactions match **declared targets** |
| **Mono synth** | oscillator tuning and spectra, detuning, mixer drive, filter response and resonance, envelopes, glide, note handling |
| **Combined instrument** | concurrent drums and bass, mix headroom, control changes mid-note, complete releases, reset and return to silence |
| **Hardware** | integrated RTL matches the numeric contract at I²S; the FPGA meets timing and produces the expected physical output |

**Every sound-changing commit generates measurements and regression results.**
An agent should receive *"snare noise is too quiet"* or *"decay shortened
outside tolerance"* with the supporting numbers — not a pass/fail. And
**known-broken variants must fail the relevant tests**: a report that cannot go
red is decoration. This repository has already shipped one negative control
that mutated a function signature into invalid Python and "passed" by proving
that Python rejects syntax errors.

Report **per voice and per behaviour, never as a single aggregate.** An overall
improvement must not be able to hide a worse snare.

**FAD may supplement the comparisons; it must not be the sole acceptance
score.** Its results depend on sample size, embedding choice and reference
selection ([arXiv:2311.01616](https://arxiv.org/abs/2311.01616)). Where used,
report it alongside per-voice measurements with the embedding and sample count
stated.

## Reference material, and how to get it

**Software references, available now.** Surge XT, Arturia Mini V3 and u-he
Diva, driven at matched documented settings. Surge XT is the most valuable: it
is open source and its Vintage Ladder implements the **same Huovilainen
DAFx-04 model we implemented**, so a disagreement is an implementation bug
rather than a difference of modelling taste. An earlier version of
`docs/discrimination.md` §8 rejected software references as "testing our chip
against another emulation" — that purity argument produced **zero validation
instead of imperfect validation**, and it discarded the one thing a hardware
corpus cannot give: **a reference you can set to a known patch.**

**Hardware references, from a prescribed session.** A friend with a real Moog
can produce a reusable automated reference set in one short sitting, but only
if the session is specified: exact model and serial, **panel settings recorded
for every take**, dry output with no effects, several repeated examples per
setting, and **some settings reserved for evaluation rather than tuning** so a
genuine held-out set survives. Different Moog models stay separately
identified — a Sub 37 is not a Model D — and are never pooled.

It must include **self-oscillation at several documented cutoff positions**:
`model/moog_probe.py` is built and calibrated, its discriminator is h5 relative
to h3, and it runs the moment a qualifying clip exists. Legowelt's 222 WAVs
ship no panel settings, so **0 of 222 qualify** and DR 0001 still rests on
circuit derivation alone.

**Sending someone a WAV and asking "is this good" is not a test.** It is
unblinded, single-rater, and shaped by demand characteristics. A prescribed
recording session is data collection. A listening opinion is a different thing
and belongs at the end — deciding whether the instrument is musically
compelling, not debugging it.

## Execution

| workstream | owns |
|---|---|
| **1. References and evaluation** | fixtures, measurements, failure controls, per-commit reports |
| **2. Complete 808** | the three missing circuits, and correcting existing voices against the suite |
| **3. Complete mono synth** | noise source, oscillator 3 as modulator, the full waveform set, modulation mix |
| **integration** | the combined FPGA build and host controls keep working as the above land |

The friend-facing release carries the full sound set, playable controls, proper
audio output, and a compact comparison pack. **Their audition decides whether
it is musically compelling. Routine debugging stays in the automated
process.**

## What each workstream is missing today

**808** — three circuits: mid conga/tom, claves/rim shot, cymbal. Cost
measured at **+4.5 % on `drum_kit`** (MODES 16 / NUMS 11 at 630,433 µm²
against 603,118), and the completed configuration has been **routed on an
ECP5 with 41 % of the logic still free.** The constraint is `NUMS`, not
`MODES`: `modal_dp` gives a numerator only to modes below `NUMS`, the kit runs
`NUMS = 6` with modes 0–5 as its six filters, so the filter half is full and
the cymbal needs a filter.

**Mono synth** — three gaps, each of which a player would notice:

1. **No noise source at all.** The Model D mixer has five sources: three
   oscillators, noise, and external. Noise through the ladder is a signature
   sound. The drum section already has an LFSR that may be shareable.
2. **Oscillator 3 cannot modulate.** Switching osc 3 out of the audio path to
   drive pitch and filter is a defining Minimoog feature — it is where vibrato
   and filter wobble come from.
3. **The waveform set is incomplete.** The Model D has six per oscillator;
   we have four.
