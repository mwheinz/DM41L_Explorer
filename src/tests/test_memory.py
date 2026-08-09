"""
Unit tests for DM41 emulator memory system.
Covers Register class (BCD, ASCII, hex) and Memory class (parsing, access).
"""

import pytest
from decimal import Decimal
from memory import (
    Register,
    Memory,
    StatusRegisters,
)  # Assuming memory.py is in the same directory or installable

# --- Register Tests ---


def test_register_init():
    """Test basic initialization of a Register."""
    reg = Register(size=7)
    assert reg.size == 7
    assert reg.get_hex() == "00000000000000"

    reg_data = Register(data=bytes([0x01, 0x02]))
    assert reg_data.size == 2
    assert reg_data.get_hex() == "0102"


def test_register_from_hex():
    """Test parsing from hex strings."""
    reg = Register.from_hex("01 02 03")
    assert reg.get_hex() == "010203"
    assert reg.size == 3

    with pytest.raises(ValueError):
        Register.from_hex("not hex")
    with pytest.raises(ValueError):
        Register.from_hex("01 G2")  # Invalid hex digit


def test_register_bcd_roundtrip():
    """Test round-tripping of BCD numbers: Positive, Negative, Zero."""
    reg = Register(size=7)

    test_cases = [
        1.0,
        123.456789,
        -123.456789,
        0.0,
        1e9,  # Large number
        1e-5,  # Small exponent that requires negative XS sign
        -1e-2,  # Negative small exponent
        1234567890.0,  # Max mantissa digits? Let's check precision limit 10 digits.
    ]

    for val in test_cases:
        reg.set_bcd_number(val)
        # We use pytest.approx because of float representation noise,
        # though BCD should be precise for the significant digits stored.
        assert reg.get_bcd_number() == pytest.approx(
            val, abs=1e-9
        ), f"Failed roundtrip for {val}"


def test_register_bcd_invalid_size():
    """BCD operations must fail if register is not 7 bytes."""
    reg = Register(size=3)
    with pytest.raises(ValueError, match="require a 7-byte register"):
        reg.set_bcd_number(1.0)
    with pytest.raises(ValueError, match="require a 7-byte register"):
        reg.get_bcd_number()


def test_register_bcd_invalid_nibbles():
    """Test error handling for corrupted BCD data."""
    # Manually creating a register with bad sign nibble (e.g., 1 instead of 0 or 9)
    # 1 is first nibble of '10...' in hex string '10000000000000'
    reg = Register.from_hex("10000000000000")
    with pytest.raises(ValueError, match="Invalid MS sign nibble"):
        reg.get_bcd_number()


def test_register_ascii():
    """Test ASCII writing and reading."""
    reg = Register(size=7)
    text = "HELLO"
    reg.set_ascii(text)
    assert reg.get_ascii().startswith("HELLO")
    # The register size is 7, text is 5, so expect padding '.' or null check
    # get_ascii returns '.' for non-printable. Padding is 0x00 which is not printable.
    assert (
        reg.get_ascii() == "HELLO.."
    )  # Assuming 0x00 renders as '.' in implementation logic


def test_register_ascii_error():
    """Test error conditions for ASCII."""
    reg = Register(size=3)
    with pytest.raises(ValueError, match="too long"):
        reg.set_ascii("TOOLONG")

    reg_long = Register(size=7)
    with pytest.raises(ValueError, match="non-ASCII"):
        reg_long.set_ascii("Hélló")  # Contains non-ASCII characters


def test_register_indexing():
    """Test register item access with LSB convention."""
    reg = Register(data=bytes([0x11, 0x22, 0x33]))  # size 3. Index 0 is LSB?
    # The code says: return self._data[self.size - index - 1]
    # So Index 0 -> self._data[3-0-1] = self._data[2] = 0x33
    # Index 2 -> self._data[3-2-1] = self._data[0] = 0x11
    assert reg[0] == 0x33
    assert reg[2] == 0x11


