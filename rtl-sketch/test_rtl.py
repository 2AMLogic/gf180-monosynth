"""RTL-against-model tests. The ladder RTL must be bit-exact against
model/fixed.py and the modal RTL against model/modal_fixed.py, and each
bench must be shown to fail on an injected defect.

Needs iverilog and vvp on PATH, or OSS_CAD_SUITE=/path/to/oss-cad-suite.
Without them the simulation tests SKIP -- a skip is not a pass; CI must treat
it as missing evidence.

    .venv/bin/python -m pytest rtl-sketch/ -q
"""
import os, sys
import pytest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify_ladder, verify_modal, tanh_rom, verify_top, verify_voice

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
    """Six hits and a rail-to-rail stress, every sample identical to the model."""
    assert verify_modal.main(["--outdir", str(tmp_path)]) == 0


@needs_sim
@pytest.mark.parametrize("bug", ["SHIFT", "SAT", "PREEXC"])
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
    """voice_dp against model/voice_fx.py at the register port: three
    scenarios (a note from reset; every waveform with glide, high resonance
    and drive; a paraphonic multi-trigger phrase), every sample identical."""
    assert verify_voice.main(["--outdir", str(tmp_path)]) == 0
