# Reading and Writing HP-41 Program Source (.txt) — Feasibility & Design Report

**Date:** 2026-09-02
**Scope:** What it would take to give DM41L_Explorer the ability to read a plain-text HP-41
keystroke listing and turn it into a program in memory (compile), and to take a program
already in memory and write it back out as that same kind of text file (decompile). No
code has been changed as part of this report — it's a planning document only.

## 1. Where this fits today

README.md's "Known limitations" section already names this gap directly:

> Program memory is listed (names, END markers, raw chain distances) but not decoded into
> actual instructions, and can't be created or edited from this tool yet.

The Programs tab currently offers Export/Import/Remove, but Export and Import only cover
three binary-derived formats: `.raw`, `.dat`, and `.ppc` (a word-wrapped variant of `.dat`
used for PPC Calculator Journal listings). All three are just different textual or binary
*encodings of the same opcode bytes* — none of them is a human-readable instruction
listing. Nothing in the codebase today maps an opcode byte to a mnemonic like `RCL 04` or
`XEQ "PK-N"`, or back again.

There's a good reason to be optimistic about closing this gap, though: a real reference
implementation already sits on this machine, and this project has a track record of
porting from it.

## 2. The reference implementation: `hp41uc`

`~/Work/hp41uc/Source/` contains a C command-line tool (GPLv3, by Leo Duran) that already
does exactly this conversion, among other things, and DM41L_Explorer already leans on it
in two places: `opcode_scan.py`'s docstring says it's "a direct Python port of `seek_end()`
from hp41uc," and `program_files.py`'s RAW/DAT encoders/decoders are also modeled on
hp41uc's format. So there's precedent for treating hp41uc as the design source rather than
inventing a format from scratch — and a real sample file already lives in the test
fixtures (`src/tests/data/tower.txt`, confirmed to be an exact prefix of hp41uc's own
`tower-update2.txt` sample; `tower.raw`/`tower.dat` are hp41uc's compiled output from it,
per a comment in `test_program_export.py`). That sample currently isn't read by any test —
it's just sitting there as provenance for the other two fixtures — but it's a ready-made
first target for a round-trip test once this is built.

The two files that matter are `compile.c` (text → bytes) and `decomp.c` (bytes → text).
Both turn out to be simpler than "assembler" suggests — more on why in §3.

### 2.1 The text format, in brief

One instruction per line, whitespace-separated tokens, `;` or `#` starts a trailing
comment. A few real lines from `tower.txt`, verbatim:

```
LBL 21 ;Tower of Skelos Game Program
FC? 03
GTO 20
3 E3
ST+ 19
LBL 20
AVIEW
XROM 25,46 ;X<>F
LBL "TWR" ;Tower of Skelos Initialization
">":" ;Append colon
XEQ "PK-N" ;Pack numbers to text string
END ;1084 BYTES
```

Quoted text (`"..."`) is an ALPHA string; a leading `>` (or `|-`) means "append to ALPHA"
rather than "clear ALPHA and load." `LBL nn`/`GTO nn`/`XEQ nn` with a two-digit number is a
*local* label (found only within the current program); `LBL "NAME"` is a *global* label
(found by a full-memory name search — this is what `XEQ "NAME"` from outside the program,
or a key assignment, actually invokes). `END` closes the program.

### 2.2 Why this is more tractable than "write an assembler"

The single most important finding from studying `compile.c`/`decomp.c`: **there is no
branch-offset computation anywhere in this format.** A numeric `GTO 20` doesn't get
compiled into "jump forward 14 bytes" — it's compiled into the literal bytes `D0 00 14`
(0x14 = 20 decimal), i.e. it just encodes the *target label's number*. The real calculator
resolves that at *run time* by searching the current program for a matching `LBL 20` byte
pattern — the same kind of search a global `XEQ "NAME"` does, just scoped to one program
instead of all of memory. This means a Python compiler doesn't need a symbol table, forward
references, or offset patching at all — every "address" in the format is either a small
literal number or a length-prefixed name string, both of which get encoded independent of
where anything else in the program lives. That collapses what sounds like "port a
compiler and disassembler" into something closer to "port a byte-range dispatch table
plus a line tokenizer," which is a much smaller, much more mechanical task.

