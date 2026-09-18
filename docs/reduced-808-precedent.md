# What reduced 808s got away with, and what gave them away

Research question: if we cannot ship all sixteen sounds, does the result still
read as an 808? Answer, from shipped products: **yes, repeatedly — and no
source reports a reduced 808 being rejected for having too few voices.** What
gets rejected is always a *specific voice done badly*, and it is the same voice
almost every time.

## The headline, and why it should change our priority

**The snare is what gives a fake 808 away.** Three independent directions:

- **Korg volca beats** — analog snare, wrong topology. *"Not snappy enough for
  a decent 808 emulation"*; *"one of the shittiest snare sounds in all drum
  machines"*. The community workaround is universal and diagnostic: **layer the
  sampled clap on top of the snare** to give it a front end. One producer
  simply stopped writing snares.
- **Roland T-8** — *"if you push the decay on the snare you seem to lose the
  front end, which is a shame."* Roland's own engine, still the snare.
- **io-808** (full 16-voice Web Audio synthesis) — the author names his own
  failures: *"yes I'm looking at you Cymbal and Rimshot."*

**This corroborates our own measurement from a completely independent
direction.** The discrimination study ranks our voices by knob-equivalent
separation: **SD 8.8**, LT 7.1, OH 6.9, HT 6.0, BD 3.6. Our worst voice is the
snare, and the snare is what the world says betrays a reduced 808. Two
unrelated methods, same answer.

**The cymbal and hi-hat are second.** Six enharmonic square oscillators are the
one part of the 808 nobody approximates cheaply: Mutable Instruments **Peaks**
kept **all six oscillator phases** (`uint32_t phase_[6]`) on a 72 MHz STM32
with only *two voices in the whole module* rather than fake it, and Korg
**sampled** the crash instead of synthesising it. We already generate the six
squares, which on this evidence is the right call and worth protecting.

## Voice count is not the risk

| machine | simultaneous voices | verdict |
|---|---|---|
| Roland **T-8** | **6** fixed (BD, SD, clap, tom, CH, OH) | *"authentically reproduced"*, *"a very traditional, dead easy 808-style affair"* |
| Roland **TR-6S** | 6 assignable | *"impressive circuit-level recreations"*; complaints are ergonomic only |
| Korg **volca beats** | 5 analog + 4 PCM | kick/toms/hats praised; **snare rejected** |
| Mutable **Peaks** | 2 | *"The original 808 sweet spot!"* |

Reviewers' complaint about the T-8 is uniformly *quantity* — *"wayyy less
flexibility"* — never *quality*. **Six simultaneous voices is comfortably above
the identity threshold**, and we have eight circuits.

**Roland's own revealed reduction order**, cutting 16 → 11 → 6 with the engine
held constant: congas, maracas, claves and cowbell go first; then rimshot and
cymbal; leaving **BD, SD, clap, tom, CH, OH**. Five independent sources
converge on that same set — AcidBox instruments only BD/SD/CH/OH; the Teensy
pocket machine chose kick/tom/snare/hat; producers' self-reported minimum kits
agree.

## The trap we are closest to falling into

The volca beats keeps the 808's **bridged-T topology** but replaces its
**analog decay behaviour** with a digitally generated envelope into a VCA.
Dimitree, who reverse-engineered it: Korg added the VCAs *"because without them
the decay of the bridged t-network would be too long, so they cut it out
digitally."*

That is structurally what a modal bank with per-voice envelopes does, and it
produced exactly the complaints above — a truncated tail and a missing front
end. Our own cowbell already measures **τ 26 ms against a real 98 ms**, which
is the same failure. Worth treating as a named hazard rather than a
coincidence.

## The discrepancy, resolved — and it turned out not to matter

Roland's TR-08 instrument listing groups the sixteen sounds into five exclusive
pairs (LC/LT, MC/MT, HC/HT, CL/RS, MA/CP), implying **eleven** circuits.
Wikipedia says **twelve** timbral voices. This was marked open because it was
believed to change the modal-bank arithmetic by one.

**Eleven is right for circuits, and the twelfth is a counting convention.**
The service notes group the sound generators into exactly eleven blocks — BD,
SD, the three tom/conga circuits (SW8), RS/CL (SW11), CP/MA (SW12), CB, CY, OH,
CH — and each of the five pairs shares a trigger, a switch and an output
buffer, so no pair can sound together. The earlier guess that the ambiguity was
CH versus OH is wrong: §11 of the reference has them on separate VCAs, separate
envelopes and separate high-pass corners, and
`drum-verification.md` §4 measured the two corners 8.5× apart on our own
render. They are two.

What can be said for **twelve** is that the RS/CL block contains **two**
independent bridged-T networks (IC21 at 453 Hz and IC20a at 2526 Hz, §5), so
counting *resonators* rather than *voices* gives twelve. Both numbers are
defensible; they count different things.

**And the arithmetic does not depend on which.** The implementation allocates
modal-bank modes per *resonator*, not per voice, so the RS/CL circuit gets two
modes whichever way it is counted. The complete machine needs **eleven trigger
stops and sixteen modes** — built, and bit-exact against the RTL, at contract
revision 9. The open item was real but it was never on the critical path.

## What this changes for us

1. **The snare goes to the front of the queue.** It is our worst-measuring
   voice *and* the voice that historically betrays a reduced 808. Better
   evidenced than the excitation-shaping hypothesis, which is still worth
   testing on one voice but is not the same grade of finding.
2. **Protect the six squares.** Do not "optimise" the hats and cymbal into
   noise. Everyone who tried, failed; the one designer with the tightest budget
   in this survey spent it here.
3. **Eight circuits is enough.** Our palette is above every shipped reduction
   that reviewers accepted. Completing the 808 is worth doing, but it is not
   what stands between us and sounding like one.
4. **Watch the tails.** The envelope-into-VCA shortcut is the documented way a
   bridged-T emulation goes wrong, and our cowbell already shows it.

## Evidence quality

Manufacturer specifications and owner's manuals are primary and strong. Reviews
(Sound On Sound, MusicRadar, MusicTech, gearnews) are professional but
subjective. Reddit quotes are individual opinion, cited because the *pattern*
across many independent users is the signal, not any one remark. Source code
(Peaks, AcidBox, io-808, Teensy) was read directly and is the strongest
evidence here.

**Not established:** any controlled A/B of a reduced voice set against a real
TR-808 with a reported result. No blind test, no listening study, no published
spectral comparison. The one that existed — Dimitree's *"volca beats my mods vs
tr808"* — is dead and unarchived. Every claim above about *acceptance* is
reviewer and user opinion, not measurement.

The search ran without a working keyword engine (every general search engine
was CAPTCHA or 403 blocked), so this is strong on primary sources and weak on
breadth. Absence of a finding here is not evidence of absence.
