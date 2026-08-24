'''
Encoders for the single-program HP-41 file formats hp41uc (Leo Duran's
HP-41 User-Code File Converter, ~/Work/hp41uc) reads and writes -- so a
program exported from DM41L_Explorer can round-trip through hp41uc and
other tools built on the same formats (V41, LIFUTILS, EMU41, ...).

Ignores hp41uc's TXT format (the de-compiled/compiled FOCAL mnemonic
listing) -- that needs a full HP-41 opcode table to render as text, a
separate project from exporting/importing raw program bytes. RAW and DAT
are both byte-for-byte reproductions of hp41uc's own output, verified
against a locally-built copy of hp41uc itself (Source/convert.c's
copy_file()/write_raw_checksum()/write_dat_size()/write_dat_checksum()):
run a program's instruction bytes (Memory.get_program_bytes()) through
`encode_program_raw()`/`encode_program_dat()` here, and hp41uc's own
`/r=x.raw /d` conversion of the same bytes produces an identical file.

Both formats store exactly one program's instruction bytes (as returned
by Memory.get_program_bytes()) -- they carry no program *name*; that's
only ever recorded in the instruction bytes themselves, in the global
label header (see docs/program.md sec 5.2).

`decode_program_raw()`/`decode_program_dat()` are the reverse direction --
recovering the instruction bytes from an existing RAW/DAT file, verifying
its checksum along the way. Round-trip-verified against
tests/data/tower.{raw,dat}: two real files hp41uc itself compiled from a
1088-byte program (tests/data/tower.txt) -- decoding either one recovers
identical instruction bytes, `find_program_end()` confirms they form one
well-formed program, and re-encoding reproduces both files byte for byte.
These decoders are not wired into a GUI Import yet (that also needs
program-memory chain-splicing logic -- see project notes); they exist so
a RAW/DAT file's instruction bytes can be recovered and inspected/
verified without hand-parsing the format.

`encode_program_ppc()`/`decode_program_ppc()` handle a third, unlabeled
format found alongside real RAW/DAT/TXT files for the same programs
(~/Work/DM41/TowerOfSkelos, given the ".ppc" suffix by whoever saved them
-- no hp41uc mode produces it, and it isn't HP's WND format either).
Reverse-engineered by comparing those files directly: a PPC file turned
out to be byte-for-byte identical to its own DAT sibling, except with a
newline (0x0A) inserted every 50 characters and one trailing newline --
i.e. it's just DAT's hex text word-wrapped for display or printing, not a
distinct binary layout. (The programs in that sample set were originally
a magazine listing in the PPC Calculator Journal, which may explain both
the name and the wrapping -- printed hex dumps need line breaks -- but
that's a guess, not confirmed.) `decode_program_ppc()` strips whitespace
and defers to `decode_program_dat()`; `encode_program_ppc()` wraps
`encode_program_dat()`'s own output. Verified against the two real PPC
files this was reverse-engineered from: decoding either one and
re-encoding the result reproduces the original file exactly.
'''

from .opcode_scan import find_program_end
from .registers import DM41LMemoryError


def _checksum(data: bytes) -> int:
    '''Plain byte-sum checksum, mod 256 -- hp41uc's copy_raw_blocks()/
    copy_dat_blocks() checksum loop (`*pchksum += buf[j]`).'''
    return sum(data) % 256


def encode_program_raw(data: bytes) -> bytes:
    '''
    hp41uc RAW format (Source/hp41uc.c's `/r` help text):
    `[compiled code] + [1-byte checksum] + [trailer]`, where the trailer
    is zero-padding so the total file length is a multiple of 256 bytes
    (hp41uc's write_raw_checksum(), bufsize=256) -- if `data` is already
    an exact multiple of 256 bytes, a full extra 256-byte block is
    appended (checksum byte + 255 zero bytes), matching hp41uc exactly.
    '''
    checksum = _checksum(data)
    pad_len = 256 - (len(data) % 256)
    trailer = bytes([checksum]) + bytes(pad_len - 1)
    return data + trailer


def encode_program_dat(data: bytes) -> bytes:
    '''
    hp41uc DAT format (Source/hp41uc.c's `/d` help text):
    `[4-byte header] + [compiled code] + [2-byte checksum]`, all as
    upper-case ASCII hex digits. The header is `data`'s length as a
    big-endian 16-bit value; the checksum is the sum of `data`'s bytes
    plus the header's own two raw bytes (hp41uc's copy_file() FILE_DAT
    branch: `chksum += size_lo_byte + size_hi_byte` on top of
    copy_dat_blocks()'s data-byte sum), all mod 256.

    Raises ValueError if `data` is longer than 65535 bytes (the format's
    4-hex-digit header can't represent a larger size).
    '''
    length = len(data)
    if length > 0xFFFF:
        raise ValueError(
            f"Program is {length} bytes, too long for DAT format's "
            "16-bit length header (max 65535)."
        )
    size_hi = (length >> 8) & 0xFF
    size_lo = length & 0xFF
    checksum = (_checksum(data) + size_lo + size_hi) % 256
    header = f"{length:04X}".encode("ascii")
    body = data.hex().upper().encode("ascii")
    trailer = f"{checksum:02X}".encode("ascii")
    return header + body + trailer


