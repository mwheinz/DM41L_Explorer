"""
Register and AlphaRegister: fixed-length byte buffers representing HP41/
DM41L hardware registers, plus the BCD/ASCII encode/decode logic for them.

NOTE: The HP41C and DM41L are "little endian" - the LSB is considered to by
"byte 0" and the MSB is considered "byte 6" - but DM41L dump files print hex
data from MSB to LSB. That is, _data[0] contains the MSB of the register. and
_data[6] contains the LSB. Care must be taken to remember this difference when
comparing HP41 documentation with the implementation of the Register and
Memory classes.
"""

from decimal import Decimal, Context, ROUND_HALF_EVEN


class DM41LMemoryError(ValueError):
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
    """Represents the HP41/DM41L alpha register."""

    def __str__(self):
        skip_nulls = True
        text = ""
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
