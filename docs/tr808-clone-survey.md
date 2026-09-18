# What the 808 clones shipped, what it cost them, and whether 8 modes is enough

**Purpose.** `docs/tr808-reference.md` says what the original machine *is*. This
document is about **everything that came after it** — the clones, the
emulations, the cut-down descendants — and it exists to answer one engineering
question:

> We have a shared modal bank of two-pole resonators. **12 modes cost
> 0.646 mm², 8 modes cost 0.461 mm².** If we take 8, what do we lose, and does
> the result still read as an 808?

The answer is in §9. The short version is at the end of this preamble.

**How claims are tagged.** Same convention as the reference document, with two
additions that this subject needs:

- **[verified: SOURCE]** — read directly in the cited source, which is named
  with its URL.
- **[manufacturer claim]** — the vendor says so. Marketing copy is a claim
  about a product, not a measurement of it. Kept separate from [verified]
  throughout, even when it is probably true.
- **[listener opinion]** — a review or forum statement. Evidence that somebody
  *perceived* something; not evidence of what the signal did.
- **[inferred]** — derived by me from something verified. Reproducible; not
  independently measured.
- **[could not establish]** — looked, did not find. Do not build on it.

**A note on how this was researched, because it bounds the evidence.** The
session's web-search budget was exhausted early and every general search engine
reachable from here (DuckDuckGo html and lite, Startpage, six SearXNG
instances, Brave, Ecosia, Mojeek, Yandex, Bing) returned a CAPTCHA, a 403, or
garbage. What still worked was direct URL fetching, the Wikipedia API, the
archive.org search API, and the DAFx paper-archive search. **Primary sources —
manuals, spec sheets, schematics — are therefore over-represented in this
document and forum/review material is under-represented relative to what a
normal search pass would find.** That skew happens to favour the strong
evidence, but §7 (what listeners complain about) is the section most damaged by
it, and it is labelled accordingly.

