'''
Converting between raw HP-41 program instruction bytes and a plain-text
keystroke listing -- see docs/program_text_io_plan.md's suggested
phasing (sec. 7): phase 1, `encode_program_txt()` (bytes -> text,
decompile), and phase 2, `decode_program_txt()` (text -> bytes, compile).

`encode_program_txt()` turns a program's instruction bytes (the same
bytes `ProgramMemory.get_program_bytes()`/`decode_program_raw()`/
`decode_program_dat()` deal in) into text closely matching hp41uc's own
decompiler conventions (Leo Duran's HP-41 User-Code File Converter,
~/Work/hp41uc/Source/decomp.c) -- one instruction per line, `;` comments,
quoted ALPHA strings, `XROM mm,ff` with a name comment, and so on.

`decode_program_txt()` is its reverse: it tokenizes that same kind of
text (hp41uc's own `tower.txt`/`tower-update2.txt` sample included, not
just this module's own decompile output) and reassembles the exact
instruction bytes, reusing the same opcode table -- see its own
docstring, further down, for the compile-specific design notes (the
tokenizer, the two-numeric-literals-need-a-0x00-separator quirk on the
way back in, and the "every global marker's chain-link fields are always
zero" finding that makes `LBL "NAME"`/`END` byte-identical to hp41uc's
own compiled output without any cross-instruction bookkeeping).

The opcode table itself was derived by cross-checking three sources
against each other, since ~/Work/hp41uc's C source isn't reachable from
every environment this project is developed in:

  1. `opcode_scan.py`'s byte-length classification (itself a port of
     hp41uc's `seek_end()`) -- which byte ranges are 1/2/3-byte or
     variable-length ALPHA text. This module's own dispatch mirrors
     those exact ranges, so it can never desync from the already-tested
     length scanner.
  2. `functions.py`'s SINGLE_BYTE_FUNCTIONS/XROM_FUNCTIONS tables --
     already confirmed (per docs/program_text_io_plan.md sec 3) to give
     the correct in-*program*-byte mnemonic for every entry at 0x40 and
     above, and the correct XROM (0xA6, byte2) name table for the two
     ROM modules (Extended Functions, Time) the DM41L emulates.
  3. `src/tests/data/tower.raw`/`tower.txt` -- a real 1088-byte program
     hp41uc itself compiled and decompiled, used to empirically pin down
     every byte range/format `functions.py` doesn't already cover:
     digit-literal encoding, the RCL/STO compact single-byte forms,
     compact local-numbered LBL/GTO forms, the IND/stack-register operand
     scheme, the "append to ALPHA" leading-`>` notation, the XROM
     "mm,ff" catalog-number formula, and the exact END trailer spacing.
     See that fixture's own module docstring in test_program_export.py
     for its provenance.

A few of the derivations below are marked "inferred, not directly
observed" where tower.txt doesn't happen to exercise that specific byte
value -- they follow the same pattern as a directly-confirmed neighbor
(e.g. the stack-register byte assignments for T/Z/L, sitting either side
of the two directly-observed values for Y and X) rather than being
guesses out of nothing, but should be revisited if a fixture ever
contradicts them.
'''

import re
from typing import List, Optional, Tuple

from .functions import (
    SINGLE_BYTE_FUNCTIONS,
    SINGLE_BYTE_NAMES,
    XROM_FUNCTIONS,
    normalize_function_name_input,
)
from .program_chain import decode_chain_marker, encode_chain_marker

# -- Digit-literal ("number") encoding ---------------------------------
#
# A numeric literal is spelled out byte-for-byte in normal left-to-right
# reading order, one byte per character, using this table -- confirmed
# against every number literal in tower.txt (integers, decimals, negative
# numbers, and scientific notation): e.g. "-1" is bytes 0x1C, 0x11 (the
# CHS/minus glyph, then digit '1') and "1.006" is 0x11, 0x1A, 0x10, 0x10,
# 0x16 ('1', '.', '0', '0', '6'). hp41uc's own decompiler inserts a single
# space between the mantissa and a trailing "E<exponent>" (tower.txt's
# "3 E3" for 3000, vs. bare "E2" when there's no mantissa before it at
# all) -- see _render_number_run() below.
_DIGIT_CHARS = {
    0x10: "0", 0x11: "1", 0x12: "2", 0x13: "3", 0x14: "4",
    0x15: "5", 0x16: "6", 0x17: "7", 0x18: "8", 0x19: "9",
    0x1A: ".", 0x1B: "E", 0x1C: "-",
}

# -- Compact single-byte RCL/STO forms (registers 00-15 only) ----------
#
# NOT part of functions.py's tables (which are keyed to the Key
# Assignment Register's encoding, where these compact program-only forms
# don't exist at all -- see that module's own docstring). Confirmed
# against tower.txt: "RCL 07"/"RCL 14"/"RCL 15" all decompile to a single
# byte (0x27, 0x2E, 0x2F -- i.e. 0x20 + register), and "STO 07"..."STO 15"
# likewise (0x37..0x3F, i.e. 0x30 + register). Register 16 and up always
# use the general 2-byte 0x90/0x91-prefixed form instead (also confirmed:
# "STO 16" is 0x91 0x10, not a compact form).
_RCL_COMPACT_BASE = 0x20
_STO_COMPACT_BASE = 0x30
_COMPACT_REGISTER_MAX = 0x0F  # registers 00-15

# -- Compact single-byte local-numbered LBL forms (00-14 only) ---------
#
# Confirmed against tower.txt: "LBL 00".."LBL 09" all decompile to a
# single byte, 0x01 + the label number (0x01 = LBL 00, ..., 0x0A = LBL
# 09). Label numbers 15-99 use the general 2-byte 0xCF-prefixed form
# instead (confirmed: "LBL 20"/"LBL 21"/"LBL 92" are all 0xCF <value>).
# Local *letter* labels A-J also use that same 2-byte 0xCF form, with
# values 0x66-0x6F (see _decode_register_operand below) -- confirmed
# separately via src/tests/data/samplelabels.dm41, per project notes.
_LBL_COMPACT_BASE = 0x01
_LBL_COMPACT_MAX = 14

# -- Compact 2-byte local-numbered GTO forms (00-14 only) ---------------
#
# Confirmed against tower.txt: "GTO 00".."GTO 06" all decompile to 2
# bytes, (0xB1 + target number) followed by a fixed 0x00 byte (the second
# byte never varies across every example in the fixture, so it's treated
# here as a fixed/reserved byte, not a second operand). Local numbers
# 15-99 (and presumably local letters, though unobserved in this
# fixture) use the general 3-byte 0xD0-prefixed form instead (confirmed:
# "GTO 20"/"GTO 73" are 0xD0 0x00 <value>). GTO has no comparable compact
# form for XEQ -- XEQ always uses the 3-byte 0xE0 form regardless of how
# low the target number is (confirmed: "XEQ 07" is 0xE0 0x00 0x07).
_GTO_COMPACT_BASE = 0xB1
_GTO_COMPACT_MAX = 14
_GTO_COMPACT_FIXED_BYTE2 = 0x00

# 0xAF and 0xB0 -- the two bytes between GTO-IND (0xAE) and the compact
# GTO block (0xB1-0xBF) -- are confirmed-spare, unassigned opcodes: see
# docs/program_text_io_plan.md sec 2.3 ("hp41uc also emits informational
# ... comments for two truly unassigned 'spare' opcode bytes (0xAF,
# 0xB0)"). They fall in opcode_scan's 2-byte-instruction range, so each
# still consumes one operand byte; see _decode_2byte() below.
_SPARE_OPCODES = frozenset({0xAF, 0xB0})

