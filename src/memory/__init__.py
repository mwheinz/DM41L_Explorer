"""
A representation of the memory of a DM41L emulator.

The dump consists of three parts: the header ("DM41") the dump of main
memory, and the "special registers" which I believe represent the emulated
HP41 CPU registers.

NOTE: The HP41C and DM41L are "little endian" - the LSB is considered to by
"byte 0" and the MSB is considered "byte 6" - but DM41L dump files print hex
data from MSB to LSB. That is, _data[0] contains the MSB of the register. and
_data[6] contains the LSB. Care must be taken to remember this difference when
comparing HP41 documentation with the implementation of the Register and
Memory classes.

This used to be a single memory.py file; it was split into this package on
2026-08-13 for readability (memory.py had grown to ~1900 lines / 78KB).
Every name that was importable from `memory` before the split still is, via
the re-exports below, so `from memory import Memory, Register, ...`
elsewhere in the codebase (or in external code) is unaffected. See the
individual submodules for what lives where:

  registers.py     Register, AlphaRegister, DM41LMemoryError,
                    format_data_line/parse_data_line (DATA line format)
  trigraphs.py     encode_trigraphs/decode_trigraphs (docs/trigraphs.md --
                    the HP41/DM41L FOCAL character set's non-ASCII symbols)
  constants.py     address-range and sentinel-register constants
  regions.py       MemoryRegion and its non-XM subclasses
  xm_file.py       XMFile, ExtendedMemory (extended-memory file storage)
  program_info.py  ProgramInfo (program-memory "global chain" entries)
  memory.py        Memory (the top-level dump: parsing, raw register
                    access, and the R00/.END./flags/program-chain
                    accessors built on top of it)
"""

from .registers import (
    DM41LMemoryError,
    Register,
    AlphaRegister,
    format_data_line,
    parse_data_line,
)
from .trigraphs import encode_trigraphs, decode_trigraphs
from .constants import (
    STATUS_REGISTERS_RANGE,
    VOID_RANGE,
    KEY_ASSIGNMENTS_RANGE,
    PRIMARY_DATA_END,
    ZERO_REGISTER_HEX,
    ZERO_REGISTER,
    EOM_REGISTER_HEX,
    EOM_REGISTER,
    STATUS_REGISTER_LABELS,
    XM_REGIONS,
)
from .regions import (
    MemoryRegion,
    StatusRegisters,
    KeyAssignments,
    Alarms,
    ProgramMemory,
    PrimaryData,
    UnusedRegion,
)
from .xm_file import XMFile, ExtendedMemory, NAME_MIN_CHAR, NAME_MAX_CHAR
from .program_info import ProgramInfo
from .memory import Memory

# Every concrete region type, used to build REGION_NAMES and available for
# isinstance() checks by callers (e.g. the GUI) that need to special-case a
# particular kind of region.
REGION_CLASSES = [
    StatusRegisters,
    KeyAssignments,
    ProgramMemory,
    PrimaryData,
    ExtendedMemory,
    UnusedRegion,
]

# Display name for each region key. Kept as a plain dict (rather than only
# living on the classes) since callers like the preferences UI iterate over
# it directly.
REGION_NAMES = {cls.key: cls.label for cls in REGION_CLASSES}

__all__ = [
    "DM41LMemoryError",
    "Register",
    "AlphaRegister",
    "format_data_line",
    "parse_data_line",
    "encode_trigraphs",
    "decode_trigraphs",
    "STATUS_REGISTERS_RANGE",
    "VOID_RANGE",
    "KEY_ASSIGNMENTS_RANGE",
    "PRIMARY_DATA_END",
    "ZERO_REGISTER_HEX",
    "ZERO_REGISTER",
    "EOM_REGISTER_HEX",
    "EOM_REGISTER",
    "STATUS_REGISTER_LABELS",
    "XM_REGIONS",
    "MemoryRegion",
    "StatusRegisters",
    "KeyAssignments",
    "Alarms",
    "ProgramMemory",
    "PrimaryData",
    "UnusedRegion",
    "XMFile",
    "ExtendedMemory",
    "NAME_MIN_CHAR",
    "NAME_MAX_CHAR",
    "ProgramInfo",
    "Memory",
    "REGION_CLASSES",
    "REGION_NAMES",
]
