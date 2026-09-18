# The scorecard

`cases.csv` is the source — 100 cases, **80 development and 20 holdout**, split
Drums 32 / Mono 32 / Filters 24 / Ensemble 12. Results are one JSON per case in
`results/`. `tools/scorecard.py` renders the board.

There is deliberately **no spreadsheet in the repository.** A binary you cannot
read from a console cannot be diffed, grepped or reviewed in a pull request. The
sheet is a view; this is the evidence.

## The completion gate for the first 32

**Thirty-two honestly accounted-for cases — not thirty-two passing ones.** A
baseline of failures and no-verdicts is a baseline; a baseline of unrun cases is
not. What makes later improvement measurable is that every case has a stated
outcome, including the ones we could not measure and why.

## Rules the tool enforces, each because it is a way a scorecard starts lying

**An invalid measurement has no distance, not zero distance.** Zero reads as a
perfect match. It is `no verdict`, and it counts against coverage.

**A missing required component invalidates the case** rather than being dropped
from the maximum — otherwise the cheapest route to a better score is to stop
measuring the inconvenient thing.

**Distances are never averaged across units.** Milliseconds, cents and decibels
do not combine. Each is normalised by *its own* tolerance; the case reports the
worst, which is dimensionless and passes at ≤ 1.

**Coverage is reported separately and always** — *"20 passing, 4 failing, 6
without verdicts"*, never *"83 % passing"*, which conceals what was not checked.

**Every result names the engine that produced it:** `float-model`,
`fixed-model`, `integrated-rtl`, `board-digital`, `board-analog`. These are not
interchangeable, and the tool says so out loud when no case has been measured on
the integrated RTL:

> *no case has been measured on the integrated RTL. Results describe a model,
> not the instrument.*

**That is the failure this column exists to prevent** — optimising eighty cases
against a model the built instrument does not reproduce.

## What is frozen before results are collected, and why

Reference identity and patch · parameter mappings · allowed alignment and level
matching · measurement definitions · acceptance tolerances.

A fixed, calibrated cutoff conversion between synths is legitimate. **Retuning
each patch after inspecting its error is not** — it conceals a deficient control
response by fitting around it.

Holdout settings are chosen now, and they hold out **meaningful settings and
playing sequences, not different noise seeds.** A different stochastic strike
tests repeatability; it is not evidence of generalisation to a new knob setting.

And once a holdout case's detailed errors have guided a change, **it has become
development data** — a fresh independent claim needs new holdout cases.

## What a result file looks like

```json
{
  "engine": "integrated-rtl",
  "source_commit": "2024889",
  "reference_profile": "miniv3-1.3.0-patch-a",
  "render_run": "…", "analysis_run": "…", "audio": "…",
  "metrics": {
    "Pitch trajectory": {"value": 49.8, "units": "Hz", "reference": 49.4,
                         "error": 0.4, "tolerance": 1.0, "valid": true},
    "decay":            {"value": 70.0, "units": "ms", "reference": [90, 110],
                         "error": 20.0, "tolerance": 10.0, "valid": true}
  }
}
```

**Distance is kept per property, not just per case.** An accepted τ of 90–110 ms
measured at 70 is *20 ms below the range*; improving it to 85 is visible progress
before it passes — which is the point of a continuous score.