# -- Register/flag/data "descriptor" operand byte -----------------------
#
# Shared by every 2-byte instruction that takes a register, flag, or
# other small numeric operand (RCL, STO, ST+/-/*//, ISG, DSE, VIEW,
# SIGMAREG, ASTO, ARCL, SF, CF, FS?/FC?(C), X<>, and the compact/general
# LBL and GTO/XEQ forms above). The high bit (0x80) flags "indirect
# through" -- confirmed: "STO IND 16" is STO + 0x90 (0x80 | 0x10), vs.
# plain "STO 16" being STO + 0x10. Below that:
#   0x00-0x63 (0-99): direct register/flag/label number.
#   0x66-0x6F: local letter labels A-J (10 slots -- confirmed elsewhere,
#     see samplelabels.dm41 per project notes; not exercised by name in
#     tower.txt, since it has no letter-labelled GTO/XEQ/LBL, but the
#     encoding matches the already-established local-letter table).
#   0x70-0x74: the stack registers T/Z/Y/X/L. Only X (0x73) and Y (0x72)
#     are directly confirmed in tower.txt ("GTO IND X" and "ARCL X" both
#     decode operand 0x73; "STO IND Y" decodes operand 0xF2 = 0x80 |
#     0x72). T (0x70), Z (0x71), and L/LASTX (0x74) are *inferred* by
#     the consistent surrounding pattern (the four stack registers listed
#     in their conventional T,Z,Y,X display order, with L immediately
#     after) rather than directly observed -- flagged here in case a
#     future fixture disagrees.
# Anything else doesn't decode to a known operand -- callers should treat
# that as an unrecognized/spare instruction (see _format_unknown()).
_STACK_REGISTER_NAMES = {
    0x70: "T",   # inferred -- not directly observed in tower.txt
    0x71: "Z",   # inferred -- not directly observed in tower.txt
    0x72: "Y",   # confirmed: "STO IND Y" -> STO 0xF2 (0x80 | 0x72)
    0x73: "X",   # confirmed: "GTO IND X" -> GTO IND 0x73; "ARCL X" -> ARCL 0x73
    0x74: "L",   # inferred -- not directly observed in tower.txt
}


def _decode_register_operand(byte: int) -> Optional[str]:
    '''Decodes a "descriptor" operand byte (see the module-level comment
    above) into its display text -- a 2-digit register/flag number, a
    local letter label, a stack register name, or an "IND "-prefixed
    version of any of those. Returns None if `byte` doesn't decode to
    anything recognized.'''
    indirect = bool(byte & 0x80)
    base = byte & 0x7F
    if 0 <= base <= 0x63:
        core = f"{base:02d}"
    elif 0x66 <= base <= 0x6F:
        core = chr(ord("A") + (base - 0x66))
    elif base in _STACK_REGISTER_NAMES:
        core = _STACK_REGISTER_NAMES[base]
    else:
        return None
    return f"IND {core}" if indirect else core


def _decode_small_digit_operand(byte: int) -> Optional[str]:
    '''FIX/SCI/ENG/TONE's own operand style: a bare 0-9 digit with no
    zero-padding (confirmed: "FIX 0"/"FIX 2"/"TONE 0"/"TONE 2", never
    "FIX 00"/"TONE 02" -- contrast with _decode_register_operand()'s
    2-digit style used by every other operand-taking instruction). Falls
    back to the general register-descriptor decode for anything outside
    0-9 (e.g. an IND form), which isn't exercised by tower.txt but is a
    reasonable, safe fallback rather than silently misrendering it.'''
    if 0 <= byte <= 9:
        return str(byte)
    return _decode_register_operand(byte)


# Mnemonic names for every 2-byte-instruction prefix byte this module
# knows how to decode, split by which operand-formatting rule applies.
# Reuses functions.py's SINGLE_BYTE_FUNCTIONS directly for the mnemonic
# text -- confirmed reusable for program-byte decoding at every entry
# 0x40 and above (see this module's own docstring, point 2).
_REGISTER_OPERAND_PREFIXES = {
    0x90: "RCL", 0x91: "STO", 0x92: "ST+", 0x93: "ST-",
    0x94: "ST*", 0x95: "ST/", 0x96: "ISG", 0x97: "DSE",
    0x98: "VIEW", 0x99: "SIGMAREG", 0x9A: "ASTO", 0x9B: "ARCL",
    0xA8: "SF", 0xA9: "CF", 0xAA: "FS?C", 0xAB: "FC?C",
    0xAC: "FS?", 0xAD: "FC?",
    0xCE: "X<>",
}
_SMALL_DIGIT_OPERAND_PREFIXES = {
    0x9C: "FIX", 0x9D: "SCI", 0x9E: "ENG", 0x9F: "TONE",
}

# functions.py's own names for 0x99/SIGMAREG use the real Sigma glyph
# ("ΣREG"); hp41uc's own text format is 7-bit ASCII, so this module uses
# a plain-ASCII spelling for it directly above rather than round-tripping
# through functions.py's unicode name -- not exercised by tower.txt, but
# consistent with the ASCII substitutions confirmed for other symbols
# below (ASCII_DISPLAY_NAMES).

# hp41uc-style ASCII spellings for the handful of SINGLE_BYTE_FUNCTIONS
# names that contain a non-ASCII symbol. '<=' and '#' are directly
# confirmed against tower.txt ("X<=Y?", "X<=0?", "X#Y?", "X#0?"); '->HMS'
# collapsing to bare "HMS" is also directly confirmed ("HMS" alone, not
# "->HMS" or "HMS" with any arrow at all -- tower.txt line "HMS"). The
# rest of this table (->HR, ->OCT, and the P->R/R->P/D->R/R->D pairs) is
# *not* exercised by tower.txt; it follows the same "drop the arrow, keep
# the format name" pattern confirmed for ->HMS, which is a reasonable
# but unverified extrapolation -- revisit if a fixture ever contradicts
# it. Sigma (Σ) and up-arrow (↑) names (ΣREG, Σ+, Σ-, CLΣ, X↑2, Y↑X,
# ENTER↑, E↑X, 10↑X, R↑, E↑X-1) are also unexercised by tower.txt and are
# left as functions.py's own unicode spelling for now, since no fixture
# evidence favors any one particular ASCII substitute over another.
ASCII_DISPLAY_NAMES = {
    "X≤Y?": "X<=Y?",
    "X≤0?": "X<=0?",
    "X≠Y?": "X#Y?",
    "X≠0?": "X#0?",
    "→HMS": "HMS",
    "→HR": "HR",
    "→OCT": "OCT",
    "P→R": "PR",
    "R→P": "RP",
    "D→R": "DR",
    "R→D": "RD",
}


def _display_name(name: str) -> str:
    return ASCII_DISPLAY_NAMES.get(name, name)


def _append_mnemonic(lines, mnemonic, operand_text, data, start, length):
    '''Appends "<mnemonic> <operand_text>", or an unknown-opcode fallback
    comment if `operand_text` is None (an unrecognized operand byte) --
    a small shared helper for the several 2-/3-byte instruction forms
    below that all follow this same "mnemonic + decoded operand, or give
    up" shape.'''
    if operand_text is None:
        lines.append(_format_unknown(data, start, length))
    else:
        lines.append(f"{mnemonic} {operand_text}")


