"""
Help > FOCAL Mnemonics Reference: every instruction's display and
canonical names and the other spellings text import (and the Key
Assignment dialog) accepts, plus the character-substitution and trigraph
tables. Built at run time from memory/mnemonic_doc.py, the same source
as docs/mnemonics.md, so it always matches what the code accepts.

Not modal: it's a reference to keep open while editing a listing or
assigning keys. gui/app.py keeps at most one open and raises it if the
menu item is chosen again.

Uses ttk.Treeview rather than CTkScrollableFrame, which doesn't receive
macOS trackpad scroll events on its own (see gui/scroll_support.py).
"""

import logging
import platform

import customtkinter as ctk

from gui.tab_common import apply_row_tags, build_tree_with_scrollbar, style_treeview
from memory.mnemonic_doc import (
    mnemonic_reference_rows,
    substitution_rows,
    trigraph_rows,
)

logger = logging.getLogger(__name__)

PLATFORM_SYSTEM = platform.system()

_STYLE = "Mnemonics.Treeview"

_INSTRUCTION_COLUMNS = [
    ("display", "Display", 100, False),
    ("canonical", "Export as", 100, False),
    ("others", "Other spellings", 140, True),
    ("encoding", "Encoding", 130, False),
    ("notes", "Notes", 130, False),
]
_SUBSTITUTION_COLUMNS = [
    ("glyph", "Character", 100, False),
    ("first", "Canonical stand-in", 150, False),
    ("rest", "Also accepted", 200, True),
]
_TRIGRAPH_COLUMNS = [
    ("escape", "Escape", 100, False),
    ("symbol", "Character", 100, False),
    ("byte", "FOCAL byte", 100, True),
]

_INSTRUCTIONS_HELP = (
    "Import accepts any listed spelling, in upper or lower case. Export "
    'writes the "Export as" name. The other tabs explain where the '
    'substitution and trigraph spellings come from. Type to filter; "sigma" '
    "finds every Σ instruction."
)


class MnemonicsReferenceDialog(ctk.CTkToplevel):
    """Non-modal, read-only reference window (see module docstring)."""

    def __init__(self, master):
        super().__init__(master)
        self.title("FOCAL Mnemonics Reference")
        self.geometry("760x560")
        self.minsize(560, 360)
        if PLATFORM_SYSTEM == "Darwin" and hasattr(master, "_menubar"):
            self.config(menu=master._menubar)

        self._rows = mnemonic_reference_rows()
        stripe_bg = style_treeview(_STYLE, selectable=False)

        tabs = ctk.CTkTabview(self)
        tabs.pack(padx=12, pady=(8, 4), fill="both", expand=True)
        for name in ("Instructions", "Substitutions", "Trigraphs"):
            tabs.add(name)
        self._tabs = tabs

        # -- Instructions: filter box + table ---------------------------
        page = tabs.tab("Instructions")
        ctk.CTkLabel(
            page, text=_INSTRUCTIONS_HELP, wraplength=700, justify="left"
        ).pack(anchor="w", padx=4, pady=(4, 6))
        filter_row = ctk.CTkFrame(page, fg_color="transparent")
        filter_row.pack(fill="x", padx=4, pady=(0, 6))
        ctk.CTkLabel(filter_row, text="Filter:").pack(side="left")
        self._filter_var = ctk.StringVar()
        self._filter_entry = ctk.CTkEntry(
            filter_row, textvariable=self._filter_var, width=220
        )
        self._filter_entry.pack(side="left", padx=(6, 12))
        self._count_label = ctk.CTkLabel(filter_row, text="")
        self._count_label.pack(side="left")
        self._tree = self._build_table(page, _INSTRUCTION_COLUMNS, stripe_bg)
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())

        # -- Substitutions / Trigraphs: small fixed tables -----------------
        page = tabs.tab("Substitutions")
        ctk.CTkLabel(
            page,
            text="Each special character in a display name can be typed as "
            "any of these ASCII stand-ins, in any combination "
            "(SIGMAREG, X!=Y?, X**2).",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=4, pady=(4, 6))
        self._fill(
            self._build_table(page, _SUBSTITUTION_COLUMNS, stripe_bg),
            substitution_rows(),
        )

        page = tabs.tab("Trigraphs")
        ctk.CTkLabel(
            page,
            text="A backslash escape stands for one FOCAL character, in "
            "instruction names and in quoted ALPHA text. Escapes are "
            "case-sensitive (\\E is Σ; \\e is an error). Any byte can also be "
            "written as a backslash and three decimal digits (\\126 is Σ).",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=4, pady=(4, 6))
        self._fill(
            self._build_table(page, _TRIGRAPH_COLUMNS, stripe_bg), trigraph_rows()
        )

        ctk.CTkButton(self, text="Close", width=90, command=self.destroy).pack(
            padx=12, pady=(4, 12), anchor="e"
        )
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())

        self._apply_filter()
        self._filter_entry.focus_set()

    @staticmethod
    def _build_table(parent, columns, stripe_bg):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        tree, _ = build_tree_with_scrollbar(
            frame, columns, selectmode="none", style=_STYLE
        )
        apply_row_tags(tree, stripe_bg)
        return tree

    @staticmethod
    def _fill(tree, rows):
        tree.delete(*tree.get_children())
        for pos, values in enumerate(rows):
            tree.insert("", "end", values=values, tags=("oddrow",) if pos % 2 else ())

    def _apply_filter(self):
        wanted = self._filter_var.get().strip().upper()
        shown = [
            (r.display, r.canonical, ", ".join(r.other_spellings), r.encoding, r.notes)
            for r in self._rows
            if not wanted or wanted in r.search_text
        ]
        self._fill(self._tree, shown)
        total = len(self._rows)
        if wanted:
            self._count_label.configure(text=f"{len(shown)} of {total} instructions")
        else:
            self._count_label.configure(text=f"{total} instructions")

    def visible_displays(self):
        """The Display column of every row currently shown (for tests)."""
        return [self._tree.item(i, "values")[0] for i in self._tree.get_children()]
