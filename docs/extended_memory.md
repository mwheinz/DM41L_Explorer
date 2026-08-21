# Extended Memory

Note: The structures will be described here in terms of registers and nibbles.
Registers are composed of seven bytes. Nibbles are single hexadecimal digits.
Two nibbles make one byte; seven bytes make one register.

Extended memory (XM) is considered "off-line storage" because, in normal
operation, data in extended memory has to be copied to "main memory" to be
used. The first memory region occupies registers 0x040 to 0x0bf but some
registers are used by the operating system and are not available for storage.
Similarly, the second memory region only has 238 registers that are available
for storage, it appears that registers 0x200 and 0x201 are reserved for the
operating system and registers 0x2f0-0x2ff are "non-existant".

This is described on page 29 of *HP-41 Advanced Programming Tips*:

> The memory of the Extended Functions Module (XFM) is built into the
HP-41CX, and is available in a separate module for the other HP-41 models. Look
between hex addresses 0BF and 040 (191 to 64 decimal) in Figure 1.2.
`(page 13 - MWH)` Not all of the 128 registers contained within this memory space are
available for data, programs or text (ASCII) files. A certain amount of
overhead is required to keep things in order, such as maintaining the illusion
that this memory is one continuous block that includes any existing Extended
Memory modules. After Extended Memory (XM) is cleared, executing EMDIR shows
124 registers available. The bottom register in the memory of the Extended
Functions module (hex address 040) contains a "header" which links XM to any
existing Extended Memory modules. Another register is filled with seven FF
(decimal 255) bytes to mark off the end of occupied XM. This leaves 126
registers available. However, two is subtracted from this count because any
file created requires one register for the file name and another to hold the
file type and the number of bytes and number of registers the file takes up. So
the count returned by EMDIR is exactly the number of registers available for
CRFLD or CRFLAS (CReate FiLe -- Data, or AScii) 
> ...
> Depending on the number of Extended Memory modules (0, 1, or 2), XM may
contain a total of 128, 367, or 606 total registers. Due to the fact that the
bottom register of each XM device is used to link it to the next, and one
register containing FF bytes is needed, this translates into 126, 364, or 602
registers available. When the directory is empty, the count returned by EMDIR
will always be two less than these numbers.

For the DM41L emulator, this means there are a total of 362 extended memory
registers available to the user. Addresses above 0x300 are not available in the
DM41L emulator.

## 1. Special XM Registers

* **0x040:** 000WW0PPNNNTTT or 00000000000000 (if no XM files have been created)
* **0x200:** Always zero? Purpose unknown.
* **0x201:** 000WW0PPNNNTTT or 00000000000000 (if no XM files have been created)

- TTT is the address of the top of the current XM region. For the DM41L
  emulator this will be either 0xbf or 0x2ef.
- NNN is the address of the top of the next block of XM memory. For the DM41L
  emulator this will be either 0x2ef or zero. **Confirmed:** NNN reflects
  whether the next region is actually *in use*, not merely whether it exists
  — a single non-spanning file leaves NNN at zero in register 0x040 even
  though region 1 exists in hardware (`tests/data/helloworld.dm41`), while a
  file that actually spans into region 1 sets NNN to 0x2ef there
  (`tests/data/3x-xm.dm41`, `6x-xm.dm41`).
- WW is the index of the currently open XM file. (It is unclear if this is true
  for register 0x201.) **Observed:** register 0x040 for a freshly-created,
  still-open single file (`helloworld.dm41`) has WW=01, PP=00; for two static,
  presumably-closed multi-file dumps (`3x-xm.dm41` with 3 files, `6x-xm.dm41`
  with 6 files) WW=PP=the file count (03/03 and 06/06 respectively) — consistent
  with "currently/previously open" but not a confirmed transition rule, since
  no capture of an *intermediate* append operation is available yet.
