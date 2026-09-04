# Extended Memory

Note: The structures will be described here in terms of registers and nibbles.
Registers are composed of seven bytes. Nibbles are single hexadecimal digits.
Two nibbles make one byte; seven bytes make one register.

The original HP-41C only had support for a small amount of memory. To allow the
calculator access to more memory, the "Extended Functions" module and "Extended
Memory" were developed. Extended memory (XM) is considered "off-line storage"
because for a real HP41 to read and write data in the extended memory region it
has to be copied into and out of primary memory first. 

The DM41L emulates the Extended Functions module and a single Extended Memory
module as two separate memory regions. The first extended memory region
occupies registers 0x040 to 0x0bf and the second extended memory region extends
from 0x200 to 0x2ef. The first memory region reserves register 0x40 for system
use, while the second reserves 0x200 and 0x201. In addition, a register is
reserved for marking the end of used memory, leaving 362 registers worth of
extended memory available to the user. Registers 0x2f0-0x2ff are
"non-existant".

This is described on page 29 of *HP-41 Advanced Programming Tips*:

> The memory of the Extended Functions Module (XFM) is built into the
HP-41CX, and is available in a separate module for the other HP-41 models. Look
between hex addresses 0BF and 040 (191 to 64 decimal) in Figure 1.2.
(page 13) Not all of the 128 registers contained within this memory space are
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
* **0x201:** 000WW0PP000TTT or 00000000000000 (if no XM files have been created)

- TTT is the address of the top of the current XM region. For the DM41L
  emulator this will be either 0xbf or 0x2ef.
- NNN is the address of the top of the next block of XM memory. For the DM41L
  emulator this will be either 0x2ef or zero. Note that NNN reflects whether
  the next region is actually *in use*, not merely whether it exists — if the
  current catalog of XM files does not extend in the the higher memory region,
  NNN will be zero.
- WW is the index of the currently open XM file. (It is unclear if this is true
  for register 0x201.)
- PP may be the index of the previously open XM file. or it might be a back
  link to the previous XM region. It is possible that the value of PP in
  register 0x40 and the value of PP in register 0x201 have different meanings.
- Unused nibbles are not guaranteed to be zero, they might be used as temporary
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
    `3` = ASCII.
* Immediately below the header sit the file's data registers, going down to the
  next file's name register (or, for the bottommost file in a region, down to
  whatever the region's real floor turns out to be — see §4.5).

## 3 XM File Formats

All three file formats begin with a register that indicates the type of file,
its size, and for DATA and ASCII file types, a record or character pointer into
the file.

* **Program file header** (saved program/app): `10000000BBBSSS`
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

* **Data file header**: `2AAA0000RRRSSS`
  - `AAA` (nibbles 1-3): the header's own address -- in every real dump
    *until* a file has been deleted; see the "Resolved" note below on why
    Explorer no longer checks it.
  - `RRR` (nibbles 8-10): documented as "address of the current record of the
    file". Registers in a data file are numbered from 0, with register zero
    being the register immediately below the name register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.
  - Data files do not appear to have a terminator of any kind.

* **ASCII** file header: `3AAA00CCRRRSSS`
  - `AAA` (nibbles 1-3): the header's own address, same as Data — see §4.4,
    and the same "until a delete happens" caveat.
  - `CC` (nibbles 6-7): documented as pointing to a character within the
    current register.
  - `RRR` (nibbles 8-10): documented as pointing to the current register.
  - `SSS` (nibbles 11-13): length of the file in registers, per §4.3 above.
  - ASCII file contents are packed as a byte stream across the file's data
    registers (nearest-header-first, concatenated in normal left-to-right byte
    order): a series of records back-to-back with no padding between them.
  - ASCII files are terminated with an 0xff byte after the final character.

## 4 Notes

- A register of all `0xFF` bytes marks the end of the last extended memory
  file.
- Files are stored in creation order.
- Files can span between the extended memory regions. When this happens, there
  is no header or other indication; if the next record would be at location
  0x40, it will be at location 0x2ef instead.
- Deleting a file on the actual DM41L (PURFL) will cause XM to be repacked, but
  the `AAA` field is not updated to point to the new location. That is, `AAA`
  points to the original creation point of the file, not necessarily the
  current location of the header.
