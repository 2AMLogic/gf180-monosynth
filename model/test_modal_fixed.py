#!/usr/bin/env python3
"""Regression tests for the proposed fixed-point modal bank. They lock the
sizing the RTL was written to, and the finding that sized it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest
import modal_fixed
from modal_fixed import ModalFx, pole_error, snr_db


@pytest.mark.parametrize("note", [28, 52, 88])
def test_tracks_the_float_bank(note):
    """Q2.24 coefficients, 28-bit state: within 40 dB of the float on a hit."""
    assert snr_db(note, ModalFx()) > 40.0


def test_q2_16_coefficients_cannot_tune_a_low_bar():
    """The earlier sketch's 18-bit coefficient ports. Locked so the reason the
    RTL grew a 26-bit coefficient path is not lost: at note 28 the pole is
    2.4 % off pitch and the output is not an approximation of the float."""
    df, dd = pole_error(28, 16)
    assert abs(df) > 1.0
    assert snr_db(28, ModalFx(coef_frac=16)) < 10.0


def test_q2_24_pitch_and_decay_at_the_lowest_note():
    df, dd = pole_error(28, 24)
    assert abs(df) < 0.01 and abs(dd) < 0.1


def test_rounding_buys_nothing():
    """Measured, and why the datapath carries no rounding constant."""
    assert abs(snr_db(28, ModalFx(rounding=True)) - snr_db(28, ModalFx(rounding=False))) < 1.0