The whole opcode space is a fixed table of byte ranges — e.g. `0x01`–`0x0F` is `LBL
00`–`LBL 14`, `0x20`–`0x8F` is ~110 single-byte zero-operand functions, `0xC0`–`0xCD` is a
global label header (or an END, disambiguated by the next byte), `0xF0`–`0xFF` is an ALPHA
string whose low nibble gives its length, and so on. Every instruction's byte length is
determined purely by its first byte or two, with no lookahead beyond that.

### 2.3 A few real gotchas worth carrying over (not exhaustive — see the two research
appendices below for the full list)

- **Two numeric literals back-to-back need a `0x00` separator byte — confirmed against
  real hardware.** Digit bytes (`0x10`–`0x1C`) don't have a length prefix and would
  otherwise run together; a new fixture, `src/tests/data/numtest.dm41` (a real DM41
  program the user built specifically to test this — `LBL "NUMTEST"`, the number
  `12345`, the number `67890`, `+`, `END`), confirms the separator byte-for-byte: its
  26-byte program body is the 11-byte global label header, then `11 12 13 14 15`
  (digits 1‑2‑3‑4‑5), then a lone `00`, then `16 17 18 19 10` (digits 6‑7‑8‑9‑0), then
  `40` (`+`), then the 3-byte END trailer — exactly the "second number gets a leading
  `0x00`" behavior hp41uc's source predicts, with nothing between the two numbers in
  the *source* text (no explicit separator token needed on the text side — a Python
  decompiler emits two plain number lines back to back, and a compiler must remember
  "the last instruction I emitted was a bare number" and silently insert the `0x00`
  whenever the next one is too, matching the decompiler's own silent swallow of a lone
  `0x00` on the way back).
- **Global labels vs. same-named local letters — resolved, confirmed against real
  hardware (see the update at the end of §2.3 and §5).** hp41uc's own docs describe
  `LBL "A"` as ambiguous with local letter label `A`, needing a "force global" flag to
  disambiguate. It isn't actually ambiguous — see below.
- Non-printable bytes inside ALPHA text render as `\xHH` escapes in hp41uc's own output
  — see §3.1 below for how that interacts with this project's existing `trigraphs.py`
  escape scheme, and the conflict/resolution found there. hp41uc also emits
  informational (non-recompilable) `; hex-byte comment` lines for two truly unassigned
  "spare" opcode bytes (0xAF, 0xB0) so a round trip doesn't silently lose calculator
  memory content it has no mnemonic for.
- **XROM (plug-in module) instructions — scope narrowed, per the user's direction (see
  §3.1).** hp41uc ships a name table covering ~400 entries across roughly 15 real HP-41
  modules, but the DM41L itself only emulates two of them (Extended Functions and Time),
  and DM41L_Explorer already has a complete, verified name table for exactly those two —
  see §3.1. Any other module number, or an unrecognized function number within those two
  modules, is out of scope and should be a compile-time error rather than silently
  falling back to literal `XROM mm,ff` syntax the way hp41uc does — the user's explicit
  call, since there's no real DM41L hardware behavior to reproduce for a module it
  doesn't have.
- The END trailer encodes total program size in "registers of 7 bytes" plus a small
  remainder — this is the same distance/size encoding documented at length in this
  project's own `docs/program.md` (§5.1), which was reverse-engineered independently and
  agrees with hp41uc's version.

