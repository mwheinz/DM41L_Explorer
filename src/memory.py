"""
A representation of the memory of a DM41 emulator.

The dump consists of three parts: the header ("DM41"), the dump of main
memory, and the "special registers" which I believe represent the emulated
HP41 CPU registers.
"""

import re
import logging
from typing import Dict, Optional, Union
from pathlib import Path
from decimal import Decimal, Context, ROUND_HALF_EVEN

logger = logging.getLogger(__name__)


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
XM_REGION_RANGES = (0x40, 0xBF, 0x200, 0x3FF)
KEY_ASSIGNMENTS_RANGE = (0xC0, 0xC0)  # Key assignments are variable length.
PRIMARY_DATA_END = 0x1FF

ZERO_REGISTER_HEX = "00000000000000"


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


class ExtendedMemory(MemoryRegion):
    """Extended memory (XM); may hold packed/variable-length ASCII data."""

    key = "extended_memory"
    label = "Extended Memory"


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

        # Section II: Core Memory with sparse row grouping
        sorted_indices = sorted(self._core_memory.keys())
        if sorted_indices:
            i = 0
            n = len(sorted_indices)

            while i < n:
                base_idx = sorted_indices[i]
                row = [f"{base_idx:02x}"]
                count = 0
                while count < 4 and (i + count) < n:
                    next_idx = sorted_indices[i + count]
                    if next_idx == base_idx + count:
                        row.append(self._core_memory[next_idx].get_hex())
                        count += 1
                    else:
                        break
                lines.append("  ".join(row))
                i += count

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
