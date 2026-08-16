"""
XM Files tab: view, add, edit, remove, import, and export extended-memory
files.
"""

import logging
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk

from memory import Memory, ExtendedMemory, DM41LMemoryError, parse_data_line
from gui.xm_file_dialog import XMFileDialog
from gui.scroll_support import bind_touchpad_scroll
from gui.tab_common import build_tab_header, MONOSPACE_FONT_FAMILY, stripe_bg_color

logger = logging.getLogger(__name__)


def _guess_file_type(lines: list) -> str:
    """Best-effort default type for a freshly-imported file's content:
    "Data" only if *every* line actually parses as a valid DATA line (see
    registers.parse_data_line()); "ASCII" otherwise, since ASCII only
    requires 1-254 characters per line -- real text (e.g. anything with a
    line longer than 6 characters that isn't a plain number) almost never
    also happens to be valid DATA content, but the reverse doesn't hold at
    all: a file of short numbers/words is completely ambiguous between the
    two, so this can only ever be a starting guess -- the type stays
    editable in the dialog (see XMFileDialog's `initial=` handling, which
    pre-fills both the Data and ASCII editors with the same lines so
    switching the guess doesn't lose anything)."""
    if not lines:
        return "Data"
    try:
        for line in lines:
            parse_data_line(line)
    except ValueError:
        return "ASCII"
    return "Data"