def _format_unknown(data: bytes, start: int, length: int) -> str:
    '''hp41uc's own decompiler emits an informational, non-recompilable
    comment line for a synthetic/unassigned opcode byte rather than
    silently dropping it (docs/program_text_io_plan.md sec 2.3/5) -- e.g.
    the two confirmed-spare bytes 0xAF/0xB0. This module follows the same
    policy for anything else it doesn't recognize (an unexpected operand
    byte, an unassigned prefix range, etc.), rather than guessing.'''
    hex_bytes = " ".join(f"{b:02X}" for b in data[start : start + length])
    return f"; UNKNOWN OPCODE: {hex_bytes}"


def _render_number_run(chars: List[str]) -> str:
    '''Renders a run of digit-literal characters (see _DIGIT_CHARS)
    exactly as hp41uc's own decompiler does: the characters in order,
    except a single space is inserted immediately before an 'E' that
    isn't the very first character -- confirmed by tower.txt's "3 E3"
    (mantissa "3" then a space then the exponent marker) vs. bare "E2"
    (no mantissa, no leading space).'''
    out = []
    for i, ch in enumerate(chars):
        if ch == "E" and i > 0:
            out.append(" ")
        out.append(ch)
    return "".join(out)


def _encode_alpha_content(data: bytes) -> str:
    '''Renders raw ALPHA-text character bytes as a quoted string body
    (the text between the double quotes, not including them).

    Deliberately does NOT reuse trigraphs.py's own escape scheme here --
    confirmed against tower.txt's `"Y ^ X ?"` (a PROMPT string), whose
    raw content byte is 0x5E: trigraphs.py's shorthand table treats 0x5E
    as the FOCAL "up arrow" glyph and would render it as its own "\\^|"
    escape (correct for this project's *other* file formats, per that
    module's own docstring), but hp41uc's own decompiler prints it as a
    bare, literal '^' -- i.e. hp41uc doesn't care that FOCAL has
    reassigned some ASCII punctuation positions to other glyphs; it just
    emits every printable-ASCII-range byte (0x20-0x7E) as its own ASCII
    character, unconditionally. This module follows that same rule, with
    two necessary exceptions for bytes that would otherwise collide with
    this format's own syntax: a literal double-quote (0x22) would be
    ambiguous with the closing quote, and a literal backslash (0x5C)
    would be ambiguous with an escape sequence -- both instead go through
    the \\nnn numeric fallback, matching this project's other file
    formats' own canonical escape spelling (docs/program_text_io_plan.md
    sec 3.1's decision) since there's no fixture evidence favoring any
    other spelling. Anything outside the printable range at all (control
    bytes, DEL, high bytes) also falls back to \\nnn for the same reason.'''
    out = []
    for b in data:
        if b in (0x22, 0x5C):
            out.append(f"\\{b:03d}")
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03d}")
    return "".join(out)


def _decode_alpha_instruction(
    data: bytes, start: int, prefix_len: int, count: int
) -> str:
    '''Renders a direct ALPHA-text-load instruction (the 0xF0-0xFF class,
    prefix_len=1) or a GTO"/XEQ"-style global-name reference (the
    0x1D-0x1F class, prefix_len=2) as quoted text. A leading "Append"
    control byte (0x7F, trigraphs.py's own "\\+" shorthand) is rendered
    as hp41uc's own leading ">" notation instead, with the rest of the
    string quoted normally -- confirmed by tower.txt's `>":" ` (append a
    colon) and `>" " ` (append a space), both of which have 0x7F as
    their very first content byte.'''
    content = data[start + prefix_len : start + prefix_len + count]
    if content and content[0] == 0x7F:
        return ">" + '"' + _encode_alpha_content(content[1:]) + '"'
    return '"' + _encode_alpha_content(content) + '"'


def _decode_xrom(byte1: int, byte2: int) -> str:
    '''Renders an XROM instruction the way hp41uc's own decompiler does:
    always as "XROM mm,ff" (never the friendly function name as the
    mnemonic itself), with the function's name as a trailing comment when
    it's a known Extended Functions/Time function -- confirmed against
    every XROM instance in tower.txt (e.g. "XROM 25,46 ;X<>F"). mm/ff are
    recovered from the two raw bytes via mm = ((byte1 & 0x07) << 2) |
    (byte2 >> 6), ff = byte2 & 0x3F -- a formula confirmed by cross-
    checking multiple known (byte1, byte2) pairs from functions.py's own
    XROM_FUNCTIONS table against tower.txt's "mm,ff" comments (SEEKPT,
    ARCLREC, GETKEY, X<>F all check out exactly).'''
    mm = ((byte1 & 0x07) << 2) | (byte2 >> 6)
    ff = byte2 & 0x3F
    name = XROM_FUNCTIONS.get((byte1, byte2))
    text = f"XROM {mm},{ff:02d}"
    if name is not None:
        text += f" ;{name}"
    return text


