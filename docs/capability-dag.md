# The capability DAG

One capability at a time, stamped before the next — the way torchsynth was
built. But **not a ladder**: the 808's voices are independent of each other and
of the Moog, so the real structure is a directed graph, and the useful question
at any moment is "which nodes are unblocked right now".

## Why, specifically here

Every voice and every routing path multiplies the state space, so the cost of
establishing that a thing works grows faster than the thing itself. Two
measured facts from this repository:

- Every block is bit-exact against its model. **Two integration bugs still
  shipped** — a drum mix fault and a cowbell gating fault — both found by
  listening, not by any test.
- Six measurement claims here have been confidently wrong. One ("1,917 cells")
  was quoted three times before anyone noticed every output was X.

A stamped node is a place you can always return to, and a regression suite that
keeps running forever. Nodes are never un-stamped and their tests are never
deleted.

## What "stamped" means

All five, or it is not stamped. Four out of five is not a node.

1. **Tagged** — annotated git tag, `node/<id>`. Three exist:
   `node/F1-ladder`, `node/M1-voice`, `node/M2-minimoog`.
2. **A named test set, green, in CI on every push** — no path filter.
3. **Negative controls carried** — an injected defect that turns each property
   red. A test that has never failed is not evidence.
4. **Area measured**, labelled *cell* / *synthesized* / *routed*. Those are
   three different numbers and this repo has conflated them.
5. **A written statement of what the node does NOT cover.**

## The graph

```mermaid
graph TD
  F3[F3 measurement ground truth] --> M2 & DAUD[per-voice audio]
  F1[F1 ladder bit-exact] --> M1 & P1
  F2[F2 modal bank bit-exact] --> D0
  M1[M1 one Moog voice bit-exact] --> M2[M2 Minimoog acceptance]
  M2 --> M3[M3 vs real hardware]
  M2 --> P1[P1 channel independence]
  M3 --> P2
  P1 --> P2[P2 paraphonic musical behaviour<br/>NEEDS LISTENING]
  D0[D0 excitation shaping<br/>the ~90% term] --> DCOEF[per-voice coefficients]
  DCOEF --> DAUD --> DHW[per-voice vs hardware]
  DHW --> DL[DL full 16-voice library]
  DL --> I1
  P2 --> I1[I1 mix bus + master clamp]
  I1 --> I2[I2 SPI] --> I3[I3 I2S vs the MODEL] --> I4[I4 full chip bit-exact]
  I4 --> S1[S1 synthesis] --> S2[S2 P&R + DRC] --> S3[S3 STA closed]
```

## Foundation and Minimoog

| node | capability | status |
|---|---|---|
| F1 | Ladder filter, bit-exact | verifier green — stamping |
| F2 | Modal bank, bit-exact | on `drums`, PR #14 |
| F3 | Measurement library ground truth, 60 tests | **green on main** |
| M1 | One Moog voice, bit-exact, 255,060 frames | verifier green — stamping |
| M2 | Musically a Minimoog, 42 tests, 6 injected defects | **green on main** |
| M3 | Ladder structure vs real hardware | **BLOCKED** |

**M3 is blocked on one input, not on work.** `model/moog_probe.py` is built and
calibrated: the discriminator is **h5 relative to h3** (not h2 — `tanh` is
odd-symmetric, so h2 is absent in both our every-stage structure and the
one-tanh alternative, and a probe built on h2 would measure nothing). It
separates the two structures by 25 dB. But **0 of 222 Legowelt recordings
qualify** — 80 are odd-symmetric oscillator waveforms, 27 are near-sine but
carry even harmonics at or above their odd ones. It needs **one clip of a real
Minimoog filter self-oscillating**. Until then DR 0001 rests on circuit
derivation alone.

## Paraphony — and we have THREE oscillators, not four

| node | capability | status |
|---|---|---|
| P0 | A **fourth** oscillator exists | **not built** |
| P1 | The channels are genuinely independent | **untested** — issue #20 |
| P2 | Paraphony sounds right | **no automated criterion exists** |

**P0 is implementation work, not verification work, and this document
previously got it wrong.** `model/voice_fx.py:533` builds
`[OscFx(...) for _ in range(3)]`, and `sounding()` maps held keys to slots with
`[held[i] if i < len(held) else held[-1] for i in range(3)]` — so a fourth held
key is **never sounded**. What we have is *three*-note paraphony.

