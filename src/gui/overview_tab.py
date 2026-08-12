"""
Overview tab: status registers, the R00/.END. partition, and a summary of
how memory is divided up. Flags live in their own tab (gui/flags_tab.py).
"""

from tkinter import messagebox
import customtkinter as ctk

from memory import Memory, StatusRegisters, ExtendedMemory, MemoryError as DM41LMemoryError
from gui.memory_ranges import MIN_SANE_R00
from gui.scroll_support import bind_touchpad_scroll

# Registers 0x0c1-0x1ff are the addressable main-memory range (0x0c0 is Key
# Assignments); PRIMARY_DATA_END (0x1ff) is main memory's top boundary, so
# main data storage always runs from R00 up to and including this address.
PRIMARY_DATA_END = 0x1FF
# Program/key-assignment/alarm storage all live at/above this address; see
# docs/memory.md. The tool doesn't yet know how to tell program bytes apart
# from key assignments/alarms within this span -- see FUTURE_STATS below.
LOW_MEMORY_START = 0xC0

FUTURE_STATS = (
    "Coming soon: user key assignment count, alarm count, and program "
    "count. These all live below ‘.END.’ in the same region and "
    "need more reverse-engineering before this tool can tell them apart "
    "(see docs/memory.md)."
)

CARD_FG = ("gray92", "gray17")
CARD_BORDER = ("gray80", "gray28")


