import os
from pathlib import Path
import pytest
from engine.commands import MemoryDumpCommand, LoadMemoryCommand

# chmod-based permission restrictions have no effect when running as root
# (uid 0 bypasses the permission bits), so these tests are meaningless in
# that context -- e.g. root-run CI or an unprivileged Docker image that
# hasn't dropped to a non-root user.
running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
skip_if_root = pytest.mark.skipif(
    running_as_root,
    reason="chmod-based permission checks don't apply when running as root",
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


@skip_if_root
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


@skip_if_root
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
