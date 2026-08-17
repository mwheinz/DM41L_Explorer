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
- **`docs/pdfs/byte_table.html`** — a clean, already-extracted HTML table of all 256 byte values 0x00-0xFF with their Prefix/Suffix meanings (essentially Wickes' Table 2-1, "The HP-41C Byte Table," in directly-parseable form rather than a PDF diagram). Confirms every built-in function byte code found in this document (see §4.8) and is a starting point for the full instruction-set table requirement (§6, item 5) — check here before re-deriving anything from the PDFs.
- **`docs/function_table.md`** — the DM41L's actual instruction set: a merged 256-row table (Dec, Hex, Instruction Prefix, Instruction Length, Function, Assignable?) covering every base byte value, plus separate Extended Functions ROM and Time ROM catalogs, built from "A programmers handbook v.2.07.pdf." The merge makes explicit that Prefix (program-byte meaning) and Function (key-assignment meaning) are the same for codes 064-224 but diverge for codes 000-015 (§5), and records for the first time which low-code functions can be key-assigned at all. Confirms every 2-byte peripheral function code found in this document (see §4.8) and, together with `byte_table.html`, is most of requirement 5 (§6) already done.
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

    F0  [fn byte 1] [fn byte 2 / filler] [key byte]  [fn byte 1] [fn byte 2 / filler] [key byte]
        \_____________ entry 1 ______________/      \_____________ entry 2 ______________/

A built-in HP-41 function needs only one function byte; the second byte is
filler (`0x04`, which happens to read as "LBL 03" if the register is listed
as a program). A peripheral/ROM function's XROM code uses both function
bytes — confirmed against `xrom-keyassignments.dm41` (§4.8). An odd number
of assignments leaves one register half-full (Wickes' "KP" utility repacks
these).

### 4.3 Key Byte Encoding

The key byte for an **unshifted** key at row `M`, column `N` is:

    byte = 16*(N-1) + M

For the **shifted** version of the same key:

    byte = 16*(N-1) + (M+8)

carrying into the high nibble when `M+8 >= 16` (only possible for `M=8`
rows). Confirmed exactly against `keyassigns.dm41`'s 14 assignments across
8 different physical keys, both shift states, with zero mismatches.

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

Bit position for key row `M`, column `N`:

    bit = 37 - M - 8*(N-1)

Confirmed against both `keyassigns.dm41` (4 unshifted + 4 shifted keys, all
8 corresponding bits set and no others) and `global-key-assignments.dm41`
(2 unshifted-only program assignments, exactly the 2 corresponding bits set
in register F and register e entirely zero).

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
the byte table's `A0`-`A7` "XROM n-n+3" rows). A full translation table is
requirement 5 below.

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
- `Memory.key_assignments_end()` (see `src/memory/memory.py`) is only
  recomputed when a dump is loaded, not after a live edit — relevant once
  an editor exists (§6, item 4).
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
  case.

## 6. Requirements: Key Assignments Tab

A planned GUI tab for viewing and editing key assignments, and for
exporting/importing them. As each item below is implemented, remove it
from this list rather than marking it done — the reference material above
should be all that's left once the tab is finished.

1. **Import mode: overwrite vs. append.** The user needs a choice, at
   import time, between replacing the current dump's key assignments
   entirely and adding the imported ones on top of what's already there.
   Needs a decision on collision handling for append mode (an imported
   assignment targeting a key that's already assigned in the target
   dump) — silently replace, warn, or skip; not yet decided.

2. **Status-register bitmasks are derived, not stored.** Export must not
   include the raw contents of registers F/e — they're fully
   reconstructable from the assignments themselves (§4.5). Import must
   regenerate the correct KEYFLAGS bits for every assignment being
   written, using the §4.5 formula. This needs a new `Memory` method
   analogous to `set_flag()`/`get_flag()` but operating on the KEYFLAGS
   bitmap in F/e rather than the 56 flags in register d — those are
   unrelated bitmaps despite the register-d flags document
   (`docs/flags.md`) using similar bit-indexing language. Overwrite-mode
   import, and any future single-key edit/clear in the tab itself, will
   also need to *clear* stale bits, not just set new ones.

3. **Export both kinds of assignment; warn and skip missing programs on
   import.** Export must include both built-in/peripheral assignments
   (from the Key Assignment Registers, §4.2) and global-label assignments
   (from `Memory.list_programs()`'s `key_assignment` field, §4.6) —
   tagged distinctly, since a program assignment needs to travel as a
   *name* (program addresses aren't portable across dumps) while a
   built-in assignment travels as a function identifier. On import, a
   built-in/peripheral assignment can always be applied. A program
   assignment requires first checking whether a same-named global label
   exists in the *target* dump (via `list_programs()`); if not, the
   importer must warn the user and skip that specific assignment rather
   than fail the whole import or silently drop it.

4. **Two synchronized keypad-shaped tables for viewing/editing.** The tab
   shows **two** keypad grids, one above the other, both displaying the
   same underlying assignment data — an edit made in either one must be
   reflected immediately in the other. Both use the key-number notation
   from §2 (`MN` as the user sees it engraved on the keyboard, *not* the
   internal key-byte encoding of §4.3), and both need to show the
   unshifted and shifted assignment for each key.

   The **top table, "HP41"**, approximates the classic HP-41's physical
   row layout — 8 rows, the first three holding 5 keys each and the rest
   holding 4, with one gap in row 3 where key `31` would be — that
   position is the physical **SHIFT** key itself, which can never hold an
   assignment (consistent with `function_table.md`'s Assignable? column,
   §5, which also lists the `SHIFT` *function*, code 014, as not
   assignable):

   | Row | Keys |
   |--|--|
   | 1 | 11, 12, 13, 14, 15 |
   | 2 | 21, 22, 23, 24, 25 |
   | 3 | *(shift)*, 32, 33, 34, 35 |
   | 4 | 41, 42, 43, 44 |
   | 5 | 51, 52, 53, 54 |
   | 6 | 61, 62, 63, 64 |
   | 7 | 71, 72, 73, 74 |
   | 8 | 81, 82, 83, 84 |

   The **bottom table, "DM41L"**, approximates the DM41L's actual physical
   keyboard — a more compact 4-row-by-10-column arrangement of the exact
   same 34 assignable keys, several of them relocated relative to the HP41
   layout above (note key `42` in row 1, `43` in row 2, and `41`/`44` in
   row 3 — not in row-4 order like the HP41 table). The remaining cells
   are real physical keys too, just never assignable ones — mode-toggle
   and system keys rather than FOCAL function keys: USR (row 3, col 1),
   PGM (row 3, col 2), ON (row 4, col 1), SHIFT (row 4, col 2), ALPHA (row
   4, col 3), and one blank/spare position (row 4, col 6):

   | Row | Keys |
   |--|--|
   | 1 | 11, 12, 13, 14, 15, 42, 51, 52, 53, 54 |
   | 2 | 21, 22, 23, 24, 25, 43, 61, 62, 63, 64 |
   | 3 | *(USR)*, *(PGM)*, 32, 35, 44, 41, 71, 72, 73, 74 |
   | 4 | *(ON)*, *(SHIFT)*, *(ALPHA)*, 33, 34, *(blank)*, 81, 82, 83, 84 |

   Implementation-wise this means a single shared data model (a unified
   accessor merging both storage mechanisms per §4.1, reading the Key
   Assignment Registers and every global label's key-assignment byte
   together into one "what is this key assigned to" view) driving two
   independent grid layouts — a lookup table mapping each key number to
   its `(row, column)` position in each of the two grids above, both
   rendering from and writing back to the same model, with no assumption
   that the two grids share a coordinate system.

5. **A complete HP-41CX instruction byte table.** Needed both to display
   an existing assignment's function name and to translate a user's
   chosen function back into the correct byte(s) when creating one, and
   to know which functions are even offerable in a key-assignment picker
   UI. `docs/function_table.md` (§1) now covers most of this ground in
   one merged table — Instruction Prefix, Length, Function name, and an
   Assignable? column that directly answers the picker-UI question —
   plus the Extended Functions and Time ROM catalogs (§4.8), derived from
   "A programmers handbook." What's still needed: converting it into a
   single directly-usable data structure (e.g. JSON or a Python dict,
   keyed by the encodings in §4.8) rather than parsing the markdown table
   at runtime; resolving the §5 open question about whether a low-code
   (`<64`) function's Key Assignment Register byte equals its
   `function_table.md` code, since the Assignable? column lists nine
   such functions (`CAT`, `DEL`, `COPY`, `CLP`, `SIZE`, `BST`, `SST`,
   `PACK`, `ASN`) that the picker will need to encode correctly; and
   filling in any remaining HP-41CX-specific catalogs (X-Memory, Card
   Reader/Printer, per Wickes' Table 5-1) not yet captured in
   `function_table.md`.
