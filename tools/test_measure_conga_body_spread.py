"""Controls for the recovered conga instrument, including its false-green CLI."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import measure_conga_body_spread as probe


def test_known_answer_control_checks_two_tones_without_our_model():
    rows = probe.validate_known_answer()
    assert len(rows) == 8
    assert max(abs(row["error_db"]) for row in rows) < 0.1


def test_check_refuses_an_empty_existing_reference_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe", "--check", "--refs", str(tmp_path)])
    assert probe.main() == 2


def test_check_fails_an_injected_band_direction_error(tmp_path, monkeypatch):
    real = probe.am.band_energy
    monkeypatch.setattr(probe.am, "band_energy", lambda *a, **kw: real(*a, **kw)[::-1])
    monkeypatch.setattr(sys, "argv", ["probe", "--check", "--refs", str(tmp_path)])
    assert probe.main() == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.0])
def test_check_fails_invalid_or_drifted_historical_reproduction(value):
    report = {"known_answer": probe.validate_known_answer(),
              "reproduction": [{"delta_db": 0.0}, {"delta_db": value}]}
    assert probe.validation_status(report) == 1


def test_check_passes_qualified_controls():
    report = {"known_answer": probe.validate_known_answer(),
              "reproduction": [{"delta_db": 0.0}, {"delta_db": 0.0}]}
    assert probe.validation_status(report) == 0