Three is the faithful Minimoog number (it has three VCOs), so this is not a
defect; it is a gap against the stated four-note target in issue #23.

`NV=4` is a different axis entirely: four **filter/channel contexts**, not four
oscillators. Conflating the two is what produced the earlier claim that
four-note paraphony merely needed testing. Four separately pitched oscillators
into one shared filter is the instrument we want — not four filters.

P1 is mechanical and can be done today. `rtl-sketch/tb_ladder_n.v:59-61`
assigns `x_in` *outside* the per-channel loop, so every channel receives
identical stimulus — a bug where channel 2 leaked into channel 3's state would
pass, because the channels would agree anyway. `synth_core` at `NV=4` routes
(1.079 mm², 0 DRC) and therefore looks finished. It is not.

**P2 cannot be automated and we should stop pretending otherwise.** Four notes
sharing one filter is a musical compromise, not a specification: whether it
sounds like an instrument or like a fault depends on voice allocation, note
stealing, and what the shared cutoff does to a held chord. There is no
reference recording, because the Minimoog is monophonic and never did this.
M1–M3 come first so that when P2 sounds wrong we know the voice itself is
right. The listening protocol P2 needs is not yet written.

## Drums, per voice

Shared first, but **D0 is a hypothesis to test on one voice, not a fix to
apply to all of them.** The discrimination study's classifier looks only at the
first 240 ms and finds most of its signal in the attack; that makes the attack
a promising target. It does **not** establish that the attack accounts for 90 %
of *audible* error — feature importance inside a 240 ms window is not
audibility, and two versions can both score 1.000 separable while one sounds
much better. An earlier draft of this document stated the stronger claim; it
was not supported.

What *is* supported: the fixes `docs/drum-verification.md` prescribes leave the
kit separated at 1.000, so they are not sufficient on their own; and the 808
acceptance suite independently finds the BD attack window simply absent (§2
wants ≈130 Hz for 4 ms). So: shape the excitation on **one** voice, compare
before and after by ear and by measurement, and extend it only where it helps.
It is an envelope change, so nearly free in area.

Each voice needs three things, deliberately separate so a failure localises:
**(a) coefficients** — read back and converted to (f0, τ) with no audio at all;
**(b) audio** — measured against a cited reference fact; **(c) hardware** —
against a real recording, where one exists.

| # | circuit | built | a. coef | b. audio | c. hardware | note |
|---|---|:-:|:-:|:-:|:-:|---|
| 1 | BD bass drum | ✓ | ✓ | **red** | 3.6 | no attack window; §2 wants ≈130 Hz for 4 ms |
| 2 | SD snare | ✓ | ✓ | ✓ | **red** 8.8 | 3 % of energy >700 Hz vs a real 51.5 % |
| 3 | **LC / LT** low conga *or* low tom | ✓ | ✓ | **red** | 7.1 | have LT; no pitch drop (§4) |
| 4 | **MC / MT** mid conga *or* mid tom | — | — | — | — | **missing** |
| 5 | **HC / HT** hi conga *or* hi tom | ✓ | ✓ | **red** | 6.0 | have HT; no pitch drop (§4) |
| 6 | **CL / RS** claves *or* rim shot | — | — | — | — | **missing**; one bridged-T |
| 7 | **MA / CP** maracas *or* hand clap | ✓ | ✓ | ✓ | n/a | have CP; no knob → no held-out setting |
| 8 | CB cowbell | ✓ | ✓ | ✓ | **red** | τ 26 ms vs a real 98 ms |
| 9 | CY cymbal | — | — | — | — | **missing**; shares the hats' six squares |
| 10 | OH open hat | ✓ | ✓ | ✓ | 6.9 | |
| 11 | CH closed hat | ✓ | ✓ | ✓ | n/a | no knob → no held-out setting |
| — | DL full library | — | — | — | — | simultaneity and mix, after all circuits |

