## 5. Program Memory

### 5.1 Traversing Program Memory

The list of programs in an HP41/DM41L is traversed backwards, by starting at
the register pointed to by .END. and progressing to higher addresses.

From HP-41 Synthetic Programming by Jonathan Wickes:

>We have come to the 'END'. The bytes CO-CD, 'GLOBAL', play a dual role--they
identify both 'END' lines and global alpha labels. If the third byte of a line
starting with 'Cn' (0<=n<E) is a text byte 'Fn', then the line is a global alpha
label. Otherwise, it is a three- byte 'END'. For both types of lines, the
second, third and fourth nybbles give the distance from the current line to the
next 'END' or alpha label preceding in memory. The distance is coded as in the
three-byte GTO's (Section 2C). Thus, all the global Tines are linked together;
a GTO-alpha or XEQ-alpha starts searching the global chain from the end of
program memory, the permanent .END., backwards to the first global line in
memory, which is identified by its first two bytes 'CO 00'. 'CAT 1' shows the
labels and END's in order forward from the first global line. In 'END' lines,
the third byte is used to provide information about the current program
--whether it has been packed and whether it is the last program in memory,
i.e., if the END is the permanent .END. In the third byte, a first nybble 'O'
indicates a normal END; a '2' identifies the permanent .END. For the second
nybble, '9' means that the program file is packeds 'D' indicates that the file
needs packing. ...

Reviewing the relevant section, we can see that END instructions will take the form:

`1100 bbbr rrrr rrrr eeee ffff`

Where '1100' is the bytecode for indicating and END or LBL instruction, 'r rrrr rrrr' is the distance in registers, 
and 'bbb' is the byte in the destination register.

**Update:** the third byte ('eeee ffff' above) is explained a little further
on in the same section of Wickes (2C, p.15), in the paragraph right after the
one quoted above. For a plain END line, the high nibble ('eeee') is `0` for a
normal END or `2` for the permanent `.END.`; the low nibble ('ffff') is `9`
if the program file has been packed, or `D` if it needs packing. For a global
label line, the high nibble is always `F` — that's exactly the marker Wickes
uses to distinguish a label from a plain END — and the low nibble gives the
label's name length, plus one. See §5.2 below for the full label format.

#### Addressing within program memory

Register offset and absolute address run in *opposite* directions within a
register. If `reg` is a register's decimal value and `offset` is the byte
position counting left-to-right through its printed hex (0 = the first/
leftmost byte, 6 = the last/rightmost byte), then:

```
address(reg, offset) = 7*reg + (6 - offset)
```

Offset 0 (the first printed byte) is at the *highest* address within that
register; offset 6 (the last printed byte) is at the *lowest*. This matches
Wickes' own description in 2C: HP41 "byte 6" (offset 0 here) is a register's
first byte and "byte 0" (offset 6 here) its last, and stepping forward
through a program decrements the byte number before decrementing the
register number. Every "distance in registers and bytes" calculation below
works out to: take the address of the byte the distance is measured from,
add `r*7 + bbb`, and convert the result back to (register, offset) with the
same formula. Worked out this way, every hop in the examples below lands
exactly on the next instruction, byte for byte — verified directly against
`simple.dm41` and `6x-xm.dm41`.

Simple example: This is a dump of a DM41L that has just been initalized; there
are no programs in memory. R00 is 19c and .END. is 19b:

```
DM41
08  4b000000000000  00000000000000  00000000000000  00000000000000  
0c  1000000000019c  1a70016919c19b  0000002c048000  00000000000000  
198  00000000000000  00000000000000  00000000000000  00000000c00020  
...
```

The END instruction appears in the last 3 bytes of register 19b: 'c0 00 20'
which appears to encode a distance of 0 registers and 0 bytes to the next END.

The next example contains a single small program in an otherwise empty DM41L
emulator. The program is called "APPTEST" (this file used to be labeled
"TESTAPP" in this doc — see the correction below). On the calculator, the CAT 1
command reports that this program occupies 26 bytes and the nameless app
occupies 10 bytes. The registers in the dumpfile looks like this:

```
DM41
00  01000000000000  01000000000002  01000000000002  01000000000002
04  01000000000000  00000000000000  00000000000000  00000000000000
08  4b020000000000  7100fffffff0ff  00000000001000  00000000000000
0c  00000000002198  1a70016919c197  0000002c048000  00000000007000
194  00000000000000  00000000000000  00000000000000  00000000c40120
198  b200c403090000  40111010468475  54455354100211  c000f800415050
...
```

In this dump, R00 is register 19c and .END. is register 197.

Register 197 contains "00 00 00 00 c4 01 20" which decodes to:

| Instruction | bbb | rrrrrrrrr | eeee ffff | 
|-|-|-|-|-|
| 1100 | 010 | 0 0000 0001 | 0010 0000 |
| END | 2 bytes | 1 register | .END. |

Total distance = 1 register + 2 bytes, so 9 bytes counting from the first byte
of the end instruction. That takes us to another END instruction: "c40309".
Decoding that:

