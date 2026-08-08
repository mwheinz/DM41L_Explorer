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

## 2. Memory Regions
The calculator's memory is divided into regions where the hardware registers are interpreted differently:
| Region | Description | Start | End |
| ----------- | ----------- | ----------- | ----------- | 
| Status Registers | Operational registers for the HP41/DM41, including the math stack, Alpha Register and system pointers | 0x00 | 0x0F |
| Void Region | Registers do not exist / not used. | 0x10 | 0x3F |
| Extended Memory #0 | File-oriented memory region | 0x40 | 0xBF |
| Main Memory | Main memory consists of 319 registers that are subdivided into variable length sub-regions. | 0xC0 | 0x1FF |
| Extended Memory #1 | File-oriented memoroy region. | 0x200 | 0x2FF |
| Extended Memory #2 | File-oriented memoroy region. | 0x300 | 0x3FF |

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
| R | unshifted key assign: R[3:6], scratch: R[0:2] | 0x0a |
| Execution Stack | 2 registers that provide a 6-level address stack. Each entry in the stack is 2 bytes long. | 0x0b-0x0c |
| a | return stack part 2 | 0x0b |
| b | return stack part 1 | 0x0c | 
| c | Contains ∑REG, R00, and ".END." | 0x0d |
| d | User and System flags. | 0x0e | 
| e | shifted key assign: e[3:6], scratch: e[2], LineNo e[0:1] | 0x0f |

R00 contains the address of the first data memory register (which the user sees as Register 00). ".END." indicates the end of the currently loaded user programs. The registers between ".END." and the last Alarm, Key Assignment or address 0x0C0 is currently unused.

| Main Memory Sub-Region | Description | Start | End |
| ----------- | ----------- | ----------- | ----------- | 
| Key assignments | User defined key assignments (note that the first key assignments may be stored in portions of Status Registers e and F. | 0xC0 | variable |
| Alarms | User defined alarms. Detailed information is unknown. | After Key Assignments | variable |
| User Programs | Space reserved for user programs. Programs begin at high addresses and proceed to lower addresses as they execute. | After Alarms | R00 |
| Data Memory | Space reserved for user data. | R00 | 0x1FF |  


## 3. Memory Register Structure and Data Formats
### Word Size:
- Every hardware register is exactly **7 bytes** (56 bits) long. Registers can contain numeric data, text data, or program instructions.

### Numeric data
1. Values are stored in **Binary Coded Decimal (BCD)**. The MSB is in byte 0 of the register, the LSB is in byte 6.
2. **Mantissa Sign (MS):** 1 nybble (4 bits). Stored in bits 47 of the MSB. 0000 for positive, 1001 for negative.
3. **Mantissa:** The next 10 nybbles of the register represent 10 decimal digits. This represents normalized values with fixed 10-digit precision.
4. **Exponent Sign (XS):** 1 nybble (4 bits). 0000 for positive, 1001 for negative.
5. **Exponent:** 2 decimal digits packed into 2 nybbles. Provides a range of $10^{-99}$ to $10^{99}$.
   - **Negative Exponent Convention:** When the XS nibble indicates a negative exponent, the stored BCD value follows a complementary rule where the value represents $100 - |E|$, where $E$ is the true exponent. For example, an exponent of $-5$ is stored as $95$.

### Alpha Storage:
- A register in main memory holding ASCII data will begin with 0x10 in the MSB and can hold up to 6 ASCII characters. If the ASCII data is less than 6 characters long, it will be prepended with one or more NUL bytes until the data is 6 characters long.

#### Program instructions
- instructions are read from registers as bytes and are read from higher addresses to lower ones.

## 4. Addressing and Indexing Logic
- **Register Indexing:** Memory dump labels (e.g., 00, 04, 08) indicate **register indices**, not byte offsets.
- **Address Calculation:** The absolute memory location is determined by: $$\text{Byte Address} = \text{Register Index} \times 7$$
- **Row Increments:** Each row in a dump typically displays 4 registers, representing a 28-byte jump between labeled rows. When gaps exist, they indicate empty (zeroed) memory regions.
