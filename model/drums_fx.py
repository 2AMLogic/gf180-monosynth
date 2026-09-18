"""Fully integer drum section, TR-808-shaped: the executable specification of
contract section 15 (DR 0008). Nothing evaluated per frame is float; float is
allowed only in the host conversions at the bottom (Hz, seconds and levels to
register values), the same rule as model/voice_fx.py.

What the 808 is, per docs/tr808-reference.md, and what that makes this block:

  * BD, SD, toms are BRIDGED-T RESONATORS pinged by a pulse and left to ring:
    two-pole resonators, i.e. modes of the modal bank (model/modal_fixed.py).
    They are coefficient presets, not hardware. Nothing resets their state
    at a hit; a hit while ringing interferes with the ring, as the circuit
    does (reference 2, "retrigger while ringing").
  * CH, OH, CB are SIX SQUARE-WAVE OSCILLATORS summed to a 7-level staircase
    -- not noise -- through a band-pass, an asymmetric "swing" VCA and a
    high-pass. The band-pass and high-passes are modes of the same bank with
    a numerator selected (BP: 1 - z^-2, HP: (1 - z^-1)^2); the six squares
    are phase accumulators; the swing VCA is x4 on the positive half, /8 on
    the negative, through the ladder's tanh table (contract Appendix C).
  * SD's snap and CP are WHITE NOISE from one shared source (the 808 has one
    noise generator) through a high-pass / band-pass mode and an envelope;
    the clap's envelope is three bursts 10 ms apart plus a tail.

So the block is: 8 edge-triggered stops -> 12 exponential-decay envelopes
(fired by a stop, optionally held, re-struck for bursts, choked by another
stop) -> 16 routing PATHS, each `v = nl(source) * (env_a + env_b) >> (15 +
att)` on ONE multiplier, summed exactly into the mix bus or into one mode's
excitation -> the modal bank (12 modes, the first 6 with numerators) -> the
body bus. Two buses leave: `dmix` (21-bit exact sum of the paths routed to
MIX) and `body` (the bank's 19-bit Q4.15 word). The instrument's output stage
(`output_fx`) sums them with the voice under three gains and clamps ONCE
(contract 12): there is no clip inside this block other than the modal state
word's sat28 (part of the bank's arithmetic since rev 1) and the tap's rail.

Formats (contract 15.1):
    stops       8 bits; a 0->1 change between consecutive frames fires
    accent      Q0.15 per stop, 16 bits (32768 = 1.0; 65535 = 2.0 is legal)
    envelope    level 24-bit unsigned Q0.24; peak 24; rate Q0.16; hold 8 bits
                (frames); bursts 2 bits; period 9 bits; t 11-bit frame counter
                decay: level -= max(1, (level * rate) >> 16) -- the voice's
                release rule, dead zone closed by the max(1, .), section 8.3
    path        src 5 bits, e1/e2 4 bits, nl 2, att 3, dest 4 (22 bits)
    sources     Q1.15: NOISE (16 LFSR bits per frame), SQSUM (six squares,
                +-5461 each), PULSE (32767), SQPAIR (squares 4 + 5, +-16383
                each), SQ i (one square alone, +-16383, i = 0..5 at src 5..10),
                TAP m = sat16(y1[m] >> 3), the mode's state / 8
    envsum      ENV(e1) + ENV(e2), ENV(e) = level >> 9; index 15 reads 32767
    v           17 bits; dmix and every exc exact, 21 bits
    LFSR        31 bits, x^31 + x^15 + x^13 + x^11 + 1, seed 1, 16 steps per frame
    oscillators 6 x 24-bit phase accumulators, host-written increments
    bank        ModalFx(modes=12, nums=6, headroom=0, out_bits=19)
"""
from __future__ import annotations
import math
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audition"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from dsp import SR, PHASE_BITS, PHASE_MASK, phase_inc
from fixed import LadderFx, sat, usat
from voice_fx import LADDER_CFG, VOL_REF
import modal_fixed
from modal_fixed import ModalFx, RAW, BP, HP, pole_regs

# ---- sizes (contract 15.1) ----------------------------------------------------
N_STOPS, N_ENV, N_PATH, N_MODES, N_NUMS, N_OSC = 8, 12, 16, 12, 6, 6
ENV_BITS, RATE_Q, ACCENT_BITS = 24, 16, 16
HOLD_BITS, BURST_BITS, PERIOD_BITS, T_BITS = 8, 2, 9, 11
T_MAX = (1 << T_BITS) - 1
BURST_C = 53248                  # 13/16 in Q0.16: each re-strike is 13/16 of the last (15.3)
LFSR_BITS, LFSR_SEED = 31, 1     # x^31 + x^15 + x^13 + x^11 + 1 (15.4)
LFSR_TAPS = (30, 15, 17, 19)     # state bits XORed for the new bit: delays 31, 16, 18, 20
LFSR_MASK = (1 << LFSR_BITS) - 1
NOISE_BITS = 16                  # LFSR steps per frame = bits per noise word
SQ_STEP, SQPAIR_STEP = 5461, 16383   # six squares sum to +-32766; the pair to +-32766
SQPAIR = (4, 5)                  # the 808's trimmed oscillators 5 and 6 (800 and 540 Hz)
TAP_SHIFT = 3                    # TAP m = sat16(y1[m] >> 3): the state / 8, rails at +-8.0 (15.5)
SRC_OFF, SRC_NOISE, SRC_SQSUM, SRC_PULSE, SRC_SQPAIR, SRC_SQ, SRC_TAP = 0, 1, 2, 3, 4, 5, 16
NL_LIN, NL_SWING, NL_TANH = 0, 1, 2
DEST_MIX, ENV_FULL = 15, 15
MIX_BITS = 21                    # 16 paths x 17-bit values, exact
BODY_HR, BODY_BITS = 0, modal_fixed.OUT_BITS
FULL24 = (1 << ENV_BITS) - 1

