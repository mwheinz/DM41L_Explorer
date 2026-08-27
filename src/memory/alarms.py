'''
Alarms: the alarms buffer (docs/alarms.md sec 3/4).

The buffer sits immediately above the Key Assignment Registers, with no
gap, and below whatever free/program-memory space follows: one header
register (0xAA marker + a total register count that includes the header
and the closing delimiter), followed by the alarm entries in ascending,
time-sorted order, then a single 0xF0-marked delimiter register.

Per-alarm content (the time/repeat/message registers) isn't decoded here
yet -- but the buffer's outer bounds are enough to (a) show it as its own
region in the hex view and (b) keep it from being overwritten, or
separated by a gap, whenever a Key Assignments edit changes how many
registers that region needs (see `relocate()`).
'''

from typing import TYPE_CHECKING

from .registers import Register, DM41LMemoryError
from .regions import MemoryRegion
from .constants import PRIMARY_DATA_END

if TYPE_CHECKING:
    from .memory import Memory


class Alarms(MemoryRegion):
    '''
    A variable memory region that begins the register after the last key
    assignment and extends for the number of registers defined in the first
    alarms register. If no alarms exist, this region will be 0-length.
    '''

    key = "alarms"
    label = "Alarms"

    HEADER_MARKER = 0xAA

    def __init__(self, memory: "Memory"):
        super().__init__(memory)

    @property
    def start(self) -> int:
        '''Exactly where the Key Assignment Registers stop -- the two
        regions are always back-to-back with no gap (docs/alarms.md sec 3).
        Read live, so a key-assignment edit that grows or shrinks that
        region moves this one with it.'''
        return self._memory.key_assignments.end_exclusive

    @property
    def end(self) -> int:
        '''Highest address in the buffer (the closing 0xF0 delimiter), or
        `start - 1` when there is no buffer here at all.'''
        return self.span_end_at(self.start) - 1

    def span_end_at(self, start: int) -> int:
        '''Calculates the end of the alarm buffer+1.
        returns `start` itself if there is no real buffer there.

        This takes the start address as an argument and then walks the alarms
        and calculates a new end value to allow the caller to relocate the
        alarms buffer when new key assignments are inserted.
        '''
        header = self._memory.get_register(start).get_bytes()
        if header[0] != self.HEADER_MARKER:
            return start
        count = header[1]
        end = start + count
        if count <= 0 or end - 1 > PRIMARY_DATA_END:
            return start
        return end

    def relocate(self, old_start: int, new_start: int):

        '''
        Moves the buffer (if any) from old_start to new_start.
        `new_start`, with no gap -- called from
        KeyAssignments._encode_entries() with that region's boundary before
        and after an edit, since this buffer always starts exactly at that
        boundary. Called BEFORE any new Key Assignment register is written, so
        a growing region can't clobber the header/entries currently sitting
        right where it's about to write.

        No-op if the two boundaries are equal (the edit didn't change how
        many registers Key Assignments occupies) or if there's no real
        buffer at `old_start` (same check span_end_at() makes).

        Copies the whole buffer -- header, entries, and delimiter -- as
        one block, in whichever direction avoids overwriting a source
        register before it's been read.

        Registers freed by the buffer moving up (Key Assignments growing) are
        left alone -- the caller is about to overwrite that entire span with
        real Key Assignment register data anyway. Registers freed by the
        buffer moving down (Key Assignments shrinking) are explicitly zeroed,
        since nothing else is about to write there. (Strictly speaking, this
        isn't necessary, but it helps avoid confusion if the user looks at the
        raw memory dump.)
        '''

        delta = new_start - old_start
        if delta == 0:
            # Nothing to do.
            return

        memory = self._memory
        header = memory.get_register(old_start).get_bytes()
        if header[0] != self.HEADER_MARKER:
            # no Alarms buffer here -- nothing to move
            return 

        count = header[1]
        old_end = old_start + count
        if count <= 0 or old_end - 1 > PRIMARY_DATA_END:
            raise DM41LMemoryError("Alarm memory is corrupt.")

        if new_start + count - 1 > PRIMARY_DATA_END:
            # Nowhere to put it -- on real hardware this would be an
            # out-of-memory condition this tool doesn't model; the
            # safest thing to do here is decline to move the buffer
            # rather than truncate or wrap it into an invalid address.
            raise DM41LMemoryError("Insufficient memory.")

        indices = range(count - 1, -1, -1) if delta > 0 else range(count)
        for i in indices:
            memory.set_register(new_start + i, memory.get_register(old_start + i))

        if delta < 0:
            new_end = new_start + count
            for addr in range(new_end, old_end):
                memory.set_register(addr, Register(size=7))
