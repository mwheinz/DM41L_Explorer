'''
A forward HP-41 FOCAL opcode-length scanner: given a stream of raw program
bytes starting at a global label's header, finds exactly how many bytes
that program occupies -- through its opcodes, up to and including its own
terminating END marker.

This is a direct Python port of `seek_end()` from hp41uc (Leo Duran's
HP-41 User-Code File Converter, ~/Work/hp41uc/Source/decomp.c), used there
to find a program's length within a raw byte stream when converting
between HP-41 file formats (.raw/.bin/.dat/.p41/.lif). It walks forward
byte-by-byte, classifying each opcode purely by its length class (single
byte; 2-byte; 3-byte; global END/LBL; variable-length ALPHA text) and
advancing a small state machine -- it does not need to understand what
any instruction *means*, only how many bytes it occupies, so it can skip
straight over ordinary opcodes and stop the instant it reaches a byte
sequence that is itself a plain END marker.

Deliberately independent of the "distance" field in the global label/END
chain that Memory.list_programs() walks (see ProgramInfo's docstring and
docs/program.md) -- that backward-chain distance is for GTO/XEQ-alpha's
global search, not a program's own forward length.

A label embedded partway through another label's own code (two global
entry points sharing one trailing END -- a legitimate, real HP-41
construct) is walked straight through, matching hp41uc's own behavior:
`SEEK_BYTE3_GLOBAL` only stops the scan when the third marker byte's high
nibble is *not* `0xF` (i.e. it's a plain END, not another label -- see
docs/program.md sec 5.1's `eeee ffff` byte).
'''

from typing import Optional

from .program_chain import decode_chain_marker, decode_label_name

# Opcode classification, mirroring hp41uc's decomp.c SEEK_* states.
_BYTE1 = "byte1"                 # expecting the start of a new instruction
_BYTE2_OF_2 = "byte2_of_2"       # 1 more byte of a 2-byte instruction
_BYTE2_OF_3 = "byte2_of_3"       # 2 more bytes of a 3-byte instruction
_BYTE3_OF_3 = "byte3_of_3"
_BYTE2_GLOBAL = "byte2_global"   # 2nd byte of a C0-CD END/LBL marker
_BYTE3_GLOBAL = "byte3_global"   # 3rd byte -- decides END vs. LBL
_BYTE4_GLOBAL = "byte4_global"   # LBL's key-assignment byte
_BYTE2_ALPHA = "byte2_alpha"     # 2nd byte of a 1D-1F ALPHA-text opcode
_BYTE_ALPHA = "byte_alpha"       # remaining ALPHA-text character bytes


def find_program_end(data: bytes) -> Optional[int]:  # pylint: disable=too-many-branches
    '''
    Scans `data` (raw program bytes, starting at a global label's own
    header -- see Memory.get_program_bytes()) forward, opcode by opcode,
    for this program's own terminating END marker.

    Returns the number of bytes from the start of `data` through
    (inclusive) that END marker's 3rd byte -- i.e. this program's total
    byte length, the same number CAT 1 reports. Returns None if `data` is
    exhausted before a terminating END is found (the program doesn't fit
    in the bytes given -- see Memory.get_program_bytes() for how the
    caller bounds this against program memory's actual floor).
    '''
    state = _BYTE1
    alpha_count = 0

    for i, c in enumerate(data):
        if state == _BYTE1:
            if 0x1D <= c <= 0x1F:
                state = _BYTE2_ALPHA
            elif (0x90 <= c <= 0xBF) or (0xCE <= c <= 0xCF):
                state = _BYTE2_OF_2
            elif 0xC0 <= c <= 0xCD:
                state = _BYTE2_GLOBAL
            elif 0xD0 <= c <= 0xEF:
                state = _BYTE2_OF_3
            elif 0xF0 <= c <= 0xFF:
                alpha_count = c & 0x0F
                if alpha_count:
                    state = _BYTE_ALPHA
            # else: a plain single-byte opcode -- stay in _BYTE1

        elif state == _BYTE2_OF_2:
            state = _BYTE1

        elif state == _BYTE2_OF_3:
            state = _BYTE3_OF_3

        elif state == _BYTE3_OF_3:
            state = _BYTE1

        elif state == _BYTE2_GLOBAL:
            state = _BYTE3_GLOBAL

        elif state == _BYTE3_GLOBAL:
            if c < 0xF0:
                # High nibble isn't F -- a plain END (or the permanent
                # .END.), not a label. This program is done.
                return i + 1
            alpha_count = c & 0x0F
            state = _BYTE4_GLOBAL if alpha_count else _BYTE1

        elif state == _BYTE4_GLOBAL:
            alpha_count -= 1
            state = _BYTE_ALPHA if alpha_count else _BYTE1

        elif state == _BYTE2_ALPHA:
            if c <= 0xF0:
                state = _BYTE1
            else:
                alpha_count = c & 0x0F
                state = _BYTE_ALPHA

        elif state == _BYTE_ALPHA:
            alpha_count -= 1
            if alpha_count == 0:
                state = _BYTE1

    return None


