Title: DM41 Memory Architecture Reference
Tags: Active, DM41 Explorer
----------------------------------------
# DM41 Explorer: Hardware Memory Architecture Reference

The purpose of the DM41 Explorer project is to design a python application that can read, write, and edit the memory of the DM41L emulator via the DM41L's serial port. This document outlines the memory architecture of the original physical calculator hardware and it's implementation in the DM41L. 

Note on limitations: The DM41L specifically emulates the HP41CX calculator, which was an upgraded version of the HP41C and HP41CV models. The HP41C* series could be expanded with various ROM and RAM cartridges. The HP41C model had the most limited amount of main memory and no extended memory, while the HP41CV had the maximum amount of main memory already built in, but no extended memory. The HP41CX had the maximum amount of main memory and the equivalent of a time functions ROM cartridge and two extended memory cartridges already installed.

A note on confidence: most of this document describes hardware behavior confirmed against real memory dumps (see `src/tests/data/*.dm41`), either because it matches published documentation or because it's been cross-checked against known content taken from a DM41L memory dump. (e.g. a file's declared length matching its actual size, or a checksum coming out valid). Where something is still a guess, it's flagged as such rather than stated as fact.

A note on the DM41X emulator: When this project was begun, it was believed that the DM41L and DM41X were similar. It was later discovered that this was not the case - the DM41X does not produce memory dumps and is not compatible with this project.

## 1. Core Architectural Specifications
- **Target Model:** DM41L which emulates the HP41CX (part of the HP41C series: basic C, expanded memory CV, and extended capabilities CX).
- **Memory Hardware:** The HP41 organized its memory into 7-byte (56-bit) registers. The DM41 emulator mimics this organization.
- **Instruction Set:** Operates on a variable-length instruction set where opcodes are between **1 and 3 bytes** long. This requires careful alignment for disassembly as code fragments may not align with register boundaries.
- **Execution Model:** When the HP41 series was developed, many modern computer architecture conventions had not yet stablized. In particular, the HP41 employs a **Reverse Execution Model** where the instruction pointer moves from higher memory addresses to lower memory addresses ($N \rightarrow 0$). This explains why program termination sequences (like "...END...") appear at relatively low register indices in dumps, while the entry point resides in high memory. This same high-to-low convention governs saved files in Extended Memory (see §4), but not user data stored in main memory.

## 2. Memory Architecture

Note that much of this data was derived from "HP-41 Advanced Programming Tips"
by Alan McCornack & Keith Jarett. It is available as a PDF on the internet.

The calculator's memory is divided into regions where the hardware registers are interpreted differently:

| Region | Description | Start | End |
| ----------- | ----------- | ----------- | ----------- | 
| Status Registers | Operational registers for the HP41/DM41, including the math stack, Alpha Register and system pointers | 0x00 | 0x0F |
| Void Region | Registers do not exist / not used. | 0x10 | 0x3F |
| Extended Memory #0 | File-oriented memory region | 0x40 | 0xBF |
| Main Memory | Main memory consists of 319 registers that are subdivided into variable length sub-regions. | 0xC0 | 0x1FF |
| Extended Memory #1 | File-oriented memory region. | 0x200 | 0x2FF |
| Extended Memory #2 | File-oriented memory region. Does not exist in the DM41L emulator. | 0x300 | 0x3FF |

| Status Registers | Description | Address |
|---|---|---|
| T | Top of the Math Stack | 0x00 |
| Z | Math Stack Register Z | 0x01 |
| Y | Math Stack Register Y | 0x02 |
| X | Math Stack Register X | 0x03 |
| L | Last X (additional Math Register) | 0x04 |
| Alpha Register | 4 registers comprising the HP41 Alphanumeric display | 0x05-0x08 |
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

R00 contains the address of the first data memory register (which the user sees
as Register 00). ".END." indicates the end of the currently loaded user
programs. The registers between ".END." and the last Alarm, Key Assignment or
address 0x0C0 is currently unused. Unlike application instructions and XM
files, main data memory registers begin at a low address and go UP towards the
end of main memory. In other words, what the user sees as "Memory 00" is at
address R00, "Memory 01" is at R00+1, "Memory 02" is at R00+2, et cetra. The
highest user memory location will be at address 0x1ff.

