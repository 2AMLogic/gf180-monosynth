# Recording protocol for a real Moog

**For someone with the instrument and an hour.** Follow this and the session
produces a *reusable automated reference set*: `model/moog_probe.py` and
`model/reference_compare.py` run against it the moment it exists, with no
further human judgement. Deviate from it and the recordings join the 222 files
in Legowelt's pack, which are lovely and which this project could not use for
anything, because they ship no panel settings (`docs/discrimination.md` §8).

**This is data collection, not an opinion.** Do not audition our chip against
yours, and do not tell us whether it sounds right. An unblinded single rater
comparing two sounds, one of which they know is the "real" one, measures
demand characteristics. A listening test belongs at the *end*, deciding
whether the instrument is musically compelling — never in debugging, where a
number with an error bar is worth more than a strong impression.

---

## 0. What decides whether the session was worth doing

Three things, in order. If you can only do one, do the first.

1. **The self-oscillation takes (§4.1).** They are the only material that
   fingerprints the filter's *structure*, they need no calibration, and the
   probe that reads them is already written and tested. They also convert the
   cutoff knob into hertz, which every other measurement then depends on.
2. **Panel settings recorded for every take.** Without them a take is a
   sound, not a measurement. A photograph of the panel is enough and is
   faster than writing.
3. **The held-out block (§6) recorded but not sent, or sent sealed.** If every
   setting we have is a setting we tuned against, we have no way left to find
   out we are wrong.

---

## 1. Identify the instrument, once

In a file `instrument.txt` beside the audio:

```
model:          Minimoog Model D          # the exact model. NOT "Moog".
serial:         1234567
year:           1974
last_serviced:  2019 (filter board recapped)
notes:          osc 3 drifts sharp when cold; left it on for 30 min first
```

**Different Moog models are different instruments and are never pooled.** A
Sub 37, a Voyager, a Model D reissue and a 1974 Model D have four different
filters; averaging them produces a number that describes nothing. One
`instrument.txt` per instrument, one directory per instrument. If two people
contribute, that is two directories, not one bigger set — and it is *more*
useful that way, because the spread between two real Model Ds is exactly the
number this project has never had.

---

## 2. Signal path — dry, and nothing else

- **Straight from the instrument's output to the interface.** No pedals, no
  desk EQ, no channel strip, no compressor, no reverb, no tape, no amp, no
  microphone. If it is in the path, it is in the measurement, and we cannot
  tell it apart from the filter afterwards.
- **No processing on the way to disk**: no normalisation, no limiting, no
  noise reduction, no dither beyond the converter's own, no "clean-up".
  Hiss, hum and drift are wanted — they are part of the instrument.
- **48 kHz, 24-bit, mono, WAV.** 48 kHz is our own sample rate, so nothing is
  resampled; 96 kHz is welcome if it is free, and is better for the aliasing
  questions. 44.1 kHz is acceptable. Do not convert anything yourself.
- **Set the gain once and never touch it again.** Every level comparison in
  the set dies the moment the gain knob moves mid-session. Aim for the
  loudest take (§4.4, mixer fully up) peaking around **−6 dBFS**, and leave
  it. Quiet takes are meant to be quiet.
- **Record 10 seconds of silence** with the instrument on and the volume up,
  as `00-silence.wav`. That is the noise floor every "is this a harmonic or
  is it hiss" question is answered against, and the probes refuse to report a
  level below it.
- **Record a reference tone** if you have a signal generator: 1 kHz at a
  known level, as `00-reference-1k.wav`. Not essential.

---

## 3. Documenting the panel — the part that makes it data

**Photograph the whole panel for every take**, straight on, in focus, whole
front panel in frame. It takes two seconds and it is more reliable than
writing numbers down. Name the photo after the take.

Also write the settings that the take is *about* into a manifest line, since
that is what the harness reads. One CSV, `takes.csv`, appended as you go:

```csv
file,type,cutoff,emphasis,osc1_wave,osc1_range,osc1_level,osc2_level,osc3_level,noise_level,contour_amount,attack,decay,sustain,note,repeat,notes
04-selfosc-cut2.wav,selfosc,2.0,10,,,0,0,0,0,0,0,10,10,,1,
04-selfosc-cut2.wav,selfosc,2.0,10,,,0,0,0,0,0,0,10,10,,2,
06-sweep-cut4-emph2.wav,tone,4.0,2,saw,8,10,0,0,0,0,0,10,10,A2,1,
```

Knob positions are the panel's own **0–10**, to the nearest half. Nobody
expects a Model D's knob to be readable to better than that, and the
self-oscillation takes convert those positions into hertz for us anyway.
Switch positions by their panel label (`saw`, `tri`, `8`, `16`).

---

## 4. The takes

Each take: **hold it steady for 8 seconds**, and **do every take three
times** (`repeat` 1, 2, 3), retriggering between. Three repeats are what let
the harness separate the instrument's own drift from a measurement error;
one take of everything is worth much less than three takes of half of it.

### 4.1 Self-oscillation — the one that matters most

The filter singing on its own, with nothing else in the path.

- **All three oscillator levels at 0. Noise at 0. External input at 0.**
  Nothing in the mixer.
- **Emphasis at 10** — past the threshold, so it sings.
- **Contour amount 0**, filter attack 0, decay 0, sustain 10 (so the filter
  envelope does not move the cutoff).