| Instruction | bbb | rrrrrrrrr | eeee ffff | 
|-|-|-|-|-|
| 1100 | 010 | 0 0000 0011 | 0000 1001 |
| END | 2 bytes | 3 register | Packed End | ? |

Total distance = 3 registers + 2 bytes, 23 bytes, counting from the first byte
of the END instruction takes us to the MSB of register 19b: "c0 00 f8 00 41 50
50", the label of the program. See §5.2 below for how to decode this into the
name "APPTEST" — the name is *not* "TESTAPP" as this doc originally (and
wrongly) said; that was a transcription error, not a decoding difference. The
23-byte arithmetic above is correct as written and lands exactly on this
register (see "Addressing within program memory" above for why).

The next example is a part of a dump that contains three apps, called "XMBCD",
"XMALPHA", and "PURXM" (this doc used to misname the third one "PURFL" — the
raw bytes spell "PURXM", confirmed against the real calculator's CAT 1
listing):

```
DM41
...
0c  00000000001189  1a70016919c188  0000023c048008  00000000007000
...
188  00000000c20120  5fb100c6020900  584d0111a674a6  c600f621505552
18c  4f4e457ecc0609  449600b2b1f444  30870220a66fa6  4a16141a101916
190  504841111218a6  4841f7584d414c  f811584d414c50  457ec40809c600
194  01b100f4444f4e  a6689600b20096  10113002101a10  4b16141a101915
198  21689b731312a6  10113101f2584d  4344111a101014  c000f601584d42
...
```

R00 is 19c (which seems to be the default for the DM41L) and .END. is set to
register 188. Looking at register 188 we find "00 00 00 00 c2 01 20". (In all
samples, .END. is always found in the last 3 bytes of a register, even if that
means padding it with null bytes.)

| Instruction | bbb | rrrrrrrrr | eeee ffff | 
|-|-|-|-|-|
| 1100 | 001 | 0 0000 0001 | 0010 0000 |
| END | 1 bytes | 1 register | .END. |

This takes us to register 189 and the next END is "c6 02 09"

| Instruction | bbb | rrrrrrrrr | eeee ffff | 
|-|-|-|-|-|
| 1100 | 011 | 0 0000 0010 | 0000 1001 |
| END | 3 bytes | 2 register | Packed End |

2 * 7 + 3 = 17 bytes. 17 bytes from the c6 instruction takes us register 18b and "c600f621505552"
which is the label of the program "PURXM". c600 translates to 3 bytes, which takes us to "cc0609" in register 18c:

| Instruction | bbb | rrrrrrrrr | eeee ffff | 
|-|-|-|-|-|
| 1100 | 110 | 0 0000 0110 | 0000 1001 |
| END | 6 bytes | 6 registers | Packed End |

This continues the chain further back (toward XMALPHA/XMBCD) rather than
terminating — not fully walked out in this doc yet.

### 5.2 Decoding a Global Label's Name

Once the chain above lands on an entry whose third byte is `Fn` (high nibble
`F`) rather than a plain END, that entry is a global label, not just a
chain link. Wickes (2C, p.15) gives the exact byte layout:

`LBL "ABC" = C1 mn F4 ab 41 42 43`

- Byte 0: `Cn` — the same marker byte as an END; `n` is part of the shared
  chain-distance field described above.
- Byte 1: `mn` — the rest of that chain-distance field.
- Byte 2: `Fn` — high nibble `F` marks this as a label (not an END); low
  nibble `n` is the name's length **plus one**.
- Byte 3: the assigned-key code (`00` = no key assigned; `ab` in the example
  above is a placeholder for a real key code).
- The remaining `n - 1` bytes spell out the name, in plain forward reading
  order, starting right after the key-code byte.

For a 3-character name like "ABC" this is exactly 7 bytes — one whole
register, header and name together, as in Wickes' example. For a longer
name, the header's own register only has 3 bytes left after the 4-byte
header (offsets 4, 5, 6), so the name overflows into the **preceding**
(lower-address) register, starting at *its* offset 0, for up to 4 more
characters — continuing a register further back if the name is longer
still.

Worked examples, both confirmed against the real calculator's CAT 1 listing:

- **XMBCD** (`6x-xm.dm41`): header at register 19b, offset 0: `c0 00 f6 01`.
  `f6` → length 5. Name chars: offset 4-6 of 19b = "XMB", + offset 0-1 of
  19a = "CD" → **XMBCD**.
- **PURXM** (`6x-xm.dm41`): header at register 18b, offset 0: `c6 00 f6 21`.
  `f6` → length 5. Name chars: offset 4-6 of 18b = "PUR", + offset 0-1 of
  18a = "XM" → **PURXM**.
- **APPTEST** (`simple.dm41`, the "single small program" example above):
  header at register 19b, offset 0: `c0 00 f8 00`. `f8` → length 7. Name
  chars: offset 4-6 of 19b = "APP", + offset 0-3 of 19a = "TEST" →
  **APPTEST**. This is the correction referenced above — the same method
  that correctly reproduces XMBCD and PURXM reproduces this name too, and
  it isn't "TESTAPP".


