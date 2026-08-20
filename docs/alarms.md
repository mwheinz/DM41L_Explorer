# DM41L Explorer: Alarm Storage Research Report

**Status:** Research notes for GitHub issue #5 ("Add support for alarms").
The buffer-level layout, the per-alarm entry format, the fire/reschedule/
expire lifecycle, and the message-length range are all **confirmed against
real DM41L dumps**: `src/tests/data/alarmtest.dm41` (created 2026-08-20 —
1 key assignment plus 3 alarms: hourly, daily, one-time),
`src/tests/data/alarmtest2.dm41` (the same calculator, purged to "Memory
Lost", reloaded from `alarmtest.dm41`, and run for several hours — §7),
`src/tests/data/alarmtest3.dm41` (extends `alarmtest2.dm41` with two
longer-message alarms and one zero-length-message alarm — §5), and
`src/tests/data/repeater.dm41` (one alarm with a non-round repeat
interval — §6). Everything marked "confirmed" was verified byte-for-byte
using this project's own `Memory`/`Register` classes. A few structural
questions remain open (see §9) — mainly around program-run alarms, which
haven't been captured yet.

## 1. Sources

- **`src/tests/data/alarmtest.dm41`, `alarmtest2.dm41`, `alarmtest3.dm41`,
  `repeater.dm41`** — real DM41L dumps created by the user specifically
  for this research. These are the primary source for everything in
  §3–7 below.
- **HP-41 Synthetic Programming Made Easy**, Keith Jarett (SYNTHETIX) —
  `docs/pdfs/hp41-synth-prog-easy.pdf`. §6 ("On-Line Memory"), Figure 6.2
  ("On-Line Memory Usage") and its accompanying prose. Source for the
  buffer's overall shape (header register, top delimiter, "time plus
  optional message/repeat" per alarm) before it was checked against the
  real dumps.
- **HP-41 Advanced Programming Tips**, Alan McCornack & Keith Jarett
  (SYNTHETIX) — `docs/pdfs/hp41-adv-prog-tips.pdf`. Contains a full FOCAL
  program, "SA"/"RA" (Save Alarms / Recall Alarms), with line-by-line
  commentary that independently confirmed the header's marker byte and its
  position before the real-dump check.
- **A Programmer's Handbook v2.07** —
  `docs/pdfs/A programmers handbook v.2.07.pdf`. A microcode/hardware-level
  reference. Documents the physical Timer chip's own "Alarm Register A/B"
  (a different thing from the main-memory alarm buffer — see §8), and its
  1/100-second-since-1900 clock format turned out to be exactly the format
  used by the main-memory alarm entries too (see §4).
- **Searched but no alarm byte-format content found:** HP-41 Synthetic
  Programming (Wickes' full book) and HP-41 Extended Functions Made Easy.
  Both discuss the alarm-setting *functions* (`SW`, `RCLSW`, `ALMCAT`, etc.)
  from a keystroke perspective, not the underlying register format.
  `ppcrom-um.pdf` and the two CX Owner's Manual volumes are large scanned
  PDFs that were not exhaustively searched.

## 2. Where alarms live

| Region (low → high address) | Notes |
| --- | --- |
| 0x000–0x00F | Status registers |
| 0x040–0x0BF | Extended Memory #0 |
| 0x0C0 upward | **Key Assignments** — grows upward as entries are added |
| immediately above Key Assignments | **Alarms** (this report) |
| above Alarms, below `.END.` | Free registers, available for programs, alarms, or key assignments |
| `.END.` down to R00 | User Programs |
| R00 up to 0x1FF | Data Memory |

Confirmed directly in `alarmtest.dm41`: the one key assignment occupies
register 0xC0 only (`Memory.key_assignments_end()` returns 0xC1), the
alarm buffer occupies 0xC1–0xCD immediately above it, and every register
from 0xCE up to `.END.` (0x19B in this dump) is exactly zero — genuinely
free, not an I/O-buffer region. (An earlier draft of this report carried
over a general-HP-41 mention of "other I/O buffers" from published
prose describing peripherals — Card Reader, HP-IL, printer — that the
DM41L doesn't emulate; the user corrected that, and this dump confirms
the correction: nothing but zeros sits above the alarm buffer here.)

## 3. Alarm buffer structure (confirmed)

The whole buffer in `alarmtest.dm41`, registers 0xC1–0xCD:

```
0xc1  aa 0d 00 00 00 00 00      <- header
0xc2  39 96 21 42 00 01 02      <- alarm 1 ("HOURLY"): time
0xc3  00 00 00 36 00 00 00      <- alarm 1: repeat interval
0xc4  00 00 48 4f 55 52 4c      <- alarm 1: message, registers 1/2
0xc5  59 20 41 4c 41 52 4d      <- alarm 1: message, registers 2/2 ("HOURLY ALARM")
0xc6  39 96 21 60 00 01 02      <- alarm 2 ("DAILY"): time
0xc7  00 00 08 64 00 00 00      <- alarm 2: repeat interval
0xc8  00 00 00 44 41 49 4c      <- alarm 2: message, registers 1/2
0xc9  59 20 41 4c 41 52 4d      <- alarm 2: message, registers 2/2 ("DAILY ALARM")
0xca  39 96 21 96 00 00 02      <- alarm 3 ("SINGLE"): time (no repeat register)
0xcb  00 00 53 49 4e 47 4c      <- alarm 3: message, registers 1/2
0xcc  45 20 41 4c 41 52 4d      <- alarm 3: message, registers 2/2 ("SINGLE ALARM")
0xcd  f0 00 00 00 00 00 00      <- top delimiter
```

- **Header** (0xC1): byte 0 = `0xAA`, confirmed exactly as the published
  sources said. Byte 1 = `0x0D` = **13**, and the buffer really is 13
  registers long (0xC1 through 0xCD inclusive) — this **confirms the
  count includes the header and the delimiter themselves**, not just the
  alarm-data registers between them. Bytes 2–6 are all zero in every
  sample seen so far; whether they're ever used for anything is still
  unconfirmed.
- **Top delimiter** (0xCD, the last register the header's count reaches):
  byte 0 = `0xF0`, all other bytes zero. Confirmed present in every
  sample, always exactly at `header_address + count - 1`.
- **Alarms are packed in ascending address order** immediately after the
  header (alarm 1 right after the header, alarm 2 after that, alarm 3
  after that, then the delimiter) — the opposite convention from Key
  Assignments and Program/XM Memory (which grow downward / high-to-low),
  and matching Data Memory's normal ascending convention instead. Worth
  adding as a row to `docs/memory.md`'s "Reading Direction Quick
  Reference" table, which doesn't currently have one for Alarms.
- **Alarms are ordered by trigger time, not creation order** — confirmed
  in §5 below, where three newly-created alarms landed *between* two
  pre-existing ones rather than at either end of the buffer.

## 4. Per-alarm entry format (confirmed)

Each alarm is `[time register] + [repeat register, only if repeating] +
[message register(s), 0 or more]`, matching Jarett's description. All
BCD-bearing fields share one encoding:

**Time/interval encoding:** the first 12 nibbles (bytes 0–5) are plain
BCD decimal digits (0–9 only, never A–F) forming a 12-digit number in
hundredths of a second, exactly the "1/100 SECONDS SINCE JAN 1 1900"
format the Programmer's Handbook documents for the physical Timer chip's
own CLOCK/ALARM registers (§8) — the main-memory alarm catalog reuses
that same convention. Decoding `alarmtest.dm41`'s three time registers
this way, against a 1900-01-01 00:00:00 epoch:

| Register | Raw (first 12 digits) | Decoded |
| --- | --- | --- |
| 0xC2 (alarm 1, "HOURLY") | `399621420001` | 2026-08-20 11:30:00 |
| 0xC6 (alarm 2, "DAILY") | `399621600001` | 2026-08-20 12:00:00 |
| 0xCA (alarm 3, "SINGLE") | `399621960000` | 2026-08-20 13:00:00 |

— exactly the date the dump was made, with clean half-hour trigger times,
which is about as strong a confirmation as this kind of reverse
engineering gets. The two repeat-interval registers decode the same way,
as a plain duration rather than an absolute timestamp:

| Register | Raw (first 12 digits) | Decoded |
| --- | --- | --- |
| 0xC3 (alarm 1 repeat) | `000000360000` | 3600.00 sec = **1 hour** |
| 0xC7 (alarm 2 repeat) | `000008640000` | 86400.00 sec = **1 day** |

Alarm 3 ("SINGLE"), a one-time alarm, has **no repeat register at all** —
its message registers (0xCB) start immediately after its time register
(0xCA). This is presence/absence of a whole register, not a flag bit.

**Byte 6 of the time register = the message's register count — and only
that, not the alarm entry's overall size.** An earlier pass at this
report guessed byte 6 was a generic "record-type tag" (`0x02` for a
trigger-time record); `alarmtest3.dm41` (§5) disproved that and revealed
the real meaning: it's `ceil(message_length / 7)`, the number of
registers the message occupies (0 to 4, i.e. 0–24 characters) — counting
*only* the message registers, regardless of whether a repeat register is
also present. Every sample confirms it:

| Alarm | Message | Length | `ceil(len/7)` | Byte 6 |
| --- | --- | --- | --- | --- |
| "HOURLY ALARM" | `HOURLY ALARM` | 12 | 2 | `0x02` |
| "DAILY ALARM" | `DAILY ALARM` | 11 | 2 | `0x02` |
| "SINGLE ALARM" | `SINGLE ALARM` | 12 | 2 | `0x02` |
| alarmtest3 alarm B | `LARGER ALARM MSG` | 16 | 3 | `0x03` |
| alarmtest3 alarm C | *(none)* | 0 | 0 | `0x00` |
| alarmtest3 alarm D | `LARGER ALARM MESSAGE,,,` | 23 | 4 | `0x04` |
| `repeater.dm41`'s alarm | `REPEATER` | 8 | 2 | `0x02` |

`repeater.dm41` (§6) is the cleanest disambiguator, since it has *both*
a repeat register and a message: the whole entry is 4 registers (time +
repeat + 2 message), but byte 6 is `0x02` — matching only the message
registers, not 4 (the whole entry) and not 3 (everything after the time
register, repeat included). A parser has to separately determine whether
a repeat register is present (the peek/magnitude check below) before it
knows the entry's true total size; byte 6 alone never tells it that.

This is the field that actually lets a parser know exactly how many
message registers to consume — see the boundary-detection algorithm
below. The repeat-interval register's byte 6 is `0x00` in every sample
seen so far (2 for 2); with the message-count reading now nailed down for
the *time* register, the repeat register's byte 6 looks more like a
fixed/reserved `0x00` than a second copy of anything, but that's only
2 data points.

**How a parser tells repeating from one-time, and finds message
boundaries:** combining byte 6 (now known) with one more check resolves
this almost completely. After the time register:

1. **Peek at the next register.** If every nibble is 0–9 (valid BCD) *and*
   its magnitude is small enough to be a plausible duration (a repeat
   interval this format has actually stored: 3600s, 86400s — nowhere near
   the billions-of-centiseconds size of an absolute 1900-epoch timestamp),
   it's the repeat-interval register; consume it. Otherwise, there's no
   repeat register, and this register is either the first message
   register or (if byte 6 was `0x00`) already the next alarm's time
   register.
2. **Consume exactly byte-6 message registers** (0 or more) as raw ASCII.
   No further boundary-guessing is needed — the count is explicit.
3. The next register is the start of the next alarm's time field, or (if
   its leading byte is `0xF0`) the top delimiter.

Checked against `alarmtest3.dm41`'s harder cases: alarm C's time register
has byte 6 = `0x00`, so its entry is exactly **one register — the whole
alarm is just the time field**, and the very next register is
immediately the next alarm's time register (confirmed: it decodes as a
clean, later timestamp, not a plausible interval). Alarm D's time
register has byte 6 = `0x04`; the register right after it is *not*
all-BCD (it starts with printable text), so there's no repeat register,
and exactly 4 registers of message text follow, ending precisely where
the next alarm (or the delimiter) begins. Both match perfectly with no
ambiguity, because step 2 no longer needs to guess where the message
ends — it already knows.

The one residual soft spot is step 1's repeat-register test: a message
built mostly from ASCII digits or early-alphabet capital letters
(`A`–`I`, `P`) can produce an all-BCD-nibble register too, in principle.
The magnitude check (plausible-interval-sized vs. plausible-absolute-
timestamp-sized) narrows this a lot, since real messages don't tend to
look like 10-digit numbers, but it isn't a hard proof. No sample so far
has triggered it.

**Message registers:** raw packed ASCII, `ceil(length / 7)` registers
(0 to 4, matching a 0–24 character range), no marker byte (unlike the
single-register `0x10`-marked alpha convention used elsewhere in main
memory). The message is right-justified across its registers with any
padding as leading NUL bytes only in the lowest-address register of the
span — reading the registers low-to-high (normal address and byte order)
reproduces the text directly. Confirmed messages so far: `"HOURLY
ALARM"` (12 chars, 2 registers), `"DAILY ALARM"` (11, 2), `"SINGLE
ALARM"` (12, 2), `"LARGER ALARM MSG"` (16, 3), `"LARGER ALARM
MESSAGE,,,"` (23, 4 — the user's literal test string, not a padding
artifact; it happens to end in three commas), and a genuine **zero-length
message** (0 registers at all — see §5).

**Counting active alarms:** there's no dedicated count field anywhere —
the header's byte 1 is a *register* count (how big the whole buffer is),
not an *alarm* count, and since alarms vary in size (1 to 5 registers
depending on repeat/message length) the two aren't interchangeable. Byte
1 was 13/10/20 across the three dumps while the actual alarm counts were
3/2/5 — no arithmetic shortcut connects those pairs. Header bytes 2–6
are all zero in every sample regardless of alarm count, ruling those out
as a hidden counter too. **The only way to get the count is to walk the
buffer** with the parsing algorithm above and tally how many time
registers you pass — this is presumably exactly what `ALMCAT` (the
alarm-catalog display function) does live on the calculator, rather than
reading a precomputed value. Implemented and verified against all three
dumps:

```python
def count_alarms(memory):
    addr = memory.key_assignments_end()
    header = memory.get_register(addr)
    if header.get_bytes()[0] != 0xAA:
        return 0                       # no alarm buffer at all
    end = addr + header.get_bytes()[1]  # one past the delimiter
    addr += 1                           # skip header
    alarms = 0
    while addr < end - 1:               # stop before the delimiter
        time_reg = memory.get_register(addr)
        msg_regs = time_reg.get_bytes()[6]
        alarms += 1
        addr += 1
        if addr < end - 1:
            peek = memory.get_register(addr).get_bytes().hex()
            if is_plausible_repeat_register(peek):   # §4's all-BCD + magnitude check
                addr += 1                             # skip the repeat register
        addr += msg_regs                # skip the message registers
    return alarms
```

`count_alarms('alarmtest.dm41') == 3`, `count_alarms('alarmtest2.dm41')
== 2`, `count_alarms('alarmtest3.dm41') == 5` — all confirmed exactly
right. This is the same residual-soft-spot caveat as the rest of §4 (the
repeat-register peek), so it inherits that limitation, but nothing else
in the format offers a cheaper way to get this number.

## 5. Confirmed: message length range and alarm ordering (alarmtest3.dm41)

`alarmtest3.dm41` extends `alarmtest2.dm41`'s two surviving alarms
(hourly, daily) with three new ones, testing the message-length extremes
the documentation describes ("zero characters... up to 24 characters
long"). The full buffer, now 20 registers (0xC1–0xD4):

```
0xc1  aa 14 00 00 00 00 00   header (count 13 -> 10 -> 20)
0xc2  39 96 23 22 00 01 02   alarm A ("HOURLY", repeating): time  = 2026-08-20 16:30:00, msg regs = 2
0xc3  00 00 00 36 00 00 00   alarm A: repeat = 3600s (1 hour)
0xc4  00 00 48 4f 55 52 4c   alarm A: msg 1/2
0xc5  59 20 41 4c 41 52 4d   alarm A: msg 2/2  ("HOURLY ALARM")
0xc6  39 96 23 40 00 00 03   alarm B (new, one-time): time = 2026-08-20 17:00:00, msg regs = 3, no repeat register
0xc7  00 00 00 00 00 4c 41   alarm B: msg 1/3
0xc8  52 47 45 52 20 41 4c   alarm B: msg 2/3
0xc9  41 52 4d 20 4d 53 47   alarm B: msg 3/3  ("LARGER ALARM MSG")
0xca  39 96 23 49 00 00 00   alarm C (new, one-time): time = 2026-08-20 17:15:00, msg regs = 0 (no message, no repeat)
0xcb  39 96 23 58 00 00 04   alarm D (new, one-time): time = 2026-08-20 17:30:00, msg regs = 4, no repeat register
0xcc  00 00 00 00 00 4c 41   alarm D: msg 1/4
0xcd  52 47 45 52 20 41 4c   alarm D: msg 2/4
0xce  41 52 4d 20 4d 45 53   alarm D: msg 3/4
0xcf  53 41 47 45 2c 2c 2c   alarm D: msg 4/4  ("LARGER ALARM MESSAGE,,,")
0xd0  39 96 30 24 00 01 02   alarm E ("DAILY", repeating): time = 2026-08-21 12:00:00, msg regs = 2
0xd1  00 00 08 64 00 00 00   alarm E: repeat = 86400s (1 day)
0xd2  00 00 00 44 41 49 4c   alarm E: msg 1/2
0xd3  59 20 41 4c 41 52 4d   alarm E: msg 2/2  ("DAILY ALARM")
0xd4  f0 00 00 00 00 00 00   top delimiter
```

Register accounting checks out exactly: header(1) + A(4) + B(4) + C(1) +
D(5) + E(4) + delimiter(1) = 20, matching the header's byte-1 count.

- **A zero-length message is a real, confirmed case: the alarm is just
  its time register, nothing else.** Alarm C's time register (0xCA) has
  byte 6 = `0x00` and no repeat register, so the entire entry is one
  register. The very next register (0xCB) is unambiguously the next
  alarm's time field, not a leftover part of alarm C — its value is far
  too large to be a plausible repeat interval, and it's exactly what
  alarm D's own byte-6-driven parse expects. This confirms the minimum
  possible alarm size is a single register.
- **24-character-class messages take exactly 4 registers, matching the
  documented 24-character cap** (`ceil(24/7) = 4`; the one long-message
  sample here is 23 characters, still 4 registers). No sample yet uses
  the full 24 characters or attempts to exceed it.
- **New alarms are inserted in trigger-time order, not creation order or
  simple append — deliberately tested by the user, not just observed.**
  Alarms B, C, and D were all created after `alarmtest2.dm41` was saved
  (when the hourly alarm was already sitting at 16:30 and the daily
  alarm at tomorrow 12:00). The user specifically created alarm C
  *last* — after B and D already existed — but gave it a trigger time
  (17:15) between B's (17:00) and D's (17:30) as a deliberate test of
  insertion order. It landed exactly between them in the buffer, not
  appended after D (which creation order would predict) or inserted
  right above the header (which "newest first," the Key Assignments
  convention, would predict). Combined with B/C/D as a group landing
  between the pre-existing hourly and daily alarms, the buffer is kept
  sorted by trigger time at all times — this is the general rule that
  also explains the "reschedule" behavior in §7 below.

## 6. Confirmed: non-round repeat intervals (repeater.dm41)

Every repeat interval seen before this dump was a round number (1 hour,
1 day). `repeater.dm41` has one alarm, triggering 2026-08-20 17:18:00
and repeating every 1 hour 23 minutes 45 seconds — an arbitrary value,
testing whether the encoding still holds up. Full buffer (0xC1–0xC6):

```
0xc1  aa 06 00 00 00 00 00   header (count 6: 1 alarm, entry uses all of it)
0xc2  39 96 23 50 80 01 02   time = 2026-08-20 17:18:00, msg regs = 2
0xc3  00 00 00 50 25 00 00   repeat = 5025.00 sec = 1h 23m 45s exactly
0xc4  00 00 00 00 00 00 52   msg 1/2
0xc5  45 50 45 41 54 45 52   msg 2/2  ("REPEATER")
0xc6  f0 00 00 00 00 00 00   top delimiter
```

Both the time and the repeat interval decode exactly right against a
genuinely non-round value (1×3600 + 23×60 + 45 = 5025 seconds), confirming
the BCD-hundredths-of-a-second encoding isn't a coincidence that only
happens to work for clean hour/day values. This dump is also the
clearest example so far for one nuance of byte 6 (§4): the whole entry
here is 4 registers (time + repeat + 2 message), but byte 6 is `0x02` —
matching only the message registers, not the entry's total size. See §4
for the full comparison.

## 7. Confirmed: what happens when an alarm fires

`alarmtest2.dm41` is `alarmtest.dm41`'s calculator, purged to "Memory
Lost", reloaded from `alarmtest.dm41`, then left running for several
hours (past all three alarms' first trigger, and past the hourly alarm's
second and third triggers) before being saved again. Diffing the two
dumps' alarm buffers answers two questions directly:

```
alarmtest.dm41                         alarmtest2.dm41
0xc1  aa 0d 00 00 00 00 00   header     0xc1  aa 0a 00 00 00 00 00   header (count 13 -> 10)
0xc2  39 96 21 42 00 01 02   time  ->   0xc2  39 96 23 22 00 01 02   time (updated in place)
0xc3  00 00 00 36 00 00 00   repeat     0xc3  00 00 00 36 00 00 00   repeat (unchanged)
0xc4  00 00 48 4f 55 52 4c   msg 1/2    0xc4  00 00 48 4f 55 52 4c   msg 1/2 (unchanged)
0xc5  59 20 41 4c 41 52 4d   msg 2/2    0xc5  59 20 41 4c 41 52 4d   msg 2/2 (unchanged)
0xc6  39 96 21 60 00 01 02   time  ->   0xc6  39 96 30 24 00 01 02   time (updated in place)
0xc7  00 00 08 64 00 00 00   repeat     0xc7  00 00 08 64 00 00 00   repeat (unchanged)
0xc8  00 00 00 44 41 49 4c   msg 1/2    0xc8  00 00 00 44 41 49 4c   msg 1/2 (unchanged)
0xc9  59 20 41 4c 41 52 4d   msg 2/2    0xc9  59 20 41 4c 41 52 4d   msg 2/2 (unchanged)
0xca  39 96 21 96 00 00 02   time            (gone — alarm deleted entirely)
0xcb  00 00 53 49 4e 47 4c   msg 1/2         (gone)
0xcc  45 20 41 4c 41 52 4d   msg 2/2         (gone)
0xcd  f0 00 00 00 00 00 00   delimiter  0xca  f0 00 00 00 00 00 00   delimiter (moved down to close the gap)
```

- **A repeating alarm's time register updates when it fires — but "in
  place" overstates it.** The hourly alarm's time register (0xC2) changed
  from `11:30:00` to `16:30:00` — exactly five repeat intervals
  (5 × 3600s = 5 hours) later, consistent with it having fired at 11:30,
  12:30, 13:30, 14:30, and 15:30 before the user stopped the run "till
  almost 4 PM." The daily alarm's time register (0xC6) changed from
  `2026-08-20 12:00:00` to `2026-08-21 12:00:00` — one repeat interval
  later, after firing once. Both alarms' repeat-interval and message
  registers are byte-for-byte unchanged, and byte 6 of both time
  registers is still `0x02` — this still rules out one alternative
  reading of byte 6 floated in an earlier draft (a remaining-occurrence
  counter), and §5 later showed what byte 6 actually is (message
  register count).

  **Correction (from the user):** an earlier draft of this section called
  this "rescheduling in place," implying the calculator always rewrites
  the same register regardless of the new time. §3/§5 already established
  a stronger, more general rule that better explains this: **the buffer
  is kept sorted by trigger time at all times**, confirmed separately by
  how alarm C landed in `alarmtest3.dm41` — the user added it *last*
  (after alarm D existed), gave it a trigger time between alarms B and D,
  and it was inserted between them rather than appended at the end. A
  reschedule is really the same operation as an insert: remove the fired
  alarm, then place it wherever its new trigger time belongs in sorted
  order. In this dump, both alarms' new times still fell earlier than
  every other alarm's time (16:30 and next-day-12:00 didn't cross each
  other or anything else), so the sorted position happened not to change
  — which is why the register contents updated without the alarm visibly
  moving. That's a special case of the general sort-order rule, not
  separate "in-place update" behavior. A dump where a reschedule actually
  crosses a neighboring alarm's time (forcing a real position swap, with
  registers shifting rather than just one register's bytes changing)
  would confirm this conclusively — see §9.
- **A one-time alarm is deleted outright once it fires**, not flagged or
  zeroed in place. The single alarm's three registers (0xCA–0xCC, time +
  2 message registers) are simply gone in `alarmtest2.dm41`. The header's
  count byte dropped from `0x0D` (13) to `0x0A` (10) — exactly the 3
  registers removed — and the top delimiter moved from 0xCD down to 0xCA
  to close the gap, staying exactly at `header_addr + count - 1` as §3
  described. The two surviving alarms didn't move at all (still at
  0xC2–0xC5 and 0xC6–0xC9); only the space above them was reclaimed.

