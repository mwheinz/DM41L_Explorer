Title: DM41L Memory Architecture Reference
Tags: Active, DM41L Explorer
----------------------------------------
# DM41L Explorer: Hardware Memory Architecture Reference

The purpose of the DM41L Explorer project is to design a python application that
can read, write, and edit the memory of the DM41L emulator via the DM41L's
serial port. This document outlines the memory architecture of the original
HP41C calculator hardware and it's implementation in the DM41L. 

Note on limitations: The DM41L specifically emulates the HP41CX
calculator, which was an upgraded version of the HP41C and
HP41CV models. The HP41C* series could be expanded with various
ROM and RAM cartridges. The HP41C model had the most limited
amount of main memory and no extended memory, while the HP41CV
had the maximum amount of main memory already built in, but no
extended memory. The HP41CX had the maximum amount of main
memory and the equivalent of a time functions ROM cartridge and
two extended memory cartridges already installed.

A note on confidence: most of this document describes hardware
behavior confirmed against real memory dumps (see
`src/tests/data/*.dm41`), or is derived from published
documentation. Where something is still a guess, it's flagged
as such rather than stated as fact.

A note on sources: Much of this data was derived from "HP-41 Advanced
Programming Tips" by Alan McCornack & Keith Jarett, "HP41 Extended Functions
Made Easy", "HP41 Synthetic Programming" and other documentation found on the
internet in PDF format. 

## 1. Core Architectural Specifications
- **Target Model:** DM41L which emulates the HP41CX (part of the HP41C series:
  basic C, expanded memory CV, and extended capabilities CX).
- **Memory Hardware:** The HP41 organized its memory into 7-byte (56-bit)
  registers. The DM41L emulator mimics this organization.
- **Instruction Set:** Operates on a variable-length instruction set where
  opcodes are between **1 and 3 bytes** long. This requires careful alignment
  for disassembly as code fragments may not align with register boundaries.
- **Execution Model:** When the HP41 series was developed, many modern computer
  architecture conventions had not yet stablized. In particular, the HP41
  employs a **Reverse Execution Model** where the instruction pointer moves
  from higher memory addresses to lower memory addresses ($N \rightarrow 0$).
  This explains why program termination sequences (like ".END.") appear at
  relatively low register indices in dumps, while the entry point resides in
  high memory. This same high-to-low convention governs saved files in Extended
  Memory (see §4), but not user data stored in main memory.

## 2. Memory Register Structure and Data Formats

### Word Size:
- Every hardware register is exactly **7 bytes** (56 bits) long. Registers can
  contain numeric data, text data, or program instructions.

### Numeric data
1. Values are stored in **Binary Coded Decimal (BCD)**. The MSB is in byte 0 of
   the register, the LSB is in byte 6.
2. **Mantissa Sign (MS):** 1 nybble (4 bits). Stored in bits 4-7 of the MSB.
   0000 for positive, 1001 for negative.
3. **Mantissa:** The next 10 nybbles of the register represent 10 decimal
   digits. This represents normalized values with fixed 10-digit precision.
4. **Exponent Sign (XS):** 1 nybble (4 bits). 0000 for positive, 1001 for
   negative.
5. **Exponent:** 2 decimal digits packed into 2 nybbles. Provides a range of
$10^{-99}$ to $10^{99}$.
   - **Negative Exponent Convention:** When the XS nibble indicates a negative
     exponent, the stored BCD value follows a complementary rule where the
     value represents $100 - |E|$, where $E$ is the true exponent. For example,
     an exponent of $-5$ is stored as $95$.

### Alpha Storage:
- A register in main memory holding ASCII data will begin with 0x10 in the MSB
  and can hold up to 6 ASCII characters. If the ASCII data is less than 6
  characters long, it will be prepended with one or more NUL bytes until the
  data is 6 characters long.

### Program instructions
- instructions are read from registers as bytes and are read from higher
  addresses to lower ones.

## 3. Memory Architecture

