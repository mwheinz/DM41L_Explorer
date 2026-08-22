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
it, so this deliberately does NOT try to group entries into programs -- it
shows the raw chain, same as CAT 1 would list it, with each entry's Type
(LBL/END/.END.) and the raw byte distance its own marker reports onward to
the next chain link. That distance is NOT a program size -- see
ProgramInfo's docstring -- it's shown as-is to help research whether/how
it reconciles with CAT 1's reported program byte lengths. The `.END.` row
(the newest entry, when present) matters for that comparison too: an
earlier version of this tool silently dropped it, which turned out to hide
bytes CAT 1 counts as part of the newest program.

Uses a native ttk.Treeview rather than one CustomTkinter widget per row --
the same performance/consistency fix as gui/data_registers_tab.py and
gui/xm_files_tab.py (see either module's docstring for the full story;
GitHub issues #21/#22). This tab is read-only, so unlike those two there's
no per-row action button, no double-click-to-edit, and no selection-driven
enable/disable -- the row highlight is purely a "you can see which row you
clicked" visual nicety, matching the other tabs' look for consistency.
"""

import logging
import customtkinter as ctk

from memory import Memory
from gui.tab_common import (
    build_tab_header,
    build_tab_treeview,
    build_caption_label,
    style_treeview,
    apply_row_tags,
    highlight_selected_row,
    clear_tree_for_render,
)

logger = logging.getLogger(__name__)

# Distinct ttk style name for this tab's Treeview/scrollbar -- see
# gui/tab_common.py's `style_treeview()` docstring for why this must NOT
# be the "Treeview"/"XMFiles.Treeview" style names the other two
# Treeview-based tabs use.
_TREE_STYLE = "Programs.Treeview"

_TREE_COLUMNS = [
    ("kind", "Type", 70, False),
    ("name", "Name", 180, True),
    ("header", "Address", 120, False),
    ("distance", "Distance", 120, False),
    ("key_assignment", "Key Assignment", 160, False),
]


class ProgramTab(ctk.CTkFrame):
    """Renders the program-memory global chain for a Memory object. Call
    `render(memory)` whenever the buffer changes."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None

        _, self._header_label = build_tab_header(self)

        self._caption = build_caption_label(
            self,
            "The raw global chain in program memory: every LBL header, "
            "END marker, and the permanent .END. marker itself, in the "
            "order CAT 1 would list them. This is still-researched "
            "territory (see docs/program.md) -- entries are NOT grouped "
            "into programs (a single END can have zero, one, or several "
            "LBLs chained to it), and Distance is each entry's own raw "
            "chain-marker distance, not a program size.",
        )

        _, self._tree = build_tab_treeview(self, _TREE_COLUMNS, style=_TREE_STYLE)

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_selected)

    def refresh_theme(self):
        """Re-applies theme-dependent ttk styling/colors after
        ctk.set_appearance_mode() changes elsewhere (e.g. Preferences) --
        see gui/data_registers_tab.py's identical method for why this is
        needed at all (CustomTkinter's theme engine has no hook into
        ttk). This tab used to not need an equivalent call (its old
        CTkScrollableFrame render() recomputed stripe color fresh every
        time) -- now that it's a ttk.Treeview too, it does."""
        self._stripe_bg = style_treeview(_TREE_STYLE)
        apply_row_tags(self._tree, self._stripe_bg)

    def _on_tree_selected(self, event=None):  # pylint: disable=unused-argument
        """Gives the selected row a visible highlight, the same way (and
        for the same reason) as gui/tab_common.py's
        `highlight_selected_row()` docstring (GitHub issue #22) explains.
        Purely cosmetic here (this tab has no selection-driven action),
        kept for visual consistency with the other two tables."""
        highlight_selected_row(self._tree)

    def render(self, memory: Memory):
        self._memory = memory
        if clear_tree_for_render(self._tree, self._header_label, memory):
            return

        try:
            programs = memory.list_programs()
        except Exception as e:
            logger.warning("Could not list programs: %s", e)
            self._header_label.configure(text=f"Could not list programs: {e}")
            return

        if not programs:
            self._header_label.configure(text="Program memory entries: 0")
            return

        self._header_label.configure(text=f"Program memory entries: {len(programs)}")

        for pos, program in enumerate(programs):
            self._tree.insert(
                "",
                "end",
                iid=str(pos),
                values=(
                    program.kind,
                    program.display_name,
                    program.address_label,
                    program.distance_label,
                    self._key_assignment_text(program),
                ),
                tags=("oddrow",) if pos % 2 else (),
            )

    @staticmethod
    def _key_assignment_text(program) -> str:
        # Only global-label entries have a key-assignment byte at all --
        # a plain END marker has nothing to show here.
        if not program.is_named:
            return ""
        if program.key_assignment == 0:
            return "unassigned"
        return f"0x{program.key_assignment:02x}"