# ---- the register map (contract 15.1): 8-bit address, 32-bit value ----------
A_STOPS, A_ACCENT, A_OSC, A_ENV, A_PATH, A_MODE, A_RESET = 0x00, 0x10, 0x20, 0x40, 0x80, 0xC0, 0xFF
ENV_STRIDE, MODE_STRIDE = 4, 4   # ENV: +0 ctl, +1 peak, +2 rate; MODE: +0 a1, +1 a2, +2 amp, +3 num
REG_BITS = dict(stops=N_STOPS, accent=ACCENT_BITS, osc_inc=PHASE_BITS, env_ctl=27, peak=ENV_BITS,
                rate=RATE_Q, path=22, a1=26, a2=26, amp=16, num=2)


def env_ctl(stop: int, choke: int = 15, hold: int = 0, bursts: int = 0, period: int = 0) -> int:
    """ENV_CTL word: [3:0] stop, [7:4] choke, [15:8] hold, [17:16] bursts, [26:18] period.
    A stop or choke index >= 8 means never."""
    return ((usat(stop, 4)) | (usat(choke, 4) << 4) | (usat(hold, HOLD_BITS) << 8)
            | (usat(bursts, BURST_BITS) << 16) | (usat(period, PERIOD_BITS) << 18))


def path_word(src: int, e1: int, e2: int = 14, nl: int = NL_LIN, att: int = 0, dest: int = DEST_MIX) -> int:
    """PATH word: [4:0] src, [8:5] e1, [12:9] e2, [14:13] nl, [17:15] att, [21:18] dest.
    e = 15 reads as full scale, 12..14 as zero (so e2 = 14 is 'no second envelope')."""
    return (usat(src, 5) | (usat(e1, 4) << 5) | (usat(e2, 4) << 9) | (usat(nl, 2) << 13)
            | (usat(att, 3) << 15) | (usat(dest, 4) << 18))


def s26(v: int) -> int:
    """A 26-bit two's-complement field as a signed integer."""
    v &= (1 << 26) - 1
    return v - (1 << 26) if v & (1 << 25) else v


# ---- the noise source (contract 15.4) -------------------------------------------
def lfsr_frame(state: int) -> tuple[int, int]:
    """One frame of the LFSR: 16 steps of
        s <- (s << 1) | (s[30] ^ s[15] ^ s[17] ^ s[19])
    on a 31-bit state, the recurrence b[n] = b[n-31] + b[n-16] + b[n-18] +
    b[n-20] over GF(2), whose characteristic polynomial x^31 + x^15 + x^13 +
    x^11 + 1 is primitive (2^31 - 1 is prime, so irreducible is enough;
    test_drums_fx checks it). Returns (new state, noise word): the 16 bits
    shifted in, oldest first, read as a signed Q1.15 value. Every bit is one
    output of a maximal-length sequence and consecutive words are disjoint
    16-bit windows of it. Period 2^31 - 1 bits, 12.4 h.

    Why a pentanomial and not the strawman's trinomial: from the sparse
    reset state a trinomial LFSR's ones density recovers slowly (the
    Mersenne Twister's zero-excess problem): x^31 + x^3 + 1 measured a
    +351 mean over the first 200 000 words and +117 over the next 100 000,
    a 0.5 % ones deficit; this polynomial measures -5 and -29, inside a
    uniform source's fluctuation. All four taps are at bit 15 or above, so
    the 16 new bits of a frame are a function of the old state alone."""
    s = state
    for _ in range(NOISE_BITS):
        bit = 0
        for t in LFSR_TAPS:
            bit ^= (s >> t) & 1
        s = ((s << 1) | bit) & LFSR_MASK
    w = s & 0xFFFF
    return s, (w - 0x10000 if w & 0x8000 else w)


def lfsr_frame_leap(state: int) -> tuple[int, int]:
    """The same 16 steps computed at once, as the RTL does: new bit i (i = 0
    the first) is the XOR of s[t - i] over the taps, all from the OLD state
    since every tap is at bit 15 or above."""
    bits = 0
    for i in range(NOISE_BITS):
        b = 0
        for t in LFSR_TAPS:
            b ^= (state >> (t - i)) & 1
        bits = (bits << 1) | b
    s = ((state << NOISE_BITS) | bits) & LFSR_MASK
    return s, (bits - 0x10000 if bits & 0x8000 else bits)