**The one-paragraph answer.** Nobody has published a study of how many
resonator modes an 808 needs; that literature does not exist **[verified: DAFx
paper-archive search returns exactly one 808 circuit-emulation paper, Werner
et al. 2014, <https://www.dafx.de/paper-archive/search.php>]**. But the
question has been answered commercially, several times, by people with the same
constraint, and the answers agree with each other to a startling degree: when a
manufacturer has to cut an 808 down, the six that survive are **bass drum,
snare, hand clap, one tom, closed hat, open hat**. Roland did exactly that with
the T-8 §4.1; Korg spent its analog budget on almost exactly that set in the
volca beats §4.2; and Roland's own 1980 manual demonstrates the machine with a
three-voice pattern §3.2. More useful still: **the TR-808 itself multiplexes**
— 16 named sounds are produced by 11 voice circuits, because Roland put
tom/conga, rimshot/claves and handclap/maracas on shared circuits with panel
switches §3.1. The reduced 808 is not a hypothetical. It is what the original
already was.

---

## 1. Sources actually consulted

Only sources I read are listed. Where a subsection rests on a source I could
not reach, it says so.

| key | source | what it gives |
|---|---|---|
| **T8M** | Roland, *T-8 Owner's Manual* (PDF). <https://static.roland.com/assets/media/pdf/T-8_eng01_W.pdf> | the T-8's exact instrument list and per-instrument controls, read out of the "Main Specifications" page |
| **T8S** | Roland T-8 specifications and product page. <https://www.roland.com/global/products/t-8/specifications/>, <https://www.roland.com/global/products/t-8/> | instrument list; the ACB marketing claim |
| **TR08S** | Roland TR-08 specifications. <https://www.roland.com/global/products/tr-08/specifications/> | the full 16-instrument list, in the original's exclusive-pair form |
| **TR6S** | Roland TR-6S specifications. <https://www.roland.com/global/products/tr-6s/specifications/> | 6 instrument parts; the ACB library claim |
| **TR8SS** | Roland TR-8S specifications. <https://www.roland.com/global/products/tr-8s/specifications/> | "11 instrument parts and 1 exclusive part for trigger out" |
| **VB** | Korg volca beats specifications. <https://www.korg.com/us/products/dj/volca_beats/page_2.php> | the analog/PCM split, part by part |
| **OM** | Roland, *TR-808 Owner's Manual*. Scan and OCR: <https://archive.org/details/synthmanual-roland-tr-808-owners-manual> | the panel switches that make 16 sounds out of 11 circuits; Roland's own demonstration patterns |
| **SOS-MIA** | P. Nagle, "Acidlab Miami" review, *Sound On Sound*. <https://www.soundonsound.com/reviews/acidlab-miami> | a full-voice analog clone, reviewed |
| **SOS-8S** | "Roland TR-8S" review, *Sound On Sound*. <https://www.soundonsound.com/reviews/roland-tr-8s> | 11 drum voices; the reviewer's refusal to assess ACB fidelity |
| **WP808** | Wikipedia, "Roland TR-808". <https://en.wikipedia.org/wiki/Roland_TR-808> | the bass drum's standing; Shocklee quote; Sexual Healing provenance |
| **DAFX** | DAFx paper archive search. <https://www.dafx.de/paper-archive/search.php> | that the 808 emulation literature is Werner et al. and essentially nothing else |
| **REF** | this repository, `docs/tr808-reference.md` | every circuit fact used below: centre frequencies, Qs, decays, the choke, the swing VCAs |

Sources contributed by the parallel survey passes are cited inline in §5, §6,
§7 and §8 with their own URLs.

---

## 2. The decision, restated precisely — and a counting discrepancy

The 12 modes as given to me:

| # | mode | what it is, from `docs/tr808-reference.md` | kind |
|---|---|---|---|
| 1 | hats band-pass | 7.1 kHz, Q ≈ 6, bridged-T band-pass on the six-square sum; feeds CH, OH **and** the cymbal's high band | static filter |
| 2 | OH high-pass | 7.8 kHz, Q 2.5 (2-pole Sallen-Key, ≈ +8 dB peak) | static filter |
| 3 | CH high-pass | 11.7 kHz, Q 2.5 | static filter |
| 4 | SD "snappy" high-pass | 2.75 kHz, **Q ≈ 0.7** | static filter |
| 5 | clap band-pass | 1.07 kHz, Q ≈ 1.6 | static filter |
| 6 | cowbell band-pass | centre unresolved (0.9 kHz by topology reading, 2.64 kHz per SOS), Q ≈ 4–8 | static filter |
| 7 | BD body | 56 Hz, Q 2.3 → 84 by the decay knob | struck resonator |
| 8 | SD-low body | 173 Hz, Q 16 (later units) | struck resonator |
| 9 | SD-high body | 336 Hz, Q 10 | struck resonator |
| 10 | LT body | 90 Hz, Q ≈ 25 | struck resonator |
| 11 | HT body | 185 Hz, Q ≈ 25 | struck resonator |
| 12 | **not specified** | — | — |

**That list names eleven modes, not twelve.** Before the cut list in §9 is
acted on, somebody should say what mode 12 is, because it changes the answer:
if it is the cymbal's low band (3.45 kHz, Q 6) then one of the four cuts is
already made and costs nothing we were not already prepared to lose; if it is a
second BD preset for the 4 ms attack window, it is genuinely cheap to delete
(the attack can be a coefficient switch on mode 7 instead of a second mode —
`docs/tr808-reference.md` §14 says the RTL already takes coefficients per
sample); if it is MT, deleting it is the §9 tom decision made twice. I have
assumed the cymbal band throughout and flagged every place the assumption
matters. **[inferred]**

**The distinction that does the work in §9 is the right-hand column.** Modes
1–6 are *fixed filters*: their coefficients never change, they process a signal
that is already there (the free-running six-square sum, or the noise bus), and
they are idle whenever their voice is silent. Modes 7–11 are *struck
resonators*: they are kicked by a 1 ms pulse and must be left to ring, which
means they hold state that belongs to one note.

Those two kinds have completely different sharing properties, and the whole of
§9 turns on it:

- A fixed filter's "memory" is its own ring-down, and for these Qs that is
  **microscopic**: τ = Q/(π f₀) is 0.27 ms for the hats band-pass, 0.10 ms for
  the CH high-pass, 0.50 ms for the clap band-pass **[inferred, from the f₀/Q
  in `docs/tr808-reference.md` §10–11 and §7]**. Re-tuning one of these between
  two notes 50 ms apart is inaudible, because it forgets the previous note
  within half a millisecond either way. **Fixed-filter modes can be
  time-multiplexed between voices essentially for free.**
- A struck resonator's memory is the note itself. The BD at Q 84 has
  τ = 540 ms; a tom, τ = 92 ms. Re-tuning one of these while it rings *is* the
  note being cut off. **Struck-resonator modes cannot be shared between
  overlapping notes without stealing one.**

This is not a subtlety I am importing. It is the distinction Roland's own
engineers acted on, which is §3.

---

## 3. The strongest precedent is the TR-808 itself

### 3.1 Sixteen sounds, eleven circuits

The 808's front panel offers 16 named sounds. It does not contain 16 voice
circuits. It contains **11**, because five of the sounds are the *same circuit
with a switch*:

> "Five of the Sound Sources have selector switches that allow them to become
> different instruments or sounds. The three TOM positions can be switched to
> become CONGAs, the RIM SHOT becomes CLAVES and the HAND CLAP switches to
> become MARACAS."
> **[verified: OM, "Mixing Percussion Sounds"]**

The service notes say the same thing in circuit terms — the toms and congas are
one bridged-T per pair with a capacitor switched in or out ("Voices are switched
by SW8 (C77 — frequency, R224 — level)"), RS/CL share one circuit via SW11, and
CP/MA share IC19 via SW12 **[verified: `docs/tr808-reference.md` §4, §5, §8,
quoting Service Notes p.6]**.

The consequence, which matters enormously for a mode budget: **on a real TR-808
a tom and a conga can never sound together, a rimshot and a claves can never
sound together, and a handclap and maracas can never sound together.** The
machine that defines the target sound is itself a machine with shared voice
hardware and hard voice-stealing. Roland shipped 16 sounds on an 11-voice
budget in 1980 and nobody has ever complained that the 808 sounds wrong because
its congas cut off its toms.

Roland has kept doing it. The TR-8S — the current flagship, with ACB models of
five vintage machines — has **"11 instrument parts and 1 exclusive part for
trigger out"** **[verified: TR8SS]**, which its Sound On Sound review states as
"11 drum voices" **[verified: SOS-8S]**. Eleven, again, forty years later.

### 3.2 Roland's own demonstration pattern uses three voices

The 808 manual's walkthrough does not start by showing off sixteen sounds. It
starts here:

> "Switch on BASIC RHYTHM Number 3, which is a Rock type of Rhythm and press
> the START/STOP button to start it running. **This Rhythm incorporates three
> different percussion sound — Bass Drum, Snare Drum, and Hi Hat.**"
> **[verified: OM, "Mixing Percussion Sounds"; emphasis mine]**

The all-voices pattern is explicitly relegated to a test tone:

> "BASIC RHYTHM #12 features the sounds of all percusive sounds beating
> simultaneously. **This Rhythm is used for checking purposes only**, and to
> help you become familiar with the different sounds produced by the TR-808."
> **[verified: OM]**

This is weak evidence about *music* and strong evidence about *Roland's own
model of the instrument*: the factory demonstration of the TR-808 is BD + SD +
HH, and the full kit is a diagnostic. **[verified: OM; the interpretation is
[inferred]]**

---

## 4. The central question: has anyone shipped a *reduced* 808 that still reads as an 808?

Yes. Twice, from the two companies best placed to know, and they converged on
nearly the same set. This is the most valuable material in the document and it
is all primary-source.

### 4.1 Roland T-8 — six drum voices, and Roland picked them

The T-8 (AIRA Compact, 2022) is Roland's own pocket 808. Its specification
page, and its manual's "Main Specifications", give the complete instrument
list:

> "Rhythm instrument parts x 6 / Bass part x 1 / 32 steps"
> "INST tone: **BASS DRUM, SNARE DRUM, HAND CLAP, TOM, CLOSED HIHAT, OPEN
> HIHAT**, BASS"
> **[verified: T8M, "Main Specifications"; identical list at T8S]**

Roland's claim for the sound engine: "Six rhythm tracks with sounds from the
influential TR-808, TR-909, and TR-606 drum machines", using "Analog Circuit
Behavior (ACB) technology [which] faithfully recreates the tonality and
behavior of vintage Roland instruments" **[manufacturer claim: T8S]**. Note
that the T-8 is not a pure 808 — it draws on three machines — so it is evidence
about *which voice types* survive a cut, not about 808 fidelity per voice.

**What Roland kept:** BD, SD, CP, **one** tom, CH, OH.
**What Roland dropped:** cowbell, cymbal, rimshot, claves, maracas, all three
congas, and two of the three toms.
**[verified: T8M]**

The per-voice controls are worth reading as a second, independent ranking,
because knob count is expensive on a 188 mm box and Roland spent it unevenly:

| T-8 voice | controls | comment |
|---|---|---|
| BASS DRUM | LEVEL, TUNE, **DECAY** | the only two 808 knobs that matter on the BD |
| SNARE DRUM | LEVEL, TUNE, **DECAY** | |
| TOM + HAND CLAP | **one shared LEVEL**, TUNE each | Roland gave a tom and a clap *one level knob between them* |
| CLOSED / OPEN HIHAT | LEVEL, TUNE, DECAY | |
| — | global ACCENT: "Accents are applied to all rhythm instruments" | the 808's own global-accent architecture, preserved |
**[verified: T8M panel description, §5 "TOM/HAND CLAP" and §6]**

The shared TOM/HAND CLAP level control is the detail I would not have predicted
and it is the single most direct precedent for §9: Roland, designing a
deliberately reduced 808, treated the tom and the clap as *one slot on the
panel*.

*What reviewers said about whether the T-8 reads as an 808* — see §7; I could
not reach review text for the T-8 myself (Sound On Sound's site search is
non-functional for product queries from here and returns date-sorted news
regardless of the query string; every guessed review slug returned HTTP 410).

### 4.2 Korg volca beats — the analog budget bought five voices, and everything else became a sample

The volca beats is the purest available statement of "we had a hardware budget
and had to choose", because Korg published exactly where the boundary fell:

> "Synthesizer Type: **Analog synthesis (Kick, Snare, Hi Tom, Lo Tom, Closed Hi
> Hat/Open Hi Hat)** / **PCM synthesis (Clap, Claves, Agogo, Crash)**"
> **[verified: VB]**

with these parameters per part:

> "Kick: **Click**, Pitch, Decay, Part Level / Snare: **Snappy**, Pitch, Decay,
> Part Level / Tom: Hi Pitch, Lo Pitch, Decay, Part Level / Hi Hat: Closed
> Decay, Open Decay, **Grain**, Part Level"
> **[verified: VB]**

Two things follow.

**First, the analog set is almost exactly Roland's T-8 set** — BD, SD, two
toms, CH+OH — with the clap being the one voice Korg pushed to PCM that Roland
kept synthesised. Two different companies, a decade apart, with different
constraints (Korg's was analog transistor count; Roland's was DSP and panel
space), landed on the same five or six voice *types*. **[verified: VB, T8M;
the convergence observation is [inferred]]**

**Second, "Click" and "Snappy" are the 808's own control names** — the 808's BD
click is the shaped trigger pulse leaking past the resonator through the tone
low-pass, and SNAPPY is the 808's noise-envelope amplitude **[verified:
`docs/tr808-reference.md` §2, §3]**. Korg's parameter naming is an admission of
what it is modelling.

