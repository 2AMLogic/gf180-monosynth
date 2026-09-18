# Working in this repository

Read `docs/verification-rules.md` first — start red, carry injected-bug
controls, a cell count is not evidence of correctness. Then read
`docs/failure-modes.md`, which root-causes why this project keeps producing
confident wrong answers: **internal consistency is cheap to check and external
grounding is expensive, so work drifts toward the cheap check — and the cheap
check feels like rigour because it is rigorous in form.**

Four consequences that will bite you specifically:

- **An estimator calibrated on our own model is not validated.** It needs a
  signal whose answer is known independently of the thing being measured. A
  probe calibrated the other way reported 25 dB of separation that turned out
  to be window leakage.
- **A suite that only tests against our own decision records cannot tell you
  the model is right.** The voice has 42 such tests and, until today, zero
  external references.
- **Check that the thing you are testing is the thing that ships.** Every bench
  drove the register write port rather than the link, so the control path
  delivered 37 of 155 writes with every block still bit-exact.
- **Sweep a parameter before arguing about it.** Hours went into 8 modes versus
  12; yosys pads the bank to a power of two, so 9 through 16 cost identically,
  and the variable that mattered was `NUMS`.

**And a second root cause, from the measurement apparatus rather than the
evidence: preconditions assumed rather than asserted.** Every one of these was
a correct instrument in a wrong state — an unlicensed Diva inserting clicks for
hours, a Model D rendering exact silence, Surge renaming parameter 265 from
"Unison Voices" to "High Cut" by oscillator type, Mini V3 defaulting to a
sub-audio octave, all three plugins appearing to step at 94 Hz because that was
the host's block rate.

- **Assert your apparatus's preconditions at the point of use, and REFUSE
  rather than report when they fail.** `REFUSED` is a first-class outcome,
  distinct from pass and fail. A tool that answers when it cannot is worse than
  one that is absent, because its output looks exactly like data.
- **Run a gate against the current state before committing it.** Three
  unsatisfiable gates were written here in one day. An unsatisfiable gate is
  worse than no gate: it trains everyone to ignore gates, including the ones
  that work.
- **Publish your wrong-then-right rate** where the numbers are read. One
  session produced five measurements that were wrong before they were right,
  all caught by controls rather than inspection. That rate is how a reader
  calibrates any single figure.

This file is about how to work, not what to build.

## Write Python, not bash

**Anything with logic goes in Python.** Bash is for a single command with no
branching, no arithmetic and no error handling. This is not style: the bash
version of `tools/run_all.py` printed **`FAIL(??)` for a job that exited 1**,
because `eval "cmd; exit 1"` exits the subshell before the wrapper can record
the status — *an unknown rendered in the place where a result belongs.*

The same session produced `exit=$?` after a pipe (capturing `tail`'s status,
not the command's) **three separate times**, each one reporting success for a
command that had failed.

Python's `subprocess.run` cannot do either. Everything else here is Python and
is tested; tooling should be too.

## Waiting is the expensive part, not the work

Simulation here is slow: a bit-exact voice run is 255,060 frames and takes
~20 minutes under iverilog; gate-level drum runs take an hour. You will be
waiting a lot. **How you wait dominates the cost of the session.**

The thing to understand: a check is not cheap just because the command is
cheap. Every time you wake to look at a job you re-process your whole context.
Two hours in that is several hundred thousand tokens, so `ls build/` costs the
same as a hard reasoning turn. Twenty polls is twenty full-context passes with
no work in them.

Five of six agents on this repository burned a large fraction of their budget
in polling loops after their work was already finished on disk. That is the
single biggest avoidable cost here.

### Do this

**Block in one command.** Exit when the condition is true, with
`run_in_background: true`. One tool call, one notification, zero turns while
waiting:

```bash
until [ -f rtl-sketch/build/results.json ]; do sleep 2; done
```

**Chain the follow-up work into the same command.** Do not return to the model
between running a thing and reading its result:

```bash
.venv/bin/python rtl-sketch/verify_voice.py --set full > /tmp/v.log 2>&1 \
  && grep -E "PASS|mismatch" /tmp/v.log
```

**End your turn.** You are re-invoked when a background job completes. Firing a
job and stopping costs nothing while it runs. Firing a job and polling costs a
full turn per check.

**Use `Monitor` for progress you actually need to see** — it streams stdout
lines as events without a turn each. Filter to the lines you would act on,
including failures, not just the success marker.

### Do not do this

- launch several background jobs and then loop checking all of them
- `sleep`, check, `sleep`, check
- re-run a long job to see whether it still passes when you have not changed
  anything it depends on
- report "waiting on the run" as a turn. If the work is done and only a report
  is missing, write the report

### If you are stopping because you are blocked

Say what you are blocked on and end the turn. Do not spin. The coordinator can
read your worktree directly, and has had to several times — every agent whose
work was harvested that way had already finished it.

## Worktrees

Several agents work here at once. Use your own:

```bash
git worktree add /tmp/wt-<yourtask> -b <branch> main
```

Do not commit in the main checkout, and do not edit files another agent owns —
your brief says which are yours. Expect to merge.