## 8. A second, unrelated "alarm register" — don't conflate the two

The Programmer's Handbook separately documents the physical Timer
peripheral chip's own hardware "ALARM REGISTER A" / "ALARM REGISTER B" —
holding the "TIME OF NEXT ALARM" in the same BCD, 1/100-second-since-
1 Jan 1900 format confirmed above for the main-memory entries, read/
written via the `WRIT 2(Y)` / `READ 2(Y)` timer-chip instructions. This is
a live hardware register on the timer chip that actually fires the
interrupt; it is distinct from the main-memory alarm buffer described in
§2–7, which is the persistent catalog that FOCAL functions like `SW`,
`ALMCAT`, and `RCLSW` maintain in RAM (and presumably use to reprogram the
hardware register as needed). Both are called "alarm register(s)" across
the source material, which invites confusion — worth keeping distinct in
any code or docs that come out of this research.

## 9. Remaining open questions / next steps

- **Repeat-register detection's residual ambiguity** (§4) — the
  magnitude + all-BCD check is well-supported but not proven airtight; a
  message built entirely from digits/early-alphabet letters could in
  principle be misread. No sample has triggered this yet.
- **Header bytes 2–6** — all zero in every sample; unconfirmed whether
  they're ever used.
- **Program-run alarms** — every alarm seen so far is message-type (one
  that displays text and beeps). An alarm set to run a program on trigger
  presumably encodes the program name somewhere, or uses a different
  record shape entirely — not tested yet. Relatedly, it's not known
  whether a *repeating* program-run alarm reschedules the same way §7
  describes for message alarms, or what a disabled alarm looks like.
