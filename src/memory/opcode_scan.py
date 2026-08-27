'''
A forward HP-41 FOCAL opcode-length scanner: given a stream of raw program
bytes starting at a global label's header, finds exactly how many bytes
that program occupies by walking its opcodes, up to and including its own
terminating END marker.

This is a direct Python port of `seek_end()` from hp41uc (Leo Duran's
HP-41 User-Code File Converter, ~/Work/hp41uc/Source/decomp.c), used there
to find a program's length within a raw byte stream when converting
between HP-41 file formats. It walks forward
byte-by-byte, classifying each opcode by its length (single
byte; 2-byte; 3-byte; global END/LBL; variable-length ALPHA text) and
advancing a small state machine -- it does not understand what
any instruction *means*, only how many bytes it occupies.
'''

from enum import Enum
from typing import Optional

from .program_chain import decode_chain_marker, decode_label_name

# Opcode classification, mirroring hp41uc's decomp.c SEEK_* states.
class State(Enum):
    BYTE1 = 1          # expecting the start of a new instruction
    BYTE2_OF_2 = 2     # 1 more byte of a 2-byte instruction
    BYTE2_OF_3 = 3     # 2 more bytes of a 3-byte instruction
    BYTE3_OF_3 = 4
    BYTE2_GLOBAL = 5   # 2nd byte of a C0-CD END/LBL marker
    BYTE3_GLOBAL = 6   # 3rd byte -- decides END vs. LBL
    BYTE4_GLOBAL = 7   # LBL's key-assignment byte
    BYTE2_ALPHA = 8     # 2nd byte of a 1D-1F ALPHA-text opcode
    BYTE_ALPHA = 9     # remaining ALPHA-text character bytes


def find_program_end(data: bytes) -> Optional[int]:  # pylint: disable=too-many-branches
    '''
    Scans `data` (raw program bytes, starting at a global label's own
    header -- see Memory.get_program_bytes()) forward, opcode by opcode,
    for this program's own terminating END marker.

    Returns the number of bytes from the start of `data` through
    that END marker's 3rd byte, inclusive. This is the program's total
    byte length, the same number CAT 1 reports. Returns None if `data` is
    exhausted before a terminating END is found (the program doesn't fit
    in the bytes given -- see Memory.get_program_bytes() for how the
    caller bounds this against program memory's actual floor).
    '''
    state = State.BYTE1
    alpha_count = 0

    for i, c in enumerate(data):
        if state == State.BYTE1:
            if 0x1D <= c <= 0x1F:
                state = State.BYTE2_ALPHA
            elif (0x90 <= c <= 0xBF) or (0xCE <= c <= 0xCF):
                state = State.BYTE2_OF_2
            elif 0xC0 <= c <= 0xCD:
                state = State.BYTE2_GLOBAL
            elif 0xD0 <= c <= 0xEF:
                state = State.BYTE2_OF_3
            elif 0xF0 <= c <= 0xFF:
                alpha_count = c & 0x0F
                if alpha_count:
                    state = State.BYTE_ALPHA
            # else: a plain single-byte opcode -- stay in BYTE1

        elif state == State.BYTE2_OF_2:
            state = State.BYTE1

        elif state == State.BYTE2_OF_3:
            state = State.BYTE3_OF_3

        elif state == State.BYTE3_OF_3:
            state = State.BYTE1

        elif state == State.BYTE2_GLOBAL:
            state = State.BYTE3_GLOBAL

        elif state == State.BYTE3_GLOBAL:
            if c < 0xF0:
                # High nibble isn't F -- a plain END (or the permanent
                # .END.), not a label. This program is done.
                return i + 1
            alpha_count = c & 0x0F
            state = State.BYTE4_GLOBAL if alpha_count else State.BYTE1

        elif state == State.BYTE4_GLOBAL:
            alpha_count -= 1
            state = State.BYTE_ALPHA if alpha_count else State.BYTE1

        elif state == State.BYTE2_ALPHA:
            if c <= 0xF0:
                state = State.BYTE1
            else:
                alpha_count = c & 0x0F
                state = State.BYTE_ALPHA

        elif state == State.BYTE_ALPHA:
            alpha_count -= 1
            if alpha_count == 0:
                state = State.BYTE1

    return None


def scan_global_markers_forward(data: bytes) -> list:
    '''
    Walks `data` forward, opcode by opcode -- the exact same length-
    classification rules `find_program_end()` uses -- but instead of
    stopping at the first END-type marker, continues all the way through
    `data`, recording EVERY global marker (a label header, a plain END, or
    the permanent `.END.`) it passes, in physical/forward-discovery order.

    Never raises -- like `find_program_end()`, an opcode that would run
    past the end of `data` (a genuinely truncated/corrupt stream) simply
    ends the scan at whatever's already been found, rather than raising.
    '''
    entries = []
    state = State.BYTE1
    alpha_count = 0
    marker_start = None

    for i, c in enumerate(data):
        if state == State.BYTE1:
            if 0x1D <= c <= 0x1F:
                state = State.BYTE2_ALPHA
            elif (0x90 <= c <= 0xBF) or (0xCE <= c <= 0xCF):
                state = State.BYTE2_OF_2
            elif 0xC0 <= c <= 0xCD:
                marker_start = i
                state = State.BYTE2_GLOBAL
            elif 0xD0 <= c <= 0xEF:
                state = State.BYTE2_OF_3
            elif 0xF0 <= c <= 0xFF:
                alpha_count = c & 0x0F
                if alpha_count:
                    state = State.BYTE_ALPHA
            # else: a plain single-byte opcode -- stay in BYTE1

        elif state == State.BYTE2_OF_2:
            state = State.BYTE1

        elif state == State.BYTE2_OF_3:
            state = State.BYTE3_OF_3

        elif state == State.BYTE3_OF_3:
            state = State.BYTE1

        elif state == State.BYTE2_GLOBAL:
            state = State.BYTE3_GLOBAL

        elif state == State.BYTE3_GLOBAL:
            marker = decode_chain_marker(data, marker_start)
            entry = dict(marker)
            entry["index"] = marker_start
            if marker["is_label"]:
                name, key = decode_label_name(data, marker_start, marker["label_length"])
                entry["name"] = name
                entry["key_assignment"] = key
            entries.append(entry)

            if c < 0xF0:
                # A plain END (or the permanent .END.) -- not a label.
                state = State.BYTE1
            else:
                alpha_count = c & 0x0F
                state = State.BYTE4_GLOBAL if alpha_count else State.BYTE1

        elif state == State.BYTE4_GLOBAL:
            alpha_count -= 1
            state = State.BYTE_ALPHA if alpha_count else State.BYTE1

        elif state == State.BYTE2_ALPHA:
            if c <= 0xF0:
                state = State.BYTE1
            else:
                alpha_count = c & 0x0F
                state = State.BYTE_ALPHA

        elif state == State.BYTE_ALPHA:
            alpha_count -= 1
            if alpha_count == 0:
                state = State.BYTE1

    return entries
