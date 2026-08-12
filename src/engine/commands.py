"""
The individual commands for controlling the emulator console.
"""

import re
import logging
import os
from typing import Any
from pathlib import Path
from .base_command import BaseCommand

# This is the one deliberate coupling point between the engine/serial layer
# and memory.py: MemoryDumpCommand and LoadMemoryCommand move dump data to
# and from disk/the device, so they're the natural place to validate that
# data is a well-formed dump before trusting it (see the docstrings below).
# Nothing else in this module touches memory.py.
from memory import Memory

logger = logging.getLogger(__name__)


class PingCommand(BaseCommand):
    """Dummy command. Used to verify the calculator console is running."""

    def __init__(self, timeout: float):
        super().__init__(timeout=timeout)

    @property
    def command_string(self) -> str:
        return ""

    def parse_response(self, raw_data: str) -> Any:
        return raw_data.strip()


class MemoryDumpCommand(BaseCommand):
    """
    's' command - Causes the calculator to dump its memory to the console
    as ASCII encoded text data. This data is then written to a file.
    """

    def __init__(self, args: list, timeout: float = 1.0, serial=None):
        super().__init__(args=args, timeout=timeout, serial=serial)
        if not args:
            raise Exception("No file argument provided for MemoryDumpCommand.")
        self.target_file = args[0]
        path = Path(self.target_file)

        # Check if parent directory exists and is writable to allow file creation
        if not path.parent.exists():
            raise Exception(
                f"Cannot create dump: The parent directory '{path.parent}' does not exist."
            )
        if not os.access(path.parent, os.W_OK):
            raise Exception(
                f"Cannot create dump: Permission denied in directory '{path.parent}'."
            )

        # If file exists already, verify it is writable for overwriting
        if path.exists() and not os.access(path, os.W_OK):
            raise Exception(
                f"Cannot write dump: File '{self.target_file}' is not writable."
            )

    @property
    def command_string(self) -> str:
        return "s"

    def parse_response(self, raw_data: str) -> Any:
        """
        Parses the device's raw dump text into a Memory (raising a clear
        error if it's malformed) before writing anything to disk, then
        writes the *canonical* re-serialization (Memory.to_string()) rather
        than the raw device bytes -- so what's on disk always matches what
        this tool's own parser understood, and a round-trip failure surfaces
        immediately instead of silently saving a dump nothing can re-read.

        Returns the parsed Memory so callers (e.g. the CLI) can load it
        straight into an in-memory buffer without a second file read.
        """
        try:
            memory = Memory.from_string(raw_data)
        except ValueError as e:
            raise ValueError(
                f"Device returned a dump that failed to parse: {e}"
            ) from e

        with open(self.target_file, "w", encoding="utf-8") as file:
            file.write(memory.to_string())

        return memory


class MemoryStringCommand(BaseCommand):
    """
    's' command - Causes the calculator to dump its memory to the console
    as ASCII encoded text data. This data is returned as a string.
    """

    def __init__(self, timeout: float = 1.0, serial=None):
        super().__init__(timeout=timeout, serial=serial)

    @property
    def command_string(self) -> str:
        return "s"

    def parse_response(self, raw_data: str) -> Any:
        dump = raw_data.strip()
        return dump


class LoadMemoryCommand(BaseCommand):
    """'l' command - Streams file contents to hardware."""

    def __init__(self, args: list, timeout: float = 5.0, serial=None):
        super().__init__(args=args, timeout=timeout, serial=serial)
        if not args:
            raise Exception("No file argument provided for LoadMemoryCommand.")
        self.source_file = args[0]
        path = Path(self.source_file)

        if not path.exists():
            raise Exception(f"{self.source_file} does not exist.")
        if not os.access(path, os.R_OK):
            raise Exception(
                f"Permission denied: File '{self.source_file}' is not readable."
            )

    @property
    def command_string(self) -> str:
        return "l"  # send_command will handle adding the newline

    def trigger_transfer(self):
        """
        Queues the file contents to the serial buffer immediately after 'l'.

        Validates self.source_file as a well-formed dump via
        Memory.from_string() *before* anything is sent to the device --
        catching a malformed file here, instead of streaming it at the
        DM41L and finding out from a garbled device response. Note that by
        this point the engine has already sent the "l" command itself (see
        CommandEngine.execute()'s docstring); if validation fails here, the
        device is left waiting for a payload that never arrives, and the
        engine's own per-command timeout is what recovers that state --
        callers that can validate earlier (e.g. the CLI, before it even
        calls engine.execute()) should still do so, to avoid sending "l" at
        all for a file that's already known to be bad.
        """
        logger.info("Beginning file transfer.")
        if not self.serial:
            logger.error("No serial manager available for LoadMemoryCommand.")
            return
        try:
            with open(self.source_file, "r", encoding="utf-8") as f:
                data = f.read()

            try:
                Memory.from_string(data)
            except ValueError as e:
                raise ValueError(
                    f"'{self.source_file}' does not look like a valid DM41 "
                    f"dump: {e}"
                ) from e

            # Send raw data without an extra newline added by send_command
            self.serial.send_data(data)
            logger.info("File contents queued for transmission.")
        except Exception as e:
            logger.error("Failed to read file for transfer: %s", e)
            raise

    def parse_response(self, raw_data: str) -> Any:
        # Search for success/failure indicators within the accumulated buffer
        if "Read OK" in raw_data:
            return raw_data.strip()
        if "Read FAILED" in raw_data:
            raise ValueError("Transfer Failed: Read FAILED")

        return raw_data.strip()


