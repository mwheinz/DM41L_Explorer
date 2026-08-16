"""
Data Registers tab: view and edit main data memory (R00 through 0x1ff).

Uses a native ttk.Treeview rather than one CustomTkinter widget per cell.
A dump can have up to ~319 data registers (if R00 sits right after Key
Assignments at 0xc1); building 4-5 CTk widgets per row for that many rows
took several seconds just to construct, and CTk widgets don't scale to
that count the way a native table does -- see the app's startup-speed
notes (gui/app.py) for the full story. ttk.Treeview also already receives
macOS trackpad scroll events correctly on its own, so it doesn't need the
CTkScrollableFrame workaround in gui/scroll_support.py.
"""

import logging
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk

from memory import Memory, Register, PRIMARY_DATA_END, format_data_line, parse_data_line
from gui.register_edit_dialog import RegisterEditDialog
from gui.memory_ranges import MIN_SANE_R00
from gui.tab_common import build_tab_header, MONOSPACE_FONT_FAMILY, stripe_bg_color

logger = logging.getLogger(__name__)


class DataRegistersTab(ctk.CTkFrame):
    """Renders the main-data-memory register table for a Memory object.
    Call `render(memory)` whenever the buffer changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change

        header, self._header_label = build_tab_header(
            self,
            button_kwargs={
                "text": "Edit...",
                "width": 130,
                "command": self._edit_selected,
            },
        )
        ctk.CTkButton(
            header, text="Export...", width=90, command=self._export_registers,
        ).pack(side="right", padx=(0, 8))
        ctk.CTkButton(
            header, text="Import...", width=90, command=self._import_registers,
        ).pack(side="right", padx=(0, 8))

        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._style_treeview()

        # The register list is split across two side-by-side tables (the
        # first half of registers on the left, the rest on the right)
        # instead of one long single-column list. A single "Value" column
        # doesn't need anywhere near the width a Treeview gives it by
        # default, so one long column wastes horizontal space and forces
        # far more scrolling than necessary; two columns use that leftover
        # width to roughly halve the amount of scrolling instead.
        left_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True)
        right_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
        right_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self._tree_left = self._build_register_tree(left_frame)
        self._tree_right = self._build_register_tree(right_frame)
        self._trees = (self._tree_left, self._tree_right)
        for tree in self._trees:
            tree.tag_configure("oddrow", background=self._stripe_bg)

        for tree in self._trees:
            tree.bind("<Double-1>", lambda e: self._edit_selected())
            # Keep selection exclusive across both tables -- selecting a
            # row in one should clear whatever was selected in the other,
            # so "Edit Selected" always has exactly one unambiguous target.
            tree.bind(
                "<<TreeviewSelect>>",
                lambda e, t=tree: self._on_tree_selected(t),
            )

    def _build_register_tree(self, parent) -> ttk.Treeview:
        columns = ("reg", "addr", "hex", "value")
        tree = ttk.Treeview(
            parent, columns=columns, show="headings", selectmode="browse"
        )
        for col, text, width, stretch in [
            ("reg", "Reg", 55, False),
            ("addr", "Addr", 65, False),
            ("hex", "Hex", 150, False),
            ("value", "Value", 170, True),
        ]:
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w", stretch=stretch)

        vsb = ttk.Scrollbar(
            parent, orient="vertical", command=tree.yview,
            style="DM41L.Vertical.TScrollbar",
        )
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        return tree

    def _style_treeview(self):
        """Rough dark/light theming so the native table (and its native
        scrollbar) don't clash too badly with CustomTkinter's look. This
        table uses ttk.Treeview/ttk.Scrollbar instead of CTk widgets purely
        for performance (see module docstring) -- CTk has no theme hook
        into ttk, so without this the scrollbar (and font) would default to
        the stock OS theme, which looks noticeably different from the
        CTkScrollableFrame scrollbars used on the Flags/XM Files tabs.

        Row/cell text uses the app's shared monospace font (see
        gui/tab_common.py) since every column here is register content
        (address, hex bytes, decoded value) rather than a label -- fixed
        width keeps those columns aligned. The heading row stays in the
        regular UI font (read from CTk's own theme dict, so it automatically
        follows whatever font preference gui/app.py applied at startup --
        see `_apply_font_prefs`), matching the bold-labeled column headers
        used elsewhere (e.g. the XM Files tab).

        Also stashes `self._stripe_bg` for alternating row colors -- reuses
        the same subtle shade already used for the heading/scrollbar trough
        (now centralized in gui/tab_common.py's `stripe_bg_color()`, shared
        with the XM Files/Programs tabs' own zebra striping) rather than
        inventing a third color, so odd rows read as a gentle tint instead
        of a jarring stripe. Row tags are applied per-item in render(),
        once the tree widgets exist (an instance method, not @staticmethod
        like this used to be, purely so it has a `self` to stash that
        color on for `_build_register_tree` to pick up)."""
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
        self._stripe_bg = bg
        ui_font = ctk.ThemeManager.theme["CTkFont"]
        font = (MONOSPACE_FONT_FAMILY, ui_font["size"])
        heading_font = (ui_font["family"], ui_font["size"], "bold")
        style.configure(
            "Treeview", background=field_bg, fieldbackground=field_bg,
            foreground=fg, rowheight=22, borderwidth=0, font=font,
        )
        style.configure("Treeview.Heading", background=bg, foreground=fg, font=heading_font)
        style.map("Treeview", background=[("selected", "#1f6aa5")])

        # Approximate CTkScrollableFrame's own scrollbar look (a slim,
        # borderless thumb with no up/down arrow buttons) so this native
        # scrollbar doesn't stand out as a different widget kit. clam's
        # stock Vertical.TScrollbar layout always includes arrow buttons,
        # so this defines a trimmed-down layout without them, matching the
        # trough to the table background.
        trough = field_bg
        thumb = "#565b5e" if dark else "#c0c0c0"
        thumb_active = "#6e7173" if dark else "#a6a6a6"
        style.layout(
            "DM41L.Vertical.TScrollbar",
            [(
                "Vertical.Scrollbar.trough",
                {
                    "sticky": "ns",
                    "children": [(
                        "Vertical.Scrollbar.thumb",
                        {"expand": "1", "sticky": "nswe"},
                    )],
                },
            )],
        )
        style.configure(
            "DM41L.Vertical.TScrollbar",
            background=thumb, troughcolor=trough, bordercolor=trough,
            relief="flat", borderwidth=0,
        )
        style.map(
            "DM41L.Vertical.TScrollbar",
            background=[("active", thumb_active), ("pressed", thumb_active)],
        )

    def refresh_theme(self):
        """Re-applies theme-dependent ttk styling/colors after
        ctk.set_appearance_mode() changes elsewhere (e.g. Preferences --
        see gui/app.py's _on_preferences_saved()).

        __init__ used to call _style_treeview() once, at construction
        time, and nothing ever re-invoked it on a live theme change --
        CTk's own theme engine has no hook into ttk (see
        _style_treeview()'s docstring). That's why this tab used to need
        a full restart to follow a dark/light switch. This recomputes
        _stripe_bg and re-applies the "oddrow" tag on both trees, in
        place -- tag_configure updates propagate to already-rendered
        rows automatically, no need to re-render()."""
        self._style_treeview()
        for tree in self._trees:
            tree.tag_configure("oddrow", background=self._stripe_bg)

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    def _on_tree_selected(self, selected_tree: ttk.Treeview):
        if not selected_tree.selection():
            return
        for tree in self._trees:
            if tree is not selected_tree:
                tree.selection_remove(*tree.selection())

    def render(self, memory: Memory):
        self._memory = memory
        for tree in self._trees:
            tree.delete(*tree.get_children())

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
            return

        try:
            r00 = memory.R00()
        except Exception as e:
            logger.warning("Could not determine R00: %s", e)
            self._header_label.configure(text=f"Could not determine R00: {e}")
            return

        if r00 < MIN_SANE_R00:
            self._header_label.configure(
                text="No data registers yet -- start a new buffer or load/read a dump first."
            )
            return

        count = (PRIMARY_DATA_END + 1) - r00
        self._header_label.configure(
            text=(
                f"Data registers: 0x{r00:03x}-0x{PRIMARY_DATA_END:03x} "
                f"({count} registers, R00-R{count - 1:02d})"
            )
        )

        # First half of the registers goes in the left table, the rest in
        # the right one; the left table gets the extra register when the
        # count is odd.
        split = -(-count // 2)  # ceil(count / 2)

        # Alternating-row shading is tracked per table (not by the global
        # register index `i`) so both tables' top rows start on the same
        # shade regardless of whether `split` happens to be odd or even.
        row_pos = {id(self._tree_left): 0, id(self._tree_right): 0}

        for i, addr in enumerate(range(r00, PRIMARY_DATA_END + 1)):
            tree = self._tree_left if i < split else self._tree_right
            pos = row_pos[id(tree)]
            row_pos[id(tree)] = pos + 1
            register = memory.get_register(addr)
            tree.insert(
                "",
                "end",
                iid=str(addr),
                values=(f"R{i:02d}", f"0x{addr:03x}", register.get_hex(), str(register)),
                tags=("oddrow",) if pos % 2 else (),
            )

    def _current_range(self):
        """Returns (r00, count) for the currently-displayed data
        registers, or None if there's no memory loaded / no sane R00 --
        the same check render() uses, shared here so Export/Import don't
        each re-derive it."""
        if self._memory is None:
            return None
        try:
            r00 = self._memory.R00()
        except Exception:
            return None
        if r00 < MIN_SANE_R00:
            return None
        return r00, (PRIMARY_DATA_END + 1) - r00

    def _export_registers(self):
        """Writes every currently-displayed data register as one DATA-
        format line each (see registers.format_data_line()), in R00..end
        order -- GitHub issue #11."""
        current_range = self._current_range()
        if current_range is None:
            messagebox.showwarning(
                "No Data Registers", "Load or start a memory buffer first."
            )
            return
        r00, count = current_range

        path = filedialog.asksaveasfilename(
            initialfile="registers.txt",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            lines = [
                format_data_line(self._memory.get_register(addr))
                for addr in range(r00, PRIMARY_DATA_END + 1)
            ]
            Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
        except (OSError, UnicodeEncodeError) as e:
            logger.warning("Could not export data registers to %s: %s", path, e)
            messagebox.showerror("Could Not Export", str(e))
            return
        logger.info("Exported %d data registers to %s", count, path)
        messagebox.showinfo("Exported", f"{count} data registers written to {path}")

    def _import_registers(self):
        """Reads a DATA-format file (see registers.parse_data_line()) and
        overwrites the currently-displayed data registers with it, in
        R00..end order -- GitHub issue #11. The file must have exactly as
        many lines as there are currently-displayed registers; this does
        not resize main memory."""
        current_range = self._current_range()
        if current_range is None:
            messagebox.showwarning(
                "No Data Registers", "Load or start a memory buffer first."
            )
            return
        r00, count = current_range

        path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Could not read %s for register import: %s", path, e)
            messagebox.showerror("Could Not Read File", str(e))
            return

        # Every line matters here -- each maps to one specific register
        # address -- so, unlike the XM file dialogs, blank lines aren't
        # silently skipped; a blank line just fails to parse like any
        # other bad line would.
        lines = content.rstrip("\n").split("\n") if content.strip("\n") else []
        if len(lines) != count:
            messagebox.showerror(
                "Line Count Mismatch",
                f"{path} has {len(lines)} line(s), but there are {count} "
                f"currently-displayed data registers (R00-R{count - 1:02d}). "
                "Import requires an exact match; it does not resize main "
                "memory.",
            )
            return

        new_registers = []
        for i, line in enumerate(lines, start=1):
            try:
                new_registers.append(parse_data_line(line))
            except ValueError as e:
                logger.error("Could not import %s: line %d (%r): %s", path, i, line, e)
                messagebox.showerror("Invalid Content", f"Line {i} ({line!r}): {e}")
                return

        if not messagebox.askyesno(
            "Import Data Registers",
            f"Overwrite all {count} data registers (R00-R{count - 1:02d}) "
            f"with the contents of {path}?",
        ):
            return

        for addr, reg in zip(range(r00, PRIMARY_DATA_END + 1), new_registers):
            self._memory.set_register(addr, reg)
        logger.info("Imported %d data registers from %s", count, path)
        self._notify_change()
        self.render(self._memory)

    def _selected_addr(self):
        for tree in self._trees:
            selection = tree.selection()
            if selection:
                return int(selection[0]), tree
        return None, None

    def _edit_selected(self):
        if self._memory is None:
            return
        addr, _ = self._selected_addr()
        if addr is None:
            messagebox.showinfo("No Selection", "Select a register row first.")
            return
        self._edit_register(addr)

    def _edit_register(self, addr: int):
        register = self._memory.get_register(addr)

        def save(new_register: Register):
            self._memory.set_register(addr, new_register)
            logger.info("Register 0x%03x edited: %s", addr, new_register)
            self._notify_change()
            self.render(self._memory)
            tree = self._tree_left if str(addr) in \
                    self._tree_left.get_children() else self._tree_right
            tree.selection_set(str(addr))
            tree.see(str(addr))

        RegisterEditDialog(self, addr, register, save)
