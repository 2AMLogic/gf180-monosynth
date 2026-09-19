# Localising the excitation-energy defect (#152)

**One deliverable: where in time and band we differ from the machine, and
whether #152's excess and #154's deficit are one mechanism or two.**

This is an investigation. `model/drums_fx.py` is unchanged; no coefficient was
fitted and nothing was tuned. The instrument is
[`tools/probes/excitation_energy.py`](../tools/probes/excitation_energy.py),
eighteen self-tests, two of them injected-bug controls.

---

## The answer, in four sentences

**Two mechanisms, on disjoint voice sets, and #152's "sixteen" is not sixteen.**

1. **The excess is real on five voices strongly and three weakly, and it is not
   broadband.** It is a **low-frequency step** — a single 33 Hz-wide bin below
   200 Hz, which is to say near DC — emitted by two named things in the
   excitation path: `SRC_PULSE`, whose mean equals its mean magnitude *exactly*,
   driving modes whose DC gain is 18 to 23,899; and `NL_SWING`, which
   rectifies. Nothing downstream removes a mean, because the block has **no
   output coupling anywhere**.
2. **The deficit is a separate mechanism on the six tom/conga positions**, in
   0.7–5 kHz, present in every window, and it moves not at all when the
   excitation's asymmetry is removed.
3. **The shared-circuit paradox of #152 does not exist at HEAD.** All six
   positions are short in 0.7–5 kHz, by 6 to 20 dB, monotone in f0. The
   "+28 dB too much" on the congas was the ×1.7 sweep #154 removed — it moved
   a 400 Hz conga's fundamental across the 700 Hz split and a 90 Hz tom's
   nowhere near it.
4. **Several of #152's sixteen rows are the measuring instrument.** CH, OH and
   BD have no low-frequency onset excess at all once the conditioning is
   causal, and on CL, CP and RS most of the reported magnitude was
   `test_discrimination.condition()`'s zero-phase high-pass.

---

## 1. The instrument first, because two of #152's three legs are the instrument

`docs/failure-modes.md`: *preconditions assumed rather than asserted*. #101 and
#103 are already on record here as **"the two sides of every drum comparison
were filtered under different boundary conditions, and nothing said so"**. That
defect is back, in the conditioning the whole discrimination study runs on, and
it is larger there.

Run `.venv/bin/python tools/probes/excitation_energy.py --floors`.

### F1 — the conditioning manufactures the thing it is used to measure

`test_discrimination.condition()` high-passes at 20 Hz with **`sosfiltfilt`**.
scipy pads that with `padlen = 3*(2*len(sos)+1-1) = 6` samples, for a
first-order filter whose pole is 0.99739 and whose settling time is about 1,900
samples. Fed a unit impulse at index 0 it answers with a **near-full-scale
negative pedestal**:

| | first 30 ms of the impulse response, summed | second sample |
|---|--:|--:|
| `sosfiltfilt` @ 48 kHz | **−372.65** | **−0.99739** |
| `sosfiltfilt` @ 44.1 kHz | **−342.34** | −0.99716 |
| causal `sosfilt` | +0.0231 | −0.00261 |

A high-pass integrating a unit impulse to −373 is not measuring anything's low
frequencies. **The pedestal lands on window 0, which is where the whole of
#152 lives.**

`condition()`'s own docstring anticipates exactly this — *"a 20 Hz filter
settles over ~50 ms, and filtering a 240 ms window in place puts that transient
right on top of the attack — which is where most of the discrimination lives"* —
and then reaches for the acausal filter, which has the same transient at
index 0 and a worse one.

The control, run the other way round (`test_the_pedestal_creates_low_frequency_where_there_is_none`):
a signal built with **no energy at all below 400 Hz** comes out of `condition()`
reading large in window 0 below 120 Hz, and comes out of a causal conditioning
reading under −20 dB.

### F2 — the two sides do not enter the conditioning the same way

