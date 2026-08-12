"""
XM Files tab: view, add, edit, and remove extended-memory files.
"""

from tkinter import messagebox
import customtkinter as ctk

from memory import Memory, ExtendedMemory, MemoryError as DM41MemoryError
from gui.xm_file_dialog import XMFileDialog
from gui.scroll_support import bind_touchpad_scroll


class XMFilesTab(ctk.CTkFrame):
    """Renders the extended-memory file list for a Memory object. Call
    `render(memory)` whenever the buffer changes."""

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
        ctk.CTkButton(header, text="Add File...", width=100, command=self._add_file).pack(
            side="right"
        )

        self._table = ctk.CTkScrollableFrame(self)
        self._table.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for col, weight in enumerate([0, 0, 0, 0, 1, 0, 0]):
            self._table.grid_columnconfigure(col, weight=weight)
        bind_touchpad_scroll(self._table)

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    def _xm(self) -> ExtendedMemory:
        return ExtendedMemory(self._memory, address_range=[0x40, 0x3FF])

    def render(self, memory: Memory):
        self._memory = memory
        for widget in self._table.winfo_children():
            widget.destroy()

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
            return

        try:
            files = self._xm().list_files()
        except DM41MemoryError as e:
            self._header_label.configure(text=f"Could not list XM files: {e}")
            return

        self._header_label.configure(text=f"Extended-memory files: {len(files)}")

        headers = ["Name", "Type", "Header", "Registers", "Preview", "", ""]
        for col, text in enumerate(headers):
            ctk.CTkLabel(
                self._table, text=text, font=ctk.CTkFont(weight="bold")
            ).grid(row=0, column=col, sticky="w", padx=6, pady=4)

        for i, f in enumerate(files, start=1):
            self._render_row(f, row=i)

    def _render_row(self, f, row: int):
        preview = self._preview_for(f)

        ctk.CTkLabel(self._table, text=f.name.rstrip(), anchor="w").grid(
            row=row, column=0, sticky="w", padx=6, pady=1
        )
        ctk.CTkLabel(self._table, text=f.type_label, anchor="w").grid(
            row=row, column=1, sticky="w", padx=6, pady=1
        )
        ctk.CTkLabel(
            self._table,
            text=f"0x{f.header_addr:03x}",
            font=ctk.CTkFont(family="Courier"),
            anchor="w",
        ).grid(row=row, column=2, sticky="w", padx=6, pady=1)
        span_note = " (spans regions)" if f.spans_regions else ""
        ctk.CTkLabel(
            self._table, text=f"{f.num_registers}{span_note}", anchor="w"
        ).grid(row=row, column=3, sticky="w", padx=6, pady=1)
        ctk.CTkLabel(self._table, text=preview, anchor="w").grid(
            row=row, column=4, sticky="w", padx=6, pady=1
        )

        can_edit = f.file_type in (ExtendedMemory.TYPE_DATA, ExtendedMemory.TYPE_ASCII)
        edit_button = ctk.CTkButton(
            self._table,
            text="Edit",
            width=56,
            state="normal" if can_edit else "disabled",
            command=lambda addr=f.header_addr: self._edit_file(addr),
        )
        edit_button.grid(row=row, column=5, sticky="e", padx=6, pady=1)
        ctk.CTkButton(
            self._table,
            text="Remove",
            width=64,
            fg_color="#a03e3e",
            hover_color="#832f2f",
            command=lambda addr=f.header_addr, name=f.name: self._remove_file(addr, name),
        ).grid(row=row, column=6, sticky="e", padx=6, pady=1)

    @staticmethod
    def _preview_for(f) -> str:
        try:
            if f.file_type == ExtendedMemory.TYPE_DATA:
                numbers = f.get_numbers()
                text = ", ".join(f"{n:g}" for n in numbers[:6])
                if len(numbers) > 6:
                    text += f", ... ({len(numbers)} total)"
                return text
            if f.file_type == ExtendedMemory.TYPE_ASCII:
                records = f.get_records()
                text = ", ".join(repr(r) for r in records[:4])
                if len(records) > 4:
                    text += f", ... ({len(records)} total)"
                return text
            if f.file_type == ExtendedMemory.TYPE_PROGRAM:
                checksum = f.checksum_valid
                status = (
                    "valid" if checksum else "INVALID" if checksum is False else "unknown"
                )
                return f"{f.byte_length} instruction bytes, checksum {status}"
        except Exception as e:
            return f"(could not decode: {e})"
        return ""

    # -- Add / Edit / Remove ------------------------------------------------

    def _add_file(self):
        if self._memory is None:
            messagebox.showwarning("No Memory Loaded", "Load or start a memory buffer first.")
            return

        def save(name, file_type, kwargs):
            try:
                self._xm().add_file(name, file_type, **kwargs)
            except (ValueError, DM41MemoryError) as e:
                messagebox.showerror("Could Not Add File", str(e))
                return
            self._notify_change()
            self.render(self._memory)

        XMFileDialog(self, save)

    def _edit_file(self, header_addr: int):
        xm = self._xm()
        files = xm.list_files()
        existing = next((f for f in files if f.header_addr == header_addr), None)
        if existing is None:
            messagebox.showerror("Not Found", "That file no longer exists.")
            self.render(self._memory)
            return

        def save(name, file_type, kwargs):
            # Editing is implemented as remove-then-add (see
            # ExtendedMemory.remove_file()'s docstring): there's no
            # in-place content resize, so the edited file is rebuilt fresh
            # and ends up positioned after whatever files remain, rather
            # than keeping its original slot.
            try:
                xm2 = self._xm()
                xm2.remove_file(header_addr)
                xm2.add_file(name, file_type, **kwargs)
            except (ValueError, DM41MemoryError) as e:
                messagebox.showerror("Could Not Save File", str(e))
                return
            self._notify_change()
            self.render(self._memory)

        XMFileDialog(self, save, existing=existing)

    def _remove_file(self, header_addr: int, name: str):
        if not messagebox.askyesno(
            "Remove XM File", f"Remove {name.rstrip()!r} from extended memory?"
        ):
            return
        try:
            self._xm().remove_file(header_addr)
        except DM41MemoryError as e:
            messagebox.showerror("Could Not Remove File", str(e))
            return
        self._notify_change()
        self.render(self._memory)
