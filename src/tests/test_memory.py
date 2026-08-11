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


# --- Extended Memory / XMFile Tests ---

from pathlib import Path
from memory import ExtendedMemory, MemoryError, XM_REGIONS

DATA_DIR = Path(__file__).parent / "data"


def _load_xm(filename: str) -> ExtendedMemory:
    memory = Memory.from_file(DATA_DIR / filename)
    return ExtendedMemory(memory, address_range=[0x40, 0x3FF])


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
    with pytest.raises(MemoryError):
        xm.add_file("HUGE", xm.TYPE_DATA, numbers=[float(i) for i in range(4000)])


def test_xm_add_file_rejects_name_over_seven_characters():
    xm = _load_xm("empty.dm41")
    with pytest.raises(ValueError):
        xm.add_file("TOOLONGNAME", xm.TYPE_DATA, numbers=[1])


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
    xm2 = ExtendedMemory(reloaded, address_range=[0x40, 0x3FF])
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
