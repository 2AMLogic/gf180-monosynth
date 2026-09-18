# Plans as received

Working documents from review, preserved verbatim so nothing is lost and so
later decisions can be traced to what they were responding to. **These are
inputs, not the repository's position** — where they and the repo's own docs
disagree, the repo's docs are what the build enforces.

| file | what it carries |
|---|---|
| `instrument-execution-plan-v0.30.md` | the 100-case plan, the scoring rule, and the reference-qualification requirements |
| `instrument-scorecard-v0.30.xlsx` | the sheet itself — Progress / Sound cases / Release. **Measurements deliberately blank**: nobody has run this benchmark yet |
| `instrument-testing-ladder-v0.27.md` | the earlier gated ladder |
| `instrument-testing-plan-v0.25.md` | the earlier testing plan |

## What v0.30 adds that our own documents did not have

**A continuous score, so improvement is visible before a case passes.**

```
worst normalized error = max(metric error / metric tolerance)
```

At or below 1 the case passes. Crucially: **a missing component invalidates the
case rather than being omitted from the maximum** — so dropping an inconvenient
measurement cannot improve the number.

**Four separate reports**, never merged: coverage (with missing and no-verdict
reasons) · agreement (by family and by reference profile) · **error movement**
against both the frozen baseline and the previous candidate, including the worst
five and any regressions · implementation status.

**Tolerances calibrated on reference repeats and deliberately altered examples,
then frozen.** And: *if a metric cannot distinguish a meaningful injected error
from ordinary reference variation, give it no verdict and repair or replace it.*
That is our blindness matrix promoted to an acceptance criterion.

**Do not expand tolerances merely to make the current design pass.**

**Every intended difference keeps its original reference error visible.** A
deliberate product choice may change the release target; it does not
retroactively make the emulation comparison pass. That is sharper than our
"two scores" rule.

**Holdout discipline that survives contact.** Reserved cases have their settings
sealed before tuning, and **once their detailed errors guide development they
become development cases and need replacing** for a fresh holdout claim.

**Do not fabricate a variation by scaling a WAV.** A different stochastic strike
tests repeatability; it is not evidence of generalisation to a new knob setting.

**Correct known host latency once**, rather than shifting every note
independently — which would hide exactly the timing defects we want to find.

**Only compare dynamics a reference actually implements.** An extra velocity
response is not faithful Model D behaviour if the chosen reference patch does
not respond to velocity.

**And the clearest argument yet for why FAD cannot replace paired checks:**
shuffling the same clips among the wrong note or patch labels leaves the
aggregate audio distribution unchanged. A hundred related cases also does not
establish human indistinguishability.

## Where this supersedes our own drafts

`docs/reference-ladder.md` and the scorecard sketch in issue #75 are earlier and
less developed. Their surviving contributions are the five cell states and the
separation of **reference fidelity / digital quality / functional correctness**,
which v0.30 does not name explicitly and which should be carried forward.

One correction v0.30 makes to our sequencing, already accepted: the Surge fix
blocks comparisons **using that driver**, not reference comparison generally.
Hardware-808 rows, Mini V3 rows, Model D rows, envelope and glide tests against
specified behaviour, aliasing against analytic references, and the whole of the
scorecard infrastructure can proceed now.