**Update — the single-letter-label question above is now settled, not open.** A new
fixture, `src/tests/data/samplelabels.dm41`, was created and captured by the user
directly on a real DM41 specifically to test this, and decoding it byte-for-byte
confirms the following: local letter labels `A` through `J` always compile to the
compact 2-byte local form (`CF 66`–`CF 6F`, the same 10-entry postfix table used
throughout §2), and every *other* single letter (`K`, `L`, `O`, `T`, `X`, `Z` were the
ones tested) compiles to the full 5-byte global form (`C0/Cn 00 F2 00 <letter-byte>`)
every time — with no flag or special case involved. The reason turns out to be
simpler than hp41uc's docs suggest: the local-letter encoding only ever had 10 slots
to begin with (matching the 10 physical top-row calculator keys, A–E unshifted and
shifted — see the aside below), so `K`–`Z` were never representable as a local label
at all. There's nothing to disambiguate; entering one necessarily produces a genuine
one-character global name, because that's the only encoding that exists for it. **A
Python port needs only the same 10-letter (A–J) table §2 already describes — every
other single letter defaults to global automatically, no force-global flag or special
case required.** hp41uc's own "-g force global" flag would only ever matter for A–J,
where both encodings genuinely exist.

One incidental finding from the same fixture: the real DM41 accepted two labels both
named `LBL "K"` in the same program without complaint — duplicate global label names
aren't rejected at creation time on real hardware. Worth checking that a future text
importer doesn't end up stricter than that (DM41L_Explorer's own
`_check_no_duplicate_labels()` currently guards against duplicate names on *import*)
without a deliberate decision to do so.

*Aside, not part of the text-format design but useful context*: the user separately
confirmed that in USER-mode key assignments, local labels A–J belonging to whichever
program is currently active auto-assign themselves to key positions 11–15/21–25 (the
physical top two key rows) automatically. This is a live calculator behavior, not
anything stored in the memory dump's KEYFLAGS bits the way `memory/key_assignments.py`
models user-defined `ASN` assignments — it's a nice confirmation of *why* the
instruction set reserves exactly 10 local letters, but there's nothing to read or
write in a program's bytes for it, so it has no bearing on this feature. Flagging only
because it may be useful background if Key Assignments documentation gets revisited
later.

## 3. What already exists in DM41L_Explorer to build on

This is the encouraging part — several of the pieces a text-import/export feature needs
are already written, tested, and in some cases directly ported from hp41uc already:

| Piece needed | Status |
|---|---|
| ALPHA text byte ↔ string round-trip (7-bit character set, escapes) | **Already exists** — `src/memory/trigraphs.py` (`encode_trigraphs`/`decode_trigraphs`), fully bidirectional for every byte value 0–255, with its own shorthand table for FOCAL's special glyphs (Σ, →, ↑, etc.) and a `\nnn` fallback. Directly reusable for ALPHA string literals. |
| Program boundary / instruction-length classification | **Already exists, partially** — `src/memory/opcode_scan.py`'s `find_program_end`/`scan_global_markers_forward` already classify every opcode's byte-length (1/2/3/variable) exactly the way `decomp.c` does, since it's a direct port of hp41uc's `seek_end()`. It does *not* map bytes to mnemonic names — it only knows lengths, not meanings — but the length-classification logic can be extended or reused as the skeleton of a real decoder. |
| Program/chain plumbing — splice a program's bytes in or out of memory, address it, relink the chain | **Already exists** — `src/memory/program_memory.py` (`import_program`, `get_program_bytes`, `list_programs`, etc.) and `src/memory/program_chain.py`. This is the layer a new text importer/exporter would sit *on top of*: text ⇄ bytes is the missing piece, bytes ⇄ memory already works. |
| Container format encode/decode pattern to follow | **Already exists as a template** — `src/memory/program_files.py` currently has `encode_program_raw/decode_program_raw`, `encode_program_dat/decode_program_dat`, `encode_program_ppc/decode_program_ppc`. Its own docstring literally says "Does not support decompiling into text files (yet)" — a `encode_program_txt`/`decode_program_txt` pair, following the exact same shape, is the natural extension point. |
| GUI hook | **Does not exist yet, but the hook point is obvious** — `src/gui/program_tab.py`'s `_EXPORT_FORMATS`/`_IMPORT_FORMATS` lists (currently `.raw`/`.dat`/`.ppc`) are where `.txt` gets added; the Export/Import button handlers already dispatch by file extension. |
| Opcode-byte ↔ mnemonic table (the actual instruction set, keyed by the in-*program* byte encoding) | **Partially exists — more reusable than first thought; see §3.1.** `src/memory/functions.py`'s own docstring warns its `SINGLE_BYTE_FUNCTIONS` table is keyed to the *Key Assignment Register's* byte encoding, not the in-program instruction-prefix encoding — true for its low-code entries (below 0x40: `CAT`, `DEL`, `SIZE`, `BST`, `SST`, `ASN`, etc. — assignment-only, no program-byte meaning at all). But every entry checked at 0x40 and above (`+`→0x40, `Σ+`→0x47, `SIN`→0x59, `AVIEW`→0x7E, `RCL`→0x90, `STO`→0x91, …) turns out to numerically match the real in-program opcode byte exactly, cross-checked against hp41uc's own byte-level decode from §2. And its `XROM_FUNCTIONS` table (keyed `(0xA6, byte2)`) already covers exactly the two ROM modules — Extended Functions and Time — the DM41L itself emulates, which the user has confirmed (§3.1) is all this feature needs to support. So a real opcode table can *reuse* `functions.py`'s data directly for XROM and for every 0x40+ single-byte function; what's still missing is the postfix/register-name table for 2-and-3-byte instructions (`RCL nn`, `GTO nn`, etc.) and the below-0x40 KAR-only entries need excluding, not adapting. |
| Text tokenizer (lines → instruction tokens) | **Does not exist.** New code, though hp41uc's version (`get_line_args`/`is_inquotes` in `hp41uc.c`) is simple enough (quote-aware whitespace splitting, `;`/`#` comments, optional line-number prefix) to port in well under a day. |
| Text formatter (instructions → mnemonic lines, with comments) | **Does not exist.** New code — the decompile side of the work. |

