"""
The DM41L/HP-41CX instruction set, keyed by the byte encoding used inside a
Key Assignment Register entry (docs/key_assignments.md sec 4.2/4.8) -- NOT
by the program-byte ("Instruction Prefix") encoding, which differs for the
nine low-code (<64) Assignable functions (see the module note below and
docs/key_assignments.md sec 5). Generated from docs/function_table.md's
merged table (Assignable=Yes single-byte functions) and its Extended
Functions ROM / Time ROM catalogs, via the two-byte XROM encoding confirmed
in docs/key_assignments.md sec 4.8:

    byte1 = 0xA0 + floor(xrom / 4)
    byte2 = ((xrom mod 4) << 6) | fn

This is a static data structure (per docs/key_assignments.md sec 6 item 5)
rather than something parsed from the markdown table at runtime -- re-run
the generation script (see CONTRIBUTING.md, or ask in the project's chat
history) if function_table.md ever changes.

CAVEAT (docs/key_assignments.md sec 5, still open as of this writing): for
the nine low-code Assignable functions (CAT, DEL, COPY, CLP, SIZE, BST,
SST, PACK, ASN -- codes 0x00-0x0F), SINGLE_BYTE_FUNCTIONS below assumes the
Key Assignment Register byte equals the function's plain decimal/hex code
from function_table.md -- e.g. CAT is assumed to be encoded as 0x00. This
matches the one synthetic-looking test fixture found so far
(keyassigntest.dm41) but has NOT been confirmed against a real device
capture with real KEYFLAGS bits set. Everything from 0x40 ('+') through
0xE0 (XEQ) is fully confirmed (docs sec 4.8); the XROM/peripheral entries
are fully confirmed too (docs sec 4.8, xrom-keyassignments.dm41).
"""

# Single raw function byte -> function name, for every built-in HP-41
# function function_table.md marks Assignable with a one-byte encoding.
# The low-code entries (< 0x40) carry the sec-5 caveat above.
SINGLE_BYTE_FUNCTIONS = {
    0x00: 'CAT',
    0x02: 'DEL',
    0x03: 'COPY',
    0x04: 'CLP',
    0x06: 'SIZE',
    0x07: 'BST',
    0x08: 'SST',
    0x0A: 'PACK',
    0x0F: 'ASN',
    0x40: '+',
    0x41: '-',
    0x42: '*',
    0x43: '/',
    0x44: 'X<Y?',
    0x45: 'X>Y?',
    0x46: 'X≤Y?',
    0x47: 'Σ+',
    0x48: 'Σ-',
    0x49: 'HMS+',
    0x4A: 'HMS-',
    0x4B: 'MOD',
    0x4C: '%',
    0x4D: '%CH',
    0x4E: 'P→R',
    0x4F: 'R→P',
    0x50: 'LN',
    0x51: 'X↑2',
    0x52: 'SQRT',
    0x53: 'Y↑X',
    0x54: 'CHS',
    0x55: 'E↑X',
    0x56: 'LOG',
    0x57: '10↑X',
    0x58: 'E↑X-1',
    0x59: 'SIN',
    0x5A: 'COS',
    0x5B: 'TAN',
    0x5C: 'ASIN',
    0x5D: 'ACOS',
    0x5E: 'ATAN',
    0x5F: 'DEC',
    0x60: '1/X',
    0x61: 'ABS',
    0x62: 'FACT',
    0x63: 'X≠0?',
    0x64: 'X>0?',
    0x65: 'LNX+1',
    0x66: 'X<0?',
    0x67: 'X=0?',
    0x68: 'INT',
    0x69: 'FRC',
    0x6A: 'D→R',
    0x6B: 'R→D',
    0x6C: '→HMS',
    0x6D: '→HR',
    0x6E: 'RND',
    0x6F: '→OCT',
    0x70: 'CLΣ',
    0x71: 'X<>Y',
    0x72: 'PI',
    0x73: 'CLST',
    0x74: 'R↑',
    0x75: 'RDN',
    0x76: 'LASTX',
    0x77: 'CLX',
    0x78: 'X=Y?',
    0x79: 'X≠Y?',
    0x7A: 'SIGN',
    0x7B: 'X≤0?',
    0x7C: 'MEAN',
    0x7D: 'SDEV',
    0x7E: 'AVIEW',
    0x7F: 'CLD',
    0x80: 'DEG',
    0x81: 'RAD',
    0x82: 'GRAD',
    0x83: 'ENTER↑',
    0x84: 'STOP',
    0x85: 'RTN',
    0x86: 'BEEP',
    0x87: 'CLA',
    0x88: 'ASHF',
    0x89: 'PSE',
    0x8A: 'CLRG',
    0x8B: 'AOFF',
    0x8C: 'AON',
    0x8D: 'OFF',
    0x8E: 'PROMPT',
    0x8F: 'ADV',
    0x90: 'RCL',
    0x91: 'STO',
    0x92: 'ST+',
    0x93: 'ST-',
    0x94: 'ST*',
    0x95: 'ST/',
    0x96: 'ISG',
    0x97: 'DSE',
    0x98: 'VIEW',
    0x99: 'ΣREG',
    0x9A: 'ASTO',
    0x9B: 'ARCL',
    0x9C: 'FIX',
    0x9D: 'SCI',
    0x9E: 'ENG',
    0x9F: 'TONE',
    0xA8: 'SF',
    0xA9: 'CF',
    0xAA: 'FS?C',
    0xAB: 'FC?C',
    0xAC: 'FS?',
    0xAD: 'FC?',
    0xCE: 'X<>',
    0xCF: 'LBL',
    0xD0: 'GTO',
    0xE0: 'XEQ',
}

