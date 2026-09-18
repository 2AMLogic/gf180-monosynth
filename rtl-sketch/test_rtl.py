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
import verify_ctl, verify_synth_top

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
                                 "DRUM_LAST_PATH", "DRUM_SQ_LONE", "MODAL_NUM_HOLD", "MODAL_EXC_NOCLEAR"])
def test_drum_negative_control_is_caught(bug, tmp_path):
    """Each defect -- the envelope without its max(1, .), level- instead of
    edge-triggered stops, a wrong LFSR tap, a wrapping tap, the strawman's
    dropped last drum, a lone-square source that returns the PAIR (rev 5's
    cowbell defect, the one that made a 260 Hz difference tone), a numerator
    with no history, an excitation register that is not consumed -- must
    produce a mismatch: status exactly 1."""
    assert verify_drums.main(["--short", "--inject", bug, "--outdir", str(tmp_path)]) == 1


@needs_sim
def test_drum_timing_contract_is_load_bearing(tmp_path):
    """The control buses must be held from the tick to body_valid (15.6).
    Applying a frame's writes 20 clocks into the frame instead must be seen
    by the comparison: status exactly 1."""
    assert verify_drums.main(["--short", "--jitter", "20", "--outdir", str(tmp_path)]) == 1


# ---- the control link: can it CARRY what the models write? ------------------

@needs_sim
def test_control_link_carries_both_models_register_images(tmp_path):
    """Every bench above drives the register WRITE PORT. This one drives the
    PINS and compares what reaches the port against what the host INTENDED --
    155 writes: the voice's patch image from model/voice_fx.py's own
    conversion, the reference kit from model/drums_fx.py's kit_808(), and
    every drum register class at its full width. Status exactly 0."""
    assert verify_ctl.main(["--outdir", str(tmp_path)]) == 0


@needs_sim
def test_dr7_revision1_frame_could_not_carry_the_drum_image(tmp_path):
    """THE DEFECT THIS BENCH EXISTS FOR, kept runnable. DR 0007 revision 1's
    32-bit frame -- 7-bit address, 24-bit datum, no page bit -- corrupts 118
    of those 155 writes: 118 have no drum page to land in, 67 addresses do not
    fit in 7 bits (A_PATH 0x80, A_MODE 0xC0, A_RESET 0xFF) and 26 data do not
    fit in 24 (ENV_CTL is 27 bits, MODE_A1/A2 are 26). Status exactly 1."""
    assert verify_ctl.main(["--link", "dr7rev1", "--outdir", str(tmp_path)]) == 1


@needs_sim
@pytest.mark.parametrize("bug", ["SPI_ADDR7", "SPI_DATA24", "SPI_NOSEC", "SPI_ANYLEN", "SPI_DRAIN_LATE"])
def test_control_link_negative_control_is_caught(bug, tmp_path):
    """Revision 1's address field, revision 1's data field, no page bit, a
    mis-sized transaction applied instead of discarded, and a drain that runs
    at `go` instead of before it -- each must produce a mismatch."""
    assert verify_ctl.main(["--inject", bug, "--outdir", str(tmp_path)]) == 1


# ---- the whole chip at its pins, against the model -------------------------

@needs_sim
def test_chip_is_bit_exact_at_its_pins(tmp_path):
    """synth_top through SCK/MOSI/CS_N in and BCLK/LRCLK/SDATA out: the voice
    image and the reference drum kit are written over the link, notes are
    played, drums are struck, a body is retuned while it rings, ROUTE.DFILT is
    engaged and released mid-ring, and every I2S word decoded from the WIRE is
    compared against model/synth_top_model.py. Not against dut.sample: that
    comparison is circular and is what tb_synth_top.v does."""
    assert verify_synth_top.main(["--short", "--outdir", str(tmp_path)]) == 0


@needs_sim
@pytest.mark.parametrize("bug", ["VOICE_MASTER_PRESHIFT", "VOICE_DRUM_CLAMP16", "VOICE_OUT_SAT",
                                 "I2S_SHIFT", "I2S_SWAP", "I2S_DELAY",
                                 "MODAL_NUM_HOLD", "MODAL_EXC_NOCLEAR", "DRUM_LFSR_TAP"])
def test_chip_negative_control_is_caught(bug, tmp_path):
    """Each product shifted before the sum instead of contract 12's single
    shift; the drum buses clipped to 16 bits before their gains; no rail; the
    wire one bit late; the channels swapped; the sample a period late -- and
    three defects inside the drum engine, to show the chip-level bench sees
    through to them. Status exactly 1."""
    assert verify_synth_top.main(["--short", "--inject", bug, "--outdir", str(tmp_path)]) == 1


@needs_sim
def test_chip_reaches_the_envelope_dead_zone(tmp_path):
    """DRUM_ENV_FLOOR needs the full-length stimulus, because the short one
    never drives an envelope into the dead zone and the control went UNCAUGHT
    until the stimulus was changed to strike the open hat from just above its
    freeze level. Recorded as a test so the hole cannot come back."""
    assert verify_synth_top.main(["--inject", "DRUM_ENV_FLOOR", "--outdir", str(tmp_path)]) == 1


@needs_sim
@pytest.mark.parametrize("legacy", [False, True])
def test_ladder_channel_bleed_is_caught_by_either_stimulus(legacy, tmp_path):
    """INJECT_BUG_LADDER_CH_BLEED shares the half-sample delay line across
    channels. Both the row-per-channel stimulus and the old every-row-to-every-
    channel one catch it -- measured, and it corrects the claim that the old
    stimulus was blind to cross-channel bleeding. What the old one really could
    not do is run the two contexts on DIFFERENT signals and coefficients, which
    is what the chip does (the drum filter has its own DCUT/DK/DGAIN/DOGAIN)."""
    args = ["--nch", "2", "--inject", "CH_BLEED", "--outdir", str(tmp_path)]
    if legacy:
        args.append("--legacy-stimulus")
    assert verify_ladder.main(args) == 1
