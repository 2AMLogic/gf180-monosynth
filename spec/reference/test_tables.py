"""The contract's tables are the model's, and the hashes the contract states
are the ones the revisions were written with: revision 1's five, unchanged
through revisions 2, 3 and 4; K_ROM32 from DR 0006 (revision 3); NOISE64 and
KIT808 from DR 0007 (revision 4).

    .venv/bin/python -m pytest spec/reference -q

The literal hashes below are deliberately duplicated from the contract: if
the model's tables change, BOTH this test and `gen_tables.py --check` fail,
and the right response is a revision bump, not an update of the literals.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_tables as gt

REV3 = {
    "NOTE_INC":      "e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4",
    "SINE_Q256":     "66cfc2e50e0ea6c326d698bd2aa14cc8b67f8e518530c9bb9c3f8f62d0fd19a0",
    "SINE_FULL1024": "41a30c959df1413245a6817c2d398c9d571f33460b34634b433c0717fb3c52ea",
    "TANH16":        "65a5fa4b38b807735e09eed0eadd49b2a42850151daa47e3abb97a1641542c04",
    "TANH16_ROM":    "3aa73628ec4f1b6eec99e77524a5460813c531dd9703a8fdea6df799dc91efeb",
    "G_ROM128":      "c5ee86efeffbe3cadd040ca3851b5c90806f05f9fab13d5f3cea1cf7730fbe2a",
    "K_ROM32":       "514d0ba224df47ab47e4c6b5454666b88568f3172bacdc2e17baba3c5b6c6e1a",
}
REV4 = {
    "NOISE64":       "41f2adb399b60f0d7f1d77a03bf004d9b2ec28ab220f476cfafe96c36f99a613",
    "KIT808":        "819ef081eca2aaff17c8f63d9653ee8d62dc69a6f6e48b08082161b8db66b3dc",
}


def test_committed_images_and_contract_match_the_model():
    """Every hex image, the appendix block, rtl-sketch/tanh16.hex and every
    stated hash must be exactly what the model generates now."""
    assert gt.main(["--check"]) == 0


def test_rev3_hashes_are_unchanged_and_rev4_adds_two():
    """Revision 4 added NOISE64 and KIT808 and changed no existing table."""
    got = {name: gt.sha(vals) for name, vals, _, _, _ in gt.tables()}
    assert {k: got[k] for k in REV3} == REV3
    assert {k: got[k] for k in REV4} == REV4
    assert set(got) == set(REV3) | set(REV4)


def test_spot_values_the_contract_quotes():
    ni = gt.note_inc()
    assert (ni[0], ni[69], ni[127]) == (2858, 153791, 4384395)
    assert max(ni) < (1 << 23)
    sq = gt.sine_q256()
    assert len(sq) == 256 and sq[0] == 101 and sq[255] == 32767
    th = gt.tanh16()
    assert len(th) == 16 and th[0] == 0 and th[1] == 8025 and th[15] == 32731
    assert gt.tanh16_rom()[16] == 32767
    gr = gt.g_rom128()
    assert len(gr) == 129 and gr[0] == 0 and gr[1] == 1089 and gr[128] == 57861
    assert all(b > a for a, b in zip(gr, gr[1:]))          # strictly increasing
    kr = gt.k_rom32()
    assert len(kr) == 33 and kr[0] == 32799 and max(kr) == 39879 and kr[22] == 33964
    nz = gt.noise64()
    assert len(nz) == 64 and nz[0] == 1 and all(-32768 <= v <= 32767 for v in nz)
    kit = gt.kit808()
    assert len(kit) == 99 and all(0 <= a < 256 and 0 <= v < (1 << 32) for a, v in kit)
    assert kit[0] == (0x20, 71758)                           # OSC_INC[0]: 205.3 Hz


def test_note_inc_is_the_siblings():
    """Same formula, same 128 values as gf180-polysynth's Appendix A."""
    assert gt.sha(gt.note_inc()) == "e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4"
