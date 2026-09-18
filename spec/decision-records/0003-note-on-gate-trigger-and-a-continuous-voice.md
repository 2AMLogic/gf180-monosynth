# 0003: Note-on semantics — a gate, a trigger, and one continuous voice

- **Status**: proposed
- **Date**: 2026-09-17
- **Decided by**: block agent, from the instrument survey below and measurements in `model/` (`test_voice_fx.py`, the DR 0003 tests)

## Context

Revision 1 of the contract renders every note from reset and sums the
overlaps in the harness (5.3, 8.5, open item 17.1). A hardware voice is one
state machine: what a second GATE_ON does to a voice that is still sounding
or releasing — whether the envelopes restart, from where, whether the
oscillators' phases reset, what the filter's state does — was undecided in
both models. The sponsor also prefers a **paraphonic** voice if it can be
afforded, which makes the same question sharper: with several keys held
into one filter and one amplitude envelope, what does the next key do?

These are questions about what instruments do, and the instrument this voice
is shaped after has a definite answer.

### What the Minimoog does

- **Lowest-note priority.** "If more than one key is held down, only the
  lowest one has effect." — Minimoog owner's manual,
  <https://funkwerkes.com/web/wp-content/techdocs/MixedProAudio/Minimoog-Manual.pdf>.
  The 2016/2022 reissue keeps it as the default: "Hold this C minor chord …
  to choose Low Note Priority. This is the default setting and how a classic
  Model D behaves." — <https://www.moogmusic.com/sites/default/files/Minimoog_Model_D_Users_Manual_Web.pdf>
- **Single triggering** (the contours restart only when no key was held).
  The original has no trigger at all, only a gate: "A timing signal begins
  whenever a key on the keyboard is depressed, and stops when all keys are
  released." (owner's manual, above). Sound On Sound: the Minimoog "uses
  lowest-note priority and single triggering" —
  <https://www.soundonsound.com/techniques/priorities-triggers>; and its
  "single, unconventional timing signal is called an S-Trigger, but is, in
  fact, a Gate" — <https://www.soundonsound.com/techniques/envelopes-gates-triggers>.
  The reissue adds the other choice as a power-on option: "When multiple
  triggering is enabled, each new note played on the keyboard will send a
  new pitch to the Oscillators, and will trigger the Filter and Loudness
  Contour Generators. By disabling multiple triggering (Legato Mode), the
  Contour Generators will only trigger if all notes have been released"
  (reissue manual, above). Which of the two the reissue ships with is not
  stated in either manual — **could not establish**.
- **The contour continues from its current level; it is not reset to zero.**
  Measured on originals and the reissue: "if you play a second note early in
  the release phase, the next attack peaks a little higher than the first,
  and the third is a little higher than that" and the reissue "does" —
  <https://www.soundonsound.com/reviews/moog-minimoog-model-d>. Moog's
  modern default is the same: "By default, with envelope reset turned off,
  an envelope Attack sweeps the envelope output only from its current level
  to maximum." — Sub 37 manual,
  <https://www.moogmusic.com/sites/default/files/Sub_37_Web_Manual_8_13.pdf>.
  A reset to zero is a different class of envelope: "Some synths reset in
  this way, and it can lead to a very disjointed sound indeed." (SOS,
  envelopes-gates-triggers, above).
- **The oscillators free-run.** No source states it for the original in so
  many words; the reissue lists the keyboard's hard-wired connections as
  pitch CV to the two oscillators and triggers to the two contours, nothing
  else (reissue manual, Specifications), and on Moog's modern instruments a
  phase reset is an opt-in feature: "When engaged, the keyboard reset
  function forces the audio oscillators to simultaneously begin their
  cycles whenever you play a new note." (Sub 37 manual, above). Taken as
  established by topology, not by citation.

### What modern monosynths do

Every instrument in the survey that documents a default uses **last-note
priority** except the Model D reissue, and every Moog with the option
defaults to **single triggering** with multi as the switch:

