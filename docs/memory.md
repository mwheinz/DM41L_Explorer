Title: DM41 Memory Architecture Reference
Tags: Active, DM41 Explorer
----------------------------------------
# DM41 Explorer: Hardware Memory Architecture Reference

The purpose of the DM41 Explorer project is to design a python application that can read, write, and edit the memory of the DM41 emulator via the DM41 emulator's serial port. This document outlines the memory architecture of the original physical calculator hardware — specifically targeting the **DM41 emulator of the HP41CX calculator**.

## 1. Core Architectural Specifications
- **Target Model:** DM41L which emulates the HP41CX (part of the HP41C series: basic C, expanded memory CV, and extended capabilities CX).
- **Memory Hardare:** The HP41 organized its memory into 7-byte (56-bit) registers. The DM41 emulator mimics this organization.
- **Instruction Set:** Operates on a variable-length instruction set where opcodes are between **1 and 3 bytes** long. This requires careful alignment for disassembly as code fragments may not align with register boundaries.
- **Execution Model:** Employs a **Reverse Execution Model**. The instruction pointer moves from higher memory addresses to lower memory addresses ($N \rightarrow 0$). This explains why program termination sequences (like \"...END...\") appear at relatively low register indices in dumps, while the entry point resides in high memory.

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
| F | Different sources may call this register "F", "R", or "Append". unshifted key assign: F[3:6], scratch: R[0:2] | 0x0a |
| Execution Stack | 2 registers that provide a 6-level address stack. Each entry in the stack is 2 bytes long. | 0x0b-0x0c |
| a | return stack part 2 | 0x0b |
| b | return stack part 1 | 0x0c | 
| c | Contains ∑REG, R00, and ".END." | 0x0d |
| d | User and System flags. | 0x0e | 
| e | shifted key assign: e[3:6], scratch: e[2], LineNo e[0:1] | 0x0f |

R00 contains the address of the first data memory register (which the user sees
as Register 00). ".END." indicates the end of the currently loaded user
programs. The registers between ".END." and the last Alarm, Key Assignment or
address 0x0C0 is currently unused.

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

### Extended Memory

Extended memory (XM) is considered "off-line storage" because, in normal
operation, data in extended memory has to be copied to "main memory" to be
used. The first memory region occupies registers 0x040 to 0x0bf but register
0x040 is used by the operating system and is not available for storage. (It does
contain pointer to the top of the next XM region.) Similarly, the
second memory region only has 238 registers that are available for storage, it
appears that registers 0x200 and 0x201 are reserved for the operating system
and registers 0x2f0-0x2ff are "non-existant".

For the DM41L emulator, this means there are a total of 362 extended memory
registers available to the user. Addresses above 0x300 are not available in the
DM41L emulator.

Note: The structures will be described here in terms of registers and nibbles. Registers are composed of seven bytes. Nibbles are single hexadecimal digits. Two nibbles make one byte; seven bytes make one register.

#### Special XM Registers

* **0x040:** 000WW0PPNNNTTT or 00000000000000 (if no XM files have been created)
* **0x200:** Always zero? Purpose unknown.
* **0x201:** 000WW0PPNNNTTT or 00000000000000 (if no XM files have been created)

- TTT is the address of the top of the current XM region. For the DM41L emulator this will be either 0xbf or 0x2ef.
- NNN is the address of the top of the next block of XM memory. For the DM41L emulator this will be either 0x2ef or zero.
- WW is the index of the currently open XM file.
- PP maybe the index of the previously open XM file.
- unused nibbles are not guaranteed to be zero, they may be used as temporary memory for internal operations.

#### XM File Structure

* Like HP41/DM41L applications, information flows from high addresses to low addresses. 
* File headers will occupy 2 registers.
* The first of these registers contains the file name, up to 7 characters. If the file name is fewer than 7 characters, spaces (hexadecimal 20) are added on the right to fill the 7 bytes of the register.
* The second file header register contains several pieces of information about the file. The structure will be de-
scribed here in terms of nibbles, which are hexadecimal digits. Two nibbles make one byte; seven bytes make one register. The leftmost nibble of the second file header register
* The second register will vary depending on the file type but the first nibble of the register will indicate the file type, where 1 = program, 2 = data, 3 = ASCII.
* For program files, the 14 nibbles of the header are: 10000000BBBSSS where 1 is the file type, BBB is the length of the program in bytes and SSS is the length of the program in registers. The last byte of the program is a modulo 256 checksum of the program.
* For data files, the 14 nibbles of the header are: 2AAA0000RRRSSS where 2 is the file type, AAA is the address of the header register, RRR is the address of the current record of the file and SSS is the length of the file in registers. Registers in a data file are numbered from 0, with register zero being the register below the second header register.
* For ascii files, the 14 nibbles of the header are: 3AAA00CCRRRSSS where 3 is the file type, AAA is the address of the header register, RRR points to the current register, CC points to a character in the current register, and SSS is the length of the file in registers.
