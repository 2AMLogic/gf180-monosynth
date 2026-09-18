"""RTL-against-model tests. The ladder RTL must be bit-exact against
model/fixed.py, the modal RTL against model/modal_fixed.py, the whole voice
(voice_dp.v) against model/voice_fx.py and the drum section (drum_kit.v:
drum_dp.v + modal_dp.v) against model/drums_fx.py, and each bench must be
shown to fail on an injected defect -- and, for the voice, on an all-X stub.

Needs iverilog and vvp on PATH, or OSS_CAD_SUITE=/path/to/oss-cad-suite.
Without them the simulation tests SKIP -- a skip is not a pass; CI must treat
it as missing evidence.

    .venv/bin/python -m pytest rtl-sketch/ -q
"""
import os, sys
import pytest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify_ladder, verify_modal, verify_drums, verify_top, verify_voice, tanh_rom

needs_sim = pytest.mark.skipif(
    verify_ladder.tool("iverilog") is None or verify_ladder.tool("vvp") is None,
    reason="iverilog/vvp not found on PATH and OSS_CAD_SUITE not set")


def test_rom_images_are_the_models():
    """tanh16.hex / tanh256.hex must be exactly LadderFx.tbl plus 32767."""
    assert tanh_rom.main(["--check"]) == 0


@needs_sim
@pytest.mark.parametrize("entries", [16, 256])
def test_ladder_rtl_is_bit_exact(entries, tmp_path):
    """28,800 samples over five patches, every one identical to the model."""
    assert verify_ladder.main(["--tanh-n", str(entries), "--outdir", str(tmp_path)]) == 0


@needs_sim
@pytest.mark.parametrize("bug", ["FB", "SAT", "TANH_CLAMP"])
def test_negative_control_is_caught(bug, tmp_path):
    """A bench that cannot fail proves nothing. Each injected defect must
    produce a mismatch: status exactly 1, never 2 (which means it did not run)."""
    assert verify_ladder.main(["--tanh-n", "16", "--inject", bug,
                               "--outdir", str(tmp_path)]) == 1


@needs_sim
def test_modal_rtl_is_bit_exact(tmp_path):
    """The bar's six hits and rail-to-rail stress, the two numerators on
    noise and DC, and the coefficient extremes: every sample identical."""
    assert verify_modal.main(["--outdir", str(tmp_path)]) == 0


@needs_sim
@pytest.mark.parametrize("bug", ["SHIFT", "SAT", "PREEXC", "NUM_HOLD", "EXC_NOCLEAR"])
def test_modal_negative_control_is_caught(bug, tmp_path):
    assert verify_modal.main(["--inject", bug, "--outdir", str(tmp_path)]) == 1


@needs_sim
@pytest.mark.parametrize("nch", [2, 4])
def test_ladder_n_rtl_is_bit_exact_on_every_channel(nch, tmp_path):
    """ladder_dp_n (the voice's two filter contexts, ARCHITECTURE.md section 4):
    the same 28,800 samples driven to each channel in turn, every channel
    identical to the model, 19-bit output. The committed tb_ladder_n.v read
    120-bit words from the 128-bit vector file and could not pass; fixed."""
    assert verify_ladder.main(["--nch", str(nch), "--outdir", str(tmp_path)]) == 0


@needs_sim
def test_top_level_schedule_link_and_i2s(tmp_path):
    """synth_top through its pins: the status word reads back, the datapath is
    idle at every tick, the I2S stream decodes to the sample stream with D = 1,
    and the chip makes sound from the model's own register conversions."""
    assert verify_top.main(["--outdir", str(tmp_path), "--frames", "800"]) == 0


@needs_sim
def test_voice_rtl_is_bit_exact(tmp_path):
    """voice_dp against model/voice_fx.py at the register port: every
    scenario of verify_voice.py (every waveform; every note and the
    increments where 5.5's clamps fire; glide up, down and at its limits;
    gate / trig / retrigger; a release to exactly zero; paraphonic keys; the
    register extremes) in the quick set, every sample, every tap of 16.4 and
    the final state identical. The full set (--set full, ~175k frames, with
    the audition reference sequences) is the documented command."""
    assert verify_voice.main(["--set", "quick", "--outdir", str(tmp_path)]) == 0


# each injected defect and the scenarios that reach the thing it breaks
VOICE_BUGS = [("SQUARE_SIGN", "default"),          # the square takes the saw's sign at the wrap
              ("ENV_FLOOR",   "silence"),          # release without max(1, .): the note never ends
              ("KEFF",        "default"),          # no resonance compensation: k_eff = k
              ("MIX_SAT",     "extremes"),         # the mixer wraps
              ("GLIDE_FLOOR", "notes"),            # slew without max(1, .): a small inc never moves
              ("RECIP_CLAMP", "notes"),            # a power-of-two inc gets r = 0
              ("TRIG_RESET",  "gate"),             # GATE_ON / TRIG reset the level to zero
              ("OUT_SAT",     "extremes")]         # no rail at the master mix


@needs_sim
def test_voice_bench_fails_on_a_stub(tmp_path):
    """The red run of docs/verification-rules.md: voice_dp's ports with no
    behaviour and every output X must give status exactly 1 -- a mismatch,
    with the frames reported as undefined -- never a pass and never 2."""
    assert verify_voice.main(["--set", "quick", "--only", "default", "--outdir", str(tmp_path),
                              "--rtl", os.path.join(HERE, "stubs", "voice_dp_stub.v")]) == 1


@needs_sim
@pytest.mark.parametrize("bug,only", VOICE_BUGS)
def test_voice_negative_control_is_caught(bug, only, tmp_path):
    """A bench that cannot fail proves nothing. Each injected defect must
    produce a mismatch on the scenario that reaches it: status exactly 1,
    never 2 (which means it did not run)."""
    assert verify_voice.main(["--set", "quick", "--only", only, "--inject", bug, "--outdir", str(tmp_path)]) == 1


@needs_sim
def test_drum_section_rtl_is_bit_exact(tmp_path):
    """The short stimulus (every stop soloed, edge semantics, all eight at
    accent 2.0, a bar with the choke and a BD retune, register extremes on
    the last paths and the spare mode, a RESET, decay to silence): both
    buses identical to the model on every frame. verify_drums.py without
    --short is the full-length run of the same stream."""
    assert verify_drums.main(["--short", "--outdir", str(tmp_path)]) == 0


@needs_sim
@pytest.mark.parametrize("bug", ["DRUM_ENV_FLOOR", "DRUM_LEVEL_TRIG", "DRUM_LFSR_TAP", "DRUM_TAP_NOSAT",
                                 "DRUM_LAST_PATH", "MODAL_NUM_HOLD", "MODAL_EXC_NOCLEAR"])
def test_drum_negative_control_is_caught(bug, tmp_path):
    """Each defect -- the envelope without its max(1, .), level- instead of
    edge-triggered stops, a wrong LFSR tap, a wrapping tap, the strawman's
    dropped last drum, a numerator with no history, an excitation register
    that is not consumed -- must produce a mismatch: status exactly 1."""
    assert verify_drums.main(["--short", "--inject", bug, "--outdir", str(tmp_path)]) == 1


@needs_sim
def test_drum_timing_contract_is_load_bearing(tmp_path):
    """The control buses must be held from the tick to body_valid (15.6).
    Applying a frame's writes 20 clocks into the frame instead must be seen
    by the comparison: status exactly 1."""
    assert verify_drums.main(["--short", "--jitter", "20", "--outdir", str(tmp_path)]) == 1
