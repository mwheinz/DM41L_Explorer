"""
MemoryRegion and its concrete subclasses -- named spans of registers
within a Memory (status registers, primary/data memory, and the
still-lightly-understood key-assignment/alarm/program-memory regions).

Extended memory (XMFile/ExtendedMemory) lives in xm_file.py instead, since
it has its own file-system-like structure built on top of a region.
"""

from typing import Dict, TYPE_CHECKING

from .registers import Register, AlphaRegister
from .constants import STATUS_REGISTERS_RANGE, STATUS_REGISTER_LABELS

if TYPE_CHECKING:
    from .memory import Memory


class MemoryRegion:
    """
    Base class for a contiguous, addressable span of registers within a
    Memory. Subclasses represent the different kinds of memory (status
    registers, primary data, extended memory, etc.) and add whatever
    access is appropriate for that kind -- e.g. StatusRegisters exposes
    named accessors, DataMemory exposes BCD numbers.
    """

    key: str = "region"
    label: str = "Region"
    address_range: list

    def __init__(self, memory: "Memory", address_range: list):
        self._memory = memory
        self.address_range = address_range

    def __contains__(self, addr: int) -> bool:
        return self.address_range[0] <= addr <= self.address_range[1]

    def __iter__(self):
        return iter(range(self.address_range[0], self.address_range[1] + 1))

    def __len__(self) -> int:
        return self.address_range[1] - self.address_range[0] + 1

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(0x{self.address_range[0]:03X}-"
            f"0x{self.address_range[1]:03X})"
        )

    def _check_addr(self, addr: int):
        if addr not in self:
            raise ValueError(
                f"Address 0x{addr:03X} is outside {type(self).__name__} "
                f"(0x{self.address_range[0]:03X}-0x{self.address_range[1]:03X})"
            )

    def get_register(self, addr: int) -> Register:
        """Reads a register at an absolute address within this region."""
        self._check_addr(addr)
        return self._memory.get_register(addr)

    def set_register(self, addr: int, register: Register):
        """Writes a register at an absolute address within this region."""
        self._check_addr(addr)
        self._memory.set_register(addr, register)

    def registers(self) -> Dict[int, Register]:
        """All registers in this region, keyed by absolute address."""
        return {addr: self.get_register(addr) for addr in self}


class StatusRegisters(MemoryRegion):
    """The 16 named CPU/system registers, T through e."""

    key = "status_registers"
    label = "Status Registers"

    def __init__(self, memory: "Memory"):
        super().__init__(memory, STATUS_REGISTERS_RANGE)
        bd = (
            self.get_register(8)._data[4:7]
            + self.get_register(7)._data
            + self.get_register(6)._data
            + self.get_register(5)._data
        )
        self.alpha = AlphaRegister(data=bd, ascii_only=True, read_only=True)

    def T(self) -> Register:
        return self.get_register(0)

    def Z(self) -> Register:
        return self.get_register(1)

    def Y(self) -> Register:
        return self.get_register(2)

    def X(self) -> Register:
        return self.get_register(3)

    def LastX(self) -> Register:
        return self.get_register(4)

    def M(self) -> Register:
        return self.get_register(5)

    def N(self) -> Register:
        return self.get_register(6)

    def O(self) -> Register:
        return self.get_register(7)

    def P(self) -> Register:
        return self.get_register(8)

    def Q(self) -> Register:
        return self.get_register(9)

    def F(self) -> Register:
        return self.get_register(10)

    def a(self) -> Register:
        return self.get_register(11)

    def b(self) -> Register:
        return self.get_register(12)

    def c(self) -> Register:
        return self.get_register(13)

    def d(self) -> Register:
        return self.get_register(14)

    def e(self) -> Register:
        return self.get_register(15)

    def Flags(self) -> Register:
        return self.get_register(14)

    def label_for(self, addr: int) -> str:
        """The system-register name (e.g. 'X') for an address in this region."""
        if 0x00 <= addr <= 0x04:
            return (
                f"{STATUS_REGISTER_LABELS[addr]}: "
                f"{self.get_register(addr).get_bcd_number()}"
            )
        if 0x05 <= addr <= 0x08:
            return (
                f"{STATUS_REGISTER_LABELS[addr]}: "
                f"{self.get_register(addr).get_ascii()}"
            )
        if 0x09 <= addr <= 0x0F:
            return (
                f"{STATUS_REGISTER_LABELS[addr]}: "
                f"{self.get_register(addr).get_hex()}"
            )
        return None


class KeyAssignments(MemoryRegion):
    """Need more research."""

    key = "key_assignments"
    label = "Key Assignments"


class Alarms(MemoryRegion):
    """Need more research."""

    key = "alarms"
    label = "Alarms"


class ProgramMemory(MemoryRegion):
    """
    Still needs more research for anything beyond listing what's here --
    decoding actual instruction bytes isn't implemented. See
    docs/program.md sec 5 for the global-label/END chain format, and
    Memory.list_programs() below for what that lets us report today.
    """

    key = "program_memory"
    label = "Program Memory"


class PrimaryData(MemoryRegion):
    """
    Main data-register storage; registers here hold BCD-encoded numbers,
    0-6 characters of ASCII data, or packed binary data.
    """

    key = "primary_data"
    label = "Main Memory"

    def get_number(self, addr: int) -> float:
        return self.get_register(addr).get_bcd_number()

    def set_number(self, addr: int, value: float):
        register = self.get_register(addr)
        register.set_bcd_number(value)
        self.set_register(addr, register)


class UnusedRegion(MemoryRegion):
    key = "unused"
    label = "Unused / Free"
