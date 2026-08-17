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
- **`docs/pdfs/byte_table.html`** — a clean, already-extracted HTML table of all 256 byte values 0x00-0xFF with their Prefix/Suffix meanings (essentially Wickes' Table 2-1, "The HP-41C Byte Table," in directly-parseable form rather than a PDF diagram). Confirms every function byte code found in this document (see §4.8) and is the starting point for the full instruction-set table requirement (§6, item 5) — check here before re-deriving anything from the PDFs.
- `docs/memory.md` §1.1 ("Reading Direction Quick Reference") and its "Key Assignment Registers" subsection under §3 Main Memory — the condensed version of §4 below, kept there for readers of the general memory map.
- `docs/program.md` §5.2, "Decoding a Global Label's Name" — the format of a global label's header, whose 4th byte is a program's key assignment (see §4.6 below).

Everything in §4 below has been independently confirmed against real memory
dumps captured by hand on a DM41L (`src/tests/data/keyassigns.dm41` and
`src/tests/data/global-key-assignments.dm41`), not just derived from the
PDFs.

## 2. Terminology

- **Unshifted / shifted key** — every physical key on the keyboard can hold
  two independent assignments: one for a plain press, one for a press
  preceded by the shift ("f") key. They're stored completely separately (see §4.2
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
   the **Key Assignment Registers**, a variable-length buffer starting at `0x0C0` (§4.2).
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

    F0  [fn byte 1] [fn byte 2] [key byte]  [fn byte 1] [fn byte 2] [key byte]
         \___________ entry 1 __________/    \__________ entry 2 __________/

A most built-in HP-41 function needs only one function byte; the second byte is
filler (`0x04`, which happens to read as "LBL 03" if the register is listed
as a program). A peripheral/ROM function's XROM code uses both function
bytes. An odd number of assignments, and deleting assignments, can leave a register half-full (Wickes' "KP" utility repacks these).

### 4.3 Key Byte Encoding

The key byte for an **unshifted** key at row `M`, column `N` is:

    byte = 16*(N-1) + M

For the **shifted** version of the same key:

    byte = 16*(N-1) + (M+8)

carrying into the high nibble when `M+8 >= 16` (only possible for `M=8`
rows). (Confirmed against `keyassigns.dm41`'s 14 assignments across
8 different physical keys, both shift states, with zero mismatches. **TODO:**
Perform a full suite of tests, evaluating all 35 assignable keys.)

**Note:** The Key Byte encoding matches the original HP41's keypad layout. The DM41L's keypad is laid out in a different order. Any of the main keypad keys are re-assignable; the "ON", "USR", "PRGM"/"PGM" and "ALPHA"/"a" keys are not reassignable on either the HP41 or the DM41L.

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

In addition to global assignments, a program may dynamically re-define keys A-E and "a-e". 
- These definitions are only present while that program is active and do not alter the key assignment bitmask or key assignment registers. 
- Actual user key assignments will take precedence over in-program assignments.

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

## 5. Known Unknowns

- The Alarms region's exact byte format (it sits immediately above the Key
  Assignment Registers, per Jarrett, with one "header" register declaring
  a count) hasn't been mined from the PDFs yet.
- Whether a peripheral/XROM function assignment's key byte and register
  packing behave identically to the built-in case once real 2-byte
  entries are captured in a dump — only the *filler-byte* (1-byte
  function) case has been directly confirmed so far (§4.2).
- `Memory.key_assignments_end()` (see `src/memory/memory.py`) is only
  recomputed when a dump is loaded, not after a live edit — relevant once
  an editor exists (§6, item 4).

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

4. **A keypad-shaped table for viewing/editing.** The tab's main view
   needs to visually approximate the physical HP-41CX/DM41L keyboard
   layout (§4.3's row/column grid), showing both the unshifted and
   shifted assignment for each key. This requires a unified accessor that
   merges both storage mechanisms (§4.1) into one "what is this key
   currently assigned to" view — reading the Key Assignment Registers and
   every global label's key-assignment byte together — since the two
   sources need to be presented identically to the user despite being
   stored completely differently.

5. **A complete HP-41CX instruction byte table.** Needed both to display
   an existing assignment's function name and to translate a user's
   chosen function back into the correct byte(s) when creating one.
   `docs/pdfs/byte_table.html` (§1) already covers the base 256-byte
   table and should be the starting point rather than re-deriving it from
   the Wickes/QRG PDFs — what's still needed is extending it to the
   HP-41CX-specific functions (time module, extended functions, X-Memory)
   that live behind the XROM-catalog prefix bytes, and converting the
   whole thing into a directly-usable data structure (e.g. JSON or a
   Python dict) rather than parsing the HTML at runtime.