def encode_program_txt(data: bytes) -> str:
    '''
    Decompiles one program's raw instruction bytes (as returned by
    ProgramMemory.get_program_bytes(), decode_program_raw(), or
    decode_program_dat() -- a single program's bytes, ending in its own
    terminating END or the permanent .END. marker) into a plain-text
    keystroke listing, closely matching hp41uc's own decompile
    conventions (see this module's docstring for how that convention was
    derived and confirmed).

    Per docs/program_text_io_plan.md sec 5's round-trip decision, this is
    *not* expected to exactly reproduce a hand-authored source file's own
    prose comments (those are discarded when a file is compiled and can
    never be recovered from the compiled bytes alone) -- only hp41uc's
    own mechanical annotations (the "XROM mm,ff" name comment, the END
    trailer's own byte count) are reproduced.

    An opcode or operand byte this module doesn't recognize (an
    unassigned/spare opcode, or a malformed operand) renders as an
    informational "; UNKNOWN OPCODE: ..." comment line rather than
    raising or guessing -- see _format_unknown().
    '''
    lines: List[str] = []
    i = 0
    n = len(data)

    while i < n:
        c = data[i]

        # -- A digit-literal run (one number). hp41uc's compiler inserts
        # a single 0x00 separator byte between two back-to-back numeric
        # literals (docs/program_text_io_plan.md sec 2.3 -- digit bytes
        # 0x10-0x1C have no length prefix and would otherwise run
        # together), confirmed against numtest.dm41's real, purpose-built
        # "12345" then "67890" example. That separator is a pure
        # technical necessity with no display text of its own -- it's
        # swallowed rather than rendered as its own line -- but it still
        # ends the *first* run: hp41uc's own decompiler (and the plan
        # doc's own description of it, sec 2.3: "a Python decompiler
        # emits two plain number lines back to back") emits "12345" and
        # "67890" as two separate lines, not one merged "1234567890" --
        # confirmed directly against numtest.dm41's own real DM41
        # hardware capture. So the run this loop builds stops at the
        # first byte that isn't itself a digit-literal character
        # (whether that's a 0x00 separator or anything else); the
        # separator-swallow below only ever skips a *single* 0x00 that
        # sits between this run and the very next one, once this run's
        # own line has already been appended -- it can never extend the
        # current run.
        if c in _DIGIT_CHARS:
            chars = [_DIGIT_CHARS[c]]
            i += 1
            while i < n and data[i] in _DIGIT_CHARS:
                chars.append(_DIGIT_CHARS[data[i]])
                i += 1
            lines.append(_render_number_run(chars))
            if i < n and data[i] == 0x00 and i + 1 < n and data[i + 1] in _DIGIT_CHARS:
                i += 1  # swallow the separator -- no line of its own
            continue

        # -- GTO"/XEQ"-with-a-global-name, or an unrecognized 2-byte form
        # sharing the same prefix range (opcode_scan's BYTE2_ALPHA class).
        if 0x1D <= c <= 0x1F:
            if i + 1 >= n:
                lines.append(_format_unknown(data, i, n - i))
                break
            c2 = data[i + 1]
            if c2 <= 0xF0:
                # Not actually an alpha-name reference -- not exercised
                # by tower.txt and not otherwise documented.
                lines.append(_format_unknown(data, i, 2))
                i += 2
                continue
            count = c2 & 0x0F
            total = 2 + count
            if i + total > n:
                lines.append(_format_unknown(data, i, n - i))
                break
            name = _decode_alpha_instruction(data, i, 2, count)
            if c == 0x1D:
                lines.append(f"GTO {name}")
            elif c == 0x1E:
                lines.append(f"XEQ {name}")
            else:  # 0x1F -- not confirmed to mean anything; see docstring
                lines.append(_format_unknown(data, i, total))
            i += total
            continue

        # -- 2-byte instructions: 0x90-0xBF, plus X<>/LBL at 0xCE/0xCF.
        if (0x90 <= c <= 0xBF) or (0xCE <= c <= 0xCF):
            if i + 1 >= n:
                lines.append(_format_unknown(data, i, n - i))
                break
            operand = data[i + 1]

            if c in _REGISTER_OPERAND_PREFIXES:
                mnemonic = _display_name(_REGISTER_OPERAND_PREFIXES[c])
                text = _decode_register_operand(operand)
                _append_mnemonic(lines, mnemonic, text, data, i, 2)
            elif c in _SMALL_DIGIT_OPERAND_PREFIXES:
                mnemonic = _SMALL_DIGIT_OPERAND_PREFIXES[c]
                text = _decode_small_digit_operand(operand)
                _append_mnemonic(lines, mnemonic, text, data, i, 2)
            elif c == 0xA6:
                lines.append(_decode_xrom(c, operand))
            elif c == 0xAE:
                text = _decode_register_operand(operand)
                _append_mnemonic(lines, "GTO IND", text, data, i, 2)
            elif c in _SPARE_OPCODES:
                lines.append(_format_unknown(data, i, 2))
            elif _GTO_COMPACT_BASE <= c <= _GTO_COMPACT_BASE + _GTO_COMPACT_MAX:
                target = c - _GTO_COMPACT_BASE
                if operand == _GTO_COMPACT_FIXED_BYTE2:
                    lines.append(f"GTO {target:02d}")
                else:
                    lines.append(_format_unknown(data, i, 2))
            elif c == 0xCF:
                text = _decode_register_operand(operand)
                _append_mnemonic(lines, "LBL", text, data, i, 2)
            else:
                lines.append(_format_unknown(data, i, 2))
            i += 2
            continue

        # -- Global chain marker: an END, the permanent .END., or a
        # global (quoted-name) LBL header.
        if 0xC0 <= c <= 0xCD:
            marker = decode_chain_marker(data, i)
            if marker is None:
                lines.append(_format_unknown(data, i, n - i))
                break
            if marker["is_label"]:
                length = marker["label_length"]
                header_len = 4 + max(length, 0)
                if i + header_len > n:
                    lines.append(_format_unknown(data, i, n - i))
                    break
                name_bytes = data[i + 4 : i + header_len]
                name = _encode_alpha_content(name_bytes)
                lines.append(f'LBL "{name}"')
                i += header_len
                continue
            # A plain END or the permanent .END. -- this program's own
            # terminator. Its byte count is *this* marker's own ending
            # position (i + 3), never len(data): a caller that
            # accidentally passes extra trailing bytes (e.g. a RAW
            # file's checksum-and-zero-padding trailer, still attached
            # because decode_program_raw() wasn't called first) must
            # not have that padding counted into the reported size.
            # Stopping here (rather than falling through to `continue`
            # and walking whatever comes next) is what keeps that same
            # trailing padding from being misdecoded as more
            # instructions -- see the opcode-length classifier's own
            # find_program_end(), which this mirrors: a program's real
            # end is always its own first terminating END, never
            # wherever the caller's buffer happens to stop.
            lines.append(f"END ;{i + 3} BYTES")
            break

        # -- 3-byte instructions: GTO/XEQ's general long form (0xD0/0xE0),
        # or an unrecognized prefix elsewhere in 0xD0-0xEF.
        if 0xD0 <= c <= 0xEF:
            if i + 3 > n:
                lines.append(_format_unknown(data, i, n - i))
                break
            byte2, byte3 = data[i + 1], data[i + 2]
            if c in (0xD0, 0xE0) and byte2 == 0x00:
                mnemonic = "GTO" if c == 0xD0 else "XEQ"
                text = _decode_register_operand(byte3)
                _append_mnemonic(lines, mnemonic, text, data, i, 3)
            else:
                lines.append(_format_unknown(data, i, 3))
            i += 3
            continue

        # -- Direct ALPHA-text-load instruction (or an "Append" variant --
        # see _decode_alpha_instruction()).
        if 0xF0 <= c <= 0xFF:
            count = c & 0x0F
            total = 1 + count
            if i + total > n:
                lines.append(_format_unknown(data, i, n - i))
                break
            lines.append(_decode_alpha_instruction(data, i, 1, count))
            i += total
            continue

        # -- Plain single-byte instruction (0x20-0x8F, minus the RCL/STO
        # compact blocks and the digit-literal range already handled
        # above; also 0x01-0x0F's compact local LBL block).
        if _LBL_COMPACT_BASE <= c <= _LBL_COMPACT_BASE + _LBL_COMPACT_MAX:
            lines.append(f"LBL {c - _LBL_COMPACT_BASE:02d}")
        elif _RCL_COMPACT_BASE <= c <= _RCL_COMPACT_BASE + _COMPACT_REGISTER_MAX:
            lines.append(f"RCL {c - _RCL_COMPACT_BASE:02d}")
        elif _STO_COMPACT_BASE <= c <= _STO_COMPACT_BASE + _COMPACT_REGISTER_MAX:
            lines.append(f"STO {c - _STO_COMPACT_BASE:02d}")
        elif c in SINGLE_BYTE_FUNCTIONS and c >= 0x40:
            lines.append(_display_name(SINGLE_BYTE_FUNCTIONS[c]))
        else:
            lines.append(_format_unknown(data, i, 1))
        i += 1

    return "\n".join(lines) + "\n"


# ===========================================================================
# Phase 2 -- decode_program_txt(): compiling text back into instruction
# bytes. Everything below is the reverse of the opcode table above; see
# decode_program_txt()'s own docstring for the compile-specific design
# notes (the tokenizer, the numeric-literal-separator quirk, and the
# chain-marker "always zero" finding).
# ===========================================================================