| instrument | priority (default) | trigger (default) | source |
|---|---|---|---|
| Moog Sub 37 / Subsequent 37 | low/high/last (**last**) | single; MULTI TRIG button | "By default, it plays a note in response to the most recent key you pressed … last-note priority"; "By default, playing legato … prevents envelopes from retriggering … single triggering" — Sub 37 manual (above) |
| Moog Grandmother | low/high/last (**last**) | single; Multi Trig from FW 1.1.0 (**off**) | <https://api.moogmusic.com/sites/default/files/2022-01/Grandmother_Manual_Version_2.pdf>, <https://api.moogmusic.com/sites/default/files/2020-09/Grandmother_V1.1.0_Firmware_Update_notes_0.pdf> |
| Moog Matriarch | low/high/last (**last**) | MULTI TRIG (**off**) | "The default setting is LAST"; "57 Multi Trig … (Default: 0 / Off)" — <https://cdn.inmusicbrands.com/Moog/Matriarch/Matriarch_Manual_012023.pdf> |
| Moog Minitaur / Sirin | low/high/last (**last**) | Legato ON / OFF / EG reset (**Legato ON**) | <https://api.moogmusic.com/sites/default/files/2018-02/Minitaur_Manual.pdf> |
| Sequential Pro 3 | low/high/last | Retrigger on/off | "Low (note) Priority is most common in vintage synths" — <https://sequential.com/wp-content/uploads/2021/02/Pro-3-Users-Guide-1.2.pdf> |
| Arturia MiniBrute 2 | low/high/last | Legato / Retrigger | <https://dl.arturia.net/products/minibrute-2/manual/minibrute-2_Manual_1_0_EN.pdf> |
| Novation Bass Station II | — | Single / Multi / Autoglide | <https://fael-downloads-prod.focusrite.com/customer/prod/downloads/bass_station_ii_user_guide_v5_en.pdf> |
| Roland SH-101 | low (GATE) or last (GATE+TRIG) | tied to the same switch | <https://archive.org/stream/synthmanual-roland-sh-101-owners-manual/rolandsh-101ownersmanual_djvu.txt> |

### What paraphonic instruments do with the shared envelope

It is a user choice on every one found, never a fixed behaviour:

- Korg Mono/Poly (1981), TRIGGER switch: "Single Trigger: The EGs are
  triggered and a new attack is produced when the first key or keys are
  depressed … while new keys are depressed, the EGs will not be triggered";
  "Multiple Trigger: Both EGs are triggered and new Attack cycles are
  initiated every time a new key is depressed, regardless of whether or not
  other keys are held down" —
  <https://archive.org/stream/synthmanual-korg-mono-poly-owners-manual/korgmono-polyownersmanual_djvu.txt>
- Korg Poly-800, single/multi for the filter envelope: "The Envelope attack
  cycle will NOT be retriggered (restarted) by any new keys played until ALL
  keys are released" / "DEG 3 will be triggered whenever a new note is
  played, even if other keys are still being held down" —
  <https://archive.org/stream/synthmanual-korg-poly-800-owners-manual/korgpoly-800ownersmanual_djvu.txt>
- Moog Matriarch, paraphonic: "all oscillators then sharing a common signal
  path from the Mixer section and beyond (VCF, VCA, etc.)", MULTI TRIG
  default off, plus "a dedicated pre-mixer Gate" per oscillator (manual,
  above).