The calculator's memory is divided into regions where the hardware registers
are interpreted differently:

| Region | Description | Start | End |
| ----------- | ----------- | ----------- | ----------- | 
| Status Registers | Operational registers for the HP41/DM41L, including the math stack, Alpha Register and system pointers | 0x00 | 0x0F |
| Void Region | Registers do not exist / not used. | 0x10 | 0x3F |
| Extended Memory #0 | File-oriented memory region | 0x40 | 0xBF |
| Main Memory | Main memory consists of 319 registers that are subdivided into variable length sub-regions. | 0xC0 | 0x1FF |
| Extended Memory #1 | File-oriented memory region. | 0x200 | 0x2FF |

An additional memory region may exist in actual HP41CV and HP41CX calculators
if an an addition Extended Memory module is installed, but this is not
reflected in the DM41L emulator.

### Status Registers

| Status Registers | Description | Address |
|---|---|---|
| T | Top of the Math Stack | 0x00 |
| Z | Math Stack Register Z | 0x01 |
| Y | Math Stack Register Y | 0x02 |
| X | Math Stack Register X | 0x03 |
| L | Last X (additional Math Register) | 0x04 |
| Alpha Register | 3.5 registers comprising the HP41 Alphanumeric display | 0x05-0x08 |
| M | Alpha characters 1-7 | 0x05 |
| N | Alpha characters 8-14 | 0x06 | 
| O | Alpha characters 15-21 | 0x07 | 
| P | Alpha characters 22-25: P[0:3], scratch: P[4-6] | 0x08 |
| Q | scratch | 0x09 |
| F | Different sources may call this register "F", "R", or "Append". unshifted key assign: F[3:6], scratch: F[0:2] | 0x0a |
| Execution Stack | 2 registers that provide a 6-level address stack. Each entry in the stack is 2 bytes long. | 0x0b-0x0c |
| a | return stack part 2 | 0x0b |
| b | return stack part 1 | 0x0c | 
| c | Contains ∑REG, R00, and ".END." | 0x0d |
| d | User and System flags. | 0x0e | 
| e | shifted key assign: e[3:6], scratch: e[2], LineNo e[0:1] | 0x0f |

#### HP41 Alpha display:

The main display of the HP41 series and the DM41L emulator is actually composed
of Status Registers M, N, O, and part of register P. The user sees this as a
continuous buffer of 24 ASCII characters but the physical memory is still
comprised of 7-byte registers.

### Main Memory