# Reverse of _DIGIT_CHARS: display character -> raw byte.
_DIGIT_BYTES = {v: k for k, v in _DIGIT_CHARS.items()}
_NUMBER_LITERAL_CHARS = frozenset("0123456789.E-")
# A bare "-" is genuinely ambiguous as *text* -- SINGLE_BYTE_FUNCTIONS'
# 0x41 (the SUBTRACT arithmetic function) and _DIGIT_CHARS' 0x1C (the
# CHS glyph, valid only as part of an in-progress digit run, e.g. the
# leading byte of "-1") both render as the exact same one-character line
# "-" on decode -- confirmed by decompiling tower.raw itself, where a
# solitary "-" line (immediately after a plain, already-terminated "3"
# literal, with no other digit characters anywhere nearby) turns out to
# be byte 0x41, not 0x1C. Checked this is the *only* such collision --
# no other SINGLE_BYTE_FUNCTIONS entry at 0x40+ renders as text made up
# purely of "0123456789.E-" characters -- so a bare "E" (real, if rare:
# src/tests/data/targ-packed.dm41 decompiles a standalone exponent-marker
# digit with no mantissa at all anywhere near it) or a bare "." both
# still need to read back as digit-literal bytes, just not a bare "-".
_AMBIGUOUS_NUMBER_LITERAL_TEXT = "-"

# Reverse of _STACK_REGISTER_NAMES: display name -> raw base value.
_STACK_REGISTER_CODES = {v: k for k, v in _STACK_REGISTER_NAMES.items()}

# Reverse of _REGISTER_OPERAND_PREFIXES/_SMALL_DIGIT_OPERAND_PREFIXES:
# mnemonic text -> prefix byte. Built from those tables rather than
# transcribed a second time, so the two directions can never drift apart
# -- same reasoning as functions.py's own SINGLE_BYTE_NAMES/XROM_NAMES.
_REGISTER_OPERAND_PREFIX_BYTES = {v: k for k, v in _REGISTER_OPERAND_PREFIXES.items()}
_SMALL_DIGIT_OPERAND_PREFIX_BYTES = {
    v: k for k, v in _SMALL_DIGIT_OPERAND_PREFIXES.items()
}
_REGISTER_OPERAND_PREFIX_NAMES = frozenset(_REGISTER_OPERAND_PREFIX_BYTES)
_SMALL_DIGIT_OPERAND_PREFIX_NAMES = frozenset(_SMALL_DIGIT_OPERAND_PREFIX_BYTES)

# Reverse of ASCII_DISPLAY_NAMES: the ASCII spelling this module's own
# decoder emits -> the real (possibly non-ASCII) name SINGLE_BYTE_NAMES
# is keyed by, e.g. "X<=Y?" -> "X≤Y?", "HMS" -> "→HMS".
_CANONICAL_NAME_FOR_DISPLAY = {v: k for k, v in ASCII_DISPLAY_NAMES.items()}

# hp41uc's own C-style single-letter escapes (docs/program_text_io_plan.md
# sec 5's decision: "accepted on decode ... none collide with
# trigraphs.py's shorthand table"). Accept-only -- _encode_alpha_content()
# above never emits these, only the canonical \nnn form; see this
# module's own top-of-file docstring.
_C_STYLE_ESCAPES = {
    "a": 0x07,  # BEL
    "b": 0x08,  # backspace
    "f": 0x0C,  # form feed
    "n": 0x0A,  # line feed
    "r": 0x0D,  # carriage return
    "t": 0x09,  # horizontal tab
    "v": 0x0B,  # vertical tab
    "?": 0x3F,  # '?' (only needed to defeat C trigraphs; harmless here)
    '"': 0x22,
    "'": 0x27,
    "\\": 0x5C,
}

# hp41uc/§4.4's own two-marker comment style for a byte-for-byte-unknown
# instruction (see _format_unknown() above) -- recognized specially on
# decode so a decompile -> (unedited) -> recompile round trip can carry
# a synthetic/unassigned opcode straight through untouched, per §5's
# decision ("A decompile-edit-recompile round trip must be able to carry
# a byte-for-byte-unknown instruction through untouched as long as the
# user doesn't try to hand-edit that particular line").
_UNKNOWN_OPCODE_RE = re.compile(
    r"^;\s*UNKNOWN OPCODE:\s*([0-9A-Fa-f]{2}(?:\s+[0-9A-Fa-f]{2})*)\s*$"
)

# "XROM mm,ff" -- hp41uc's own spelling, no space around the comma
# (confirmed throughout tower.txt: "XROM 25,46", "XROM 25,05"), but a
# stray space either side is tolerated for hand-authored source.
_XROM_RE = re.compile(r"^(\d{1,2})\s*,\s*(\d{1,2})$")


def _tokenize_line(line: str) -> List[str]:
    '''Quote-and-escape-aware tokenizer for one line of program-text
    source: splits on whitespace outside a quoted ALPHA string, and
    treats a backslash inside quotes as escaping the very next character
    (so `\\"` inside a string doesn't end it early -- necessary for the
    `\\XHH`/`\\nnn`/C-style escapes _decode_alpha_text_literal() accepts
    below, several of which start with a digit or letter that would
    otherwise look like ordinary text, but `\\"` specifically needs this
    to avoid ending the string on the escaped quote itself).

    Stops -- discarding the token that triggered it and the rest of the
    line -- at the first token, outside quotes, that begins with `;` or
    `#` (hp41uc's own two comment markers, plan doc sec 2.1). A token can
    only begin with one of those characters right at a whitespace/line
    boundary (checked here via "is `cur` still empty"), which is exactly
    what keeps a mnemonic like "X#Y?" (a single token whose first
    character is 'X') from ever being mistaken for a comment -- matching
    src/tests/test_program_text.py's own `_strip_trailing_comment()`
    reasoning on the decode side.

    Raises ValueError if the line ends with an unterminated quoted
    string (an unmatched `"`).'''
    tokens: List[str] = []
    cur: List[str] = []
    in_quotes = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_quotes and ch == "\\" and i + 1 < n:
            cur.append(ch)
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
            cur.append(ch)
            i += 1
            continue
        if ch.isspace() and not in_quotes:
            if cur:
                tokens.append("".join(cur))
                cur = []
            i += 1
            continue
        if not in_quotes and not cur and ch in ";#":
            break  # a comment token boundary -- stop, discard the rest
        cur.append(ch)
        i += 1
    if in_quotes:
        raise ValueError(f"unterminated quoted text in line: {line!r}")
    if cur:
        tokens.append("".join(cur))
    return tokens


def _is_number_literal_tokens(tokens: List[str]) -> bool:
    '''True if `tokens`, concatenated back together with no separator,
    forms nothing but digit-literal characters (see _DIGIT_CHARS) -- the
    compile-side mirror of _render_number_run()'s own single-space-
    before-a-non-initial-'E' rule: decompiling "3 E3" splits it into two
    whitespace-separated tokens ("3", "E3") purely for display, so
    joining them back together (undoing that one cosmetic space) is what
    recovers the original one-instruction digit run. No real mnemonic
    this module recognizes is spelled using only "0123456789.E-" (every
    one has at least one letter outside that set -- "ST-" has 'S'/'T',
    "SIN" has 'S'/'I'/'N', etc.), so this check can never misfire against
    an actual instruction. The one exception -- a bare "-" alone is
    *not* treated as a number literal -- is what tells a real number
    literal like "-1" apart from a bare "-" that's actually the
    unrelated SUBTRACT function; see _AMBIGUOUS_NUMBER_LITERAL_TEXT's
    own comment above.'''
    joined = "".join(tokens)
    if joined == _AMBIGUOUS_NUMBER_LITERAL_TEXT:
        return False
    return bool(joined) and all(ch in _NUMBER_LITERAL_CHARS for ch in joined)


