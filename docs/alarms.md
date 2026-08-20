# DM41L Explorer: Alarm Storage Research Report

**Status:** Research notes for GitHub issue #5 ("Add support for alarms"). This
is a first pass mined from `docs/pdfs/`, in the same spirit as
`docs/program.md` and `docs/key_assignments.md`. Unlike those two documents,
**nothing below has been confirmed against a real memory dump yet** — there is
no `.dm41` test fixture in `src/tests/data/` with an alarm set, so everything
here is sourced from published documentation only. Treat this as a starting
point for reverse-engineering, not as validated fact, until it's checked
against a real device capture.

## 1. Sources checked

- **HP-41 Synthetic Programming Made Easy**, Keith Jarett (SYNTHETIX) —
  `docs/pdfs/hp41-synth-prog-easy.pdf`. §6 ("On-Line Memory"), Figure 6.2
  ("On-Line Memory Usage") and its accompanying prose, is the main source
  for the structural description in §3–4 below.
- **HP-41 Advanced Programming Tips**, Alan McCornack & Keith Jarett
  (SYNTHETIX) — `docs/pdfs/hp41-adv-prog-tips.pdf`. Contains a full FOCAL
  program, "SA"/"RA" (Save Alarms / Recall Alarms), with line-by-line
  commentary. This independently confirms the header marker byte, its
  position, and the region ordering, and is the most concrete source found.
- **A Programmer's Handbook v2.07** —
  `docs/pdfs/A programmers handbook v.2.07.pdf`. A microcode/hardware-level
  reference. It separately documents the physical Timer chip's own "Alarm
  Register A/B" (a different thing from the main-memory alarm buffer — see
  §5) and labels an "Alarm buffer area" in its RAM map, but gives no byte
  detail for it.
- **Searched but no alarm byte-format content found:** HP-41 Synthetic
  Programming (Wickes' full book, `hp41-synthetic-prog.pdf`) and HP-41
  Extended Functions Made Easy (`hp41-extfunceasy-en.pdf`). Both discuss the
  alarm-setting *functions* (`SW`, `RCLSW`, `ALMCAT`, etc.) from a keystroke
  perspective, not the underlying register format. `ppcrom-um.pdf` and the
  two CX Owner's Manual volumes are large scanned PDFs that were not
  exhaustively searched — worth a closer look if the unknowns below need
  closing (see §6).

## 2. Where alarms live

This confirms and slightly extends the existing note in `docs/memory.md`'s
Main Memory table ("Alarms | ... | After Key Assignments | variable"):

| Region (low → high address) | Notes |
| --- | --- |
| 0x000–0x00F | Status registers |
| 0x040–0x0BF | Extended Memory #0 |
| 0x0C0 upward | **Key Assignments** — grows upward as entries are added |
| immediately above Key Assignments | **Alarms** (this report) |
| above Alarms, below `.END.` | Free registers, available for programs, alarms, or key assignments |
| `.END.` down to R00 | User Programs |
| R00 up to 0x1FF | Data Memory |

Both sources agree on this ordering. Jarett's Figure 6.2 shows, top to
bottom in the diagram: Program Memory → "Free" Registers → **Alarms (Time
Module Alarm Data)** → Function Key Assignments → bottom of on-line memory
(hex 0C0 = 192). McCornack & Jarett's Advanced Programming Tips states it in
prose: "Below the free registers are the buffers. The order of the buffers,
from hex address 0C0 (decimal 192) upwards is key assignments, followed by
alarms and other I/O buffers."

**Correction (per user, who knows the DM41L hardware/emulation directly):**
that last phrase — "and other I/O buffers" — describes what's possible on a
physical HP-41 with peripherals like a Card Reader, HP-IL loop, or printer
attached, each of which can claim its own buffer register(s) in this same
stacking region above Key Assignments. The DM41L doesn't emulate those
peripherals, so no such I/O-buffer region exists in the DM41L specifically.
Concretely: everything above the Alarms region (or above Key Assignments, if
there are no alarms) up to `.END.` is simply **unused free registers** —
available for additional programs, alarms, or key assignments, exactly as
`docs/memory.md` already states. The row above has been corrected
accordingly; treat "I/O buffers" as a general-HP-41 fact that doesn't apply
to this project's target hardware, not as a region that actually appears in
DM41L dumps.

## 3. Buffer-level structure

Jarett's description in Synthetic Programming Made Easy (§6, p.109):

> Timer alarms reside immediately above the key assignment registers. Each
> alarm requires one register for the time, plus additional spaces for a
> message and/or a repeat interval associated with the alarm. One "header"
> register at the bottom of the alarm registers, just above the uppermost
> key assignment register, is required to define the total number of alarm
> registers in use. Another register delimits the top of the alarms.

Breaking that down against the byte-level evidence in Advanced Programming
Tips' "SA" program listing:

- **Header register** — sits at the *lowest* address of the alarm buffer,
  immediately above the topmost key-assignment register.
  - **Byte 0 (MSB) = `0xAA`.** This is the buffer's signature byte. The "SA"
    program locates the header by scanning register addresses upward from
    191 (0xBF, i.e. one below the key-assignment region's start) and testing
    each register's leftmost byte for a decoded value of 170 (`0xAA`):
    "If this byte is hex AA, decimal 170, it will match line 13." `0xAA`
    can't be mistaken for BCD numeric data (nibbles A/A aren't valid decimal
    digits), the same trick used by `0xF0` for key-assignment registers and
    `0x10` for XM data-file headers elsewhere in this memory map.
  - **Byte 1 = total register count of the whole alarm buffer** (all alarm
    entries combined, not per-alarm). Confirmed directly: "Line 18 decodes
    the second byte of the alarm register, which contains the number of
    registers in the buffer." The program uses this value verbatim as the
    register count when copying the whole buffer to an Extended Memory file.
  - Bytes 2–6 of the header: not decoded by either source.
- **Top delimiter register** — a second, separate register that "delimits
  the top of the alarms," per Jarett, sitting at the *highest* address of
  the buffer (adjacent to the free-register area below `.END.`). Neither
  source gives its byte format.
- The individual alarm entries occupy the registers between the header and
  the top delimiter.

## 4. Individual alarm entries

- Each alarm occupies **at least one register**, holding the alarm's
  trigger date/time.
- **Additional registers are appended per-alarm** if the alarm has an
  associated message and/or a repeat interval — the exact split isn't
  stated (e.g. whether message and repeat interval each get a dedicated
  register, or share one, or vary with message length).
- Neither source gives the byte/nibble layout of a single alarm entry: how
  the date/time is packed, how message text is encoded, how a repeat
  interval is represented, or how the alarm's type/state (message vs.
  program-run alarm, enabled/disabled, etc.) is flagged.