def decode_program_raw(data: bytes) -> bytes:
    '''
    Recovers a program's instruction bytes from an hp41uc RAW file
    (`encode_program_raw()`'s own format). RAW carries no length header
    of its own, so this uses `find_program_end()` -- the same forward
    opcode scan `Memory.get_program_bytes()` uses -- to find where the
    compiled code ends and the checksum trailer begins, then verifies
    that checksum byte.

    Raises DM41LMemoryError if no terminating END is found, if there's no
    checksum byte after it, or if the checksum doesn't match.
    '''
    length = find_program_end(data)
    if length is None:
        raise DM41LMemoryError(
            "Could not find a terminating END in this RAW file's compiled code."
        )
    if length >= len(data):
        raise DM41LMemoryError(
            "RAW file has no checksum byte after its compiled code."
        )
    instruction_bytes = data[:length]
    checksum = data[length]
    expected = _checksum(instruction_bytes)
    if checksum != expected:
        raise DM41LMemoryError(
            f"RAW file checksum mismatch: expected 0x{expected:02X}, "
            f"found 0x{checksum:02X}."
        )
    return instruction_bytes


def decode_program_dat(data: bytes) -> bytes:
    '''
    Recovers a program's instruction bytes from an hp41uc DAT file
    (`encode_program_dat()`'s own format): reads the 4-hex-digit length
    header, decodes that many ASCII-hex-encoded bytes, and verifies the
    trailing 2-hex-digit checksum.

    Raises DM41LMemoryError if `data` is too short for its own declared
    length, contains non-hex-digit data, or the checksum doesn't match.
    '''
    if len(data) < 6:
        raise DM41LMemoryError(
            "DAT file is too short for a 4-byte header and 2-byte checksum."
        )
    try:
        length = int(data[:4], 16)
    except ValueError as e:
        raise DM41LMemoryError(
            f"DAT file's 4-byte header isn't hex digits: {data[:4]!r}."
        ) from e

    body_hex = data[4 : 4 + 2 * length]
    checksum_hex = data[4 + 2 * length : 4 + 2 * length + 2]
    if len(body_hex) != 2 * length or len(checksum_hex) != 2:
        raise DM41LMemoryError(
            f"DAT file is shorter than its own declared length ({length} bytes)."
        )
    try:
        instruction_bytes = bytes.fromhex(body_hex.decode("ascii"))
        checksum = int(checksum_hex, 16)
    except (ValueError, UnicodeDecodeError) as e:
        raise DM41LMemoryError("DAT file contains non-hex-digit data.") from e

    size_hi = (length >> 8) & 0xFF
    size_lo = length & 0xFF
    expected = (_checksum(instruction_bytes) + size_lo + size_hi) % 256
    if checksum != expected:
        raise DM41LMemoryError(
            f"DAT file checksum mismatch: expected 0x{expected:02X}, "
            f"found 0x{checksum:02X}."
        )
    return instruction_bytes


_PPC_LINE_WIDTH = 50

# ASCII whitespace decode_program_ppc() strips before handing off to
# decode_program_dat() -- covers the plain "\n" the two real PPC sample
# files use, plus "\r" in case a file has picked up CRLF line endings
# (e.g. from being opened/resaved on Windows) along the way.
_PPC_WHITESPACE = b" \t\r\n\v\f"


def encode_program_ppc(data: bytes) -> bytes:
    '''
    PPC format (see this module's docstring): `encode_program_dat()`'s own
    output, word-wrapped to `_PPC_LINE_WIDTH` (50) characters per line,
    with a trailing newline after the last line. Verified byte-for-byte
    against the two real PPC files this format was reverse-engineered
    from (~/Work/DM41/TowerOfSkelos's pack.ppc/tower-orig.ppc) --
    re-wrapping `encode_program_dat()`'s output for their own decoded
    instruction bytes reproduces both files exactly.
    '''
    dat_text = encode_program_dat(data)
    lines = [
        dat_text[i : i + _PPC_LINE_WIDTH]
        for i in range(0, len(dat_text), _PPC_LINE_WIDTH)
    ]
    return b"\n".join(lines) + b"\n"


def decode_program_ppc(data: bytes) -> bytes:
    '''
    Recovers a program's instruction bytes from a PPC file (see this
    module's docstring): strips the line-wrap whitespace back out and
    decodes what's left as a DAT file (`decode_program_dat()`), including
    that format's own checksum check.

    Raises DM41LMemoryError under the same conditions `decode_program_dat()`
    does, once whitespace has been removed.
    '''
    stripped = bytes(b for b in data if b not in _PPC_WHITESPACE)
    return decode_program_dat(stripped)
