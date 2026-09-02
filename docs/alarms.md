# DM41L Explorer: Alarm Storage Research Report

**Status:** Research notes for GitHub issue #5 ("Add support for alarms").
Unlike most of the HP41 architecture, there's no documentation (that I could find) on how alarms are managed. The buffer-level layout, the per-alarm entry format, the fire/reschedule/
expire lifecycle, the message-length range, alarm TYPE encoding
(message/control/conditional), and a best-effort "past due" marker are all
**confirmed against real DM41L dumps**: `src/tests/data/alarmtest.dm41`
(created 2026-08-20 — 1 key assignment plus 3 alarms: hourly, daily,
one-time), `src/tests/data/alarmtest2.dm41` (the same calculator, purged
to "Memory Lost", reloaded from `alarmtest.dm41`, and run for several
hours — §7), `src/tests/data/alarmtest3.dm41` (extends `alarmtest2.dm41`
with two longer-message alarms and one zero-length-message alarm — §5),
`src/tests/data/repeater.dm41` (two alarms, one one-time and one with a
non-round repeat interval — §6, regenerated 2026-09-01 with different
content than the original single-alarm capture this section used to
describe), and `src/tests/data/4alarmtest.dm41` (regenerated 2026-09-01
with one alarm of each type — past-due message, control, conditional,
repeating — §9). Everything marked "confirmed" was verified byte-for-byte
using this project's own `Memory`/`Register` classes. A few structural
questions remain open (see §10) — mainly around the "bypassed past-due
control alarm" case and further confirmation of the past-due marker.

**Implementation status (2026-09-01, updated 2026-09-02):** this research
is now implemented. `src/memory/alarms.py`'s `Alarm`/`Alarms` classes
decode, add, and delete alarms (sorted by trigger time, as §5/§7
describe), and `src/gui/alarms_tab.py` + `src/gui/alarm_edit_dialog.py`
expose it as an Alarms tab, mirroring the Programs/XM Files common-tab
pattern. The bypassed-past-due-control-alarm case (§10) is explicitly not
handled yet. The Alarms tab's first two real-hardware round trips through
the write path (add/edit/delete, then upload) turned up two real bugs the
same day: plain-typed lowercase letters aren't all valid FOCAL characters
(§11, `src/tests/data/badalarms.dm41`), and — more fundamentally —
**§4's "repeat register vs. message text" ambiguity turned out not to be
ambiguous at all**. There is a real, deterministic marker for it, missed
by every earlier pass of this research; see §12, which supersedes §4's
"residual soft spot" framing and §9/§10's related notes. §4 is left as
originally written below for the historical record of how the heuristic
was arrived at, but §12 is the corrected, authoritative account.

It has been concerning that there doesn't seem to be any way to definitively know how the HP41CX/DM41L tell the difference between a repeating and a one-shot alarm, but it is where we are. Also, note that if an "old" DM41 dumpfile that contains alarms is loaded into the emulator all elapsed alarms will be triggered again when the emulator is turned on.

## 1. Sources

- **`src/tests/data/alarmtest.dm41`, `alarmtest2.dm41`, `alarmtest3.dm41`,
  `repeater.dm41`, `4alarmtest.dm41`** — real DM41L dumps created by the
  user specifically for this research. `repeater.dm41` and
  `4alarmtest.dm41` were both regenerated 2026-09-01 with different,
  more thorough content than their original captures (see §6 and §9).
  These are the primary source for everything in §3–7 and §9 below.
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
- **HP-41CX Owner's Manual, Volume 2** —
  `docs/pdfs/hp41cx-om-vol2-en.pdf`, Section 16 ("Alarm Functions"). The
  user pointed to this section 2026-09-01 while confirming what
  "conditional" alarms are and how alarm types are set (`SW`'s
  message/program-execute/non-interrupting-program-execute choice);
  it independently confirmed the up-arrow type-marker scheme in §9 below.

## 2. Where alarms live

| Region (low → high address) | Notes |
| --- | --- |
| 0x000–0x00F | Status registers |
| 0x040–0x0BF | Extended Memory #0 |
| 0x0C0 upward | **Key Assignments** — grows upward as entries are added |
| immediately above Key Assignments | **Alarms** (this report) |
| above Alarms, below `.END.` | Free registers, available for programs, alarms, or key assignments |
| `.END.` up to R00 | User Programs |
| R00 up to 0x1FF | Data Memory |