**The 808's sixteen sounds are eleven circuits, in five exclusive pairs.** The
paired voices are the *same circuit retuned* and cannot sound simultaneously —
verified from Roland's own TR-08 instrument listing, which still groups them in
exactly those pairs thirty-five years later, and consistent with the original's
panel. This matters enormously for a shared modal bank, which needs a mode per
*concurrent* voice rather than per named sound.

**So we have 8 of 11 circuits, and a complete 808 is +3, not +8.** Missing:
the mid conga/tom, the claves/rim shot, and the cymbal. Adding the second half
of each pair we already own (LC, MC, HC, CL or RS, MA) is a coefficient preset,
not a mode.

Precedent for shipping fewer: Roland's own **T-8** ships six drum voices and
Roland chose which six; **Korg volca beats** bought five analog voices and
sampled everything else; the **TR-6S** has six assignable parts. Six
simultaneous drum parts is a shipped product more than once.

The hardware column is **knob-equivalent separation out of 10**: how far the
real machine's own knob must travel before it looks this different from itself.
It is not an accuracy. Three voices (CH, CP, CB) have no knob, so the corpus
cannot adjudicate them at all — the cowbell is documented wrong and
*unconfirmable* here. LT/HT/OH have only 2 held-out settings, below what
excludes chance. And there is **no real-vs-real floor** in this dataset.

Three of eleven circuits are missing, and the cymbal can share the hats' six
square oscillators (205.3/369.6/304.4/522.7/800/540 Hz). The full library is
**+3 circuits**, which is a far smaller ask than the "+5 to 7 modes" an earlier
draft of this document guessed at from the sixteen-sound count.

## Integration and silicon

| node | capability | status |
|---|---|---|
| I1 | Mix bus and master clamp | |
| I2 | SPI control, including a write landing mid-sample | |
| I3 | I2S **compared against the model**, not the DUT | see below |
| I4 | Full chip bit-exact | first run came back **red** |
| S1 | Synthesis | 925,387 µm² cells, 55.3 % util pre-placement |
| S2 | P&R, DRC | running |
| S3 | STA closed at every corner | |

I3 is called out because the existing top-level test compares the I2S stream
against the DUT's *own* sample stream, which is circular: it cannot detect a
bit-shift or a channel swap, which is exactly the bug that shipped broken in
trial1.

## Releases: each one a smaller instrument that already works

The DAG says what *depends* on what. It does not say what to ship. These are
the release gates, and the discipline belongs here rather than on every
exploratory task — an agent chasing a measurement does not need a milestone.

| release | what must work | gated on |
|---|---|---|
| **v0.1 known baseline** | The existing voice, its controls and its audio output reproduce from a clean checkout. **The actual note count is stated, not implied.** | F1, M1, M2 — all green |
| **v0.2 lead** | Four distinct pitches, a defined note-allocation and retrigger behaviour, one shared filter, and a verified per-sample cycle deadline | P0, P1 |
| **v0.3 lead + the eight drums we have** | Real drums integrated; solo hits and a combined groove; accent, choking and mixing all correct | D-coef/audio for 8 voices, I1 |
| **v0.4 complete 808** | The missing voices added **in small groups**, every earlier check still green | the per-voice table |
| **v0.5 extensions** | Extra routing and experimental voices, each with an audible reason to exist | — |

Every release preserves **the exact source revision, the configuration, the
test results and a short audio demo**. FPGA, board and ASIC evidence are
recorded separately: a verified RTL version is worth having before a board
exists.

The immediate goal is **one reproducible version that is enjoyable to play**,
then small additions whose benefit can be heard and whose behaviour can be
verified.

## The rule, and where we stand against it

> **Do not start a node until its predecessors are stamped.**

We have been working on drums, integration and silicon with F1, M1, M2 and P1
all unstamped. There were **no git tags in this repository at all** until now,
and CI ran one of four suites — path-filtered so that an RTL change could not
turn it red.

**Stamped:** F1 (28,800 samples, 0 mismatches), M1 (255,060 frames, every tap
and the final state), M2 (42 tests, 6 injected defects).

**Unblocked right now:** P0 — build the fourth oscillator, because v0.2 cannot
be described honestly without it. Then P1 (mechanical, issue #20), then D0 on
one voice (issue #21). M3 needs one audio clip from outside. P2 needs a
listening protocol that does not exist yet.
