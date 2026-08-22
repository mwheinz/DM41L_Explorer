'''
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
'''

import logging
from tkinter import ttk
import tkinter
import customtkinter as ctk

from memory import Memory
from gui.tab_common import build_tab_header, MONOSPACE_FONT_FAMILY

logger = logging.getLogger(__name__)

# The full addressable range this tab displays -- matches the span
# Memory.regions() covers (0x000-0x2ef): Status Registers, an unused/"void"
# gap, Extended Memory #0, Main Memory (itself split further, when a dump
# with a sane R00/.END. is loaded), Extended Memory #1. This is the full
# address space of the HP41CX calculator and the DM41L emulator.
DISPLAY_START = 0x000
DISPLAY_END = 0x2EF

# One entry per region key Memory.regions() can report. `light`/`dark` are
# the row background tints for CTk's two appearance modes -- picked
# distinct enough to tell apart at a glance but not so saturated they
# fight with the selection highlight or make the monospace text hard to
# read. Order here is also legend display order. This is a color/legend
# catalog only now (issue #25) -- it lists every region kind that COULD
# appear (so the legend stays complete even when the current dump doesn't
# have one of them, e.g. "Program"/"Data" while no sane R00/.END. is
# loaded), not the actual boundaries, which come from Memory.regions().
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


def _region_span_for(regions: list, addr: int):
    '''The RegionSpan in `regions` (a Memory.regions() list) containing
    `addr`, or None. `regions` covers the full display range with no gaps
    (see Memory.regions()'s docstring), so every address in
    [DISPLAY_START, DISPLAY_END] is expected to match something -- render()
    below falls back to the "nonexistent" catalog entry if this somehow
    returns None, rather than crashing.'''
    for span in regions:
        if addr in span:
            return span
    return None


class HexViewTab(ctk.CTkFrame):
    '''Renders a read-only, region-colored hex dump of the full address
    space for a Memory object. Call `render(memory)` whenever the buffer
    changes.'''

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
        '''A row of small color swatches + labels so the row colors below
        are self-explanatory without a separate reference doc.'''
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

        vsb = tkinter.Scrollbar(
            parent,
            orient="vertical",
            command=tree.yview,
        )
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        return tree

    def _style_treeview(self):
        '''Same dark/light ttk theming approach as Data Registers (see that
        module's `_style_treeview` docstring for why ttk needs this at
        all) -- kept as its own copy rather than a shared helper since the
        two tabs configure different tag sets (region colors here,
        odd/even zebra striping there) on top of the same base style
        names, and a shared style object is already how ttk works (the
        style names/registration are process-global, not per-widget).'''
        style = ttk.Style()
        try:
            style.theme_use("default")
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

    def refresh_theme(self):
        '''Re-applies every theme-dependent color after
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
        updates propagate to existing rows automatically).'''
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

        # One regions() call per render, not one per address -- render()
        # walks up to 752 addresses below, and Memory.regions() itself
        # already does the R00/.END./key-assignments/alarms boundary work
        # (including the same defensive R00/DotEnd fallback this tab used
        # to do inline) once per call.
        regions = memory.regions()

        count = DISPLAY_END - DISPLAY_START + 1
        self._header_label.configure(
            text=f"Full memory map: 0x{DISPLAY_START:03x}-0x{DISPLAY_END:03x} ({count} registers)"
        )

        for addr in range(DISPLAY_START, DISPLAY_END + 1):
            register = memory.get_register(addr)
            span = _region_span_for(regions, addr)
            region_key = span.key if span else "nonexistent"
            region_label = span.label if span else "Inaccessible"
            self._tree.insert(
                "",
                "end",
                values=(
                    f"0x{addr:03x}",
                    self._hex_spaced(register),
                    self._ascii_preview(register),
                    region_label,
                ),
                tags=(region_key,),
            )