`_render_raw` returns `out[onset(out):]` — **our** clip arrives pre-trimmed to
its onset. `read_wav` does not trim the machine's. F1's pedestal is therefore
placed differently on the two sides. Applying the same pre-trim to the machine
moves its own window-0 sub-120 Hz reading by:

| CL | CP | CB | MA | CH | HC | MC | LC | RS | HT | OH | SD | others |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **+32.2** | +29.8 | +29.5 | +22.5 | +20.0 | +19.9 | +19.9 | +10.2 | +11.1 | +9.7 | +6.0 | +1.4 | ≤ +0.2 |

dB, from a choice of array bounds. "Applied identically to both sides" is true
of the code and false of the measurement.

### F3 — ten of the fifty-two bands cannot hold a reading at all

The map's windows are 30 ms, so the analysis bin is **33.33 Hz** — at both
44.1 and 48 kHz, because 0.24 s / 8 is a whole number of samples at each, which
is also why the trajectory's rate-independence test passes.

- **Bands 0–15 are all narrower than one bin.**
- **Bands 0, 1, 2, 3, 5, 6, 8, 9, 11 and 14 — 42, 48, 53, 60, 76, 85, 107, 120,
  151 and 214 Hz — contain no bin centre at all.** They are pinned to the
  −75 dB clamp on both sides by construction. That is why they never appear in
  `docs/discrimination-trajectory.txt`, and it is not because the machine and
  we agree there.
- The bands that do appear — **67, 95, 135, 170, 190, 240, 269, 302, 339 and
  427 Hz** — are each **one FFT bin**, over-reporting by up to **+6.3 dB**
  because the bin is wider than the band, and scattering by **5.57 dB** on a
  single reading because one bin of a stochastic signal is chi-square with two
  degrees of freedom.

So **"67 Hz" in that file means bin 2 of a 30 ms Hann window** — a 33 Hz
neighbourhood whose main lobe reaches DC — and not a 63.5–71.3 Hz band.

### F4, F5, F6 — the floors that stayed

- **F4, the 16-bit reference's quantisation floor**, per cell, closed form
  checked against a measured requantisation. It runs −63 to −97 dB depending on
  how much headroom the clip was mastered with.
- **F5, leakage**, measured per reported cell by notching the band out of the
  signal and re-reading its own cell. Below about 1 kHz this is *at* the
  reading, which is the honest statement: the cell is reading its whole 33 Hz
  bin. It is reported as `BIN-WIDE` and is deliberately **not** part of the
  refusal — both sides read the same bin, so the difference of the readings is
  real whatever else is in it; what is not real is the band it is named after.
- **F6, one-bin scatter**: 5.57 dB / √n. A row on a one-bin band from a
  single setting must clear 11.1 dB before it is a row.

### What the machine's corpus can and cannot support

The Fischer set is **16-bit, 44.1 kHz, hard-trimmed to round durations**
(250/500/1000/1500/2000/3000/4000 ms) with the onset at sample 0–18 in every
file. Two consequences, both checked:

- **No clip is zero-padded by the 240 ms window** — #139's defeat of the decay
  guard is not active here. The 250 ms files fit, with 10 ms to spare.
- **There is no pre-onset lead anywhere.** That is why the band split in §4
  uses a rectangular-window FFT (Parseval exact) rather than
  `audio_measure.band_energy`, whose own docstring says it *"manufactures an
  edge worth up to 10 dB in a sparsely-occupied band"* unless the segment
  arrives with a true lead.
- The corpus's own noise floor, where it can be measured (`MA`, `CY0050` have
  a lead), is **−45 to −52 dB** broadband relative to the clip peak, and the
  machine's low-frequency content in the non-pitched voices sits flat on it
  (CB reads −62 dB flat from 5 to 100 Hz). **The machine's recording chain is
  not high-passing above ~20 Hz**: BD0050 has its 50 Hz fundamental at −3 dB
  and falls at about 6 dB/octave below 30 Hz, which is one pole. So the absence
  of low frequency in the machine's hats, cowbell and claves is the machine's,
  not the recording's.

