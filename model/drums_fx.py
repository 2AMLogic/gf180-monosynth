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
                each), TAP m = sat16(y1[m] >> 3), the mode's state / 8
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
SRC_OFF, SRC_NOISE, SRC_SQSUM, SRC_PULSE, SRC_SQPAIR, SRC_TAP = 0, 1, 2, 3, 4, 16
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
        sqpair = sum(SQPAIR_STEP if self.phase[i] < (1 << (PHASE_BITS - 1)) else -SQPAIR_STEP
                     for i in SQPAIR)
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
        int32 arrays; `self.trace` holds the per-frame internals."""
        ev = {}
        for f, a, v in writes:
            f = int(f)
            assert 0 <= f < n, f"write ({f}, {a:#x}, {v}) outside 0..{n-1}"
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
M_HATBP, M_OHHP, M_CHHP, M_SDHP, M_CPBP, M_CBBP, M_BD, M_SDLO, M_SDHI, M_LT, M_HT, M_SPARE = range(12)
# Envelopes.
E_BDX, E_BDCLICK, E_SDX, E_SDN, E_LTX, E_HTX, E_CH, E_OH, E_CPBURST, E_CPTAIL, E_CBA, E_CBB = range(12)
OSC_HZ = (205.3, 369.6, 304.4, 522.7, 800.0, 540.0)   # the HD14584 bank, reference 1.5
FRAME = 1.0 / SR


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
    w += mode_writes(M_SDHP, 2750.0, 0.7, 0.34, HP)           # SD snappy high-pass, reference 3
    w += mode_writes(M_CPBP, 1071.0, 1.6, 0.0, BP)           # CP band-pass, reference 7; tapped only
    w += mode_writes(M_CBBP, 900.0, 4.0, 0.0224, BP)            # CB band-pass: 0.9 kHz Q 4 CHOSEN (reference 9, 18)
    w += mode_writes(M_BD, 56.0, 22.3, 0.00286, RAW)          # BD, decay mid, reference 2 / 14
    w += mode_writes(M_SDLO, 173.0, 16.3, 0.004, RAW)        # SD low, later units, reference 3
    w += mode_writes(M_SDHI, 336.0, 9.9, 0.0041, RAW)         # SD high; TONE = this pair's ratio
    w += mode_writes(M_LT, 90.0, 25.0, 0.0046, RAW)          # LT, reference 4
    w += mode_writes(M_HT, 185.0, 25.0, 0.0094, RAW)         # HT, reference 4
    # envelopes: the pulse-shaper's kick is a 0.1 ms exponential (reference 2, "what to implement");
    # the bodies' exciters are 0.25 so that an accent of 2.0 keeps the BD's state (the bank's
    # loudest ring, ~720 x the kick) under a quarter of the 28-bit rail
    w += env_writes(E_BDX, BD, 0.1e-3, 0.25)
    w += env_writes(E_BDCLICK, BD, 0.0, 0.06, hold=48)       # the 1 ms pulse leaking through, reference 2
    w += env_writes(E_SDX, SD, 0.1e-3, 0.25)
    w += env_writes(E_SDN, SD, 15e-3, 0.5)                   # SNAPPY = this peak, reference 3
    w += env_writes(E_LTX, LT, 0.1e-3, 0.25)
    w += env_writes(E_HTX, HT, 0.1e-3, 0.25)
    w += env_writes(E_CH, CH, 20e-3, 1.0)                    # reference 11
    w += env_writes(E_OH, OH, 150e-3, 1.0, choke=CH)         # DECAY knob mid; CH chokes it, reference 11
    w += env_writes(E_CPBURST, CP, 4e-3, 0.69, bursts=2, period=480)  # three bursts 10 ms apart, reference 7
    w += env_writes(E_CPTAIL, CP, 47e-3, 0.22)               # the tail at -10 dB, reference 7 (chosen ratio)
    w += env_writes(E_CBA, CB, 5e-3, 0.5)                    # two-slope envelope, reference 9
    w += env_writes(E_CBB, CB, 30e-3, 0.5)
    # paths
    paths = [
        path_word(SRC_PULSE, E_BDX, dest=M_BD),
        path_word(SRC_PULSE, E_BDCLICK, dest=DEST_MIX),
        path_word(SRC_PULSE, E_SDX, dest=M_SDLO),
        path_word(SRC_PULSE, E_SDX, dest=M_SDHI),              # both from the pulse (reference 3: cascade is subtle)
        path_word(SRC_NOISE, E_SDN, dest=M_SDHP),
        path_word(SRC_PULSE, E_LTX, dest=M_LT),
        path_word(SRC_PULSE, E_HTX, dest=M_HT),
        path_word(SRC_SQSUM, ENV_FULL, dest=M_HATBP),          # the six squares, always on, into the band-pass
        path_word(SRC_TAP + M_HATBP, E_CH, nl=NL_SWING, dest=M_CHHP),
        path_word(SRC_TAP + M_HATBP, E_OH, nl=NL_SWING, dest=M_OHHP),
        path_word(SRC_NOISE, ENV_FULL, dest=M_CPBP),           # noise, always on, into the clap band-pass
        path_word(SRC_TAP + M_CPBP, E_CPBURST, E_CPTAIL, nl=NL_TANH, dest=DEST_MIX),
        path_word(SRC_SQPAIR, E_CBA, E_CBB, nl=NL_SWING, dest=M_CBBP),
    ]
    for p, word in enumerate(paths):
        w.append((A_PATH + p, word))
    return w


# ---- the reference host (informative): hits and patterns to writes ------------------
def hit_writes(hits, kit: list = None, start_frame: int = 0) -> list:
    """hits: (frame, stop, accent 0..2.0). Each hit writes its stop's accent
    and raises the stop bit in that frame; the bit is dropped in the next
    frame so the next hit is an edge again. Two hits of one stop in
    consecutive frames cannot both fire (no 0->1 between them) -- a host
    leaves a frame between hits, as a slice-based host does by construction."""
    w = [(start_frame, a, v) for a, v in (kit or [])]
    by_frame = {}
    for f, s, a in hits:
        by_frame.setdefault(int(f), []).append((int(s), float(a)))
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
