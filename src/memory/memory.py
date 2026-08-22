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

from .registers import Register
from .constants import (
    PRIMARY_DATA_END,
    KEY_ASSIGNMENTS_RANGE,
    STATUS_REGISTERS_RANGE,
    VOID_RANGE,
    XM_REGIONS,
    MIN_SANE_R00,
)
from .program_info import ProgramInfo
from .regions import RegionSpan
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
        list_programs()'s `key_assignment` field for those, per
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

    def list_programs(self) -> list:
        '''
        Walks the global chain backward from `.END.` toward R00 and
        returns every global alpha label and plain END marker found along
        the way, oldest first -- the register nearest R00 is the first
        chain link ever created, matching the order CAT 1 shows on a real
        calculator. See docs/program.md sec 5 for the derivation and the
        worked examples this was checked against (every
        `src/tests/data/*.dm41` sample that has any programs in it).

        Each entry is one independent chain link (see ProgramInfo) -- do
        NOT assume labels and END markers pair up one-to-one. The user's
        own testing (against a modified copy of 6x-xm.dm41) found a single
        END can have zero, one, or several global labels chained to it, so
        this makes no attempt to group entries into "programs"; it just
        reports the raw chain in the order it's found, same as CAT 1 would
        list it.

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
        list_programs()' own order, in the rare case of a duplicate name)
        -- shared by set_program_key_assignment()/
        clear_program_key_assignment()/get_program_for_key().'''
        for program in self.list_programs():
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
        for program in self.list_programs():
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
        for program in self.list_programs():
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
