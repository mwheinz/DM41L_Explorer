"""
Programs tab: a read-only listing of program memory's "global chain" --
every global label header (LBL), plain END marker, and the one permanent
`.END.` marker itself, found walking backward from `.END.` toward R00.
See docs/program.md sec 5 for the full derivation (reverse-engineered from
sample dumps and Wickes' "Synthetic Programming on the HP-41C", section
2C) and memory.py's Memory.list_programs() / ProgramInfo for the
implementation this renders.

Each row is one independent chain link, not "a program": the user's own
testing found a single END can have zero, one, or several LBLs chained to
it, so this deliberately does NOT try to group entries into programs --
it shows the raw chain, same as CAT 1 would list it, with each entry's
Type (LBL/END/.END.) and the raw byte distance its own marker reports
onward to the next chain link. That distance is NOT a program size -- see
ProgramInfo's docstring -- it's shown as-is to help research whether/how
it reconciles with CAT 1's reported program byte lengths. The `.END.` row
(the newest entry, when present) matters for that comparison too: an
earlier version of this tool silently dropped it, which turned out to
hide bytes CAT 1 counts as part of the newest program.

Modeled on gui/xm_files_tab.py's layout (status header + scrollable table),
but view-only: there's no way yet to decode a program's actual instruction
bytes, so there's nothing here to edit, add, or remove.
"""

import customtkinter as ctk

from memory import Memory
from gui.scroll_support import bind_touchpad_scroll
from gui.tab_common import build_tab_header, MONOSPACE_FONT_FAMILY


class ProgramTab(ctk.CTkFrame):
    """Renders the program-memory global chain for a Memory object. Call
    `render(memory)` whenever the buffer changes."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None

        _, self._header_label = build_tab_header(self)

        self._caption = ctk.CTkLabel(
            self,
            text=(
                "The raw global chain in program memory: every LBL header, "
                "END marker, and the permanent .END. marker itself, in the "
                "order CAT 1 would list them. This is still-researched "
                "territory (see docs/program.md) -- entries are NOT grouped "
                "into programs (a single END can have zero, one, or several "
                "LBLs chained to it), and Distance is each entry's own raw "
                "chain-marker distance, not a program size."
            ),
            font=ctk.CTkFont(size=12),
            text_color="gray60",
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self._caption.pack(fill="x", padx=8, pady=(0, 4))

        self._table = ctk.CTkScrollableFrame(self)
        self._table.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for col, weight in enumerate([0, 1, 0, 0, 0]):
            self._table.grid_columnconfigure(col, weight=weight)
        bind_touchpad_scroll(self._table)

    def render(self, memory: Memory):
        self._memory = memory
        for widget in self._table.winfo_children():
            widget.destroy()

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
            return

        try:
            programs = memory.list_programs()
        except Exception as e:
            self._header_label.configure(text=f"Could not list programs: {e}")
            return

        if not programs:
            self._header_label.configure(text="Program memory entries: 0")
            return

        self._header_label.configure(text=f"Program memory entries: {len(programs)}")

        headers = ["Type", "Name", "Header Address", "Distance", "Key Assignment"]
        for col, text in enumerate(headers):
            ctk.CTkLabel(
                self._table, text=text, font=ctk.CTkFont(weight="bold")
            ).grid(row=0, column=col, sticky="w", padx=6, pady=4)

        for i, program in enumerate(programs, start=1):
            self._render_row(program, row=i)

    def _render_row(self, program, row: int):
        row_color = None if program.is_named else "gray60"

        ctk.CTkLabel(
            self._table,
            text=program.kind,
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
            anchor="w",
            text_color=row_color,
        ).grid(row=row, column=0, sticky="w", padx=6, pady=1)

        ctk.CTkLabel(
            self._table, text=program.display_name, anchor="w", text_color=row_color
        ).grid(row=row, column=1, sticky="w", padx=6, pady=1)

        ctk.CTkLabel(
            self._table,
            text=program.address_label,
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
            anchor="w",
        ).grid(row=row, column=2, sticky="w", padx=6, pady=1)

        ctk.CTkLabel(
            self._table,
            text=program.distance_label,
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
            anchor="w",
        ).grid(row=row, column=3, sticky="w", padx=6, pady=1)

        ctk.CTkLabel(
            self._table,
            text=self._key_assignment_text(program),
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
            anchor="w",
        ).grid(row=row, column=4, sticky="w", padx=6, pady=1)

    @staticmethod
    def _key_assignment_text(program) -> str:
        # Only global-label entries have a key-assignment byte at all --
        # a plain END marker has nothing to show here.
        if not program.is_named:
            return ""
        if program.key_assignment == 0:
            return "unassigned"
        return f"0x{program.key_assignment:02x}"
