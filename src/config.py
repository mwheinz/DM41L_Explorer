"""
Centralized configuration for DM41L_Explorer.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectConfig:
    """Centralized configuration for DM41L_Explorer with file-based persistence."""

    # Persistent storage location in the user's home directory. Filename is
    # a holdover from the project's old name "Project Voyager".
    PREFS_FILE = Path.home() / ".voyager_prefs.json"

    # Default values
    DEFAULT_PREFS = {
        "baudrate": 38400,
        "console_timeout_minutes": 10,
        "serial_port": "/dev/tty.usbmodem14101",
        "logging_level": "INFO",
        "log_directory": str(Path.home()),
        "appearance_mode": "System",  # "System", "Light", "Dark"
        "color_theme": "blue",  # CustomTkinter built-in theme name
        "font_family": "",  # "" = use CustomTkinter's built-in per-platform default
        "font_size": 0,  # 0 = use CustomTkinter's built-in default size
    }

    def __init__(self):
        """Initializes the config with values loaded from disk."""
        self._prefs = self.load()

    def load(self) -> dict:
        """Loads preferences from disk, returning defaults if loading fails."""
        prefs = self.DEFAULT_PREFS.copy()
        loaded_data = {}
        try:
            if self.PREFS_FILE.exists():
                with open(self.PREFS_FILE, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    prefs.update(loaded_data)
        except Exception as e:
            logger.warning("Could not load preferences from %s: %s", self.PREFS_FILE, e)
            raise Exception(
                f"Warning: Could not load preferences from {self.PREFS_FILE}"
            ) from e

        return prefs

    def save(self, prefs: dict = None) -> None:
        """Saves current preferences to disk."""
        if prefs is not None:
            self._prefs = prefs

        try:
            with open(self.PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._prefs, f, indent=2)
        except Exception as e:
            logger.error("Could not save preferences to %s: %s", self.PREFS_FILE, e)
            raise Exception(
                f"Error: Could not save preferences to {self.PREFS_FILE}"
                ) from e

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

    @property
    def appearance_mode(self) -> str:
        return self._prefs["appearance_mode"]

    @appearance_mode.setter
    def appearance_mode(self, value):
        self._prefs["appearance_mode"] = value

    @property
    def color_theme(self) -> str:
        return self._prefs["color_theme"]

    @color_theme.setter
    def color_theme(self, value):
        self._prefs["color_theme"] = value

    @property
    def font_family(self) -> str:
        return self._prefs["font_family"]

    @font_family.setter
    def font_family(self, value):
        self._prefs["font_family"] = value

    @property
    def font_size(self) -> int:
        return self._prefs["font_size"]

    @font_size.setter
    def font_size(self, value):
        self._prefs["font_size"] = value

    def get_all(self) -> dict:
        return self._prefs