def _decode_alpha_text_literal(text: str) -> bytes:
    '''Reverses _encode_alpha_content() -- turns the text between a pair
    of quotes back into raw content bytes. A literal printable-ASCII
    character (0x20-0x7E) maps to its own byte value, matching hp41uc's
    "FOCAL's reassigned punctuation prints literally" behavior confirmed
    in this module's own docstring/`_encode_alpha_content()`. `\\` starts
    an escape: `\\XHH` (2 hex digits, the capital-X spelling settled on
    in docs/program_text_io_plan.md sec 3.1 to avoid colliding with
    trigraphs.py's lowercase `\\x` "times" shorthand), `\\nnn` (3 decimal
    digits, this project's own canonical fallback -- what
    _encode_alpha_content() actually emits), or one of the C-style
    single-letter escapes in _C_STYLE_ESCAPES (accepted per the plan's
    sec 5 decision, for smoother acceptance of hp41uc/community source --
    never emitted by the encoder). Raises ValueError on a trailing
    backslash or an escape sequence that matches none of those forms.'''
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\\":
            b = ord(ch)
            if b > 0xFF:
                raise ValueError(f"non-8-bit character {ch!r} in ALPHA text: {text!r}")
            out.append(b)
            i += 1
            continue
        if i + 1 >= n:
            raise ValueError(f"trailing backslash in ALPHA text: {text!r}")
        nxt = text[i + 1]
        if nxt == "X":
            hex_digits = text[i + 2 : i + 4]
            is_hex = all(c in "0123456789ABCDEFabcdef" for c in hex_digits)
            if len(hex_digits) == 2 and is_hex:
                out.append(int(hex_digits, 16))
                i += 4
                continue
            raise ValueError(f"malformed \\X escape (need 2 hex digits) in: {text!r}")
        if nxt.isdigit():
            digits = text[i + 1 : i + 4]
            if len(digits) == 3 and digits.isdigit():
                value = int(digits)
                if value > 0xFF:
                    raise ValueError(f"\\{digits} out of byte range in: {text!r}")
                out.append(value)
                i += 4
                continue
            raise ValueError(f"malformed \\nnn escape (need 3 digits) in: {text!r}")
        if nxt in _C_STYLE_ESCAPES:
            out.append(_C_STYLE_ESCAPES[nxt])
            i += 2
            continue
        raise ValueError(f"unrecognized escape '\\{nxt}' in ALPHA text: {text!r}")
    return bytes(out)


def _parse_quoted_token(token: str) -> bytes:
    '''Parses a single tokenized quoted-string token -- e.g. `'"SCORE: "'`
    or `'>":"'` (a leading `>`, hp41uc's own "append to ALPHA" notation,
    see _decode_alpha_instruction()'s own docstring) -- into raw content
    bytes, with the 0x7F "Append" control byte prepended when `>` was
    present. Raises ValueError if `token` isn't a well-formed quoted
    string (missing/mismatched quotes).'''
    append = token.startswith(">")
    body = token[1:] if append else token
    if len(body) < 2 or body[0] != '"' or body[-1] != '"':
        raise ValueError(f"malformed quoted ALPHA text: {token!r}")
    content = _decode_alpha_text_literal(body[1:-1])
    return bytes([0x7F]) + content if append else content


def _parse_register_base(token: str) -> int:
    '''Parses a bare (non-indirect) register/label/flag descriptor
    token -- a decimal register/flag number 0-99, a local letter label
    A-J, or a stack register name T/Z/Y/X/L -- into its raw base value
    (see the module-level comment above _decode_register_operand(), which
    this reverses). Raises ValueError if `token` doesn't match any of
    those forms.'''
    upper = token.upper()
    if upper in _STACK_REGISTER_CODES:
        return _STACK_REGISTER_CODES[upper]
    if len(upper) == 1 and "A" <= upper <= "J":
        return 0x66 + (ord(upper) - ord("A"))
    if token.isdigit():
        n = int(token)
        if 0 <= n <= 99:
            return n
    raise ValueError(f"not a valid register/label operand: {token!r}")


def _parse_register_operand(tokens: List[str]) -> int:
    '''Parses an operand token list that may lead with a literal "IND"
    token (e.g. `["IND", "16"]` or just `["16"]`) into a full descriptor
    byte, indirect bit included -- the reverse of
    _decode_register_operand(). Raises ValueError if `tokens` isn't
    exactly an optional "IND" followed by one base-operand token.'''
    indirect = bool(tokens) and tokens[0].upper() == "IND"
    rest = tokens[1:] if indirect else tokens
    if len(rest) != 1:
        raise ValueError(f"expected exactly one register operand, got: {tokens!r}")
    base = _parse_register_base(rest[0])
    return (0x80 if indirect else 0x00) | base


def _resolve_single_byte_mnemonic(mnemonic: str) -> Optional[int]:
    '''Reverses SINGLE_BYTE_FUNCTIONS/ASCII_DISPLAY_NAMES for a plain
    (zero-operand) mnemonic token -- the compile-side counterpart of
    _display_name() plus this module's own SINGLE_BYTE_FUNCTIONS
    dispatch in encode_program_txt(). Tries, in order: (1) an exact match
    against a real function name already in SINGLE_BYTE_NAMES (covers
    every mnemonic that's already plain ASCII, e.g. "SIN", "AVIEW", "+");
    (2) this module's own ASCII_DISPLAY_NAMES reversed (covers the
    handful this module's own decoder substitutes, e.g. "X<=Y?" ->
    "X≤Y?", "HMS" -> "→HMS"); (3) functions.py's own
    normalize_function_name_input(), a courtesy extension covering the
    small set of symbol substitutions it already knows about
    ("->","<=","^","sigma") so hand-authored source using those spellings
    compiles too, even though this module's own decoder never emits them.
    Returns None (never raises) if nothing matches, or if the only match
    is a Key-Assignment-Register-only entry below 0x40 (see this module's
    own top-of-file docstring, point 2) -- those aren't valid in-program
    opcodes at all, matching encode_program_txt()'s own `c >= 0x40`
    guard.'''
    for name in (
        mnemonic,
        _CANONICAL_NAME_FOR_DISPLAY.get(mnemonic),
        normalize_function_name_input(mnemonic),
    ):
        if name is None:
            continue
        byte = SINGLE_BYTE_NAMES.get(name)
        if byte is not None and byte >= 0x40:
            return byte
    return None


