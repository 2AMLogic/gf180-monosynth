"""RTL-against-model tests. The ladder RTL must be bit-exact against
model/fixed.py, the modal RTL against model/modal_fixed.py and the drum
section (drum_kit.v: drum_dp.v + modal_dp.v) against model/drums_fx.py, and
each bench must be shown to fail on an injected defect.

Needs iverilog and vvp on PATH, or OSS_CAD_SUITE=/path/to/oss-cad-suite.
Without them the simulation tests SKIP -- a skip is not a pass; CI must treat
it as missing evidence.

    .venv/bin/python -m pytest rtl-sketch/ -q
"""
import os, sys
import pytest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify_ladder, verify_modal, verify_drums, tanh_rom

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