def scan_global_markers_forward(data: bytes) -> list:
    '''
    Walks `data` forward, opcode by opcode -- the exact same length-
    classification rules `find_program_end()` uses -- but instead of
    stopping at the first END-type marker, continues all the way through
    `data`, recording EVERY global marker (a label header, a plain END, or
    the permanent `.END.`) it passes, in physical/forward-discovery order.

    This is deliberately independent of each marker's own `bbb`/
    `distance_registers` "backlink" field -- what `list_global_chain()`/
    `program_chain.walk_chain()` both rely on to find anything at all.
    That backlink is a completely separate piece of bookkeeping from the
    marker's own physical position; a dump written by a tool other than a
    real HP-41/DM41L (or DM41L_Explorer itself) may never have set it at
    all, leaving `list_global_chain()` reporting "no programs" even
    though real, well-formed FOCAL code sits right there in the raw
    bytes -- see docs/program.md sec 5.4 and the PACK investigation that
    motivated this function (`Memory._forward_scan_programs()`/`pack()`,
    memory.py). Real PACK repairs exactly this: it re-derives the whole
    chain by reading the actual opcodes, the same way this function does.

    Returns a list of dicts, one per marker found, each shaped like
    `program_chain.decode_chain_marker()`'s own return (plus `"index"`,
    and for a label also `"name"`/`"key_assignment"` via
    `program_chain.decode_label_name()`) -- the same shape
    `program_chain.walk_chain()`'s entries already have, so callers that
    already know how to consume one can consume the other. A label
    embedded partway through another label's own code (two global entry
    points sharing one trailing END) is recorded as two separate entries,
    same as it physically is -- callers group consecutive labels under
    whichever END/`.END.` closes them, same as `Memory.list_programs()`
    already does for the backlink-walk case.

    Never raises -- like `find_program_end()`, an opcode that would run
    past the end of `data` (a genuinely truncated/corrupt stream) simply
    ends the scan at whatever's already been found, rather than raising.
    '''
    entries = []
    state = _BYTE1
    alpha_count = 0
    marker_start = None

    for i, c in enumerate(data):
        if state == _BYTE1:
            if 0x1D <= c <= 0x1F:
                state = _BYTE2_ALPHA
            elif (0x90 <= c <= 0xBF) or (0xCE <= c <= 0xCF):
                state = _BYTE2_OF_2
            elif 0xC0 <= c <= 0xCD:
                marker_start = i
                state = _BYTE2_GLOBAL
            elif 0xD0 <= c <= 0xEF:
                state = _BYTE2_OF_3
            elif 0xF0 <= c <= 0xFF:
                alpha_count = c & 0x0F
                if alpha_count:
                    state = _BYTE_ALPHA
            # else: a plain single-byte opcode -- stay in _BYTE1

        elif state == _BYTE2_OF_2:
            state = _BYTE1

        elif state == _BYTE2_OF_3:
            state = _BYTE3_OF_3

        elif state == _BYTE3_OF_3:
            state = _BYTE1

        elif state == _BYTE2_GLOBAL:
            state = _BYTE3_GLOBAL

        elif state == _BYTE3_GLOBAL:
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
                state = _BYTE1
            else:
                alpha_count = c & 0x0F
                state = _BYTE4_GLOBAL if alpha_count else _BYTE1

        elif state == _BYTE4_GLOBAL:
            alpha_count -= 1
            state = _BYTE_ALPHA if alpha_count else _BYTE1

        elif state == _BYTE2_ALPHA:
            if c <= 0xF0:
                state = _BYTE1
            else:
                alpha_count = c & 0x0F
                state = _BYTE_ALPHA

        elif state == _BYTE_ALPHA:
            alpha_count -= 1
            if alpha_count == 0:
                state = _BYTE1

    return entries
