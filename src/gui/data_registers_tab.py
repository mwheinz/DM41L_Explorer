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


class DataRegistersTab(ctk.CTkFrame):
    """Renders the main-data-memory register table for a Memory object.
    Call `render(memory)` whenever the buffer changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=8)
        self._header_label = ctk.CTkLabel(
            header, text="(no memory dump loaded)", font=ctk.CTkFont(weight="bold")
        )
        self._header_label.pack(side="left")
        ctk.CTkButton(
            header, text="Edit Selected...", width=130, command=self._edit_selected
        ).pack(side="right")
        ctk.CTkButton(header, text="Refresh", width=80, command=self._refresh).pack(
            side="right", padx=(0, 8)
        )

        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._style_treeview()

        columns = ("reg", "addr", "hex", "value")
        self._tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, text, width, stretch in [
            ("reg", "Reg", 60, False),
            ("addr", "Addr", 70, False),
            ("hex", "Hex", 160, False),
            ("value", "Value", 300, True),
        ]:
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor="w", stretch=stretch)

        vsb = ttk.Scrollbar(
            table_frame, orient="vertical", command=self._tree.yview,
            style="DM41.Vertical.TScrollbar",
        )
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        self._tree.bind("<Double-1>", lambda e: self._edit_selected())

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
            "DM41.Vertical.TScrollbar",
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
            "DM41.Vertical.TScrollbar",
            background=thumb, troughcolor=trough, bordercolor=trough,
            relief="flat", borderwidth=0,
        )
        style.map(
            "DM41.Vertical.TScrollbar",
            background=[("active", thumb_active), ("pressed", thumb_active)],
        )

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    def _refresh(self):
        if self._memory is not None:
            self.render(self._memory)

    def render(self, memory: Memory):
        self._memory = memory
        self._tree.delete(*self._tree.get_children())

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

        for i, addr in enumerate(range(r00, PRIMARY_DATA_END + 1)):
            register = memory.get_register(addr)
            self._tree.insert(
                "",
                "end",
                iid=str(addr),
                values=(f"R{i:02d}", f"0x{addr:03x}", register.get_hex(), str(register)),
            )

    def _edit_selected(self):
        if self._memory is None:
            return
        selection = self._tree.selection()
        if not selection:
            messagebox.showinfo("No Selection", "Select a register row first.")
            return
        addr = int(selection[0])
        self._edit_register(addr)

    def _edit_register(self, addr: int):
        register = self._memory.get_register(addr)

        def save(new_register: Register):
            self._memory.set_register(addr, new_register)
            self._notify_change()
            self.render(self._memory)
            self._tree.selection_set(str(addr))
            self._tree.see(str(addr))

        RegisterEditDialog(self, addr, register, save)