### 3.1 Two follow-up decisions, resolved this session

**ALPHA text escapes: `trigraphs.py` vs. hp41uc's `\xHH`.** hp41uc's compiler accepts
C-style escapes inside quoted text: `\a \b \f \n \r \t \v \? \" \' \\`, plus `\xHH`/`\HH`
hex-byte escapes. This project already has its own, unrelated escape scheme in
`src/memory/trigraphs.py` (`encode_trigraphs`/`decode_trigraphs`) — a `\mnemonic`
shorthand table for FOCAL's non-ASCII display symbols, plus a fully general `\nnn`
(3-decimal-digit) fallback that already covers every byte value 0–255. Read in full to
check for the conflict the user asked about: **there is a real one.** `trigraphs.py`'s
shorthand table already maps `\x` to byte `0x01` (the "times" symbol) — its
`_SHORTHAND_BY_BYTE` dict has the entry `0x01: "x"`. Since `\nnn` already gives full
round-trip coverage of every byte, hp41uc's hex-escape spelling isn't *needed*, only
convenient for accepting
hp41uc-authored `.txt` source without translation — but if it's added, it can't reuse
lowercase `\x`, or `\x01` would become ambiguous with the existing times-symbol
shorthand. **Recommendation: spell the hex-byte escape `\X` (capital) instead** — checked
against every current shorthand key (`--`, `x`, `u`, `<)`, `/=`, `\`, `^|`, `T`, `E`,
`+`), `X` isn't used by any of them, and the matcher is already case-sensitive (both
`T` and `x` exist as *different* entries), so this is a clean, non-breaking addition:
`decode_trigraphs` (or a variant of it) gains a new case for `\X` followed by exactly 2
hex digits, alongside its existing shorthand and `\nnn` cases. Checked the rest of
hp41uc's escape list the same way: `\a \b \f \n \r \t \v \? \" \'` — **none of them
collide** with any current shorthand key either (case-sensitive match again rules out
any clash with `\T`/`\E`). Whether to also accept those C-style single-letter escapes
(for smoother acceptance of existing hp41uc/community `.txt` files) or just `\X`/`\nnn`
is a smaller follow-up decision — either way, the encoder should keep emitting this
project's existing canonical `\nnn` form (consistent with every other file format in
the app), while the decoder can be liberal about what it accepts on the way in.