- **Sort-order is well-supported but a reschedule-across-a-neighbor case
  hasn't been captured yet** (§5/§7). The insertion-order evidence is
  strong (the user deliberately tested it — see §5), and it fully
  explains why the fired-alarm reschedules in §7 looked like in-place
  updates: neither alarm's new time crossed another alarm's position. To
  fully confirm the general rule at the register level (not just infer
  it), the cleanest test would be a fast-repeating alarm whose next
  trigger time is deliberately made to land *past* another alarm's time
  — if the sort-by-time rule is real, that alarm's whole entry should
  visibly move to a new address (with neighboring alarms' registers
  shifting to make room), not just have its own time bytes rewritten.
- **The exact 24-character cap** hasn't been tested at the boundary — no
  sample has tried a message of exactly 24 characters or attempted one
  longer to see how (or whether) the calculator rejects it.
- `ppcrom-um.pdf` and the two `hp41cx-om-vol*-en.pdf` Owner's Manual
  volumes are large scanned PDFs that weren't exhaustively searched and
  may help with the above, particularly program-run alarms and any
  documented flag byte meanings.
- Next most useful test dumps, in rough priority order: (1) a program-run
  alarm, (2) a disabled alarm, (3) an alarm with a trigger time earlier
  than an existing alarm (settles insertion-order conclusively), (4) a
  message of exactly 24 characters and one attempting 25+.