# ---- one envelope (contract 15.3) ------------------------------------------------
class EnvFx:
    """Exponential decay with a fire, an optional hold, optional re-strikes
    and a choke. Per frame, before the paths read it:

        fired (its stop went 0->1 this frame):
            level <- usat24((peak * accent[stop]) >> 15); strike <- level; t <- 0
        else:
            t <- min(t + 1, 2047)
            t < hold:                        level unchanged (the 1 ms pulse)
            bursts >= k and t == k * period  (k = 1, 2, 3):
                                             strike <- (strike * 53248) >> 16; level <- strike
            otherwise:                       dec <- (level * rate) >> 16
                                             level <- max(0, level - max(1, dec))
        choked (its choke stop went 0->1 this frame): level <- 0
        ENV = level >> 9                      (Q0.15, what the paths multiply by)

    The `max(1, dec)` is the voice's (8.3): below level = 2^16 / rate the
    product truncates to zero and the tail would never end; with it the tail
    below that floor is one LSB per frame and reaches exactly zero. `floor`
    exists to measure that, like LadderFx's `interp`."""
    __slots__ = ("stop", "choke", "hold", "bursts", "period", "peak", "rate",
                 "level", "strike", "t", "floor", "n_fire", "n_choke", "n_restrike", "n_floor")

    def __init__(self, floor: bool = True):
        self.stop = self.choke = self.hold = self.bursts = self.period = 0
        self.peak = self.rate = 0
        self.floor = floor
        self.n_fire = self.n_choke = self.n_restrike = self.n_floor = 0   # coverage, not state
        self.reset()

    def reset(self):
        self.level = self.strike = self.t = 0

    def set_ctl(self, word: int):
        self.stop, self.choke = word & 15, (word >> 4) & 15
        self.hold, self.bursts, self.period = (word >> 8) & 255, (word >> 16) & 3, (word >> 18) & 511

    def frame(self, fire: int, accents):
        if self.stop < N_STOPS and (fire >> self.stop) & 1:
            self.level = usat((self.peak * accents[self.stop]) >> 15, ENV_BITS)
            self.strike = self.level
            self.t = 0
            self.n_fire += 1
        else:
            self.t = min(self.t + 1, T_MAX)
            t = self.t
            if t < self.hold:
                pass
            elif self.period and any(t == k * self.period for k in (1, 2, 3) if k <= self.bursts):
                self.strike = (self.strike * BURST_C) >> 16
                self.level = self.strike
                self.n_restrike += 1
            else:
                dec = (self.level * self.rate) >> RATE_Q
                if dec == 0:
                    self.n_floor += self.level > 0
                    if self.floor:
                        dec = 1
                self.level = max(0, self.level - dec)
        if self.choke < N_STOPS and (fire >> self.choke) & 1:
            self.level = 0
            self.n_choke += 1

    @property
    def out(self) -> int:
        return self.level >> (ENV_BITS - 15)

    @property
    def floor_level(self) -> int:
        """Below this level the exponential step is zero and the tail is
        linear at one LSB per frame: 2^16 / rate (rate = 0: everything)."""
        return (1 << RATE_Q) // self.rate + 1 if self.rate else FULL24


