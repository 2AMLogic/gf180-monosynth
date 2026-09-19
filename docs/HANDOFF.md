# Where this is, and what to pick up

Written to survive a lost session. Everything here is checkable; nothing is a
plan without evidence behind it.

## The board, and what its number means

```
             cases  valid  pass  fail  no verdict  not run
Drums           32     12     4     8           4       16
Mono            32      0     0     0           0       32
Filters         24      3     1     2           0       21
Ensemble        12      2     2     0           1        9
TOTAL          100     17     7    10           5       78
```

**It went DOWN today, from 19 valid to 15 and back to 17, and that is the
result.** Three cases that were *passing* were passing on measurements that were
never valid — most starkly the bass drum, whose decay guard reported 55 dB of
apparent margin on a record that **ends before the decay does**.

Run it: `tools/scorecard.py --verbose`. Regenerate: `--readme --markdown`.

## The DAG

`tools/compile_dag.py` — evidence re-ran cleanly today (F3 M2 M3 D2 S1 S3 PASS).
Two things outstanding:

- **F1, M1, D1 are STALE** — `ladder_dp.v`, `voice_dp.v`, `drum_kit.v` moved
  since their tags were cut. Clearing them needs the bit-exact verifiers re-run
  **and new tags**, roughly 1.5 h. Do it before the next tag.
- **D3 is RED** — `model/sound_report.py` exit 1: **one** property outside
  tolerance across nine voices. Small, real, unexplained.

## In flight — check these first

| branch | state |
|---|---|
| `sound-tom-pitch-drop` | **pushed, 4 commits + 4 uncommitted in `/tmp/wt-toms`.** The first sound change. If the agent died, the commits are safe on the remote; the uncommitted four are not. |
| `docs-klt-findings` | combing the repo for klayout-tools defects. Nothing committed yet. |
| PR #149 | the `fcr` comment fix, ready to merge |

## The three highest-value open items

**1. All sixteen voices carry broadband energy in the first 30 ms that the
machine does not have** — 41 to 91 dB under the machine's own peak in that band
(#148, `docs/discrimination-trajectory.txt`). **One defect, sixteen sounds.**
This is the largest single finding and it has no issue yet.

**2. #139 — the decay guard is defeated by silence.** Padding a truncated decay
with zeros turns a correct refusal into a **48 % error**. Four board no-verdicts
rest on this guard, so they are not yet evidence of anything.

**3. #150 — `filt_corner` has an uncalibrated frequency-dependent bias.** An
ideal four-pole whose true corner ratio is constant reads 0.460 / 0.439 / 0.432.
#146's attribution of the Filters failures to "cutoff mapping only" is therefore
unsupported.

## Constraints that will bite you

- **LT/MT/HT have nothing in 0.7–5 kHz while their conga twins on the same three
  circuits have up to +28 dB too much.** Raising that band naively makes the
  congas worse. Shared circuits, shared consequences.
- **Knob-equivalents may not share a ruler across voices** (#143). On a frozen
  common ruler **12 of 16 saturate** — our error is largely not on the machine's
  knob axis at all.
- **Every real-808 recording reachable here descends from one machine**
  (Fischer s/n 103852); the nominally different `808*` sets are byte-identical
  re-pressings. Distances are from *that unit*, not from the 808 as a class.
- **Model D works under `pedalboard`, not `dawdreamer`. Mini V3 is the exact
  reverse.** Which host works is a per-plugin property (#123).

## The repeating failure, named

**Guards keep being satisfiable by the pathology they guard against.** Four
instances, all found today:

| guard | defeated by |
|---|---|
| silence check | **NaN** — IEEE comparisons with NaN are always False (#134) |
| decay `tail_db` | the backward integral's own shape (#118, fixed) |
| decay length | **zero-padding** (#139, open) |
| DAG verdict | **the evidence file existing** (#140, fixed in #145) |

**Ask at write time: what input satisfies this guard while violating its
intent?** That question would have caught all four.

## This is a canary — file upstream

The instrument is the payload; **exercising the toolchain is the goal**. Tool
defects go to `2AMLogic/klayout-tools` (layout/flow) and `rjwalters/loom`
(orchestration). Filed today: klayout-tools #2085, #2086; loom #8267, #8268.
See `CLAUDE.md`, "Why this block exists".

## What I would do next, in order

1. Land the toms (measured target ×1.063/×1.140/×1.236, no metric decision needed)
2. File and attack the 30 ms broadband energy — one fix, sixteen sounds
3. Fix #139, which unblocks four no-verdicts
4. Calibrate `filt_corner` (#150), then re-express F1A/B/C before concluding anything about the filter