# (byte1, byte2) -> function name, for every Extended Functions ROM (25,xx)
# and Time ROM (26,xx) function -- confirmed encoding, docs sec 4.8.
XROM_FUNCTIONS = {
    (0xA6, 0x41): 'ALENG',
    (0xA6, 0x42): 'ANUM',
    (0xA6, 0x43): 'APPCHR',
    (0xA6, 0x44): 'APPREC',
    (0xA6, 0x45): 'ARCLREC',
    (0xA6, 0x46): 'AROT',
    (0xA6, 0x47): 'ATOX',
    (0xA6, 0x48): 'CLFL',
    (0xA6, 0x49): 'CLKEYS',
    (0xA6, 0x4A): 'CRFLAS',
    (0xA6, 0x4B): 'CRFLD',
    (0xA6, 0x4C): 'DELCHR',
    (0xA6, 0x4D): 'DELREC',
    (0xA6, 0x4E): 'EMDIR',
    (0xA6, 0x4F): 'FLSIZE',
    (0xA6, 0x50): 'GETAS',
    (0xA6, 0x51): 'GETKEY',
    (0xA6, 0x52): 'GETP',
    (0xA6, 0x53): 'GETR',
    (0xA6, 0x54): 'GETREC',
    (0xA6, 0x55): 'GETRX',
    (0xA6, 0x56): 'GETSUB',
    (0xA6, 0x57): 'GETX',
    (0xA6, 0x58): 'INSCHR',
    (0xA6, 0x59): 'INSREC',
    (0xA6, 0x5A): 'PASN',
    (0xA6, 0x5B): 'PCLPS',
    (0xA6, 0x5C): 'POSA',
    (0xA6, 0x5D): 'POSFL',
    (0xA6, 0x5E): 'PSIZE',
    (0xA6, 0x5F): 'PURFL',
    (0xA6, 0x60): 'RCLFLAG',
    (0xA6, 0x61): 'RCLPT',
    (0xA6, 0x62): 'RCLPTA',
    (0xA6, 0x63): 'REGMOVE',
    (0xA6, 0x64): 'REGSWAP',
    (0xA6, 0x65): 'SAVEAS',
    (0xA6, 0x66): 'SAVEP',
    (0xA6, 0x67): 'SAVER',
    (0xA6, 0x68): 'SAVERX',
    (0xA6, 0x69): 'SAVEX',
    (0xA6, 0x6A): 'SEEKPT',
    (0xA6, 0x6B): 'SEEKPTA',
    (0xA6, 0x6C): 'SIZE?',
    (0xA6, 0x6D): 'STOFLAG',
    (0xA6, 0x6E): 'X<>F',
    (0xA6, 0x6F): 'XTOA',
    (0xA6, 0x71): 'ASROOM',
    (0xA6, 0x72): 'CLRGX',
    (0xA6, 0x73): 'ED',
    (0xA6, 0x74): 'EMDIRX',
    (0xA6, 0x75): 'EMROOM',
    (0xA6, 0x76): 'GETKEYX',
    (0xA6, 0x77): 'RESZFL',
    (0xA6, 0x78): 'ΣREG?',
    (0xA6, 0x79): 'X=NN?',
    (0xA6, 0x7A): 'X≠NN?',
    (0xA6, 0x7B): 'X<NN?',
    (0xA6, 0x7C): 'X<=NN?',
    (0xA6, 0x7D): 'X>NN?',
    (0xA6, 0x7E): 'X>=NN?',
    (0xA6, 0x81): 'ADATE',
    (0xA6, 0x82): 'ALMCAT',
    (0xA6, 0x83): 'ALMNOW',
    (0xA6, 0x84): 'ATIME',
    (0xA6, 0x85): 'ATIME24',
    (0xA6, 0x86): 'CLK12',
    (0xA6, 0x87): 'CLK24',
    (0xA6, 0x88): 'CLKT',
    (0xA6, 0x89): 'CLKTD',
    (0xA6, 0x8A): 'CLOCK',
    (0xA6, 0x8B): 'CORRECT',
    (0xA6, 0x8C): 'DATE',
    (0xA6, 0x8D): 'DATE+',
    (0xA6, 0x8E): 'DDAYS',
    (0xA6, 0x8F): 'DMY',
    (0xA6, 0x90): 'DOW',
    (0xA6, 0x91): 'MDY',
    (0xA6, 0x92): 'RCLAF',
    (0xA6, 0x93): 'RCLSW',
    (0xA6, 0x94): 'RUNSW',
    (0xA6, 0x95): 'SETAF',
    (0xA6, 0x96): 'SETDATE',
    (0xA6, 0x97): 'SETIME',
    (0xA6, 0x98): 'SETSW',
    (0xA6, 0x99): 'STOPSW',
    (0xA6, 0x9A): 'SW',
    (0xA6, 0x9B): 'T+X',
    (0xA6, 0x9C): 'TIME',
    (0xA6, 0x9D): 'XYZALM',
    (0xA6, 0x9F): 'CLALMA',
    (0xA6, 0xA0): 'CLALMX',
    (0xA6, 0xA1): 'CLRALMS',
    (0xA6, 0xA2): 'RCLALM',
    (0xA6, 0xA3): 'SWPT',
}

