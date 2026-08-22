'''
MemoryRegion/StatusRegisters, and RegionSpan -- two different answers to
"what named span of registers is this."

MemoryRegion is a real object with behavior (get_register()/set_register()/
registers()/__contains__), meant for a region whose address range is fixed
at construction time. StatusRegisters (0x00-0x0F, never moves) is the only
region that actually fits that shape, which is why it's the only subclass
here -- until issue #25, this module also had KeyAssignments/Alarms/
ProgramMemory/PrimaryData/UnusedRegion stub subclasses for the *dynamic*
regions (key assignments, alarms, program memory, data memory), but none
of them were ever actually instantiated anywhere in the codebase (two --
KeyAssignments/Alarms -- didn't even have a working __init__), and for
good reason: those regions' boundaries move on nearly every edit (adding a
key assignment moves key_assignments_end(), which moves the Alarms buffer,
which moves where "unused" program memory starts, independently of R00()/
DotEnd() also moving as programs are added/removed). A MemoryRegion
instance built at one instant would go stale the moment any of that
happened -- worse than not having the abstraction at all, and exactly the
kind of drift issue #23 was caused by. Meanwhile hex_view_tab.py and
overview_tab.py, the only real consumers, never wanted region *behavior*
for these anyway -- both just wanted "what are the current boundaries",
computed fresh, as plain data.

That's what RegionSpan is for: a small immutable (key, label, start, end)
descriptor, no behavior beyond containment/length, returned in a fresh
list by Memory.regions() (memory.py) every time it's called -- so it can
never drift from Memory's own live boundary accessors (R00()/DotEnd()/
key_assignments_end()/alarms_end()). hex_view_tab.py and overview_tab.py
both now read region boundaries from that single source instead of each
hand-rolling its own classification/arithmetic.

Extended memory (XMFile/ExtendedMemory) lives in xm_file.py instead, since
it has its own file-system-like structure built on top of a region.
'''

from typing import Dict, TYPE_CHECKING

from .registers import Register, AlphaRegister
from .constants import STATUS_REGISTERS_RANGE, STATUS_REGISTER_LABELS

if TYPE_CHECKING:
    from .memory import Memory


class MemoryRegion:
    '''
    Base class for a contiguous, addressable span of registers within a
    Memory. Subclasses represent the different kinds of memory (status
    registers, primary data, extended memory, etc.) and add whatever
    access is appropriate for that kind -- e.g. StatusRegisters exposes
    named accessors, DataMemory exposes BCD numbers.
    '''

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
        '''Reads a register at an absolute address within this region.'''
        self._check_addr(addr)
        return self._memory.get_register(addr)

    def set_register(self, addr: int, register: Register):
        '''Writes a register at an absolute address within this region.'''
        self._check_addr(addr)
        self._memory.set_register(addr, register)

    def registers(self) -> Dict[int, Register]:
        '''All registers in this region, keyed by absolute address.'''
        return {addr: self.get_register(addr) for addr in self}


class StatusRegisters(MemoryRegion):
    '''The 16 named CPU/system registers, T through e.'''

    key = "status_registers"
    label = "Status Registers"

    def __init__(self, memory: "Memory"):
        super().__init__(memory, STATUS_REGISTERS_RANGE)
        bd = (
            self.get_register(8).get_bytes()[4:7]
            + self.get_register(7).get_bytes()
            + self.get_register(6).get_bytes()
            + self.get_register(5).get_bytes()
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
        '''The system-register name (e.g. 'X') for an address in this region.'''
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


class RegionSpan:
    '''
    A plain, immutable descriptor for one of the *dynamic* regions
    Memory.regions() (memory.py) reports -- key assignments, alarms,
    program memory, data memory, status registers, XM, the unused/void
    gaps. Deliberately NOT a MemoryRegion: it carries no reference back to
    a Memory and no read/write behavior, just the boundaries and label a
    caller asked "what's here" for at one moment. See this module's
    docstring for why the region-with-behavior shape (MemoryRegion) is
    wrong for anything whose boundaries move.

    `start`/`end` are both inclusive, matching MemoryRegion.address_range's
    own convention (`start <= addr <= end`).
    '''

    __slots__ = ("key", "label", "start", "end")

    def __init__(self, key: str, label: str, start: int, end: int):
        self.key = key
        self.label = label
        self.start = start
        self.end = end

    @property
    def count(self) -> int:
        '''Number of registers this span covers -- 0 (not negative) for an
        empty span, e.g. a dump with no key assignments at all.'''
        return max(0, self.end - self.start + 1)

    def __contains__(self, addr: int) -> bool:
        return self.start <= addr <= self.end

    def __repr__(self) -> str:
        return f"RegionSpan({self.key!r}, 0x{self.start:03X}-0x{self.end:03X})"
