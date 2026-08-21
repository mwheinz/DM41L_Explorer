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
from tkinter import ttk
import customtkinter as ctk

from memory import Memory
from gui.tab_common import build_tab_header, MONOSPACE_FONT_FAMILY, stripe_bg_color

logger = logging.getLogger(__name__)

# Selected-row highlight -- deliberately a local copy of
# data_registers_tab.py's/xm_files_tab.py's own SELECTED_ROW_BG/FG (same
# values), not a shared import; see this tab's _style_treeview() docstring
# for why it needs its own separately-named ttk style too.
SELECTED_ROW_BG = "#1f6aa5"
SELECTED_ROW_FG = "#ffffff"

# Distinct ttk style names for this tab's Treeview/scrollbar -- see
# _style_treeview()'s docstring for why these must NOT be the "Treeview"/
# "XMFiles.Treeview" style names the other two Treeview-based tabs use.
_TREE_STYLE = "Programs.Treeview"
_SCROLLBAR_STYLE = "Programs.Vertical.TScrollbar"


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

        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._stripe_bg = self._style_treeview()

        self._tree = ttk.Treeview(
            table_frame,
            columns=("kind", "name", "header", "distance", "key_assignment"),
            show="headings",
            selectmode="browse",
            style=_TREE_STYLE,
        )
        for col, text, width, stretch in [
            ("kind", "Type", 70, False),
            ("name", "Name", 180, True),
            ("header", "Address", 120, False),
            ("distance", "Distance", 120, False),
            ("key_assignment", "Key Assignment", 160, False),
        ]:
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor="w", stretch=stretch)
        self._tree.tag_configure("oddrow", background=self._stripe_bg)
        self._tree.tag_configure(
            "selectedrow", background=SELECTED_ROW_BG, foreground=SELECTED_ROW_FG
        )

        vsb = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self._tree.yview,
            style=_SCROLLBAR_STYLE,
        )
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_selected)

    def _style_treeview(self) -> str:
        """Rough dark/light theming for this tab's native table (font,
        colors, scrollbar look) -- see gui/data_registers_tab.py's/
        gui/xm_files_tab.py's own `_style_treeview()` for the original
        version of this and why a native ttk.Treeview/ttk.Scrollbar is
        used here instead of CTk widgets at all.

        This tab configures its OWN ttk style names (`_TREE_STYLE` /
        `_SCROLLBAR_STYLE` above), not the "Treeview" or "XMFiles.*"
        names the other two Treeview-based tabs use -- ttk styles are
        global and shared by name, not per-widget-instance, so any two
        Treeview-using tabs that configured the *same* style name with
        different font/color choices would silently fight over it,
        whichever tab styled itself last winning for every table using
        that name (see xm_files_tab.py's `_style_treeview()` docstring,
        GitHub issue #21, for the full story of catching this before it
        became a live bug). Three tabs now means three distinct names.

        Returns the current stripe background color, for the caller to
        `tag_configure("oddrow", ...)` -- unlike the style calls above,
        tag colors are per-widget-instance, not shared."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception as e:
            # "clam" ships with every Tcl/Tk this project supports; this
            # is a defensive fallback, not something expected to fire --
            # see the identical pattern in hex_view_tab.py.
            logger.debug("Could not switch ttk theme to 'clam': %s", e)
        dark = ctk.get_appearance_mode() == "Dark"
        bg = stripe_bg_color()
        field_bg = "#242424" if dark else "#ffffff"
        fg = "#e6e6e6" if dark else "#1a1a1a"
        ui_font = ctk.ThemeManager.theme["CTkFont"]
        font = (MONOSPACE_FONT_FAMILY, ui_font["size"])
        heading_font = (ui_font["family"], ui_font["size"], "bold")
        style.configure(
            _TREE_STYLE,
            background=field_bg,
            fieldbackground=field_bg,
            foreground=fg,
            rowheight=22,
            borderwidth=0,
            font=font,
        )
        style.configure(
            f"{_TREE_STYLE}.Heading", background=bg, foreground=fg, font=heading_font
        )
        # Kept as a harmless fallback even though the hand-managed
        # "selectedrow" tag (see _on_tree_selected()) is what actually
        # does the work -- a per-item tag's background silently overrides
        # this "selected" state map in ttk.Treeview regardless of what
        # this says, a long-standing Tk behavior. See
        # data_registers_tab.py's _on_tree_selected() docstring (GitHub
        # issue #22) for the full story.
        style.map(_TREE_STYLE, background=[("selected", SELECTED_ROW_BG)])

        # Approximate CTkScrollableFrame's own scrollbar look (a slim,
        # borderless thumb with no up/down arrow buttons) -- same layout
        # the other two Treeview-based tabs use, just under this tab's
        # own style name.
        trough = field_bg
        thumb = "#565b5e" if dark else "#c0c0c0"
        thumb_active = "#6e7173" if dark else "#a6a6a6"
        style.layout(
            _SCROLLBAR_STYLE,
            [
                (
                    "Vertical.Scrollbar.trough",
                    {
                        "sticky": "ns",
                        "children": [
                            (
                                "Vertical.Scrollbar.thumb",
                                {"expand": "1", "sticky": "nswe"},
                            )
                        ],
                    },
                )
            ],
        )
        style.configure(
            _SCROLLBAR_STYLE,
            background=thumb,
            troughcolor=trough,
            bordercolor=trough,
            relief="flat",
            borderwidth=0,
        )
        style.map(
            _SCROLLBAR_STYLE,
            background=[("active", thumb_active), ("pressed", thumb_active)],
        )
        return bg

    def refresh_theme(self):
        """Re-applies theme-dependent ttk styling/colors after
        ctk.set_appearance_mode() changes elsewhere (e.g. Preferences) --
        see gui/data_registers_tab.py's identical method for why this is
        needed at all (CustomTkinter's theme engine has no hook into
        ttk). This tab used to not need an equivalent call (its old
        CTkScrollableFrame render() recomputed stripe color fresh every
        time) -- now that it's a ttk.Treeview too, it does."""
        self._stripe_bg = self._style_treeview()
        self._tree.tag_configure("oddrow", background=self._stripe_bg)
        self._tree.tag_configure(
            "selectedrow", background=SELECTED_ROW_BG, foreground=SELECTED_ROW_FG
        )

    def _on_tree_selected(self, event=None):  # pylint: disable=unused-argument
        """Gives the selected row a visible highlight, the same way (and
        for the same reason) as data_registers_tab.py's/xm_files_tab.py's
        own `_on_tree_selected()` -- see either method's docstring for
        the full GitHub issue #22 story. Purely cosmetic here (this tab
        has no selection-driven action), kept for visual consistency with
        the other two tables."""
        for pos, iid in enumerate(self._tree.get_children()):
            if "selectedrow" in self._tree.item(iid, "tags"):
                self._tree.item(iid, tags=("oddrow",) if pos % 2 else ())

        selection = self._tree.selection()
        if selection:
            self._tree.item(selection[0], tags=("selectedrow",))

    def render(self, memory: Memory):
        self._memory = memory
        self._tree.delete(*self._tree.get_children())

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
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
