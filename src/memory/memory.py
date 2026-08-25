'''
Memory: a complete DM41L memory dump -- parsing/serializing the dump
format, raw register access, and the higher-level accessors built on top
of it (R00/.END./SigmaReg, the 56 status flags, and the program-memory
global chain walk). See the memory package's __init__.py docstring for
the on-disk dump format overview.
'''

import re
from typing import Dict, Optional, Union
from pathlib import Path

from .registers import Register, DM41LMemoryError
from .constants import (
    PRIMARY_DATA_END,
    KEY_ASSIGNMENTS_RANGE,
    STATUS_REGISTERS_RANGE,
    VOID_RANGE,
    XM_REGIONS,
    MIN_SANE_R00,
)
from .program_info import ProgramInfo, ProgramLabel, Program
from .regions import RegionSpan
from .opcode_scan import find_program_end, scan_global_markers_forward
from .program_chain import walk_chain, encode_chain_marker
from . import functions as key_functions


class Memory:
    '''A complete DM41L memory dump.'''

    # Pattern to capture 'A:' followed by any hex string of 1 or more chars
    SPECIAL_PATTERN = re.compile(r"([A-Z]:\s*)([0-9a-fA-F]+)")

    # Status register addresses used by the R00/.END./Flags accessors below.
    REG_C_ADDR = 0x0D  # SREG / printer-use / cold-start / R00 / .END.
    REG_D_ADDR = 0x0E  # Flags
    FLAG_COUNT = 56

    # KEYFLAGS bitmaps (docs/key_assignments.md sec 4.5): register F holds
    # the unshifted-key existence bits, register e the shifted-key ones.
    KEYFLAGS_UNSHIFTED_ADDR = 0x0A  # F
    KEYFLAGS_SHIFTED_ADDR = 0x0F  # e

    def __init__(self, header: str = "DM41"):
        self._header = header
        self._core_memory: Dict[int, Register] = {}  # Keyed by register index
        self._special_registers: Dict[str, Register] = (
            {}
        )  # Keyed by label order preservation

        # Default values for some status registers. Taken from a memory
        # dump in the "Memory Lost" state. Registers not initialized
        # are all zeroes.
        self._core_memory[8] = Register.from_hex("4b000000000000")
        self._core_memory[12] = Register.from_hex("1000000000019c")
        self._core_memory[13] = Register.from_hex("1a70016919c19b")
        self._core_memory[14] = Register.from_hex("0000002c048000")

        # Default values for special registers. Taken from a
        # memory dump in the "Memory Lost" state.
        self._special_registers["A"] = Register.from_hex("00000000c00020")
        self._special_registers["B"] = Register.from_hex("f000002c0480fd")
        self._special_registers["C"] = Register.from_hex("f000002c0480fd")
        self._special_registers["S"] = Register.from_hex("00001100000000")
        self._special_registers["M"] = Register.from_hex("00011cd5ff73cb")
        self._special_registers["N"] = Register.from_hex("000000000000c0")
        self._special_registers["G"] = Register.from_hex("00")

        # Address one past the last Key Assignments register (see
        # key_assignments_end()'s docstring below). A freshly-constructed
        # Memory has no dump loaded, so there's nothing to have scanned yet
        # -- this defaults to KEY_ASSIGNMENTS_RANGE[0] (0xC0) itself, the
        # same "no key assignments found" value _scan_key_assignments_end()
        # returns for a real dump with an empty Key Assignments region.
        self._key_assignments_end = KEY_ASSIGNMENTS_RANGE[0]

    def __eq__(self, other):
        if not isinstance(other, Memory):
            return False

        if self._header != other._header:
            return False
        if self._special_registers != other._special_registers:
            return False

        # Compare *effective* register values via get_register() rather
        # than the raw _core_memory dicts: get_register() already treats
        # an address with no explicit entry as an implicit zero register,
        # so two Memory objects that agree on every address's effective
        # value are equal even if one of them happens to have an explicit
        # zero-valued entry (e.g. written out as part of a 4-register-
        # aligned page in to_string()/from_string(), see the page-grouping
        # note there) where the other has none at all. Comparing the raw
        # dicts directly used to make a dump fail to equal itself after a
        # to_string()/from_string() round trip whenever a page mixed
        # explicitly-set and implicitly-zero registers -- e.g. Memory()'s
        # own defaults, which set registers 8, 12, 13, and 14 but leave
        # 9, 10, 11, and 15 (in the same two pages) implicit.
        addrs = set(self._core_memory) | set(other._core_memory)
        return all(self.get_register(a) == other.get_register(a) for a in addrs)

    @classmethod
    def from_string(cls, buffer: str) -> "Memory":
        '''
        Creates a new Memory object from a string that contains a DM41
        memory dump.
        '''
        lines = buffer.strip().splitlines()
        if not lines:
            return cls()

        header = lines[0]
        if header != "DM41":
            raise ValueError(f"Invalid header: {header}")

        memory = cls(header)
        phase = 1
        next_base = 0
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            token = line.split()
            if ":" not in token[0]:
                if phase != 1:
                    raise ValueError(
                        "Memory registers cannot follow" f" special registers. {line}"
                    )
                # We're expecting a well-formed memory dump.
                # First token should be a hex base-addr.
                try:
                    base = int(token[0], 16)
                except ValueError as e:
                    raise ValueError(
                        f"{token[0]} is not a hexadecimal" " number. {line}"
                    ) from e
                if base < next_base:
                    raise ValueError(
                        "Memory dump is not well-formed:"
                        f"{base} < {next_base}. {line}"
                    )

                i = 0
                for hex_str in token[1:]:
                    memory._core_memory[base + i] = Register.from_hex(hex_str)
                    i += 1
                if i > 4:
                    raise ValueError(f"Line too long: {line}")

                next_base = base + i
            else:
                phase = 2

                # This section can have a varying number of registers per
                # line, but they should be in pairs.
                for i in range(0, len(token), 2):
                    if ":" != token[i][1]:
                        raise ValueError(f"Malformed line {line}")
                    label = token[i][0]
                    memory._special_registers[label] = Register.from_hex(token[i + 1])

        memory._key_assignments_end = memory._scan_key_assignments_end()
        return memory

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "Memory":
        ''' Load a memory dump from disk. '''
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_string(f.read())

    def get_register(self, key: Union[int, str]) -> Optional[Register]:
        if isinstance(key, int):
            # Check if the address exists in our sparse core memory mapping
            reg = self._core_memory.get(key)
            if reg is None:
                # Return a default 56-bit (7 byte) register of zeroes if address is missing
                return Register(7)
            return reg
        return self._special_registers.get(key)

    def set_register(self, key: Union[int, str], register: Register):
        if isinstance(key, int):
            self._core_memory[key] = register
        else:
            self._special_registers[key] = register

    @staticmethod
    def _nibbles_to_int(nibbles) -> int:
        ''' Combine a list of nibbles into an integer. '''
        value = 0
        for n in nibbles:
            value = (value << 4) | n
        return value

    # -- Register c (0x0D): SREG / printer-use / cold-start / R00 / .END. --
    #
    #   Register c contains multiple important fields. Read memory.md for a
    #   detailed explanation of what each field is fore.
    #   nibbles[0:3]   SREG  (ΣREG) absolute address
    #   nibbles[3:5]   printer use (undecoded)
    #   nibbles[5:8]   cold-start signature -- always 0x169 in real dumps,
    #                  usable as a sanity check
    #   nibbles[8:11]  R00   absolute address of data register 00
    #   nibbles[11:14] .END. absolute address of the end of program memory
    def _reg_c_nibbles(self) -> list:
        return self.get_register(self.REG_C_ADDR).get_nibbles()

    def SigmaReg(self) -> int:
        '''Absolute address of ΣREG, decoded from register c.'''
        return self._nibbles_to_int(self._reg_c_nibbles()[0:3])

    def DotEnd(self) -> int:
        '''Absolute address of the end of loaded program memory (".END.").'''
        return self._nibbles_to_int(self._reg_c_nibbles()[11:14])

    def R00(self) -> int:
        '''
        Absolute address of data register 00 -- the boundary between
        program memory (below R00) and main data memory (R00 up to
        PRIMARY_DATA_END, inclusive).
        '''
        return self._nibbles_to_int(self._reg_c_nibbles()[8:11])

    def set_R00(self, addr: int):
        '''
        Directly rewrites the R00 pointer in register c.

        This only moves the partition marker -- it does NOT move, clear, or
        resize any actual register contents on either side of the new
        boundary, so moving it can expose stale program bytes as "data" (or
        hide real data registers behind the program-memory boundary).

        This is useful for experimenting with synthetic programming - careful
        use of R00 movement can be used to create special "byte jumper" and
        "byte loader" instructions that are the foundation of synthetic
        programming.
        '''
        if not (0 <= addr <= 0xFFF):
            raise ValueError(
                f"R00 must fit in a 3-nibble address (0-0xFFF), got 0x{addr:x}"
            )
        nibbles = self._reg_c_nibbles()
        nibbles[8] = (addr >> 8) & 0xF
        nibbles[9] = (addr >> 4) & 0xF
        nibbles[10] = addr & 0xF
        new_bytes = bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, 14, 2))
        self.set_register(self.REG_C_ADDR, Register(data=new_bytes))

    def set_DotEnd(self, addr: int):
        '''
        Directly rewrites the `.END.` pointer in register c -- the write
        side `DotEnd()` doesn't have, added for `import_program()` (below)
        to move the permanent `.END.` sentinel to the top of whatever
        newly-imported program memory it just wrote. Like `set_R00()`,
        this only moves the pointer itself; it doesn't touch, clear, or
        validate any register contents on either side of it.
        '''
        if not (0 <= addr <= 0xFFF):
            raise ValueError(
                f".END. must fit in a 3-nibble address (0-0xFFF), got 0x{addr:x}"
            )
        nibbles = self._reg_c_nibbles()
        nibbles[11] = (addr >> 8) & 0xF
        nibbles[12] = (addr >> 4) & 0xF
        nibbles[13] = addr & 0xF
        new_bytes = bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, 14, 2))
        self.set_register(self.REG_C_ADDR, Register(data=new_bytes))

    # -- Key Assignments (starting at KEY_ASSIGNMENTS_RANGE[0] / 0xC0) --
    #
    # Each register holding user function key assignments starts with a
    # 0xF0 marker byte, followed by up to two 3-byte assignment entries:
    #   [fn byte 1] [fn byte 2] [key byte]
    # A built-in single-byte HP-41 function stores its filler byte FIRST
    # (fn byte 1 == 0x04) and the real function code second; a two-byte
    # XROM/peripheral function uses both bytes for real data, no filler.
    # Reverse-engineered from William C. Wickes' "Synthetic Programming on
    # the HP-41C" (Section 2E, "The Key Assignment Registers") and
    # confirmed byte-for-byte against real dumps -- see
    # docs/key_assignments.md sec 4.2/4.8 for the full derivation. The
    # Alarms buffer (docs/alarms.md sec 3/4, see alarms_end() below)
    # occupies the next span above this one; genuinely free registers
    # take up whatever remains up to .END. Telling the Alarms buffer's
    # own contents apart -- individual alarm entries, not just its outer
    # bounds -- isn't implemented yet (see regions.py's Alarms class).

    def _scan_key_assignments_end(self) -> int:
        '''Scans upward from KEY_ASSIGNMENTS_RANGE[0] (0xC0) for as long as
        each register's leading byte is the 0xF0 key-assignment marker,
        and returns the address one past the last such register -- an
        exclusive upper bound, suitable for e.g. `range(0xC0, end)`.
        Returns KEY_ASSIGNMENTS_RANGE[0] itself if register 0xC0 doesn't
        start a key-assignment register at all (no assignments made, or
        no real dump loaded).

        Bounded at PRIMARY_DATA_END as a hard backstop against a corrupt
        dump wandering past the Key Assignments region entirely, rather
        than trusting DotEnd()/R00() -- both of those are themselves
        derived values that can be nonsense in a fresh or corrupt Memory,
        so this scan deliberately doesn't depend on either.
        '''
        addr = KEY_ASSIGNMENTS_RANGE[0]
        while (
            addr <= PRIMARY_DATA_END
            and self.get_register(addr).get_bytes()[0] == 0xF0
        ):
            addr += 1
        return addr

    def key_assignments_end(self) -> int:
        '''Address one past the last Key Assignments register, as of the
        last time this dump was loaded via from_string()/from_file() (see
        _scan_key_assignments_end()). KEY_ASSIGNMENTS_RANGE[0] (0xC0)
        itself if there are no key assignments.

        This is cached at load time rather than recomputed on every call
        (unlike R00()/DotEnd(), which are cheap single-register nibble
        reads) -- a set_register() call after loading, e.g. from an edit
        dialog, will NOT update this until the dump is reloaded. The one
        exception is a Key Assignments edit made through
        set_key_assignment()/delete_key_assignment() themselves -- those
        go through _encode_key_assignment_entries(), which keeps this
        cached value (and the Alarms buffer immediately above it, see
        alarms_end()) up to date as part of the edit.
        '''
        return self._key_assignments_end

    # -- Alarms (docs/alarms.md sec 3/4) --
    #
    # The Alarms buffer sits immediately above the Key Assignments
    # registers, with no gap, and below whatever free/program-memory
    # space follows: one header register (0xAA marker + a total register
    # count that includes the header and the closing delimiter), that
    # many alarm entries packed in ascending, time-sorted order, then a
    # single 0xF0-marked delimiter register. Per-alarm content (the
    # time/repeat/message registers) isn't decoded here yet -- but the
    # buffer's outer bounds (alarms_end() below, exposed as a region via
    # regions() further down) are enough to (a) show it as its own region
    # in the hex view and (b)
    # keep it from being overwritten, or separated by a gap, whenever a
    # Key Assignments edit changes how many registers that region needs
    # (see _relocate_alarms() below).

    ALARMS_HEADER_MARKER = 0xAA

    def alarms_end(self) -> int:
        '''Address one past the last Alarms register (the header, every
        entry, and the closing 0xF0 delimiter). Unlike
        key_assignments_end(), this isn't cached -- there's no dedicated
        set/delete-alarm API yet that would need to keep a cached value
        in sync (edits so far only move the buffer as a block, see
        _relocate_alarms()), and reading the one header register this
        needs is cheap enough to just always recompute.

        Returns key_assignments_end() unchanged -- i.e. reports an empty
        Alarms buffer -- if the register immediately above Key
        Assignments doesn't start with the 0xAA header marker (no alarms
        set, or no real dump loaded), or if the header's declared count
        is nonsensical (zero, or reaching past the addressable space):
        that's treated as "not a real Alarms buffer" rather than trusted
        at face value, the same defensive posture
        _scan_key_assignments_end() takes against a corrupt dump.
        '''
        return self._alarms_span_end(self.key_assignments_end())

    def _alarms_span_end(self, start: int) -> int:
        '''Address one past the Alarms buffer starting at `start` (the
        same header-marker/count check alarms_end() makes), or `start`
        itself if there's no real Alarms buffer there. Factored out of
        alarms_end() so _encode_key_assignment_entries() can ask "where
        does the buffer end NOW, given it may have just been relocated
        to start at the brand new key_assignments_end?" without going
        through alarms_end() itself -- that method always calls
        key_assignments_end() for `start`, which is a cached value not
        yet updated to the new boundary at the point in that method
        where this is needed (see its docstring).'''
        header = self.get_register(start).get_bytes()
        if header[0] != self.ALARMS_HEADER_MARKER:
            return start
        count = header[1]
        end = start + count
        if count <= 0 or end - 1 > PRIMARY_DATA_END:
            return start
        return end

    def _relocate_alarms(self, old_key_assignments_end: int, new_key_assignments_end: int):
        '''Moves the Alarms buffer (if any) so it keeps starting exactly
        at `new_key_assignments_end`, with no gap -- called from
        _encode_key_assignment_entries() with the Key Assignments
        region's boundary before and after an edit, since the Alarms
        buffer (sec 2) always starts exactly at that boundary. Called
        BEFORE any new Key Assignment register is written, so a growing
        region can't clobber the Alarms header/entries currently sitting
        right where it's about to write.

        No-op if the two boundaries are equal (the edit didn't change how
        many registers Key Assignments occupies) or if there's no real
        Alarms buffer at `old_key_assignments_end` (same check
        alarms_end() makes).

        Copies the whole buffer -- header, entries, and delimiter -- as
        one block, in whichever direction avoids overwriting a source
        register before it's been read: reverse (highest address first)
        when the buffer is moving up and the move distance is smaller
        than the buffer itself, so the old and new spans overlap; forward
        otherwise. Registers freed by the buffer moving down (Key
        Assignments shrinking) are explicitly zeroed, since nothing else
        is about to write there. Registers freed by the buffer moving up
        (Key Assignments growing) are left alone -- the caller,
        _encode_key_assignment_entries(), is about to overwrite that
        entire span with real Key Assignment register data anyway.
        '''
        delta = new_key_assignments_end - old_key_assignments_end
        if delta == 0:
            return

        old_end = old_key_assignments_end
        header = self.get_register(old_end).get_bytes()
        if header[0] != self.ALARMS_HEADER_MARKER:
            return  # no Alarms buffer here -- nothing to move

        count = header[1]
        old_alarms_end = old_end + count
        if count <= 0 or old_alarms_end - 1 > PRIMARY_DATA_END:
            return  # doesn't look like a real Alarms buffer -- leave it be

        new_start = new_key_assignments_end
        if new_start + count - 1 > PRIMARY_DATA_END:
            # Nowhere to put it -- on real hardware this would be an
            # out-of-memory condition this tool doesn't model; the
            # safest thing to do here is decline to move the buffer
            # rather than truncate or wrap it into an invalid address.
            return

        indices = range(count - 1, -1, -1) if delta > 0 else range(count)
        for i in indices:
            self.set_register(new_start + i, self.get_register(old_end + i))

        if delta < 0:
            new_alarms_end = new_start + count
            for addr in range(new_alarms_end, old_alarms_end):
                self.set_register(addr, Register(size=7))

    # -- Regions (issue #25) --
    #
    # A single source for "what named region is this address in", replacing
    # what used to be independently hand-rolled in gui/hex_view_tab.py's
    # _classify() and gui/overview_tab.py's _render_summary()/
    # _render_partition() -- both called the boundary accessors above
    # (key_assignments_end()/alarms_end()/R00()/DotEnd()) correctly, but
    # each also reimplemented its own copy of "so what are the actual
    # region spans", which is exactly the kind of duplication that let
    # issue #23 (Alarms/Key Assignments not counted in the memory summary)
    # happen in the first place. regions() below is that missing shared
    # answer.

    def regions(self) -> list:
        '''
        Every named region of the full addressable display range
        (0x000-0x2EF), as a flat, address-ordered list of RegionSpan(key,
        label, start, end) -- both inclusive. Computed fresh from this
        Memory's own live boundary accessors on every call, so (unlike a
        construction-time MemoryRegion instance would) it can never go
        stale after key assignments/alarms/programs/data change -- see
        regions.py's module docstring for why that matters here.

        The "key" region (Key Assignments) always starts at
        KEY_ASSIGNMENTS_RANGE[0] (0xC0); "alarms" always starts exactly
        where "key" ends, with no gap (see alarms_end()'s docstring).
        Above that, when R00()/DotEnd() describe a sane program/data
        partition (see MIN_SANE_R00), the remaining span up to
        PRIMARY_DATA_END splits into "unused" (whatever's left over,
        approximate), "program", and "data"; when there's no sane
        partition yet (e.g. a freshly-created empty buffer, or a
        corrupt/unloaded dump), the whole remaining span is reported as
        one "unused" region instead of guessing at a split from
        meaningless R00/.END. values.

        A span can be empty (`.count == 0`, e.g. "key" when no key
        assignments exist) -- callers that want addresses (like
        hex_view_tab.py's per-row classification) can rely on `addr in
        span` correctly never matching an empty one, so empty spans don't
        need special-casing there; callers that want counts/text (like
        overview_tab.py's summary card) just read `.count` directly.

        The "xm" key appears twice (Extended Memory #0 and #1), since the
        two spans aren't contiguous with each other. Note XM #1's reported
        start (XM_REGIONS[1][0] - 1) is one register below XM_REGIONS[1]'s
        own start -- XM_REGIONS describes each region's *usable storage*
        span (excluding its reserved link/pointer register), while this
        display range includes that reserved register as part of the
        region visually, matching what hex_view_tab.py already showed
        before this method existed. XM #0 needs no such adjustment since
        XM_REGIONS[0][0] (0x40) already is the first displayed address
        there.
        '''
        spans = []

        spans.append(RegionSpan("status", "Status Registers", *STATUS_REGISTERS_RANGE))
        spans.append(RegionSpan("nonexistent", "Inaccessible", *VOID_RANGE))

        xm0_lo, xm0_hi = XM_REGIONS[0]
        spans.append(RegionSpan("xm", "XM", xm0_lo, xm0_hi))

        low = KEY_ASSIGNMENTS_RANGE[0]
        key_assignments_end = self.key_assignments_end()
        alarms_end = self.alarms_end()
        spans.append(RegionSpan("key", "Key Assignments", low, key_assignments_end - 1))
        spans.append(RegionSpan("alarms", "Alarms", key_assignments_end, alarms_end - 1))

        try:
            r00 = self.R00()
            dot_end = self.DotEnd()
        except Exception:
            # Same defensive posture as the try/except this replaces in
            # hex_view_tab.py/overview_tab.py -- a real dump always
            # decodes SOME r00/dot_end (even a fresh Memory()'s built-in
            # defaults do), but this guards against whatever unusual state
            # those call sites were already guarding against.
            r00 = dot_end = 0
        has_partition = r00 >= MIN_SANE_R00 and dot_end <= r00

        if has_partition:
            spans.append(RegionSpan("unused", "Unused / Free", alarms_end, dot_end - 1))
            spans.append(RegionSpan("program", "User Programs", dot_end, r00 - 1))
            spans.append(RegionSpan("data", "Data Memory", r00, PRIMARY_DATA_END))
        else:
            spans.append(RegionSpan("unused", "Unused / Free", alarms_end, PRIMARY_DATA_END))

        xm1_lo, xm1_hi = XM_REGIONS[1]
        spans.append(RegionSpan("xm", "XM", xm1_lo - 1, xm1_hi))

        return spans

    def region_for(self, addr: int):
        '''The RegionSpan containing `addr` (from regions()), or None if
        `addr` falls outside every span this method returns (shouldn't
        happen for any address in [0x000, 0x2EF], the full display range
        regions() covers, but this is a lookup, not a guarantee).'''
        for span in self.regions():
            if addr in span:
                return span
        return None

    # The 34 real assignable key positions on the physical keyboard (docs
    # sec 6 item 4's "HP41" grid) as (M, N) pairs. Row 3 has no N=1 -- that
    # position is the physical SHIFT key, which can never be assigned;
    # rows 4-8 only go up to N=4. Validating against this (rather than
    # just "1<=M<=8, 1<=N<=5") matters: an out-of-range pair like (8, 5)
    # produces a *negative* raw bit number in _keyflags_bit()'s formula,
    # which Python's divmod()/bytes indexing would silently wrap around to
    # a real (but wrong) byte instead of raising -- corrupting an
    # unrelated KEYFLAGS bit rather than failing loudly.
    _VALID_KEY_POSITIONS = (
        [(1, n) for n in range(1, 6)]
        + [(2, n) for n in range(1, 6)]
        + [(3, n) for n in range(2, 6)]
        + [(m, n) for m in range(4, 9) for n in range(1, 5)]
    )
    _VALID_KEY_NUMBERS = [10 * m + n for m, n in _VALID_KEY_POSITIONS]

    # Row 4's ENTER^ key is physically double-width -- on the real
    # keyboard it occupies both the column-1 AND column-2 slots in the
    # key-byte (sec 4.3) / KEYFLAGS (sec 4.5) column numbering, so there
    # is no real key at physical column 2 for row 4 at all. Confirmed
    # against Wickes' Figure 4-2 ("Key Assignment Flag Bits"): that
    # diagram draws a single wide box spanning columns 1-2 in row 4, with
    # no bit assigned to column 2 -- this is the "imaginary 42nd key
    # under ENTER" mentioned in sec 4.5's flag-count note. Wickes' key-
    # NUMBER notation (sec 2) still numbers row 4's three other keys
    # sequentially -- 42, 43, 44, the same as every other row -- but they
    # sit at physical column positions 3, 4, 5 in the formulas below, not
    # 2, 3, 4. Every other row's key-number column digit equals its
    # physical column directly; row 4 is the sole exception. Found
    # 2026-08-18 from the user's real-hardware testing: assignments to
    # key 42 showed up on the calculator as key 41 and didn't work, and
    # real-calculator row-4 assignments came back missing/misplaced when
    # read by this app -- both are exactly what using the wrong (N-1)
    # column offset for row 4 would cause.
    _ROW4_PHYSICAL_COLUMN = {1: 1, 2: 3, 3: 4, 4: 5}

    @staticmethod
    def _key_row_col(key_number: int) -> tuple:
        '''Splits a two-digit key number `MN` (docs/key_assignments.md sec
        2 -- row M, column N) into (M, N). Raises ValueError unless
        `key_number` is one of the 34 real assignable keyboard positions
        (see _VALID_KEY_POSITIONS above) -- notably rejecting `31` (the
        physical SHIFT key) and anything with M or N outside the real
        keyboard's layout. `N` here is the key-NUMBER column (as printed
        on the key, e.g. the `2` in `42`) -- see _physical_column() for
        the column actually used by the byte/bit formulas, which differs
        from this for row 4.'''
        m, n = divmod(key_number, 10)
        if (m, n) not in Memory._VALID_KEY_POSITIONS:
            raise ValueError(f"Invalid key number: {key_number!r}")
        return m, n

    @staticmethod
    def _physical_column(m: int, n: int) -> int:
        '''Maps a key number's (M, N) -- N being the key-NUMBER column,
        e.g. the `2` in key `42` -- to the physical column actually used
        by the key-byte (sec 4.3) and KEYFLAGS bit (sec 4.5) formulas.
        Identical to N for every row except row 4, whose double-width
        ENTER^ key shifts the three keys after it over by one physical
        column -- see _ROW4_PHYSICAL_COLUMN above.'''
        if m == 4:
            return Memory._ROW4_PHYSICAL_COLUMN[n]
        return n

    @staticmethod
    def key_byte_for(key_number: int, shifted: bool) -> int:
        '''The internal key-byte encoding for `key_number` (docs sec 4.3):
        `16*(N-1) + M` unshifted, `16*(N-1) + (M+8)` shifted, where `N` is
        the *physical* column (see _physical_column()).'''
        m, n = Memory._key_row_col(key_number)
        n_phys = Memory._physical_column(m, n)
        row = m + 8 if shifted else m
        return 16 * (n_phys - 1) + row

    @staticmethod
    def _keyflags_bit(key_number: int) -> int:
        '''Bit position within the KEYFLAGS bitmap (register F or e) for
        `key_number` (docs sec 4.5): `36 - M - 8*(N-1)`, where `N` is the
        *physical* column (see _physical_column()). The same bit number
        is used in both registers -- which register (F vs. e)
        distinguishes unshifted from shifted, not the bit position.'''
        m, n = Memory._key_row_col(key_number)
        n_phys = Memory._physical_column(m, n)
        return 36 - m - 8 * (n_phys - 1)

    def get_key_flag(self, key_number: int, shifted: bool) -> bool:
        '''Reads the KEYFLAGS existence bit for `key_number` -- True means
        *some* assignment exists for this key/shift-state, in either the
        Key Assignment Registers (sec 4.2) or a global label (sec 4.6);
        it says nothing about which kind. See docs sec 4.5.'''
        addr = self.KEYFLAGS_SHIFTED_ADDR if shifted else self.KEYFLAGS_UNSHIFTED_ADDR
        bit = self._keyflags_bit(key_number)
        reg = self.get_register(addr)
        byte_index, bit_in_byte = divmod(bit, 8)
        return bool((reg.get_bytes()[byte_index] >> (7 - bit_in_byte)) & 1)

    def set_key_flag(self, key_number: int, shifted: bool, value: bool):
        '''Sets or clears the KEYFLAGS existence bit for `key_number`
        (docs sec 4.5). Callers writing an actual assignment should use
        set_key_assignment()/delete_key_assignment() below instead of
        calling this directly -- those keep the Key Assignment Registers
        and KEYFLAGS in sync; this is the low-level primitive they (and
        global-label assignment/deletion, once implemented) share.'''
        addr = self.KEYFLAGS_SHIFTED_ADDR if shifted else self.KEYFLAGS_UNSHIFTED_ADDR
        bit = self._keyflags_bit(key_number)
        reg = self.get_register(addr)
        data = bytearray(reg.get_bytes())
        byte_index, bit_in_byte = divmod(bit, 8)
        mask = 1 << (7 - bit_in_byte)
        if value:
            data[byte_index] |= mask
        else:
            data[byte_index] &= ~mask & 0xFF
        self.set_register(addr, Register(data=bytes(data)))

    def _decode_key_assignment_entries(self) -> list:
        '''Returns every entry currently in the Key Assignment Registers,
        in stored (newest-first, sec 4.4) order, as
        `(fn_byte1, fn_byte2_or_None, key_byte)` tuples -- `fn_byte2` is
        None for a single-byte built-in function entry (the register's
        real filler-first storage, sec 4.2, is normalized away here so
        every other method only deals with "1 byte" vs. "2 bytes").'''
        entries = []
        for addr in range(KEY_ASSIGNMENTS_RANGE[0], self.key_assignments_end()):
            raw = self.get_register(addr).get_bytes()
            for offset in (1, 4):
                b0, b1, b2 = raw[offset], raw[offset + 1], raw[offset + 2]
                if b0 == 0 and b1 == 0 and b2 == 0:
                    continue  # register has an odd number of assignments
                if b0 == 0x04:
                    entries.append((b1, None, b2))
                else:
                    entries.append((b0, b1, b2))
        return entries

    def _encode_key_assignment_entries(self, entries: list):
        '''Repacks `entries` (same shape _decode_key_assignment_entries()
        returns) canonically into the Key Assignment Registers, starting
        at KEY_ASSIGNMENTS_RANGE[0] with no gaps, two entries per
        register, re-adding the filler byte for a single-byte entry (sec
        4.2). Clears every register between the new end and whatever now
        comes right after it -- either the old end, or the end of a
        just-relocated Alarms buffer if one is present and reaches past
        the old end -- so a shrinking edit doesn't leave stale F0-marked
        registers behind without also clobbering an Alarms buffer that
        may have just been moved into part of that same span. Also
        updates key_assignments_end(). See _relocate_alarms() for the
        move itself. Entries are written in list order -- callers
        control LIFO placement (sec 4.4) by ordering `entries` themselves
        before calling this.'''
        base = KEY_ASSIGNMENTS_RANGE[0]
        old_end = self.key_assignments_end()
        new_end = base + (len(entries) + 1) // 2  # ceil(len/2), 2 entries/register

        # Move the Alarms buffer out of the way BEFORE writing a single
        # new Key Assignment register below -- see _relocate_alarms()'s
        # docstring for why the order matters (a growing region would
        # otherwise overwrite it before it could be moved).
        self._relocate_alarms(old_end, new_end)

        addr = base
        i = 0
        while i < len(entries):
            data = bytearray(7)
            data[0] = 0xF0
            for slot in range(2):
                if i >= len(entries):
                    break
                fn1, fn2, key = entries[i]
                offset = 1 + slot * 3
                if fn2 is None:
                    data[offset] = 0x04
                    data[offset + 1] = fn1
                else:
                    data[offset] = fn1
                    data[offset + 1] = fn2
                data[offset + 2] = key
                i += 1
            self.set_register(addr, Register(data=bytes(data)))
            addr += 1

        # Anything from new_end up to old_end is stale -- UNLESS the
        # Alarms buffer was just relocated to start at new_end and
        # reaches into (or past) that span, in which case it's real,
        # just-moved Alarms data, not leftover Key Assignments bytes.
        # _alarms_span_end(new_end) reflects the buffer's post-move
        # position; alarms_end() can't be used here since it still goes
        # through key_assignments_end(), which isn't updated to new_end
        # until the line right after this loop.
        clear_from = self._alarms_span_end(new_end)
        for stale in range(clear_from, old_end):
            self.set_register(stale, Register(size=7))
        self._key_assignments_end = new_end

    def set_key_assignment(self, key_number: int, shifted: bool, function_bytes):
        '''Assigns `key_number` (unshifted or shifted, per `shifted`) to a
        built-in/peripheral function -- `function_bytes` is a single int
        (a one-byte HP-41 function, e.g. 0x40 for `+`; see the sec-5
        caveat in memory/functions.py for the low-code (<0x40) case) or a
        2-item sequence of ints (an XROM/peripheral function's two bytes,
        sec 4.8).

        Any existing entry for the same key/shift-state is replaced (not
        left as a stale duplicate): the old entry is removed and the new
        one inserted at the front, so it lands in register 0xC0 exactly
        as a brand-new assignment would (sec 4.4's LIFO order). Also sets
        the corresponding KEYFLAGS bit (sec 4.5), and clears any global
        label (sec 4.6) currently assigned to the same key -- the real
        lookup order (sec 4.7) would otherwise let this entry silently
        shadow that program's assignment rather than genuinely replacing
        it; see set_program_key_assignment() for the same precedent in
        the other direction.
        '''
        key_byte = self.key_byte_for(key_number, shifted)

        if isinstance(function_bytes, int):
            fn1, fn2 = function_bytes, None
        else:
            fn1, fn2 = function_bytes
            if fn2 is None:
                raise ValueError("A 2-byte function's second byte can't be None")

        for b in (fn1,) if fn2 is None else (fn1, fn2):
            if not (0 <= b <= 0xFF):
                raise ValueError(f"Function byte out of range: {b!r}")

        entries = [e for e in self._decode_key_assignment_entries() if e[2] != key_byte]
        entries.insert(0, (fn1, fn2, key_byte))
        self._encode_key_assignment_entries(entries)
        self._clear_program_assignments_for_key_byte(key_byte)
        self.set_key_flag(key_number, shifted, True)

    def delete_key_assignment(self, key_number: int, shifted: bool):
        '''Removes any Key Assignment Register entry for `key_number`/
        `shifted` and clears its KEYFLAGS bit. A no-op (still clears the
        flag) if the key currently has no entry there -- e.g. it's a
        global-label assignment (sec 4.6, untouched by this method) or
        simply unassigned.'''
        key_byte = self.key_byte_for(key_number, shifted)
        entries = self._decode_key_assignment_entries()
        filtered = [e for e in entries if e[2] != key_byte]
        if len(filtered) != len(entries):
            self._encode_key_assignment_entries(filtered)
        self.set_key_flag(key_number, shifted, False)

    def get_key_assignment(self, key_number: int, shifted: bool) -> Optional[dict]:
        '''Looks up the single Key Assignment Register entry (if any) for
        `key_number`/`shifted` -- same dict shape as one entry from
        list_key_assignments(), or None if that key/shift-state has no
        entry there (unassigned, or assigned via a global label instead,
        sec 4.6). Intended for a GUI rendering one keypad cell at a time
        (docs sec 6 item 4), where scanning the full decoded list per cell
        would be wasteful for a whole grid at once -- callers rendering
        every key at once should use list_key_assignments() instead.'''
        key_byte = self.key_byte_for(key_number, shifted)
        for fn1, fn2, kb in self._decode_key_assignment_entries():
            if kb == key_byte:
                return {
                    "key_number": key_number,
                    "shifted": shifted,
                    "fn_byte1": fn1,
                    "fn_byte2": fn2,
                    "name": key_functions.function_name_for_bytes(fn1, fn2),
                    "raw_key_byte": kb,
                }
        return None

    def list_key_assignments(self) -> list:
        '''Returns every built-in/peripheral key assignment currently in
        the Key Assignment Registers as a list of dicts:
        `{"key_number": int, "shifted": bool, "fn_byte1": int,
        "fn_byte2": int|None, "name": str}` -- `name` is the looked-up
        function name (memory/functions.py), or a "0xNN"-style fallback
        string if the byte(s) don't match any known function. Order
        matches the buffer's own newest-first order (sec 4.4); global
        label assignments (sec 4.6) are NOT included here -- see
        list_global_chain()'s `key_assignment` field for those, per
        docs/key_assignments.md sec 6 item 4's shared-data-model note.'''
        results = []
        for fn1, fn2, key_byte in self._decode_key_assignment_entries():
            try:
                key_number, shifted = self._key_number_for_byte(key_byte)
            except ValueError:
                # Doesn't decode to any of the 34 real assignable keyboard
                # positions -- seen so far only in a hand-crafted test
                # fixture (keyassigntest.dm41), not a real device capture.
                # Surfaced rather than silently dropped or crashing the
                # whole listing, with enough raw detail (the key byte
                # itself) that a caller/GUI can flag it distinctly.
                key_number, shifted = None, None
            results.append({
                "key_number": key_number,
                "shifted": shifted,
                "fn_byte1": fn1,
                "fn_byte2": fn2,
                "name": key_functions.function_name_for_bytes(fn1, fn2),
                "raw_key_byte": key_byte,
            })
        return results

    @staticmethod
    def _key_number_for_byte(key_byte: int) -> tuple:
        '''Inverts key_byte_for(): given a stored key byte, returns
        (key_number, shifted). Tries every real assignable keyboard
        position (_VALID_KEY_NUMBERS) rather than algebraically inverting
        the formula, since the carry behavior for M=8 rows (sec 4.3) makes
        a closed-form inverse easy to get subtly wrong; this is only ever
        called on the small number of decoded entries in a dump, so the
        brute-force cost is immaterial. Raises ValueError if `key_byte`
        doesn't match any real key (e.g. a corrupt dump, or a hand-crafted
        test fixture targeting a non-assignable position).'''
        for key_number in Memory._VALID_KEY_NUMBERS:
            if Memory.key_byte_for(key_number, False) == key_byte:
                return key_number, False
            if Memory.key_byte_for(key_number, True) == key_byte:
                return key_number, True
        raise ValueError(f"Key byte 0x{key_byte:02x} doesn't decode to a known key")

    # -- Register d (0x0E): the 56 user/system flags --
    #
    # Direct 1:1 mapping (confirmed against "A programmers handbook
    # v.2.07.pdf"'s "Flag register d" diagram): flag N is bit N of the
    # 56-bit register, counting from the MSB (flag 00) to the LSB (flag
    # 55). See docs/flags.md for each flag's name.

    def get_flag(self, n: int) -> bool:
        if not (0 <= n < self.FLAG_COUNT):
            raise ValueError(f"Flag number must be 0-{self.FLAG_COUNT - 1}, got {n}")
        d = self.get_register(self.REG_D_ADDR)
        byte_index, bit_in_byte = divmod(n, 8)
        return bool((d.get_bytes()[byte_index] >> (7 - bit_in_byte)) & 1)

    def set_flag(self, n: int, value: bool):
        if not (0 <= n < self.FLAG_COUNT):
            raise ValueError(f"Flag number must be 0-{self.FLAG_COUNT - 1}, got {n}")
        d = self.get_register(self.REG_D_ADDR)
        data = bytearray(d.get_bytes())
        byte_index, bit_in_byte = divmod(n, 8)
        mask = 1 << (7 - bit_in_byte)
        if value:
            data[byte_index] |= mask
        else:
            data[byte_index] &= ~mask & 0xFF
        self.set_register(self.REG_D_ADDR, Register(data=bytes(data)))

    def get_all_flags(self) -> list:
        '''Returns a list of FLAG_COUNT bools, flag 0 first.'''
        d = self.get_register(self.REG_D_ADDR)
        bits = int.from_bytes(d.get_bytes(), "big")
        binary = format(bits, f"0{self.FLAG_COUNT}b")
        return [c == "1" for c in binary]

    # -- Program memory: the "global chain" of END lines and global alpha
    # labels, see docs/program.md sec 5 for the full derivation ----------
    #
    # Register offset and absolute address run in *opposite* directions
    # within a register (offset 0 = the first/leftmost printed byte = the
    # *highest* address in that register; offset 6 = the last/rightmost
    # byte = the *lowest*) -- see docs/program.md's "Addressing within
    # program memory". _addr_for/_pos_for convert between the two; every
    # chain-distance calculation below goes through them.

    @staticmethod
    def _addr_for(reg: int, offset: int) -> int:
        return 7 * reg + (6 - offset)

    @staticmethod
    def _pos_for(addr: int) -> tuple:
        reg, remainder = divmod(addr, 7)
        return reg, 6 - remainder

    def _read_bytes_forward(self, reg: int, offset: int, count: int) -> bytes:
        '''Reads `count` bytes starting at (reg, offset) in the direction
        chain markers and global-label names read correctly in (increasing
        program line number / decreasing address -- see docs/program.md).
        Running past offset 6 continues at offset 0 of the next LOWER
        register, matching how program memory actually continues across a
        register boundary.'''
        out = bytearray()
        r, o = reg, offset
        for _ in range(count):
            out.append(self.get_register(r).get_bytes()[o])
            o += 1
            if o > 6:
                o = 0
                r -= 1
        return bytes(out)

    def _write_bytes_forward(self, addr: int, data: bytes):
        '''Writes `data` starting at absolute byte-address `addr`,
        continuing in the same forward/decreasing-address direction
        `_read_bytes_forward()` reads in (and crossing register
        boundaries the same way) -- the write-side counterpart used by
        `import_program()` to splice a program's bytes into program
        memory. Each byte is its own register read-modify-write, same
        granularity as `_write_program_key_byte()` already uses below.'''
        reg, offset = self._pos_for(addr)
        for byte in data:
            reg_data = bytearray(self.get_register(reg).get_bytes())
            reg_data[offset] = byte
            self.set_register(reg, Register(data=bytes(reg_data)))
            offset += 1
            if offset > 6:
                offset = 0
                reg -= 1

    def _decode_chain_marker(self, reg: int, offset: int) -> Optional[dict]:
        '''Decodes the 3-byte '1100 bbb rrrrrrrrr eeeeffff' marker at
        (reg, offset) -- docs/program.md sec 5.1. Returns None if the byte
        at (reg, offset) doesn't start with the 0xC0-0xCD marker nibble.'''
        raw = self._read_bytes_forward(reg, offset, 3)
        if (raw[0] >> 4) != 0xC:
            return None
        val = (raw[0] << 16) | (raw[1] << 8) | raw[2]
        is_label = (raw[2] >> 4) == 0xF
        return {
            "bbb": (val >> 17) & 0x7,
            "distance_registers": (val >> 8) & 0x1FF,
            "is_label": is_label,
            # High nibble of the third byte, when this isn't a label: 0 =
            # normal END, 2 = the permanent `.END.` itself (docs/program.md
            # sec 5.1). None for a label, where that nibble is always F.
            "end_type": None if is_label else (raw[2] >> 4),
            "label_length": (raw[2] & 0x0F) - 1 if is_label else None,
        }

    def _decode_label_name(self, reg: int, offset: int, length: int) -> tuple:
        '''Decodes a global label's key-assignment byte and name, given
        where its 4-byte header starts -- docs/program.md sec 5.2. Reading
        the header and name in one continuous forward pass (rather than as
        two separate reads) is what makes a name longer than 3 characters
        correctly spill into the preceding register: `_read_bytes_forward`
        only wraps registers within a single call. Returns
        (name, key_assignment).'''
        combined = self._read_bytes_forward(reg, offset, 4 + max(length, 0))
        key_assignment = combined[3]
        name = "".join(
            chr(b) if 0x20 <= b <= 0x7E else "?" for b in combined[4:]
        )
        return name, key_assignment

    def list_global_chain(self) -> list:
        '''
        Walks the global chain backward from `.END.` toward R00 and
        returns every global alpha label and plain END marker found along
        the way, oldest first -- the register nearest R00 is the first
        chain link ever created, matching the order CAT 1 shows on a real
        calculator. See docs/program.md sec 5 for the derivation and the
        worked examples this was checked against (every
        `src/tests/data/*.dm41` sample that has any programs in it).

        Each entry is one independent chain link (see ProgramInfo) -- do
        NOT assume labels and END markers pair up one-to-one, and do NOT
        assume consecutive entries belong to different programs. The
        user's own testing (against a modified copy of 6x-xm.dm41) found a
        single END can have zero, one, or several global labels chained to
        it, so this makes no attempt to group entries into "programs"; it
        just reports the raw chain in the order it's found, same as CAT 1
        would list it. For the grouped, "one row per real program" view --
        the one the Program tab and program export actually use -- see
        `list_programs()` below and docs/program.md sec 5.3. This method
        is still what key-assignment code (`_find_program_by_name()` and
        friends) uses, since a key assignment lives on one label's own
        header regardless of how many labels its program has.

        Returns [] if program memory is empty, or if R00/.END. don't look
        like a real partition (e.g. a fresh, never-loaded Memory()). The
        permanent `.END.` marker itself is otherwise included as the last
        (newest) entry -- see ProgramInfo's docstring -- unless it truly
        has nothing chained to it yet (see docs/program.md's first worked
        example), in which case there's nothing to report at all.

        Stops -- without raising -- the moment a byte that should start a
        marker doesn't have the 0xC0-0xCD high nibble, since that means
        either this model doesn't fit this dump or the data is corrupt;
        better to show whatever was found up to that point than to crash
        the caller. Also bounded to a generous iteration cap, and guards
        against revisiting the same position, as a backstop against an
        accidentally circular chain.
        '''
        r00 = self.R00()
        dend = self.DotEnd()
        # MIN_SANE_R00 -- a fresh, never-loaded Memory() decodes R00 as 0,
        # which isn't a real partition boundary.
        if not (MIN_SANE_R00 <= r00 <= PRIMARY_DATA_END) or not (
            KEY_ASSIGNMENTS_RANGE[0] <= dend < r00
        ):
            return []

        entries = []
        reg, offset = dend, 4
        visited = set()
        for _ in range(512):
            if (reg, offset) in visited:
                break
            visited.add((reg, offset))

            marker = self._decode_chain_marker(reg, offset)
            if marker is None:
                break

            # The byte distance THIS entry's own marker reports onward to
            # the next chain link the walk visits from here -- see
            # ProgramInfo's docstring for why this is exposed raw rather
            # than interpreted as a program size.
            distance_bytes = marker["distance_registers"] * 7 + marker["bbb"]

            if marker["is_label"]:
                name, key = self._decode_label_name(
                    reg, offset, marker["label_length"]
                )
                entries.append((
                    reg, offset, name, key,
                    distance_bytes, marker["bbb"], marker["distance_registers"],
                    None,
                ))
            else:
                # The very first marker examined is always this partition's
                # permanent `.END.` (it's where the walk starts). Only skip
                # recording it when program memory is genuinely empty --
                # i.e. it has no predecessor of its own (bbb/distance_regs
                # both 0) -- since then it's not really a chain link, just
                # an empty partition's bookkeeping. Whenever it DOES have a
                # predecessor, it's a real, informative entry: it's the
                # newest thing in memory, and its own distance can account
                # for bytes CAT 1 counts as part of the newest program that
                # a plain-END-only view would otherwise miss entirely (see
                # ProgramInfo's docstring -- this was found by the user
                # comparing this tab's output against a real CAT 1 listing).
                is_empty_partition_marker = (
                    len(entries) == 0
                    and marker["end_type"] == 2
                    and marker["bbb"] == 0
                    and marker["distance_registers"] == 0
                )
                if not is_empty_partition_marker:
                    entries.append((
                        reg, offset, None, None,
                        distance_bytes, marker["bbb"], marker["distance_registers"],
                        marker["end_type"],
                    ))

            if marker["bbb"] == 0 and marker["distance_registers"] == 0:
                break  # no predecessor -- first global line in memory

            addr = self._addr_for(reg, offset)
            target_addr = addr + distance_bytes
            if target_addr <= addr:
                break  # defensive: distance should never be non-positive
            next_reg, next_offset = self._pos_for(target_addr)
            if next_reg >= r00 or next_reg < 0xC0:
                break  # defensive: shouldn't walk past R00 or below 0xC0
            reg, offset = next_reg, next_offset

        programs = [
            ProgramInfo(
                header_addr=r, header_offset=o, name=n, key_assignment=k,
                distance_bytes=d, bbb=b, distance_registers=dr, end_type=et,
            )
            for r, o, n, k, d, b, dr, et in entries
        ]
        programs.reverse()
        return programs

    def _program_memory_top_addr(self) -> int:
        '''Address just below R00 -- the top of program memory, where the
        very first program ever written begins (see docs/program.md's
        "Addressing within program memory"). R00 itself belongs to the
        free/data-register side of the partition, not to program memory.'''
        return self._addr_for(self.R00() - 1, 0)

    def list_programs(self) -> list:
        '''
        Groups `list_global_chain()`'s raw chain into real, END-delimited
        programs -- one `Program` per program CAT 1 would show, oldest
        first. See docs/program.md sec 5.3 for the full derivation; this
        replaces an earlier version of this method (see
        `list_global_chain()`, and Program/ProgramInfo's docstrings) that
        conflated "one chain link" with "one program" and, separately, had
        a real bug: it could mistake register-alignment zero-padding
        before the permanent `.END.` marker for a small extra unnamed
        program. Both are fixed here, verified against the user's own
        real-hardware `CAT 1` comparisons on two purpose-built fixtures:

          - `tests/data/unlabelled.dm41`: two programs, NEITHER one named
            (one holds only an ALPHA string, the other only a local
            numbered label) -- `CAT 1` reports them as 16 and 20 bytes.
            The old code miscounted this as three programs (16, 20, and a
            phantom 6-byte one made of nothing but the zero-padding in
            front of `.END.`).
          - `tests/data/twolabels.dm41`: ONE program with TWO global
            labels ("FIRST" and "SECOND") and, notably, no explicit END
            at all -- only the permanent `.END.` terminates it, which is
            legal for the single newest program in memory (see `Program`'s
            docstring). `CAT 1` would show two catalog entries here (one
            per label) but they are the same underlying program.

        A program is delimited by an explicit plain END marker, never by
        a global label -- a program can have zero, one, or several labels
        (`Program.labels`), and per the second fixture above the single
        newest program in memory does not need an explicit END of its own
        at all; the permanent `.END.` sentinel can close it out instead.
        Every OLDER program, by construction, must have a real END, since
        nothing else could have closed it while a newer one was added
        after it.

        Walking the chain oldest to newest: every LBL entry is added to
        the label list for whatever program is currently being
        accumulated. Every plain END entry (`end_type == 0`) always closes
        a real program -- its length is computed directly from the
        address arithmetic already validated for the chain itself (no
        byte-by-byte opcode scanning needed: the chain's own marker
        position already tells us exactly where this program's terminator
        sits), and a fresh, empty label list starts for whatever comes
        next. The permanent `.END.` entry (`end_type == 2`) is always
        last, and is handled specially, since it plays two different
        roles depending on what precedes it:

          - If any labels have been accumulated since the last explicit
            END (or since the top of program memory, if there's been none
            yet) -- as in `twolabels.dm41` -- `.END.` is genuinely this
            program's own terminator, and everything from the oldest of
            those labels' own header through `.END.`'s own bytes is one
            real program.
          - Otherwise (no labels pending), check whether the bytes between
            wherever the last real program left off and `.END.`'s own
            marker are ALL zero. If so, that gap is nothing but the
            register-alignment padding described above -- not a program,
            not even an empty one -- and is dropped entirely (this is
            what fixes the `unlabelled.dm41` miscount). If the gap
            contains any non-zero byte, it's a real final program with no
            label of its own at all (an HP-41 program doesn't require
            one, confirmed against tests/data/tower.txt, which opens with
            a local "LBL 21" instead of a global one) -- `.END.` closes
            that program too, same as the labeled case.

        Returns [] if `list_global_chain()` does (empty or not-yet-real
        program memory).
        '''
        chain = self.list_global_chain()
        if not chain:
            return []

        programs = []
        pending_labels = []
        group_start_addr = self._program_memory_top_addr()

        for entry in chain:
            marker_addr = self._addr_for(entry.header_addr, entry.header_offset)

            if entry.is_named:
                pending_labels.append(ProgramLabel(
                    name=entry.name,
                    key_assignment=entry.key_assignment,
                    header_addr=entry.header_addr,
                    header_offset=entry.header_offset,
                ))
                continue

            marker_last_byte_addr = marker_addr - 2  # 3-byte marker
            length = group_start_addr - marker_last_byte_addr + 1

            if entry.end_type == 2:
                # The permanent .END. -- always the last entry examined.
                gap = length - 3
                if not pending_labels and not self._has_nonzero_bytes(
                    group_start_addr, gap
                ):
                    break  # pure padding -- not a program, nothing to add
            start_reg, start_offset = self._pos_for(group_start_addr)
            programs.append(Program(
                start_addr=start_reg,
                start_offset=start_offset,
                length=length,
                labels=pending_labels,
                terminator=".END." if entry.end_type == 2 else "END",
            ))
            pending_labels = []
            group_start_addr = marker_last_byte_addr - 1

        return programs

    def _has_nonzero_bytes(self, addr: int, count: int) -> bool:
        '''True if any of the `count` bytes forward from `addr` (same
        addressing convention as `_read_bytes_forward`) is non-zero.
        `count <= 0` is trivially False -- used by `list_programs()` to
        tell real (if unnamed) trailing program content apart from mere
        register-alignment padding before the permanent `.END.` marker.'''
        if count <= 0:
            return False
        reg, offset = self._pos_for(addr)
        return any(self._read_bytes_forward(reg, offset, count))

    def get_program_bytes(self, program: Program) -> bytes:
        '''
        Returns the raw instruction bytes for one real, END-delimited
        program (`list_programs()`) -- its own opcodes, in on-calculator
        reading order (decreasing address, see docs/program.md's
        "Addressing within program memory"), up to and including its own
        terminating marker (an explicit END, or the permanent `.END.` for
        the single newest program in memory -- see `Program`'s
        docstring). This is the byte sequence a program-file export
        (RAW/DAT/...) should contain -- see program_files.py.

        A named program (one with at least one global label) is not
        required for this to work: an HP-41 program can consist of
        nothing but local (numbered) labels, or no labels at all -- see
        `list_programs()`'s docstring for how such a program is told
        apart from mere register-alignment padding before `.END.`.
        Verified against docs/program.md's own worked APPTEST example (26
        bytes) and against the user's own real-hardware `CAT 1`
        comparison for tests/data/unlabelled.dm41 (16 and 20 bytes,
        neither program named) and tests/data/twolabels.dm41 (28 bytes,
        one program with two labels and no explicit END).

        A program with more than one global label (twolabels.dm41's case)
        is exported as the single physical block CAT 1's END-delimited
        view treats it as -- from its OLDEST label's own header through
        its own terminator -- not as separate slices per label.

        `length` was already computed directly from the global chain's
        own validated marker positions (see `list_programs()`); this
        re-reads exactly that many bytes and, as a defensive
        cross-check against corrupt data, confirms `find_program_end()`
        -- an independent forward opcode-stream scan (ported from
        hp41uc's seek_end(), see opcode_scan.py) -- agrees on exactly
        where those bytes end.

        Raises ValueError if `program` doesn't match any entry in the
        current program list (e.g. it's stale, from a `list_programs()`
        call before the dump changed).
        Raises DM41LMemoryError if `find_program_end()` disagrees with
        the chain-derived length -- signals corrupt data or a program
        that isn't well-formed HP-41 code.
        '''
        for candidate in self.list_programs():
            if (
                candidate.start_addr == program.start_addr
                and candidate.start_offset == program.start_offset
            ):
                instruction_bytes = self._read_bytes_forward(
                    candidate.start_addr, candidate.start_offset, candidate.length
                )
                if find_program_end(instruction_bytes) != candidate.length:
                    raise DM41LMemoryError(
                        f"Program {candidate.names_label!r}'s own bytes "
                        "don't form one well-formed HP-41 program (forward "
                        "opcode scan disagrees with the global chain) -- "
                        "the dump may be corrupt."
                    )
                return instruction_bytes
        raise ValueError(
            "This program entry doesn't match the current program list -- "
            "it may be stale (from a list_programs() call taken before "
            "the dump changed)."
        )

    def _convert_dot_end_to_real_end(self, entry: ProgramInfo):
        '''Rewrites the permanent `.END.` marker's own end-type nibble
        (docs/program.md sec 5.1's high `eeee` nibble) from `2` to `0` in
        place, at its existing (`entry.header_addr`, `entry.header_offset`)
        position -- turning it into a genuine closing `END` for whatever
        program it used to terminate, without touching its `bbb`/
        `distance_registers` fields (still correctly linking back to
        whatever preceded it -- see `import_program()`'s "Case A"). Used
        only when the program `.END.` used to terminate is no longer the
        newest thing in memory -- i.e. right before a fresh `.END.` gets
        written further down by `import_program()`.'''
        marker_addr = self._addr_for(entry.header_addr, entry.header_offset)
        third_byte_addr = marker_addr - 2
        reg, offset = self._pos_for(third_byte_addr)
        data = bytearray(self.get_register(reg).get_bytes())
        data[offset] &= 0x0F  # clear the high (end-type) nibble: 2 -> 0
        self.set_register(reg, Register(data=bytes(data)))

    def import_program(self, instruction_bytes: bytes) -> Program:
        '''
        Splices a standalone program's instruction bytes -- as produced by
        `get_program_bytes()` above, or by `decode_program_raw()`/
        `decode_program_dat()` (program_files.py) reading an external
        RAW/DAT file -- into this Memory's program memory as the newest
        program, updating the global chain (docs/program.md sec 5) and
        moving the permanent `.END.` sentinel so the result reads exactly
        like a program a real calculator wrote there itself. This is the
        write-side counterpart to `get_program_bytes()`; see that method
        and `program_files.py`'s module docstring for the read side, and
        `program_chain.py` for the byte-level chain parsing this leans on.

        Only ever appends as the newest program -- there's no "insert at
        an arbitrary position" here, matching the project's own scope
        decision that Import should be as low-risk as the data model
        allows (see project notes). Splicing anywhere else in the middle
        of an existing chain would need a fundamentally different (and
        much riskier) algorithm.

        **The algorithm**, in the order it runs:

        1. Confirm `instruction_bytes` is one well-formed program (
           `find_program_end()` agrees with its own length) -- the same
           cross-check `get_program_bytes()` already relies on.
        2. `program_chain.walk_chain()` finds every chain marker inside
           `instruction_bytes` -- its own trailing terminator, plus any
           internal global labels, backward-linked to each other exactly
           as `list_global_chain()` links live registers. Every one of
           these internal links is already correct and stays untouched;
           only the *outermost* one (`walk_chain()`'s last entry -- the
           one whose distance pointed outside `instruction_bytes` in its
           original source memory) needs a new distance computed, since
           the destination memory it's being copied into is a different
           place entirely.
        3. Block the import if any global label name found in step 2
           already exists somewhere in this memory's own global chain --
           see project notes for why duplicates are refused rather than
           silently created.
        4. Every label's own key-assignment byte (the header's 4th byte,
           docs/program.md sec 5.2) is zeroed (unassigned) in the copy
           about to be written -- an imported program shouldn't silently
           steal a key from whatever else already holds it in this
           buffer; the user can reassign it afterward (Key Assignments
           tab / `ASN`).
        5. Figure out where the new program goes and what its outermost
           marker's distance should now point back to:
           - If this memory has no programs at all yet, it starts at
             `_program_memory_top_addr()` and the outermost marker gets
             `bbb = distance_registers = 0` ("no predecessor" -- the
             chain's own way of saying "first program in memory").
           - Otherwise, the permanent `.END.` entry (`list_global_chain()`'s
             own last entry) is always the link point, but plays one of
             two roles depending on what `list_programs()` says about it
             (mirroring that method's own "Case A"/"Case B" split, see its
             docstring): if it was genuinely serving as the newest
             program's own terminator (pending label(s), or real
             unlabelled trailing content -- `twolabels.dm41`'s case),
             it's converted in place into a real closing `END`
             (`_convert_dot_end_to_real_end()`) and left as the new link
             target. Otherwise a real `END` already exists further up
             (`simple.dm41`'s case, where `.END.` is pure register-
             alignment padding) -- that untouched entry is the link
             target instead, and the padding-plus-`.END.` bytes below it
             are simply about to be overwritten by the new program's own
             content.
        6. If `instruction_bytes`' own trailing marker happens to be a
           `.END.`-type one itself (`end_type == 2` -- true when the
           program being imported was originally exported as the single
           newest, `.END.`-terminated program in *its* source memory,
           e.g. a `twolabels.dm41`-style export), it's forced to a normal
           closing `END` here too, in the copy -- it's not going to be the
           top of memory anymore once step 8 writes a fresh `.END.` below
           it.
        7. Enough free program memory to hold all of this (the program's
           own bytes, plus whatever zero-padding is needed to land the
           fresh `.END.` on a register boundary, plus its own 3 bytes)?
           If not, raises `DM41LMemoryError` rather than overwriting the
           Key Assignments/Alarms regions below it.
        8. Writes the (patched) instruction bytes into registers
           (`_write_bytes_forward()`), zero-pads up to the next register
           boundary (`.END.` is always found in the last 3 bytes of a
           register -- docs/program.md sec 5.1), writes a fresh `.END.`
           marker there linking back to the program's own trailing
           marker, and moves the `.END.` pointer (`set_DotEnd()`) to it.
           `R00()` is never touched -- growing into the Key
           Assignments/Alarms regions is refused outright (step 7) rather
           than silently reclaiming data-register space to make room.

        Returns the newly-imported `Program`, freshly re-read via
        `list_programs()` as a sanity check that the splice produced a
        well-formed chain (defensive -- mirrors `get_program_bytes()`'s
        own independent-verification habit).

        Raises `ValueError` if `instruction_bytes` isn't one well-formed
        program, or contains a global label name that already exists in
        this memory. Raises `DM41LMemoryError` if there's no valid R00/
        `.END.` partition loaded yet, if there isn't enough free program
        memory, or if the computed link distance doesn't fit the format's
        9-bit register-count field (a *very* large program landing right
        at the edge of addressable program memory).
        '''
        if not instruction_bytes:
            raise ValueError("Nothing to import -- the program is empty.")
        if find_program_end(instruction_bytes) != len(instruction_bytes):
            raise ValueError(
                "This doesn't decode as one well-formed HP-41 program -- "
                "find_program_end() disagrees with the file's own length."
            )
        if not (MIN_SANE_R00 <= self.R00() <= PRIMARY_DATA_END):
            raise DM41LMemoryError(
                "No valid program memory partition is loaded -- load or "
                "start a memory buffer first."
            )

        chain_entries = walk_chain(instruction_bytes)
        if not chain_entries:
            raise DM41LMemoryError(
                "Could not find a valid END/label marker in this "
                "program's own bytes -- it may be corrupt."
            )
        self._check_no_duplicate_labels(chain_entries)

        data = bytearray(instruction_bytes)

        # Step 4: zero every label's own key-assignment byte in the copy.
        for entry in chain_entries:
            if entry["is_label"]:
                data[entry["index"] + 3] = 0x00

        # Step 5: where this goes, and what the outermost marker should
        # now link back to. `dot_end_to_convert` records whether Case A
        # applies (see _resolve_import_link()'s docstring) -- nothing
        # touches a live register yet.
        insertion_addr, link_addr, dot_end_to_convert = self._resolve_import_link()

        # Step 6: force a copied `.END.`-type trailing marker to a real END.
        trailing = chain_entries[0]
        if not trailing["is_label"] and trailing["end_type"] == 2:
            data[trailing["index"] + 2] &= 0x0F

        # Step 2 (continued): recompute the outermost marker's own link.
        self._relink_outermost_marker(data, chain_entries[-1], insertion_addr, link_addr)

        # Step 7: is there room? This has to run -- and be allowed to
        # raise -- before anything below actually touches a live register
        # (including converting `.END.` in Case A), so a rejected import
        # leaves this Memory completely unchanged rather than partially
        # spliced.
        end_marker_addr, next_free_addr = self._check_import_room(insertion_addr, len(data))

        # Step 8: write it -- starting with the Case A conversion deferred
        # from step 5, now that every earlier check has passed.
        if dot_end_to_convert is not None:
            self._convert_dot_end_to_real_end(dot_end_to_convert)
        self._write_bytes_forward(insertion_addr, bytes(data))
        padding = next_free_addr - end_marker_addr
        if padding > 0:
            self._write_bytes_forward(next_free_addr, bytes(padding))

        trailing_dest_addr = insertion_addr - trailing["index"]
        end_dr, end_bbb = divmod(trailing_dest_addr - end_marker_addr, 7)
        end_marker_bytes = encode_chain_marker(end_bbb, end_dr, 0x20)
        self._write_bytes_forward(end_marker_addr, end_marker_bytes)

        new_dot_end_reg, _ = self._pos_for(end_marker_addr)
        self.set_DotEnd(new_dot_end_reg)

        programs = self.list_programs()
        if not programs or programs[-1].length != len(instruction_bytes):
            raise DM41LMemoryError(
                "Import produced an inconsistent program chain -- this "
                "looks like a bug, please report it."
            )
        return programs[-1]

    def _check_no_duplicate_labels(self, chain_entries: list):
        '''Raises ValueError if any global label name found by
        `walk_chain()` (in a program about to be imported) already exists
        somewhere in this memory's own global chain -- see
        `import_program()`'s step 3.'''
        existing_names = {p.name for p in self.list_global_chain() if p.is_named}
        for entry in chain_entries:
            if entry["is_label"] and entry["name"] in existing_names:
                raise ValueError(
                    f"A global label named {entry['name']!r} already exists "
                    "in this memory -- rename or delete the existing "
                    "program before importing this one."
                )

    def _resolve_import_link(self) -> tuple:
        '''
        `import_program()`'s step 5: figures out where a new program
        should be written (the highest address it can start at) and what
        its outermost marker's distance should now point back to.

        Returns `(insertion_addr, link_addr, dot_end_to_convert)`:
        - `insertion_addr`: the highest address the new program's own
          first byte can occupy.
        - `link_addr`: the address the new program's outermost marker
          should now link back to, or `None` if this memory has no
          programs at all yet (the new marker gets `bbb =
          distance_registers = 0`, "no predecessor").
        - `dot_end_to_convert`: the permanent `.END.` `ProgramInfo` to
          convert into a real closing `END` (Case A -- see
          `_convert_dot_end_to_real_end()`), or `None` if no conversion
          is needed (Case B, or no existing programs at all). Deliberately
          not converted here -- see `import_program()`'s own comment on
          why that has to wait until after the room check.

        Raises `DM41LMemoryError` if this memory's program chain is
        non-empty but doesn't resolve to any real program at all (would
        only happen for corrupt data -- see `list_programs()`'s
        docstring).
        '''
        chain = self.list_global_chain()
        if not chain:
            return self._program_memory_top_addr(), None, None

        boundary = chain[-1]  # always the permanent .END. entry
        programs = self.list_programs()
        if not programs:
            raise DM41LMemoryError(
                "This memory's program chain doesn't resolve to any "
                "real program -- it may be corrupt."
            )
        if programs[-1].terminator == ".END.":
            # Case A: `.END.` was genuinely serving as the newest
            # program's own terminator -- it'll be converted in place
            # into a real closing END (its own link, unchanged, is still
            # valid) and used as the new link target.
            link_entry = boundary
            dot_end_to_convert = boundary
        else:
            # Case B: a real END already exists further up; `.END.`
            # itself (plus any padding before it) is pure register-
            # alignment filler about to be overwritten.
            link_entry = chain[-2]
            dot_end_to_convert = None

        link_addr = self._addr_for(link_entry.header_addr, link_entry.header_offset)
        insertion_addr = link_addr - 2 - 1  # one below the link marker's own last byte
        return insertion_addr, link_addr, dot_end_to_convert

    @staticmethod
    def _relink_outermost_marker(
        data: bytearray, outermost: dict, insertion_addr: int, link_addr: Optional[int]
    ):
        '''`import_program()`'s step 2 finish: overwrites `outermost`'s
        `bbb`/`distance_registers` fields in `data` (in place) so it
        correctly links back to `link_addr` once `data` is written
        starting at `insertion_addr` -- or to "no predecessor" (`bbb =
        distance_registers = 0`) if `link_addr` is `None` (this is the
        first program in memory). Its own third byte is preserved as-is.
        Raises `DM41LMemoryError` if the computed distance doesn't fit
        the format's 9-bit register-count field.'''
        if link_addr is None:
            new_bbb, new_dr = 0, 0
        else:
            outermost_dest_addr = insertion_addr - outermost["index"]
            new_dr, new_bbb = divmod(link_addr - outermost_dest_addr, 7)
            if new_dr > 0x1FF:
                raise DM41LMemoryError(
                    "This program lands too far from the existing program "
                    "chain to encode -- program memory may be unusually "
                    "large or fragmented."
                )
        index = outermost["index"]
        third = data[index + 2]
        data[index : index + 3] = encode_chain_marker(new_bbb, new_dr, third)

    def _check_import_room(self, insertion_addr: int, data_len: int) -> tuple:
        '''`import_program()`'s step 7: works out where the fresh `.END.`
        marker would land -- register-aligned to the last 3 bytes of a
        register, right after `data_len` bytes written starting at
        `insertion_addr` and however much zero-padding gets it to that
        boundary -- and checks that against the Alarms/Key Assignments
        boundary (`alarms_end()`). Returns `(end_marker_addr,
        next_free_addr)` if there's room; raises `DM41LMemoryError` if
        not.'''
        program_end_addr = insertion_addr - data_len + 1
        next_free_addr = program_end_addr - 1
        end_marker_addr = next_free_addr - ((next_free_addr - 2) % 7)
        end_marker_last_addr = end_marker_addr - 2
        end_marker_reg, _ = self._pos_for(end_marker_last_addr)
        if end_marker_reg < self.alarms_end():
            lowest_free_addr = self._addr_for(self.alarms_end(), 6)
            available = insertion_addr - lowest_free_addr + 1
            needed = insertion_addr - end_marker_last_addr + 1
            raise DM41LMemoryError(
                f"Not enough free program memory to import this program "
                f"(needs {needed} bytes, only {max(available, 0)} available)."
            )
        return end_marker_addr, next_free_addr

    def _forward_scan_programs(self) -> list:
        '''
        Physically re-derives every program in program memory by scanning
        its raw opcodes forward -- from `_program_memory_top_addr()` (the
        oldest program's fixed starting point) down to `.END.`'s own
        floor (`self._addr_for(self.DotEnd(), 6)`) -- entirely independent
        of the existing backward chain-link ("backlink") fields
        `list_global_chain()`/`list_programs()` rely on. This is `pack()`'s
        primary job (below), per the user's own real-hardware
        investigation (project notes,
        `pack_anomaly_investigation_2026-08-24.md`): a dump written by a
        tool other than a real HP-41/DM41L (or this app) can leave those
        backlinks zeroed or simply never set, even though real,
        well-formed FOCAL code sits right there in the raw bytes --
        `list_global_chain()` then reports no programs at all, and no
        global label in that memory can be viewed, exported, or assigned
        to a key, even though it is genuinely present. This is real
        PACK's actual documented job: walk the opcodes forward and
        rebuild the chain from scratch, the same way
        `scan_global_markers_forward()` (opcode_scan.py) does.

        Trusts `R00()`/`DotEnd()` themselves as sane boundary pointers --
        confirmed by the user's own investigation to remain correct even
        when the chain *inside* that span is broken -- but nothing about
        the marker bytes within that span, including a marker's own
        distance/`bbb` fields, its end-type nibble, or whether `.END.`
        itself decodes at all.

        Because `import_program()` (used by `_rebuild_program_memory()`
        below to actually re-splice each program found here) itself
        trusts `program_chain.walk_chain()` to find every *embedded*
        label within one program's own bytes -- which depends on exactly
        the same backlink fields that may be broken, not just for the
        outermost link but for any internal one -- this does not just
        slice out each program's bytes unchanged. It first rewrites every
        marker's own `bbb`/`distance_registers` fields, in a local
        working copy, to the true physical gap back to whichever marker
        `scan_global_markers_forward()` found immediately before it (0
        for the very first marker in the whole span -- "no predecessor",
        the same convention `_resolve_import_link()` uses for an empty
        memory). Only then are the (now internally self-consistent)
        per-program byte ranges sliced out. A marker's own third byte
        (end-type, or a label's length-plus-key-length byte, docs/
        program.md sec 5.1/5.2) is never touched -- only its link.

        Returns a list of `(instruction_bytes, key_assignments)` tuples,
        oldest program first -- the same shape `pack()`/`remove_program()`
        already pass to `_rebuild_program_memory()` -- or `[]` if program
        memory holds nothing at all, or if R00/`.END.` do not look like a
        real partition yet (matching `list_global_chain()`'s own guard).

        Raises `DM41LMemoryError` if the scan cannot safely determine
        where real content ends: if real (non-zero) bytes are found but
        no marker at all could be located in them, if the very last
        marker found is a label with nothing closing it, or if non-zero
        bytes remain between the last marker found and `DotEnd()`'s own
        floor. Any of these mean the scan cannot be sure it has found
        every real program without risking silently dropping one --
        matching this project's existing preference (see
        `get_program_bytes()`, `import_program()`) for raising over
        guessing when a dump does not look well-formed.
        '''
        r00 = self.R00()
        dend = self.DotEnd()
        if not (MIN_SANE_R00 <= r00 <= PRIMARY_DATA_END) or not (
            KEY_ASSIGNMENTS_RANGE[0] <= dend < r00
        ):
            return []

        top_addr = self._addr_for(r00 - 1, 0)
        floor_addr = self._addr_for(dend, 6)
        top_reg, top_offset = self._pos_for(top_addr)
        data = bytearray(
            self._read_bytes_forward(top_reg, top_offset, top_addr - floor_addr + 1)
        )

        markers = scan_global_markers_forward(bytes(data))
        if not markers:
            if any(data):
                raise DM41LMemoryError(
                    "Program memory contains data, but no recognizable "
                    "global chain marker (a label or END) could be found "
                    "in it -- pack() can't safely determine where a "
                    "program boundary is."
                )
            return []

        last_marker = markers[-1]
        if last_marker["is_label"]:
            raise DM41LMemoryError(
                "Program memory ends with a global label that's never "
                "closed by an END -- pack() can't safely determine where "
                "that program ends."
            )
        tail_start = last_marker["index"] + 3
        if any(data[tail_start:]):
            raise DM41LMemoryError(
                "Program memory has unrecognized data after its last "
                "global chain marker -- pack() can't safely determine "
                "where program memory's real boundary is."
            )

        # Repair every marker's own link, in a local working copy, to the
        # true physical gap back to whichever marker was found just
        # before it -- see docstring. Nothing here touches a live
        # register; _rebuild_program_memory() does that once these byte
        # ranges are re-imported.
        for i, marker in enumerate(markers):
            distance_bytes = (
                0 if i == 0 else marker["index"] - markers[i - 1]["index"]
            )
            distance_registers, bbb = divmod(distance_bytes, 7)
            if distance_registers > 0x1FF:
                raise DM41LMemoryError(
                    "Two global chain markers are too far apart to "
                    "re-link -- program memory may be unusually large or "
                    "fragmented."
                )
            start = marker["index"]
            data[start : start + 3] = encode_chain_marker(
                bbb, distance_registers, marker["third_byte"]
            )

        programs = []
        pending_labels = []
        group_start_index = 0

        for marker in markers:
            if marker["is_label"]:
                pending_labels.append((marker["name"], marker["key_assignment"]))
                continue

            marker_last_byte_index = marker["index"] + 2
            if (
                marker is last_marker
                and not pending_labels
                and not any(data[group_start_index : marker["index"]])
            ):
                break  # pure register-alignment padding -- not a program

            instruction_bytes = bytes(
                data[group_start_index : marker_last_byte_index + 1]
            )
            key_assignments = {name: key for name, key in pending_labels if key}
            programs.append((instruction_bytes, key_assignments))
            pending_labels = []
            group_start_index = marker_last_byte_index + 1

        return programs

    def _rebuild_program_memory(self, programs: list):
        '''
        Physically rewrites program memory from scratch so it exactly
        contains `programs` -- a list of `(instruction_bytes,
        key_assignments)` tuples, oldest program first (`key_assignments`
        is a `{label_name: key_byte}` dict, for that program's own labels
        that currently hold a real key assignment, i.e. `key_byte != 0`).
        Shared by `remove_program()` (called with every *other* existing
        program, physically closing the gap the removed one leaves
        behind) and `pack()` (called with every existing program,
        unchanged -- reclaims only incidental drift, e.g. from a
        hand-edited or externally-loaded dump).

        Every entry in `programs` is assumed to already be well-formed
        (each `instruction_bytes` came from this same Memory's own
        `get_program_bytes()`, captured by the caller *before* this
        method touches anything) and to contain no label name duplicated
        elsewhere in `programs` -- both guaranteed by construction, since
        these are exactly the programs that were already coexisting
        validly in this Memory before the call.

        First clears every register from `alarms_end()` up to (not
        including) `R00()` and resets `.END.` to `R00()` itself --
        `list_global_chain()`'s own definition of "no programs at all
        yet" (its `dend < r00` check) -- then re-`import_program()`s each
        entry in order. Reusing `import_program()` here, rather than
        re-deriving its splicing/linking arithmetic, is deliberate: it's
        already the thoroughly-tested single source of truth for "how
        does one program get spliced onto the current chain," and every
        program here is by definition importable (no duplicate names,
        each already well-formed, and the total result can only be
        smaller than or equal to what was already fitting in this same
        space before the call).

        `import_program()` always zeroes a freshly-spliced program's own
        label key-assignment bytes (it can't tell "this is a foreign
        import" from "this is the exact same program moving to a new
        address" -- see its own docstring, step 4); this method restores
        each label's original key-assignment byte immediately afterward
        instead, straight from the `key_assignments` dict passed in for
        it. The corresponding KEYFLAGS bits (sec 4.5) are never touched
        by any of this -- they live in a completely different register
        (`set_key_flag()`) -- so as long as they were already correct
        before this call, restoring the header byte alone is enough to
        leave a kept program's key assignment exactly as it was.
        '''
        for reg in range(self.alarms_end(), self.R00()):
            self.set_register(reg, Register(size=7))
        self.set_DotEnd(self.R00())

        for instruction_bytes, key_assignments in programs:
            imported = self.import_program(instruction_bytes)
            for label in imported.labels:
                key_byte = key_assignments.get(label.name)
                if key_byte:
                    self._write_program_key_byte(
                        label.header_addr, label.header_offset, key_byte
                    )

        if programs:
            self._collapse_trailing_end_into_dot_end()

    def _collapse_trailing_end_into_dot_end(self):
        '''
        `_rebuild_program_memory()`'s own best-effort cleanup pass: every
        call it makes to `import_program()` -- including the very last
        one, for the newest program being kept -- always writes a real,
        explicit END for whatever it just imported and then a *separate*,
        freshly written permanent `.END.` sentinel right after it (see
        `import_program()`'s own step 8; it has no way to know, on any
        given call, whether another program is about to be imported right
        after it). Left alone, that can leave the newest kept program
        genuinely `terminator == "END"` in `list_programs()`'s eyes,
        wasting up to a full register on a redundant second marker that
        the `Program`/`import_program()` docstrings' own stated invariant
        says shouldn't exist -- the single newest program in memory is
        supposed to be closed out by the permanent `.END.` sentinel
        directly, with no explicit END of its own.

        This collapses the two back into that canonical single-marker
        form -- but ONLY when it's actually safe to: `.END.` is only ever
        valid register-aligned, sitting in the last 3 bytes of whatever
        register `DotEnd()` names (docs/program.md sec 5.1), while an
        ordinary internal chain marker (what the last-imported program's
        own real END now is) can legally sit at any byte offset within
        its own register -- most of the time it won't happen to be
        exactly offset 4. When it IS (i.e. this program's own real END
        already happens to occupy the same 3 bytes a `.END.` marker would
        need), it's rewritten in place as the permanent `.END.` itself
        (only its end-type nibble changes -- its `bbb`/`distance_registers`
        fields already correctly link back to whatever precedes it and
        are left untouched), `.END.` is moved to point at it, and the now
        -superfluous separate sentinel above it (pure zero padding by
        construction) is zeroed out and reclaimed as free space. This is
        exactly what recovers `twolabels.dm41`-style dumps (a single
        program with no explicit END of its own, terminated only by
        `.END.`) back to their original, maximally-compact layout after a
        `pack()` that changed nothing else about them.

        When it's NOT offset-4-aligned, this leaves memory exactly as
        `import_program()` itself already produces it -- correct, just
        not maximally compact, the same tradeoff every single call to
        that method already makes and that the rest of this project
        already accepts (see e.g. `test_import_apptest_into_empty_memory
        _matches_simple_dm41_exactly()`, which only round-trips exactly
        because APPTEST happens to already be offset-4-aligned).

        Only ever called when `_rebuild_program_memory()` actually
        imported at least one program -- with none, `.END.` is already
        sitting at `R00()` (no separate sentinel was ever written) and
        there is nothing to collapse.
        '''
        chain = self.list_global_chain()
        sentinel = chain[-1]  # the fresh, empty .END. just written
        sentinel_addr = self._addr_for(sentinel.header_addr, sentinel.header_offset)
        target_addr = sentinel_addr + sentinel.distance_bytes
        pred_reg, pred_offset = self._pos_for(target_addr)
        if pred_offset != 4:
            return  # not register-aligned -- can't collapse without moving bytes

        third_byte_addr = self._addr_for(pred_reg, pred_offset) - 2
        reg, offset = self._pos_for(third_byte_addr)
        data = bytearray(self.get_register(reg).get_bytes())
        data[offset] = (data[offset] & 0x0F) | 0x20  # end-type nibble -> 2 (.END.)
        self.set_register(reg, Register(data=bytes(data)))

        old_dot_end_reg = self.DotEnd()
        self.set_DotEnd(pred_reg)
        for stale in range(pred_reg + 1, old_dot_end_reg + 1):
            self.set_register(stale, Register(size=7))

    def remove_program(self, program: Program):
        '''
        Removes `program` from program memory entirely and closes up the
        gap it leaves behind, so every remaining program stays exactly as
        contiguous as it was before -- the write-side counterpart to
        `get_program_bytes()`/`import_program()`, and this project's
        answer to GitHub issue #6 ("add the ability to remove programs";
        Import/Export already covered "add"/"edit").

        Removing anything other than the single newest program
        (`is_last`) is not simply "erase these bytes": every OLDER
        program sits at a fixed, unmovable address (the oldest one
        always starts exactly at `_program_memory_top_addr()`, right
        below `R00()` -- see that method's docstring), so deleting one
        from the middle (or the very oldest one) would otherwise leave a
        hole of genuinely unreachable register space wedged between
        `R00()` and whatever programs remain above it -- space
        `regions()`'s own "Unused / Free" accounting would never see,
        since it only ever looks at the gap between `alarms_end()` and
        `.END.`. This reclaims that space by rebuilding the entire
        program area from scratch, keeping everything except `program`
        (`_rebuild_program_memory()`).

        Also clears the KEYFLAGS bit (sec 4.5) for any of `program`'s own
        labels that currently hold a key assignment (sec 4.6) -- once its
        header is gone, `get_program_for_key()` can never find it there
        again, so leaving the flag set would misreport that key as still
        assigned to something. Key Assignment Register entries (sec 4.1
        -- the *other* storage mechanism, see `set_key_assignment()`) are
        completely unrelated to any program and are left untouched.

        Raises ValueError if `program` doesn't match any entry in the
        current program list (e.g. it's stale, from a `list_programs()`
        call taken before the dump changed) -- same defensive check as
        `get_program_bytes()`.
        '''
        programs = self.list_programs()
        match = next(
            (
                p for p in programs
                if p.start_addr == program.start_addr
                and p.start_offset == program.start_offset
            ),
            None,
        )
        if match is None:
            raise ValueError(
                "This program entry doesn't match the current program "
                "list -- it may be stale (from a list_programs() call "
                "taken before the dump changed)."
            )

        for label in match.labels:
            if label.key_assignment:
                try:
                    key_number, shifted = self._key_number_for_byte(
                        label.key_assignment
                    )
                    self.set_key_flag(key_number, shifted, False)
                except ValueError:
                    pass  # didn't decode to a real key position

        keep = []
        for p in programs:
            if p is match:
                continue
            raw = self.get_program_bytes(p)
            key_assignments = {
                l.name: l.key_assignment for l in p.labels if l.key_assignment
            }
            keep.append((raw, key_assignments))

        self._rebuild_program_memory(keep)

    def pack(self) -> int:
        '''
        Explicitly repacks user memory -- GitHub issue #31 ("DM41L_Explorer
        needs PACK functionality"). Key Assignments (sec 4) and Alarms
        (sec 3/4, docs/alarms.md) already stay perfectly packed as a side
        effect of every one of this class's own
        `set_key_assignment()`/`delete_key_assignment()` calls (see
        `_encode_key_assignment_entries()`'s docstring) -- this re-runs
        that same canonical repack explicitly, which is a no-op for a
        dump this class has only ever edited itself, but self-heals one
        loaded from disk with a pre-existing gap (e.g. a real
        calculator's own dump, or one hand-edited outside this app).

        Program memory (docs/program.md sec 5) gets more than a repack:
        per the user's own correction to this method's first version,
        packing has to *rebuild* the global chain, not just compact
        whatever it already recognizes -- `_forward_scan_programs()`
        walks the raw opcodes forward, entirely independent of the
        existing (possibly zeroed, possibly never-set) backward chain-
        link fields, so a global label that's physically present but not
        currently chain-linked -- confirmed on real hardware, see project
        notes `pack_anomaly_investigation_2026-08-24.md` -- becomes
        visible again via `list_programs()`/`list_global_chain()`, and
        assignable to a key, exactly like this method's issue asked for
        ("manually walking program memory to identify labels"). Every
        program found is then rewritten back tightly against `R00()`
        with `_rebuild_program_memory()`, reclaiming any accumulated
        register-alignment drift the same way `remove_program()` does for
        the program it deletes.

        Meant to be run explicitly before an Import (the issue's own
        suggested use) to guarantee the maximum possible free space is
        available for it, and to make sure every label actually present
        is visible for assignment -- this project deliberately doesn't
        run it automatically on every edit, so what's in memory always
        matches exactly what the user last loaded or changed until they
        ask for this.

        Returns the number of additional registers now free as a result
        (the change in `DotEnd() - alarms_end()`) -- 0 if nothing needed
        packing. Safe to call on a buffer with no programs at all (still
        repacks Key Assignments/Alarms; program memory is left untouched
        rather than guessing at a DotEnd for an empty partition this
        method did not create).

        Raises `DM41LMemoryError` if `_forward_scan_programs()` cannot
        safely determine program memory's real content -- see that
        method's own docstring for exactly when that happens. This
        method makes no changes at all if that happens: the scan runs,
        and can raise, before anything about program memory is touched.
        '''
        before_free = self.DotEnd() - self.alarms_end()

        self._encode_key_assignment_entries(self._decode_key_assignment_entries())

        keep = self._forward_scan_programs()
        if keep:
            self._rebuild_program_memory(keep)

        after_free = self.DotEnd() - self.alarms_end()
        return after_free - before_free

    # -- Global label (program) key assignments (docs/key_assignments.md
    # sec 4.6) -- a completely separate storage mechanism from the Key
    # Assignment Registers above (sec 4.2): the key byte lives in the
    # program's own global-label header (ProgramInfo.key_assignment, the
    # 4th header byte, docs/program.md sec 5.2) rather than in a shared
    # buffer. A label's header has room for exactly one key byte, so a
    # program can hold only one key assignment at a time -- unlike a
    # physical key, which has independent unshifted/shifted slots.

    def _find_program_by_name(self, name: str) -> Optional[ProgramInfo]:
        '''First named global label matching `name` (oldest-created, i.e.
        list_global_chain()'s own order, in the rare case of a duplicate
        name) -- shared by set_program_key_assignment()/
        clear_program_key_assignment()/get_program_for_key(). A key
        assignment lives on one label's own header (sec 4.6/5.2)
        regardless of how many labels its program has, so this works off
        the flat per-label chain, not the grouped `list_programs()`.'''
        for program in self.list_global_chain():
            if program.is_named and program.name == name:
                return program
        return None

    def _write_program_key_byte(self, header_addr: int, header_offset: int, value: int):
        '''Overwrites the key-assignment byte (the 4th byte, sec 4.2/5.2)
        of the global-label header starting at (header_addr,
        header_offset) -- the write-side counterpart to
        _decode_label_name() reading it. `_addr_for`/`_pos_for` convert to
        and from the linear address space so this doesn't need its own
        register-boundary-crossing loop (see _read_bytes_forward for why
        register offset and address run in opposite directions).'''
        reg, offset = self._pos_for(self._addr_for(header_addr, header_offset) - 3)
        data = bytearray(self.get_register(reg).get_bytes())
        data[offset] = value
        self.set_register(reg, Register(data=bytes(data)))

    def _clear_program_assignments_for_key_byte(
        self, key_byte: int, except_name: Optional[str] = None
    ):
        '''Writes 0x00 (unassigned) into the header of every global label
        currently holding `key_byte`, except one named `except_name` (used
        by set_program_key_assignment() while moving that program itself
        onto this key -- its own old byte is handled separately there).
        Does not touch KEYFLAGS -- callers own that, since the bit should
        usually end up set (by whatever new assignment is replacing these)
        rather than cleared.'''
        for program in self.list_global_chain():
            if (
                program.is_named
                and program.key_assignment == key_byte
                and program.name != except_name
            ):
                self._write_program_key_byte(program.header_addr, program.header_offset, 0x00)

    def get_program_for_key(self, key_number: int, shifted: bool) -> Optional[ProgramInfo]:
        '''Looks up the global label (if any) assigned to `key_number`/
        `shifted` via sec 4.6 -- the counterpart to get_key_assignment()
        for the other storage mechanism (sec 4.1). Per the real lookup
        order (sec 4.7), a Key Assignment Register entry on the same key
        always takes priority over a global-label one, but this method
        only checks global labels -- callers wanting "whatever's actually
        assigned to this key" should check get_key_assignment() first and
        fall back to this (see gui/key_assignments_tab.py).'''
        key_byte = self.key_byte_for(key_number, shifted)
        for program in self.list_global_chain():
            if program.is_named and program.key_assignment == key_byte:
                return program
        return None

    def set_program_key_assignment(self, name: str, key_number: int, shifted: bool):
        '''Assigns the global label `name` to `key_number`/`shifted` (sec
        4.6) -- `ASN "name" [key]` on a real calculator. Unlike
        set_key_assignment(), this never touches the Key Assignment
        Registers; it writes directly into the label's own header.

        Because that header holds only one key byte, reassigning a
        program that's already on a different key MOVES it here rather
        than creating a second assignment -- its previous key's KEYFLAGS
        bit is cleared as part of the move. This also enforces mutual
        exclusivity with the *other* storage mechanism on the target key:
        any existing Key Assignment Register entry there is removed, and
        any other program currently pointing at this key is cleared to
        unassigned -- the real lookup order (sec 4.7) means a Key
        Assignment Register entry would otherwise silently shadow a
        global-label one on the same key, so letting both exist at once
        would be misleading rather than a real dual assignment. Same
        silent-overwrite precedent as set_key_assignment().

        Raises ValueError if no global label named `name` exists.'''
        program = self._find_program_by_name(name)
        if program is None:
            raise ValueError(f"No global label named {name!r} found")

        key_byte = self.key_byte_for(key_number, shifted)

        # Moving this same program off whatever key it held before, if any
        # (0x00 means "never assigned" -- nothing to move off of).
        if program.key_assignment:
            try:
                old_key_number, old_shifted = self._key_number_for_byte(
                    program.key_assignment
                )
                self.set_key_flag(old_key_number, old_shifted, False)
            except ValueError:
                pass  # didn't decode to a real key position; nothing to clear

        # This key can only run one thing -- clear whatever else was there.
        self.delete_key_assignment(key_number, shifted)
        self._clear_program_assignments_for_key_byte(key_byte, except_name=name)

        self._write_program_key_byte(program.header_addr, program.header_offset, key_byte)
        self.set_key_flag(key_number, shifted, True)

    def clear_program_key_assignment(self, name: str):
        '''Removes global label `name`'s key assignment (sec 4.6), if it
        has one -- writes 0x00 back into its header and clears the
        corresponding KEYFLAGS bit. No-op if the label has no key
        assignment. Raises ValueError if no global label named `name`
        exists.'''
        program = self._find_program_by_name(name)
        if program is None:
            raise ValueError(f"No global label named {name!r} found")
        if not program.key_assignment:
            return
        try:
            key_number, shifted = self._key_number_for_byte(program.key_assignment)
            self.set_key_flag(key_number, shifted, False)
        except ValueError:
            pass
        self._write_program_key_byte(program.header_addr, program.header_offset, 0x00)

    def to_string(self) -> str:
        lines = [self._header]

        # Section II: Core Memory, grouped into complete 4-register pages.
        #
        # Every real captured dump (see tests/data/*.dm41) only ever
        # starts a row on a 4-register-aligned address (0x00, 0x04, 0x08,
        # ...) and always writes all 4 registers of that page -- whole
        # *pages* can be skipped entirely (e.g. the unused Void region),
        # but a page that has any register set is always written in
        # full. The DM41L's own loader appears to require this: it
        # rejected a dump with a row starting at a non-aligned address
        # (e.g. 0xba instead of 0xb8). So rather than grouping by
        # whatever runs of addresses happen to already be present in
        # _core_memory, group by aligned page and fill in any missing
        # register in a page that has at least one entry -- missing ones
        # default to the zero register, same as get_register() already
        # does for any address with no explicit entry.
        sorted_indices = sorted(self._core_memory.keys())
        if sorted_indices:
            pages = sorted({idx - (idx % 4) for idx in sorted_indices})
            for base_idx in pages:
                row = [f"{base_idx:02x}"]
                for offset in range(4):
                    row.append(self.get_register(base_idx + offset).get_hex())
                lines.append("  ".join(row))

        # Section III: Special Registers
        if self._special_registers:
            # These need to be emitted in the same order they first appeared.
            A = self._special_registers["A"].get_hex()
            B = self._special_registers["B"].get_hex()
            C = self._special_registers["C"].get_hex()
            lines.append(f"A: {A} B: {B} C: {C}")
            # S may not be present.
            S = self._special_registers.get("S", None)
            if S is not None:
                lines.append(f"S: {S.get_hex()}")
            M = self._special_registers["M"].get_hex()
            N = self._special_registers["N"].get_hex()
            G = self._special_registers["G"].get_hex()
            lines.append(f"M: {M} N: {N} G: {G}")

        return "\n".join(lines) + "\n"

    def to_file(self, path: Union[str, Path]):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_string())