- Notably, the "SA"/"RA" program itself never decodes an individual alarm.
  It treats the whole buffer as an opaque block: it reads the header's
  count byte, then copies that many whole registers to Extended Memory
  with `NRCLM`/`NSTOM` and zeroes the originals, with no per-alarm parsing
  anywhere in the listing. So even the people who wrote the reference
  material didn't need to (or chose not to) document the internal layout —
  this part will need reverse-engineering from a real dump.

## 5. A second, unrelated "alarm register" — don't conflate the two

The Programmer's Handbook separately documents the physical Timer
peripheral chip's own hardware "ALARM REGISTER A" / "ALARM REGISTER B" —
holding the "TIME OF NEXT ALARM" in the same BCD, 1/100-second-since-
1 Jan 1900 format used by the clock registers, read/written via the
`WRIT 2(Y)` / `READ 2(Y)` timer-chip instructions. This is a live hardware
register on the timer chip that actually fires the interrupt; it is
distinct from the main-memory alarm buffer described in §2–4, which is the
persistent catalog that FOCAL functions like `SW`, `ALMCAT`, and `RCLSW`
maintain in RAM (and presumably use to reprogram the hardware register as
needed). Both are called "alarm register(s)" across the source material,
which invites confusion — worth keeping distinct in any code or docs that
come out of this research.

## 6. Known unknowns / next steps

- Byte layout of the header register's bytes 2–6.
- Byte layout of the top-delimiter register.
- Byte layout of a single alarm entry: date/time encoding, message-text
  packing, repeat-interval encoding, and any type/state flag.
- Whether the count in the header's byte 1 includes the header and
  delimiter registers themselves, or only the alarm-data registers between
  them (the "SA" program's usage is consistent with either reading — it
  just copies "that many registers starting from the header," which was
  not pinned down further here).
- `ppcrom-um.pdf` and the two `hp41cx-om-vol*-en.pdf` Owner's Manual volumes
  are large scanned PDFs that weren't exhaustively searched for this report
  and may have more detail (the PPC ROM manual in particular documents
  several alarm-related synthetic utilities per the Advanced Programming
  Tips references to it).
- The most reliable path to closing these unknowns is almost certainly the
  same one used for `docs/program.md` and `docs/key_assignments.md`: set a
  real alarm (with and without a message, with and without a repeat
  interval) on the actual DM41L hardware, capture a dump over the serial
  protocol this project already implements, and diff it against a
  no-alarm baseline dump.
