"""
The individual commands for controlling the emulator console.
"""

import re
import logging
import os
from typing import Any
from pathlib import Path
from .base_command import BaseCommand

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
        # TODO(redesign): ported from Project Voyager, where this wrote the
        # raw ASCII dump straight to disk with no validation. Now that
        # memory.Memory has a real parser (Memory.from_string()) with
        # MemoryError reporting, this should build a Memory from raw_data
        # first -- so a corrupt/truncated dump raises a clear error here
        # instead of silently overwriting a good file on disk -- and only
        # write to self.target_file (e.g. via memory.to_string()) once that
        # succeeds.
        raise NotImplementedError(
            "MemoryDumpCommand.parse_response needs to be redesigned to "
            "validate the dump via memory.Memory before writing it to disk."
        )


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
        """Queues the file contents to the serial buffer immediately after 'l'."""
        # TODO(redesign): ported from Project Voyager, where this streamed
        # the file's raw text to the device with no validation. It should
        # instead parse self.source_file via memory.Memory.from_file() (or
        # from_string()) first, so a malformed file is rejected here with a
        # clear MemoryError-based message instead of being streamed at the
        # DM41L over serial. Once validated, re-serialize with
        # memory.to_string() (or send the original text, if validation
        # alone is judged sufficient) via self.serial.send_data().
        raise NotImplementedError(
            "LoadMemoryCommand.trigger_transfer needs to be redesigned to "
            "validate the file via memory.Memory before streaming it to "
            "the device."
        )

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