- PP maybe the index of the previously open XM file. (It is unclear if this is
  true for register 0x201.) In register 0x201 specifically, both available
  spanning captures (`3x-xm.dm41`, `6x-xm.dm41`, despite differing file counts)
  show the *identical* PP=0x40 — this looks more like a fixed back-link to
  register 0x040's own address than a file-count-style index, but that's not
  confirmed either.
- unused nibbles are not guaranteed to be zero, they may be used as temporary
  memory for internal operations.

## 2 XM File Structure — General Layout

* Like HP41/DM41L applications, information flows from high addresses to low
  addresses: within a region, files are packed from the top (highest address)
  downward, and within a file, records/data are packed
  nearest-the-header-first.
* File headers occupy 2 registers, packed at the top of the file's space:
  - The **upper** header register (higher address) contains the file name, up
    to 7 characters. If the file name is fewer than 7 characters, spaces
    (hexadecimal 0x20) are added on the right to fill the 7 bytes of the
    register.
  - The **lower** header register (name register's address minus 1) is the
    actual "header" register described below, and its leftmost nibble always
    identifies the file type: `1` = Program (saved program/app), `2` = Data,
    `3` = ASCII. This nibble has been reliable across every sample dump.
* Immediately below the header sit the file's data registers, going down to the
  next file's name register (or, for the bottommost file in a region, down to
  whatever the region's real floor turns out to be — see §4.5).

## 3 XM File Header Formats

All three header formats are 14 nibbles (7 bytes) and share a `SSS` field in
the same position — nibbles 11-13 (the low nibble of byte 5, plus all of byte
6) — giving the register count declared for the file. **`SSS` is a 3-nibble
(12-bit) field, up to 0xFFF = 4095**.

* **Program** (saved program/app): `10000000BBBSSS`
  - Nibble 0 = `1` (type). Nibbles 1-7 are a **fixed `0x10 00 00 00`
    signature** (bytes 0-3 of the register) — this is the one header field,
    across all three types, confirmed reliable enough to use as a structural
    fingerprint on its own (see §4.4).
  - `BBB` (nibbles 8-10): length of the program's instruction bytes, **not
    including the trailing checksum byte**.
  - `SSS` (nibbles 11-13): length of the file in registers.
  - The program's raw bytes occupy the `SSS` registers below the header, read
    nearest-header-first (i.e. descending address, same convention as
    Data/ASCII data registers). Concatenating those registers gives a byte
    stream of exactly `SSS * 7` bytes; the first `BBB` bytes are the
    instruction bytes, and the byte immediately after them is a **modulo-256
    checksum of those `BBB` bytes**.
  - The saved-program's *name* register (7 ASCII characters, space-padded like
    Data/ASCII names) sits immediately above the header, following the same
    "name register above header register" convention as Data/ASCII files.

* **Data**: `2AAA0000RRRSSS`
  - `AAA` (nibbles 1-3): the header's own address — confirmed reliable, see
    §4.4.
  - `RRR` (nibbles 8-10): documented as "address of the current record of the
    file". Registers in a data file are numbered from 0, with register zero
    being the register immediately below the name register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.

* **ASCII**: `3AAA00CCRRRSSS`
  - `AAA` (nibbles 1-3): the header's own address, same as Data — see §4.4.
  - `CC` (nibbles 6-7): documented as pointing to a character within the
    current register.
  - `RRR` (nibbles 8-10): documented as pointing to the current register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.
  - ASCII file *contents* are packed as a byte stream across the file's data
    registers (nearest-header-first, concatenated in normal left-to-right byte
    order): a series of `[1-byte length][text bytes]` records back-to-back with
    no padding between them. **Confirmed** (by comparing a real DM41L-created
    2-record file against a hand-packed one that used a `0x00` terminator and
    was rejected by the calculator): the record stream is terminated by a
    `0xFF` length byte, matching the same "`0xFF` marks free/end" convention as
    elsewhere in this format (see §4.5) — not by a `0x00` length byte.

## 4 File Boundaries, Free Space, and Open Questions