class XMFilesTab(ctk.CTkFrame):
    """Renders the extended-memory file list for a Memory object. Call
    `render(memory)` whenever the buffer changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change

        header, self._header_label = build_tab_header(
            self,
            button_kwargs={"text": "Add File", "width": 100, "command": self._add_file},
        )
        ctk.CTkButton(
            header, text="Import File", width=110, command=self._import_file,
        ).pack(side="right", padx=(0, 8))

        self._table = ctk.CTkScrollableFrame(self)
        self._table.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for col, weight in enumerate([0, 0, 0, 0, 1, 0, 0, 0]):
            self._table.grid_columnconfigure(col, weight=weight)
        bind_touchpad_scroll(self._table)

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    def _xm(self) -> ExtendedMemory:
        return ExtendedMemory(self._memory, address_range=[0x40, 0x2EF])

    def render(self, memory: Memory):
        self._memory = memory
        for widget in self._table.winfo_children():
            widget.destroy()

        if memory is None:
            self._header_label.configure(text="(no memory dump loaded)")
            return

        try:
            files = self._xm().list_files()
        except DM41LMemoryError as e:
            logger.warning("Could not list XM files: %s", e)
            self._header_label.configure(text=f"Could not list XM files: {e}")
            return

        self._header_label.configure(text=f"Extended-memory files: {len(files)}")
        self._stripe_bg = stripe_bg_color()

        headers = ["Name", "Type", "Header", "Registers", "Preview", "", "", ""]
        for col, text in enumerate(headers):
            ctk.CTkLabel(
                self._table, text=text, font=ctk.CTkFont(weight="bold")
            ).grid(row=0, column=col, sticky="w", padx=6, pady=4)

        for i, f in enumerate(files, start=1):
            self._render_row(f, row=i)

    def _render_row(self, f, row: int):
        # Alternating row shading: the same shared shade as Data Registers'
        # ttk.Treeview striping (see stripe_bg_color()), applied directly as
        # each label's own fg_color rather than as a separate background
        # widget behind them.
        #
        # An earlier version gridded one full-row CTkFrame *behind* the
        # row's labels instead. That doesn't work with CustomTkinter:
        # CTkLabel's "transparent" isn't real canvas alpha -- it just paints
        # itself to match its own master's declared color at construction
        # time -- so each label still showed its own (wrong-colored) opaque
        # patch on top of the frame instead of blending with it. Worse, an
        # unconstrained CTkFrame defaults to a 200x200 minimum size, and
        # with nothing else in that row tall enough to out-rank it, the
        # whole row grew to match -- exactly the "rows are much taller"
        # symptom the user reported. Coloring each label directly (with
        # `sticky="nsew"` so it fills its whole cell, not just its text)
        # avoids both problems: no extra oversized widget, and no
        # mismatched "transparent" patches.
        row_bg = self._stripe_bg if (row - 1) % 2 == 1 else "transparent"

        preview = self._preview_for(f)

        ctk.CTkLabel(self._table, text=f.name.rstrip(), anchor="w", fg_color=row_bg).grid(
            row=row, column=0, sticky="nsew", padx=6, pady=1
        )
        ctk.CTkLabel(self._table, text=f.type_label, anchor="w", fg_color=row_bg).grid(
            row=row, column=1, sticky="nsew", padx=6, pady=1
        )
        ctk.CTkLabel(
            self._table,
            text=f"0x{f.header_addr:03x}",
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
            anchor="w",
            fg_color=row_bg,
        ).grid(row=row, column=2, sticky="nsew", padx=6, pady=1)
        span_note = " (spans regions)" if f.spans_regions else ""
        ctk.CTkLabel(
            self._table, text=f"{f.num_registers}{span_note}", anchor="w", fg_color=row_bg
        ).grid(row=row, column=3, sticky="nsew", padx=6, pady=1)
        ctk.CTkLabel(
            self._table, text=preview, font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
            anchor="w", fg_color=row_bg,
        ).grid(row=row, column=4, sticky="nsew", padx=6, pady=1)

        # Export (like Edit) only makes sense for Data/ASCII -- Program
        # files' on-disk format isn't part of this feature (see the
        # XMFileDialog module docstring on why Program isn't editable
        # here either).
        can_edit = f.file_type in (ExtendedMemory.TYPE_DATA, ExtendedMemory.TYPE_ASCII)
        export_button = ctk.CTkButton(
            self._table,
            text="Export...",
            width=76,
            state="normal" if can_edit else "disabled",
            command=lambda file=f: self._export_file(file),
        )
        export_button.grid(row=row, column=5, sticky="e", padx=6, pady=1)
        edit_button = ctk.CTkButton(
            self._table,
            text="Edit",
            width=56,
            state="normal" if can_edit else "disabled",
            command=lambda addr=f.header_addr: self._edit_file(addr),
        )
        edit_button.grid(row=row, column=6, sticky="e", padx=6, pady=1)
        ctk.CTkButton(
            self._table,
            text="Remove",
            width=64,
            fg_color="#a03e3e",
            hover_color="#832f2f",
            command=lambda addr=f.header_addr, name=f.name: self._remove_file(addr, name),
        ).grid(row=row, column=7, sticky="e", padx=6, pady=1)

    @staticmethod
    def _preview_for(f) -> str:
        try:
            if f.file_type == ExtendedMemory.TYPE_DATA:
                lines = f.get_data_lines()
                text = ", ".join(lines[:6])
                if len(lines) > 6:
                    text += f", ... ({len(lines)} total)"
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
            # Expected for a file whose content doesn't fit the shape its
            # own type nibble claims (e.g. a corrupt or hand-edited dump)
            # -- shown inline in the Preview column rather than a popup,
            # so this is a DEBUG detail, not a WARNING-worthy event.
            logger.debug("Could not decode preview for XM file: %s", e)
            return f"(could not decode: {e})"
        return ""

    # -- Add / Edit / Remove ------------------------------------------------

    def _save_new_or_edited_file(self, name, file_type, kwargs, *, replacing_addr=None):
        """Shared save path for Add, Import, and Edit -- all three end up
        calling ExtendedMemory.add_file() with the same kind of kwargs
        (see XMFileDialog); Edit additionally removes the file being
        replaced first (see _edit_file())."""
        try:
            xm = self._xm()
            if replacing_addr is not None:
                # Editing is implemented as remove-then-add (see
                # ExtendedMemory.remove_file()'s docstring): there's no
                # in-place content resize, so the edited file is rebuilt
                # fresh and ends up positioned after whatever files
                # remain, rather than keeping its original slot.
                xm.remove_file(replacing_addr)
            xm.add_file(name, file_type, **kwargs)
        except (ValueError, DM41LMemoryError) as e:
            verb = "save" if replacing_addr is not None else "add"
            logger.warning("Could not %s XM file %r: %s", verb, name, e)
            messagebox.showerror(f"Could Not {verb.title()} File", str(e))
            return
        logger.info(
            "XM file %s: %r (%s)",
            "edited" if replacing_addr is not None else "added",
            name,
            file_type,
        )
        self._notify_change()
        self.render(self._memory)

    def _add_file(self):
        if self._memory is None:
            messagebox.showwarning("No Memory Loaded", "Load or start a memory buffer first.")
            return

        def save(name, file_type, kwargs):
            self._save_new_or_edited_file(name, file_type, kwargs)

        XMFileDialog(self, save)

    def _import_file(self):
        """Reads a plain-text file from disk and opens it pre-filled in
        the Add dialog (Data or ASCII, per the DATA/ASCII line formats --
        see registers.parse_data_line()) so the user can review/adjust the
        name and type before it's actually added. GitHub issue #11."""
        if self._memory is None:
            messagebox.showwarning("No Memory Loaded", "Load or start a memory buffer first.")
            return

        path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Could not read %s for XM file import: %s", path, e)
            messagebox.showerror("Could Not Read File", str(e))
            return

        default_name = Path(path).stem[:7] or "IMPORT"
        stripped_content = content.rstrip("\n")
        guessed_type = _guess_file_type(
            [line for line in stripped_content.split("\n") if line != ""]
        )
        # The guessed type just picks which editor is shown first --
        # XMFileDialog pre-fills *both* the Data and ASCII boxes with this
        # same content when given `initial=`, so switching the type
        # dropdown afterward re-labels the same lines rather than clearing
        # whichever box wasn't showing.
        XMFileDialog(
            self,
            lambda name, file_type, kwargs: self._save_new_or_edited_file(
                name, file_type, kwargs
            ),
            initial={
                "name": default_name,
                "file_type": guessed_type,
                "content": stripped_content,
            },
        )

    def _export_file(self, f):
        default_name = f"{f.name.rstrip()}.txt"
        path = filedialog.asksaveasfilename(
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            if f.file_type == ExtendedMemory.TYPE_DATA:
                lines = f.get_data_lines()
            elif f.file_type == ExtendedMemory.TYPE_ASCII:
                lines = f.get_records()
            else:
                raise ValueError(f"Export isn't supported for {f.type_label} files.")
            Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
        except (OSError, ValueError, UnicodeEncodeError) as e:
            logger.warning("Could not export XM file %r to %s: %s", f.name, path, e)
            messagebox.showerror("Could Not Export File", str(e))
            return
        logger.info("XM file %r exported to %s", f.name, path)
        messagebox.showinfo("Exported", f"{f.name.rstrip()!r} written to {path}")

    def _edit_file(self, header_addr: int):
        xm = self._xm()
        files = xm.list_files()
        existing = next((f for f in files if f.header_addr == header_addr), None)
        if existing is None:
            logger.warning("Edit requested for XM file at 0x%03x, but it no longer exists.", header_addr)
            messagebox.showerror("Not Found", "That file no longer exists.")
            self.render(self._memory)
            return

        def save(name, file_type, kwargs):
            self._save_new_or_edited_file(
                name, file_type, kwargs, replacing_addr=header_addr
            )

        XMFileDialog(self, save, existing=existing)

    def _remove_file(self, header_addr: int, name: str):
        if not messagebox.askyesno(
            "Remove XM File", f"Remove {name.rstrip()!r} from extended memory?"
        ):
            return
        try:
            self._xm().remove_file(header_addr)
        except DM41LMemoryError as e:
            logger.warning("Could not remove XM file %r: %s", name, e)
            messagebox.showerror("Could Not Remove File", str(e))
            return
        logger.info("XM file removed: %r", name)
        self._notify_change()
        self.render(self._memory)