# ---- the drum section --------------------------------------------------------------
class DrumsFx:
    """8 stops, N_ENV envelopes, N_PATH paths, six squares, one LFSR and the
    modal bank. `write` is the register interface of 15.1; `play` applies a
    list of (frame, addr, value) writes at frame starts (4.3) and returns
    the two buses. All control registers reset to 0 (15.8) and the block is
    silent until programmed."""

    def __init__(self, envs=N_ENV, paths=N_PATH, modes=N_MODES, nums=N_NUMS, floor=True):
        self.E, self.P, self.M = envs, paths, modes
        self.bank = ModalFx(modes=modes, nums=nums, headroom=BODY_HR, out_bits=BODY_BITS)
        self.tanh = LadderFx(**LADDER_CFG)
        self.floor = floor
        self.n_tapsat = 0            # coverage: taps that hit the +-8.0 rail (15.5)
        self.n_late_writes = 0       # writes scheduled past the end of a play()
        self.trace = {}
        self.reset()

    def reset(self):
        self.stops = self.stops_prev = 0
        self.accent = [0] * N_STOPS
        self.osc_inc = [0] * N_OSC
        self.phase = [0] * N_OSC
        self.lfsr = LFSR_SEED
        if not hasattr(self, "envs"):
            self.envs = [EnvFx(self.floor) for _ in range(self.E)]
        for env in self.envs:                    # state and control to 0; the coverage counters stay
            env.reset(); env.set_ctl(0); env.peak = env.rate = 0
        self.paths = [0] * self.P
        self.a1 = [0] * self.M
        self.a2 = [0] * self.M
        self.amp = [0] * self.M
        self.num = [0] * self.M
        self.bank.reset()

    # ---- control (contract 15.1) ---------------------------------------------
    def write(self, addr: int, value: int):
        addr, value = int(addr), int(value)
        if addr == A_RESET:
            self.reset()
        elif addr == A_STOPS:
            self.stops = value & 0xFF
        elif A_ACCENT <= addr < A_ACCENT + N_STOPS:
            self.accent[addr - A_ACCENT] = value & 0xFFFF
        elif A_OSC <= addr < A_OSC + N_OSC:
            self.osc_inc[addr - A_OSC] = value & PHASE_MASK
        elif A_ENV <= addr < A_ENV + self.E * ENV_STRIDE:
            e, f = divmod(addr - A_ENV, ENV_STRIDE)
            if f == 0:
                self.envs[e].set_ctl(value)
            elif f == 1:
                self.envs[e].peak = value & FULL24
            elif f == 2:
                self.envs[e].rate = value & 0xFFFF
        elif A_PATH <= addr < A_PATH + self.P:
            self.paths[addr - A_PATH] = value & ((1 << 22) - 1)
        elif A_MODE <= addr < A_MODE + self.M * MODE_STRIDE:
            m, f = divmod(addr - A_MODE, MODE_STRIDE)
            if f == 0:
                self.a1[m] = s26(value)
            elif f == 1:
                self.a2[m] = s26(value)
            elif f == 2:
                self.amp[m] = value & 0xFFFF
            else:
                self.num[m] = value & 3
        # any other address: no register, the write is ignored (15.1)

    # ---- one frame (contract 15.2) ---------------------------------------------
    def _env_value(self, e: int) -> int:
        if e < self.E:
            return self.envs[e].out
        return 32767 if e == ENV_FULL else 0

    def _nonlinear(self, x: int, nl: int) -> int:
        """LIN: x. SWING: x4 on the positive half, /8 on the negative, then
        tanh. TANH: tanh. The tanh is the ladder's (11.3) on the Q1.15 value
        scaled to its Q4.20 argument, so 1.0 maps to tanh(1.0) = 0.76 and
        the swing's 4.0 to the table's clamp (15.5)."""
        if nl == NL_LIN:
            return x
        if nl == NL_SWING:
            x = (x << 2) if x > 0 else (x >> 3)
        return self.tanh.tanh_fx(sat(x << 5, 24))

    def frame(self):
        fire = self.stops & ~self.stops_prev & 0xFF
        self.stops_prev = self.stops
        for env in self.envs:                                   # 15.3, before the paths
            env.frame(fire, self.accent)
        self.lfsr, noise = lfsr_frame(self.lfsr)                # 15.4
        sq = [SQ_STEP if p < (1 << (PHASE_BITS - 1)) else -SQ_STEP for p in self.phase]
        sqsum = sum(sq)
        sq1 = [SQPAIR_STEP if p < (1 << (PHASE_BITS - 1)) else -SQPAIR_STEP for p in self.phase]
        sqpair = sq1[SQPAIR[0]] + sq1[SQPAIR[1]]
        for i in range(N_OSC):
            self.phase[i] = (self.phase[i] + self.osc_inc[i]) & PHASE_MASK
        y1 = self.bank.y1
        dmix = 0
        exc = [0] * self.M
        vals = []
        for w in self.paths:                                    # 15.5, in order
            src, e1, e2 = w & 31, (w >> 5) & 15, (w >> 9) & 15
            nl, att, dest = (w >> 13) & 3, (w >> 15) & 7, (w >> 18) & 15
            if src == SRC_NOISE:
                s = noise
            elif src == SRC_SQSUM:
                s = sqsum
            elif src == SRC_PULSE:
                s = 32767
            elif src == SRC_SQPAIR:
                s = sqpair
            elif SRC_SQ <= src < SRC_SQ + N_OSC:
                s = sq1[src - SRC_SQ]
            elif SRC_TAP <= src < SRC_TAP + self.M:
                s = y1[src - SRC_TAP] >> TAP_SHIFT
                self.n_tapsat += not (-32768 <= s <= 32767)
                s = sat(s, 16)
            else:
                s = 0
            s = self._nonlinear(s, nl)
            v = (s * (self._env_value(e1) + self._env_value(e2))) >> (15 + att)
            vals.append(v)
            if dest == DEST_MIX:
                dmix += v
            elif dest < self.M:
                exc[dest] += v
        coefs = list(zip(self.a1, self.a2, self.amp))
        body = self.bank.step(exc, coefs, self.num)             # 15.6
        return dmix, body, fire, noise, sqsum, exc, vals

    def play(self, writes, n: int):
        """n frames; `writes` is a list of (frame, addr, value), applied at the
        start of their frame in list order. Returns (dmix, body) as int64 /
        int32 arrays; `self.trace` holds the per-frame internals. A write at a
        frame at or past `n` is dropped and counted in `self.n_late_writes` --
        it could not have affected any sample -- and a negative frame raises."""
        ev = {}
        self.n_late_writes = 0
        for f, a, v in writes:
            f = int(f)
            assert f >= 0, f"write ({f}, {a:#x}, {v}) before frame 0"
            if f >= n:
                # A write scheduled after the last frame cannot affect any
                # sample, so it is DROPPED rather than rejected. The
                # coefficient sequences of 15.7.1 run to 60 ms past a hit, and
                # a caller rendering a shorter passage than that must not have
                # to know it -- `render(..., 0.012)` in an acceptance suite is
                # a legitimate thing to ask for. Counted so a test can see how
                # many were dropped; a negative frame is still a caller error.
                self.n_late_writes += 1
                continue
            ev.setdefault(f, []).append((a, v))
        dmix = np.empty(n, dtype=np.int64)
        body = np.empty(n, dtype=np.int32)
        fire = np.empty(n, dtype=np.int64)
        noise = np.empty(n, dtype=np.int64)
        env = np.empty((self.E, n), dtype=np.int64)
        exc = np.empty((n, self.M), dtype=np.int64)
        for f in range(n):
            for a, v in ev.get(f, ()):
                self.write(a, v)
            d, b, fi, nz, _, ex, _ = self.frame()
            dmix[f], body[f], fire[f], noise[f] = d, b, fi, nz
            exc[f] = ex
            for e in range(self.E):
                env[e, f] = self.envs[e].out
        self.trace = dict(dmix=dmix, body=body, fire=fire, noise=noise, env=env, exc=exc)
        return dmix, body