def _encode_register_operand_instruction(mnemonic: str, tokens: List[str]) -> bytes:
    '''RCL/STO/ST+/ST-/ST*/ST//ISG/DSE/VIEW/SIGMAREG/ASTO/ARCL/SF/CF/
    FS?C/FC?C/FS?/FC?/X<> -- every mnemonic sharing the register/flag
    "descriptor" operand byte scheme. RCL/STO additionally prefer the
    compact single-byte form for a direct (non-IND) register 00-15,
    mirroring encode_program_txt()'s own compact-vs-general split exactly
    (see _RCL_COMPACT_BASE/_STO_COMPACT_BASE's own module-level
    comment) -- every other mnemonic in this group always uses the
    general 2-byte form, since it has no compact form to begin with.'''
    operand_tokens = tokens[1:]
    if not operand_tokens:
        raise ValueError(f"{mnemonic} needs an operand: {' '.join(tokens)!r}")
    indirect = operand_tokens[0].upper() == "IND"
    base_tokens = operand_tokens[1:] if indirect else operand_tokens
    if len(base_tokens) != 1:
        raise ValueError(
            f"unexpected extra tokens for {mnemonic}: {' '.join(tokens)!r}"
        )
    base = _parse_register_base(base_tokens[0])

    is_compact_eligible = (
        mnemonic in ("RCL", "STO")
        and not indirect
        and 0 <= base <= _COMPACT_REGISTER_MAX
    )
    if is_compact_eligible:
        compact_base = _RCL_COMPACT_BASE if mnemonic == "RCL" else _STO_COMPACT_BASE
        return bytes([compact_base + base])

    prefix = _REGISTER_OPERAND_PREFIX_BYTES[mnemonic]
    descriptor = (0x80 if indirect else 0x00) | base
    return bytes([prefix, descriptor])


def _encode_small_digit_operand_instruction(mnemonic: str, tokens: List[str]) -> bytes:
    '''FIX/SCI/ENG/TONE -- the bare-0-9-digit operand style (see
    _decode_small_digit_operand()). Falls back to the general
    register-descriptor encode (supporting an "IND" operand) for anything
    that isn't a single bare digit 0-9, mirroring
    _decode_small_digit_operand()'s own fallback.'''
    operand_tokens = tokens[1:]
    if not operand_tokens:
        raise ValueError(f"{mnemonic} needs an operand: {' '.join(tokens)!r}")
    prefix = _SMALL_DIGIT_OPERAND_PREFIX_BYTES[mnemonic]
    is_bare_digit = (
        len(operand_tokens) == 1
        and operand_tokens[0].isdigit()
        and len(operand_tokens[0]) == 1
    )
    if is_bare_digit:
        return bytes([prefix, int(operand_tokens[0])])
    descriptor = _parse_register_operand(operand_tokens)
    return bytes([prefix, descriptor])


def _encode_xrom(tokens: List[str]) -> bytes:
    '''"XROM mm,ff" -- reverses _decode_xrom()'s mm/ff-recovery formula
    (byte1 = 0xA0 | ((mm>>2)&7), byte2 = ((mm&3)<<6) | (ff&0x3F)) and then
    -- per docs/program_text_io_plan.md sec 3.1's decision -- requires
    the resulting (byte1, byte2) pair to already be a known entry in
    functions.py's XROM_FUNCTIONS table (covering exactly the two ROM
    modules, Extended Functions and Time, the DM41L emulates). Any other
    module number, or an unrecognized function number within those two
    modules, is a compile error -- never a silent fallback to the literal
    bytes the way hp41uc itself handles an unknown module.'''
    if len(tokens) != 2:
        raise ValueError(
            f"XROM needs exactly one 'mm,ff' operand: {' '.join(tokens)!r}"
        )
    match = _XROM_RE.match(tokens[1])
    if not match:
        raise ValueError(f"malformed XROM operand (expected 'mm,ff'): {tokens[1]!r}")
    mm, ff = int(match.group(1)), int(match.group(2))
    byte1 = 0xA0 | ((mm >> 2) & 0x07)
    byte2 = ((mm & 0x03) << 6) | (ff & 0x3F)
    if (byte1, byte2) not in XROM_FUNCTIONS:
        raise ValueError(
            f"unsupported XROM {mm},{ff:02d} -- only Extended Functions (module "
            "25) and Time (module 26) functions the DM41L emulates are supported"
        )
    return bytes([byte1, byte2])


def _encode_gto_xeq(mnemonic: str, tokens: List[str]) -> bytes:
    '''GTO/XEQ -- three forms, matching encode_program_txt()'s own three
    GTO/XEQ decode branches exactly: a quoted global name reference
    (`GTO "NAME"`/`XEQ "NAME"`, the 0x1D/0x1E-prefixed form), `GTO IND
    <reg>` (the single dedicated 0xAE opcode -- GTO only, no XEQ
    equivalent exists in this module's opcode table), or a bare local
    target number/letter (GTO additionally prefers the compact 2-byte
    form for a local number 00-14, matching _GTO_COMPACT_BASE's own
    module-level comment; XEQ has no compact form at all and always uses
    the general 3-byte form).'''
    operand_tokens = tokens[1:]
    if not operand_tokens:
        raise ValueError(f"{mnemonic} needs an operand: {' '.join(tokens)!r}")
    first_operand = operand_tokens[0]

    if first_operand.startswith('"') or first_operand.startswith('>"'):
        if len(operand_tokens) != 1:
            raise ValueError(
                f"unexpected extra tokens after {mnemonic} name: {' '.join(tokens)!r}"
            )
        content = _parse_quoted_token(first_operand)
        if not 1 <= len(content) <= 15:
            raise ValueError(
                f"{mnemonic} global name must be 1-15 bytes, got {len(content)}: "
                f"{first_operand!r}"
            )
        prefix = 0x1D if mnemonic == "GTO" else 0x1E
        return bytes([prefix, 0xF0 | len(content)]) + content

    if mnemonic == "GTO" and first_operand.upper() == "IND":
        if len(operand_tokens) != 2:
            raise ValueError(f"GTO IND needs exactly one register operand: {tokens!r}")
        descriptor = _parse_register_operand([operand_tokens[1]])
        return bytes([0xAE, descriptor])

    if len(operand_tokens) != 1:
        raise ValueError(
            f"unexpected extra tokens after {mnemonic}: {' '.join(tokens)!r}"
        )
    base = _parse_register_base(first_operand)
    if mnemonic == "GTO" and 0 <= base <= _GTO_COMPACT_MAX:
        return bytes([_GTO_COMPACT_BASE + base, _GTO_COMPACT_FIXED_BYTE2])
    prefix = 0xD0 if mnemonic == "GTO" else 0xE0
    return bytes([prefix, 0x00, base])