class OverviewTab(ctk.CTkScrollableFrame):
    """Renders a Memory object's status registers, R00/.END. partition, and
    a register-usage summary. Call `render(memory)` whenever the buffer
    changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change

        bind_touchpad_scroll(self)

        self.columnconfigure(0, weight=1, uniform="col")
        self.columnconfigure(1, weight=1, uniform="col")

        # Row 0: status registers, split into two side-by-side cards so the
        # tab makes use of the full window width instead of one narrow
        # vertical stack.
        self._stack_frame = self._make_card(0, 0, "Stack & Alpha Registers")
        self._system_frame = self._make_card(0, 1, "System & Pointer Registers")

        # Row 1: partition editor + usage summary, also side by side.
        self._partition_frame = self._make_card(1, 0, "Program / Data Partition")
        self._summary_frame = self._make_card(1, 1, "Memory Summary")

        # Row 2: placeholder for future stats, full width.
        self._future_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._future_frame.grid(
            row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(4, 12)
        )
        ctk.CTkLabel(
            self._future_frame,
            text=FUTURE_STATS,
            wraplength=760,
            justify="left",
            text_color="gray60",
        ).pack(anchor="w")

    def _make_card(self, row, column, title):
        """Creates a bordered/tinted 'card' frame at (row, column) with a
        bold title, used to visually separate sections from each other."""
        card = ctk.CTkFrame(
            self, fg_color=CARD_FG, border_width=1, border_color=CARD_BORDER,
            corner_radius=10,
        )
        card.grid(row=row, column=column, sticky="nsew", padx=8, pady=4)
        ctk.CTkLabel(
            card, text=title, font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 6))
        return card

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    # -- Top-level render ---------------------------------------------------

    def render(self, memory: Memory):
        self._memory = memory
        self._render_stack_registers()
        self._render_system_registers()
        self._render_partition()
        self._render_summary()

    # -- Status registers -----------------------------------------------

    def _clear_below_title(self, frame):
        # Row 0 holds the card title -- leave it, clear everything else.
        for widget in frame.winfo_children():
            info = widget.grid_info()
            if info and int(info.get("row", 0)) > 0:
                widget.destroy()

    def _render_grid_rows(self, frame, rows, start_row=1, columns=2):
        for i, (label, value) in enumerate(rows):
            r, c = divmod(i, columns)
            cell = ctk.CTkFrame(frame, fg_color="transparent")
            cell.grid(row=start_row + r, column=c, sticky="w", padx=10, pady=2)
            ctk.CTkLabel(cell, text=f"{label}:", width=90, anchor="w").pack(side="left")
            ctk.CTkLabel(
                cell, text=value, font=ctk.CTkFont(family="Courier"), anchor="w"
            ).pack(side="left")
        return start_row + (-(-len(rows) // columns) if rows else 0)  # ceil div

    def _render_stack_registers(self):
        self._clear_below_title(self._stack_frame)

        if self._memory is None:
            ctk.CTkLabel(self._stack_frame, text="(no memory dump loaded)").grid(
                row=1, column=0, padx=10, pady=(0, 10), sticky="w"
            )
            return

        sr = StatusRegisters(self._memory)

        stack_rows = [
            ("T", f"{sr.T().get_bcd_number():.8g}"),
            ("Z", f"{sr.Z().get_bcd_number():.8g}"),
            ("Y", f"{sr.Y().get_bcd_number():.8g}"),
            ("X", f"{sr.X().get_bcd_number():.8g}"),
            ("LastX", f"{sr.LastX().get_bcd_number():.8g}"),
        ]
        next_row = self._render_grid_rows(self._stack_frame, stack_rows, start_row=1, columns=2)

        ctk.CTkLabel(
            self._stack_frame, text="Alpha (M-P, combined):", anchor="w"
        ).grid(row=next_row, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 0))
        ctk.CTkLabel(
            self._stack_frame,
            text=repr(str(sr.alpha)),
            font=ctk.CTkFont(family="Courier"),
            anchor="w",
        ).grid(row=next_row + 1, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 4))

        mnop_rows = [
            ("M", repr(sr.M().get_ascii())),
            ("N", repr(sr.N().get_ascii())),
            ("O", repr(sr.O().get_ascii())),
            ("P", repr(sr.P().get_ascii())),
        ]
        self._render_grid_rows(
            self._stack_frame, mnop_rows, start_row=next_row + 2, columns=2
        )
        # Bottom padding on the last row.
        ctk.CTkFrame(self._stack_frame, fg_color="transparent", height=6).grid(
            row=next_row + 4, column=0
        )

    def _render_system_registers(self):
        self._clear_below_title(self._system_frame)

        if self._memory is None:
            ctk.CTkLabel(self._system_frame, text="(no memory dump loaded)").grid(
                row=1, column=0, padx=10, pady=(0, 10), sticky="w"
            )
            return

        sr = StatusRegisters(self._memory)

        rows = [
            ("Q (scratch)", sr.Q().get_hex()),
            ("F (Append)", sr.F().get_hex()),
            ("Ret. stack a", sr.a().get_hex()),
            ("Ret. stack b", sr.b().get_hex()),
            ("c (partition)", sr.c().get_hex()),
            ("d (56 flags)", sr.d().get_hex()),
            ("e", sr.e().get_hex()),
        ]
        next_row = self._render_grid_rows(self._system_frame, rows, start_row=1, columns=2)

        ctk.CTkLabel(
            self._system_frame,
            text="Registers c and d are broken out in detail in the "
            "Partition panel and the Flags tab, respectively.",
            wraplength=340,
            justify="left",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).grid(row=next_row, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 10))

    # -- R00 / .END. / SREG partition ------------------------------------

    def _render_partition(self):
        self._clear_below_title(self._partition_frame)

        if self._memory is None:
            return

        try:
            r00 = self._memory.R00()
            dot_end = self._memory.DotEnd()
            sigma_reg = self._memory.SigmaReg()
        except Exception as e:
            ctk.CTkLabel(
                self._partition_frame, text=f"Could not decode register c: {e}"
            ).grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")
            return

        if r00 < MIN_SANE_R00:
            ctk.CTkLabel(
                self._partition_frame,
                text="No dump loaded yet -- start a new buffer or load/read a dump first.",
                text_color="gray60",
            ).grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="w")
            return

        ctk.CTkLabel(self._partition_frame, text=".END. (end of program):").grid(
            row=1, column=0, sticky="w", padx=10, pady=2
        )
        ctk.CTkLabel(
            self._partition_frame,
            text=f"0x{dot_end:03x}",
            font=ctk.CTkFont(family="Courier"),
        ).grid(row=1, column=1, sticky="w", padx=10, pady=2)

        ctk.CTkLabel(self._partition_frame, text="ΣREG address:").grid(
            row=2, column=0, sticky="w", padx=10, pady=2
        )
        ctk.CTkLabel(
            self._partition_frame,
            text=f"0x{sigma_reg:03x}",
            font=ctk.CTkFont(family="Courier"),
        ).grid(row=2, column=1, sticky="w", padx=10, pady=2)

        ctk.CTkLabel(self._partition_frame, text="R00 (data register 00):").grid(
            row=3, column=0, sticky="w", padx=10, pady=(2, 10)
        )
        self._r00_var = ctk.StringVar(value=f"0x{r00:03x}")
        entry = ctk.CTkEntry(
            self._partition_frame, textvariable=self._r00_var, width=100
        )
        entry.grid(row=3, column=1, sticky="w", padx=10, pady=(2, 10))
        ctk.CTkButton(
            self._partition_frame, text="Apply", width=70, command=self._apply_r00
        ).grid(row=3, column=2, sticky="w", padx=(0, 10), pady=(2, 10))

    def _apply_r00(self):
        text = self._r00_var.get().strip()
        try:
            value = int(text, 16) if text.lower().startswith("0x") else int(text, 16)
        except ValueError:
            messagebox.showerror("Invalid R00", f"'{text}' is not a valid hex address.")
            return

        if not messagebox.askyesno(
            "Change R00",
            "This directly rewrites the R00 partition pointer. It does NOT "
            "move, clear, or resize any register contents on either side of "
            "the new boundary -- it can expose stale program bytes as data, "
            "or hide real data registers behind the new program-memory "
            "boundary. Continue?",
        ):
            return

        try:
            self._memory.set_R00(value)
        except ValueError as e:
            messagebox.showerror("Invalid R00", str(e))
            return

        self._notify_change()
        self.render(self._memory)

    # -- Memory usage summary ---------------------------------------------

    def _render_summary(self):
        self._clear_below_title(self._summary_frame)

        if self._memory is None:
            return

        try:
            r00 = self._memory.R00()
            dot_end = self._memory.DotEnd()
        except Exception:
            r00 = dot_end = None

        if r00 is not None and r00 < MIN_SANE_R00:
            r00 = None  # No real dump loaded yet -- see gui/memory_ranges.py.

        try:
            xm = ExtendedMemory(self._memory, address_range=[0x40, 0x3FF])
            xm_count = len(xm.list_files())
            xm_text = str(xm_count)
        except DM41LMemoryError as e:
            xm_text = f"could not be listed ({e})"

        rows = []
        if r00 is not None:
            reserved = (PRIMARY_DATA_END + 1) - r00
            consumed = r00 - dot_end
            available = dot_end - LOW_MEMORY_START
            rows.append(
                ("Main data registers reserved", f"{reserved} (R00-0x{PRIMARY_DATA_END:03x})")
            )
            rows.append(("Program storage consumed", f"{consumed} registers"))
            rows.append(
                (
                    "Free below program memory",
                    f"{available} registers (approx. -- may still include "
                    "key assignments/alarms, see note below)",
                )
            )
        rows.append(("Extended-memory files", xm_text))

        for i, (label, value) in enumerate(rows, start=1):
            ctk.CTkLabel(self._summary_frame, text=f"{label}:", anchor="w").grid(
                row=i, column=0, sticky="nw", padx=10, pady=2
            )
            ctk.CTkLabel(
                self._summary_frame, text=value, anchor="w", justify="left",
                wraplength=280,
            ).grid(row=i, column=1, sticky="w", padx=10, pady=2)
        ctk.CTkFrame(self._summary_frame, fg_color="transparent", height=6).grid(
            row=len(rows) + 1, column=0
        )