# ---- the instrument's output stage (contract 12) ------------------------------------
def output_fx(v, vol: int, dmix, dvol: int, body, bvol: int) -> np.ndarray:
    """sample = sat16((v * vol + dmix * dvol + body * bvol) >> 15): the voice's
    VCA output (9), the drum mix bus and the body bus under three Q0.15 gains,
    summed exactly, shifted, clamped once -- the one hard rail. With dvol =
    bvol = 0 it is the voice's rev-3 formula bit for bit."""
    v = np.asarray(v, dtype=np.int64); dmix = np.asarray(dmix, dtype=np.int64)
    body = np.asarray(body, dtype=np.int64)
    acc = v * int(vol) + dmix * int(dvol) + body * int(bvol)
    return np.clip(acc >> 15, -32768, 32767).astype(np.int16)


# ---- host conversions (contract 15.7, informative) ---------------------------------
def rate_reg(tau_s: float) -> int:
    """Q0.16 decay rate for an amplitude time constant of tau seconds:
    round((1 - exp(-1 / (tau * SR))) * 2^16), at least 1; tau <= 0 is instant
    (65535). The voice's release conversion with tau in place of release/4."""
    if tau_s <= 0.0:
        return 65535
    return max(1, usat(int(round((1.0 - math.exp(-1.0 / (tau_s * SR))) * (1 << RATE_Q))), RATE_Q))


def accent_reg(level: float) -> int:
    return usat(int(round(level * 32768)), ACCENT_BITS)


def peak_reg(level: float) -> int:
    return usat(int(round(level * FULL24)), ENV_BITS)


def amp_reg(level: float) -> int:
    return usat(int(round(level * 65536)), 16)


def osc_inc_reg(hz: float) -> int:
    return usat(phase_inc(hz), PHASE_BITS)


def mode_regs(f0_hz: float, q: float, amp: float, num: int = RAW) -> tuple[int, int, int, int]:
    """(a1, a2, amp, num) for one mode: the pole pair of modal_fixed.pole_regs
    (docs/tr808-reference.md section 14's formula) and a Q0.16 level."""
    a1, a2 = pole_regs(f0_hz, q)
    return a1 & ((1 << 26) - 1), a2 & ((1 << 26) - 1), amp_reg(amp), num


def mode_writes(m: int, f0_hz: float, q: float, amp: float, num: int = RAW) -> list:
    base = A_MODE + m * MODE_STRIDE
    return [(base + i, v) for i, v in enumerate(mode_regs(f0_hz, q, amp, num))]


def env_writes(e: int, stop: int, tau_s: float, peak: float, *, choke: int = 15,
               hold: int = 0, bursts: int = 0, period: int = 0) -> list:
    base = A_ENV + e * ENV_STRIDE
    return [(base, env_ctl(stop, choke, hold, bursts, period)),
            (base + 1, peak_reg(peak)), (base + 2, rate_reg(tau_s))]


# ---- the reference kit (contract Appendix G, informative) -----------------------------
# Stops, in the order the host sees them.
BD, SD, LT, HT, CH, OH, CP, CB = range(8)
STOP_NAMES = ("BD", "SD", "LT", "HT", "CH", "OH", "CP", "CB")
# Modes 0..5 have numerators (the filters), 6..11 are the bridged-T bodies.
M_HATBP, M_OHHP, M_CHHP, M_SDN, M_CPBP, M_CBBP, M_BD, M_SDLO, M_SDHI, M_LT, M_HT, M_SPARE = range(12)
# Envelopes.
E_BDX, E_BDCLICK, E_SDX, E_SDN, E_LTX, E_HTX, E_CH, E_OH, E_CPBURST, E_CPTAIL, E_CBA, E_CBB = range(12)
OSC_HZ = (205.3, 369.6, 304.4, 522.7, 800.0, 540.0)   # the HD14584 bank, reference 1.5
FRAME = 1.0 / SR