def test_register_equality():
    """Test Register __eq__."""
    reg1 = Register.from_hex("aabbcc")
    reg2 = Register.from_hex("aabbcc")
    reg3 = Register.from_hex("ddeeff")
    assert reg1 == reg2
    assert reg1 != reg3
    assert reg1 != "not a register"


# --- Memory Tests ---


@pytest.fixture
def empty_memory():
    return Memory()


def test_memory_initialization(empty_memory):
    """Test default special register values."""
    # Check S as an example from implementation defaults
    s_reg = empty_memory.get_register("S")
    assert s_reg is not None
    assert s_reg.get_hex() == "00001100000000"


def test_memory_from_string(empty_memory):
    """Test parsing a memory dump string."""
    dump = """DM41
00  01020304050607  08090a0b0c0d0e  0f101112131415 
A: c000f50046494c B: 8000000000c196 C: 0000002c0480fd S: 00101100100000 M: 00011cd5ff73cb N: 00000000000000 G: 00"""
    # Note: In my earlier analysis I saw A was c0..., which I'll assume is valid for test parsing,
    # even if get_bcd_number() would fail later. We are testing the parser here.
    mem = Memory.from_string(dump)
    assert mem._header == "DM41"
    assert mem.get_register(0).get_hex() == "01020304050607"
    assert mem.get_register("A").get_hex() == "c000f50046494c"
    assert mem.get_register("S").get_hex() == "00101100100000"


def test_memory_get_set_register(empty_memory):
    """Test accessing core memory and special registers."""
    # Core memory access by index
    new_reg = Register.from_hex("11223344556677")
    empty_memory.set_register(0x10, new_reg)
    assert empty_memory.get_register(0x10) == new_reg

    # Missing register defaults to 7 zeroed bytes
    missing_reg = empty_memory.get_register(0xFF)  # Address not in dict
    assert missing_reg.size == 7
    assert missing_reg.get_hex() == "00000000000000"

    # Special register access by label
    empty_memory.set_register("A", Register.from_hex("11223344556677"))
    assert empty_memory.get_register("A").get_hex() == "11223344556677"


def test_memory_to_string(empty_memory):
    """Test reconstructing dump string from Memory object."""
    # Add some data to core memory
    empty_memory.set_register(0, Register.from_hex("01020304050607"))
    dump_str = empty_memory.to_string()
    assert "DM41" in dump_str
    assert "00  01020304050607" in dump_str
    assert "A:" in dump_str


def test_memory_equality():
    """Test that two identical memories are equal."""
    dump = "DM41\n00 01020304050607\nA: 00000000000000 B: 00000000000000 C: 00000000000000 S: 00000000000000 M: 00000000000000 N: 00000000000000 G: 00"
    mem1 = Memory.from_string(dump)
    mem2 = Memory.from_string(dump)
    assert mem1 == mem2

    # Modify one
    mem2.set_register(0, Register.from_hex("ffffffffffffffff"))
    assert mem1 != mem2


def test_memory_malformed_dump():
    """Test error handling for invalid dump formats."""
    with pytest.raises(ValueError, match="Invalid header"):
        Memory.from_string("WRONG\n00 01020304050607")

    with pytest.raises(ValueError, match="not a hexadecimal number"):
        Memory.from_string("DM41\nXX 01020304050607")


# ---- StatusRegisters tests