- **Loudness contour**: attack 0, decay 0, sustain 10, so the note is a flat
  gate and does not shape the tone.
- Hold a key down for the whole 8 seconds.

Do this at **cutoff = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10** — eleven takes,
three repeats each. This is the single most valuable block in the session:

- it fingerprints the nonlinearity's **structure** (the h5-to-h3 signature),
  which is the thing no unlabelled recording can give;
- its pitch at each knob position **is** the cutoff in hertz, which
  calibrates the knob and makes every other take in the session measurable;
- it needs no reference signal, no level matching and no patch recall.

Also do **emphasis = 7, 8, 9, 10 at cutoff 5**, so we can see where your
instrument's oscillation actually starts.

### 4.2 Filter response, with a known source

- **Oscillator 1 only**, sawtooth, range 8′, level 10; oscillators 2 and 3 and
  noise at 0.
- Contour amount 0; both envelopes flat as in §4.1.
- Hold **A2** (110 Hz) for 8 seconds.
- Grid: **cutoff = 2, 4, 6, 8, 10 × emphasis = 0, 3, 5, 7** — twenty takes.

### 4.3 Filter response, broadband

Same as §4.2 but **noise at 10 and all oscillators at 0**, white noise if the
instrument offers the choice. Cutoff = 2, 4, 6, 8; emphasis = 0, 5. Eight
takes. Noise gives the whole response in one take instead of one frequency at
a time.

### 4.4 Drive — where the Model D's character actually lives

Fixed **cutoff 5, emphasis 3**, oscillator 1 saw at A2, everything else at 0.
Take one per **oscillator-1 level = 2, 4, 6, 8, 10**, and then, if the
instrument has the feedback trick, one with the output patched back into the
external input at a documented external-input level. Five to seven takes.

This is the block that says whether a filter *thickens* or *flat-tops* as it
is pushed, which is the audible consequence of where the nonlinearity sits.

### 4.5 Oscillators alone, for tuning and waveform

Filter wide open (**cutoff 10, emphasis 0**), oscillator 1 only, level 10.
One take per waveform (triangle, shark-tooth, sawtooth, square, wide pulse,
narrow pulse) at A2, and one sawtooth take at each of **A0, A2, A4, A6** for
the pitch and aliasing questions. Ten takes.

### 4.6 Envelopes

Oscillator 1 saw, cutoff 10, emphasis 0. Loudness contour attack/decay/sustain
at **(0,2,0), (0,5,0), (3,5,5), (0,10,10)**; play a short note and let the
whole tail run, 8 seconds, key released after 1 second. Four takes. Then the
same four on the **filter** contour with contour amount 8 and cutoff 2.

---

## 5. What not to do

- **Do not tweak to taste between takes.** A take that sounds better but whose
  panel drifted is not usable.
- **Do not skip a setting because it sounds bad.** The ugly settings are
  where two filters differ most.
- **Do not normalise, trim silence, or "tidy" the files.** Send them as
  recorded.
- **Do not record the same setting once and copy it.** Three real repeats.
- **Do not play musically.** Hold one key. Vibrato, glide and key velocity are
  extra unknowns in every measurement they touch.

---

## 6. The held-out block — please read this one

Record §4.2's grid a second time at settings we have **not** listed:

- **cutoff = 3, 5, 7, 9 × emphasis = 2, 6**, oscillator 1 saw at **D3**.

Keep these in a separate directory `heldout/`, with their own photos and
manifest, and **do not send them with the first batch.** Send them later, or
send them to someone who will hold them. Everything in §4 will be used to
find and fix problems in our model, and anything used for fixing can no
longer be used for testing — that is not a technicality, it is the entire
difference between "we tuned until it matched" and "it matched". The held-out
block is the only part of the session that can ever tell us we are wrong.

If you would rather not manage two batches: record §6 **first**, put it in
`heldout/`, and forget about it.

---

## 7. Delivering it

A single archive:

```
model-d-1234567/
  instrument.txt
  takes.csv
  00-silence.wav
  00-reference-1k.wav
  04-selfosc-cut0-r1.wav   04-selfosc-cut0-r1.jpg
  04-selfosc-cut0-r2.wav   ...
  ...
  heldout/
    instrument.txt  takes.csv  ...
```

Filenames do not have to match exactly — `takes.csv` is what the harness
reads, and the filename only has to appear in it. Photos should share the
take's stem.

**Licence.** Say what we may do with it, in `instrument.txt`. CC0 or CC-BY
makes it usable as a reference other people can reproduce our results
against, which is worth a great deal; "this project only, not
redistributable" is still useful and is better than nothing. If you say
nothing we will assume the most restrictive reading and will not publish any
of it.

---

## 8. What happens to it here

`model/moog_probe.py` reads §4.1 and returns the structural fingerprint — it
has been calibrated and checked in since 2026-09-18 and has had no material
to work on. §4.2 and §4.3 feed `model/reference_compare.py`'s response
measurements, which currently compare us only against software emulations
(`docs/discrimination.md` §8) and would then have a real instrument in the
same table. §4.4 feeds the drive comparison, §4.5 the oscillator acceptance
tests, §4.6 the envelope ones.

Every one of them reports **per property, with its measurement's own floor**,
and refuses to report a number it cannot support. None of them asks anybody
whether it sounds good.