def _encode_instruction(tokens: List[str]) -> Tuple[bytes, bool]:
    '''Encodes one non-numeric-literal instruction's tokens (as produced
    by _tokenize_line()) into its raw bytes. Returns (bytes, is_end) --
    `is_end` is True only for the program's own terminating END, so
    decode_program_txt() knows to stop there. Raises ValueError, with a
    message naming the offending token(s), for anything it doesn't
    recognize -- the same "give up and be informative" posture
    _format_unknown() takes on the decode side, just as an exception
    instead of a comment line, since a program that doesn't compile has
    no bytes to fall back to.'''
    first = tokens[0]

    # A bare quoted string (optionally `>`-prefixed) with no leading
    # mnemonic word at all is a direct ALPHA-text-load instruction (the
    # 0xF0-0xFF class) -- see _decode_alpha_instruction()'s prefix_len=1
    # case.
    if first.startswith('"') or first.startswith('>"'):
        if len(tokens) != 1:
            raise ValueError(f"unexpected extra tokens after ALPHA text: {tokens!r}")
        content = _parse_quoted_token(first)
        if not 0 <= len(content) <= 15:
            raise ValueError(
                f"ALPHA text must be 0-15 bytes, got {len(content)}: {first!r}"
            )
        return bytes([0xF0 | len(content)]) + content, False

    mnemonic = first.upper()

    if mnemonic == "END":
        if len(tokens) != 1:
            raise ValueError(f"unexpected extra tokens after END: {tokens!r}")
        # Always bbb=0/distance_registers=0 (an unlinked/"no predecessor"
        # marker) and third_byte=0x0D (a normal, non-.END., "needs
        # packing" END) -- confirmed to be hp41uc's own compiled output
        # for *every* global marker in tower.raw (not just its trailing
        # END: `scan_global_markers_forward()` on tower.raw's decoded
        # bytes shows the same bbb=0/distance=0 on its `LBL "TWR"` marker
        # too), even though `LBL "TWR"` demonstrably precedes it in the
        # very same 1088-byte buffer. Real HP-41/DM41L hardware *does*
        # maintain real backward links (see APPTEST_BYTES's own non-zero
        # bbb/distance in test_program_export.py, captured live off a
        # real calculator) -- but that linking is exactly what this
        # project's own existing pack()/_forward_scan_programs() repair
        # mechanism (docs/program.md sec 5.4) already exists to fix up
        # for "a dump written by a tool other than a real HP-41/DM41L (or
        # this app)", so this compiler doesn't need to track any
        # cross-instruction chain position itself -- it just needs to
        # match what hp41uc's own compiler actually emits.
        return encode_chain_marker(0, 0, 0x0D), True

    if mnemonic == "LBL":
        if len(tokens) != 2:
            raise ValueError(f"LBL needs exactly one operand: {tokens!r}")
        operand = tokens[1]
        if operand.startswith('"'):
            name = _parse_quoted_token(operand)
            if len(name) > 14:
                raise ValueError(
                    f"global label name must be at most 14 bytes, got "
                    f"{len(name)}: {operand!r}"
                )
            third_byte = 0xF0 | ((len(name) + 1) & 0x0F)
            # Same "always zero" chain-link fields as END above, plus a
            # key-assignment byte of 0x00 -- confirmed against tower.raw's
            # own `LBL "TWR"` marker (key_assignment == 0), consistent
            # with there being no key-assignment syntax anywhere in the
            # program-text format to begin with.
            return encode_chain_marker(0, 0, third_byte) + bytes([0x00]) + name, False
        base = _parse_register_base(operand)
        if 0 <= base <= _LBL_COMPACT_MAX:
            return bytes([_LBL_COMPACT_BASE + base]), False
        return bytes([0xCF, base]), False

    if mnemonic in ("GTO", "XEQ"):
        return _encode_gto_xeq(mnemonic, tokens), False

    if mnemonic == "XROM":
        return _encode_xrom(tokens), False

    if mnemonic in _REGISTER_OPERAND_PREFIX_NAMES:
        return _encode_register_operand_instruction(mnemonic, tokens), False

    if mnemonic in _SMALL_DIGIT_OPERAND_PREFIX_NAMES:
        return _encode_small_digit_operand_instruction(mnemonic, tokens), False

    byte = _resolve_single_byte_mnemonic(mnemonic)
    if byte is not None:
        if len(tokens) != 1:
            raise ValueError(
                f"unexpected operand(s) for {mnemonic}: {' '.join(tokens)!r}"
            )
        return bytes([byte]), False

    raise ValueError(f"unrecognized instruction: {' '.join(tokens)!r}")


def decode_program_txt(text: str) -> bytes:
    '''
    Compiles a plain-text keystroke listing (as produced by
    `encode_program_txt()`, or an hp41uc/community-authored `.txt` file
    such as `src/tests/data/tower.txt` itself) back into one program's
    raw instruction bytes, ready for `Memory.import_program()` (per
    docs/program_text_io_plan.md sec 4.3/sec 5: packing is a separate,
    already-implemented, user-invoked operation and is never this
    function's job).

    One line is (usually) one instruction; see _tokenize_line() for the
    quote/escape-aware tokenizer and comment handling (`;`/`#`, matching
    encode_program_txt()'s own comment conventions). Two exceptions:

    - A numeric literal that encode_program_txt() rendered with a
      cosmetic space before a non-initial "E" (`_render_number_run()`,
      e.g. "3 E3") tokenizes as two whitespace-separated tokens but is
      still one instruction -- see _is_number_literal_tokens(), checked
      before general per-mnemonic dispatch on every line.
    - Two numeric-literal instructions back to back need a `0x00`
      separator byte reinserted between them (digit bytes 0x10-0x1C have
      no length prefix and would otherwise run together on the way back
      onto a real calculator) -- confirmed against real hardware, both by
      a purpose-built fixture (`src/tests/data/numtest.dm41`) and,
      independently, by tower.txt's own back-to-back "3"/"-" lines (a
      digit-run immediately followed by a lone CHS-glyph digit-run,
      which only round-trips correctly through encode_program_txt() if a
      0x00 separator actually sits between them in tower.raw). This
      function tracks whether the immediately preceding instruction it
      emitted was a numeric literal and inserts the separator whenever
      the current one is too.

    An `; UNKNOWN OPCODE: <hex bytes>` line (encode_program_txt()'s own
    informational comment for a synthetic/unassigned opcode -- see
    _format_unknown()) is recognized specially and passed straight
    through as those exact raw bytes, so a decompile -> (unedited) ->
    recompile round trip never loses or corrupts a byte-for-byte-unknown
    instruction, per the plan's sec 5 decision.

    Raises ValueError -- with the 1-based line number and a description
    of the problem -- for a line that doesn't parse as any recognized
    instruction, an operand that doesn't fit its field width, an XROM
    reference outside the two modules the DM41L emulates (sec 3.1's
    compile-time-error decision), or a missing/misplaced terminating
    END. Never silently drops or guesses at malformed input.
    '''
    out = bytearray()
    last_was_number = False
    end_seen = False

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if end_seen:
            stripped_after_end = raw_line.strip()
            if stripped_after_end and not stripped_after_end.startswith((";", "#")):
                raise ValueError(
                    f"line {lineno}: unexpected content after program's "
                    f"terminating END: {raw_line!r}"
                )
            continue

        stripped = raw_line.strip()
        unknown_match = _UNKNOWN_OPCODE_RE.match(stripped)
        if unknown_match is not None:
            try:
                hex_bytes = bytes(int(h, 16) for h in unknown_match.group(1).split())
            except ValueError as exc:
                raise ValueError(
                    f"line {lineno}: malformed UNKNOWN OPCODE comment: {raw_line!r}"
                ) from exc
            out.extend(hex_bytes)
            last_was_number = False
            continue

        try:
            tokens = _tokenize_line(raw_line)
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
        if not tokens:
            continue  # blank line, or a comment-only line

        if _is_number_literal_tokens(tokens):
            try:
                digit_bytes = bytes(_DIGIT_BYTES[ch] for ch in "".join(tokens))
            except KeyError as exc:
                raise ValueError(
                    f"line {lineno}: invalid digit-literal character in: "
                    f"{' '.join(tokens)!r}"
                ) from exc
            if last_was_number:
                out.append(0x00)
            out.extend(digit_bytes)
            last_was_number = True
            continue

        try:
            instr_bytes, is_end = _encode_instruction(tokens)
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
        out.extend(instr_bytes)
        last_was_number = False
        if is_end:
            end_seen = True

    if not end_seen:
        raise ValueError("program text has no terminating END line")
    return bytes(out)
