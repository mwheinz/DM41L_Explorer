"""
Key Assignments tab: two synchronized keypad-shaped grids ("HP41" and
"DM41L", docs/key_assignments.md sec 6 item 4) for viewing and editing
built-in/peripheral key assignments. Both grids render the exact same 34
assignable keys, just laid out to match a different physical keyboard --
an edit made through either grid is immediately reflected in the other,
since both are just two different arrangements of the same
Memory.get_key_assignment()/set_key_assignment()/delete_key_assignment()
calls.

Scope for this first pass (explicitly out of scope, per the project's own
request): import, export, and global-label (user program) key assignments
-- see docs/key_assignments.md sec 4.6 and sec 6 items 1-3. Only built-in/
peripheral assignments (sec 4.2) are shown/editable here; a key assigned
only via a global label (ASN "PROGNAME") shows as unassigned in this tab
even though its KEYFLAGS bit is set -- Memory.list_programs()'s
`key_assignment` field is the only place that's currently visible (the
Programs tab).

Unlike every other tab's render(), this one does NOT destroy and rebuild
its widgets on every call. Every other tab's row count scales with actual
data (XM files, programs, ...), so a full rebuild is cheap; this tab
always has the same fixed 34*2 = 68 buttons per grid regardless of how
many keys are actually assigned, and CustomTkinter widget construction
(each CTkButton draws its own rounded-rect image) is expensive enough
that destroying and recreating ~270 widgets on every single key edit was
visibly slow -- the whole tab would go blank for a couple of seconds
before redrawing. The grids are now built once and subsequently only
their existing buttons' text/color are updated in place via configure().
"""

import logging
import customtkinter as ctk

from memory import Memory
from gui.key_assignment_edit_dialog import KeyAssignmentEditDialog
from gui.scroll_support import bind_touchpad_scroll
from gui.tab_common import build_tab_header

logger = logging.getLogger(__name__)

# Physical keyboard layouts (docs/key_assignments.md sec 6 item 4): each
# row is a list of cells, where an int is an assignable key number (`MN`
# notation, sec 2) and a str is a non-assignable physical key's label
# (empty string for a genuinely blank/spare position). Both layouts cover
# the same 34 assignable keys -- see the docs section for why they're laid
# out differently (the DM41L's actual compact keyboard relocates several
# keys relative to the classic HP-41's row layout).
HP41_LAYOUT = [
    [11, 12, 13, 14, 15],
    [21, 22, 23, 24, 25],
    ["SHIFT", 32, 33, 34, 35],
    [41, 41, 42, 43, 44],
    [51, 52, 53, 54],
    [61, 62, 63, 64],
    [71, 72, 73, 74],
    [81, 82, 83, 84],
]

DM41L_LAYOUT = [
    [11, 12, 13, 14, 15, 42, 51, 52, 53, 54],
    [21, 22, 23, 24, 25, 43, 61, 62, 63, 64],
    ["USR", "PGM", 32, 35, 44, 41, 71, 72, 73, 74],
    ["ON", "SHIFT", "ALPHA", 33, 34, 41, 81, 82, 83, 84],
]

CARD_FG = ("gray92", "gray17")
CARD_BORDER = ("gray80", "gray28")
UNASSIGNED_TEXT = "gray50"
UNASSIGNED_FG = ("gray85", "gray24")

# Sized for the actual function-name lengths in memory/functions.py (median
# 4 characters, longest 7, e.g. "RCLFLAG") rather than the widest string
# that could ever appear -- a handful of long names may render a touch
# wider than this minimum, which is fine; a fixed width big enough for the
# rare 7-character name made every column far wider than it needed to be
# and pushed the DM41L grid's 10 columns past the visible area.
KEY_BUTTON_WIDTH = 62
KEY_BUTTON_HEIGHT = 20
KEY_BUTTON_FONT_SIZE = 14


