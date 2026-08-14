import json
import os
import platform
import pytest
from config import ProjectConfig

# chmod-based permission restrictions have no effect when running as root
# (uid 0 bypasses the permission bits), and separately os.chmod() on
# Windows can only toggle the read-only attribute -- a directory's
# read-only attribute there doesn't block creating files inside it, so
# chmod(readonly_dir, 0o555) below is a no-op on Windows too -- see the
# matching guards in test_commands.py.
running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
skip_if_permission_bits_unenforced = pytest.mark.skipif(
    running_as_root or platform.system() == "Windows",
    reason="chmod-based directory/unreadable-file checks aren't enforced "
    "(root, or Windows os.chmod semantics)",
)


@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    """Points ProjectConfig.PREFS_FILE at a throwaway path
    for the test. It doesn't exist on disk until a test creates it."""
    fake_prefs_path = tmp_path / ".voyager_prefs.json"
    monkeypatch.setattr(ProjectConfig, "PREFS_FILE", fake_prefs_path)
    return fake_prefs_path


def test_defaults_when_no_prefs_file(prefs_file):
    """With no file on disk, all defaults should be used."""
    config = ProjectConfig()
    assert config.baudrate == ProjectConfig.DEFAULT_PREFS["baudrate"]
    assert config.serial_port == ProjectConfig.DEFAULT_PREFS["serial_port"]
    assert config.logging_level == ProjectConfig.DEFAULT_PREFS["logging_level"]
    # GUI display prefs are unified into the same config/file as of
    # 2026-08-12 (gui/gui_config.py's separate ExplorerConfig is gone).
    assert config.appearance_mode == ProjectConfig.DEFAULT_PREFS["appearance_mode"]
    assert config.color_theme == ProjectConfig.DEFAULT_PREFS["color_theme"]


def test_load_merges_saved_values_over_defaults(prefs_file):
    """Only the keys present on disk should override the defaults."""
    prefs_file.write_text(json.dumps({"baudrate": 115200}))
    config = ProjectConfig()
    assert config.baudrate == 115200
    # Untouched keys should still fall back to defaults.
    assert (
        config.console_timeout_minutes
        == ProjectConfig.DEFAULT_PREFS["console_timeout_minutes"]
    )


def test_load_raises_exception_on_corrupt_json(prefs_file):
    """Corrupt JSON now raises an exception instead of falling back to defaults."""
    prefs_file.write_text("{not valid json")
    with pytest.raises(Exception) as excinfo:
        ProjectConfig()
    assert "Could not load preferences from" in str(excinfo.value)


def test_save_writes_current_prefs_to_disk(prefs_file):
    config = ProjectConfig()
    config.baudrate = 57600
    config.save()

    on_disk = json.loads(prefs_file.read_text())
    assert on_disk["baudrate"] == 57600


def test_save_with_explicit_prefs_argument(prefs_file):
    config = ProjectConfig()
    new_prefs = {**ProjectConfig.DEFAULT_PREFS, "logging_level": "DEBUG"}
    config.save(new_prefs)

    on_disk = json.loads(prefs_file.read_text())
    assert on_disk["logging_level"] == "DEBUG"
    assert config.logging_level == "DEBUG"


def test_property_setters_update_internal_state(prefs_file):
    config = ProjectConfig()
    config.serial_port = "/dev/tty.fake"
    config.console_timeout_minutes = 5
    config.appearance_mode = "Dark"
    config.color_theme = "green"

    assert config.serial_port == "/dev/tty.fake"
    assert config.console_timeout_minutes == 5
    assert config.appearance_mode == "Dark"
    assert config.color_theme == "green"
    assert config.get_all()["serial_port"] == "/dev/tty.fake"


def test_save_persists_appearance_and_theme(prefs_file):
    """appearance_mode/color_theme round-trip through the same single file
    as every other setting -- there's no more separate GUI prefs file."""
    config = ProjectConfig()
    config.appearance_mode = "Dark"
    config.color_theme = "green"
    config.save()

    on_disk = json.loads(prefs_file.read_text())
    assert on_disk["appearance_mode"] == "Dark"
    assert on_disk["color_theme"] == "green"

    reloaded = ProjectConfig()
    assert reloaded.appearance_mode == "Dark"
    assert reloaded.color_theme == "green"


def test_round_trip_persists_across_instances(prefs_file):
    """Saving with one instance and loading with a fresh one should agree."""
    first = ProjectConfig()
    first.baudrate = 4800
    first.save()

    second = ProjectConfig()
    assert second.baudrate == 4800


@skip_if_permission_bits_unenforced
def test_save_raises_exception_on_permission_error(tmp_path, monkeypatch):
    """Verifies that save() raises an exception when writing fails."""
    readonly_dir = tmp_path / "readonly_dir"
    readonly_dir.mkdir()

    # Read + execute only, no write: the directory stays traversable (so
    # PREFS_FILE.exists() in load() still works, same as the ProjectConfig()
    # constructor below expects) but writing a new file inside it fails.
    # (stat.S_IREAD alone also strips the execute bit, which breaks
    # exists()-style checks on children rather than exercising the write
    # failure this test is meant to cover -- see the equivalent, correct
    # 0o555 usage in test_commands.py's no_permission_on_parent test.)
    os.chmod(readonly_dir, 0o555)

    fake_prefs_path = readonly_dir / ".voyager_prefs.json"
    monkeypatch.setattr(ProjectConfig, "PREFS_FILE", fake_prefs_path)

    config = ProjectConfig()
    with pytest.raises(Exception) as excinfo:
        config.save()
    assert "Could not save preferences to" in str(excinfo.value)