| Main Memory Sub-Region | Description | Start | End |
| ----------- | ----------- | ----------- | ----------- | 
| Key assignments | User defined key assignments (note that the first key assignments may be stored in portions of Status Registers e and F. | 0xC0 | variable |
| Alarms | User defined alarms. Detailed information is unknown. | After Key Assignments | variable |
| User Programs | Space reserved for user programs. Programs begin at high addresses and proceed to lower addresses as they execute. | After Alarms | R00 |
| Data Memory | Space reserved for user data. | R00 | 0x1FF |  


## 3. Memory Register Structure and Data Formats

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

Note: The structures will be described here in terms of registers and nibbles. Registers are composed of seven bytes. Nibbles are single hexadecimal digits. Two nibbles make one byte; seven bytes make one register.

### 4.1 Special XM Registers

* **0x040:** 000WW0PPNNNTTT or 00000000000000 (if no XM files have been created)
* **0x200:** Always zero? Purpose unknown.
* **0x201:** 000WW0PPNNNTTT or 00000000000000 (if no XM files have been created)

- TTT is the address of the top of the current XM region. For the DM41L emulator this will be either 0xbf or 0x2ef.
- NNN is the address of the top of the next block of XM memory. For the DM41L emulator this will be either 0x2ef or zero.
- WW is the index of the currently open XM file.
- PP maybe the index of the previously open XM file.
- unused nibbles are not guaranteed to be zero, they may be used as temporary memory for internal operations.

### 4.2 XM File Structure — General Layout

* Like HP41/DM41L applications, information flows from high addresses to low addresses: within a region, files are packed from the top (highest address) downward, and within a file, records/data are packed nearest-the-header-first.
* File headers occupy 2 registers, packed at the top of the file's space:
  - The **upper** header register (higher address) contains the file name, up to 7 characters. If the file name is fewer than 7 characters, spaces (hexadecimal 0x20) are added on the right to fill the 7 bytes of the register.
  - The **lower** header register (name register's address minus 1) is the actual "header" register described below, and its leftmost nibble always identifies the file type: `1` = Program (saved program/app), `2` = Data, `3` = ASCII. This nibble has been reliable across every sample dump.
* Immediately below the header sit the file's data registers, going down to the next file's name register (or, for the bottommost file in a region, down to whatever the region's real floor turns out to be — see §4.5).

### 4.3 XM File Header Formats

All three header formats are 14 nibbles (7 bytes) and share a `SSS` field in the same position — nibbles 11-13 (the low nibble of byte 5, plus all of byte 6) — giving the register count declared for the file. **`SSS` is a 3-nibble (12-bit) field, up to 0xFFF = 4095** — reading only the header's last byte (as an earlier version of this code did) truncates it to 0-255 and silently wraps for anything larger. This wasn't a hypothetical: `fillextended.dm41`'s `FILLMEM` file declares `SSS = 0x16a = 362` registers — the entire XM capacity of the DM41L, since that file is deliberately built to span every region (see §4.5) — and a single-byte read misreported it as 362 mod 256 = 106.

* **Program** (saved program/app): `10000000BBBSSS`
  - Nibble 0 = `1` (type). Nibbles 1-7 are a **fixed `0x10 00 00 00` signature** (bytes 0-3 of the register) — this is the one header field, across all three types, confirmed reliable enough to use as a structural fingerprint on its own (see §4.4).
  - `BBB` (nibbles 8-10): length of the program's instruction bytes, **not including the trailing checksum byte**.
  - `SSS` (nibbles 11-13): length of the file in registers.
  - The program's raw bytes occupy the `SSS` registers below the header, read nearest-header-first (i.e. descending address, same convention as Data/ASCII data registers). Concatenating those registers gives a byte stream of exactly `SSS * 7` bytes; the first `BBB` bytes are the instruction bytes, and the byte immediately after them is a **modulo-256 checksum of those `BBB` bytes**. (`SSS * 7` and `BBB + 1` line up exactly in every sample seen so far — i.e. no trailing padding — but that hasn't been tested against a program that doesn't fill its last register evenly.)
  - **Confirmed**: found and decoded in both `3x-xm.dm41` and `6x-xm.dm41`, each holding a 3-register, 20-instruction-byte program named `PURXM`. The checksum byte in both cases validates against the preceding 20 bytes, which is strong independent confirmation this format is right (a coincidental match is very unlikely).
  - The saved-program's *name* register (7 ASCII characters, space-padded like Data/ASCII names) sits immediately above the header, following the same "name register above header register" convention as Data/ASCII files.

* **Data**: `2AAA0000RRRSSS`
  - `AAA` (nibbles 1-3): documented as "address of the header register" but **not reliable** — see §4.4.
  - `RRR` (nibbles 8-10): documented as "address of the current record of the file". Registers in a data file are numbered from 0, with register zero being the register immediately below the name register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.

* **ASCII**: `3AAA00CCRRRSSS`
  - `AAA` (nibbles 1-3): same caveat as Data.
  - `CC` (nibbles 6-7): documented as pointing to a character within the current register.
  - `RRR` (nibbles 8-10): documented as pointing to the current register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.
  - ASCII file *contents* are packed as a byte stream across the file's data registers (nearest-header-first, concatenated in normal left-to-right byte order): a series of `[1-byte length][text bytes]` records back-to-back with no padding between them, running until a zero length byte or a length that would overrun the file's registers. Confirmed against the `"@"`, `"@A"`, `"@AB"`, ... sequence in `3x-xm.dm41`/`6x-xm.dm41`'s `XMALPHA` file and the repeating `"FILLMEM"` records in `fillextended.dm41`.

### 4.4 Header Field Reliability

The file-type nibble (and, for Program headers, the full `0x10 00 00 00` signature) is reliable. The rest of the Data/ASCII header — `AAA`, `RRR`, `CC` — is **not** reliable as a general rule:

- An earlier version of this code found file headers by checking whether `AAA` equalled the header's own address, which held across several sample dumps.
- But a dump generated by an independent test program (a self-copying program, not the two original file-creator apps) broke that check: those bytes were plain zero in its Data-file header.
- That same dump's Data-file header also had a last byte (0xC8 = 200) matching leftover CPU stack content rather than any sensible register count.
- Conclusion: `AAA`/`RRR`/`CC` are likely creator-supplied scratch space rather than an OS-enforced field — the earlier "AAA == own address" pattern was probably specific to how the two original test apps happened to write their headers, not a hardware guarantee. **Don't trust these fields**; only `SSS` (register count) has held up as reliable across every sample so far.

Because of this, file discovery works structurally rather than by trusting header content:

- **Data/ASCII headers** are found by looking for a register with a Data or ASCII type nibble immediately followed by a register that "looks like a name" — i.e. at least 5 of its 7 bytes are printable ASCII (0x20-0x7E). This is true of every real file name seen so far (always exactly 7 characters, sometimes space-padded) and false for BCD data, all-zero/all-0xFF filler, and packed ASCII-record content (which mixes in raw length-prefix bytes that usually aren't printable).
- **Program headers** are found by the fixed `0x10 00 00 00` signature (plus the same name-shaped check on the following register). This distinction matters: a register merely *starting* with a `1` nibble — which happens routinely in the middle of a packed ASCII record's byte stream — is not enough on its own to be mistaken for a Program header; the full 4-byte signature is required.
- This combined approach has matched every file in every sample dump (old and new) with no known false positives, including the empty-XM dumps.

### 4.5 File Boundaries, Free Space, and Open Questions

- Within a region, a file's data floor (its lowest-address register) is derived **structurally**, not from `SSS`: it's either the top of the next file below it (i.e. that file's name-register address + 1), or, for the bottommost file in a region, the region's natural floor (the register just above the region's reserved config/boundary record at its very start — e.g. 0x41 or 0x202).
- A register of all `0xFF` bytes marks "free space starts here" partway through that natural range (seen in `3x-xm.dm41`'s second Data file and `fillextended.dm41`'s second region). When one is found between the natural floor and the file above it, the file's real data starts just above the sentinel — the space below the sentinel down to the natural floor is simply unused, not part of any file.
- Because of this, a file's *actual* register count can legitimately be smaller than its header's declared `SSS` — this isn't a parsing bug, it's what happens when the calculator runs out of room and the header's declared length is never updated to match. Confirmed case: `6x-xm.dm41`'s `XM4.000` declares `SSS = 32` but only has 23 registers actually available below it (the other three Data files in the same region already consumed the rest of the 127 usable registers in Extended Memory #0).
- **Not yet understood**: how a file continues once it outgrows a single region and spills into the next one. `fillextended.dm41`'s `FILLMEM` file declares `SSS = 362` — the entire XM capacity across all regions — which is direct evidence this happens, but the mechanism (how the continuation is linked, whether there's a second header, how record numbering carries across the boundary) hasn't been decoded yet. Today's tooling only reports the portion of such a file found in the region where its header sits, and under-reports its true size accordingly.