**XROM scope, and the reusable table.** The user has confirmed the DM41L only emulates
two plug-in ROM modules — Extended Functions and Time — not the full ~15-module,
~400-function catalog hp41uc's own table covers. `src/memory/functions.py` already has
a complete, verified table for exactly those two (`XROM_FUNCTIONS`, keyed `(0xA6,
byte2)` — its own comment says "Extended Functions ROM (25,xx) and Time ROM (26,xx)"),
confirmed reusable as-is in §3's table above. **Decision (the user's call, not
hp41uc's): any XROM reference in source text that isn't in this table — wrong module
number, or an unrecognized function number within these two modules — is a compile
error**, not a silent fallback to literal `XROM mm,ff` syntax the way hp41uc handles
an unknown module. There's no real hardware behavior on a module the DM41L doesn't
have, so erroring is more honest than accepting text that could never actually run.
This also resolves what was an open question in §5 of the previous version of this
report (how much of the ~400-entry table to bring in) — the answer is "all of it, since
it's already there and complete for the modules that matter," with nothing to phase in
later.

## 4. Proposed design

### 4.1 New module: `src/memory/program_text.py` (name flexible)

This is the one genuinely new piece of substance. It would hold, mirroring the
existing `program_files.py` pattern:

- **An opcode table** — the byte-range dispatch table from §2.2/2.3, expressed as
  something like a small set of Python dicts/lists keyed by opcode byte or byte-range,
  each entry carrying: mnemonic name, total instruction length, and how to interpret any
  operand byte(s) (register/flag/digit postfix, XROM module/function pair, ALPHA text
  length, or global-label name). Given this project's established taste (see the code
  style note below), this is a natural place for an `Enum` of instruction *categories*
  (single-byte, 2-byte-postfix, 3-byte-local, global-label/END, XROM, ALPHA-text) even
  though the underlying byte values themselves are just data, not states.
- **`encode_program_txt(instruction_bytes: bytes) -> str`** — the decompiler: walk the
  bytes with the opcode table, emit one mnemonic line per instruction, handling the
  numeric-digit-run-without-separator quirk and the `0x00` separator-byte quirk from
  §2.3, delegate ALPHA text through `trigraphs.py`.
- **`decode_program_txt(text: str) -> bytes`** — the compiler: tokenize a line at a time
  (quote-aware), look up each mnemonic, assemble its bytes, insert the `0x00` separator
  where two numeric literals are adjacent, and build the END trailer from the
  accumulated size — same register/byte-count formula this project's own
  `docs/program.md` §5.1 already documents independently for reading END markers, so
  writing one is the mirror image of code the project effectively already understands.
