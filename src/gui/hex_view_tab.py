"""
Hex View tab: a read-only, color-coded hex dump of the entire addressable
memory space (0x000-0x2ff), one row per register.

This is a map, not an editor -- no selection handling, no double-click, no
edit dialog. Each row's background color shows which memory region that
register belongs to (see docs/memory.md section 3 for the region table),
so gaps, the program/data split, and the two extended-memory blocks are all
visible at a glance without cross-referencing addresses by hand.

Like Data Registers, this uses a native ttk.Treeview rather than one
CustomTkinter widget per row -- the full address space is up to 768
registers, well into the range where CTk widget construction cost matters
(see gui/data_registers_tab.py's module docstring for the measured
numbers). Unlike Data Registers, this is a single table rather than a
left/right split: a hex dump reads more naturally as one continuous
top-to-bottom listing, and the whole point here is seeing color bands
transition as you scroll through it.
"""

import logging
from tkinter import ttk
import customtkinter as ctk

from memory import Memory
from gui.memory_ranges import MIN_SANE_R00
from gui.tab_common import build_tab_header, MONOSPACE_FONT_FAMILY

logger = logging.getLogger(__name__)

# The full addressable range this tab displays. Per docs/memory.md section
# 3/4: Status Registers 0x000-0x00f, an unused/"void" gap 0x010-0x03f,
# Extended Memory #0 0x040-0x0bf, Main Memory 0x0c0-0x1ff (itself split
# further below, when a dump with a sane R00/.END. is loaded), Extended
# Memory #1 0x200-0x2ef. This covers the full address space of the HP41CX
# calculator and the DM41L emulator.
DISPLAY_START = 0x000
DISPLAY_END = 0x2EF

STATUS_END = 0x00F
UNUSED_END = 0x03F
XM0_END = 0x0BF
MAIN_MEMORY_START = 0x0C0
MAIN_MEMORY_END = 0x1FF
XM1_START = 0x200
XM1_END = 0x2EF

# One entry per region this tab can color. `light`/`dark` are the row
# background tints for CTk's two appearance modes -- picked distinct enough
# to tell apart at a glance but not so saturated they fight with the
# selection highlight or make the monospace text hard to read. Order here
# is also legend display order.
REGIONS = [
    ("status", "Status Registers", "#cfe0f5", "#39507a"),
    ("unused", "Unused / Free", "#e8e8e8", "#3a3a3a"),
    ("xm", "XM", "#d7f0dc", "#3f6b4f"),
    ("key", "Key Assignments", "#e6d9f5", "#6b4f8c"),
    ("alarms", "Alarms", "#f5d9df", "#7a3f52"),
    ("program", "User Programs", "#f5e3c2", "#8c6b2f"),
    ("data", "Data Memory", "#c9f0ee", "#2f7a7a"),
    ("nonexistent", "Inaccessible", "#d0d0d0", "#242424"),
]
REGION_LABELS = {key: label for key, label, _, _ in REGIONS}


def _classify(
    addr: int,
    r00: int,
    dot_end: int,
    has_partition: bool,
    key_assignments_end: int,
    alarms_end: int,
) -> str:
    """Returns the region key for a single address. `has_partition` is
    False when no real dump is loaded yet (R00 below MIN_SANE_R00) -- in
    that case Main Memory is shown as one undivided band rather than
    guessing at a program/data split from meaningless R00/.END. values.
    `key_assignments_end` (Memory.key_assignments_end()) and `alarms_end`
    (Memory.alarms_end()) are both independent of R00/.END. sanity --
    the former is found by scanning for the 0xF0 marker byte Key
    Assignment registers start with, the latter by reading the Alarms
    buffer's own header (see alarms_end()'s docstring) -- so both are
    honored even when `has_partition` is False."""
    if DISPLAY_START <= addr <= STATUS_END:
        return "status"
    if addr <= UNUSED_END:
        return "nonexistent"
    if addr <= XM0_END:
        return "xm"
    if addr <= MAIN_MEMORY_END:
        if addr < key_assignments_end:
            return "key"
        if addr < alarms_end:
            return "alarms"
        if not has_partition:
            return "unused"
        if addr < dot_end:
            return "unused"
        if addr < r00:
            return "program"
        return "data"
    if addr <= XM1_END:
        return "xm"
    return "nonexistent"


