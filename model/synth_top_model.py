"""Fixed-point model of the WHOLE CHIP at its top-level boundary --
rtl-sketch/synth_top.v's specification, the way model/voice_fx.py is
voice_dp.v's and model/fixed.py is the ladder's.

Every block in this design is bit-exact against a model of that block. None of
that says anything about what happens BETWEEN the blocks, and both integration
defects found so far (a drum mix bug and a gating bug) were found by listening,
not by a test. This model closes that: register writes in, one 16-bit sample
per frame out, and the I2S word stream that carries them.

WHAT IT MODELS, in the order synth_top.v runs it (ARCHITECTURE.md section 5):

  1. the register port. Writes reach the datapath in the drain at cycles 2..5,
     before `go` at cycle 8, so at frame granularity a write is atomic and
     lands at the START of its frame. Which frame that is, is the link's
     business (verify_synth_top.py derives it from the CS_N pin event and the
     documented 3-cycle synchroniser latency, and checks the chip agrees).
  2. the drum sources of drum_section_placeholder: a trigger edge reloads a
     16-bit envelope, an LFSR signs it, and that is the frame's excitation.
  3. the modal bank (model/modal_fixed.py, ModalFx) on the preset's note.
     ONE excitation for the whole 15-cycle pass -- the hazard of
     ARCHITECTURE.md 4.4, which rtl-sketch/verify_modal_exc.py verifies.
  4. the voice (model/voice_fx.py, VoiceFx) -- oscillators, mixer, envelopes,
     cutoff, ladder context 0, VCA, volume -- taken UNSATURATED at out_v.
     This is a real difference from the voice alone: VoiceFx.play() returns
     sat16((v*vol)>>15) because the voice's own output is the chip's output
     when there is nothing else on the bus, but in the chip out_v is a 20-bit
     word that meets the drum bus BEFORE the rail (ARCHITECTURE.md 4.3).
  5. the drum path: bypass, or ROUTE.DFILT through ladder context 1 on
     sat16(drum_bus) with its own DCUT/DK/DGAIN/DOGAIN -- and DCUT through the
     same g and kc ROMs the voice uses.
  6. the master mix: sat16(out_v + ((d19*dvol) >> 15)). ONE rail, at 20/21
     bits, sum THEN clamp. Clamping either bus to 16 bits first is a different
     circuit and a different sound; that ordering is what this model pins.
  7. the I2S stream: the sample strobed in frame f is transmitted in LRCLK
     period f+1 (contract 13, D = 1) on both channels.

Register map: DR 0007 section 3 plus the chip-level additions of
ARCHITECTURE.md section 9.
"""
from __future__ import annotations
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "audition"))
import numpy as np
import voice_fx as vf
import fixed
from fixed import LadderFx
from modal_fixed import ModalFx

# ---- the register map (DR 0007 section 3, ARCHITECTURE.md section 9) ----------
A = dict(INC=0x00, WAVE=0x04, W=0x08, GLIDE=0x0C, VOL=0x0D, DVOL=0x0E, ROUTE=0x0F,
         AMP=0x10, FILT=0x14, CUT_LO=0x18, CUT_HI=0x19, TRACK=0x1A,
         K=0x1C, GAIN=0x1D, OGAIN=0x1E,
         GATE_ON=0x20, GATE_OFF=0x21, TRIG=0x22, RESET=0x23,
         DCUT=0x28, DK=0x29, DGAIN=0x2A, DOGAIN=0x2B, NOP=0x3F,
         DRUM_TRIG=0x40, MODAL_PRESET=0x41)
WAVE_NAME = {0: "saw", 1: "square", 2: "pulse25", 3: "tri", 4: "sine"}
PRESET_NOTES = [28, 40, 52, 64, 76, 88, 100, 112]      # gen_modal_rom.py's P = 8 table
CUT_MIN, CUT_MAX = 30, 21600                           # contract 10
K_BITS = 17


def sat(v: int, bits: int) -> int:
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return lo if v < lo else (hi if v > hi else v)