| Main Memory Sub-Region | Description | Start | End |
| ----------- | ----------- | ----------- | ----------- | 
| Key assignments | User defined key assignments (note that the first key assignments may be stored in portions of Status Registers e and F. | 0xC0 | variable |
| Alarms | User defined alarms. Detailed information is unknown. | After Key Assignments | variable |
| User Programs | Space reserved for user programs. Programs begin at high addresses and proceed to lower addresses as they execute. | .END. | R00 |
| Data Memory | Space reserved for user data. | R00 | 0x1FF |  

- R00 contains the address of the first data memory register
  (which the user sees as Register 00). Unlike application
  instructions and XM files, main data memory registers begin
  at a low address and go UP towards the end of main memory. In
  other words, what the user sees as "Memory 00" is at address
  R00, "Memory 01" is at R00+1, "Memory 02" is at R00+2, et
  cetra. The highest main memory location the user can access
  will always be at address 0x1ff.

- ".END." indicates the end of the currently loaded user
  programs. The registers between ".END." and the last Alarm,
  Key Assignment, or address 0x0C0 are available for use by
  additional programs, alarms, or key assignments.

### Program Memory

HP41 programs begin at the register pointed to by R00-1 and proceed down
through memory. The lowest register used by programs will be pointed to by
.END. and will contain a 3-byte instruction that is also called ".END.".

This is explained further in `docs/program.md`, a separate document
(currently its own actively-researched doc rather than a section of this
one — its internal numbering starts at "5." only because it's written as a
continuation of this document's numbering, not because it's physically
part of this file).

### Extended Memory

In an actual HP41 series calculator, extended memory may or may not be present.
The DM41L emulates the presence of an "Extended Functions" module which
occupies registers 0x040-0x0bf and a single "Extended Memory" module which
occupies registers 0x200-0x2ef. This is explained further in the section on
Extended Memory.

## 4. Extended Memory

Extended memory (XM) is considered "off-line storage" because, in normal
operation, data in extended memory has to be copied to "main memory" to be
used. The first memory region occupies registers 0x040 to 0x0bf but register
0x040 is used by the operating system and is not available for storage. (It does
contain a pointer to the top of the next XM region.) Similarly, the
second memory region only has 238 registers that are available for storage, it
appears that registers 0x200 and 0x201 are reserved for the operating system
and registers 0x2f0-0x2ff are "non-existant".

For the DM41L emulator, this means there are a total of 362 extended memory
registers available to the user. Addresses above 0x300 are not available in the
DM41L emulator.

Note: The structures will be described here in terms of registers and nibbles.
Registers are composed of seven bytes. Nibbles are single hexadecimal digits.
Two nibbles make one byte; seven bytes make one register.

### 4.1 Special XM Registers

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

### 4.2 XM File Structure — General Layout

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

### 4.3 XM File Header Formats

All three header formats are 14 nibbles (7 bytes) and share a `SSS` field in
the same position — nibbles 11-13 (the low nibble of byte 5, plus all of byte
6) — giving the register count declared for the file. **`SSS` is a 3-nibble
(12-bit) field, up to 0xFFF = 4095**.

* **Program** (saved program/app): `10000000BBBSSS`
  - Nibble 0 = `1` (type). Nibbles 1-7 are a **fixed `0x10 00 00 00` signature** (bytes 0-3 of the register) — this is the one header field, across all three types, confirmed reliable enough to use as a structural fingerprint on its own (see §4.4).
  - `BBB` (nibbles 8-10): length of the program's instruction bytes, **not including the trailing checksum byte**.
  - `SSS` (nibbles 11-13): length of the file in registers.
  - The program's raw bytes occupy the `SSS` registers below the header, read nearest-header-first (i.e. descending address, same convention as Data/ASCII data registers). Concatenating those registers gives a byte stream of exactly `SSS * 7` bytes; the first `BBB` bytes are the instruction bytes, and the byte immediately after them is a **modulo-256 checksum of those `BBB` bytes**.
  - The saved-program's *name* register (7 ASCII characters, space-padded like Data/ASCII names) sits immediately above the header, following the same "name register above header register" convention as Data/ASCII files.

* **Data**: `2AAA0000RRRSSS`
  - `AAA` (nibbles 1-3): the header's own address — confirmed reliable, see §4.4.
  - `RRR` (nibbles 8-10): documented as "address of the current record of the file". Registers in a data file are numbered from 0, with register zero being the register immediately below the name register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.

* **ASCII**: `3AAA00CCRRRSSS`
  - `AAA` (nibbles 1-3): the header's own address, same as Data — see §4.4.
  - `CC` (nibbles 6-7): documented as pointing to a character within the current register.
  - `RRR` (nibbles 8-10): documented as pointing to the current register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.
  - ASCII file *contents* are packed as a byte stream across the file's data registers (nearest-header-first, concatenated in normal left-to-right byte order): a series of `[1-byte length][text bytes]` records back-to-back with no padding between them. **Confirmed** (by comparing a real DM41L-created 2-record file against a hand-packed one that used a `0x00` terminator and was rejected by the calculator): the record stream is terminated by a `0xFF` length byte, matching the same "`0xFF` marks free/end" convention as elsewhere in this format (see §4.5) — not by a `0x00` length byte.

### 4.5 File Boundaries, Free Space, and Open Questions

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

### 4.6 Coincidental False-Positive Headers

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
