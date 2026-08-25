"""
Tests for Memory.pack() -- GitHub issue #31 ("DM41L_Explorer needs PACK
functionality"). Key Assignments/Alarms already stay canonically packed
as a side effect of every set_key_assignment()/delete_key_assignment()
call (see _encode_key_assignment_entries()'s docstring); pack() re-runs
that explicitly and does the equivalent for program memory
(_rebuild_program_memory(), shared with Memory.remove_program() -- see
test_program_remove.py for that other caller).
"""

from pathlib import Path

import pytest

from memory import Memory

DATA_DIR = Path(__file__).parent / "data"

ALL_FIXTURES = sorted(DATA_DIR.glob("*.dm41"))


# -- Safety/idempotence across every real sample dump ------------------------


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_pack_never_loses_or_reorders_programs(path):
    memory = Memory.from_file(path)
    before = [(p.names_label, p.length) for p in memory.list_programs()]
    before_bytes = [memory.get_program_bytes(p) for p in memory.list_programs()]

    memory.pack()

    after_programs = memory.list_programs()
    assert [(p.names_label, p.length) for p in after_programs] == before
    assert [memory.get_program_bytes(p) for p in after_programs] == before_bytes


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_pack_never_reports_a_negative_reclaim(path):
    # The regression this guards: an earlier version of the newest-
    # program collapse optimization (_collapse_trailing_end_into_dot_end())
    # didn't check register alignment before rewriting DotEnd, and could
    # move it the WRONG way (using *more* register space than before,
    # e.g. on twolabels.dm41 -- a single program terminated only by the
    # permanent .END., already in its most-compact form). pack() must
    # never make memory less free than it started.
    memory = Memory.from_file(path)
    freed = memory.pack()
    assert freed >= 0, f"{path.name}: pack() reported a NEGATIVE reclaim ({freed})"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_pack_is_idempotent(path):
    # Packing an already-packed buffer a second time should never find
    # anything left to reclaim.
    memory = Memory.from_file(path)
    memory.pack()
    assert memory.pack() == 0


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_pack_round_trips_through_to_string_and_from_string(path):
    memory = Memory.from_file(path)
    memory.pack()
    expected = [(p.names_label, p.length) for p in memory.list_programs()]

    reloaded = Memory.from_string(memory.to_string())
    assert [(p.names_label, p.length) for p in reloaded.list_programs()] == expected


# -- twolabels.dm41: the specific alignment regression ------------------------


def test_pack_on_twolabels_stays_at_the_optimal_dot_end_terminated_layout():
    # FIRST/SECOND (twolabels.dm41) has no explicit END at all -- only
    # the permanent .END. terminates it, already the most compact form a
    # single newest program can take (Program's own docstring). This is
    # exactly the fixture that caught the alignment bug during
    # development (see test_pack_never_reports_a_negative_reclaim).
    memory = Memory.from_file(DATA_DIR / "twolabels.dm41")
    before = memory.list_programs()[0]
    assert before.terminator == ".END."
    before_dot_end = memory.DotEnd()

    freed = memory.pack()

    after = memory.list_programs()[0]
    assert freed == 0
    assert after.terminator == ".END."
    assert memory.DotEnd() == before_dot_end


# -- Key Assignments / Alarms --------------------------------------------------


def test_pack_leaves_correct_key_assignment_entries_unchanged():
    memory = Memory.from_file(DATA_DIR / "keyassigns.dm41")
    before = memory._decode_key_assignment_entries()
    memory.pack()
    assert memory._decode_key_assignment_entries() == before


def test_pack_leaves_key_assignments_end_and_alarms_end_unchanged_when_canonical():
    memory = Memory.from_file(DATA_DIR / "alarmtest.dm41")
    before_key_end = memory.key_assignments_end()
    before_alarms_end = memory.alarms_end()
    memory.pack()
    assert memory.key_assignments_end() == before_key_end
    assert memory.alarms_end() == before_alarms_end


# -- Programs with key assignments (sec 4.6) ----------------------------------


def test_pack_preserves_global_label_key_assignments():
    memory = Memory.from_file(DATA_DIR / "global-key-assignments.dm41")
    before = {
        p.names_label: p.labels[0].key_assignment for p in memory.list_programs()
    }
    memory.pack()
    after = {
        p.names_label: p.labels[0].key_assignment for p in memory.list_programs()
    }
    assert after == before

    # And the KEYFLAGS bits themselves are untouched too.
    for p in memory.list_programs():
        key_number, shifted = memory._key_number_for_byte(p.labels[0].key_assignment)
        assert memory.get_key_flag(key_number, shifted) is True


# -- Edge cases ----------------------------------------------------------------


def test_pack_on_empty_program_memory_is_a_safe_no_op():
    memory = Memory.from_file(DATA_DIR / "empty.dm41")
    assert memory.list_programs() == []
    before_dot_end = memory.DotEnd()
    freed = memory.pack()
    assert freed == 0
    assert memory.list_programs() == []
    assert memory.DotEnd() == before_dot_end


def test_pack_on_a_freshly_constructed_memory_does_not_raise():
    # A brand-new Memory() (no dump loaded at all) has no sane R00/.END.
    # partition -- pack() should still repack Key Assignments/Alarms
    # (trivially empty) without raising, and leave program memory alone.
    memory = Memory()
    memory.pack()  # must not raise
    assert memory.list_programs() == []
