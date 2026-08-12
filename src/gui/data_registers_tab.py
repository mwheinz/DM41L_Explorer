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

from tkinter import ttk, messagebox
import customtkinter as ctk

from memory import Memory, Register, PRIMARY_DATA_END
from gui.register_edit_dialog import RegisterEditDialog
from gui.memory_ranges import MIN_SANE_R00
from gui.tab_common import build_tab_header


class DataRegistersTab(ctk.CTkFrame):
    """Renders the main-data-memory register table for a Memory object.
    Call `render(memory)` whenever the buffer changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change

        _, self._header_label = build_tab_header(
            self,
            button_kwargs={
                "text": "Edit Selected...",
                "width": 130,
                "command": self._edit_selected,
            },
        )

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

    @staticmethod
    def _style_treeview():
        """Rough dark/light theming so the native table (and its native
        scrollbar) don't clash too badly with CustomTkinter's look. This
        table uses ttk.Treeview/ttk.Scrollbar instead of CTk widgets purely
        for performance (see module docstring) -- CTk has no theme hook
        into ttk, so without this the scrollbar would default to the
        stock OS theme, which looks noticeably different from the
        CTkScrollableFrame scrollbars used on the Flags/XM Files tabs."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        dark = ctk.get_appearance_mode() == "Dark"
        bg = "#2b2b2b" if dark else "#f4f4f4"
        field_bg = "#242424" if dark else "#ffffff"
        fg = "#e6e6e6" if dark else "#1a1a1a"
        style.configure(
            "Treeview", background=field_bg, fieldbackground=field_bg,
            foreground=fg, rowheight=22, borderwidth=0,
        )
        style.configure("Treeview.Heading", background=bg, foreground=fg)
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

        for i, addr in enumerate(range(r00, PRIMARY_DATA_END + 1)):
            tree = self._tree_left if i < split else self._tree_right
            register = memory.get_register(addr)
            tree.insert(
                "",
                "end",
                iid=str(addr),
                values=(f"R{i:02d}", f"0x{addr:03x}", register.get_hex(), str(register)),
            )

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
            self._notify_change()
            self.render(self._memory)
            tree = self._tree_left if str(addr) in self._tree_left.get_children() else self._tree_right
            tree.selection_set(str(addr))
            tree.see(str(addr))

        RegisterEditDialog(self, addr, register, save)