---

## 2. The map, re-derived

`.venv/bin/python tools/probes/excitation_energy.py --map` — the full 52 × 8
per voice, ours minus the machine, under a **causal** 20 Hz high-pass with both
sides pre-trimmed, every row carrying its floor. Full report:
[`excitation-energy-map.txt`](excitation-energy-map.txt).

### The summary the one-mechanism question turns on

`low w0` is the largest EXCESS under 200 Hz in window 0 — the onset pedestal.
`high` is the mean signed difference over every live cell in 0.7–5 kHz, all
eight windows. Both in dB, ours minus the machine.

| voice | low w0 | high 0.7–5 k | excess cells | deficit cells |
|---|--:|--:|--:|--:|
| CY | **+50.7** | **+12.6** | 228 | 8 |
| RS | **+44.6** | −13.0 | 13 | 261 |
| MA | **+43.2** | +0.7 | 109 | 165 |
| CL | **+36.1** | −3.7 | 26 | 156 |
| CP | **+24.1** | −6.0 | 42 | 142 |
| MC | +8.8 | −4.8 | 3 | 38 |
| CB | +8.7 | +2.6 | 141 | 52 |
| HC | +8.4 | −5.2 | 2 | 35 |
| MT | +6.4 | **−20.1** | 1 | 194 |
| LT | +1.6 | **−19.3** | 0 | 206 |
| LC | +0.8 | −8.3 | 0 | 33 |
| HT | +0.6 | **−21.9** | 1 | 201 |
| SD | −0.1 | +1.4 | 93 | 36 |
| CH | −0.5 | −5.3 | 20 | 144 |
| BD | −0.9 | −1.9 | 14 | 34 |
| OH | −6.4 | −5.1 | 31 | 93 |

**The two columns are anti-correlated, not aligned.** Every voice with a large
onset pedestal (top five) has a small or positive 0.7–5 kHz number, and every
voice with a large 0.7–5 kHz deficit (LT, MT, HT) has no pedestal at all. If
one blunt over-broad excitation produced both, they would move together.

### Where the excess lives

- **It is below 200 Hz**, in the bands F3 says are single bins — so read it as
  "the 33 Hz neighbourhood of 67 / 95 / 135 / 170 Hz", which is to say
  *near DC*. Not broadband. `RS 95 Hz 0–30 ms +44.6`, `CL 67 Hz 0–30 ms +36.1`,
  `CP 170 Hz 0–30 ms +24.1`.
- **On RS, CL and CP it is confined to window 0** and gone by 60 ms: a step.
- **On CY it is not.** `CY 135 Hz` reads +67.5, +64.6, +66.5, +63.3 dB at
  30–60, 90–120, 150–180 and 210–240 ms. The cymbal's low band runs through the
  swing VCA under `E_CYL`, whose τ is 500 ms, so its rectified mean decays over
  the whole clip rather than at the onset. Same mechanism, longer envelope.
- **MA carries a second, unrelated excess**: +42 to +48 dB across 3–14 kHz at
  30–60 ms. That is the maraca's `HP` mode ringing where the machine's has
  decayed, not a low-frequency step.
- **CH and OH have no low-frequency excess at all** under a causal
  conditioning. Their #152 rows (`CH 95 Hz +33.4`, `OH 67 Hz +21.1`) do not
  reproduce.

### Where the deficit lives

- **0.7–5 kHz on all six tom/conga positions, in every window.** `LT 538 Hz
  0–30 ms −47.6`, `HT 678 Hz 120–150 ms −47.4`, `MT 604 Hz 60–90 ms −44.4`.
  On the congas it is concentrated in window 0 and higher up — `HC 1709 Hz
  0–30 ms −29.7`, `LC 1709 Hz 0–30 ms −27.8` — which is where a strike's
  broadband content would be.
