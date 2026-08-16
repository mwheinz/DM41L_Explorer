"""
Modal dialog for adding or editing a Data or ASCII extended-memory file.

Program-type XM files can be viewed and removed in the XM Files tab, but
not created or edited here -- there's still real research to do on program
storage before it's safe to write program bytes from this tool.
"""

import logging
import platform
from tkinter import messagebox
import customtkinter as ctk

from memory import ExtendedMemory
from gui.tab_common import MONOSPACE_FONT_FAMILY

logger = logging.getLogger(__name__)

PLATFORM_SYSTEM = platform.system()


class XMFileDialog(ctk.CTkToplevel):
    """
    Blocking modal dialog to add a new Data/ASCII XM file, or edit an
    existing one's name/content. `on_save(name, file_type, kwargs)` is
    called with arguments suitable for `ExtendedMemory.add_file()` if the
    user saves.
    """

    def __init__(self, master, on_save, *, existing=None):
        super().__init__(master)
        self._on_save = on_save
        self._editing = existing is not None

        self.title("Edit XM File" if self._editing else "Add XM File")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        if PLATFORM_SYSTEM == "Darwin" and hasattr(master, "_menubar"):
            self.config(menu=master._menubar)

        ctk.CTkLabel(self, text="Name (1-7 characters):").pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        name_default = existing.name.rstrip() if existing else ""
        self._name_var = ctk.StringVar(value=name_default)
        ctk.CTkEntry(self, textvariable=self._name_var, width=320).pack(
            anchor="w", padx=16
        )

        ctk.CTkLabel(self, text="Type:").pack(anchor="w", padx=16, pady=(12, 4))
        type_default = (
            "ASCII" if existing and existing.file_type == ExtendedMemory.TYPE_ASCII
            else "Data"
        )
        self._type_var = ctk.StringVar(value=type_default)
        type_menu = ctk.CTkOptionMenu(
            self, values=["Data", "ASCII"], variable=self._type_var,
            command=self._on_type_changed,
        )
        type_menu.pack(anchor="w", padx=16, fill="x")
        if self._editing:
            # Changing a file's type in place isn't meaningful -- content
            # format is type-specific -- so lock it while editing.
            type_menu.configure(state="disabled")

        self._data_label = ctk.CTkLabel(
            self, text="Numbers (comma-separated):"
        )
        self._ascii_label = ctk.CTkLabel(
            self, text="Records (one per line):"
        )

        data_default = ""
        if existing and existing.file_type == ExtendedMemory.TYPE_DATA:
            data_default = ", ".join(f"{n:g}" for n in existing.get_numbers())
        self._data_var = ctk.StringVar(value=data_default)
        self._data_entry = ctk.CTkEntry(
            self, textvariable=self._data_var, width=320,
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
        )

        ascii_default = ""
        if existing and existing.file_type == ExtendedMemory.TYPE_ASCII:
            ascii_default = "\n".join(existing.get_records())
        self._ascii_box = ctk.CTkTextbox(
            self, width=320, height=140, font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY)
        )
        if ascii_default:
            self._ascii_box.insert("1.0", ascii_default)

        self._content_row = 6
        self._on_type_changed(self._type_var.get())

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(padx=16, pady=(12, 16), fill="x", side="bottom")
        ctk.CTkButton(button_row, text="Cancel", width=90, command=self.destroy).pack(
            side="right"
        )
        ctk.CTkButton(button_row, text="Save", width=90, command=self._on_save_clicked).pack(
            side="right", padx=(0, 8)
        )

    def _on_type_changed(self, value):
        self._data_label.pack_forget()
        self._data_entry.pack_forget()
        self._ascii_label.pack_forget()
        self._ascii_box.pack_forget()
        if value == "Data":
            self._data_label.pack(anchor="w", padx=16, pady=(12, 4))
            self._data_entry.pack(anchor="w", padx=16, fill="x")
        else:
            self._ascii_label.pack(anchor="w", padx=16, pady=(12, 4))
            self._ascii_box.pack(anchor="w", padx=16, fill="both", expand=True)

    def _on_save_clicked(self):
        name = self._name_var.get().strip()
        if not name or len(name) > 7:
            logger.warning("Invalid XM file name %r: must be 1-7 characters.", name)
            messagebox.showerror(
                "Invalid Name", "File name must be 1-7 characters."
            )
            return
        try:
            name.encode("ascii")
        except UnicodeEncodeError:
            logger.warning("Invalid XM file name %r: not plain ASCII.", name)
            messagebox.showerror("Invalid Name", "File name must be plain ASCII.")
            return

        file_type_str = self._type_var.get()
        try:
            if file_type_str == "Data":
                raw = self._data_var.get().strip()
                if not raw:
                    raise ValueError("Enter at least one number.")
                numbers = [float(n.strip()) for n in raw.split(",") if n.strip()]
                if not numbers:
                    raise ValueError("Enter at least one number.")
                self._on_save(name, ExtendedMemory.TYPE_DATA, {"numbers": numbers})
            else:
                raw = self._ascii_box.get("1.0", "end").rstrip("\n")
                records = [line for line in raw.split("\n") if line != ""]
                if not records:
                    raise ValueError("Enter at least one record.")
                for r in records:
                    r.encode("ascii")
                self._on_save(name, ExtendedMemory.TYPE_ASCII, {"records": records})
        except (ValueError, UnicodeEncodeError) as e:
            logger.warning("Invalid XM file content for %r: %s", name, e)
            messagebox.showerror("Invalid Content", str(e))
            return

        self.destroy()