class LoadMemoryStringCommand(BaseCommand):
    """'l' command - Streams a string to hardware as a memory dump."""

    def __init__(self, args: list, timeout: float = 5.0, serial=None):
        super().__init__(args=args, timeout=timeout, serial=serial)
        if not args or len(args) < 1:
            raise Exception("No data provided for LoadMemoryStringCommand.")
        self.source = args[0]

    @property
    def command_string(self) -> str:
        return "l"  # send_command will handle adding the newline

    def trigger_transfer(self):
        """Queues the file contents to the serial buffer immediately after 'l'."""
        logger.info("Beginning file transfer.")
        if not self.serial:
            logger.error("No serial manager available for LoadMemoryStringCommand.")
            return
        try:
            # Send raw data without an extra newline added by send_command
            self.serial.send_data(self.source)
            logger.info("File contents queued for transmission.")
        except Exception as e:
            logger.error("Failed to transfer data: %s", e)
            raise

    def parse_response(self, raw_data: str) -> Any:
        # Search for success/failure indicators within the accumulated buffer
        if "Read OK" in raw_data:
            return raw_data.strip()
        if "Read FAILED" in raw_data:
            raise ValueError("Transfer Failed: Read FAILED")

        return raw_data.strip()


class GetTimeCommand(BaseCommand):
    """'t' command - Requests system time."""

    @property
    def command_string(self) -> str:
        return "t"

    def parse_response(self, raw_data: str) -> Any:
        # Expected Response:
        # YYYY-MM-DD HH:MM:SS DOW
        response = raw_data.strip()
        pattern = r"^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\s[A-Z]{3}$"
        if re.match(pattern, response):
            return response

        raise ValueError(f"Invalid time data received: '{response}'")


class SetTimeCommand(BaseCommand):
    """'ts' command - Sets device clock."""

    def __init__(self, args: list):
        """
        Sets the calculator's clock. arguments are in the form
        [ "YYYYMMDD", "HHMMSS"]
        """
        super().__init__(args=args)

        try:
            self._formatted_arg = " ".join(args)
        except Exception as e:
            logger.error("Invalid Time Stamp '%s'", args)
            raise e

    @property
    def command_string(self) -> str:
        return f"ts {self._formatted_arg}"

    def parse_response(self, raw_data: str) -> Any:
        return raw_data.strip()


class BatteryCheckCommand(BaseCommand):
    """'b' command - Returns battery voltage in mV."""

    @property
    def command_string(self) -> str:
        return "b"

    def parse_response(self, raw_data: str) -> Any:
        # Expected Response:
        # "BAT: <nnnn>mV"
        pattern = r"BAT:\s*(\d+)mV"
        match = re.search(pattern, raw_data)

        if match:
            return int(match.group(1))

        raise ValueError(
            f"Could not parse battery voltage from " f"response: '{raw_data}'"
        )


class ConsoleTimeoutCommand(BaseCommand):
    """'ct' command - Configures console timeout in minutes."""

    def __init__(self, args: list):
        super().__init__(args=args)
        self.minutes = int(args[0])

    @property
    def command_string(self) -> str:
        return f"ct {self.minutes}"

    def parse_response(self, raw_data: str) -> Any:
        # Expected Response:
        # "Console timeout set to <nn> minutes"
        return raw_data.strip()