- **BD's whole attack is short**, 170–678 Hz in window 0 only, −17.8 to
  −23.2 dB. That is a separate finding and it is not in #152: our bass drum's
  click is too weak across the band, not too strong.
- **CH is short everywhere and late**: 3–15 kHz at 210–240 ms, −20 to −22 dB,
  our side at the −75 dB clamp. The closed hat ends before the machine's does.
- **OH's tail is the other way**: +17 to +20 dB at 5–15 kHz at 210–240 ms, and
  −15 dB at 3–4 kHz mid-clip. It decays too slowly at the top and too fast in
  the middle.

## 3. Attributing the excess

`--attribute` mutes **one register path at a time** and re-renders, and
`--dc` prints the excitation's mean beside the DC gain it is multiplied by.
Between them the four candidates #152 names are tested exhaustively rather than
one guess at a time, because three of the four are path words.

### The measurement

Sub-120 Hz energy of the first 30 ms, dB relative to the conditioned clip's
total, with all paths held but one:

| voice | baseline | all `nl` → `LIN` | change |
|---|--:|--:|--:|
| MA | +13.2 | −34.0 | **−47.2** |
| CB | −16.9 | −39.8 | **−22.9** |
| CY | −12.9 | −30.0 | **−17.1** |
| RS | +20.2 | +5.5 | **−14.7** |
| CP | −6.6 | −9.5 | −2.9 |
| BD SD LT LC MT MC HT HC CL | — | — | **0.0** |

### Candidate 4, the coefficient-write transient: **not it**

`coef_seq=False` removes the BD's 4 ms attack window and the toms' pitch drop.
Over all sixteen voices the largest change is **+1.8 dB (MT)** and every change
is **positive** — removing the sequences *raises* the low-frequency share.
The coefficient writes are not the source of the onset excess. (They are the
source of something else: see §4.)

### Candidates 2 and 3, the envelope attack and the noise onset: **not it**

The envelope's attack is one frame for every voice, and the noise source is
ungated (`ENV_FULL`) on the two circuits that use it as a source. Muting the
noise path changes nothing on any voice but SD, where it *raises* the
low-frequency share by 1.1 dB because it removes energy elsewhere.

### Candidate 1, the excitation pulse shape: **it, in two halves**

**(a) `SRC_PULSE` has a full DC component and the modes it drives are
all-pole.** `SRC_PULSE` is the constant +32767 gated by an envelope, so its
mean equals its mean magnitude *exactly* — it never changes sign
(`test_the_pulse_source_has_a_full_dc_component`). A mode with the `RAW`
numerator has no zero at z = 1, so its DC gain is 1/(1 − a₁ − a₂):

| mode | M_BD | M_LT | M_MT | M_SDLO | M_HT | M_SDHI | M_RS1 | M_RS2 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| DC gain | **23,899** | 7,204 | 3,202 | 1,949 | 1,706 | 517 | 282 | 18.5 |

Every one of those eight modes is driven by `SRC_PULSE` and every one is
`RAW`. The `BP` and `HP` numerators, which the hat, clap, cowbell and cymbal
modes carry, have a zero at z = 1 and measure **0** — with a −1 % integer
truncation residue, recorded because it is real and is 30 dB under what `RAW`
does.

**(b) `NL_SWING` rectifies.** `x << 2` above zero and `x >> 3` below it turns a
zero-mean square into one whose mean is **0.7 of its mean magnitude**
(`test_the_swing_nonlinearity_rectifies`). It is the output VCA of RS, CY's low
band, MA, CB and the two hats — reference 5's Q62, "the distortion is the
sound; do not skip it". The distortion is correct. What is missing is what
follows it in the circuit.

**Neither half is removed downstream, because there is nothing downstream.**
`output_fx` sums the two buses under three gains and saturates. There is **no
DC blocking anywhere in the block** — no coupling capacitor, no high-pass, not
on a voice, not on a bus, not at the output. In the real machine every voice's
gate is followed by one.