# ---- the bass drum, entirely from docs/tr808-reference.md section 2 -----------
# VERIFIED IN A SOURCE [W14a section 5; computed with section 1.2 from R161,
# R165, R166, R170, C41/C42]: the bridged-T's f0 is **49.4 Hz**, and Werner
# measures ~49.5. Roland's tuning chart says 56 Hz ("18 ms"); the reference
# calls that "typical and variable" and tells the implementer to treat 50-56 Hz
# as the target. The two are not interchangeable, and rev 5 shipped the chart's
# f0 with the CIRCUIT's Q table -- which is inconsistent: section 2's decay
# table (Q 2.3/5.2/22.3/63/84 against tau 15/33/144/408/544 ms) satisfies
# tau = Q/(pi f0) to 1.5 % at f0 = 49.4 and only to 12.8 % at 56. Shipping
# Q = 22.3 at 56 Hz gives tau = 127 ms where the same table says 144. So the
# short decay was never a DECAY fault: it was the pitch error, propagated.
# DR 0009 resolves the conflict inside the reference in favour of the computed
# value, which two sample sets also corroborate (49-51 Hz).
BD_HZ, BD_HZ_CHART = 49.4, 56.0
# VERIFIED IN A SOURCE [section 2, W14a section 6]: Q against the VR6 DECAY
# knob position, the feedback buffer's own law. The DECAY CONTROL IS NOT A
# FAULT -- this is the table rev 5 already shipped. Knob positions are the
# panel's 0..10; the reference tabulates VR6's 0..1.
BD_DECAY_Q = {0.0: 2.3, 1.0: 5.2, 5.0: 22.3, 9.0: 63.0, 10.0: 84.0}
# VERIFIED IN A SOURCE [section 2, W14a section 8.1; SN p.6]: while Q43 is on
# it shorts R165, the foot resistance falls and f0 rises to ~130 Hz at Q ~ 6
# for ~4 ms ("the ON period of Q43 ... equals 4 ms"; Werner measures ~6 ms).
# It is the SAME resonator retuned, not a second one, so the host writes the
# attack coefficients at the hit and the body's 4 ms later.
BD_ATTACK_HZ, BD_ATTACK_Q, BD_ATTACK_MS = 130.0, 6.0, 4.0
# VERIFIED IN A SOURCE [section 4, SN text; magnitude inferred]: with the tom's
# germanium diodes conducting the foot resistance collapses and f0 rises to
# ~1.7x the small-signal value at the start of a hard hit, settling back as the
# ring decays -- "amplitude-dependent and gradual, not a stepped envelope", and
# "accent changes the pitch envelope". This is the toms' "doom" sweep.
TOM_DROP_RATIO, TOM_DROP_MS, TOM_DROP_STEPS = 1.7, 60.0, 6


def bd_decay_q(knob: float) -> float:
    """Q of the BD body mode for a DECAY knob position in 0..10, from the
    reference's own table, interpolated geometrically (the law is a resistive
    divider's, and log Q tracks the tabulated points to 1 % where they are
    dense). Float; host side only."""
    ks = sorted(BD_DECAY_Q)
    k = min(max(float(knob), ks[0]), ks[-1])
    return float(math.exp(np.interp(k, ks, [math.log(BD_DECAY_Q[x]) for x in ks])))


def bd_attack_writes(frame: int, restore: list = None) -> list:
    """The BD attack window as host writes (reference section 2): the body
    mode is retuned to BD_ATTACK_HZ / BD_ATTACK_Q in the frame of the hit and
    back after BD_ATTACK_MS. Two writes each way -- a1 and a2 only, because
    the level and the numerator do not move: the circuit shorts a resistor,
    it does not change the gain.

    `restore` is the (a1, a2) register PAIR to write back, and the caller
    passes what was in the image before the hit. In the circuit Q43 shorts
    R165 and then releases, so the resonator returns to whatever the DECAY
    knob currently sets -- NOT to a fixed preset. Recomputing the preset here
    would silently overwrite a host that had retuned the decay, which is
    exactly what it did to `test_808_acceptance.bd_at_decay`. Omitted, it
    restores the kit's own DECAY 5.0 setting."""
    n = int(round(BD_ATTACK_MS * 1e-3 * SR))
    hot = mode_writes(M_BD, BD_ATTACK_HZ, BD_ATTACK_Q, 0.0)[:2]
    if restore is None:
        restore = [v for _, v in mode_writes(M_BD, BD_HZ, bd_decay_q(5.0), 0.0)[:2]]
    base = A_MODE + M_BD * MODE_STRIDE
    return ([(frame, a, v) for a, v in hot]
            + [(frame + n, base + i, v) for i, v in enumerate(restore)])


def tom_pitch_drop_writes(frame: int, mode: int, f0_hz: float, q: float, amp: float,
                          accent: float = 1.0) -> list:
    """The toms' diode pitch drop as host writes (reference section 4): f0
    starts at up to TOM_DROP_RATIO x its small-signal value and relaxes back
    over TOM_DROP_MS in TOM_DROP_STEPS, the excess scaled by the accent
    because the mechanism is amplitude-dependent. Q is held: the diodes move
    the foot resistance, which the reference treats as an f0 effect."""
    out = []
    excess = (TOM_DROP_RATIO - 1.0) * min(max(accent, 0.0), 1.0)
    for i in range(TOM_DROP_STEPS + 1):
        t = i / TOM_DROP_STEPS
        hz = f0_hz * (1.0 + excess * math.exp(-3.0 * t))
        f = frame + int(round(t * TOM_DROP_MS * 1e-3 * SR))
        out += [(f, a, v) for a, v in mode_writes(mode, hz, q, amp)[:2]]
    return out