@pytest.fixture
def status_memory():
    """Fixture to provide a basic memory object with some data initialized."""
    mem = Memory()
    # Fill core memory with some controlled data to test accessors and labels
    # Addresses 0-4: BCD data for label_for testing
    for addr in range(0, 5):
        reg = Register(size=7)
        reg.set_bcd_number(float(addr))  # 0, 1, 2, 3, 4
        mem.set_register(addr, reg)

    # Addresses 5-8: ASCII data for label_for testing
    for addr in range(5, 9):
        reg = Register(size=7)
        reg.set_ascii("A")  # Simple char 'A' at each address
        mem.set_register(addr, reg)

    # Addresses 9-15: Hex data for label_for testing
    for addr in range(9, 16):
        reg = Register(size=7)
        reg.set_ascii("X")  # We'll treat this as hex data by ignoring ASCII logic
        # Manually set hex to be predictable
        reg._data = bytearray([0x12, 0x34, 0x56, 0x00, 0x00, 0x00, 0x00])
        mem.set_register(addr, reg)

    # Set up address 14 specifically for 'd' and 'Flags' tests
    flag_reg = Register(size=7)
    flag_reg._data = bytearray([0xFF] * 7)
    mem.set_register(14, flag_reg)

    return mem


def test_status_registers_accessors(status_memory):
    """Test that all named accessors return the correct registers at correct addresses."""
    sr = StatusRegisters(status_memory)

    # Test BCD range accessors
    assert sr.T().get_bcd_number() == 0.0
    assert sr.Z().get_bcd_number() == 1.0
    assert sr.Y().get_bcd_number() == 2.0
    assert sr.X().get_bcd_number() == 3.0
    assert sr.LastX().get_bcd_number() == 4.0

    # Test ASCII range accessors (assuming address 5 contains 'A')
    assert sr.M().get_ascii().startswith("A")  # M is at index 5
    assert sr.N().get_ascii().startswith("A")  # N is at index 6
    assert sr.O().get_ascii().startswith("A")  # O is at index 7
    assert (
        sr.P().get_ascii().startswith("A")
    )  # P is at index 8 is outside range? No, 0x05-0x08 is M,N,O,P.
    # Let's check implementation: M=5, N=6, O=7. 25 is not right.
    # The loop goes 5,6,7,8. So M(5), N(6), O(7), P(8). Correct.


def test_status_registers_flags_accessor(status_memory):
    """Test the Flags() accessor returns register d at address 14."""
    sr = StatusRegisters(status_memory)
    expected = status_memory.get_register(14)
    assert sr.Flags() == expected
    assert sr.d() == expected


def test_status_registers_label_for(status_memory):
    """Test that label_for returns correctly formatted strings based on address range."""
    sr = StatusRegisters(status_memory)

    # BCD Range (0-4)
    bcd_label = sr.label_for(1)
    assert "Z" in bcd_label  # Z is at index 1
    assert "1.0" in bcd_label

    # ASCII Range (5-8)
    ascii_label = sr.label_for(6)  # N is at index 6
    assert "N" in ascii_label
    assert "A" in ascii_label  # Should contain the char A

    # Hex Range (9-15)
    hex_label = sr.label_for(10)  # Q is at index 10? No, label_for says 9..15 is hex.
    # Index 9 is Q in list: T=0... Q=9. So index 9 is Q.
    assert f"{sr.Q().get_hex()}" in hex_label.split("\n")[-1]  # simplified check


def test_status_registers_alpha_construction(status_memory):
    """
    Test the alpha register construction logic from combined data.
    Note: The current implementation in src/memory.py uses 'register + register',
    which may raise a TypeError. This test documents that behavior.
    """
    sr = StatusRegisters(status_memory)
    # If implementation is fixed to concatenate bytes properly, this should pass.
    # Currently it will likely fail with TypeError unless Register implements __add__.
    try:
        assert isinstance(sr.alpha, Register)
        assert sr.alpha.ascii_only is True
    except TypeError:
        pytest.fail(
            "StatusRegisters alpha construction failed - check if Register implements __add__ or use byte concatenation."
        )


def test_status_registers_invalid_address(status_memory):
    """Test label_for returns None for addresses outside the Status register range."""
    sr = StatusRegisters(status_memory)
    assert sr.label_for(0x20) is None
    assert sr.label_for(-1) is None