class SynthTopModel:
    """One chip. `run(writes, n)` plays n frames with `writes` applied at the
    start of the frames they name, and returns every signal the bench can see."""

    def __init__(self):
        self.v = vf.VoiceFx()
        self.reset()

    # ---- RESET (0x23) and the reset pin: contract 14 -------------------------
    def reset(self):
        self.v.reset()
        # voice_dp's control image, all zero out of reset
        self.waves = ["saw", "saw", "saw"]
        self.weights = [0, 0, 0]
        self.amp = [0, 0, 0, 0]
        self.fenv = [0, 0, 0, 0]
        self.cut_lo = self.cut_hi = self.track_hz = 0
        self.k = self.gain = self.ogain = 0
        self.vol = self.dvol = 0
        self.dfilt = 0
        self.dcut = self.dk = self.dgain = self.dogain = 0
        self.glide = 0
        self.gate = 0
        # drum_section_placeholder
        self.trig = self.trig_q = 0
        self.env = 0
        self.lfsr = 0xACE1
        self.preset = 0
        self.bank = ModalFx()
        # ladder context 1, the drum filter (a second state set, same arithmetic)
        self.dl = LadderFx(state_bits=24, state_q=20, tanh_entries=16, interp=True, out_bits=19)
        self._coefs = self.bank.coefficients(PRESET_NOTES[0])
        self.d19_reg = 0                    # voice_dp's d19: held while DFILT is off

    # ---- one register write, exactly voice_dp.v's / the placeholder's port ----
    def write(self, flag: int, addr: int, data: int) -> bool:
        """Returns True if this write was RESET (the caller must re-apply any
        writes that follow it in the same frame; the RTL's soft reset is a
        combinational gate on rst_n, so it wipes state and then later writes of
        the same drain land on the zeroed image)."""
        addr &= 0x7F; data &= 0xFFFFFF
        if addr <= 0x02:
            k = addr & 3
            self.v.oscs[k].set_inc(data, bool(flag), self.glide)
        elif 0x04 <= addr <= 0x06:
            self.waves[addr - 0x04] = WAVE_NAME.get(data & 7, "sine")
            self.v.oscs[addr - 0x04].set_shape(self.waves[addr - 0x04], self.v.blep)
        elif 0x08 <= addr <= 0x0A: self.weights[addr - 0x08] = data & 0xFFFF
        elif addr == 0x0C: self.glide = data
        elif addr == 0x0D: self.vol = data & 0xFFFF
        elif addr == 0x0E: self.dvol = data & 0xFFFF
        elif addr == 0x0F: self.dfilt = data & 1
        elif 0x10 <= addr <= 0x13: self.amp[addr - 0x10] = data & (0xFFFF if addr == 0x13 else 0xFFFFFF)
        elif 0x14 <= addr <= 0x17: self.fenv[addr - 0x14] = data & (0xFFFF if addr == 0x17 else 0xFFFFFF)
        elif addr == 0x18: self.cut_lo = data & 0xFFFF
        elif addr == 0x19: self.cut_hi = data & 0xFFFF
        elif addr == 0x1A: self.track_hz = data & 0xFFFF
        elif addr == 0x1C: self.k = data & 0x1FFFF
        elif addr == 0x1D: self.gain = data & 0xFFFFF
        elif addr == 0x1E: self.ogain = data & 0xFFFFF
        elif addr == 0x20: self.gate = 1                      # GATE_ON: seg -> attack, level kept
        elif addr == 0x21: self.gate = 0                      # GATE_OFF
        elif addr == 0x22: pass                               # TRIG: seg -> attack, level kept
        elif addr == 0x23: self.reset(); return True          # RESET
        elif addr == 0x28: self.dcut = data & 0xFFFF
        elif addr == 0x29: self.dk = data & 0x1FFFF
        elif addr == 0x2A: self.dgain = data & 0xFFFFF
        elif addr == 0x2B: self.dogain = data & 0xFFFFF
        elif addr == 0x40: self.trig = data & 0xFF
        elif addr == 0x41: self.preset = data & 7; self._coefs = self.bank.coefficients(PRESET_NOTES[self.preset])
        return False

    # ---- the drum sources of drum_section_placeholder, one frame -------------
    def drum_source_frame(self) -> int:
        fire = (self.trig & ~self.trig_q) != 0
        self.trig_q = self.trig
        self.env = 0x7FFF if fire else (self.env - (self.env >> 3)) & 0xFFFF
        bit = ((self.lfsr >> 15) ^ (self.lfsr >> 13) ^ (self.lfsr >> 12) ^ (self.lfsr >> 10)) & 1
        self.lfsr = ((self.lfsr << 1) | bit) & 0xFFFF
        return self.env if (self.lfsr & 1) else -self.env     # exc, Q1.15

    # ---- the chip ------------------------------------------------------------
    def run(self, writes, n: int) -> dict:
        """writes: iterable of (frame, flag, addr, data), applied in list order
        at the start of their frame. Returns arrays of length n plus the I2S
        word stream (length n; word[f] is what LRCLK period f carries)."""
        ev = {}
        for f, flag, addr, data in writes:
            assert 0 <= f < n, f"write at frame {f} outside 0..{n-1}"
            ev.setdefault(int(f), []).append((int(flag), int(addr), int(data)))
        bounds = sorted(set([0, n] + [f for f in ev if 0 < f < n]))
        sample = np.zeros(n, dtype=np.int64)
        out_v = np.zeros(n, dtype=np.int64)
        out_d = np.zeros(n, dtype=np.int64)
        d19a = np.zeros(n, dtype=np.int64)
        drum = np.zeros(n, dtype=np.int64)
        mixed = np.zeros(n, dtype=np.int64)
        y19 = np.zeros(n, dtype=np.int64)
        aea = np.zeros(n, dtype=np.int64); fea = np.zeros(n, dtype=np.int64)
        cuta = np.zeros(n, dtype=np.int64); keffa = np.zeros(n, dtype=np.int64)
        for f0, f1 in zip(bounds, bounds[1:]):
            trig_arr = np.zeros(f1 - f0, dtype=np.int64)
            for flag, addr, data in ev.get(f0, []):
                if addr in (A["GATE_ON"], A["TRIG"]):
                    trig_arr[0] = 1                       # restart both envelope segments
                self.write(flag, addr, data)
            m = f1 - f0
            # --- 2, 3: drum sources then the bodies, this frame's strike ------
            exc = np.array([self.drum_source_frame() for _ in range(m)], dtype=np.int16)
            d16 = self.bank.process(exc, self._coefs).astype(np.int64)
            drum[f0:f1] = d16                              # sign-extended to 19 bits: same value
            # --- 4: the voice, out_v UNSATURATED -----------------------------
            incs = [o.slew(m, self.glide) for o in self.v.oscs]
            self.v.weights = list(self.weights)
            self.v.amp_env.set_regs(*self.amp); self.v.filt_env.set_regs(*self.fenv)
            self.v.cut_lo, self.v.cut_hi = self.cut_lo, self.cut_hi
            self.v.k_reg, self.v.gain, self.v.ogain = self.k, self.gain, self.ogain
            self.v.vol = self.vol
            self.v.res = self.v.drive = 0.0        # unused: k, gain, ogain are the registers
            track = np.full(m, self.track_hz, dtype=np.int64)
            gate = np.full(m, self.gate, dtype=np.int64)
            self.v._render(incs, track, gate, trig_arr, m)
            t = self.v.trace
            ov = (t["vca"].astype(np.int64) * self.vol) >> 15
            out_v[f0:f1] = ov
            mixed[f0:f1] = t["mixed"]; y19[f0:f1] = t["ladder"]
            aea[f0:f1] = t["amp_env"]; fea[f0:f1] = t["filt_env"]
            cuta[f0:f1] = t["cut"]; keffa[f0:f1] = t["k_eff"]
            # --- 5: the drum path --------------------------------------------
            # d19 is a REGISTER in voice_dp: ladder context 1 runs only while
            # ROUTE.DFILT is set, so with the filter off d19 holds whatever it
            # last produced (0 from reset) and the master mix takes the raw
            # drum bus instead. That is state that survives a routing change.
            if self.dfilt:
                x = np.array([sat(int(d), 16) for d in d16], dtype=np.int16)   # sat16(drum_bus)
                dc = min(max(self.dcut, CUT_MIN), CUT_MAX)
                g2 = int(vf.g_from_cut(np.array([dc]), self.v.g_rom, self.v.GB)[0])
                kc2 = int(vf.kc_from_cut(np.array([dc]), self.v.k_rom, self.v.KB)[0])
                ke2 = int(vf.k_effective(self.dk, kc2))
                d19 = self.dl.process(x, None, 0.0, 0.0,
                                      g_q16=np.full(m, g2, dtype=np.int64),
                                      k=self.dk, gain=self.dgain, ogain=self.dogain,
                                      k_q14=np.full(m, ke2, dtype=np.int64)).astype(np.int64)
                self.d19_reg = int(d19[-1])
            else:
                d19 = np.full(m, self.d19_reg, dtype=np.int64)     # held, not driven
            d19a[f0:f1] = d19
            # --- 6: the master mix, ONE rail, sum then clamp ------------------
            bus = d19 if self.dfilt else d16                       # DFILT selects which reaches the mix
            od = (bus * self.dvol) >> 15
            out_d[f0:f1] = od
            sample[f0:f1] = np.array([sat(int(a) + int(b), 16) for a, b in zip(ov, od)], dtype=np.int64)
        # --- 7: I2S, D = 1, the same word on both channels --------------------
        i2s = np.concatenate([[0], sample[:-1]]).astype(np.int64)
        return dict(sample=sample, i2s=i2s, out_v=out_v, out_d=out_d, drum_bus=drum, d19=d19a,
                    mixed=mixed, y19=y19, ae=aea, fe=fea, cut=cuta, k_eff=keffa)
