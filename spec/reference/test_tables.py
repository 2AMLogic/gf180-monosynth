"""The contract's tables are the model's, and the hashes the contract states
are the ones the revisions were written with: revision 1's five, unchanged
through revisions 2, 3 and 4 (4 changed no arithmetic); K_ROM32 from DR 0006
(revision 3); NOISE64 from DR 0008 (revision 5), which KIT808 joined in the
same revision and then LEFT in revision 6 -- the kit was fitted to a real
TR-808 (DR 0009, DR 0010) and its hash moved. It is the first pinned table in
this contract's history to change, and the pair below is how that is visible
rather than quiet: REV5 holds what rev 5 stated, REV6 what rev 6 states, and
`test_the_only_hash_that_ever_moved_is_the_kits` asserts exactly which one.

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
REV5 = {
    "NOISE64":       "41f2adb399b60f0d7f1d77a03bf004d9b2ec28ab220f476cfafe96c36f99a613",
}
# KIT808 as revision 5 stated it, kept so the change is a visible fact and not
# an edited literal. Revision 6 refitted the kit to the reference recording.
KIT808_REV5 = "819ef081eca2aaff17c8f63d9653ee8d62dc69a6f6e48b08082161b8db66b3dc"
# ... and as revision 6 stated it. Revision 7 moved it a second time: the
# snare's partial balance and snappy rate, both measured on the same machine.
KIT808_REV6 = "06f47f307efbd44317e2aa0fcba99cba96f7cf747cdeffdc6c471b94b869914a"
REV7 = {
    "KIT808":        "7ea9a2e3ae152f3aa7e65ad33b43b154aa8c513105ccde0f2bc6605ee6ae6ec4",
}


def test_committed_images_and_contract_match_the_model():
    """Every hex image, the appendix block, rtl-sketch/tanh16.hex and every
    stated hash must be exactly what the model generates now."""
    assert gt.main(["--check"]) == 0


def test_rev3_hashes_are_unchanged_and_rev5_adds_two():
    """Revision 5 added NOISE64 and KIT808 and changed no existing table;
    revision 6 changed KIT808 and nothing else."""
    got = {name: gt.sha(vals) for name, vals, _, _, _ in gt.tables()}
    assert {k: got[k] for k in REV3} == REV3
    assert {k: got[k] for k in REV5} == REV5
    assert {k: got[k] for k in REV7} == REV7
    assert set(got) == set(REV3) | set(REV5) | set(REV7)


def test_the_only_hash_that_ever_moved_is_the_kits():
    """Loudly, because a pinned table has now moved TWICE: KIT808 is not what
    revision 5 pinned and not what revision 6 pinned, and every other table in
    the contract's history still is what revision 1 or 3 or 5 pinned. If this
    test ever needs a second entry, a second pinned table has moved and that
    needs its own revision and its own paragraph."""
    got = {name: gt.sha(vals) for name, vals, _, _, _ in gt.tables()}
    for stated, rev in ((KIT808_REV5, 5), (KIT808_REV6, 6)):
        was = {**REV3, **REV5, "KIT808": stated}
        moved = sorted(k for k, v in was.items() if got[k] != v)
        assert moved == ["KIT808"], f"against revision {rev}'s pins: {moved}"
    assert got["KIT808"] == REV7["KIT808"]


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
    assert len(kit) == 100 and all(0 <= a < 256 and 0 <= v < (1 << 32) for a, v in kit)
    assert kit[0] == (0x20, 71758)                           # OSC_INC[0]: 205.3 Hz


def test_note_inc_is_the_siblings():
    """Same formula, same 128 values as gf180-polysynth's Appendix A."""
    assert gt.sha(gt.note_inc()) == "e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4"