- **XROM names** — no new table needed. Per §3.1's resolution, `src/memory/
  functions.py`'s existing `XROM_FUNCTIONS` table already covers exactly the two
  modules (Extended Functions, Time) this feature needs to support; nothing from
  hp41uc's own ~400-entry table gets copied in.

### 4.2 Extending `program_files.py`

Add `encode_program_txt`/`decode_program_txt` there (thin wrappers calling into
`program_text.py`, or the logic could live directly in `program_files.py` — whichever
keeps the module sizes reasonable), following the exact same function-naming and
call-site pattern as the RAW/DAT/PPC pair already there. This keeps "how do I get a
program's bytes into/out of a particular file format" all in one place, consistent with
how the codebase already organizes this.

### 4.3 Extending `program_tab.py`

Add `.txt` to `_EXPORT_FORMATS` and `_IMPORT_FORMATS`. Export becomes "get program
bytes → `encode_program_txt` → write file." Import becomes "read file →
`decode_program_txt` → `Memory.import_program()`" — the last step already exists and is
already tested independently of file format. **Confirmed: no packing step belongs
here.** The compiler's job ends at "produce instruction bytes for one program";
`import_program()` already splices that in as the newest program without needing
memory to be pre-packed, and `Memory.pack()`/`ProgramMemory.repack()` (issues #6/#31)
is a separate, already-implemented, user-invoked operation (Tools > Pack Memory...) —
nothing about `.txt` import changes that relationship.

### 4.4 Testing plan

`src/tests/data/tower.txt`/`tower.raw`/`tower.dat` already form a ready-made
round-trip fixture set — and because `tower.raw` is *hp41uc's own compiled output* from
`tower.txt`, a byte-identical match on `decode_program_txt(tower.txt) == tower.raw`'s
program bytes is a strong, independent correctness check (not just "does the code agree
with itself"). The reverse direction (`encode_program_txt(tower.raw)` reproducing
`tower.txt`) is a good second test too — per §5's decision to match hp41uc's comment
style closely, this one should be closer to an exact textual match than a purely
semantic one, modulo the inherent "user-written prose comments can't survive a
compile" limitation §5 also notes (`tower.txt`'s own comments, having been compiled
away, obviously can't come back on redecompiling `tower.raw` — the test should compare
against a version of `tower.txt` with human prose comments stripped, or compare
opcode-by-opcode ignoring comment text, rather than expecting a truly byte-identical
file).

Beyond that one fixture, the natural place to get more coverage cheaply is running the
real hp41uc binary (it's right there, already built — `Source/hp41uc`) against a handful
of hand-written or found `.txt` programs and diffing its `.raw` output against this
project's own compiler, plus running its decompiler against a few of this project's
existing `.dm41` sample programs (APPTEST, LANDER, TARG, PURXM, etc. — already
extractable via `get_program_bytes()`) and comparing.

## 5. Decisions (resolved by the user, 2026-09-02)

Every judgment call this report originally raised as open has now been settled:

- **Exact vs. semantic round-trip: match hp41uc's comment style as closely as
  possible.** Decompile output should follow hp41uc's own conventions — the `;NNNN
  BYTES` trailer on `END`, `;XROM mm,ff` annotations, and so on — closely enough that
  `tower.txt` (already an hp41uc file sitting in the fixtures) and other
  hp41uc/community-authored `.txt` archives feel native rather than foreign. The one
  accepted limit, per the user's own framing: user-*written* prose comments (the
  free-text after a `;` that a human typed, as opposed to a comment the tool itself
  generates) can never be perfectly reproduced on a round trip through raw bytes —
  compiling a `.txt` file discards comments entirely (they're not part of the
  instruction stream), so a decompile of the resulting program can only regenerate the
  tool's *own* mechanical annotations, never recover the original human wording. That's
  an inherent property of the format, not a design shortcut — hp41uc has exactly the
  same limitation.
- **Private programs: not supported.** No attempt to read or write the HP-41's
  "private" program flag. On compile, the END trailer's flags byte is always the
  normal, non-private form (matching hp41uc's own compiler, which never emits private
  either). On decompile, nothing about the flags byte needs to be inspected beyond what
  already distinguishes an END from a label header (§2.1) — the instruction bytes
  themselves aren't encrypted or otherwise altered by the private flag on real
  hardware, so a private program's *content* would decompile identically to a normal
  one; DM41L_Explorer just won't try to reproduce or preserve the flag itself. No
  special-case code needed either direction.
- **Packing: not the compiler's job.** Confirmed in §4.3 — `decode_program_txt()`
  produces one program's instruction bytes and hands them to the existing
  `import_program()`, unchanged; `Memory.pack()`/`ProgramMemory.repack()` stays the
  separate, user-invoked operation it already is (Tools > Pack Memory...). Nothing
  about `.txt` import needs to trigger, replicate, or special-case packing.
- **Synthetic/undocumented opcodes: match hp41uc's behavior.** The two truly spare
  bytes (0xAF, 0xB0) and any opcode byte this project's table hasn't been taught yet
  render as an informational, non-recompilable comment line on decompile (hp41uc's own
  approach, §2.3/§4) — never silently dropped or corrupted. A decompile→edit→recompile
  round trip must be able to carry a byte-for-byte-unknown instruction through
  untouched as long as the user doesn't try to hand-edit that particular line.
- **C-style single-letter escapes: accepted on decode.** `\a \b \f \n \r \t \v \?`
  (alongside the existing `\nnn`/`\mnemonic` forms and the new `\XHH` from §3.1) are all
  recognized as synonyms when *parsing* ALPHA text, for smoother acceptance of existing
  hp41uc/community `.txt` files — none collide with `trigraphs.py`'s shorthand table
  (§3.1 already checked). The encoder still always emits this project's own canonical
  `\nnn` form; these are accept-only, not alternate output spellings.

## 6. Licensing note

`hp41uc` is GPLv3 (per its `License.pdf`). DM41L_Explorer's own license should be
checked for compatibility before copying any of hp41uc's code verbatim — porting the
*design* (the byte-range scheme, the line grammar) as freshly-written Python is one
thing; copying substantial code passages directly is a separate question worth a
deliberate decision rather than an oversight. This concern is smaller than the first
version of this report suggested: per §3.1/§5, the XROM name table comes from
DM41L_Explorer's own already-existing `functions.py`, not copied from hp41uc's
`hp41ucg.h` — so the main remaining question is just the compile/decompile *logic*
itself (dispatch tables, tokenizer), where porting the design in fresh Python is the
plan already, not verbatim copying. Matching hp41uc's *comment wording conventions*
per §5's round-trip decision (short format strings like the `;NNNN BYTES` trailer, not
large data) is a similarly low-risk case of the same question, but still worth having
in mind rather than assuming away. (This report doesn't attempt the legal analysis
itself — just flagging that it's a real question, now a narrower one than first
thought.)

## 7. Suggested phasing

Consistent with this project's stated preference for one focused feature per PR
(`CONTRIBUTING.md`), a natural breakdown:

1. **Opcode table + decompile only** (bytes → text), read-only, no GUI yet — get
   `tower.raw` → text closely matching `tower.txt` (per §5's decision — comment
   *conventions* matched, human prose comments necessarily excluded, see §4.4), proven
   with a unit test. Lowest risk, immediately useful on its own (the Programs tab could
   show real instruction listings even before any write support exists — this alone
   closes half of the README's stated limitation). Includes the synthetic/unknown-opcode
   comment-line handling from §5, since that's a decompile-only concern.
2. **Compile** (text → bytes) — the tokenizer plus the reverse of every opcode-table
   entry, including the C-style escape acceptance from §5; round-trip-test against the
   same `tower.txt`/`tower.raw` pair, and against a few hand-authored short test
   programs covering each instruction category (single-byte, postfix, global label,
   ALPHA text with escapes, XROM, END).
3. **File format + GUI wiring** — `encode_program_txt`/`decode_program_txt` in
   `program_files.py`, `.txt` added to the Programs tab's Export/Import lists. This is
   the smallest step once 1 and 2 exist, since it's just plumbing into
   already-tested code paths.
4. **(Optional, later)** consider whether other container formats hp41uc supports
   (`.p41`, `.lif`) are worth adding too, once the core `.txt` path is solid — the only
   remaining open-ended item, now that XROM scope (§3.1), private-program handling, and
   packing (§5) are all settled rather than deferred.

---

*Research for this report drew on a full read-through of hp41uc's `compile.c`, `decomp.c`,
`hp41uc.h`, `hp41ucg.h`, and `convert.c`, cross-checked byte-for-byte against
`tower-update2.raw`/`.txt`/`.p41`; a full read-through of DM41L_Explorer's
`program_memory.py`, `program_files.py`, `program_info.py`, `program_chain.py`,
`opcode_scan.py`, `trigraphs.py`, `functions.py`, `program_tab.py`, and their associated
tests; a byte-level decode of a new real-hardware fixture, `samplelabels.dm41`, which
the user created specifically to settle the local-vs-global single-letter-label
question in §2.3; a byte-level decode of a second new fixture, `numtest.dm41`, which
the user created to confirm the numeric-literal separator byte (§2.3); and a
read-through of `src/memory/trigraphs.py` and the rest of `src/memory/functions.py`
(beyond the single table cited in the original pass) to resolve the escape-syntax
conflict and confirm the XROM/single-byte-function table's reusability (§3.1).*
