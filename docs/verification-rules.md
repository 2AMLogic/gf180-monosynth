# Verification rules

Short, because there are only three, and they exist because each was learned
the expensive way in this repository on 2026-09-17.

---

## 1. Start red

**Before an implementation exists, run its harness against a stub with the
right ports and no behaviour, and watch it fail.** Record the result. Only
then write the implementation.

A `verify_*.py` script must support this directly:

```bash
.venv/bin/python rtl-sketch/verify_ladder.py --rtl rtl-sketch/stubs/ladder_dp_stub.v
#   first mismatch at sample 6: model -1, RTL 0, error +1 LSB
#   worst |error| 64290 LSB; error RMS 25961.9 LSB vs signal RMS 25961.9 LSB (+0.0 dB)
#   exit 1
```

Model-first is not enough. This repository was already model-first — a Python
reference model as the specification, RTL compared against it — and still shipped
four separate harnesses that had never been observed to fail:

| what | how it hid |
|---|---|
| the cocotb bit-exact suite | died at `import synth_ref` before running a test; the negative-control job read *any* non-zero exit as "bug caught" and reported four catches in 1.6 s |
| `ladder_dp_t16.v` | its `tanh` index was out of range, yosys marked the datapath don't-care, **every output was X** — and it was quoted at 1,917 cells for three rounds |
| `tb_ladder_n.v` | read 120-bit words from a 128-bit vector file; it could never have passed against anything |
| `voice_dp.v` | bit-exact over 43,200 frames with **zero** injected-bug controls, so nothing had shown the bench could detect a defect |

Every one is the same shape: **a harness nobody had watched fail.** Starting
red catches all four by construction, and costs about fifteen lines of stub.

### The hardware-specific part

In software an unimplemented function raises. In hardware it outputs **X**, and
an X comparison can silently pass depending on how the bench is written — which
is exactly how `ladder_dp_t16` survived. So the red run must distinguish three
outcomes, not two:

- **X** — the design did not elaborate, or synthesis optimised it away
- **wrong value** — it computes, incorrectly
- **right value** — it computes correctly

A bench that reports "mismatch" for all three is fine. A bench that reports
"pass" for X is not a bench. Check this explicitly; do not assume it.

---

## 2. Every bench carries injected-bug controls

A green bench means nothing until each control has been demonstrated to turn it
red, with a mismatch count. Target the things most likely to be silently wrong
rather than the easy ones — in this design that has meant the PolyBLEP square
sign flip (backwards measures 5 dB *worse* than no correction at all), the
envelope release floor (without it a note never ends), and the resonance
compensation lookup (without it the filter dies above 3 kHz).

---

## 3. A cell count is not evidence of correctness

Synthesis and cycle counts establish area and schedule. They say nothing about
whether the circuit computes anything: a netlist whose every output is X has an
area, and it was reported here three times before anyone simulated it.

Quote area only alongside a simulation result, and say which flow produced it —
`klt` allows `*_1` cells and ORFS excludes them by default, which is a 22–42 %
difference on the same RTL.