def kit_808() -> list:
    """The reference kit as a list of (addr, value) writes: every number is
    docs/tr808-reference.md's where it gives one (tagged there), and marked
    'chosen' here where it does not. Levels (`amp`, peaks) are balanced by
    `model/drums_fx_render.py --balance` so that each voice alone peaks near
    -6 dBFS on its bus at accent 1.0, in the proportions of Roland's tuning
    chart; they are the kit's, not the circuit's."""
    w = []
    for i, hz in enumerate(OSC_HZ):
        w.append((A_OSC + i, osc_inc_reg(hz)))
    # modes: filters first (numerators), then the bodies
    w += mode_writes(M_HATBP, 7117.0, 6.0, 0.0, BP)          # hats' band-pass, reference 10/11; tapped only
    w += mode_writes(M_OHHP, 7800.0, 2.5, 0.45, HP)          # OH high-pass, reference 11
    w += mode_writes(M_CHHP, 11700.0, 2.5, 0.69, HP)         # CH high-pass, reference 11
    w += mode_writes(M_SDN, 2750.0, 0.7, 0.2059, BP)         # SD snappy filter: the pole is VERIFIED
                                                             # IN A SOURCE (reference 3's 2.75 kHz /
                                                             # Q 0.7); the NUMERATOR is MEASURED -- a
                                                             # band-pass, not the high-pass 3 calls it
                                                             # (17.22). The amp is the SNAPPY knob's
                                                             # measured curve at 5.0.
    w += mode_writes(M_CPBP, 1071.0, 1.6, 0.0, BP)           # CP band-pass, reference 7; tapped only
    w += mode_writes(M_CBBP, 1100.0, 2.8, 0.02176, BP)         # CB band-pass: MEASURED -- fitted to the
                                                             # reference unit's 16 partials, closing
                                                             # reference 9's open item (DR 0010)
    w += mode_writes(M_BD, BD_HZ, bd_decay_q(5.0), 0.003309, RAW)   # BD at DECAY 5.0. f0 and Q are both
                                                             # VERIFIED IN A SOURCE (reference 2's
                                                             # component-value f0 and its own Q table),
                                                             # not the chart's 56 Hz -- DR 0009; two
                                                             # sample sets corroborate at 48.8-51.6 Hz
    w += mode_writes(M_SDLO, 173.0, 16.3, 0.002673, RAW)      # SD low, later units, reference 3
    w += mode_writes(M_SDHI, 336.0, 9.9, 0.008865, RAW)        # SD high; TONE = this pair's ratio, and
                                                             # the RATIO here is MEASURED (17.24): the
                                                             # machine at TONE 5.0 puts the upper partial
                                                             # 1.42x the lower (+3.0 dB), on both the
                                                             # SNAPPY-up and SNAPPY-down file. Rev 6
                                                             # shipped 0.394 (-8.1 dB) -- 11 dB of the
                                                             # snare's front end missing. The pair is
                                                             # then scaled together to the kit's own
                                                             # peak, which is unchanged at 0.46 FS.
    w += mode_writes(M_LT, 90.0, 25.0, 0.0078319, RAW)          # LT, reference 4
    w += mode_writes(M_HT, 185.0, 25.0, 0.0162904, RAW)         # HT, reference 4
    # envelopes: the pulse-shaper's kick is a 0.1 ms exponential (reference 2, "what to implement");
    # the bodies' exciters are 0.25 so that an accent of 2.0 keeps the BD's state (the bank's
    # loudest ring, ~720 x the kick) under a quarter of the 28-bit rail
    w += env_writes(E_BDX, BD, 0.1e-3, 0.25)
    w += env_writes(E_BDCLICK, BD, 0.0, 0.06, hold=48)       # the 1 ms pulse leaking through, reference 2
    w += env_writes(E_SDX, SD, 0.1e-3, 0.25)
    w += env_writes(E_SDN, SD, 30e-3, 0.3046)                # SNAPPY = this peak x M_SDN's amp, reference 3.
                                                             # The RATE is MEASURED (17.25): the machine's
                                                             # snappy burst measures T20 63-78 ms over six
                                                             # files; reference 3's 15 ms is R186 x C51,
                                                             # the CHARGE path, and gives 34 ms. The peak
                                                             # holds the noise share at the machine's
                                                             # 27.7 % with the new rate.
    w += env_writes(E_LTX, LT, 0.1e-3, 0.25)
    w += env_writes(E_HTX, HT, 0.1e-3, 0.25)
    w += env_writes(E_CH, CH, 20e-3, 1.0)                    # reference 11
    w += env_writes(E_OH, OH, 150e-3, 1.0, choke=CH)         # DECAY knob mid; CH chokes it, reference 11
    w += env_writes(E_CPBURST, CP, 4e-3, 0.69, bursts=2, period=480)  # three bursts 10 ms apart, reference 7
    w += env_writes(E_CPTAIL, CP, 47e-3, 0.22)               # the tail at -10 dB, reference 7 (chosen ratio)
    w += env_writes(E_CBA, CB, 5e-3, 0.5)                    # two-slope envelope, reference 9
    w += env_writes(E_CBB, CB, 100e-3, 0.5)                  # MEASURED: the reference tail is tau 98 ms
    # paths
    paths = [
        path_word(SRC_PULSE, E_BDX, dest=M_BD),
        path_word(SRC_PULSE, E_BDCLICK, dest=DEST_MIX),
        path_word(SRC_PULSE, E_SDX, dest=M_SDLO),
        path_word(SRC_PULSE, E_SDX, dest=M_SDHI),              # both from the pulse (reference 3: cascade is subtle)
        path_word(SRC_NOISE, E_SDN, dest=M_SDN),
        path_word(SRC_PULSE, E_LTX, dest=M_LT),
        path_word(SRC_PULSE, E_HTX, dest=M_HT),
        path_word(SRC_SQSUM, ENV_FULL, dest=M_HATBP),          # the six squares, always on, into the band-pass
        path_word(SRC_TAP + M_HATBP, E_CH, nl=NL_SWING, dest=M_CHHP),
        path_word(SRC_TAP + M_HATBP, E_OH, nl=NL_SWING, dest=M_OHHP),
        path_word(SRC_NOISE, ENV_FULL, dest=M_CPBP),           # noise, always on, into the clap band-pass
        path_word(SRC_TAP + M_CPBP, E_CPBURST, E_CPTAIL, nl=NL_TANH, dest=DEST_MIX),
        # the cowbell's two oscillators are gated SEPARATELY (reference 9: each has its own
        # transistor gate) and summed after: nl(a) + nl(b), never nl(a + b), which would make
        # the 260 Hz difference tone the machine has not got (15.5)
        path_word(SRC_SQ + SQPAIR[0], E_CBA, E_CBB, nl=NL_SWING, dest=M_CBBP),
        path_word(SRC_SQ + SQPAIR[1], E_CBA, E_CBB, nl=NL_SWING, dest=M_CBBP),
    ]
    for p, word in enumerate(paths):
        w.append((A_PATH + p, word))
    return w