- Sequential Pro 3 and Arturia MicroFreak go the other way — a per-oscillator
  amplitude envelope with a shared filter ("the filter and its envelope are
  shared between the three oscillators", Pro 3 guide; MicroFreak "internal,
  invisible VCA envelopes … duplicated several times depending on the number
  of voices", <https://downloads.arturia.net/products/microfreak/manual/microfreak_Manual_5_0_1_EN.pdf>).
  That is more hardware, not a different rule for the shared envelope.

## Decision

The **chip** provides a mechanism; the **host** (the MCU of DR 0002, which
sees the MIDI keys) chooses the policy. The contract specifies the mechanism
exactly; the reference host and its defaults are informative and are the
model's `KeyHost`.

### Mechanism (normative, contract 5.2, 8.3, 8.5)

1. `gate` is a level. **GATE_ON** sets `gate ← 1` and, for both envelopes,
   `seg ← ATTACK` with `level` unchanged. **TRIG** sets `seg ← ATTACK` with
   `level` unchanged and leaves `gate` alone. **GATE_OFF** sets `gate ← 0`;
   the release branch runs from the current level. The attack therefore
   always proceeds from the current level — from zero only when the level is
   zero. There is no reset-to-zero.
2. **No write touches a register it does not name.** `phase[k]` and the
   ladder's `y, w, d1, d2` are written by RESET only; GATE_ON, TRIG and
   SET_INC never change them. The oscillators free-run and the filter's
   state is continuous across notes.
3. **Paraphony costs nothing on the chip.** The three `inc[k]` are already
   independent registers; a host that writes one held key per oscillator
   has a three-voice paraphonic instrument with the shared filter and
   envelopes of every instrument above. No per-oscillator envelope or gate
   is added (that is the Pro 3 / MicroFreak / Matriarch-gate design, and it
   is more hardware for a different instrument).
4. The reference sequences of contract 16 are sequences of writes; a single
   note from reset is the special case with GATE_ON at frame 0.

### Reference host (informative, `voice_fx.KeyHost`)

| policy | default | alternatives | why the default |
|---|---|---|---|
| priority | **last** | low, high | every modern Moog's default and the natural rule under a MIDI host (overlapping notes from a sequencer or keyboard); the Minimoog's low-note is one option away, in firmware, not silicon |
| trigger | **single** (GATE_ON only when no key was held) | multi (TRIG on every new key while one is held) | the Minimoog's, and the documented default of every Moog with the option |
| release to a held key | return to the previously held key without retrigger | — | the Mono/Poly's "return to previous note" and the Minimoog's own behaviour |
| paraphonic | keys to oscillators 0..2 in press order; the rest double the newest key | — | the shared envelope follows the same trigger policy (Mono/Poly, Poly-800, Matriarch) |

### Testable rules (all in `model/test_voice_fx.py`)

- A second key while one is held changes the pitch and leaves both envelopes
  where they are (`test_legato_note_changes_pitch_without_restarting_the_envelopes`).
- TRIG produces no step in the envelope output and then a rise of `a_inc`
  per frame from the current level (`test_multi_trigger_restarts_the_attack_from_the_current_level`).
- GATE_ON during a release attacks from the released level, not from zero
  (`test_gate_on_after_a_release_attacks_from_the_released_level`).
- The oscillator output over a phrase equals a free-running oscillator fed
  the same increments; no phase is reset (`test_oscillator_phase_is_not_reset_at_note_on`).
- Splitting a phrase across two `play` calls gives the identical sample
  stream, so nothing is reset between notes; a resonant ring carries into
  the next note (`test_ladder_state_is_continuous_across_notes`).
- Three held keys land on three oscillators with one trigger
  (`test_paraphonic_keys_go_to_separate_oscillators`).
- `note()` is `play()` with one gate (`test_single_note_from_reset_is_play_with_one_gate`).

## Alternatives considered

- **Restart from zero on every note** — the disjointed-envelope class (SOS
  above); no Moog does it by default; it clicks.
- **Reset the oscillator phase at note-on** — opt-in on the Sub 37, not the
  Model D's behaviour, and it would make the three detuned oscillators start
  in phase on every note, removing the beating that the detune exists for.
- **Reset the ladder at note-on** — no circuit does it; a discontinuity in a
  resonant filter is a click. Its consequence — a self-oscillating filter
  keeps singing between notes — is real and is what the instrument does; the
  note still ends because the VCA is after the filter (DR 0005).
- **Low-note priority as the default** — the Minimoog's, and it remains
  available; priority is host firmware, and the modern default under a MIDI
  host is last-note (table above).
- **Multi-trigger as the default** — the Bass Station II's initial patch;
  every Moog defaults to single. Single is also the mode in which paraphonic
  chords do not chop each other's envelope.
- **Per-oscillator envelopes for paraphony** — two more envelopes and two
  more VCAs; the sponsor's condition was "if it can be afforded", and the
  shared form costs nothing.

## Consequences

- The model is a continuous voice: `VoiceFx.play(regs, writes, n)`,
  `VoiceFx.reset()`, envelopes with per-frame `gate` and `trig`,
  `render_mono_fx` through one voice with `KeyHost` — no more summing of
  overlapping notes. Contract 5.2, 5.3, 8.3, 8.5, 14 and 16 change; revision
  2.
- The front-end RTL (not yet written) carries a TRIG path and the seg ←
  ATTACK on GATE_ON; nothing changes in the ladder.
- Not modelled, and stated: the Minimoog's contour is an RC network, so its
  attack from a mid level is faster in absolute terms than from zero; the
  linear attack here reaches full in `(FULL − level) / a_inc` frames, which
  is also shorter from a higher level. The qualitative rule is the same.
- A self-oscillating patch now sings across a rest (the ladder is at 0.41 ×
  full scale at the end of the whistle riff, inaudible because the VCA is
  closed). A host that wants the Matriarch's per-oscillator muting can write
  `w[k] = 0`; that is not in the reference host.
