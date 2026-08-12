"""
Flags tab: the 56 user/system flags (register d, 0x0e), editable, with
names loaded live from docs/flags.md.
"""

import customtkinter as ctk

from memory import Memory
from gui.flags_doc import load_flag_names
from gui.scroll_support import bind_touchpad_scroll


class FlagsTab(ctk.CTkScrollableFrame):
    """Renders the 56 flags as checkboxes. Call `render(memory)` whenever
    the buffer changes."""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._memory: Memory = None
        self._on_change = on_change
        self._flag_names = load_flag_names()
        self._flag_vars = {}
        self._suspend_flag_callbacks = False

        bind_touchpad_scroll(self)

        ctk.CTkLabel(
            self, text="Flags", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))

        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.grid(row=1, column=0, columnspan=4, sticky="w")

    def _notify_change(self):
        if self._on_change:
            self._on_change()

    def render(self, memory: Memory):
        self._memory = memory
        for widget in self._body.winfo_children():
            widget.destroy()
        self._flag_vars = {}

        if memory is None:
            ctk.CTkLabel(self._body, text="(no memory dump loaded)").grid(
                row=0, column=0, padx=8, pady=8, sticky="w"
            )
            return

        try:
            current = memory.get_all_flags()
        except Exception as e:
            ctk.CTkLabel(self._body, text=f"Could not decode flags: {e}").grid(
                row=0, column=0, padx=8, pady=4, sticky="w"
            )
            return

        self._suspend_flag_callbacks = True
        columns = 4
        for n in range(56):
            var = ctk.BooleanVar(value=current[n])
            self._flag_vars[n] = var
            label = f"{n:02d} {self._flag_names.get(n, '')}"
            cb = ctk.CTkCheckBox(
                self._body,
                text=label,
                variable=var,
                command=lambda n=n: self._on_flag_toggled(n),
            )
            r, c = divmod(n, columns)
            cb.grid(row=r, column=c, sticky="w", padx=8, pady=2)
        self._suspend_flag_callbacks = False

    def _on_flag_toggled(self, n: int):
        if self._suspend_flag_callbacks or self._memory is None:
            return
        value = self._flag_vars[n].get()
        self._memory.set_flag(n, value)
        self._notify_change()