# ---- the reference host (informative): hits and patterns to writes ------------------
def _kit_amp(kit: list, mode: int) -> float:
    """The amp register a kit image writes for one mode, back as a level."""
    a = A_MODE + mode * MODE_STRIDE + 2
    for addr, v in kit or ():
        if addr == a:
            return v / 65536.0
    return 0.0


def _kit_poles(kit: list, mode: int) -> list:
    """The (a1, a2) register pair a kit image writes for one mode, or None."""
    base = A_MODE + mode * MODE_STRIDE
    got = {}
    for addr, v in kit or ():
        if addr in (base, base + 1):
            got[addr] = v
    return [got[base], got[base + 1]] if len(got) == 2 else None


def hit_writes(hits, kit: list = None, start_frame: int = 0, coef_seq: bool = True) -> list:
    """hits: (frame, stop, accent 0..2.0). Each hit writes its stop's accent
    and raises the stop bit in that frame; the bit is dropped in the next
    frame so the next hit is an edge again. Two hits of one stop in
    consecutive frames cannot both fire (no 0->1 between them) -- a host
    leaves a frame between hits, as a slice-based host does by construction.

    `coef_seq` (the default) also emits the two coefficient sequences the
    reference describes and no register image can hold, because they are
    changes over time to ONE mode's coefficients rather than settings: the
    BD's 4 ms attack window (section 2) and the toms' diode pitch drop
    (section 4). They are the host's, not the block's -- the block already
    lets any mode be retuned on any frame (contract 15.6) -- which is why
    they live here and not in `kit_808()`, and why Appendix G is unchanged
    by them. `coef_seq=False` is the bare register image, for a host that
    sequences coefficients itself."""
    kit = kit or []
    w = [(start_frame, a, v) for a, v in kit]
    by_frame = {}
    for f, s, a in hits:
        by_frame.setdefault(int(f), []).append((int(s), float(a)))
    if coef_seq:
        for f, s_, a_ in hits:
            if s_ == BD:
                w += bd_attack_writes(int(f), _kit_poles(kit, M_BD))
            elif s_ == LT:
                w += tom_pitch_drop_writes(int(f), M_LT, 90.0, 25.0, _kit_amp(kit, M_LT), a_)
            elif s_ == HT:
                w += tom_pitch_drop_writes(int(f), M_HT, 185.0, 25.0, _kit_amp(kit, M_HT), a_)
    mask = 0
    events = {}
    for f in sorted(by_frame):
        bits = 0
        for s, a in by_frame[f]:
            w.append((f, A_ACCENT + s, accent_reg(a)))
            bits |= 1 << s
        events.setdefault(f, 0)
        events[f] |= bits
        events.setdefault(f + 1, 0)
    for f in sorted(events):
        new = events[f]
        if new != mask:
            w.append((f, A_STOPS, new))
            mask = new
    return sorted(w, key=lambda t: t[0])


PATTERN_808 = {"BD": "X...x...X..x..x.", "SD": "....X.......X...", "CH": "x.x.x.x.x.x.x.x.",
               "OH": "..x.......x.....", "CP": "............X...", "CB": "........x.......",
               "LT": "..............x.", "HT": "...........x...."}


def pattern_hits(pattern: dict, bpm: float = 118.0, bars: int = 2, swing: float = 0.0,
                 start_s: float = 0.0) -> list:
    """engines.render_groove's format: stop name -> 16-char step string, 'x' a
    hit at 1.0, 'X' accented at 1.4, 'o' soft at 0.6, '.' a rest. Returns hits."""
    step = 60.0 / bpm / 4.0
    hits = []
    for rep in range(bars):
        for name, row in pattern.items():
            s = STOP_NAMES.index(name)
            for i, c in enumerate(row):
                if c == ".":
                    continue
                a = 1.4 if c == "X" else (0.6 if c == "o" else 1.0)
                t = start_s + (rep * 16 + i) * step + (swing * step if i % 2 else 0.0)
                hits.append((int(round(t * SR)), s, a))
    return hits
