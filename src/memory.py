"""
A representation of the memory of a DM41 emulator.

The dump consists of three parts: the header ("DM41"), the dump of main
memory, and the "special registers" which I believe represent the emulated
HP41 CPU registers.

NOTE: The HP41C and DM41L are "little endian" - the LSB is considered to by
"byte 0" and the MSB is considered "byte 6" - but DM41L dump files print hex
data from MSB to LSB. That is, _data[0] contains the MSB of the register. and
_data[6] contains the LSB. Care must be taken to remember this difference when
comparing HP41 documentation with the implementation of the Register and
Memory classes.
"""

import re
import logging
from typing import Dict, Optional, Union
from pathlib import Path
from decimal import Decimal, Context, ROUND_HALF_EVEN

logger = logging.getLogger(__name__)

class MemoryError(ValueError):
    """
    Raised when a register in the data dump contains an illegal value.
    """

class Register:
    """
    Represents a hardware register with arbitrary byte length.

    Physical and emulated HP41 registers are always 7 bytes in length but,
    logically, some registers (such as the HP41 ALPHA register) are composed
    of parts of multiple physical registers. In addition, some status
    registers contain multiple smaller bitfields.
    """

    def __init__(
        self,
        data: bytes = None,
        size: int = 0,
        ascii_only: bool = False,
        read_only: bool = False,
    ):
        if data is not None:
            self._data = bytearray(data)
        else:
            self._data = bytearray(size)
        self.size = len(self._data)

        # These are "advisory" settings. ascii_only indicates that the
        # register is only intended for ascii data. read_only indicates that
        # the user should not manually alter the value (but the value can
        # still be altered by other operations, such as adjusting the size of
        # main memory, adding a program to program memory, and similar
        # operations.
        self.ascii_only = ascii_only
        self.read_only = read_only

    @classmethod
    def from_hex(cls, hex_str: str) -> "Register":
        clean_hex = hex_str.replace(" ", "")
        try:
            return cls(bytes.fromhex(clean_hex))
        except ValueError as e:
            raise ValueError(f"Invalid hexadecimal data: {e}") from e

    def get_hex(self) -> str:
        return self._data.hex()

    def _get_nibbles(self) -> list[int]:
        """Returns the register data as a list of nibbles from MSB to LSB."""
        nibbles = []
        for byte in self._data:
            nibbles.append((byte >> 4) & 0x0F)  # High nibble
            nibbles.append(byte & 0x0F)  # Low nibble
        return nibbles

    def get_bcd_number(self) -> float:
        """Reads the BCD-encoded number from this register."""
        if self.size != 7:
            raise ValueError(
                "BCD operations require a 7-byte register, " f"got {self.size} bytes."
            )

        nibbles = self._get_nibbles()

        # MS sign nibble at index 0. 1001=negative, 0000=positive.
        ms_nibble = nibbles[0]
        if ms_nibble == 9:
            ms_sign = -1
        elif ms_nibble == 0:
            ms_sign = 1
        else:
            raise ValueError(f"Invalid MS sign nibble: {hex(ms_nibble)}")

        # Mantissa extraction and validation (nibbles 1-10)
        mantissa_val = 0
        for i in range(1, 11):
            n = nibbles[i]
            if n < 0 or n > 9:
                raise ValueError(f"Invalid mantissa digit at nibble {i}: {hex(n)}")
            mantissa_val = mantissa_val * 10 + n

        # XS sign extraction and validation (nibble 11)
        xs_nibble = nibbles[11]
        if xs_nibble == 9:
            xs_sign = -1
        elif xs_nibble == 0:
            xs_sign = 1
        else:
            raise ValueError(f"Invalid XS sign nibble: {hex(xs_nibble)}")

        # Exponent extraction and validation (nibbles 12-13)
        e1 = nibbles[12]
        e2 = nibbles[13]
        if not (0 <= e1 <= 9 and 0 <= e2 <= 9):
            raise ValueError(f"Invalid exponent digits: {hex(e1)}, {hex(e2)}")

        exponent_val = e1 * 10 + e2

        # Apply the 100-X rule for negative exponents.
        # If xs_sign is negative, the stored exponent is 100 - |E|.
        if xs_sign == -1:
            total_exponent = -(100 - exponent_val)
        else:
            total_exponent = exponent_val

        # The stored exponent assumes the mantissa is d.ddddddddd (one digit
        # before the implied decimal point), so shift back by 9 to treat
        # mantissa_val as the plain 10-digit integer it actually is.
        return ms_sign * mantissa_val * (10 ** (total_exponent - 9))

    def set_bcd_number(self, number: float):
        """Writes a float to this register in BCD format."""
        if self.size != 7:
            raise ValueError(
                "BCD operations require a 7-byte register, " f"got {self.size} bytes."
            )

        if number == 0:
            ms_sign_nibble = 0
            mantissa_val = 0
            xs_sign_nibble = 0
            exp_val = 0
        else:
            sign = -1 if number < 0 else 1
            ms_sign_nibble = 9 if sign < 0 else 0

            # repr() gives the shortest decimal string that round-trips to this
            # exact float, so we round *that* value to 10 significant digits
            # rather than fighting binary-float noise from Decimal(number).
            d = Decimal(repr(abs(number)))
            d = Context(prec=10, rounding=ROUND_HALF_EVEN).create_decimal(d)
            _, digits, exponent = d.as_tuple()

            # Decimal strips trailing zeros from the coefficient (e.g. 5.0 ->
            # digits=(5,), exponent=0), so pad back out to exactly 10 digits
            # and shift the exponent to compensate.
            pad = 10 - len(digits)
            mantissa_val = int("".join(map(str, digits)) + "0" * pad)
            t_val = exponent - pad

            # The hardware treats the 10-digit mantissa as d.ddddddddd (one
            # digit before the implied decimal point, nine after), so the
            # stored exponent is offset by +9 relative to t_val, which
            # assumes a plain 10-digit integer mantissa.
            stored_exp = t_val + 9

            # Clamp to hardware's 2-digit exponent range.
            stored_exp = max(-99, min(99, stored_exp))
            if stored_exp < 0:
                xs_sign_nibble = 9
                exp_val = 100 + stored_exp
            else:
                xs_sign_nibble = 0
                exp_val = stored_exp

        # Construct nibble array: MS(4), M1..M10 (40), XS(4), E1, E2 (8) =
        # 14 nibbles.
        nibbles = [ms_sign_nibble]

        digits = [0] * 10
        val = mantissa_val
        for i in range(9, -1, -1):
            val, digits[i] = divmod(val, 10)
        nibbles.extend(digits)

        nibbles.append(xs_sign_nibble)
        nibbles.append(exp_val // 10)  # E1
        nibbles.append(exp_val % 10)  # E2

        # Pack nibbles into bytes and update _data
        new_data = bytearray()
        for i in range(0, len(nibbles), 2):
            byte = (nibbles[i] << 4) | nibbles[i + 1]
            new_data.append(byte)
        self._data = new_data

    def get_ascii(self) -> str:
        """
        Reads this register as raw ASCII text, one character per byte,
        MSB-byte first. Non-printable bytes (including 0x00 padding) are
        rendered as '.' so the string always has a fixed, predictable width.

        Note that this converts the entire register, it does not respect the
        HP41 convention for formatting physical 7 byte registers to contain
        0-6 ASCII characters.
        """
        chars = []
        for byte in self._data:
            chars.append(chr(byte) if 0x20 <= byte <= 0x7E else ".")
        return "".join(chars)

    def set_ascii(self, text: str):
        """
        Writes raw ASCII text into this register, one character per byte,
        MSB-byte first. Text shorter than the register is padded with
        trailing 0x00 bytes; text longer than the register raises an error.
        """
        if len(text) > self.size:
            raise ValueError(
                f"ASCII text is too long for a {self.size}-byte register "
                f"(got {len(text)} characters)."
            )
        try:
            encoded = text.encode("ascii")
        except UnicodeEncodeError as e:
            raise ValueError(f"Text contains non-ASCII characters: {e}") from e

        new_data = bytearray(self.size)
        new_data[: len(encoded)] = encoded
        self._data = new_data

    def __eq__(self, other):
        return (
            isinstance(other, Register)
            and self.size == other.size
            and self._data == other._data
        )

    def __str__(self) -> str:
        """
        Note that this only works for PrimaryData. ASCII data in XM can be
        variable length and is byte-packed. The StatusRegisters.Alpha register
        is 25 bytes long and doesn't have the header byte.
        """
        if self._data[0] == 0x10:
            text = ""
            for b in self._data[1:]:
                if b != 0:
                    text += chr(b)
            if text.isprintable():
                return '"' + text + '"'
            return self._data.hex()
        try:
            return f"{self.get_bcd_number():.8g}"
        except ValueError:
            pass

        return self._data.hex()

    def __getitem__(self, index: int) -> int:
        # The LSB of the data is the last byte in the array.
        return self._data[self.size - index - 1]

    def __setitem__(self, index: int, value: int):
        # The LSB of the data is the last byte in the array.
        self._data[self.size - index - 1] = value

    def __repr__(self):
        return f"Register({self.get_hex()})"

class AlphaRegister(Register):
    """Represents the HP41/DM41 alpha register."""
    def __str__(self):
        skip_nulls = True
        text=""
        for b in self._data:
            if b != 0x00 and skip_nulls:
                skip_nulls = False
            if not skip_nulls:
                if 32 <= b <= 127:
                    c = chr(b)
                else:
                    c = "."
                text = text + c
        return text

STATUS_REGISTERS_RANGE = (0x00, 0x0F)
VOID_RANGE = (0x10, 0x3F)
KEY_ASSIGNMENTS_RANGE = (0xC0, 0xC0)  # Key assignments are variable length.
PRIMARY_DATA_END = 0x1FF

ZERO_REGISTER_HEX = "00000000000000"
ZERO_REGISTER = Register(size = 7)
EOM_REGISTER_HEX = "ffffffffffffff"
EOM_REGISTER = Register.from_hex(EOM_REGISTER_HEX)

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
        return f"{type(self).__name__}(0x{self.address_range[0]:03X}-" \
               f"0x{self.address_range[1]:03X})"

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


# Labels for the 16 status registers, in address order.
STATUS_REGISTER_LABELS = [
    "T", "Z", "Y", "X",
    "LastX", "M", "N", "O",
    "P", "Q", "F", "a",
    "b", "c", "d / Flags", "e",
]

class StatusRegisters(MemoryRegion):
    """The 16 named CPU/system registers, T through e."""

    key = "status_registers"
    label = "Status Registers"

    def __init__(self, memory: "Memory"):
        super().__init__(memory, STATUS_REGISTERS_RANGE)
        bd = self.get_register(8)._data[4:7] + self.get_register(7)._data + \
                self.get_register(6)._data + self.get_register(5)._data
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
            return f"{STATUS_REGISTER_LABELS[addr]}: " \
                   f"{self.get_register(addr).get_bcd_number()}"
        if 0x05 <= addr <= 0x08:
            return f"{STATUS_REGISTER_LABELS[addr]}: " \
                   f"{self.get_register(addr).get_ascii()}"
        if 0x09 <= addr <= 0x0f:
            return f"{STATUS_REGISTER_LABELS[addr]}: " \
                   f"{self.get_register(addr).get_hex()}"
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
    """Need more research."""

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


# The extended-memory regions the calculator can address. Regions 0 and 1
# are always present in the DM41L emulator.
XM_REGIONS = [(0x40, 0xBF), (0x201, 0x2EF)]


class XMFile:
    """
    A single file (directory entry) found inside an ExtendedMemory region.

    Reverse-engineered from sample dumps rather than documented spec, so
    treat the field meanings as well-tested hypotheses, not certainties.
    """
    TYPE_PROGRAM = 1
    TYPE_DATA = 2
    TYPE_ASCII = 3
    TYPE_LABELS = {TYPE_PROGRAM: "Program", TYPE_DATA: "Data", TYPE_ASCII: "ASCII"}

    def __init__(
        self,
        memory: "Memory",
        header_addr: int,
        file_type: int,
        name: str,
        segments: list,
        declared_length: int,
        byte_length: Optional[int] = None,
    ):
        self._memory = memory
        self.header_addr = header_addr
        self.name_addr = header_addr + 1
        self.file_type = file_type
        self.name = name
        # segments is a list of inclusive (start, end) address ranges, in
        # record order: the first segment is in the header's own region and
        # starts at data_end == header_addr-1 (the register directly below
        # the header); a file whose declared_length doesn't fit in that
        # region's remaining space continues with one or more further
        # segments at the top of the next region(s) -- see the note on
        # ExtendedMemory.list_files() about cross-region continuation.
        # Each segment's start is derived structurally (from the next file
        # below it, the region floor, or a region's remaining declared
        # length), NOT assumed from declared_length.
        self.segments = list(segments)
        # Register count declared in the header (SSS in docs/memory.md).
        self.declared_length = declared_length
        # Program files only: instruction-byte count declared in the header
        # (BBB in docs/memory.md), not counting the trailing checksum byte.
        # None for Data/ASCII files.
        self.byte_length = byte_length

    @property
    def data_end(self) -> int:
        """The highest address of this file's data -- always header_addr-1,
        in the header's own region (the first/nearest-header segment)."""
        return self.segments[0][1]

    @property
    def data_start(self) -> int:
        """The lowest address of this file's data. For a file that spans
        regions, this is in the *last* (furthest-from-header) segment,
        which may be in a different region than header_addr."""
        return self.segments[-1][0]

    @property
    def type_label(self) -> str:
        return self.TYPE_LABELS.get(self.file_type, f"Unknown(0x{self.file_type:x})")

    @property
    def num_registers(self) -> int:
        return sum(end - start + 1 for start, end in self.segments)

    @property
    def spans_regions(self) -> bool:
        """True if this file's data continues past the region its header
        lives in, into the top of one or more subsequent XM regions."""
        return len(self.segments) > 1

    def __repr__(self):
        span = ", ".join(f"0x{s:03x}-0x{e:03x}" for s, e in self.segments)
        return f"XMFile({self.name!r}, {self.type_label}, {span})"

    def data_registers(self) -> list:
        """
        This file's data registers in record order: nearest the header
        (record 1) first, down to the farthest register (last record) --
        i.e. descending address within each segment, walking segments in
        order. Confirmed against known record sequences in 3x-xm.dm41
        (both Data and ASCII) and fillextended.dm41 (ASCII), and against
        the record values that continue seamlessly across a region
        boundary in 6x-xm.dm41's XM4.000 (see ExtendedMemory.list_files()).
        """
        regs = []
        for start, end in self.segments:
            regs.extend(self._memory.get_register(a) for a in range(end, start - 1, -1))
        return regs

    def get_numbers(self) -> list:
        """Data-type files: one BCD number per register, in record order."""
        if self.file_type != self.TYPE_DATA:
            raise ValueError(f"{self.name!r} is not a Data file ({self.type_label})")
        return [reg.get_bcd_number() for reg in self.data_registers()]

    def get_records(self) -> list:
        """
        ASCII-type files: the variable-length text records, in record order.

        Records are packed as [1-byte length][text bytes], back to back
        across register boundaries with no padding, in a byte stream built
        by reading data_registers() (header-adjacent first) and
        concatenating each register's 7 bytes in normal left-to-right order.
        Confirmed against the known "@", "@A", "@AB"... sequence in
        3x-xm.dm41 and the repeating "FILLMEM" records in fillextended.dm41.

        Stops at the first length byte of 0, or one that would run past the
        end of this file's allocated registers -- this keeps leftover
        uninitialized fill bytes below a partially-used file from being
        misread as records, but hasn't been tested against a file that
        legitimately contains a zero-length record.
        """
        if self.file_type != self.TYPE_ASCII:
            raise ValueError(f"{self.name!r} is not an ASCII file ({self.type_label})")
        stream = bytearray()
        for reg in self.data_registers():
            stream += bytes(reg._data)

        records = []
        i = 0
        while i < len(stream):
            length = stream[i]
            if length == 0 or i + 1 + length > len(stream):
                break
            records.append(
                bytes(stream[i + 1 : i + 1 + length]).decode("ascii", errors="replace")
            )
            i += 1 + length
        return records

    def get_program_bytes(self) -> bytes:
        """
        Program-type files: the raw byte stream for this file's registers,
        in the same header-adjacent-first order as data_registers(). This
        stream is exactly declared_length * 7 bytes long: the first
        byte_length bytes are the program's instructions (read high-to-low
        per the HP41's reverse execution model -- see docs/memory.md) and
        the byte immediately after them is a modulo-256 checksum. Any bytes
        beyond that (there shouldn't be any once byte_length is set
        correctly) are leftover/padding.
        """
        if self.file_type != self.TYPE_PROGRAM:
            raise ValueError(f"{self.name!r} is not a Program file ({self.type_label})")
        stream = bytearray()
        for reg in self.data_registers():
            stream += bytes(reg._data)
        return bytes(stream)

    def get_instruction_bytes(self) -> bytes:
        """Program-type files: just the instruction bytes, excluding the
        trailing checksum byte (and any bytes past it)."""
        data = self.get_program_bytes()
        if self.byte_length is None:
            return data
        return data[: self.byte_length]

    @property
    def checksum_valid(self) -> Optional[bool]:
        """
        Program-type files: whether the byte immediately following the
        declared instruction bytes matches a modulo-256 sum of those
        instruction bytes, as described in docs/memory.md. Returns None if
        byte_length wasn't available (so there's nothing to check against).
        """
        if self.file_type != self.TYPE_PROGRAM:
            raise ValueError(f"{self.name!r} is not a Program file ({self.type_label})")
        if self.byte_length is None:
            return None
        data = self.get_program_bytes()
        if self.byte_length >= len(data):
            return None
        computed = sum(data[: self.byte_length]) % 256
        return computed == data[self.byte_length]


class ExtendedMemory(MemoryRegion):
    """
    Extended memory (XM): file-oriented storage split across up to three
    disjoint regions (see XM_REGIONS). Each region is a stack of files
    packed from its top (highest address) downward: a file is a contiguous
    run of data registers immediately followed by a 2-register
    [header][name] pair at the top of its space, with the next file (if
    any) packed directly below.

    Header register layout, reverse-engineered from several known-content
    dumps (not from a documented spec -- see docs/memory.md for the sample
    data this is based on):
      nibble 0      file type: 1 = Program, 2 = Data, 3 = ASCII.
      nibble 1-3    (Data/ASCII only) AAA, the header's own address.
                    Confirmed against every real header in every sample
                    dump with no exceptions -- see _parse_header().
      remaining     Register-count (SSS, all three types) and, for
                    Program, instruction-byte-count (BBB) -- see
                    _parse_header(). RRR/CC (Data/ASCII) aren't decoded;
                    docs/memory.md has what's documented about them, but
                    nothing here depends on them.
                    Program headers ("10000000BBBSSS") are a special case:
                    bytes 0-3 are a fixed 0x10 00 00 00 signature, and the
                    BBB/SSS fields that follow it check out against real
                    dumps -- confirmed by validating the trailing checksum
                    byte (see XMFile.checksum_valid) against 6x-xm.dm41 and
                    3x-xm.dm41's saved "PURXM" program.

    list_files() finds Data/ASCII headers structurally: a register with a
    Data/ASCII type nibble, whose AAA equals its own address, whose
    reserved-zero nibbles are actually zero, immediately followed by a
    register that looks like a 7-character name (mostly printable ASCII).
    All four checks are needed -- confirmed against largedump.dm41, where a
    run of ordinary packed text happened to satisfy the type-nibble and
    name-shaped checks alone (see _parse_header() for the specifics) but
    failed both AAA and the reserved-zero check, and would have produced a
    phantom file without them. Program headers are found by their fixed
    signature instead (see _parse_header()), which is what keeps mid-stream
    bytes of a packed ASCII record (which can also start with a nibble of
    1) from being misread as a Program header.

    """

    key = "extended_memory"
    label = "Extended Memory"

    TYPE_PROGRAM = XMFile.TYPE_PROGRAM
    TYPE_DATA = XMFile.TYPE_DATA
    TYPE_ASCII = XMFile.TYPE_ASCII

    @staticmethod
    def _looks_like_name(raw: bytes) -> bool:
        """A register is 'name-shaped' if most of its bytes are printable
        ASCII -- true for every real file name seen so far (always exactly
        7 characters, sometimes space-padded), and not true for BCD data,
        the all-zero/all-FF filler seen elsewhere, or packed ASCII-record
        content (which mixes in raw length-prefix bytes)."""
        return sum(1 for b in raw if 0x20 <= b <= 0x7E) >= 5

    @classmethod
    def _parse_header(cls, addr: int, raw: bytes) -> Optional[dict]:
        """
        Attempts to interpret a 7-byte register at `addr` as an XM file
        header. Returns None if `raw` doesn't match a known header shape,
        otherwise a dict with file_type, register_length (SSS in
        docs/memory.md, the register count declared in the header) and,
        for Program files only, byte_length (BBB, the instruction-byte
        count).

        register_length/byte_length are read from the 3-nibble SSS field
        (byte 5's low nibble + byte 6) and the 3-nibble BBB field (byte 4 +
        byte 5's high nibble) respectively -- these positions are the same
        across all three header formats in docs/memory.md.
        """
        if len(raw) != 7:
            return None
        file_type = raw[0] >> 4
        if file_type not in (cls.TYPE_PROGRAM, cls.TYPE_DATA, cls.TYPE_ASCII):
            return None

        register_length = ((raw[5] & 0x0F) << 8) | raw[6]

        if file_type == cls.TYPE_PROGRAM:
            # Program headers are "10000000BBBSSS" -- bytes 0-3 are a fixed
            # 0x10 00 00 00 signature. Without this check, mid-stream bytes
            # of a packed ASCII record (which can also start with a nibble
            # of 1) would be misread as Program headers.
            if raw[0] != 0x10 or raw[1:4] != b"\x00\x00\x00":
                return None
            byte_length = (raw[4] << 4) | (raw[5] >> 4)
            return {
                "file_type": file_type,
                "register_length": register_length,
                "byte_length": byte_length,
            }

        # Data ("2AAA0000RRRSSS") and ASCII ("3AAA00CCRRRSSS") headers both
        # encode the header's own address as AAA (nibble 1-3: the low
        # nibble of byte 0, plus all of byte 1) and both specify a reserved
        # run of nibbles that must literally be zero: nibble 4-7 for Data,
        # nibble 4-5 for ASCII. Both are confirmed against every real
        # header in every sample dump with no exceptions: AAA always equals
        # the header's own address, and the reserved nibbles are always
        # zero. Requiring both -- on top of the type nibble and
        # the name-shaped check on the next register -- is what tells a
        # real header apart from a register that merely coincidences into
        # looking like one. (Certain advanced HP41 programming techniques
        # can embed additional data in a file register; this is called
        # "Non-normalized data".)
        aaa = ((raw[0] & 0x0F) << 8) | raw[1]
        if aaa != addr:
            return None
        if file_type == cls.TYPE_DATA:
            if raw[2:4] != b"\x00\x00":
                return None
        else:  # TYPE_ASCII -- nibble 4-5 is byte 2 in full; nibble 6-7
            # (byte 3) is the CC field and isn't required to be zero.
            if raw[2] != 0x00:
                return None

        return {"file_type": file_type, "register_length": register_length, "byte_length": None}

    def list_files(self) -> list[XMFile]:
        """
        Walks every XM region top-down and returns the files found, in
        address order.

        A file's data can span multiple regions.
        """
        files = []

        # Notes: In theory we should be able to handle 1, 2, or 3 extended
        # memory regions but as a practical matter, the DM41L emulator always
        # has exactly two. These two regions occupy (0x40-0x0bf) and
        # (0x201-0x2ef).
        #
        # Also, while the contents of the XM header registers would probably
        # be initialized at boot time on a real HP41 calculator, the DM41L
        # emulator does not initialize them until the first file is created.
        # We can use this as a simple check for whether extended memory is
        # empty or not.

        # If the last 3 nibbles of the region header 
        # equal 0, there are no XM files.
        current_region = 0
        region_header_addr = XM_REGIONS[current_region][0]
        region_header = self.get_register(region_header_addr)
        if region_header == ZERO_REGISTER:
            return []

        # Compare what the memory dump says should be the top of the first
        # XM region with what we know it should be...
        addr = (region_header[1] & 0x0f) * 256 + region_header[0] 
        if addr != XM_REGIONS[current_region][1]:
            raise MemoryError(f"Invalid XM header: {addr:x} != 0x" \
                              f"{XM_REGIONS[current_region][1]}")

        while self.get_register(addr) != EOM_REGISTER:
            name = self.get_register(addr).get_ascii()
            addr -= 1
            segments=[]
            header_addr = addr
            header_register = self.get_register(addr)
            header = ExtendedMemory._parse_header(addr, header_register._data)
            if header is None:
                raise MemoryError("Detected invalid XM file header. "\
                                f"0x{addr:x}: {header_register.get_hex()}")

            addr -= header["register_length"]+1
            if addr <= XM_REGIONS[current_region][0]:
                # File spans regions.
                segments = [[ XM_REGIONS[current_region][0]+1, header_addr-1 ]]

                s = XM_REGIONS[current_region][0] - addr
                current_region += 1
                addr = XM_REGIONS[current_region][1] - s
                
                segments.append([ addr+1, XM_REGIONS[current_region][1] ])

            else:
                # File only has 1 segment.
                segments = [[ addr+1, header_addr-1 ]]
        
            file = XMFile(memory = self._memory,
                          name = name,
                          header_addr = header_addr,
                          file_type = header["file_type"],
                          declared_length = header["register_length"],
                          byte_length = header.get("byte_length", None),
                          segments = segments)
            files.append(file)
        return files

    def _find_region(self, addr: int) -> int:
        """The index into XM_REGIONS whose *usable* span (just above the
        region's reserved pointer register, up through its ceiling)
        contains addr."""
        for i, (lo, hi) in enumerate(XM_REGIONS):
            if lo < addr <= hi:
                return i
        raise MemoryError(f"Address 0x{addr:x} is not within any writable XM region")

    def _next_slot(self) -> tuple:
        """
        Where a newly-appended file's name register should go: returns
        (name_addr, region_index, needs_bootstrap).

        Mirrors list_files(): the position list_files() would check next
        (and find EOM/free space) right after the last existing file is
        exactly where a new file belongs -- see the note on
        XMFile.data_start in list_files()'s docstring. needs_bootstrap is
        True only when extended memory has never been used at all (region
        0's pointer register is still all-zero), in which case that
        pointer register doesn't exist yet and must be created from
        scratch.
        """
        files = self.list_files()
        if files:
            name_addr = files[-1].data_start - 1
            return name_addr, self._find_region(name_addr), False

        region0_header = self.get_register(XM_REGIONS[0][0])
        if region0_header == ZERO_REGISTER:
            return XM_REGIONS[0][1], 0, True

        # Region 0's pointer register is already initialized but every file
        # has apparently been deleted -- trust its TTT field, same as
        # list_files() does.
        addr = (region0_header[1] & 0x0F) * 256 + region0_header[0]
        return addr, self._find_region(addr), False

    def _allocate_segments(
        self, name_addr: int, region_index: int, register_count: int
    ) -> tuple:
        """
        Works out where a new file's register_count data registers land,
        starting immediately below the header at name_addr - 1, spilling
        into the next XM region if it doesn't fit in this one's remaining
        space -- the exact inverse of the address math in list_files()
        (see its docstring for the cross-region-continuation details), so
        that list_files() reading the result back reconstructs the same
        segments.

        Returns (segments, next_name_addr, ending_region): segments is in
        the same [[start, end], ...] shape list_files() produces;
        next_name_addr is where *this* file's own successor (or an EOM
        sentinel) belongs, in ending_region.
        """
        header_addr = name_addr - 1
        cursor = header_addr - (register_count + 1)

        if cursor <= XM_REGIONS[region_index][0]:
            # Spans into the next region, identically to the reading side.
            segments = [[XM_REGIONS[region_index][0] + 1, header_addr - 1]]
            s = XM_REGIONS[region_index][0] - cursor
            next_region = region_index + 1
            if next_region >= len(XM_REGIONS):
                raise MemoryError(
                    "Not enough free space in extended memory for this "
                    "file -- no further XM region is available to spill "
                    "into."
                )
            ceiling = XM_REGIONS[next_region][1]
            cursor = ceiling - s
            if cursor + 1 <= XM_REGIONS[next_region][0]:
                raise MemoryError(
                    "Not enough free space in extended memory for this "
                    "file -- it would need to spill into a third region, "
                    "which isn't supported (or confirmed to work on real "
                    "hardware -- see docs/memory.md sec. 4.5)."
                )
            segments.append([cursor + 1, ceiling])
            return segments, cursor, next_region

        segments = [[cursor + 1, header_addr - 1]]
        return segments, cursor, region_index

    @staticmethod
    def _build_header(
        file_type: int, header_addr: int, register_length: int,
        byte_length: Optional[int] = None,
    ) -> Register:
        """Builds a header register per the formats in docs/memory.md sec.
        4.3, inverting the exact formulas _parse_header() uses to read
        them back -- so a file written this way is guaranteed to
        round-trip through list_files()."""
        data = bytearray(7)
        if file_type == XMFile.TYPE_PROGRAM:
            data[0] = 0x10
            data[4] = (byte_length >> 4) & 0xFF
            data[5] = ((byte_length & 0x0F) << 4) | ((register_length >> 8) & 0x0F)
            data[6] = register_length & 0xFF
        else:
            # Data/ASCII: AAA (the header's own address) in nibbles 1-3,
            # RRR left at 0 and, for ASCII, CC (byte 3) also left at 0 --
            # both are documented as runtime cursors for an *open* file
            # (docs/memory.md sec. 4.3); a freshly-written, not-currently-
            # open file uses 0 for both, but this isn't confirmed against
            # a real freshly-saved dump.
            data[0] = (file_type << 4) | ((header_addr >> 8) & 0x0F)
            data[1] = header_addr & 0xFF
            data[5] = (register_length >> 8) & 0x0F
            data[6] = register_length & 0xFF
        return Register(data=bytes(data))

    @staticmethod
    def _build_region_pointer(region_index: int) -> Register:
        """Builds the 000WW0PPNNNTTT pointer register for XM_REGIONS[region_index]
        (docs/memory.md sec. 4.1), used only to bootstrap a region that has
        never held a file. TTT/NNN (this region's own ceiling, and the next
        region's ceiling or 0) are well-confirmed. WW/PP ("currently"/
        "previously open file index") are left at 0 -- their real meaning
        and whether a loadable dump requires anything else there is NOT
        confirmed; docs/memory.md flags this explicitly."""
        ttt = XM_REGIONS[region_index][1]
        next_region = region_index + 1
        nnn = XM_REGIONS[next_region][1] if next_region < len(XM_REGIONS) else 0
        data = bytearray(7)
        data[4] = (nnn >> 4) & 0xFF
        data[5] = ((nnn & 0x0F) << 4) | ((ttt >> 8) & 0x0F)
        data[6] = ttt & 0xFF
        return Register(data=bytes(data))

    def add_file(
        self,
        name: str,
        file_type: int,
        *,
        numbers: Optional[list] = None,
        records: Optional[list] = None,
        instruction_bytes: Optional[bytes] = None,
    ) -> XMFile:
        """
        Appends a new file to extended memory and returns the XMFile
        describing it.

        Exactly one of the following must be given, matching file_type:
          - numbers (TYPE_DATA): a list of floats, one BCD register each.
          - records (TYPE_ASCII): a list of strings, packed as
            [1-byte length][text] records (docs/memory.md sec. 4.3), with
            a trailing 0x00 terminator byte always written explicitly so
            get_records() has a real stopping point even when the packed
            content exactly fills a whole number of registers.
          - instruction_bytes (TYPE_PROGRAM): raw instruction bytes; a
            modulo-256 checksum byte is appended automatically.

        New files are always appended after whatever the current last
        file is (or at the very top of extended memory, if it's empty) --
        matching the "files are packed top-down in creation order"
        behavior documented in docs/memory.md sec. 4.2/4.5. There's no
        support (yet) for reusing space freed by a deleted file.

        Raises MemoryError if there isn't enough contiguous XM space left
        (see _allocate_segments()).
        """
        if not name or len(name) > 7:
            raise ValueError(
                f"File name {name!r} must be 1-7 characters, got {len(name)}."
            )
        try:
            name.encode("ascii")
        except UnicodeEncodeError as e:
            raise ValueError(f"File name contains non-ASCII characters: {e}") from e
        padded_name = name.ljust(7)

        byte_length = None
        given = [x for x in (numbers, records, instruction_bytes) if x is not None]
        if len(given) != 1:
            raise ValueError(
                "Pass exactly one of numbers=, records=, or instruction_bytes=."
            )

        if file_type == self.TYPE_DATA:
            if numbers is None:
                raise ValueError("Data files require numbers=[...]")
            if not numbers:
                raise ValueError("Data files require at least one number")
            data_registers = []
            for n in numbers:
                reg = Register(size=7)
                reg.set_bcd_number(n)
                data_registers.append(reg)

        elif file_type == self.TYPE_ASCII:
            if records is None:
                raise ValueError("ASCII files require records=[...]")
            if not records:
                raise ValueError("ASCII files require at least one record")
            stream = bytearray()
            for r in records:
                encoded = r.encode("ascii")
                if len(encoded) > 255:
                    raise ValueError(
                        f"Record {r!r} is longer than 255 characters "
                        "(1-byte length prefix can't hold it)."
                    )
                stream.append(len(encoded))
                stream += encoded
            stream.append(0)  # Explicit end-of-records marker.
            while len(stream) % 7 != 0:
                stream.append(0)
            data_registers = [
                Register(data=bytes(stream[i : i + 7]))
                for i in range(0, len(stream), 7)
            ]

        elif file_type == self.TYPE_PROGRAM:
            if instruction_bytes is None:
                raise ValueError("Program files require instruction_bytes=b'...'")
            if not instruction_bytes:
                raise ValueError("Program files require at least one instruction byte")
            if len(instruction_bytes) > 0xFFF:
                raise ValueError(
                    "Instruction byte count doesn't fit in the header's "
                    "3-nibble field (max 4095)."
                )
            byte_length = len(instruction_bytes)
            checksum = sum(instruction_bytes) % 256
            stream = bytearray(instruction_bytes)
            stream.append(checksum)
            while len(stream) % 7 != 0:
                stream.append(0)
            data_registers = [
                Register(data=bytes(stream[i : i + 7]))
                for i in range(0, len(stream), 7)
            ]

        else:
            raise ValueError(f"Unknown file_type: {file_type}")

        register_length = len(data_registers)
        if register_length > 0xFFF:
            raise ValueError(
                "File is too long to declare in the header's 3-nibble "
                "register-length field (max 4095 registers)."
            )

        name_addr, region_index, needs_bootstrap = self._next_slot()
        segments, next_name_addr, ending_region = self._allocate_segments(
            name_addr, region_index, register_length
        )
        header_addr = name_addr - 1

        name_reg = Register(size=7)
        name_reg.set_ascii(padded_name)
        self.set_register(name_addr, name_reg)
        self.set_register(
            header_addr,
            self._build_header(file_type, header_addr, register_length, byte_length),
        )

        # Data registers, header-adjacent first, walking each segment in
        # descending-address order -- the write-side mirror of
        # XMFile.data_registers().
        i = 0
        for start, end in segments:
            for addr in range(end, start - 1, -1):
                self.set_register(addr, data_registers[i])
                i += 1

        # Terminate the directory with a fresh EOM sentinel, if there's
        # still room for one below what we just wrote.
        if next_name_addr > XM_REGIONS[ending_region][0]:
            self.set_register(next_name_addr, EOM_REGISTER)

        if needs_bootstrap:
            self.set_register(XM_REGIONS[0][0], self._build_region_pointer(0))
        if ending_region == 1 and self.get_register(XM_REGIONS[1][0]) == ZERO_REGISTER:
            self.set_register(XM_REGIONS[1][0], self._build_region_pointer(1))

        return XMFile(
            memory=self._memory,
            header_addr=header_addr,
            file_type=file_type,
            name=padded_name,
            segments=segments,
            declared_length=register_length,
            byte_length=byte_length,
        )

class UnusedRegion(MemoryRegion):
    key = "unused"
    label = "Unused / Free"


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


class Memory:
    """A complete DM41 memory dump."""

    # Pattern to capture 'A:' followed by any hex string of 1 or more chars
    SPECIAL_PATTERN = re.compile(r"([A-Z]:\s*)([0-9a-fA-F]+)")

    def __init__(self, header: str = "DM41"):
        self._header = header
        self._core_memory: Dict[int, Register] = {}  # Keyed by register index
        self._special_registers: Dict[str, Register] = (
            {}
        )  # Keyed by label order preservation

        # Default values for special registers. Taken from a
        # memory dump in "Memory Lost" state.
        self._special_registers["A"] = Register.from_hex("00000000c00020")
        self._special_registers["B"] = Register.from_hex("f000002c0480fd")
        self._special_registers["C"] = Register.from_hex("f000002c0480fd")
        self._special_registers["S"] = Register.from_hex("00001100000000")
        self._special_registers["M"] = Register.from_hex("00011cd5ff73cb")
        self._special_registers["N"] = Register.from_hex("000000000000c0")
        self._special_registers["G"] = Register.from_hex("00")

    def __eq__(self, other):
        if not isinstance(other, Memory):
            return False

        return (
            self._header == other._header
            and self._core_memory == other._core_memory
            and self._special_registers == other._special_registers
        )

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
