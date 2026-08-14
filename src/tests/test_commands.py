import os
import platform
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from engine.commands import MemoryDumpCommand, LoadMemoryCommand
from memory import Memory

# chmod-based permission restrictions have no effect when running as root
# (uid 0 bypasses the permission bits), so these tests are meaningless in
# that context -- e.g. root-run CI or an unprivileged Docker image that
# hasn't dropped to a non-root user.
running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
skip_if_root = pytest.mark.skipif(
    running_as_root,
    reason="chmod-based permission checks don't apply when running as root",
)

# Separately, os.chmod() on Windows can only toggle the file read-only
# attribute (stat.S_IWRITE/S_IREAD) -- it has no notion of an unreadable
# file, and a directory's read-only attribute doesn't block creating files
# inside it (Windows uses that bit for other purposes, not access control).
# So chmod(dir, 0o555) and chmod(file, 0o000) are both no-ops there, while
# chmod(file, 0o444) still works (Windows does enforce write-protection on
# an individual file) -- see test_memory_dump_command_file_exists_but_not_writable
# below, which stays root-only. These two need the extra Windows skip.
skip_if_permission_bits_unenforced = pytest.mark.skipif(
    running_as_root or platform.system() == "Windows",
    reason="chmod-based directory/unreadable-file checks aren't enforced "
    "(root, or Windows os.chmod semantics)",
)


def test_memory_dump_command_no_args():
    """Tests that providing no arguments raises an exception."""
    with pytest.raises(Exception) as excinfo:
        MemoryDumpCommand(args=[])
    assert "No file argument provided" in str(excinfo.value)


def test_memory_dump_command_nonexistent_parent(tmp_path):
    """Tests that a non-existent parent directory triggers validation error."""
    # Create a path where the parent folder does not exist yet
    bad_path = tmp_path / "nonexistent_dir" / "dump.bin"
    with pytest.raises(Exception) as excinfo:
        MemoryDumpCommand(args=[str(bad_path)])
    assert "does not exist" in str(excinfo.value)


@skip_if_permission_bits_unenforced
def test_memory_dump_command_no_permission_on_parent(tmp_path):
    """Tests that a read-only parent directory triggers validation error."""
    dir_path = tmp_path / "readonly_dir"
    dir_path.mkdir()
    bad_path = dir_path / "dump.bin"

    # Remove write permissions from the parent directory
    os.chmod(dir_path, 0o555)  # Read & Execute only
    try:
        with pytest.raises(Exception) as excinfo:
            MemoryDumpCommand(args=[str(bad_path)])
        assert "Permission denied" in str(excinfo.value)
    finally:
        # Restore permissions so cleanup can happen properly
        os.chmod(dir_path, 0o755)


@skip_if_root
def test_memory_dump_command_file_exists_but_not_writable(tmp_path):
    """Tests that existing files must be writable for overwriting."""
    file_path = tmp_path / "readonly_file.bin"
    file_path.write_text("existing data")
    os.chmod(file_path, 0o444)  # Set file to read-only
    try:
        with pytest.raises(Exception) as excinfo:
            MemoryDumpCommand(args=[str(file_path)])
        assert "not writable" in str(excinfo.value)
    finally:
        os.chmod(file_path, 0o644)


def test_load_memory_command_no_args():
    """Tests that providing no arguments raises an exception."""
    with pytest.raises(Exception) as excinfo:
        LoadMemoryCommand(args=[])
    assert "No file argument provided" in str(excinfo.value)


def test_load_memory_command_nonexistent_file(tmp_path):
    """Tests that a missing file triggers validation error."""
    bad_path = tmp_path / "missing.bin"
    with pytest.raises(Exception) as excinfo:
        LoadMemoryCommand(args=[str(bad_path)])
    assert "does not exist" in str(excinfo.value)


@skip_if_permission_bits_unenforced
def test_load_memory_command_no_read_permission(tmp_path):
    """Tests that file read permissions are verified before attempting transfer."""
    file_path = tmp_path / "unreadable.bin"
    file_path.write_text("some data")
    os.chmod(file_path, 0o000)  # Remove all permissions
    try:
        with pytest.raises(Exception) as excinfo:
            LoadMemoryCommand(args=[str(file_path)])
        assert "Permission denied" in str(excinfo.value)
    finally:
        os.chmod(file_path, 0o644)


def test_load_memory_command_success_validation(tmp_path):
    """Verifies that a standard readable file passes validation."""
    file_path = tmp_path / "readable.bin"
    file_path.write_text("some data")
    cmd = LoadMemoryCommand(args=[str(file_path)])
    assert cmd.source_file == str(file_path)


# --- parse_response()/trigger_transfer() -- the memory.Memory integration ---
#
# These exercise the redesign called for when parse_response/trigger_transfer
# were first ported (and temporarily stubbed) from Project Voyager: dump data
# now passes through memory.Memory for validation before it's trusted, in
# either direction.

VALID_DUMP = Memory().to_string()


def test_memory_dump_command_parse_response_valid(tmp_path):
    """A well-formed dump is parsed, returned as a Memory, and written to
    disk in its canonical (re-serialized) form."""
    target = tmp_path / "out.dm41"
    cmd = MemoryDumpCommand(args=[str(target)])

    result = cmd.parse_response(VALID_DUMP)

    assert result == Memory.from_string(VALID_DUMP)
    assert target.read_text() == result.to_string()


def test_memory_dump_command_parse_response_invalid_does_not_touch_disk(tmp_path):
    """A malformed dump raises before anything is written -- an existing
    file at the target path must be left untouched."""
    target = tmp_path / "out.dm41"
    target.write_text("previous good dump\n")
    cmd = MemoryDumpCommand(args=[str(target)])

    with pytest.raises(ValueError, match="failed to parse"):
        cmd.parse_response("this is not a DM41 dump")

    assert target.read_text() == "previous good dump\n"


def test_load_memory_command_trigger_transfer_valid_sends_file(tmp_path):
    """A well-formed dump file is validated and then streamed as-is."""
    source = tmp_path / "in.dm41"
    source.write_text(VALID_DUMP)
    mock_serial = MagicMock()
    cmd = LoadMemoryCommand(args=[str(source)], serial=mock_serial)

    cmd.trigger_transfer()

    mock_serial.send_data.assert_called_once_with(VALID_DUMP)


def test_load_memory_command_trigger_transfer_invalid_never_sends(tmp_path):
    """A malformed dump file is rejected before anything reaches the
    serial manager -- send_data() must never be called."""
    source = tmp_path / "in.dm41"
    source.write_text("this is not a DM41 dump")
    mock_serial = MagicMock()
    cmd = LoadMemoryCommand(args=[str(source)], serial=mock_serial)

    with pytest.raises(ValueError, match="does not look like a valid DM41L dump"):
        cmd.trigger_transfer()

    mock_serial.send_data.assert_not_called()