Confirmed directly in `alarmtest.dm41`: the one key assignment occupies
register 0xC0 only (`KeyAssignments.end_exclusive` returns 0xC1), the
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

**Byte 6 of the time register = the message's register count (low
nibble) plus a best-effort "past due" marker (high nibble) — but not the
alarm entry's overall size.** An earlier pass at this report guessed
byte 6 was a generic "record-type tag" (`0x02` for a trigger-time
record); `alarmtest3.dm41` (§5) disproved that and revealed the message-
count meaning: the low nibble is `ceil(message_length / 7)`, the number
of registers the message occupies (0 to 4, i.e. 0–24 characters) —
counting *only* the message registers, regardless of whether a repeat
register is also present. The high nibble's "past due" reading was added
2026-09-01 (§9) — confirmed `0xF` on exactly one real past-due sample and
`0x0` on every other sample seen so far; treat it with appropriate
skepticism until more past-due samples are captured. Every message-count
sample confirms the low nibble:

| Alarm | Message | Length | `ceil(len/7)` | Byte 6 |
| --- | --- | --- | --- | --- |
| "HOURLY ALARM" | `HOURLY ALARM` | 12 | 2 | `0x02` |
| "DAILY ALARM" | `DAILY ALARM` | 11 | 2 | `0x02` |
| "SINGLE ALARM" | `SINGLE ALARM` | 12 | 2 | `0x02` |
| alarmtest3 alarm B | `LARGER ALARM MSG` | 16 | 3 | `0x03` |
| alarmtest3 alarm C | *(none)* | 0 | 0 | `0x00` |
| alarmtest3 alarm D | `LARGER ALARM MESSAGE,,,` | 23 | 4 | `0x04` |
| `repeater.dm41`'s "REPEATER" alarm | `REPEATER` | 8 | 2 | `0x02` |

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
seen so far; with the message-count reading now nailed down for the
*time* register, the repeat register's byte 6 looks more like a
fixed/reserved `0x00` than a second copy of anything.

**How a parser tells repeating from one-time, and finds message
boundaries:** combining byte 6 (now known) with one more check resolves
this almost completely. After the time register:

1. **Peek at the next register.** If every nibble is 0–9 (valid BCD) *and*
   its magnitude is small enough to be a plausible duration (a repeat
   interval this format has actually stored: 3600s, 86400s, 150 days —
   nowhere near the billions-of-centiseconds size of an absolute
   1900-epoch timestamp), it's the repeat-interval register; consume it.
   Otherwise, there's no repeat register, and this register is either the
   first message register or (if byte 6's low nibble was `0x0`) already
   the next alarm's time register. This project's implementation
   (`Alarms._looks_like_repeat_register()`) bounds "plausible" at up to
   3650 days (10 years), deliberately generous — see §9's ~416.7-day
   sample and §6's 150-day sample, both real, both far larger than the
   1-hour/1-day values first seen.
2. **Consume exactly byte-6's low nibble worth of message registers**
   (0 or more) as raw ASCII. No further boundary-guessing is needed —
   the count is explicit.
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
message** (0 registers at all — see §5). For a control or conditional
alarm, this same field holds a leading up-arrow marker plus the global
label/function name instead of a message — see §9.

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
reading a precomputed value. Implemented and verified against all
dumps:

```python
def count_alarms(memory):
    addr = memory.key_assignments.end_exclusive
    header = memory.get_register(addr)
    if header.get_bytes()[0] != 0xAA:
        return 0                       # no alarm buffer at all
    end = addr + header.get_bytes()[1]  # one past the delimiter
    addr += 1                           # skip header
    alarms = 0
    while addr < end - 1:               # stop before the delimiter
        time_reg = memory.get_register(addr)
        msg_regs = time_reg.get_bytes()[6] & 0x0F
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
== 2`, `count_alarms('alarmtest3.dm41') == 5`, `count_alarms(
'repeater.dm41') == 2`, `count_alarms('4alarmtest.dm41') == 4` — all
confirmed exactly right (`src/memory/alarms.py`'s `Alarms.list_alarms()`
is this project's real implementation of the same algorithm). This is
the same residual-soft-spot caveat as the rest of §4 (the repeat-register
peek), so it inherits that limitation, but nothing else in the format
offers a cheaper way to get this number.

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

## 6. Confirmed: non-round repeat intervals and a mix of alarm types (repeater.dm41)

`repeater.dm41` was regenerated 2026-09-01 with two alarms, replacing
the single-alarm capture this section originally described. Full buffer
(0xC1–0xC9):

```
0xc1  aa 09 00 00 00 00 00   header (count 9)
0xc2  39 96 23 76 00 00 02   alarm 1 ("NONREPTR", one-time): time = 2026-08-20 18:00:00, msg regs = 2, no repeat register
0xc3  00 00 00 00 00 00 4e   alarm 1: msg 1/2
0xc4  4f 4e 52 45 50 54 52   alarm 1: msg 2/2  ("NONREPTR")
0xc5  39 96 23 76 00 01 02   alarm 2 ("REPEATER", repeating): time = 2026-08-20 18:00:00.01, msg regs = 2
0xc6  00 12 96 00 00 00 00   alarm 2: repeat = 1296000000 centiseconds = 12,960,000 sec = **150 days**
0xc7  00 00 00 00 00 00 52   alarm 2: msg 1/2
0xc8  45 50 45 41 54 45 52   alarm 2: msg 2/2  ("REPEATER")
0xc9  f0 00 00 00 00 00 00   top delimiter
```

Both alarms share the same trigger date/time to the second (only the
hundredths digit differs — `00` vs `01`), giving the parser a real case
where "is the next register a repeat register or the next alarm's time
register" can't be resolved by looking at the timestamp alone; byte 6's
message-register count is what actually settles it (§4 step 2). The
150-day repeat interval is confirmed exactly against the raw BCD digits
(150 × 86400 = 12,960,000 sec = 1,296,000,000 centiseconds =
`001296000000`), and — combined with §9's ~416.7-day sample — confirms
the BCD-hundredths-of-a-second encoding holds up for large, non-round
values, not just clean hour/day ones. (The original capture of this
file, since superseded, tested a smaller non-round value — 1h 23m 45s —
with the same result; that sample is no longer on disk.)

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
  12:30, 13:30, 14:30, and 15:30 before the user stopped the run "at
  almost 4 PM." The daily alarm's time register (0xC6) changed from
  `2026-08-20 12:00:00` to `2026-08-21 12:00:00` — one repeat interval
  later, after firing once. Both alarms' repeat-interval and message
  registers are byte-for-byte unchanged, and byte 6 of both time
  registers is still `0x02` — this still rules out one alternative
  reading of byte 6 floated in an earlier draft (a remaining-occurrence
  counter), and §5 later showed what byte 6 actually is (message
  register count).

- **Alarms are arranged in time-sorted order:** testing confirmed this: 
  alarm C landed in `alarmtest3.dm41` between alarm B and alarm D even though
  the user added it *last* 
  (after alarm D existed), but gave it a trigger time between alarms B and D,
  and it was inserted between them rather than appended at the end. A
  reschedule is really the same operation as an insert: remove the fired
  alarm, then place it wherever its new trigger time belongs in sorted
  order. 
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

## 9. Confirmed: alarm type encoding (message/control/conditional) and the past-due marker (4alarmtest.dm41, 2026-09-01)

`4alarmtest.dm41` was regenerated 2026-09-01 with one alarm of each type
the Owner's Manual vol 2 §16 documents: a message alarm the user
deliberately set in the past (to capture what "past due" looks like), a
control alarm (runs a program), a conditional alarm (runs a program only
if the calculator is off — doesn't interrupt an in-use calculator), and
a repeating message alarm. Full buffer, now 14 registers (0xC2–0xCF):

```
0xc2  aa 0e 00 00 00 00 00   header (count 14)
0xc3  39 97 26 36 00 00 f2   alarm 1 ("PAST DUE"): time = 2026-09-01 15:00:00, byte 6 = 0xF2 (past due F, msg regs 2)
0xc4  00 00 00 00 00 00 50   alarm 1: msg 1/2
0xc5  41 53 54 20 44 55 45   alarm 1: msg 2/2  ("PAST DUE", plain message, no leading up-arrow)
0xc6  39 97 27 44 00 00 01   alarm 2 ("^^ALARM", control): time = 2026-09-01 18:00:00, msg regs = 1, not past due
0xc7  5e 5e 41 4c 41 52 4d   alarm 2: label register  ("^^ALARM" -- two up-arrows + "ALARM")
0xc8  39 97 27 80 00 00 02   alarm 3 ("^CONDITIONAL", conditional): time = 2026-09-01 19:00:00, msg regs = 2
0xc9  00 00 5e 43 4f 4e 44   alarm 3: label 1/2  (padding + one up-arrow + "COND")
0xca  49 54 49 4f 4e 41 4c   alarm 3: label 2/2  ("ITIONAL" -- combined "^CONDITIONAL")
0xcb  39 97 28 52 00 01 02   alarm 4 ("REPEATING", repeating message): time = 2026-09-01 21:00:00.01, msg regs = 2
0xcc  00 00 08 64 00 00 00   alarm 4: repeat = 86400s (1 day)
0xcd  00 00 00 00 00 52 45   alarm 4: msg 1/2
0xce  50 45 41 54 49 4e 47   alarm 4: msg 2/2  ("REPEATING")
0xcf  f0 00 00 00 00 00 00   top delimiter
```

**Alarm TYPE is not a separate field — it's the same message field as
before, with 0, 1, or 2 leading "up arrow" characters (`0x5E`, this
project's `docs/trigraphs.md` `\^|` trigraph) marking control and
conditional alarms:**

| Leading up-arrows | Alarm type | Rest of the field means |
| --- | --- | --- |
| none | Message | the message text itself |
| one (`5e`) | Conditional | the global label (or catalog-2 function) to run *only if the calculator is off* at trigger time |
| two (`5e 5e`) | Control | the global label (or catalog-2 function) to run, interrupting whatever the user is doing |

This matches the real ALMCAT display exactly (alarm 2 reads `^^ALARM`,
alarm 3 reads `^CONDITIONAL` on the calculator's own catalog) and is
independently confirmed by the HP-41CX Owner's Manual vol 2 §16's
description of `SW`'s three alarm-type choices. A control or conditional
alarm with nothing after its arrow(s) means "resume the current program
line" rather than naming a label — not exercised by this fixture, not
yet tested against a real dump.

**The past-due marker:** alarm 1's time register byte 6 is `0xF2` rather
than `0x02` — same low nibble (2 message registers) as every other
2-register message, but with the high nibble set to `0xF`. The user
deliberately set this alarm's trigger time in the past specifically to
capture this. Every other sample seen so far — across all five fixtures,
dozens of alarm entries — has high nibble `0x0`. This is a **single
confirmed sample**, so treat it as a working hypothesis, not a settled
fact: it's plausible the calculator only sets this bit at a specific
"past due" transition event (per the Owner's Manual, becoming past due
isn't automatic as time elapses — it needs an activation event, such as
power-off or `ALMNOW`, to process/reschedule/flag an overdue alarm), and
a dump can sit with a stale unfired past-due entry indefinitely without
this bit necessarily reflecting the calculator's live state. More
past-due samples — especially a past-due *repeating* alarm, and a
past-due *control/conditional* alarm — would help confirm this.

**Explicitly not tested yet: the "bypassed past-due control alarm"
case.** The Owner's Manual describes a control alarm that comes due while
bypassed (its program can't run, e.g. because the calculator was off and
set not to wake for it, or another program was already running) as
entering a distinct state from an ordinary past-due message alarm. No
real dump of this case has been captured, and `src/memory/alarms.py`'s
current implementation doesn't attempt to represent it — this was an
explicit, deliberate scope decision when the Alarms tab was built
2026-09-01, not an oversight.

**Alarm 4's repeat interval is a clean 1 day (`86400` sec)**, unlike this
fixture's original capture, which had a single hidden ~416.7-day repeat
register that ALMCAT silently omitted from its own catalog display
(synthetic-programming-poked test data, not something `SW` would
produce — see this project's memory notes from 2026-09-01 if that
sample is ever needed again; it's no longer on disk). One open item from
that earlier pass, not yet resolved: the user described this alarm as
repeating "each day at 8 PM," but its decoded trigger time is
**21:00:00 (9 PM)** — worth double-checking against the real calculator.

## 10. Remaining open questions / next steps

- **The bypassed-past-due-control-alarm case** (§9) — no real dump
  captured yet; explicitly deferred when the Alarms tab was implemented
  2026-09-01.
- **The past-due high-nibble marker** (§9) — confirmed on exactly one
  real sample; more samples (especially a past-due repeating or
  control/conditional alarm) would help confirm both the bit's meaning
  and when the calculator actually sets it.
- **8 PM vs. 9 PM discrepancy** (§9) — the user's verbal description of
  `4alarmtest.dm41`'s repeating alarm doesn't match its decoded trigger
  time; not yet resolved.
- **Repeat-register detection's residual ambiguity** (§4) — the
  magnitude + all-BCD check is well-supported but not proven airtight; a
  message built entirely from digits/early-alphabet letters could in
  principle be misread. No sample has triggered this yet.
- **Header bytes 2–6** — all zero in every sample; unconfirmed whether
  they're ever used.
- **An empty control/conditional label** ("resume the current program
  line," per the Owner's Manual) — described in the manual, not yet
  captured in a real dump.
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
- Next most useful test dumps, in rough priority order: (1) a bypassed
  past-due control alarm, (2) a past-due repeating alarm, (3) an alarm
  with a trigger time earlier than an existing alarm (settles
  insertion-order conclusively).

## 11. Confirmed: alarm text must use valid FOCAL characters (badalarms.dm41, 2026-09-02)

The Alarms tab's write path (add/edit/delete, §"Implementation status"
above) got its first real-hardware round trip 2026-09-02: the user loaded
`4alarmtest.dm41`, deleted the past-due alarm, added a new message alarm
("Test Message", repeating every 5 minutes), and edited the control
alarm's ("^^ALARM") trigger time from 18:00 to 18:20 — then uploaded the
result to the real calculator and reported `ALMCAT` displaying garbage.
The saved dump from that session is `src/tests/data/badalarms.dm41`.

Decoding `badalarms.dm41` by this project's own format rules shows a
buffer that is **completely internally consistent** — correct header
count, correctly-placed delimiter, exact register accounting, every field
in range, byte-for-byte identical to `4alarmtest.dm41` outside the Alarms
region. That ruled out buffer corruption (a wrong address, a missed
shift, a stale leftover register) as the cause, and pointed at the
content of the new alarm's text instead:

```
0xc5  00 00 54 65 73 74 20   "Test Message"'s first message register: pad(2) + "T" "e" "s" "t" " "
0xc6  4d 65 73 73 61 67 65   "Test Message"'s second message register: "M" "e" "s" "s" "a" "g" "e"
```

**FOCAL — the HP41/DM41L character set (docs/trigraphs.md) — has no real
lowercase letters above `'e'` (byte `0x65`).** Bytes `0x66`-`0x7A`
("f"-"z" in ASCII) are reassigned to unrelated symbols on the real
display, the same way `0x5C`/`0x5E`/`0x60`/`0x7E` are reassigned within
the printable range this project's trigraph table already documents.
"Test Message" contains several such bytes (`s`, `t`, `g` at minimum),
which is exactly what a user typing it plainly into the new Alarms
dialog would produce — and exactly what would render as garbage on real
hardware while decoding as perfectly well-formed *bytes* to any tool
(this one included) that doesn't know that constraint.

This project already had one independently-discovered instance of the
same boundary: `src/memory/xm_file.py`'s `NAME_MIN_CHAR`/`NAME_MAX_CHAR`
(`0x20`-`0x65`) restricts XM file *names* to the same range, for the same
underlying reason (issue #11, 2026-08-16) — discovered separately, before
this alarm bug, and never previously connected to a documented general
FOCAL rule. The two findings now confirm each other.

**Fix (2026-09-02):** `memory/trigraphs.py`'s `decode_trigraphs()` gained
an opt-in `restrict_literals` flag: a bare (non-escaped) character
outside `0x20`-`0x65` now raises `ValueError` instead of being silently
accepted, while an explicit `\nnn` (or shorthand) trigraph escape is
still honored for any byte value the caller genuinely wants — this is
what lets a control/conditional alarm's label use a real special FOCAL
character on purpose, per the user's own framing of the requirement.
`memory/alarms.py`'s `_build_entry_registers()` now passes
`restrict_literals=True`, so `add_alarm()` (and therefore the Alarms
tab's Add/Edit dialog) rejects invalid literal text up front rather than
writing it. The dialog's Message/Label field also gained an inline hint
about the constraint. Only the Alarms text path was changed — XM file
*content* (as opposed to names) and Data register alpha text still use
`decode_trigraphs()`'s permissive default, since this finding was scoped
to what the user reported; the same restriction may be worth extending
there too, not yet done.

**Not yet re-verified against real hardware**: this fix has full test
coverage (decode of `badalarms.dm41` pinned, `add_alarm()` rejecting the
exact reported case, trigraph escapes still working) but the corrected
behavior — rejecting bad input rather than writing it — hasn't itself
been round-tripped through a real DM41L upload, since the whole point is
that the bad case no longer reaches the device at all. Worth confirming
with a clean add/edit/delete pass once the user has a chance to retry.

## 12. CORRECTION: the repeat register's presence is NOT ambiguous — the time register's own "hundredths of a second" digits are a real repeats flag (2026-09-02)

§4 described telling a repeat register apart from the start of a message
as "an irreducible heuristic" (all-BCD nibbles + a plausible magnitude),
and §9/§10 repeated that framing. **This was wrong.** There is a real,
deterministic marker, and it was hiding in a field this report had
already fully decoded and dismissed as uninteresting: the time register's
own trailing two BCD digits — the "hundredths of a second" position of
its 12-digit centiseconds-since-1900 value.

### How this was found

The Alarms tab's *second* real-hardware round trip (its first, §11,
fixed the FOCAL-character bug) still failed: the user created a
`"TEST MESSAGE"` alarm repeating every 5 minutes — valid FOCAL text this
time — and `ALMCAT` again showed garbage for it and every alarm after it,
describing the symptom precisely: *"it looks as though the repeat field
... is being treated as part of the message, causing the rest of the
alarms to be mis-read."* That description is the whole story: the real
calculator decided this alarm's repeat register didn't exist, and read
its bytes as message text instead — meaning the calculator has a
different, more reliable way of deciding "is there a repeat register
here" than this project's own peek-and-guess heuristic, and this
project's *write* path wasn't setting whatever that real signal is.

Every real alarm entry across all five fixtures was re-examined for its
raw trigger-time digits:

| Fixture | Alarm | Repeats? | Time register's last 2 BCD digits |
| --- | --- | --- | --- |
| alarmtest.dm41 | HOURLY ALARM | yes | `01` |
| alarmtest.dm41 | DAILY ALARM | yes | `01` |
| alarmtest.dm41 | SINGLE ALARM | no | `00` |
| alarmtest2.dm41 | HOURLY ALARM | yes | `01` |
| alarmtest2.dm41 | DAILY ALARM | yes | `01` |
| alarmtest3.dm41 | HOURLY (A) | yes | `01` |
| alarmtest3.dm41 | LARGER ALARM MSG (B) | no | `00` |
| alarmtest3.dm41 | *(zero-length, C)* | no | `00` |
| alarmtest3.dm41 | LARGER ALARM MESSAGE,,, (D) | no | `00` |
| alarmtest3.dm41 | DAILY (E) | yes | `01` |
| repeater.dm41 | NONREPTR | no | `00` |
| repeater.dm41 | REPEATER | yes | `01` |
| 4alarmtest.dm41 | PAST DUE | no | `00` |
| 4alarmtest.dm41 | ALARM (control) | no | `00` |
| 4alarmtest.dm41 | CONDITIONAL | no | `00` |
| 4alarmtest.dm41 | REPEATING | yes | `01` |

**16 out of 16 real alarm entries, with zero exceptions**: `01` exactly
when the alarm repeats, `00` exactly when it doesn't. This is far too
clean a split to be genuine sub-second timing jitter — a real alarm set
from the keypad only ever has whole-second precision to begin with, so a
field genuinely capturing "the hundredths of a second SW happened to
execute at" would essentially never read a stable `00`/`01` split that
correlates perfectly with an unrelated property (repetition). This is a
flag hiding in a field this report mis-identified as timing precision in
§4, on the very first pass of this research back on 2026-08-20 — every
single fixture since has carried the evidence for this without anyone
(the user's tool included) noticing it.

### Why this only broke *repeating* alarms this project's own tool wrote

Before this fix, `Alarms.add_alarm()` encoded a repeating alarm's time
register byte-for-byte identically to a non-repeating one — the flag
digit was never set, always landing on `00` regardless of
`repeat_interval`. Decoding that entry back through this project's own
(then heuristic-based) reader still reported the correct
`repeat_interval`, because the old heuristic didn't look at this digit at
all — it peeked at the *next* register and guessed from its shape. That's
exactly why the bug shipped without being caught by this project's own
round-trip tests: a Python-level round trip through matching encode/
decode logic on both ends looks fine even when the actual on-the-wire
signal real hardware reads is missing. Real hardware doesn't guess from
the next register's shape at all — it just reads this flag, sees `00`,
concludes there's no repeat register, and reads the repeat register's raw
bytes as the start of the message instead. Every alarm after that point
in the buffer is then misaligned by one register, matching the user's
report exactly ("<garbage>TEST" followed by "every alarm after it
completely bogus").

One-time alarms created by the tool were unaffected throughout both
rounds of testing, which is consistent with this theory: a one-time
alarm's time register correctly encoded `00` all along (nothing ever
needed to *set* the flag for that case), so the only path that was ever
broken is create-or-edit-a-*repeating*-alarm.

### The fix

- `Alarms._decode_time()` now returns `(trigger_time, repeats)`: the
  12-digit BCD value's last two digits determine `repeats` directly
  (nonzero means yes), and `trigger_time` is truncated to whole seconds
  (the flag digit isn't real sub-second precision, so it no longer leaks
  into the decoded timestamp as a fake `.01`-second artifact — which, in
  hindsight, is visible in every "REPEATING"-style entry this report
  ever printed as a decoded time and never explained).
- `Alarms._encode_time()` takes a required `repeats` keyword and encodes
  the flag digit correctly; `add_alarm()` passes
  `repeats=repeat_interval is not None`.
- `Alarms._decode_one()` uses the flag as authoritative for "does a
  repeat register follow" — `_looks_like_repeat_register()` (§4's
  original heuristic) is kept only as a secondary sanity check: if the
  flag says a repeat register follows but the next register doesn't even
  look plausible, or there's no register left before the delimiter, that
  now raises `DM41LMemoryError` (a genuinely corrupt buffer) rather than
  silently misreading garbage as a duration or a message.
- Decoding a buffer with the flag wrong (like the *first* `badalarms.dm41`
  save, produced by the pre-fix `add_alarm()`) now reproduces the same
  misalignment real hardware hit, surfacing as a clear
  `DM41LMemoryError` once the misalignment runs into bytes that plainly
  aren't a valid time register — matching, rather than masking, what
  `ALMCAT` actually did with it.

### What this doesn't change

The buffer-level structure in §3 (header/entries/delimiter, ascending
address order, sorted by trigger time), the message-length/byte-6
findings in §4 and §5, the alarm-type up-arrow marker scheme in §9, and
the past-due high-nibble marker are all unaffected — this correction is
scoped entirely to how repeat-register *presence* is determined, which
was always a separate question from everything else in §4. §4's own
worked hex tables are still byte-for-byte accurate; only its prose
description of *how a parser tells the two cases apart* was wrong, and
only for the write direction did that wrongness ever produce a real,
uploadable bug (the read direction happened to get the right answer for
every sample this project had ever captured, by coincidence of what real
alarms look like — see the round-trip explanation above for why that
coincidence doesn't hold once the tool itself is generating entries).

**Not yet re-verified against real hardware** for the same reason as
§11: the fix has full test coverage (the flag digit's presence
confirmed byte-for-byte for both a repeating and non-repeating alarm,
`badalarms.dm41`'s known-bad buffer now correctly reproducing the
misread as an error instead of silently "working," a corrupt-buffer
synthetic case), but hasn't itself been round-tripped through a real
DM41L upload yet. Worth confirming with a repeating alarm once the user
has a chance to retry — ideally including a short, deliberately
non-round interval like the 5-minute case that first exposed this, since
that's the case most likely to have been coincidentally "fixed" by
guesswork rather than the real mechanism.
