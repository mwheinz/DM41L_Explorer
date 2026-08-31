'''
Encoders for exporting a single HP41 program file.

Supports RAW, DAT, and "PPC", which is a DAT that's been broken into multiple
lines (as seen in PPC Calculator Journal program listings).

Does not support decompiling into text files (yet).

`encode_program_[raw, dat, ppc]()`/`encode_program_[raw, dat, ppc]()` convert
a program into a file.

`decode_program_[raw, dat, ppc]()`/`decode_program_[raw, dat, ppc]()` are the
reverse direction -- read a RAW/DAT file, and convert it to a program.
'''

from .opcode_scan import find_program_end
from .registers import DM41LMemoryError


def _checksum(data: bytes) -> int:
    '''Plain byte-sum checksum, mod 256 -- hp41uc's copy_raw_blocks()/
    copy_dat_blocks() checksum loop (`*pchksum += buf[j]`).'''
    return sum(data) % 256


def encode_program_raw(data: bytes) -> bytes:
    '''
    RAW format: (Source/hp41uc.c's `/r` help text):
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
    DAT format: (Source/hp41uc.c's `/d` help text):
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
    Recovers a program's instruction bytes from an HP41 RAW file
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


# ASCII whitespace decode_program_dat() strips before
# decoding the hex data. This allows dat files to be formatted for
# readability (i.e., as in a "PPC" formatted file).

_DAT_WHITESPACE = b" \t\r\n\v\f"


def decode_program_dat(data: bytes) -> bytes:
    '''
    Recovers a program's instruction bytes from an HP41 DAT (or a "PPC" file
    (DAT that has newlines in it...) Reads the header, decodes that many
    ASCII-hex-encoded bytes, and verifies the trailing 2-hex-digit checksum.

    Raises DM41LMemoryError if `data` is too short for its own declared
    length, contains non-hex-digit data, or the checksum doesn't match.
    '''
    stripped = bytes(b for b in data if b not in _DAT_WHITESPACE)

    if len(stripped) < 6:
        raise DM41LMemoryError(
            "DAT file is too short for a 4-byte header and 2-byte checksum."
        )

    try:
        length = int(stripped[:4], 16)
    except ValueError as e:
        raise DM41LMemoryError(
            f"DAT file's 4-byte header isn't hex digits: {stripped[:4]!r}."
        ) from e

    body_hex = stripped[4 : 4 + 2 * length]
    checksum_hex = stripped[4 + 2 * length : 4 + 2 * length + 2]
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

def encode_program_ppc(data: bytes) -> bytes:
    '''
    PPC format: DAT format that's word-wrapped to `_PPC_LINE_WIDTH` (50)
    characters per line, with a trailing newline after the last line. Based on
    the formatting of HP41 programs in the PPC Calculator Journal program
    listings.

    This is entirely to make the output file easier for a human to read.
    '''
    dat_text = encode_program_dat(data)
    lines = [
        dat_text[i : i + _PPC_LINE_WIDTH]
        for i in range(0, len(dat_text), _PPC_LINE_WIDTH)
    ]
    return b"\n".join(lines) + b"\n"
