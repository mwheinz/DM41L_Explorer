"""
Extended memory (XM): XMFile (one file/directory entry) and
ExtendedMemory (the region type that lists/adds/removes them). See
docs/memory.md sec 4 for the on-disk format this was reverse-engineered
from.
"""

from typing import Optional, TYPE_CHECKING

from .registers import Register, DM41LMemoryError, format_data_line, parse_data_line
from .trigraphs import encode_trigraphs, decode_trigraphs
from .constants import XM_REGIONS, ZERO_REGISTER, EOM_REGISTER
from .regions import MemoryRegion

if TYPE_CHECKING:
    from .memory import Memory

# XM file names are restricted to plain ASCII 32-101 (space through
# lowercase 'e') -- unlike a Data/ASCII file's *content*, which supports
# the full HP41/DM41L FOCAL character set via trigraphs (docs/trigraphs.md),
# names don't get trigraph translation at all.
NAME_MIN_CHAR = 0x20
NAME_MAX_CHAR = 0x65


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
        """Data-type files: one BCD number per register, in record order.
        Raises ValueError if any register isn't a valid BCD number (e.g.
        it holds alpha text instead) -- use get_data_lines() for files
        that may hold a mix of numbers, short text, and/or raw content."""
        if self.file_type != self.TYPE_DATA:
            raise ValueError(f"{self.name!r} is not a Data file ({self.type_label})")
        return [reg.get_bcd_number() for reg in self.data_registers()]

    def get_data_lines(self) -> list:
        """Data-type files: one DATA-format line per register (see
        registers.format_data_line()), in record order -- a number, short
        alpha text, or a "0x"-prefixed raw-hex fallback, per register.
        Unlike get_numbers(), this never raises for a register that isn't
        a plain number, so it's what import/export (GitHub issue #11) and
        remove_file()'s rebuild use to round-trip a Data file's full
        content regardless of what each register actually holds."""
        if self.file_type != self.TYPE_DATA:
            raise ValueError(f"{self.name!r} is not a Data file ({self.type_label})")
        return [format_data_line(reg) for reg in self.data_registers()]

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
        end of this file's allocated registers. A real DM41L-created file
        (2 ASCII records) terminates its record stream with an explicit
        0xFF length byte -- the same "0xFF marks free/end" convention used
        elsewhere in this format (docs/memory.md sec. 4.5) -- which is
        always caught by the overrun check here regardless of position, so
        no separate 0xFF check is needed. The `length == 0` branch is a
        defensive fallback for leftover zero-filled space below a
        partially-used file; it hasn't been tested against a file that
        legitimately contains a genuine zero-length record.

        Each record's raw bytes are trigraph-encoded (see
        trigraphs.encode_trigraphs()/docs/trigraphs.md) rather than
        ascii-decoded, since a real record can hold HP41/DM41L (FOCAL)
        characters with no plain-ASCII meaning -- ascii-decoding those
        would previously have silently mangled them into "?" replacement
        characters instead of round-tripping losslessly.
        """
        if self.file_type != self.TYPE_ASCII:
            raise ValueError(f"{self.name!r} is not an ASCII file ({self.type_label})")
        stream = bytearray()
        for reg in self.data_registers():
            stream += reg.get_bytes()

        records = []
        i = 0
        while i < len(stream):
            length = stream[i]
            if length == 0 or i + 1 + length > len(stream):
                break
            records.append(encode_trigraphs(bytes(stream[i + 1 : i + 1 + length])))
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
            stream += reg.get_bytes()
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

        return {
            "file_type": file_type,
            "register_length": register_length,
            "byte_length": None,
        }

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
        addr = (region_header[1] & 0x0F) * 256 + region_header[0]
        if addr != XM_REGIONS[current_region][1]:
            raise DM41LMemoryError(
                f"Invalid XM header: {addr:x} != 0x" f"{XM_REGIONS[current_region][1]}"
            )

        while self.get_register(addr) != EOM_REGISTER:
            name = self.get_register(addr).get_ascii()
            addr -= 1
            segments = []
            header_addr = addr
            header_register = self.get_register(addr)
            header = ExtendedMemory._parse_header(addr, header_register.get_bytes())
            if header is None:
                raise DM41LMemoryError(
                    "Detected invalid XM file header. "
                    f"0x{addr:x}: {header_register.get_hex()}"
                )

            addr -= header["register_length"] + 1
            if addr <= XM_REGIONS[current_region][0]:
                # File spans regions.
                segments = [[XM_REGIONS[current_region][0] + 1, header_addr - 1]]

                s = XM_REGIONS[current_region][0] - addr
                current_region += 1
                addr = XM_REGIONS[current_region][1] - s

                segments.append([addr + 1, XM_REGIONS[current_region][1]])

            else:
                # File only has 1 segment.
                segments = [[addr + 1, header_addr - 1]]

            file = XMFile(
                memory=self._memory,
                name=name,
                header_addr=header_addr,
                file_type=header["file_type"],
                declared_length=header["register_length"],
                byte_length=header.get("byte_length", None),
                segments=segments,
            )
            files.append(file)
        return files

    def _find_region(self, addr: int) -> int:
        """The index into XM_REGIONS whose *usable* span (just above the
        region's reserved pointer register, up through its ceiling)
        contains addr."""
        for i, (lo, hi) in enumerate(XM_REGIONS):
            if lo < addr <= hi:
                return i
        raise DM41LMemoryError(f"Address 0x{addr:x} is not within any writable XM region")

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
                raise DM41LMemoryError(
                    "Not enough free space in extended memory for this "
                    "file -- no further XM region is available to spill "
                    "into."
                )
            ceiling = XM_REGIONS[next_region][1]
            cursor = ceiling - s
            if cursor + 1 <= XM_REGIONS[next_region][0]:
                raise DM41LMemoryError(
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
        file_type: int,
        header_addr: int,
        register_length: int,
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
    def _build_region_pointer(
        region_index: int, *, next_region_active: bool, ww: int, pp: int
    ) -> Register:
        """
        Builds the 000WW0PPNNNTTT pointer register for XM_REGIONS[region_index]
        (docs/memory.md sec. 4.1).

        TTT is this region's own ceiling (well-confirmed). NNN is the next
        region's ceiling, but only when next_region_active -- **confirmed**
        by comparing real captures: a single, non-spanning file
        (tests/data/helloworld.dm41) leaves NNN at 0 even though region 1
        exists in hardware, while dumps with an actually-spanning file
        (3x-xm.dm41, 6x-xm.dm41) show NNN as region 1's ceiling. So NNN
        reflects whether the next region is *in use*, not merely whether
        it exists in XM_REGIONS.

        ww/pp ("currently"/"previously open file index", docs/memory.md
        sec. 4.1) are caller-supplied -- see add_file()'s call sites for
        what's actually confirmed for each region.
        """
        ttt = XM_REGIONS[region_index][1]
        next_region = region_index + 1
        nnn = 0
        if next_region_active and next_region < len(XM_REGIONS):
            nnn = XM_REGIONS[next_region][1]
        data = bytearray(7)
        data[2] = (ww & 0x0F) << 4
        data[3] = pp & 0xFF
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
        data_lines: Optional[list] = None,
        records: Optional[list] = None,
        instruction_bytes: Optional[bytes] = None,
    ) -> XMFile:
        """
        Appends a new file to extended memory and returns the XMFile
        describing it.

        Exactly one of the following must be given, matching file_type:
          - numbers (TYPE_DATA): a list of floats, one BCD register each.
          - data_lines (TYPE_DATA): a list of DATA-format strings (see
            registers.parse_data_line()), one register each -- like
            numbers, but each entry can also be 1-6 characters of alpha
            text or a "0x"-prefixed raw-hex register. This is what
            import/export (GitHub issue #11) and the GUI's Data-file
            editor use; numbers= is kept for callers that only ever deal
            in plain numbers.
          - records (TYPE_ASCII): a list of strings, packed as
            [1-byte length][text] records (docs/memory.md sec. 4.3), with
            a trailing 0xFF terminator byte always written explicitly, so
            there's a real stopping point even when the packed content
            exactly fills a whole number of registers. 0xFF (not 0x00) is
            confirmed against a real DM41L-created 2-record ASCII file --
            see docs/memory.md sec. 4.5 for the same 0xFF convention used
            elsewhere in the format.
          - instruction_bytes (TYPE_PROGRAM): raw instruction bytes; a
            modulo-256 checksum byte is appended automatically.

        New files are always appended after whatever the current last
        file is (or at the very top of extended memory, if it's empty) --
        matching the "files are packed top-down in creation order"
        behavior documented in docs/memory.md sec. 4.2/4.5. There's no
        support (yet) for reusing space freed by a deleted file.

        Raises DM41LMemoryError if there isn't enough contiguous XM space left
        (see _allocate_segments()).
        """
        if not name or len(name) > 7:
            raise ValueError(
                f"File name {name!r} must be 1-7 characters, got {len(name)}."
            )
        for ch in name:
            if not NAME_MIN_CHAR <= ord(ch) <= NAME_MAX_CHAR:
                raise ValueError(
                    f"File name {name!r} contains {ch!r} (code {ord(ch)}), "
                    f"outside the allowed range {NAME_MIN_CHAR}-{NAME_MAX_CHAR} "
                    "(ASCII space through lowercase 'e'). Unlike file "
                    "content, names don't support trigraphs."
                )
        padded_name = name.ljust(7)

        # A real DM41L rejects a duplicate directory entry name -- caught
        # here (rather than left for the emulator to reject later) so a
        # dump built by this tool can't be created in a state real
        # hardware wouldn't accept. This also naturally allows editing a
        # file "in place" under its own unchanged name: the GUI's Edit
        # flow (and remove_file()'s own rebuild) always removes the old
        # entry *before* calling add_file(), so by the time this check
        # runs, that name is no longer in list_files().
        if any(f.name == padded_name for f in self.list_files()):
            raise DM41LMemoryError(
                f"A file named {name!r} already exists in extended memory "
                "-- duplicate names aren't allowed (the real DM41L would "
                "reject this)."
            )

        byte_length = None
        given = [
            x for x in (numbers, data_lines, records, instruction_bytes) if x is not None
        ]
        if len(given) != 1:
            raise ValueError(
                "Pass exactly one of numbers=, data_lines=, records=, or "
                "instruction_bytes=."
            )

        if file_type == self.TYPE_DATA:
            if numbers is None and data_lines is None:
                raise ValueError("Data files require numbers=[...] or data_lines=[...]")
            if numbers is not None:
                if not numbers:
                    raise ValueError("Data files require at least one number")
                data_registers = [Register(size=7) for _ in numbers]
                for reg, n in zip(data_registers, numbers):
                    reg.set_bcd_number(n)
            else:
                if not data_lines:
                    raise ValueError("Data files require at least one line")
                data_registers = [parse_data_line(line) for line in data_lines]

        elif file_type == self.TYPE_ASCII:
            if records is None:
                raise ValueError("ASCII files require records=[...]")
            if not records:
                raise ValueError("ASCII files require at least one record")
            stream = bytearray()
            for r in records:
                # decode_trigraphs (not r.encode("ascii")): a record can
                # contain HP41/DM41L FOCAL characters with no plain-ASCII
                # meaning, written as trigraph escapes -- see
                # docs/trigraphs.md and trigraphs.decode_trigraphs().
                try:
                    encoded = decode_trigraphs(r)
                except ValueError as e:
                    raise ValueError(f"Record {r!r}: {e}") from e
                if len(encoded) > 255:
                    raise ValueError(
                        f"Record {r!r} decodes to {len(encoded)} characters, "
                        "longer than 255 (1-byte length prefix can't hold it)."
                    )
                stream.append(len(encoded))
                stream += encoded
            stream.append(0xFF)  # Explicit end-of-records marker.
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

        # The first file to actually use region 1 -- whether that's this
        # very file, or a later one appended after region 0 was already
        # bootstrapped -- must be reflected in region 0's OWN pointer
        # register's NNN field, not just region 1's. Missing this is a
        # confirmed real bug: a dump where region 0 was bootstrapped by an
        # earlier, non-spanning file (leaving NNN at 0, correctly, at that
        # time) and only a *later* file first spans into region 1 left
        # NNN stuck at 0 forever after -- the real DM41L trusts that field
        # to know region 1 exists at all, so every file from the first
        # spanning one onward (including ones entirely within region 1)
        # was invisible to it, even though this tool's own list_files()
        # never needed that field and so never caught it.
        region1_is_new = (
            ending_region == 1 and self.get_register(XM_REGIONS[1][0]) == ZERO_REGISTER
        )

        if needs_bootstrap:
            # Confirmed against tests/data/helloworld.dm41 (a real DM41L,
            # erased then given its very first XM file): ww=1, pp=0.
            self.set_register(
                XM_REGIONS[0][0],
                self._build_region_pointer(
                    0, next_region_active=region1_is_new, ww=1, pp=0
                ),
            )
        elif region1_is_new:
            # Region 0 was already bootstrapped by an earlier file; patch
            # its NNN field only, preserving whatever WW/PP it already
            # had (no confirmed rule for updating those on every append --
            # see docs/memory.md sec. 4.1).
            r40 = self.get_register(XM_REGIONS[0][0])
            ww0 = (r40.get_bytes()[2] >> 4) & 0x0F
            pp0 = r40.get_bytes()[3]
            self.set_register(
                XM_REGIONS[0][0],
                self._build_region_pointer(0, next_region_active=True, ww=ww0, pp=pp0),
            )

        if region1_is_new:
            # Confirmed against tests/data/3x-xm.dm41 and 6x-xm.dm41 (both
            # real captures with a genuinely-spanning file): ww=0, and
            # pp equal to XM_REGIONS[0][0] in both -- reads like a fixed
            # back-link to region 0's own pointer register rather than a
            # file count (both dumps have a different file count but the
            # identical pp).
            self.set_register(
                XM_REGIONS[1][0],
                self._build_region_pointer(
                    1, next_region_active=False, ww=0, pp=XM_REGIONS[0][0]
                ),
            )

        return XMFile(
            memory=self._memory,
            header_addr=header_addr,
            file_type=file_type,
            name=padded_name,
            segments=segments,
            declared_length=register_length,
            byte_length=byte_length,
        )

    def remove_file(self, header_addr: int) -> None:
        """
        Removes the file whose header is at header_addr.

        There's no support (yet -- same caveat as add_file()) for reusing
        space in place, so this works by removing the target from
        list_files()'s result, wiping every register either XM region can
        touch (plus both region pointer registers) back to the "extended
        memory has never been used" state, and re-adding every surviving
        file from scratch, in its original address order, via add_file().
        This reuses add_file()'s already-tested packing/pointer logic
        instead of re-deriving the rules for an in-place delete, at the
        cost of rewriting every file that comes after the one being
        removed (their register addresses will change).

        Raises DM41LMemoryError if no file has a header at header_addr.
        """
        files = self.list_files()
        if not any(f.header_addr == header_addr for f in files):
            raise DM41LMemoryError(f"No XM file with a header at 0x{header_addr:03x}")

        # Snapshot each surviving file's content *before* clearing anything
        # -- get_numbers()/get_records()/get_instruction_bytes() all read
        # live from self._memory, so this has to happen while the original
        # layout is still intact.
        rebuild = []
        for f in files:
            if f.header_addr == header_addr:
                continue
            if f.file_type == self.TYPE_DATA:
                # get_data_lines() (not get_numbers()) so a Data file
                # containing alpha-text or raw-hex registers -- not just
                # plain numbers -- survives rebuilding correctly.
                rebuild.append((f.name, f.file_type, {"data_lines": f.get_data_lines()}))
            elif f.file_type == self.TYPE_ASCII:
                rebuild.append((f.name, f.file_type, {"records": f.get_records()}))
            elif f.file_type == self.TYPE_PROGRAM:
                rebuild.append(
                    (
                        f.name,
                        f.file_type,
                        {"instruction_bytes": f.get_instruction_bytes()},
                    )
                )
            else:
                raise DM41LMemoryError(f"Unknown file type for {f.name!r}: {f.file_type}")

        for lo, hi in XM_REGIONS:
            for addr in range(lo, hi + 1):
                self.set_register(addr, Register(size=7))

        for name, file_type, kwargs in rebuild:
            self.add_file(name, file_type, **kwargs)