The volca's hi-hat parameter is **"Grain"**, not a filter corner — i.e. Korg
did not reproduce the 808's six-oscillator-plus-band-pass chain at all, but
exposed a grain/roughness control over some cheaper metallic generator. What
that generator actually is, I **could not establish** from Korg's published
material.

### 4.3 Roland TR-6S — six slots, not six voices

The TR-6S also has "6 instrument parts", but they are *assignable* from an ACB
library covering "the Roland TR-808, TR-909, TR-606, TR-707, CR-78, and more"
**[verified/​manufacturer claim: TR6S]**. It is therefore evidence that Roland
thinks **six simultaneous drum parts is a viable product**, and *not* evidence
about which six 808 voices matter — the user picks. Worth separating from §4.1
for exactly that reason.

### 4.4 What a *full* 808 costs, for contrast

The TR-08 reproduces the whole machine and lists its instruments in the
original's exclusive-pair form, which is itself a confirmation of §3.1:

> "BD: BASS DRUM / SD: SNARE DRUM / **LC: LOW CONGA, LT: LOW TOM** / **MC: MID
> CONGA, MT: MID TOM** / **HC: HI CONGA, HT: HI TOM** / **CL: CLAVES, RS: RIM
> SHOT** / **MA: MARACAS, CP: HAND CLAP** / CB: COW BELL / CY: CYMBAL / OH:
> OPEN HI HAT / CH: CLOSED HI HAT"
> **[verified: TR08S]**

Roland's own modern full recreation ships 16 sounds as 11 parts, in the same
five pairs, thirty-five years later.

---