- Within a region, a file's data floor (its lowest-address register) is derived
  **structurally**, not from `SSS`: it's either the top of the next file below
  it (i.e. that file's name-register address + 1), or, for the bottommost file
  in a region, the region's natural floor (the register just above the region's
  reserved config/boundary record at its very start — e.g. 0x41 or 0x202).
- A register of all `0xFF` bytes marks "free space starts here" partway through
  that natural range (seen in `3x-xm.dm41`'s second Data file and
  `fillextended.dm41`'s second region). When one is found between the natural
  floor and the file above it, the file's real data starts just above the
  sentinel — the space below the sentinel down to the natural floor is simply
  unused, not part of any file.
- Because of this, a file's *actual* register count can legitimately be smaller
  than its header's declared `SSS` within a single region — but see below: the
  shortfall is usually made up by continuation in the next region, not simply
  lost.
- **Cross-region continuation (confirmed):** within a region, files are packed
  from the top down in creation order, so the *last*-created file in a region —
  the one with the lowest header address, i.e. closest to the region's natural
  floor — is the one competing for whatever space is left, and can run out of
  room before reaching its header's declared `SSS`. When that happens, the
  remaining registers continue at the very **top** of the next region (counting
  down from that region's ceiling address), landing directly above whatever
  file's header already occupies that region's top. Confirmed against
  `6x-xm.dm41`: `XM4.000` (region 0, header at 0x058) is 9 registers short of
  its declared 32 within region 0 (only 0x041-0x057 fit), and those missing 9
  registers sit at 0x2e7-0x2ef — the top of region 1, directly above
  `XMALPHA`'s header at 0x2e5 — continuing the exact same 64.095-95.095 numeric
  sequence with no gap or overlap. The same pattern explains `3x-xm.dm41`'s
  `XMBCD` (continues into 0x2cd-0x2ef) and `extendedmem.dm41`'s `XMALPHA`
  (continues into 0x2cb-0x2ef), and `fillextended.dm41`'s `FILLMEM`, whose
  declared `SSS = 362` is the *entire* XM capacity: it's built to span every
  region, and its two segments (0x041-0x0bd in region 0, 0x203-0x2ef in region
  1) add up to exactly 362 with no leftover needed in region 2.
- Because this reserved continuation space sits above every real header in the
  next region, tooling that looks for headers there must skip the reserved
  region first — otherwise continuation bytes (which can incidentally look
  header-shaped, e.g. mid-stream ASCII record bytes) risk being misread as a
  header.
- **Not yet confirmed**: whether a file can span *more than two* regions in one
  hop the same way it spans two. The reserved-space mechanism above should
  generalize to that case, but it's only been checked register-by-register for
  a two-region span so far.

## 6 Coincidental False-Positive Headers

Because Data/ASCII headers are found by combining header content with structure
(§4.4) rather than from context alone, it's worth knowing what a near-miss
looks like: a run of ordinary packed text can satisfy *some* of the checks by
coincidence, which is exactly why all of them are required together.

Confirmed case: `largedump.dm41`'s `TS` is a single 18-register ASCII file (a
game's room/item/monster vocabulary list — `EMPTY`, `STAIR DN`, `STAIR UP`,
`WARP`, `TREASURE`, `FOOD`, `SWORD`, `CLOAK`, `STAFF`, `EMPTY`, `SKELETON`,
`SPIDER`, `WRAITH`, `SPECTRE`, `GARGOYLE`, `DEMON`), floored by an `0xFF`
sentinel at 0x0ab per §4.5. Partway through that text (the space character in
`" UP.WARP"`, byte `0x20`) happens to have a Data type nibble, and the
following register happens to look name-shaped too (`"N.STAIR"`,
mostly-printable ASCII) — enough to satisfy two of the four checks in §4.4. But
its `AAA` is `0x055`, not its own address `0x0ba`, and its reserved nibble 4-7
is `5,0,0,4`, not `0000` — failing the other two, which is what correctly rules
it out. Without those two checks, this would have produced a phantom `N.STAIR`
"file" that split `TS` in two and truncated it to just 2 registers.
