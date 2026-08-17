"""
Memory: a complete DM41L memory dump -- parsing/serializing the dump
format, raw register access, and the higher-level accessors built on top
of it (R00/.END./SigmaReg, the 56 status flags, and the program-memory
global chain walk). See the memory package's __init__.py docstring for
the on-disk dump format overview.
"""

import re
from typing import Dict, Optional, Union
from pathlib import Path

from .registers import Register
from .constants import PRIMARY_DATA_END, KEY_ASSIGNMENTS_RANGE
from .program_info import ProgramInfo


class Memory:
    """A complete DM41L memory dump."""

    # Pattern to capture 'A:' followed by any hex string of 1 or more chars
    SPECIAL_PATTERN = re.compile(r"([A-Z]:\s*)([0-9a-fA-F]+)")

    # Status register addresses used by the R00/.END./Flags accessors below.
    REG_C_ADDR = 0x0D  # SREG / printer-use / cold-start / R00 / .END.
    REG_D_ADDR = 0x0E  # Flags
    FLAG_COUNT = 56

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

    # -- Register c (0x0D): SREG / printer-use / cold-start / R00 / .END. --
    #
    # Reverse-engineered from "A programmers handbook v.2.07.pdf" (its
    # "Status registers" diagram) and cross-checked against the R00/.END.
    # values implied by every src/tests/data/*.dm41 sample (e.g. R00 works
    # out to 0x19c -- 0x200-0x19c = 100 data registers, the default HP41
    # "SIZE 100" -- in most samples, and 0x180 -- 128 registers -- in
    # empty-128.dm41, matching its filename). All three address fields are
    # plain 3-nibble hex integers (not BCD), packed back-to-back with no
    # byte alignment across register c's 14 nibbles (nibble 0 = MSB,
    # matching Register._get_nibbles()):
    #   nibbles[0:3]   SREG  (ΣREG) absolute address
    #   nibbles[3:5]   printer use (undecoded)
    #   nibbles[5:8]   cold-start signature -- always 0x169 in real dumps,
    #                  usable as a sanity check
    #   nibbles[8:11]  R00   absolute address of data register 00
    #   nibbles[11:14] .END. absolute address of the end of program memory

    @staticmethod
    def _nibbles_to_int(nibbles) -> int:
        value = 0
        for n in nibbles:
            value = (value << 4) | n
        return value

    def _reg_c_nibbles(self) -> list:
        return self.get_register(self.REG_C_ADDR)._get_nibbles()

    def SigmaReg(self) -> int:
        """Absolute address of ΣREG, decoded from register c."""
        return self._nibbles_to_int(self._reg_c_nibbles()[0:3])

    def DotEnd(self) -> int:
        """Absolute address of the end of loaded program memory (".END.")."""
        return self._nibbles_to_int(self._reg_c_nibbles()[11:14])

    def R00(self) -> int:
        """
        Absolute address of data register 00 -- the boundary between
        program memory (below R00) and main data memory (R00 up to
        PRIMARY_DATA_END, inclusive).
        """
        return self._nibbles_to_int(self._reg_c_nibbles()[8:11])

    def set_R00(self, addr: int):
        """
        Directly rewrites the R00 pointer in register c.

        This only moves the partition marker -- it does NOT move, clear, or
        resize any actual register contents on either side of the new
        boundary, so moving it can expose stale program bytes as "data" (or
        hide real data registers behind the program-memory boundary).
        Callers that want a safe move should reconcile the affected
        registers themselves first.
        """
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
    # 0xF0 marker byte, followed by up to two 3-byte assignment entries
    # (function byte(s) + a key-designation byte). Reverse-engineered from
    # William C. Wickes' "Synthetic Programming on the HP-41C" (Section
    # 2E, "The Key Assignment Registers") and confirmed byte-for-byte
    # against a real 8-assignment dump -- see
    # docs/pdfs and the project's key-assignment research notes for the
    # full derivation. Alarms and genuinely free registers occupy the
    # remaining span up to .END.; telling those apart from each other
    # isn't implemented yet (see regions.py's Alarms class).

    def _scan_key_assignments_end(self) -> int:
        """Scans upward from KEY_ASSIGNMENTS_RANGE[0] (0xC0) for as long as
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
        """
        addr = KEY_ASSIGNMENTS_RANGE[0]
        while (
            addr <= PRIMARY_DATA_END
            and self.get_register(addr).get_bytes()[0] == 0xF0
        ):
            addr += 1
        return addr

    def key_assignments_end(self) -> int:
        """Address one past the last Key Assignments register, as of the
        last time this dump was loaded via from_string()/from_file() (see
        _scan_key_assignments_end()). KEY_ASSIGNMENTS_RANGE[0] (0xC0)
        itself if there are no key assignments.

        This is cached at load time rather than recomputed on every call
        (unlike R00()/DotEnd(), which are cheap single-register nibble
        reads) -- a set_register() call after loading, e.g. from an edit
        dialog, will NOT update this until the dump is reloaded.
        """
        return self._key_assignments_end

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
        """Returns a list of FLAG_COUNT bools, flag 0 first."""
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
        """Reads `count` bytes starting at (reg, offset) in the direction
        chain markers and global-label names read correctly in (increasing
        program line number / decreasing address -- see docs/program.md).
        Running past offset 6 continues at offset 0 of the next LOWER
        register, matching how program memory actually continues across a
        register boundary."""
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
        """Decodes the 3-byte '1100 bbb rrrrrrrrr eeeeffff' marker at
        (reg, offset) -- docs/program.md sec 5.1. Returns None if the byte
        at (reg, offset) doesn't start with the 0xC0-0xCD marker nibble."""
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
        """Decodes a global label's key-assignment byte and name, given
        where its 4-byte header starts -- docs/program.md sec 5.2. Reading
        the header and name in one continuous forward pass (rather than as
        two separate reads) is what makes a name longer than 3 characters
        correctly spill into the preceding register: `_read_bytes_forward`
        only wraps registers within a single call. Returns
        (name, key_assignment)."""
        combined = self._read_bytes_forward(reg, offset, 4 + max(length, 0))
        key_assignment = combined[3]
        name = "".join(
            chr(b) if 0x20 <= b <= 0x7E else "?" for b in combined[4:]
        )
        return name, key_assignment

    def list_programs(self) -> list:
        """
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
        """
        r00 = self.R00()
        dend = self.DotEnd()
        # 0xC1 matches gui/memory_ranges.py's MIN_SANE_R00 -- a fresh,
        # never-loaded Memory() decodes R00 as 0, which isn't a real
        # partition boundary.
        if not (0xC1 <= r00 <= PRIMARY_DATA_END) or not (0xC0 <= dend < r00):
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