So the sentence that names the fix is: **the excitation is asymmetric by
design and correctly so, and the AC coupling that the circuit puts after it is
not modelled.**

---

## 4. The shared-circuit constraint

#152 requires any mechanism to explain why *"the toms are short in 0.7–5 kHz
while their conga twins have up to +28 dB too much there"*.

**At HEAD that is no longer true, and the reason is #154.**
`docs/discrimination.md` §5a — the source of the +28 dB — is #148's table, and
#148 predates #154. `--shared` re-renders the six positions with
`tom_pitch_drop_writes` exactly as it stood at 24cff92 (the ×1.7 sweep and its
accent **clamp**, which handed a plain hit the full sweep) and puts that beside
HEAD. 0.7–5 kHz share of the 240 ms window, rectangular-FFT Parseval:

| voice | f0 | machine | HEAD | dB | before #154 | dB | the sweep made |
|---|--:|--:|--:|--:|--:|--:|--:|
| LT | 90 Hz | 0.00172 | 0.00002 | **−19.66** | 0.00004 | −16.01 | +3.64 |
| MT | 135 Hz | 0.00342 | 0.00006 | **−17.48** | 0.00018 | −12.84 | +4.64 |
| HT | 185 Hz | 0.00376 | 0.00016 | **−13.82** | 0.00060 | −7.95 | +5.87 |
| LC | 185 Hz | 0.00127 | 0.00009 | **−11.41** | 0.00035 | −5.64 | +5.76 |
| MC | 280 Hz | 0.00407 | 0.00040 | **−10.11** | 0.00260 | −1.94 | +8.17 |
| HC | 400 Hz | 0.00555 | 0.00137 | **−6.07** | 0.25059 | **+16.55** | **+22.62** |

**There is no paradox. There was a sweep.**

- At HEAD **all six are short**, by 6 to 20 dB, and the deficit is **monotone
  in f0** across both positions: 90 Hz −19.7, 135 −17.5, 185 −13.8, 185 −11.4,
  280 −10.1, 400 −6.1. That is exactly the shape one mechanism scaled by pitch
  gives, and exactly what a shared circuit ought to produce.
- The old law put **+22.6 dB** into HC's 0.7–5 kHz and only +3.6 dB into LT's,
  because a ×1.7 sweep moves a 400 Hz conga's fundamental to 680 Hz — **across
  the 700 Hz split** — and a 90 Hz tom's to 153 Hz, nowhere near it. The
  "opposite sign" was one voice's fundamental crossing a band edge.
- HC before #154 measures +16.55 dB here against §5a's +28.1 dB. The two use
  different splits and different estimators (§5a's is the filter bank, which
  has no pre-onset lead to work with); the sign and the order of magnitude
  agree, and the direction of the correction is unambiguous.

**So the constraint #152 imposes on any proposed mechanism is satisfied by
not needing one.** A mechanism that explains "short in the toms, over-supplied
in the congas" would be explaining an artefact that has already been removed.

## 5. One mechanism or two

**Two**, and the sets are disjoint.

| | A: the onset step | B: the 0.7–5 kHz deficit |
|---|---|---|
| **voices** | CY RS MA CL CP, weakly CB MC HC | LT MT HT LC MC HC |
| **time** | window 0 on RS/CL/CP; the whole clip on CY, whose envelope is 500 ms | every window |
| **band** | below ~200 Hz — one bin wide, i.e. near DC | 0.7–5 kHz |
| **sign** | excess, +24 to +51 dB | deficit, 6 to 22 dB |
| **cause** | a mean the excitation has and nothing removes (§3) | a partial one two-pole mode does not make (§4, unsettled) |
| **evidence they are separate** | muting the swing VCAs moves A by up to 47 dB and moves B by **nothing** on any tom | the deficit is monotone in f0 across both switch positions; the pedestal is not |