# Reverse lookups (name -> byte(s)), built from the tables above rather
# than transcribed a second time so the two directions can never drift
# apart.
SINGLE_BYTE_NAMES = {v: k for k, v in SINGLE_BYTE_FUNCTIONS.items()}
XROM_NAMES = {v: k for k, v in XROM_FUNCTIONS.items()}


def function_name_for_bytes(fn_byte1: int, fn_byte2) -> str:
    """Looks up the display name for a decoded Key Assignment Register
    entry's function byte(s) (`fn_byte2` is None for a single-byte
    built-in function -- see memory.Memory._decode_key_assignment_entries).
    Returns a "0xNN" / "0xNN 0xNN" fallback string, never raises, if the
    byte(s) don't match any known function -- callers that want to
    distinguish "known function" from "raw hex" should check
    SINGLE_BYTE_FUNCTIONS/XROM_FUNCTIONS directly instead."""
    if fn_byte2 is None:
        name = SINGLE_BYTE_FUNCTIONS.get(fn_byte1)
        return name if name is not None else f"0x{fn_byte1:02X}"
    name = XROM_FUNCTIONS.get((fn_byte1, fn_byte2))
    return name if name is not None else f"0x{fn_byte1:02X} 0x{fn_byte2:02X}"


def bytes_for_function_name(name: str):
    """Looks up the Key Assignment Register byte encoding for a function
    name from either table above. Returns an int (single-byte function)
    or a (byte1, byte2) tuple (XROM/peripheral function). Raises
    ValueError if `name` isn't a known assignable function."""
    if name in SINGLE_BYTE_NAMES:
        return SINGLE_BYTE_NAMES[name]
    if name in XROM_NAMES:
        return XROM_NAMES[name]
    raise ValueError(f"Unknown assignable function: {name!r}")
