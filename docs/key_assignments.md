# Key Assignments

This document describes how the HP-41CX (and therefore the DM41L emulator)
stores USER-mode key assignments, the source material behind that
understanding, and the requirements for a planned "Key Assignments" tab in
DM41L Explorer.

As with `docs/program.md`, this file mixes two things that will eventually
need separating: confirmed reference material (which should stay useful to
an end user indefinitely) and a running requirements list for the
not-yet-built tab (which should shrink to nothing as each item is
implemented, at which point it should be deleted from this doc rather than
marked "done"). Until that split happens, look for the "## Requirements"
section at the end — everything above it is reference material.

## 1. Source Material

- **William C. Wickes, *Synthetic Programming on the HP-41C*** (`docs/pdfs/hp41-synthetic-prog.pdf`) — the primary source. Section 2E, "The Key Assignment Registers," and Section 4E, "The Key Assignment Flags," give full byte-level prose and worked examples, not just diagrams. Originally published as an article in the *PPC Calculator Journal*, November 1979, p.28.
- **Keith Jarrett, *Synthetic Programming Made Easy*** (`docs/pdfs/hp41-synth-prog-easy.pdf`) — Section 6B and Figure 6.3 give the processor's actual USER-mode key-press lookup algorithm (see §4.7 below). Also references the *PPC ROM User's Manual* p.280, "Background for MK," for the same byte format Wickes describes — not yet independently checked against that source.
- **"A programmers handbook v.2.07.pdf"** — covers the same ground as unexplained diagrams (Ch. 8 "Key assign flag registers & e," Ch. 39-42 "Key code maps," including a "Key assignment flag bits" keypad chart). Useful for cross-checking once you already know what the diagrams mean; not a good starting point on its own.
- **`docs/pdfs/byte_table.html`** — a clean, already-extracted HTML table of all 256 byte values 0x00-0xFF with their Prefix/Suffix meanings (essentially Wickes' Table 2-1, "The HP-41C Byte Table," in directly-parseable form rather than a PDF diagram). Confirms every built-in function byte code found in this document (see §4.8) and was the starting point for `src/memory/functions.py`'s instruction table (§6, item 3) — check here before re-deriving anything from the PDFs.
- **`docs/function_table.md`** — the DM41L's actual instruction set: a merged 256-row table (Dec, Hex, Instruction Prefix, Instruction Length, Function, Assignable?) covering every base byte value, plus separate Extended Functions ROM and Time ROM catalogs, built from "A programmers handbook v.2.07.pdf." The merge makes explicit that Prefix (program-byte meaning) and Function (key-assignment meaning) are the same for codes 064-224 but diverge for codes 000-015 (§5), and records for the first time which low-code functions can be key-assigned at all. Confirms every 2-byte peripheral function code found in this document (see §4.8) and, together with `byte_table.html`, is what `src/memory/functions.py` (§6, item 3) is generated from.
- `docs/memory.md` §1.1 ("Reading Direction Quick Reference") and its "Key Assignment Registers" subsection under §3 Main Memory — the condensed version of §4 below, kept there for readers of the general memory map.
- `docs/program.md` §5.2, "Decoding a Global Label's Name" — the format of a global label's header, whose 4th byte is a program's key assignment (see §4.6 below).
- Not yet mined: `docs/pdfs/ppcrom-um.pdf` (PPC ROM User's Manual), `docs/pdfs/hp41-adv-prog-tips.pdf`, the CX/C41CV owner's manuals. `docs/pdfs/voyager_user_manual.pdf` is ruled out (wrong calculator family). `docs/pdfs/v11n4.pdf` (PPC Journal) has a minor SAVEK/GETK user program for backing up assignments to an XM file, not internal format detail.

Everything in §4 below has been independently confirmed against real memory
dumps captured by hand on a DM41L (`src/tests/data/keyassigns.dm41`,
`src/tests/data/global-key-assignments.dm41`, and
`src/tests/data/xrom-keyassignments.dm41`), not just derived from the PDFs.

## 2. Terminology

- **Unshifted / shifted key** — every physical key on the keyboard can hold
  two independent assignments: one for a plain press, one for a press
  preceded by the shift key. They're stored completely separately (see §4.2
  and §4.5).
- **Key number** — a two-digit row/column identifier, `MN`, where `M` is the
  physical row (1-8) and `N` is the physical column. This is the notation
  Wickes uses and this document follows; it is *not* the same as the byte
  value used to encode that key internally (§4.3).
- **Built-in / peripheral function assignment** — assigning a key to a
  function that's part of the calculator's own instruction set (`+`, `SIN`,
  `STO`, ...) or a plugged-in module's function. Stored in the Key
  Assignment Registers (§4.2).
- **Global label / program assignment** — assigning a key to run a
  user-written program by its global `LBL "NAME"`. Stored entirely
  differently from the above — see §4.6.
- **KEYFLAGS** — the 36-bit-per-shift-state bitmap in registers F and e that
  records *whether* a key has any assignment at all, independent of what
  kind. See §4.5.

## 3. Address Overview

Key Assignment Registers occupy addresses `0x0C0` upward, growing toward
`.END.` as more are added (see `docs/memory.md` §3's Main Memory table).
Registers F (`0x0A`) and e (`0x0F`) hold the KEYFLAGS bitmaps. Global-label
assignments live inside Program Memory itself and don't have a fixed
address — see §4.6.

## 4. How Key Assignments Are Stored

### 4.1 Two Independent Storage Mechanisms

A key assignment can be recorded in one of two completely different places,
depending on what it's assigned to:

1. A built-in or peripheral function assignment is recorded as an entry in
   the **Key Assignment Registers**, a buffer starting at `0x0C0` (§4.2).
2. A user program assignment is recorded **inside that program's own global
   label header** (§4.6) and never touches the Key Assignment Registers at
   all.

Both kinds set the same KEYFLAGS bit for the assigned key (§4.5) — that bit
only means "this key has *some* assignment," not which kind.

### 4.2 The Key Assignment Registers (starting at `0x0C0`)

Each register that holds assignments begins with marker byte `0xF0` (which,
not coincidentally, is the "TEXT 0" opcode in the byte table — an empty
alpha string; Wickes' own worked example shows a key assignment register
displaying as a program line reading `""` for exactly this reason).
Following the marker, up to **two** 3-byte entries are packed into the
remaining 6 bytes of the register:

    F0  [filler / fn byte 1] [fn byte 1 / fn byte 2] [key byte]  [filler / fn byte 1] [fn byte 1 / fn byte 2] [key byte]
        \_______________ entry 1 ________________/      \_______________ entry 2 ________________/

A built-in HP-41 function needs only one function byte; the **filler byte
comes first** (`0x04`, which happens to read as "LBL 03" if the register is
listed as a program), with the real function code in the entry's second
byte. A peripheral/ROM function's XROM code uses both bytes for real data,
in order, with no filler — confirmed against `xrom-keyassignments.dm41`
(§4.8). An odd number of assignments leaves one register half-full (Wickes'
"KP" utility repacks these).

**Byte order confirmed against `keyassigns.dm41`'s full 14 assignments**:
decoding every entry as `[filler=0x04][real fn byte][key byte]` for the
single-byte '+'/'-'/'*'// assignments reproduces all 14 correctly, with
zero mismatches — an earlier reading of this document (and a matching
comment in `src/memory/memory.py`) had the filler and function bytes
swapped (filler assumed second, not first), which decoded the same data as
nonsense function codes.

### 4.3 Key Byte Encoding

The key byte for an **unshifted** key at row `M`, physical column `N` is:

    byte = 16*(N-1) + M

For the **shifted** version of the same key:

    byte = 16*(N-1) + (M+8)

carrying into the high nibble when `M+8 >= 16` (only possible for `M=8`
rows). Confirmed exactly against `keyassigns.dm41`'s 14 assignments across
8 different physical keys, both shift states, with zero mismatches.

**Row 4 correction (2026-08-18, from real-hardware testing):** `N` above
is the *physical* column, which is **not** the same as the column digit
printed in a row-4 key's key-NUMBER (§2) for three of its four keys.
Row 4's `ENTER^` key is physically double-width -- it occupies both the
physical-column-1 *and* physical-column-2 slots, and there is no real key
at physical column 2 in row 4 at all (confirmed against Wickes' Figure
4-2, "Key Assignment Flag Bits": that diagram draws a single wide box
spanning columns 1-2 in row 4, with no bit assigned to column 2 -- this
is the "imaginary 42nd key under ENTER" mentioned in §4.5's flag-count
note). Row 4's key-NUMBER notation still numbers its three other keys
sequentially -- 42, 43, 44, same as every other row -- but they sit at
*physical* columns 3, 4, 5, not 2, 3, 4:

    key number -> physical column (row 4 only)
            41 -> 1   (ENTER^, double-width)
            42 -> 3
            43 -> 4
            44 -> 5

Every other row's key-number column digit equals its physical column
directly; row 4 is the sole exception. The user reported that assignments
made to key 42 via the app showed up on the calculator as key 41 and
didn't work, and that real-calculator row-4 assignments came back
missing or misplaced when read back by the app -- both are exactly what
using the wrong (unmapped) column would cause, since it wrote/read byte
`16*(2-1)+M` (the phantom position under `ENTER^`) instead of the real
key 42's `16*(3-1)+M`. `Memory._physical_column()` implements this
mapping, used by both `key_byte_for()` (this section) and
`_keyflags_bit()` (§4.5) -- the same wrong-column bug affected both the
Key Assignment Registers *and* the KEYFLAGS existence bit for keys 42-44,
so both needed the same fix.

### 4.4 Insertion Order

A brand-new assignment is always written into the **lowest** register
(`0x0C0`), immediately after its marker byte, pushing every existing entry
up toward `.END.`. Reading the buffer from `0x0C0` upward therefore lists
assignments **newest first** — the opposite of a naive top-to-bottom read
of a printed dump. See `docs/memory.md` §1.1 for how this compares to other
regions' addressing conventions.

This was confirmed twice independently: once against the original
8-assignment `keyassigns.dm41`, and a second time after deliberately
extending it to 14 assignments using a *different* insertion pattern (all
unshifted keys first, then all shifted) specifically to rule out
coincidence. Both times, every assignment landed exactly where strict
reverse-chronological insertion predicts.

**Consequence for import/export:** since the lookup (§4.7) is a linear scan
of the buffer, not an ordered search, correctness never depends on this
ordering — only byte-for-byte replication of a real device's dump would
need it reproduced.

### 4.5 The Key Assignment Flags (KEYFLAGS)

The processor keeps 72 flags — one bit per key, per shift state (36
unshifted + 36 shifted, counting an imaginary 42nd key under ENTER) —
packed as the first 36 bits of register F (unshifted) and the first 36 bits
of register e (shifted) respectively. This is a fast existence check
consulted *before* searching the Key Assignment Registers or scanning
global labels (§4.7) — **not** a cache of the assignment data itself, and
it's set identically regardless of whether the underlying assignment is a
built-in function (§4.2) or a global label (§4.6).

Bit position for key row `M`, physical column `N` (0-indexed, MSB-first —
the same convention `Memory.get_flag()`/`set_flag()` use for register d's
56 flags):

    bit = 36 - M - 8*(N-1)

`N` here is the *physical* column, not the key-NUMBER column digit — see
§4.3's row-4 correction; row 4's keys 42/43/44 sit at physical columns
3/4/5, and the "imaginary 42nd key under ENTER" mentioned just above is
literally the unused bit at row 4, physical column 2 (visible as the gap
in Wickes' Figure 4-2 where row 4's wide `ENTER^` box spans what would
otherwise be two separate boxes).

Confirmed against all three real fixtures simultaneously, using each
fixture's independently-known true key assignments: `keyassigns.dm41` (7
unshifted + 7 shifted keys, after it was extended from its original 4+4 —
see §4.4), `xrom-keyassignments.dm41` (4 unshifted-only peripheral
assignments), and `global-key-assignments.dm41` (2 unshifted-only program
assignments) — in every case, exactly the predicted bits are set in
register F (unshifted) or e (shifted), and no others.

**This constant was originally recorded as 37, not 36** — a mistake worth
documenting because of *why* it looked confirmed at first: the formula
`const - M - 8*(N-1)` is degenerate when only one row's data is available,
since different `(const, M)` pairs can produce identical bit sequences
(e.g. `const=37, M=2` and `const=36, M=1` agree on every bit). The original
8-assignment `keyassigns.dm41` happened to pair unshifted row 1 with
shifted row 2 (and unshifted row 5 with shifted row 6) — adjacent rows —
which created exactly this confound and made `const=37` look validated.
Testing a single hypothesis (`const=36`) against all three fixtures' true
`(M, N)` values at once, rather than one fixture at a time, is what caught
it — the wrong constant fails immediately once fixtures with non-adjacent
rows are checked simultaneously.

### 4.6 Global Label (User Program) Key Assignments

Assigning a key to a user program (`ASN "PROGNAME" [key]`) does **not**
create any entry in the Key Assignment Registers. Instead, the key byte
(§4.3's formula, same encoding) is written directly into the 4th byte of
the program's own global label header — see `docs/program.md` §5.2 for the
rest of that header's format. A label with no key assignment has `0x00` in
that byte.

Confirmed against `global-key-assignments.dm41`: two global labels ("AAA"
assigned to key 11, "BBB" to key 12) produced an entirely empty Key
Assignment Registers region (no `0xF0` marker anywhere from `0x0C0`
onward) while both keys' KEYFLAGS bits were set, and `Memory.list_programs()`
correctly reported each label's `key_assignment` byte.

### 4.7 The Lookup Algorithm

From Jarrett's SPME (Section 6B), when a USER-mode key is pressed:

1. Check the corresponding KEYFLAGS bit (§4.5). If clear, the key isn't
   assigned — run its default (printed) function, or, for a top-row/local-
   label key (A-J, a-e), search the current program for a matching local
   label first.
2. If the bit is set, search the Key Assignment Registers (§4.2) for a
   matching key byte.
3. If nothing is found there, scan every global label in Catalog 1 (from
   `.END.` up to the curtain) for a matching key-assignment byte (§4.6).
4. If that also comes up empty (not a normal case), fall back to the
   default function.

Global-label-only assignments are designed to always fail step 2 and
resolve at step 3 — that's expected, not an error case.

### 4.8 Function Byte Codes

Confirmed from real dumps and cross-checked against `docs/pdfs/byte_table.html`:
`+` = `0x40`, `-` = `0x41`, `*` = `0x42`, `/` = `0x43`. These are single
HP-41 opcodes (Prefix column in the byte table); peripheral/synthetic
functions use two bytes (an XROM-catalog prefix plus a selector byte — see
the byte table's `A0`-`A7` "XROM n-n+3" rows). The full translation table
is `src/memory/functions.py` (§6, item 3).

**Two-byte (XROM/peripheral) encoding, confirmed.** Given an XROM function's
catalog number `xrom` (the number before the comma in `docs/function_table.md`,
e.g. `25` for Extended Functions, `26` for Time) and its selector `fn` (the
number after the comma):

    byte1 = 0xA0 + floor(xrom / 4)
    byte2 = ((xrom mod 4) << 6) | fn

This matches Wickes' Table 5-1 examples (`CARD READER 30,00` → `A7 80`,
`PRINTER 29,00` → `A7 40`, `LIST 29,07` → `A7 47`, `PRP 29,13` → `A7 4D`,
`VER 30,05` → `A7 85`) and is independently confirmed against
`src/tests/data/xrom-keyassignments.dm41`, whose two Key Assignment
Registers decode as:

    0xC0: F0 A6 82 31 A6 81 21  ->  (A6,82)=XROM 26,02=ALMCAT -> key 14
                                    (A6,81)=XROM 26,01=ADATE  -> key 13
    0xC1: F0 A6 42 11 A6 41 01  ->  (A6,42)=XROM 25,02=ANUM   -> key 12
                                    (A6,41)=XROM 25,01=ALENG  -> key 11

— exactly the four assignments (ALENG→11, ANUM→12, ADATE→13, ALMCAT→14) the
dump was built to test, in the LIFO order §4.4 predicts, with both function
bytes carrying real data (no `0x04` filler) as expected for a two-byte
entry. `docs/function_table.md`'s Extended Functions ROM and Time ROM
tables give the `xrom,fn` numbers for every function in these two modules.

## 5. Known Unknowns

- The Alarms region's exact byte format (it sits immediately above the Key
  Assignment Registers, per Jarrett, with one "header" register declaring
  a count) hasn't been mined from the PDFs yet.
- **Whether a low-code (`< 64`) built-in function's Key Assignment
  Register byte literally equals its `function_table.md` decimal/hex
  code is still untested on a real device.** `function_table.md` was
  rebuilt as a single merged table with four columns per byte value:
  Instruction Prefix (the program-byte meaning, from `byte_table.html`),
  Instruction Length, Function (the ASN/key-assignment name), and
  Assignable? (whether that function can be put on a key at all). For
  codes 064 (`+`) through at least 224 (`XEQ`), Prefix and Function agree
  — the program byte and the key-assignment byte are the same value —
  and that range is already confirmed against a real dump (§4.8,
  `keyassigns.dm41`). For codes 000-015, Prefix and Function genuinely
  differ (`0x00`-`0x0F` mean `NULL`/`LBL 00`-`LBL 14` as program bytes,
  but `CAT`/`DEL`/`COPY`/`CLP`/`R/S`/`SIZE`/`BST`/`SST`/`ON`/`PACK`/
  `SHIFT`/`ASN` as functions) because those functions aren't FOCAL
  program opcodes at all — the correction from an earlier pass here
  confirms `005` is `R/S`, not a duplicate `STOP` (the real `STOP`
  opcode is `132`/`0x84`, matching Prefix and Function exactly, and is
  independently marked Assignable). The merged table also now records,
  for the first time, *which* of these low-code functions can be
  assigned to a key at all: `CAT`(000), `DEL`(002), `COPY`(003),
  `CLP`(004), `SIZE`(006), `BST`(007), `SST`(008), `PACK`(010), and
  `ASN`(015) are Assignable; `GTO..`(001), `R/S`(005), `ON`(009), and
  `SHIFT`(014) are not. **What's still not known:** whether the raw byte
  written into a Key Assignment Register's function-byte slot for one of
  those nine assignable low-code functions is the literal decimal/hex
  code shown (`0x00`-`0x0F`, which would collide with "TEXT 0"/"NULL"/
  "LBL nn" if misread as a program byte) or something else (e.g. a
  synthetic/2-byte encoding similar to the XROM case in §4.8). A small
  test dump assigning a few of the nine Assignable low-code functions
  (`CAT`, `SIZE`, `PACK`, `ASN` are good picks) to distinct keys would
  settle this the same way `xrom-keyassignments.dm41` settled the 2-byte
  case. **A candidate fixture for exactly this, `src/tests/data/
  keyassigntest.dm41`, has since turned up** — it decodes (with the §4.2
  filler-first byte order) as `CAT`(000)→key 11, `GTO..`(001)→key 21,
  `DEL`(002)→key 31, `COPY`(003)→key 51, i.e. the literal-byte-value
  hypothesis. But two things mark it as likely hand-crafted rather than a
  real device capture, so it's a data point, not confirmation: registers F
  and e are both entirely zero despite these having real Key Assignment
  Register entries (a real device sets the matching KEYFLAGS bit for any
  real assignment, §4.5), and one of the four assignments targets `GTO..`
  (001), which the merged table marks **not** Assignable, and another
  targets key `31` — the physical SHIFT key position, also never
  assignable (`gui/key_assignments_tab.py`'s `HP41_LAYOUT`). `Memory.set_key_assignment()`/
  `get_key_assignment()` (see `src/memory/memory.py`) currently implement
  the literal-byte-value hypothesis for these nine functions
  (`src/memory/functions.py`'s module docstring carries the same caveat);
  revisit if a genuine real-device capture ever contradicts it.

## 6. Requirements: Key Assignments Tab

A planned GUI tab for viewing and editing key assignments, and for
exporting/importing them. As each item below is implemented, remove it
from this list rather than marking it done — the reference material above
should be all that's left once the tab is finished.

**First pass implemented:** `gui/key_assignments_tab.py` (the two
synchronized "HP41"/"DM41L" keypad grids from the tab's original design)
and `gui/key_assignment_edit_dialog.py` (pick a named function or type a
raw hex byte / byte pair, or delete) cover viewing, creating, editing, and
deleting built-in/peripheral key assignments (§4.2) — backed by
`Memory.set_key_assignment()`/`get_key_assignment()`/
`delete_key_assignment()`/`list_key_assignments()` (§4.2/4.5,
`src/memory/memory.py`), which keep the Key Assignment Registers and
KEYFLAGS bits in sync on every edit.

**Second pass implemented:** global-label (program) assignments (§4.6)
are now also viewable and editable in the same tab/dialog, not just
read-only via the Programs tab. The edit dialog gained a third "Program"
tab (a picker over every named global label) alongside "Function" and
"Raw Hex" rather than a separate screen, since it's the same "pick a key,
pick what it does" interaction either way. Backed by three new
`Memory` methods: `get_program_for_key()`, `set_program_key_assignment()`,
and `clear_program_key_assignment()` — the write-side counterpart to
`_decode_label_name()`, which previously only read the label header's key
byte. Two behaviors worth knowing about, both driven by real constraints
of the storage format rather than being arbitrary GUI choices:

- A global label's header holds exactly one key byte (§4.6), unlike a
  physical key's independent unshifted/shifted slots — so assigning a
  program that's already on a different key *moves* it rather than
  creating a second assignment.
- The two storage mechanisms are made mutually exclusive on save: since
  the real lookup order (§4.7) always checks the Key Assignment Registers
  before global labels, letting both point at the same key at once would
  mean the global-label one silently never fires. `set_key_assignment()`
  now clears any global label pointing at the target key, and
  `set_program_key_assignment()` clears any Key Assignment Register entry
  (and any *other* program) there — same silent-overwrite precedent
  `set_key_assignment()` already used for a same-kind conflict.

Import and export are still not implemented — see items 1-2 below.

1. **Import mode: overwrite vs. append.** The user needs a choice, at
   import time, between replacing the current dump's key assignments
   entirely and adding the imported ones on top of what's already there.
   Needs a decision on collision handling for append mode (an imported
   assignment targeting a key that's already assigned in the target
   dump) — silently replace, warn, or skip; not yet decided.

2. **Export both kinds of assignment; warn and skip missing programs on
   import.** Export must include both built-in/peripheral assignments
   (from the Key Assignment Registers, §4.2) and global-label assignments
   (from `Memory.get_program_for_key()`/`list_programs()`'s
   `key_assignment` field, §4.6) — tagged distinctly, since a program
   assignment needs to travel as a *name* (program addresses aren't
   portable across dumps) while a built-in assignment travels as a
   function identifier. On import, a built-in/peripheral assignment can
   always be applied. A program assignment requires first checking
   whether a same-named global label exists in the *target* dump (via
   `list_programs()`); if not, the importer must warn the user and skip
   that specific assignment rather than fail the whole import or
   silently drop it.

3. **Remaining instruction-catalog gaps.** `src/memory/functions.py`
   (generated from `docs/function_table.md`, §1) now covers every
   single-byte Assignable function plus the Extended Functions and Time
   ROM catalogs (§4.8) as a directly-usable data structure — this is what
   the edit dialog's Function picker uses. Still not captured there or in
   `function_table.md`: any remaining HP-41CX-specific catalogs (X-Memory,
   Card Reader/Printer, per Wickes' Table 5-1). The low-code (`<64`)
   function-byte question (§5) is a correctness caveat on the data
   `functions.py` already has, not missing data — see §5 for the current
   status.
