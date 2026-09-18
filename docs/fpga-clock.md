# The clock, on an FPGA

`synth_top` is the **I2S master**. LRCLK is bit 7 of its frame cycle counter and
BCLK is bit 1; there is no MCLK input and nothing is slaved to a codec. So the
core clock *is* the sample rate, and the sample rate *is* the tuning:

    fs    = f_core / 256
    pitch = 1200 * log2(f_core / 12.288 MHz)  cents

This file exists because the build on `flow/fpga` got that wrong in a way that
a timing constraint cannot fix, and the mistake is easy to repeat.

---

## 1. What was wrong

`fpga/boards/ulx3s.lpf` said

    LOCATE COMP "clk" SITE "G2";
    FREQUENCY PORT "clk" 12.288 MHz;

SITE G2 on a ULX3S is the board's **25 MHz** oscillator — the board's own
constraint file (`emard/ulx3s`, `doc/constraints/ulx3s_v20.lpf`) names it
`clk_25mhz` and declares it at 25 MHz. Nothing in the design changed that
frequency: the routed report says

    EHXPLLL:       0/      2     0%

so no PLL was instantiated and the 25 MHz pin drove the core directly.

`FREQUENCY PORT` is an **assertion the tool checks**, not a frequency the tool
creates. nextpnr dutifully verified that the placed design would meet 12.288 MHz
and reported `PASS at 12.29 MHz`. On a board it would have run at 25 MHz:

| | value |
|---|---|
| f_core | 25.000000 MHz |
| fs | **97 656.25 Hz** |
| ratio to 12.288 MHz | 2.03450521 |
| pitch error | **+1229.6 cents** — an octave plus 29.6 cents |

A 33.01 MHz Fmax result says the design *can* be clocked at 12.288 MHz. It says
nothing about whether anything on the board produces 12.288 MHz.

---

## 2. Why 12.288 MHz is not directly reachable from 25 MHz

12.288 / 25 = 1536 / 3125, and 3125 = 5^5.

With `FEEDBK_PATH="CLKOP"` the ECP5 EHXPLLL's primary output is

    CLKOP = Fin * CLKFB_DIV / CLKI_DIV

an integer ratio. To get 3125 into the denominator you need CLKI_DIV and one
other divider to multiply to 3125 with both ≤ 128, and the only such factor
pair is 25 x 125. CLKI_DIV = 25 puts the phase detector at 25/25 = 1 MHz, below
the ECP5's 3.125 MHz minimum. So the primary output cannot do it, which is why
`ecppll -i 25 -o 12.288` answers **12.5 MHz** — 17 253 ppm out, 29.7 cents
sharp — without saying that it has given up.

## 3. What does work: the secondary output divider

Each secondary output has its own divider off the same VCO, so the reachable set
is larger:

    PFD  = Fin / CLKI_DIV                    (3.125 .. 400 MHz)
    VCO  = PFD * CLKFB_DIV * CLKOP_DIV       (400 .. 800 MHz)
    CLKOS = VCO / CLKOS_DIV                  (3.125 .. 400 MHz)

`fpga/scripts/pll_search.py` enumerates that set. The best point for 25 MHz in:

| | |
|---|---|
| CLKI_DIV | 1 → PFD = 25 MHz |
| CLKFB_DIV | 1 |
| CLKOP_DIV | 29 → VCO = 725 MHz |
| CLKOS_DIV | 59 |
| **CLKOS** | **725/59 = 12.288135593 MHz** |
| error | **+11.03 ppm, +0.019 cents** |
| fs | **48 000.530 Hz** (+0.53 Hz) |

That is the configuration in `fpga/rtl/ulx3s_top.v`. CLKOP (25 MHz) exists only
as the feedback path and drives nothing.

### Two things worth saying plainly

* This repository's `fpga/README.md` previously recorded **~12.2807 MHz
  (−594 ppm, −1.03 cents)** as the best the ECP5 PLL could do from 25 MHz.
  That figure is a real reachable point — it is `CLKOP_DIV=28, CLKOS_DIV=57` —
  but it is not the best one. 725/59 is **54x closer**.
* +11 ppm is below the ULX3S oscillator's own tolerance. A plain ±30 ppm part
  (many ULX3S boards carry ±50 ppm) contributes 3–5x more tuning error than the
  PLL does, so at this setting **the crystal, not the PLL, sets the tuning**.
  Quoting the instrument as "in tune to 11 ppm" would be wrong; the honest
  statement is "the PLL contributes +0.019 cents and the board's crystal
  contributes ±0.05 cents, so the tuning is crystal-limited".

Reproduce the table:

```sh
python3 fpga/scripts/pll_search.py            # 25 MHz, the ULX3S
python3 fpga/scripts/pll_search.py --fin 12   # a 12 MHz board, for comparison
```

## 4. How far this has been verified, and how far it has not

**Verified.** The divider arithmetic is exact rational arithmetic — 725/59 MHz
is a closed form, not a fit — and every parameter is inside the datasheet
windows quoted above (FPGA-DS-02012). The PLL is instantiated: the ECP5
synthesis for `ulx3s_top` maps `1 EHXPLLL`, against `0/2` before. nextpnr
derives the core clock constraint from the instance's `FREQUENCY_PIN_CLKOS`
attribute rather than from the LPF, so the constraint it checks is the one the
PLL actually produces; `fpga/reports/ecp5_25f.txt` prints the constraint
nextpnr used next to the Fmax it achieved.

**Not verified.** Nothing here has been measured on a board. No bitstream has
been loaded, no counter gated against a reference, no frequency counter on
LRCLK. The number 12.288135593 MHz is *computed* from the integer dividers and
the nominal 25 MHz oscillator. The first thing bring-up should do is count
LRCLK edges against a known reference for 10 s and check it against 48 000.53 Hz
— that measurement does not exist yet and is not claimed.

## 5. If the sample rate has to be exact

Feed the core 12.288 MHz directly. A 12.288 MHz CMOS oscillator can replace the
board's reference or drive a GPIO used as the clock input; then fs is exactly
48 000 Hz to the new part's own tolerance and the PLL is not in the path.

On **iCE40** there is no choice: the PLL's output range starts at 16 MHz, so
`icepll -i 12 -o 12.288` refuses outright, and an iCE40 board must carry a
12.288 MHz or 24.576 MHz oscillator. The iCEBreaker's stock 12 MHz runs the
instrument 2.3 % flat, about 40 cents.

For completeness, the best an ECP5 PLL can do from a **12 MHz** reference is
12.285714286 MHz (−186 ppm, −0.32 cents) — worse than from 25 MHz, because 25
happens to sit near a convenient VCO point.