**The two summary columns are anti-correlated.** CY, RS, MA, CL and CP carry
the pedestal and carry no unusual 0.7–5 kHz deficit; LT, MT and HT carry a
19–22 dB deficit and no pedestal. A single over-broad excitation cannot give
that: energy spread where it should be concentrated would raise the low band
*and* the mid band on the same voices.

And the excess is not "broadband" in any case. It is a **step**, which is the
most concentrated thing a transient can be, and it sits two and a half decades
below the band the toms are short in.

**This decides the question #152 asks.** It is not one fix for sixteen voices.
It is:

- **one fix for mechanism A** — a DC block. That is one high-pass on the output
  path and it would address five voices strongly and three weakly, at once;
- **a separate and unrelated question for mechanism B**, which is about what
  supplies 0.7–5 kHz on a bridged-T body and is not an excitation question;
- **and four voices in #152 that need no fix at all** — CH, OH, BD and SD have
  no low-frequency onset excess once the conditioning is causal.

## 6. What is not settled here

- **What supplies the toms' 0.7–5 kHz.** `docs/tom-pitch-drop-correction.md`
  §8 names two candidates and measures neither: reference §4's pink-noise
  rumble (which §4 says the congas do not have, and the congas are short too),
  and the harmonic content a nonlinear VCA puts on a ring that one two-pole
  mode emits as a pure sinusoid. This investigation does not choose between
  them; it narrows the target by showing the deficit is the same sign on all
  six and monotone with pitch, which a per-position noise path would not
  obviously give.
- **Whether a DC block belongs in the block or the host.** Not a measurement
  question.
- **What the 808's coupling corner actually is, per voice.** The reference
  corpus bounds it from above (the machine passes 50 Hz at −3 dB on the BD) but
  does not resolve it per circuit.

---

## 7. What this does to the documents that rest on the conditioning

`condition()` is used by `model/discrimination_run.py`,
`model/discrimination_trajectory.py` and `model/test_discrimination.py` — that
is the whole of #148 and everything quoted from it.

**The classifier results are not invalidated by F1.** The artefact is applied
to both sides, and it amplifies a real onset difference rather than inventing
one where the two sides are identical; a discriminator that scores on an
amplified real difference is still scoring on a real difference. What is
invalidated is **attribution**: any statement of the form "the difference is at
*this* frequency in *this* window" that rests on window 0 of a conditioned clip.

Specifically:

- **`docs/discrimination-trajectory.txt` window-0 rows should be re-derived.**
  The file also predates #154, so every LT/MT/HT/LC/MC/HC row in it was
  rendered with the ×1.7 sweep.
- **`docs/discrimination.md` §5a's tom/conga table predates #154** and its
  "+28.1 dB" on HC no longer reproduces.
- **#152's headline — "all sixteen voices" — does not survive.** The count of
  voices with a real, floor-clearing low-frequency onset excess is **eight**,
  and on five of the remainder the row was the instrument.

---

## 8. Wrong-then-right, on this branch

Recorded because `CLAUDE.md` asks for the rate where the numbers are read.

| what | wrong | right | caught by |
|---|---|---|---|
| the attribution-bias test | asserted a one-bin band's white-noise reading to 4 dB | one bin is chi-square with 2 dof and scatters 5.6 dB; needs 200 realisations | the test failing |
| the quantisation-floor test | compared a rescaled error slice against the prediction; 84 dB out | the closed form was right, the test's scaling was wrong | the test failing |
| the leakage floor | folded into the refusal, which refused every BD cell | both sides read the same bin; leakage is an attribution caveat, not a floor | the map reporting nothing for BD |
| the leakage floor, again | max over sides *and* settings against a mean over settings | mean per side, then max of the two | a leak floor reading higher than the signal |
| the pre-#154 test | asserted the old law gave ×1.7 at accent 0.5 | the clamp scales below 1.0 and saturates above it | the test failing |

Five, all caught by controls rather than by inspection. The first four are in
the instrument, not in the result.
