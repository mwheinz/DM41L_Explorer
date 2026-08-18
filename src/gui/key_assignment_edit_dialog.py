"""
Modal dialog for editing (or clearing) a single key's assignment, from
gui/key_assignments_tab.py -- see that module's docstring for the overall
tab design. This dialog itself never touches the Memory object; it hands
the resolved function bytes back to the caller via `on_save`, and
signals a delete via `on_delete`, exactly like RegisterEditDialog.
"""

import logging
import platform
from tkinter import messagebox
import customtkinter as ctk

from gui.dialog_common import build_dialog_button_row
from gui.tab_common import MONOSPACE_FONT_FAMILY
from memory.functions import (
    SINGLE_BYTE_NAMES,
    XROM_NAMES,
    bytes_for_function_name,
)

logger = logging.getLogger(__name__)

PLATFORM_SYSTEM = platform.system()

# Every assignable function's display name, alphabetically -- single-byte
# and XROM/peripheral functions merged into one list (memory/functions.py
# confirms there's no name collision between the two tables) since the
# picker doesn't need to distinguish them; bytes_for_function_name() below
# resolves whichever encoding a chosen name actually needs.
_ALL_FUNCTION_NAMES = sorted(set(SINGLE_BYTE_NAMES) | set(XROM_NAMES))


def _hex_for_assignment(assignment) -> str:
    """Best-effort raw-hex default for the Hex tab: the entry's function
    byte(s) as plain hex, no separators, or "" if there's no assignment to
    default from."""
    if assignment is None:
        return ""
    if assignment["fn_byte2"] is None:
        return f"{assignment['fn_byte1']:02X}"
    return f"{assignment['fn_byte1']:02X}{assignment['fn_byte2']:02X}"


class KeyAssignmentEditDialog(ctk.CTkToplevel):
    """
    Blocking modal dialog to assign, reassign, or delete one key's
    (unshifted or shifted) function. `on_save(function_bytes)` is called
    with an int (single-byte function) or (byte1, byte2) tuple (XROM/
    peripheral function) if the user saves; `on_delete()` is called
    instead if the user clicks Delete. Neither callback is invoked on
    Cancel. The dialog doesn't touch the Memory object itself -- callers
    stay in control of when (and whether) the edit takes effect, same as
    RegisterEditDialog.
    """

    def __init__(self, master, key_number: int, shifted: bool, assignment, on_save, on_delete):
        super().__init__(master)
        shift_label = "shifted" if shifted else "unshifted"
        self.title(f"Edit Key {key_number:02d} ({shift_label})")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        if PLATFORM_SYSTEM == "Darwin" and hasattr(master, "_menubar"):
            self.config(menu=master._menubar)

        self._on_save = on_save
        self._on_delete = on_delete
        self._has_existing_assignment = assignment is not None

        current_text = (
            f"Currently assigned: {assignment['name']}"
            if assignment is not None
            else "Currently unassigned."
        )
        ctk.CTkLabel(
            self, text=f"Key {key_number:02d} ({shift_label}) -- {current_text}",
            font=ctk.CTkFont(weight="bold"), wraplength=340, justify="left",
        ).pack(padx=16, pady=(16, 4), anchor="w")

        tabs = ctk.CTkTabview(self, width=360)
        tabs.pack(padx=16, pady=8, fill="both", expand=True)
        tabs.add("Function")
        tabs.add("Raw Hex")

        # -- Function tab: pick a named built-in/peripheral function -----
        default_name = (
            assignment["name"]
            if assignment is not None and assignment["name"] in _ALL_FUNCTION_NAMES
            else (_ALL_FUNCTION_NAMES[0] if _ALL_FUNCTION_NAMES else "")
        )
        self._function_var = ctk.StringVar(value=default_name)
        ctk.CTkLabel(tabs.tab("Function"), text="Function:").pack(
            anchor="w", padx=8, pady=(12, 4)
        )
        ctk.CTkComboBox(
            tabs.tab("Function"), values=_ALL_FUNCTION_NAMES,
            variable=self._function_var, width=300,
        ).pack(anchor="w", padx=8, fill="x")

        # -- Raw Hex tab: 2 hex digits (single-byte) or 4 (XROM 2-byte) --
        self._hex_var = ctk.StringVar(value=_hex_for_assignment(assignment))
        ctk.CTkLabel(
            tabs.tab("Raw Hex"),
            text="Raw function byte(s): 2 hex digits (e.g. 40) for a "
                 "built-in function, or 4 (e.g. A681) for an XROM/"
                 "peripheral function.",
            wraplength=320, justify="left",
        ).pack(anchor="w", padx=8, pady=(12, 4))
        ctk.CTkEntry(
            tabs.tab("Raw Hex"), textvariable=self._hex_var,
            font=ctk.CTkFont(family=MONOSPACE_FONT_FAMILY),
        ).pack(anchor="w", padx=8, fill="x")

        # Whichever tab already matches the current assignment (if any)
        # opens first -- an unknown/raw-hex assignment (fn2 present but no
        # matching function name, or a name outside the known list) should
        # land on Raw Hex rather than silently defaulting to some
        # unrelated function.
        if assignment is not None and assignment["name"] not in _ALL_FUNCTION_NAMES:
            tabs.set("Raw Hex")
        self._tabs = tabs

        extra_buttons = []
        if self._has_existing_assignment:
            extra_buttons.append(("Delete", self._on_delete_clicked))

        build_dialog_button_row(
            self,
            primary_text="Save",
            on_primary=self._on_save_clicked,
            extra_buttons=extra_buttons or None,
            pack_kwargs={"padx": 16, "pady": (8, 16), "fill": "x"},
        )

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_save_clicked(self):
        which = self._tabs.get()
        try:
            if which == "Function":
                name = self._function_var.get().strip()
                if not name:
                    raise ValueError("Choose a function.")
                function_bytes = bytes_for_function_name(name)
            else:  # Raw Hex
                text = self._hex_var.get().strip().replace(" ", "")
                if len(text) == 2:
                    function_bytes = int(text, 16)
                elif len(text) == 4:
                    function_bytes = (int(text[0:2], 16), int(text[2:4], 16))
                else:
                    raise ValueError(
                        f"Expected 2 or 4 hex digits, got {len(text)}."
                    )
        except ValueError as e:
            logger.warning("Invalid key assignment value on %s tab: %s", which, e)
            messagebox.showerror("Invalid Value", str(e))
            return

        self._on_save(function_bytes)
        self.destroy()

    def _on_delete_clicked(self):
        self._on_delete()
        self.destroy()