class KeyAssignmentsTab(ctk.CTkFrame):
    """Renders the HP41/DM41L key-assignment grids for a Memory object.
    Call `render(memory)` whenever the buffer changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change
        self._grids_built = False
        # (key_number, shifted) -> list of CTkButton, populated once by
        # _build_grid() and reused by _refresh_buttons() from then on. A
        # list, not a single button, because the HP41 and DM41L layouts
        # both reference the same 34 key numbers (just arranged
        # differently) -- each key number maps to one button per grid, and
        # both need to stay in sync.
        self._key_buttons = {}

        _, self._header_label = build_tab_header(self)

        self._caption = ctk.CTkLabel(
            self,
            text=(
                "Click a key's unshifted or shifted function to assign, "
                "reassign, or delete it. This covers built-in/peripheral "
                "assignments only (docs/key_assignments.md sec 4.2) -- "
                "import, export, and program (global-label) assignments "
                "aren't handled here yet."
            ),
            font=ctk.CTkFont(size=12),
            text_color="gray60",
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self._caption.pack(fill="x", padx=8, pady=(0, 4))

        self._scroll = ctk.CTkScrollableFrame(self)
        self._scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        bind_touchpad_scroll(self._scroll)

        ctk.CTkLabel(
            self._scroll, text="HP41", font=ctk.CTkFont(weight="bold", size=14),
        ).pack(anchor="w", padx=4, pady=(4, 2))
        self._hp41_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._hp41_frame.pack(anchor="w", padx=4, pady=(0, 16))

        ctk.CTkLabel(
            self._scroll, text="DM41L", font=ctk.CTkFont(weight="bold", size=14),
        ).pack(anchor="w", padx=4, pady=(4, 2))
        self._dm41l_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._dm41l_frame.pack(anchor="w", padx=4, pady=(0, 4))

        # A throwaway button, never packed/gridded, just to read back
        # CustomTkinter's own theme defaults for fg_color/text_color --
        # needed so an "unassigned" cell's overridden colors can be reset
        # to "whatever a normal button looks like" rather than a
        # hard-coded guess that could drift from the active theme.
        probe = ctk.CTkButton(self)
        self._default_fg_color = probe.cget("fg_color")
        self._default_text_color = probe.cget("text_color")
        probe.destroy()

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    def render(self, memory: Memory):
        self._memory = memory

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
            if self._grids_built:
                self._teardown_grids()
            return

        try:
            count = len(memory.list_key_assignments())
        except Exception as e:
            logger.warning("Could not list key assignments: %s", e)
            self._header_label.configure(text=f"Could not list key assignments: {e}")
            return

        self._header_label.configure(text=f"Key assignments: {count}")

        if not self._grids_built:
            self._build_grid(self._hp41_frame, HP41_LAYOUT)
            self._build_grid(self._dm41l_frame, DM41L_LAYOUT)
            self._grids_built = True

        self._refresh_buttons()

    def _teardown_grids(self):
        for widget in self._hp41_frame.winfo_children():
            widget.destroy()
        for widget in self._dm41l_frame.winfo_children():
            widget.destroy()
        self._key_buttons = {}
        self._grids_built = False

    # -- Grid construction (once) -------------------------------------------

    def _build_grid(self, parent, layout):
        for row_index, row in enumerate(layout):
            for col_index, cell in enumerate(row):
                if isinstance(cell, int):
                    self._build_key_cell(parent, cell, row_index, col_index)
                else:
                    self._build_static_cell(parent, cell, row_index, col_index)

    def _build_key_cell(self, parent, key_number: int, row: int, col: int):
        cell = ctk.CTkFrame(
            parent, fg_color=CARD_FG, border_width=1, border_color=CARD_BORDER,
            corner_radius=6,
        )
        cell.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")

        ctk.CTkLabel(
            cell, text=f"{key_number:02d}", font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(pady=(0, 0))

        for shifted in (False, True):
            btn = ctk.CTkButton(
                cell,
                text="",
                width=KEY_BUTTON_WIDTH,
                height=KEY_BUTTON_HEIGHT,
                font=ctk.CTkFont(size=KEY_BUTTON_FONT_SIZE),
                command=lambda k=key_number, s=shifted: self._edit_key(k, s),
            )
            btn.pack(padx=3, pady=(0, 3 if shifted else 1))
            self._key_buttons.setdefault((key_number, shifted), []).append(btn)

    def _build_static_cell(self, parent, label: str, row: int, col: int):
        cell = ctk.CTkFrame(
            parent, fg_color=CARD_FG, border_width=1, border_color=CARD_BORDER,
            corner_radius=6,
        )
        cell.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
        ctk.CTkLabel(
            cell, text=label, text_color="gray50", font=ctk.CTkFont(size=10),
            width=KEY_BUTTON_WIDTH, height=44,
        ).pack(expand=True)

    # -- Refresh (every render) ----------------------------------------------

    def _refresh_buttons(self):
        for (key_number, shifted), btns in self._key_buttons.items():
            assignment = self._memory.get_key_assignment(key_number, shifted)
            prefix = "⇧" if shifted else ""
            if assignment:
                text = f"{prefix}{assignment['name']}"
                fg_color = self._default_fg_color
                text_color = self._default_text_color
            else:
                text = f"{prefix}--"
                fg_color = UNASSIGNED_FG
                text_color = UNASSIGNED_TEXT
            for btn in btns:
                btn.configure(text=text, fg_color=fg_color, text_color=text_color)

    # -- Editing ------------------------------------------------------------

    def _edit_key(self, key_number: int, shifted: bool):
        assignment = self._memory.get_key_assignment(key_number, shifted)

        def save(function_bytes):
            self._memory.set_key_assignment(key_number, shifted, function_bytes)
            logger.info(
                "Key %02d (%s) assigned: %s",
                key_number, "shifted" if shifted else "unshifted", function_bytes,
            )
            self._notify_change()
            self._refresh_buttons()
            self._header_label.configure(
                text=f"Key assignments: {len(self._memory.list_key_assignments())}"
            )

        def delete():
            self._memory.delete_key_assignment(key_number, shifted)
            logger.info(
                "Key %02d (%s) assignment deleted",
                key_number, "shifted" if shifted else "unshifted",
            )
            self._notify_change()
            self._refresh_buttons()
            self._header_label.configure(
                text=f"Key assignments: {len(self._memory.list_key_assignments())}"
            )

        KeyAssignmentEditDialog(self, key_number, shifted, assignment, save, delete)