class HexViewTab(ctk.CTkFrame):
    """Renders a read-only, region-colored hex dump of the full address
    space for a Memory object. Call `render(memory)` whenever the buffer
    changes."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        # (light_color, dark_color, swatch_label) per legend entry, in
        # REGIONS order -- stashed so refresh_theme() can recolor the
        # existing swatches in place rather than tearing the legend down
        # and rebuilding it (which would also lose its packed position
        # between the header and the table -- see refresh_theme()).
        self._legend_swatches = []

        _, self._header_label = build_tab_header(self)
        self._build_legend()

        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._style_treeview()
        self._tree = self._build_tree(table_frame)
        self._apply_region_tags()

    def _build_legend(self):
        """A row of small color swatches + labels so the row colors below
        are self-explanatory without a separate reference doc."""
        legend = ctk.CTkFrame(self, fg_color="transparent")
        legend.pack(fill="x", padx=8, pady=(0, 6))
        dark = ctk.get_appearance_mode() == "Dark"
        for _, label, light, dark_color in REGIONS:
            color = dark_color if dark else light
            chip = ctk.CTkFrame(legend, fg_color="transparent")
            chip.pack(side="left", padx=(0, 14), pady=2)
            swatch = ctk.CTkLabel(
                chip,
                text="",
                fg_color=color,
                width=14,
                height=14,
                corner_radius=3,
            )
            swatch.pack(side="left", padx=(0, 5))
            ctk.CTkLabel(chip, text=label, font=ctk.CTkFont(size=11)).pack(side="left")
            self._legend_swatches.append((light, dark_color, swatch))

    def _apply_region_tags(self):
        for key, _, _, _ in REGIONS:
            self._tree.tag_configure(key, background=self._region_bg[key])

    def _build_tree(self, parent) -> ttk.Treeview:
        columns = ("addr", "hex", "ascii", "region")
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="none")
        for col, text, width, stretch in [
            ("addr", "Addr", 70, False),
            ("hex", "Hex", 240, False),
            ("ascii", "ASCII", 90, False),
            ("region", "Region", 260, True),
        ]:
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w", stretch=stretch)

        vsb = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=tree.yview,
            style="DM41L.Vertical.TScrollbar",
        )
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        return tree

    def _style_treeview(self):
        """Same dark/light ttk theming approach as Data Registers (see that
        module's `_style_treeview` docstring for why ttk needs this at
        all) -- kept as its own copy rather than a shared helper since the
        two tabs configure different tag sets (region colors here,
        odd/even zebra striping there) on top of the same base style
        names, and a shared style object is already how ttk works (the
        style names/registration are process-global, not per-widget)."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception as e:
            # "clam" ships with every Tcl/Tk this project supports; this
            # is a defensive fallback, not something expected to fire.
            logger.debug("Could not switch ttk theme to 'clam': %s", e)
        dark = ctk.get_appearance_mode() == "Dark"
        bg = "#2b2b2b" if dark else "#f4f4f4"
        field_bg = "#242424" if dark else "#ffffff"
        fg = "#e6e6e6" if dark else "#1a1a1a"
        self._region_bg = {
            key: (dark_color if dark else light)
            for key, _, light, dark_color in REGIONS
        }
        ui_font = ctk.ThemeManager.theme["CTkFont"]
        font = (MONOSPACE_FONT_FAMILY, ui_font["size"])
        heading_font = (ui_font["family"], ui_font["size"], "bold")
        style.configure(
            "Treeview",
            background=field_bg,
            fieldbackground=field_bg,
            foreground=fg,
            rowheight=22,
            borderwidth=0,
            font=font,
        )
        style.configure(
            "Treeview.Heading", background=bg, foreground=fg, font=heading_font
        )

        # No selection highlighting -- selectmode="none" above already
        # disables it functionally, but without this map a stray click can
        # still leave ttk's own focus/active-row indicator visible, which
        # would look like a broken "clickable" affordance on a tab that's
        # explicitly not interactive.
        style.map("Treeview", background=[], foreground=[])

        trough = field_bg
        thumb = "#565b5e" if dark else "#c0c0c0"
        thumb_active = "#6e7173" if dark else "#a6a6a6"
        style.layout(
            "DM41L.Vertical.TScrollbar",
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
            "DM41L.Vertical.TScrollbar",
            background=thumb,
            troughcolor=trough,
            bordercolor=trough,
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "DM41L.Vertical.TScrollbar",
            background=[("active", thumb_active), ("pressed", thumb_active)],
        )

    def refresh_theme(self):
        """Re-applies every theme-dependent color after
        ctk.set_appearance_mode() changes elsewhere (e.g. Preferences --
        see gui/app.py's _on_preferences_saved()).

        __init__ used to call _style_treeview() and _build_legend() once,
        at construction time, and nothing ever re-invoked them on a live
        theme change -- CTk's own theme engine has no hook into ttk (see
        _style_treeview()'s docstring), and the legend's swatch colors
        were likewise only ever computed once. That's why this tab used
        to need a full restart to follow a dark/light switch. This
        recomputes and re-applies both, in place, without touching the
        legend's layout or the tree's already-rendered rows (tag_configure
        updates propagate to existing rows automatically)."""
        self._style_treeview()
        self._apply_region_tags()
        dark = ctk.get_appearance_mode() == "Dark"
        for light, dark_color, swatch in self._legend_swatches:
            swatch.configure(fg_color=dark_color if dark else light)

    @staticmethod
    def _ascii_preview(register) -> str:
        return "".join(chr(b) if 32 <= b < 127 else "." for b in register.get_bytes())

    @staticmethod
    def _hex_spaced(register) -> str:
        raw = register.get_hex()
        return " ".join(raw[i : i + 2] for i in range(0, len(raw), 2))

    def render(self, memory: Memory):
        self._memory = memory
        self._tree.delete(*self._tree.get_children())

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
            return

        try:
            r00 = memory.R00()
            dot_end = memory.DotEnd()
        except Exception as e:
            # Expected whenever no real dump is loaded yet -- see the
            # identical pattern in overview_tab.py's _render_summary().
            logger.debug("Could not read R00/.END. for hex view: %s", e)
            r00 = dot_end = 0

        has_partition = r00 >= MIN_SANE_R00 and dot_end <= r00
        key_assignments_end = memory.key_assignments_end()
        alarms_end = memory.alarms_end()

        count = DISPLAY_END - DISPLAY_START + 1
        self._header_label.configure(
            text=f"Full memory map: 0x{DISPLAY_START:03x}-0x{DISPLAY_END:03x} ({count} registers)"
        )

        for addr in range(DISPLAY_START, DISPLAY_END + 1):
            register = memory.get_register(addr)
            region_key = _classify(
                addr, r00, dot_end, has_partition, key_assignments_end, alarms_end
            )
            self._tree.insert(
                "",
                "end",
                values=(
                    f"0x{addr:03x}",
                    self._hex_spaced(register),
                    self._ascii_preview(register),
                    REGION_LABELS[region_key],
                ),
                tags=(region_key,),
            )
