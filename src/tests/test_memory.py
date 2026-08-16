"""
Unit tests for DM41L emulator memory system.
Covers Register class (BCD, ASCII, hex) and Memory class (parsing, access).
"""

import pytest
from decimal import Decimal
from memory import (
    Register,
    Memory,
    StatusRegisters,
    format_data_line,
    parse_data_line,
    encode_trigraphs,
    decode_trigraphs,
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


def test_register_alpha_text_roundtrip():
    """Register.set_alpha_text()/get_alpha_text() -- the docs/memory.md
    "Alpha Storage" format: byte 0 == 0x10, remaining 6 bytes hold the
    text right-justified, NUL-padded on the left."""
    reg = Register(size=7)
    reg.set_alpha_text("HI")
    assert reg.is_alpha_text() is True
    assert reg.get_hex() == "10000000004849"  # 0x10, 4 NULs, "HI"
    assert reg.get_alpha_text() == "HI"

    reg.set_alpha_text("ABCDEF")  # exactly 6 chars, no padding
    assert reg.get_hex() == "10414243444546"
    assert reg.get_alpha_text() == "ABCDEF"


def test_register_alpha_text_errors():
    reg = Register(size=7)
    with pytest.raises(ValueError, match="1-6 characters"):
        reg.set_alpha_text("")
    with pytest.raises(ValueError, match="1-6 characters"):
        reg.set_alpha_text("TOOLONG")
    with pytest.raises(ValueError, match="non-ASCII"):
        reg.set_alpha_text("héllo")

    reg3 = Register(size=3)
    with pytest.raises(ValueError, match="7-byte register"):
        reg3.set_alpha_text("HI")

    # A plain zero register isn't alpha-marked (byte 0 == 0x00, not 0x10).
    assert Register(size=7).is_alpha_text() is False
    with pytest.raises(ValueError, match="not alpha-marked"):
        Register(size=7).get_alpha_text()


def test_register_alpha_bytes_roundtrip_non_ascii_focal_bytes():
    """get_alpha_bytes()/set_alpha_bytes() are the raw-byte primitives
    get_alpha_text()/set_alpha_text() are built on -- unlike the text
    wrappers, they accept any byte value 0-255, including bytes above the
    plain-ASCII range (128-255) that get_alpha_text()'s ASCII decode can't
    handle."""
    reg = Register(size=7)
    data = bytes([0xFF, 0x41, 0x00])  # a >127 FOCAL byte, 'A', a NUL
    reg.set_alpha_bytes(data)
    assert reg.is_alpha_text() is True
    assert reg.get_alpha_bytes() == data

    # get_alpha_text() refuses to decode a byte above the plain-ASCII
    # range rather than silently mangling it.
    with pytest.raises(ValueError, match="non-ASCII FOCAL character"):
        reg.get_alpha_text()


def test_register_alpha_bytes_errors():
    reg = Register(size=7)
    with pytest.raises(ValueError, match="1-6 characters"):
        reg.set_alpha_bytes(b"")
    with pytest.raises(ValueError, match="1-6 characters"):
        reg.set_alpha_bytes(b"TOOLONG")


def test_register_alpha_text_is_thin_ascii_wrapper_over_alpha_bytes():
    """set_alpha_text()/get_alpha_text() must still work exactly as
    before for pure-ASCII content -- they're now just get_alpha_bytes()/
    set_alpha_bytes() with an ASCII encode/decode around them."""
    reg = Register(size=7)
    reg.set_alpha_text("HI")
    assert reg.get_alpha_bytes() == b"HI"
    assert reg.get_alpha_text() == "HI"


def test_register_alpha_and_bcd_markers_cannot_collide():
    """An alpha-marked register (byte 0 == 0x10) can never also parse as a
    valid BCD number, and vice versa -- confirms format_data_line()/
    parse_data_line() below can tell the two apart unambiguously."""
    reg = Register(size=7)
    reg.set_alpha_text("HI")
    with pytest.raises(ValueError, match="Invalid MS sign nibble"):
        reg.get_bcd_number()


# --- DATA line format (format_data_line/parse_data_line, issue #11) ---


def test_format_data_line_number():
    reg = Register(size=7)
    reg.set_bcd_number(3.5)
    assert format_data_line(reg) == "3.5"
    reg.set_bcd_number(-42)
    assert format_data_line(reg) == "-42.0"  # get_bcd_number() always returns a float


def test_format_data_line_alpha_text():
    reg = Register(size=7)
    reg.set_alpha_text("HELLO")
    assert format_data_line(reg) == "HELLO"


def test_format_data_line_raw_hex_fallback():
    """A register that's neither a valid BCD number (bad MS sign nibble,
    5, instead of the only legal 0/9) nor alpha-marked (byte 0 is 0x50,
    not 0x10) round-trips as a 0x-prefixed 14-hex-digit line."""
    reg = Register.from_hex("50000000000000")
    line = format_data_line(reg)
    assert line == "0x50000000000000"


def test_parse_data_line_number():
    reg = parse_data_line("3.5")
    assert reg.get_bcd_number() == pytest.approx(3.5)
    reg2 = parse_data_line("-42")
    assert reg2.get_bcd_number() == pytest.approx(-42)


def test_parse_data_line_alpha_text():
    reg = parse_data_line("HELLO")
    assert reg.is_alpha_text() is True
    assert reg.get_alpha_text() == "HELLO"


def test_parse_data_line_raw_hex_requires_0x_prefix():
    """The "0x" prefix is required specifically so a bare 14-digit decimal
    number isn't ambiguous with raw hex -- without the prefix requirement,
    "12345678901234" (14 digits, all valid hex) could mean either."""
    reg = parse_data_line("0x99999999999999")
    assert reg.get_hex() == "99999999999999"

    # No prefix, same 14 digits: parsed as a (very large) decimal number,
    # not raw hex.
    reg2 = parse_data_line("12345678901234")
    assert reg2.get_bcd_number() == pytest.approx(12345678901234, rel=1e-9)


def test_parse_data_line_invalid_raises():
    with pytest.raises(ValueError):
        parse_data_line("")  # empty
    with pytest.raises(ValueError):
        parse_data_line("TOOLONGTEXT")  # > 6 chars, not a number
    with pytest.raises(ValueError):
        parse_data_line("0xZZZZZZZZZZZZZZ")  # "0x" prefix but not valid hex
    with pytest.raises(ValueError):
        parse_data_line("nan")  # not finite
    with pytest.raises(ValueError):
        parse_data_line("inf")  # not finite


def test_data_line_roundtrip_through_format_and_parse():
    """format_data_line() -> parse_data_line() must reproduce the exact
    same register bytes, for all three line kinds."""
    number_reg = Register(size=7)
    number_reg.set_bcd_number(1234567890.0)
    assert parse_data_line(format_data_line(number_reg)).get_hex() == number_reg.get_hex()

    alpha_reg = Register(size=7)
    alpha_reg.set_alpha_text("AB")
    assert parse_data_line(format_data_line(alpha_reg)).get_hex() == alpha_reg.get_hex()

    raw_reg = Register.from_hex("50000000000000")
    assert parse_data_line(format_data_line(raw_reg)).get_hex() == raw_reg.get_hex()


def test_format_data_line_alpha_text_uses_trigraphs_for_focal_bytes():
    """A register holding a FOCAL-special byte (Sigma, 0x7E) must format
    as its trigraph, not raise or mangle the byte."""
    reg = Register(size=7)
    reg.set_alpha_bytes(bytes([0x7E]))
    assert format_data_line(reg) == "\\E"


def test_parse_data_line_alpha_text_decodes_trigraphs():
    reg = parse_data_line("\\E")
    assert reg.is_alpha_text() is True
    assert reg.get_alpha_bytes() == bytes([0x7E])


def test_data_line_alpha_trigraph_roundtrip():
    """format_data_line() -> parse_data_line() must reproduce the exact
    same register bytes when the alpha content includes FOCAL-special
    bytes needing trigraphs."""
    reg = Register(size=7)
    reg.set_alpha_bytes(bytes([0x7E, 0x41, 0x00]))  # Sigma, 'A', high bar
    line = format_data_line(reg)
    assert parse_data_line(line).get_hex() == reg.get_hex()


def test_parse_data_line_alpha_validates_decoded_byte_length_not_source_length():
    """The 1-6 character alpha limit applies to DECODED bytes, not raw
    source-text length -- "\\E\\T\\+" is 3 decoded bytes (legal) despite
    being 9 source characters; "\\E\\E\\E\\E\\E\\E\\E" is 7 decoded bytes
    (too many) despite being shorter in some other encoding."""
    reg = parse_data_line("\\E\\T\\+")
    assert reg.get_alpha_bytes() == bytes([0x7E, 0x60, 0x7F])

    with pytest.raises(ValueError, match="alpha text must be 1-6 characters"):
        parse_data_line("\\E\\E\\E\\E\\E\\E\\E")


def test_parse_data_line_rejects_invalid_trigraph():
    with pytest.raises(ValueError):
        parse_data_line("\\zz")  # not a recognized shorthand or 3 digits


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


# --- Extended Memory / XMFile Tests ---

from pathlib import Path
from memory import ExtendedMemory, DM41LMemoryError, XM_REGIONS, ZERO_REGISTER

DATA_DIR = Path(__file__).parent / "data"


def _load_xm(filename: str) -> ExtendedMemory:
    memory = Memory.from_file(DATA_DIR / filename)
    return ExtendedMemory(memory, address_range=[0x40, 0x2EF])


def test_xm_6x_finds_all_six_files():
    """6x-xm.dm41 has 4 Data files, 1 ASCII file, and 1 Program file (PURXM)."""
    xm = _load_xm("6x-xm.dm41")
    files = xm.list_files()
    assert len(files) == 6

    by_name = {f.name: f for f in files}
    # Names are the raw, space-padded 7-character header field (see
    # docs/memory.md sec. 4.3): only PURXM is shorter than 7 characters.
    assert set(by_name) == {
        "XM1.000", "XM2.000", "XM3.000", "XM4.000", "XMALPHA", "PURXM  ",
    }

    for name in ("XM1.000", "XM2.000", "XM3.000"):
        assert by_name[name].file_type == xm.TYPE_DATA
        assert by_name[name].num_registers == 32

    # XM4.000 declares 32 registers but only 23 fit below it within region 0
    # -- the remaining 9 continue at the top of region 1 (0x2e7-0x2ef, just
    # above XMALPHA's header), confirmed by the BCD values there picking up
    # exactly where region 0's data leaves off (see docstring on
    # ExtendedMemory.list_files()).
    xm4 = by_name["XM4.000"]
    assert xm4.file_type == xm.TYPE_DATA
    assert xm4.declared_length == 32
    assert xm4.num_registers == 32
    assert xm4.spans_regions is True
    assert xm4.segments == [[0x041, 0x057], [0x2E7, 0x2EF]]
    numbers = xm4.get_numbers()
    assert len(numbers) == 32
    assert numbers == pytest.approx([64.095 + i * 1.0 for i in range(32)])

    assert by_name["XMALPHA"].file_type == xm.TYPE_ASCII
    assert by_name["XMALPHA"].num_registers == 128
    # Only some of the 128 allocated registers hold actual records; the
    # rest are unused/zero-filled, so get_records() legitimately returns
    # fewer entries than num_registers.
    assert len(by_name["XMALPHA"].get_records()) > 0

    assert by_name["PURXM  "].file_type == xm.TYPE_PROGRAM
    assert by_name["PURXM  "].num_registers == 3
    assert by_name["PURXM  "].byte_length == 20
    assert by_name["PURXM  "].checksum_valid is True
    assert len(by_name["PURXM  "].get_instruction_bytes()) == 20


def test_xm_3x_purxm_program_detected():
    """3x-xm.dm41 also contains a saved PURXM program between XMBCD and
    XMALPHA; before Program-header detection, its registers were wrongly
    counted as part of XMALPHA's data (133 registers instead of 128)."""
    xm = _load_xm("3x-xm.dm41")
    files = xm.list_files()
    by_name = {f.name: f for f in files}

    # XMBCD and PURXM are shorter than 7 characters, so their names carry
    # the raw space padding from the header field; XMALPHA fills all 7.
    assert set(by_name) == {"XMBCD  ", "XMALPHA", "PURXM  "}
    assert by_name["PURXM  "].file_type == xm.TYPE_PROGRAM
    assert by_name["PURXM  "].checksum_valid is True
    assert by_name["XMALPHA"].num_registers == 128


def test_xm_program_header_rejects_non_signature_type1_nibble():
    """A register merely starting with a 0x1 nibble (e.g. packed ASCII
    record bytes) must not be mistaken for a Program header -- only the
    fixed 0x10 00 00 00 signature counts."""
    assert ExtendedMemory._parse_header(0x62, bytes.fromhex("18444546474849")) is None
    assert ExtendedMemory._parse_header(0x263, bytes.fromhex("10000000014003")) is not None


def test_xm_header_requires_aaa_match_own_address():
    """A Data/ASCII header's AAA field (nibble 1-3) must equal its own
    address -- confirmed reliable across every real header in every sample
    dump."""
    real_header = bytes.fromhex("20580000020020")  # 6x-xm.dm41's XM4.000, AAA=0x058
    assert ExtendedMemory._parse_header(0x058, real_header) is not None
    assert ExtendedMemory._parse_header(0x059, real_header) is None

    phantom_header = bytes.fromhex("20555004574152")  # false header.
    assert ExtendedMemory._parse_header(0x0ba, phantom_header) is None


def test_xm_register_length_reads_full_three_nibble_field():
    """declared_length must read the full 3-nibble SSS field, not just the
    header's last byte -- fillextended.dm41's FILLMEM file is declared as
    362 registers (spanning multiple XM regions), which a single-byte read
    would truncate to 106 (362 mod 256)."""
    xm = _load_xm("fillextended.dm41")
    files = xm.list_files()
    assert len(files) == 1
    assert files[0].declared_length == 362


def test_xm_get_program_bytes_wrong_type_raises():
    xm = _load_xm("6x-xm.dm41")
    data_file = next(f for f in xm.list_files() if f.file_type == xm.TYPE_DATA)
    with pytest.raises(ValueError):
        data_file.get_program_bytes()


# --- ExtendedMemory.add_file() ---
#
# Each test round-trips through list_files() rather than asserting on raw
# register bytes -- that's the strongest available check, since list_files()
# is independently tested against real captured dumps above.


def test_xm_add_file_bootstraps_empty_extended_memory():
    """Adding a file to extended memory that has never been used at all
    must both write the file and initialize region 0's pointer register
    (0x040, all-zero beforehand) so list_files() recognizes it."""
    xm = _load_xm("empty.dm41")
    assert xm.list_files() == []

    added = xm.add_file("HELLO", xm.TYPE_DATA, numbers=[1, 2, 3.5, -42])
    assert added.name == "HELLO  "

    files = xm.list_files()
    assert len(files) == 1
    assert files[0].name == "HELLO  "
    assert files[0].get_numbers() == [1, 2, 3.5, -42]


def test_xm_add_file_data_lines_supports_mixed_content():
    """add_file(data_lines=[...]) (GitHub issue #11) lets a Data file mix
    numbers, short alpha text, and raw-hex registers -- unlike numbers=,
    which only ever produces plain BCD registers."""
    xm = _load_xm("empty.dm41")
    added = xm.add_file(
        "MIXED",
        xm.TYPE_DATA,
        data_lines=["1.5", "HI", "0x50000000000000", "-3"],
    )
    assert added.name == "MIXED  "

    files = xm.list_files()
    assert len(files) == 1
    assert files[0].get_data_lines() == ["1.5", "HI", "0x50000000000000", "-3.0"]
    regs = files[0].data_registers()
    assert regs[0].get_bcd_number() == pytest.approx(1.5)
    assert regs[1].get_alpha_text() == "HI"
    assert regs[2].get_hex() == "50000000000000"
    assert regs[3].get_bcd_number() == pytest.approx(-3)


def test_xm_add_file_rejects_duplicate_name():
    """Regression (user-reported): re-importing an exported file whose
    name matches one already present used to silently create a duplicate
    directory entry -- something a real DM41L would reject. add_file()
    must raise before writing anything."""
    xm = _load_xm("6x-xm.dm41")
    before = {f.name: f for f in xm.list_files()}
    assert "XM1.000" in before  # sanity: this fixture really has it

    with pytest.raises(DM41LMemoryError, match="already exists"):
        xm.add_file("XM1.000", xm.TYPE_DATA, numbers=[1, 2, 3])

    # Nothing should have been written -- same files, same content.
    after = {f.name: f for f in xm.list_files()}
    assert set(after) == set(before)


def test_xm_add_file_duplicate_check_does_not_flag_unrelated_names():
    """The duplicate check shouldn't be overly broad -- a genuinely
    different (if short) name must still be addable even though a
    same-prefix file already exists."""
    xm = _load_xm("6x-xm.dm41")
    added = xm.add_file("XM1", xm.TYPE_DATA, numbers=[1])
    assert added.name == "XM1    "


def test_xm_edit_file_keeping_same_name_does_not_self_collide():
    """Editing a file without renaming it (remove-then-add with the same
    name, as the GUI's Edit flow does) must not trip the new duplicate
    check against its own old entry."""
    xm = _load_xm("empty.dm41")
    added = xm.add_file("NOTES", xm.TYPE_ASCII, records=["hello"])

    xm.remove_file(added.header_addr)
    edited = xm.add_file("NOTES", xm.TYPE_ASCII, records=["hello", "world"])
    assert edited.get_records() == ["hello", "world"]


def test_xm_add_file_appends_after_existing_files():
    """Adding a file to an already-populated region must place it after
    (below) the current last file, and must not disturb any existing
    file's content."""
    xm = _load_xm("6x-xm.dm41")
    before = {f.name: f for f in xm.list_files()}

    xm.add_file("NOTES", xm.TYPE_ASCII, records=["hello", "world", "a third record"])

    after = {f.name: f for f in xm.list_files()}
    assert set(after) == set(before) | {"NOTES  "}
    assert after["NOTES  "].get_records() == ["hello", "world", "a third record"]

    # Every pre-existing file must read back exactly as it did before.
    for name, old in before.items():
        new = after[name]
        assert new.segments == old.segments
        assert new.file_type == old.file_type
        if old.file_type == xm.TYPE_DATA:
            assert new.get_numbers() == old.get_numbers()
        elif old.file_type == xm.TYPE_ASCII:
            assert new.get_records() == old.get_records()
        elif old.file_type == xm.TYPE_PROGRAM:
            assert new.get_instruction_bytes() == old.get_instruction_bytes()
            assert new.checksum_valid is True


def test_xm_add_file_program_checksum_and_roundtrip():
    xm = _load_xm("empty.dm41")
    instructions = bytes([0x1D, 0x2E, 0x3F, 0x40, 0x50] * 3)  # 15 bytes

    added = xm.add_file("MYPROG", xm.TYPE_PROGRAM, instruction_bytes=instructions)
    assert added.byte_length == 15

    files = xm.list_files()
    assert len(files) == 1
    prog = files[0]
    assert prog.name == "MYPROG "
    assert prog.byte_length == 15
    assert prog.get_instruction_bytes() == instructions
    assert prog.checksum_valid is True


def test_xm_add_file_spans_regions_when_it_does_not_fit():
    """A file added when region 0 doesn't have enough room left must
    spill into region 1 exactly the way a naturally-created spanning file
    does (see docs/memory.md sec. 4.5), and read back correctly across
    both segments."""
    xm = _load_xm("empty.dm41")
    xm.add_file("SMALL", xm.TYPE_DATA, numbers=list(range(70)))

    big_numbers = [float(i) for i in range(60)]
    added = xm.add_file("BIGFILE", xm.TYPE_DATA, numbers=big_numbers)
    assert added.spans_regions is True
    assert len(added.segments) == 2

    files = {f.name: f for f in xm.list_files()}
    big = files["BIGFILE"]
    assert big.spans_regions is True
    assert big.get_numbers() == big_numbers

    # Region 1's own pointer register must have been bootstrapped too,
    # since this is the first time anything has been written there.
    # Confirmed against real captures with a genuinely-spanning file
    # (tests/data/3x-xm.dm41, 6x-xm.dm41) -- both show this exact value.
    assert xm.get_register(0x201).get_hex() == "000000400002ef"


def test_xm_add_file_bootstrap_matches_real_device_pointer_register():
    """A real DM41L, erased then given its very first (non-spanning) XM
    file, wrote region 0's pointer register (0x040) as 000010000000bf --
    notably with NNN left at 0 even though region 1 exists in hardware
    (see tests/data/helloworld.dm41). add_file() bootstrapping the same
    scenario must produce the identical register."""
    real = _load_xm("helloworld.dm41")
    assert real.get_register(0x40).get_hex() == "000010000000bf"

    xm = _load_xm("empty.dm41")
    xm.add_file("NOTES", xm.TYPE_ASCII, records=["HELLO", "WORLD"])
    assert xm.get_register(0x40).get_hex() == "000010000000bf"


def test_xm_add_file_updates_region0_nnn_when_a_later_file_first_spans():
    """A real bug: region 0's pointer register (0x040) is only written
    once, when the very first file bootstraps it -- at that point NNN is
    correctly 0 if that file doesn't span. But if a *later* file (not the
    first) is the one that first spans into region 1, 0x040 must be
    patched then too, or its NNN field stays stuck at 0 forever and the
    real DM41L never looks at region 1 again -- every file placed there
    from that point on (including ones entirely inside region 1, not just
    the spanning one) becomes invisible to it, even though this tool's
    own list_files() doesn't depend on NNN and so doesn't notice.

    Confirmed via a real repro: several small ASCII files that fit
    entirely in region 0, followed by one large enough to span, followed
    by more files placed entirely in region 1."""
    xm = _load_xm("empty.dm41")

    def nnn():
        r40 = xm.get_register(0x40)
        return (r40[2] << 4) | (r40[1] >> 4)

    # Nine 9-record files fit entirely within region 0.
    for i in range(1, 10):
        xm.add_file(
            f"NOTES{i}", xm.TYPE_ASCII,
            records=[f"RECORD{n}" for n in range(1, 10)],
        )
        assert nnn() == 0, f"NNN went non-zero before any file spans (after NOTES{i})"

    # The tenth is the one that spans.
    tenth = xm.add_file(
        "NOTES10", xm.TYPE_ASCII, records=[f"RECORD{n}" for n in range(1, 10)]
    )
    assert tenth.spans_regions is True
    assert nnn() == XM_REGIONS[1][1]

    # Ten more Data files land entirely within region 1 and must still be
    # visible.
    for i in range(1, 11):
        xm.add_file(f"DATA{i}", xm.TYPE_DATA, numbers=list(range(1, 14)))
        assert nnn() == XM_REGIONS[1][1]

    files = xm.list_files()
    assert len(files) == 20
    assert {f.name.strip() for f in files} == {
        f"NOTES{i}" for i in range(1, 11)
    } | {f"DATA{i}" for i in range(1, 11)}


def test_xm_add_file_no_room_raises():
    xm = _load_xm("empty.dm41")
    with pytest.raises(DM41LMemoryError):
        xm.add_file("HUGE", xm.TYPE_DATA, numbers=[float(i) for i in range(4000)])


def test_xm_add_file_rejects_name_over_seven_characters():
    xm = _load_xm("empty.dm41")
    with pytest.raises(ValueError):
        xm.add_file("TOOLONGNAME", xm.TYPE_DATA, numbers=[1])


def test_xm_add_file_rejects_name_outside_allowed_character_range():
    """File names must be plain ASCII 32-101 inclusive (space through
    lowercase 'e') -- unlike file *content*, names don't support
    trigraphs, so a character above that range is simply rejected."""
    xm = _load_xm("empty.dm41")
    # 'z' is 122, above the 101 ('e') upper bound.
    with pytest.raises(ValueError, match="outside the allowed range"):
        xm.add_file("zzz", xm.TYPE_DATA, numbers=[1])
    # A DEL byte (127) or anything else above 101 is rejected the same way.
    with pytest.raises(ValueError, match="outside the allowed range"):
        xm.add_file("A\x7fB", xm.TYPE_DATA, numbers=[1])


def test_xm_add_file_accepts_name_at_range_boundaries():
    """32 (space) and 101 ('e') are themselves valid -- the range is
    inclusive on both ends."""
    xm = _load_xm("empty.dm41")
    added_low = xm.add_file(" a", xm.TYPE_DATA, numbers=[1])  # leading space
    assert added_low.name == " a".ljust(7)
    xm2 = _load_xm("empty.dm41")
    added_high = xm2.add_file("e", xm.TYPE_DATA, numbers=[1])  # 'e' == 101
    assert added_high.name == "e".ljust(7)


def test_xm_get_records_encodes_focal_bytes_as_trigraphs():
    """get_records() must losslessly round-trip FOCAL-special bytes as
    trigraphs rather than the old lossy '?' replacement behavior."""
    xm = _load_xm("empty.dm41")
    added = xm.add_file("NOTES", xm.TYPE_ASCII, records=["A\\EB", "\\T\\+"])
    assert added.get_records() == ["A\\EB", "\\T\\+"]

    # And it decodes to the correct raw bytes underneath.
    regs = added.data_registers()
    stream = b"".join(r.get_bytes() for r in regs)
    # First record: length 3, then 'A', 0x7E (Sigma), 'B'.
    assert stream[0] == 3
    assert stream[1:4] == bytes([0x41, 0x7E, 0x42])


def test_xm_add_file_ascii_records_reject_out_of_range_trigraph():
    xm = _load_xm("empty.dm41")
    with pytest.raises(ValueError):
        xm.add_file("BAD", xm.TYPE_ASCII, records=["\\999"])  # >255


def test_xm_add_file_ascii_plain_content_unaffected_by_trigraph_support():
    """Existing plain-ASCII-only content (no trigraphs present) must still
    round-trip identically -- no regression from adding trigraph support."""
    xm = _load_xm("empty.dm41")
    added = xm.add_file("NOTES", xm.TYPE_ASCII, records=["hello", "world"])
    assert added.get_records() == ["hello", "world"]


def test_xm_add_file_rejects_wrong_argument_for_type():
    xm = _load_xm("empty.dm41")
    with pytest.raises(ValueError):
        xm.add_file("BADARGS", xm.TYPE_DATA, records=["oops"])
    with pytest.raises(ValueError):
        xm.add_file("NOARGS", xm.TYPE_ASCII)


def test_xm_add_file_dump_rows_stay_page_aligned():
    """to_string() must only ever emit rows starting on a 4-register-
    aligned address, filling in any untouched register in a partially-
    used page with the zero register -- the DM41L's loader rejects a
    dump with a misaligned row (confirmed: it rejected one after adding
    a 6-register ASCII file to empty.dm41, which left a 2-register gap
    at the top of a page before the file's own registers began)."""
    xm = _load_xm("empty.dm41")
    xm.add_file("NOTES", xm.TYPE_ASCII, records=["1", "2", "3", "4", "5", "-16"])

    dump = xm._memory.to_string()
    for line in dump.splitlines()[1:]:
        line = line.strip()
        if not line or ":" in line.split()[0]:
            continue  # blank line or the special-register section
        base = int(line.split()[0], 16)
        assert base % 4 == 0, f"row {line!r} doesn't start on a 4-register boundary"

    # And it must still round-trip correctly.
    reloaded = Memory.from_string(dump)
    xm2 = ExtendedMemory(reloaded, address_range=[0x40, 0x2EF])
    files = xm2.list_files()
    assert len(files) == 1
    assert files[0].get_records() == ["1", "2", "3", "4", "5", "-16"]


def test_xm_add_file_ascii_matches_real_device_encoding():
    """A real DM41L, given a fresh (erased) memory and told to create an
    ASCII file called NOTES with records HELLO/WORLD, wrote its data
    registers as 0548454c4c4f05 / 574f524c44ff00 -- terminating the
    record stream with 0xFF (not 0x00). A file created by add_file()
    with the same name and records must produce byte-identical data
    registers to that real capture (see tests/data/helloworld.dm41,
    and docs/memory.md sec. 4.3)."""
    real = _load_xm("helloworld.dm41")
    real_notes = next(f for f in real.list_files() if f.name == "NOTES  ")
    real_register_hex = [r.get_hex() for r in real_notes.data_registers()]

    xm = _load_xm("empty.dm41")
    added = xm.add_file("NOTES", xm.TYPE_ASCII, records=["HELLO", "WORLD"])

    assert [r.get_hex() for r in added.data_registers()] == real_register_hex
    assert added.get_records() == ["HELLO", "WORLD"]


# ---- R00 / .END. / Flags (register c / register d) ----
#
# Expected R00/.END. values below were read directly off register c
# (address 0x0d) in each sample dump and cross-checked two ways: against
# the old (pre-rewrite) Project Voyager memory.py, which had independently
# arrived at the same nibble math for R00/.END., and against the filename
# of empty-128.dm41 (0x200 - 0x180 = 128 data registers).


def test_r00_and_dotend_match_known_sample_dumps():
    cases = {
        "empty.dm41": (0x19C, 0x19B),
        "empty-128.dm41": (0x180, 0x17F),
        "helloworld.dm41": (0x19C, 0x19B),
        "alpha.dm41": (0x19C, 0x19B),
        "3x-xm.dm41": (0x19C, 0x187),
        # 0x188, not 0x182 -- 6x-xm.dm41 was regenerated after this
        # expectation was written (it briefly had an extra unnamed/empty
        # program, just an END instruction, while its author was testing
        # program-memory research; that shifted .END. and confused the
        # chain walk in list_programs() until the fixture was fixed).
        # 0x188 matches the file as it exists now and is what
        # test_list_programs_6x_finds_xmbcd_xmalpha_purxm_in_creation_order
        # already relies on below.
        "6x-xm.dm41": (0x19C, 0x188),
    }
    for filename, (expected_r00, expected_dotend) in cases.items():
        memory = Memory.from_file(DATA_DIR / filename)
        assert memory.R00() == expected_r00, filename
        assert memory.DotEnd() == expected_dotend, filename


def test_cold_start_signature_is_0x169_in_every_sample():
    """The 3-nibble field between 'printer use' and R00 in register c is
    documented as a fixed cold-start signature; every real sample dump
    should show the same value (0x169) there. There's no public accessor
    for this (it's not user-actionable), so read it via the same nibble
    math R00()/DotEnd() use."""
    for path in DATA_DIR.glob("*.dm41"):
        memory = Memory.from_file(path)
        nibbles = memory._reg_c_nibbles()
        cold_start = memory._nibbles_to_int(nibbles[5:8])
        assert cold_start == 0x169, path.name


def test_set_r00_rewrites_only_the_r00_field():
    memory = Memory.from_file(DATA_DIR / "empty.dm41")
    sigma_before = memory.SigmaReg()
    dotend_before = memory.DotEnd()

    memory.set_R00(0x150)

    assert memory.R00() == 0x150
    assert memory.SigmaReg() == sigma_before
    assert memory.DotEnd() == dotend_before


def test_set_r00_rejects_out_of_range_values():
    memory = Memory()
    with pytest.raises(ValueError):
        memory.set_R00(-1)
    with pytest.raises(ValueError):
        memory.set_R00(0x1000)


def test_flags_get_set_bit_mapping():
    """Flag N is bit N of the 56-bit register, MSB first: flag 0 is the
    top bit of byte 0, flag 55 is the bottom bit of byte 6."""
    memory = Memory()
    memory.set_register(Memory.REG_D_ADDR, Register.from_hex("80000000000001"))

    assert memory.get_flag(0) is True
    assert memory.get_flag(55) is True
    for n in range(1, 55):
        assert memory.get_flag(n) is False, n

    all_flags = memory.get_all_flags()
    assert len(all_flags) == 56
    assert all_flags[0] is True
    assert all_flags[55] is True
    assert all_flags.count(True) == 2


def test_flags_set_flag_roundtrip():
    # Memory() now ships with realistic ("Memory Lost" state) defaults for
    # register d, not an all-zero one -- start from an explicitly zeroed
    # flag register so this test is about set_flag()/get_flag() mechanics,
    # not whatever flags happen to be on by default.
    memory = Memory()
    memory.set_register(Memory.REG_D_ADDR, Register(size=7))

    memory.set_flag(11, True)  # "auto execute" per docs/flags.md
    memory.set_flag(48, True)  # "ALPHA"
    assert memory.get_flag(11) is True
    assert memory.get_flag(48) is True
    assert memory.get_all_flags().count(True) == 2

    memory.set_flag(11, False)
    assert memory.get_flag(11) is False
    assert memory.get_flag(48) is True


def test_flags_reject_out_of_range_numbers():
    memory = Memory()
    with pytest.raises(ValueError):
        memory.get_flag(56)
    with pytest.raises(ValueError):
        memory.set_flag(-1, True)


def test_status_registers_flags_agrees_with_memory_get_flag(status_memory):
    """status_memory's fixture fills register d (0x0e) with 0xFF bytes --
    every flag should read True through both the low-level Memory API and
    the StatusRegisters.Flags() register accessor."""
    assert status_memory.get_all_flags() == [True] * 56
    sr = StatusRegisters(status_memory)
    assert sr.Flags() == status_memory.get_register(14)


# ---- ExtendedMemory.remove_file() ----


def _snapshot_content(f):
    """Eagerly materializes an XMFile's content as a plain value. Needed
    whenever a snapshot must survive a later mutation of the underlying
    Memory -- XMFile reads its registers lazily, so holding onto the
    XMFile object itself (instead of calling this right away) would read
    back whatever ends up at those addresses *after* the mutation, not
    the content that was really there when the snapshot was taken."""
    if f.file_type == ExtendedMemory.TYPE_DATA:
        # get_data_lines() (not get_numbers()) so this snapshot works for
        # a Data file that mixes numbers, alpha text, and/or raw-hex
        # registers -- see test_xm_remove_file_preserves_mixed_data_file.
        return (f.file_type, f.get_data_lines())
    if f.file_type == ExtendedMemory.TYPE_ASCII:
        return (f.file_type, f.get_records())
    if f.file_type == ExtendedMemory.TYPE_PROGRAM:
        return (f.file_type, f.get_instruction_bytes())
    raise AssertionError(f"unexpected file type: {f.file_type}")


def test_xm_remove_file_from_middle_preserves_the_rest():
    xm = _load_xm("6x-xm.dm41")
    before_files = xm.list_files()
    assert len(before_files) == 6
    before = {f.name: _snapshot_content(f) for f in before_files}

    target = next(f for f in before_files if f.name == "XMALPHA")
    xm.remove_file(target.header_addr)

    after_files = xm.list_files()
    after = {f.name: _snapshot_content(f) for f in after_files}

    assert "XMALPHA" not in after
    assert set(after) == set(before) - {"XMALPHA"}
    for name, old_content in before.items():
        if name == "XMALPHA":
            continue
        assert after[name] == old_content, name
    for f in after_files:
        if f.file_type == ExtendedMemory.TYPE_PROGRAM:
            assert f.checksum_valid is True


def test_xm_remove_file_preserves_mixed_data_file():
    """Regression: remove_file()'s rebuild used to snapshot Data-type
    survivors via get_numbers(), which raises ValueError for any register
    that isn't a plain BCD number -- so removing *any* file while a
    sibling Data file contained alpha text or raw-hex content would have
    crashed instead of preserving it. It now uses get_data_lines()."""
    xm = _load_xm("empty.dm41")
    xm.add_file("MIXED", xm.TYPE_DATA, data_lines=["1.5", "HI", "0x50000000000000"])
    xm.add_file("DOOMED", xm.TYPE_ASCII, records=["remove me"])

    doomed = next(f for f in xm.list_files() if f.name == "DOOMED ")
    xm.remove_file(doomed.header_addr)

    files = xm.list_files()
    assert {f.name for f in files} == {"MIXED  "}
    assert files[0].get_data_lines() == ["1.5", "HI", "0x50000000000000"]


def test_xm_remove_last_file_leaves_extended_memory_empty():
    xm = _load_xm("empty.dm41")
    xm.add_file("ONLYONE", xm.TYPE_DATA, numbers=[1, 2, 3])
    added = xm.list_files()[0]

    xm.remove_file(added.header_addr)

    assert xm.list_files() == []
    # Region 0's pointer register should be back to "never used".
    assert xm.get_register(0x40) == ZERO_REGISTER


def test_xm_remove_file_unknown_header_raises():
    xm = _load_xm("empty.dm41")
    with pytest.raises(DM41LMemoryError):
        xm.remove_file(0x99)


def test_xm_remove_file_then_add_new_file_still_works():
    """Removing a file frees up its space for reuse via a subsequent
    add_file() call (even though remove_file() doesn't reuse the space
    itself -- see its docstring), since the rebuild always leaves
    extended memory in a normal, valid state."""
    xm = _load_xm("3x-xm.dm41")
    files = xm.list_files()
    xm.remove_file(files[0].header_addr)

    added = xm.add_file("NEWFILE", xm.TYPE_ASCII, records=["hi"])
    assert added.get_records() == ["hi"]
    names = {f.name for f in xm.list_files()}
    assert "NEWFILE" in names


# ---- Program memory: the global chain (docs/program.md sec 5) ----
#
# Expected names/counts below were derived by walking the chain by hand
# against the raw hex in each sample dump (see docs/program.md sec 5.1 for
# simple.dm41 and 6x-xm.dm41 specifically) and cross-checked against the
# real device's CAT 1 listing for XMBCD/XMALPHA/PURXM, already recorded in
# project notes from an earlier session.
#
# Entries are NOT grouped into "programs" -- the user's own testing (against
# a modified copy of 6x-xm.dm41) found a single END can have zero, one, or
# several LBLs chained to it, so each entry is just one independent chain
# link (a LBL header or an END marker). `distance_bytes` below is that
# entry's own raw marker distance to the next chain link the walk visits
# from it -- confirmed against the exact address arithmetic in
# docs/program.md's worked examples, not a program size.
#
# The permanent `.END.` itself (kind == ".END.") is included as the newest
# (last-listed) entry whenever program memory has any real content -- the
# user found comparing this tab's output against a real CAT 1 listing that
# omitting it (an earlier version of list_programs() silently dropped it)
# was hiding bytes CAT 1 counts as part of the newest program.


def test_list_programs_empty_memory_returns_nothing():
    for filename in ("empty.dm41", "empty-128.dm41", "helloworld.dm41", "alpha.dm41"):
        memory = Memory.from_file(DATA_DIR / filename)
        assert memory.list_programs() == [], filename


def test_list_programs_fresh_memory_returns_nothing():
    """A brand new, never-loaded Memory() has R00 decoded as 0 -- not a
    real partition -- so list_programs() should bail out to [] rather than
    trying to walk a nonsensical chain."""
    assert Memory().list_programs() == []


def test_list_programs_simple_finds_apptest_lbl_its_end_and_the_global_end():
    """simple.dm41 (docs/program.md's second worked example) has one LBL
    header (APPTEST), one plain END marker, and -- since this program is
    also the newest thing in memory -- the permanent `.END.` itself as a
    third, distinct chain link. Oldest (nearest R00, i.e. created first)
    is listed first, matching CAT 1's display order."""
    memory = Memory.from_file(DATA_DIR / "simple.dm41")
    programs = memory.list_programs()

    assert len(programs) == 3

    assert programs[0].name == "APPTEST"
    assert programs[0].kind == "LBL"
    assert programs[0].header_addr == 0x19B
    assert programs[0].header_offset == 0
    assert programs[0].key_assignment == 0x00
    assert programs[0].is_named is True
    # The oldest/first-ever chain link has no predecessor to point to.
    assert programs[0].distance_bytes == 0

    assert programs[1].name is None
    assert programs[1].kind == "END"
    assert programs[1].is_named is False
    assert programs[1].display_name == "END"
    # This END's own marker points 23 bytes onward to APPTEST's header.
    assert programs[1].distance_bytes == 23
    assert programs[1].distance_label == "23 bytes"
    assert programs[1].end_type == 0x0

    assert programs[2].name is None
    assert programs[2].kind == ".END."
    assert programs[2].is_named is False
    assert programs[2].end_type == 0x2
    assert programs[2].distance_bytes == 9


def test_list_programs_6x_finds_xmbcd_xmalpha_purxm_their_ends_and_the_global_end():
    """6x-xm.dm41 (docs/program.md's third worked example) has three LBL
    headers, each followed in the chain by its own separate END marker,
    plus the permanent `.END.` itself as the seventh and newest entry --
    but the LBL/END pairing is NOT guaranteed in general (see module-level
    note above), just what this specific fixture happens to contain."""
    memory = Memory.from_file(DATA_DIR / "6x-xm.dm41")
    programs = memory.list_programs()

    names_in_order = [p.name for p in programs]
    assert names_in_order == ["XMBCD", None, "XMALPHA", None, "PURXM", None, None]

    kinds_in_order = [p.kind for p in programs]
    assert kinds_in_order == ["LBL", "END", "LBL", "END", "LBL", "END", ".END."]

    # Each entry's raw distance, confirmed against the address arithmetic
    # worked out by hand for this exact fixture.
    distances_in_order = [p.distance_bytes for p in programs]
    assert distances_in_order == [0, 58, 3, 48, 3, 17, 8]

    by_name = {p.name: p for p in programs if p.is_named}
    assert by_name["XMBCD"].header_addr == 0x19B
    assert by_name["XMALPHA"].header_addr == 0x193
    assert by_name["PURXM"].header_addr == 0x18B
    # Key-assignment byte (0x00 = unassigned) -- decoded but not otherwise
    # asserted elsewhere in this file.
    assert by_name["XMBCD"].key_assignment == 0x01

    end_entries = [p for p in programs if not p.is_named]
    assert [p.end_type for p in end_entries] == [0x0, 0x0, 0x0, 0x2]
    assert all(p.key_assignment is None for p in end_entries)

    assert programs[-1].kind == ".END."


def test_list_programs_finds_the_same_three_names_in_every_variant_dump():
    """XMBCD/XMALPHA/PURXM also appear in 3x-xm.dm41 and manyfiles.dm41 --
    different fixtures, same three real programs (see project notes on the
    real device's CAT 1 listing)."""
    for filename in ("3x-xm.dm41", "manyfiles.dm41"):
        memory = Memory.from_file(DATA_DIR / filename)
        named = {p.name for p in memory.list_programs() if p.is_named}
        assert named == {"XMBCD", "XMALPHA", "PURXM"}, filename


def test_list_programs_address_label_format():
    memory = Memory.from_file(DATA_DIR / "simple.dm41")
    assert memory.list_programs()[0].address_label == "0x19b:0"


def test_list_programs_terminates_on_every_sample_dump():
    """Defensive/regression coverage: list_programs() should never raise or
    hang on any real fixture, regardless of whether it has programs."""
    for path in DATA_DIR.glob("*.dm41"):
        memory = Memory.from_file(path)
        programs = memory.list_programs()
        assert isinstance(programs, list)
        for p in programs:
            assert p.header_addr >= 0xC0
            assert 0 <= p.header_offset <= 6
