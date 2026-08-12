"""
Simple configuration class for loading/saving values for the Voyager app.
"""

import json
from pathlib import Path


class ProjectConfig:
    """Centralized configuration for Project Voyager with file-based persistence."""

    # Persistent storage location in the user's home directory
    PREFS_FILE = Path.home() / ".voyager_prefs.json"

    # Default values
    DEFAULT_PREFS = {
        "baudrate": 38400,
        "console_timeout_minutes": 10,
        "serial_port": "/dev/tty.usbmodem14101",
        "logging_level": "INFO",
        "log_directory": str(Path.home()),
    }

    def __init__(self):
        """Initializes the config with values loaded from disk."""
        self._prefs = self.load()

    def load(self) -> dict:
        """Loads preferences from disk, returning defaults if loading fails."""
        prefs = self.DEFAULT_PREFS.copy()
        try:
            if self.PREFS_FILE.exists():
                with open(self.PREFS_FILE, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    prefs.update(loaded_data)
        except Exception as e:
            raise Exception(
                f"Warning: Could not load preferences from {self.PREFS_FILE}: {e}"
            )
        return prefs

    def save(self, prefs: dict = None) -> None:
        """Saves current preferences to disk."""
        if prefs is not None:
            self._prefs = prefs

        try:
            with open(self.PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._prefs, f, indent=2)
        except Exception as e:
            raise Exception(
                f"Error: Could not save preferences to {self.PREFS_FILE}: {e}"
            )

    # --- Properties for clean access in other modules ---

    @property
    def baudrate(self) -> int:
        return self._prefs["baudrate"]

    @baudrate.setter
    def baudrate(self, value):
        self._prefs["baudrate"] = value

    @property
    def console_timeout_minutes(self) -> int:
        return self._prefs["console_timeout_minutes"]

    @console_timeout_minutes.setter
    def console_timeout_minutes(self, value):
        self._prefs["console_timeout_minutes"] = value

    @property
    def serial_port(self) -> str:
        return self._prefs["serial_port"]

    @serial_port.setter
    def serial_port(self, value):
        self._prefs["serial_port"] = value

    @property
    def logging_level(self) -> str:
        return self._prefs["logging_level"]

    @logging_level.setter
    def logging_level(self, value):
        self._prefs["logging_level"] = value

    @property
    def log_directory(self) -> Path:
        return Path(self._prefs["log_directory"]).expanduser()

    @log_directory.setter
    def log_directory(self, value):
        self._prefs["log_directory"] = str(value)

    def get_all(self) -> dict:
        return self._prefs
