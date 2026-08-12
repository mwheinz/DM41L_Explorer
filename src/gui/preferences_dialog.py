"""
Preferences dialog: default serial port/baud/timeout, logging, and
appearance.
"""

import platform
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk

PLATFORM_SYSTEM = platform.system()

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class PreferencesDialog(ctk.CTkToplevel):
    """
    Modal preferences dialog. Changes are applied and saved immediately
    when "Save" is clicked; `on_saved` is invoked afterward so the caller
    can refresh anything that depends on the config.
    """

    def __init__(self, master, config, serial_manager, on_saved=None):
        super().__init__(master)
        self.title("Preferences")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        if PLATFORM_SYSTEM == "Darwin" and hasattr(master, "_menubar"):
            self.config(menu=master._menubar)

        self._config = config
        self._serial_manager = serial_manager
        self._on_saved = on_saved

        tabs = ctk.CTkTabview(self)
        tabs.pack(padx=16, pady=16, fill="both", expand=True)
        tabs.add("Connection")
        tabs.add("Logging & Appearance")

        self._build_connection_tab(tabs.tab("Connection"))
        self._build_logging_tab(tabs.tab("Logging & Appearance"))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(padx=16, pady=(0, 16), fill="x")
        ctk.CTkButton(button_row, text="Cancel", width=90, command=self.destroy).pack(
            side="right"
        )
        ctk.CTkButton(button_row, text="Save", width=90, command=self._on_save).pack(
            side="right", padx=(0, 8)
        )

    # -- Connection tab -------------------------------------------------

    def _build_connection_tab(self, tab):
        ctk.CTkLabel(tab, text="Default serial port:").pack(
            anchor="w", padx=8, pady=(12, 4)
        )

        ports = self._serial_manager.get_available_ports()
        current_port = self._config.serial_port
        options = (
            ports
            if current_port in ports
            else ([current_port] + ports if current_port else ports)
        )
        if not options:
            options = [""]

        self._port_var = ctk.StringVar(value=current_port or options[0])
        self._port_menu = ctk.CTkOptionMenu(
            tab, values=options, variable=self._port_var
        )
        self._port_menu.pack(anchor="w", padx=8, pady=(0, 12), fill="x")

        ctk.CTkButton(tab, text="Rescan Ports", command=self._rescan_ports).pack(
            anchor="w", padx=8
        )

        ctk.CTkLabel(tab, text="Baud rate:").pack(anchor="w", padx=8, pady=(16, 4))
        self._baud_var = ctk.StringVar(value=str(self._config.baudrate))
        ctk.CTkOptionMenu(
            tab,
            values=["9600", "19200", "38400", "57600", "115200"],
            variable=self._baud_var,
        ).pack(anchor="w", padx=8, fill="x")

        ctk.CTkLabel(tab, text="Calculator console timeout (minutes):").pack(
            anchor="w", padx=8, pady=(16, 4)
        )
        self._timeout_var = ctk.StringVar(
            value=str(self._config.console_timeout_minutes)
        )
        ctk.CTkOptionMenu(
            tab,
            values=["1", "2", "3", "4", "5"],
            variable=self._timeout_var,
        ).pack(anchor="w", padx=8, fill="x")

    def _rescan_ports(self):
        ports = self._serial_manager.get_available_ports()
        if ports:
            self._port_menu.configure(values=ports)
            self._port_var.set(ports[0])

    # -- Logging & appearance tab ----------------------------------------

    def _build_logging_tab(self, tab):
        ctk.CTkLabel(tab, text="Log level:").pack(anchor="w", padx=8, pady=(12, 4))
        self._log_level_var = ctk.StringVar(value=self._config.logging_level.upper())
        ctk.CTkOptionMenu(tab, values=LOG_LEVELS, variable=self._log_level_var).pack(
            anchor="w", padx=8, fill="x"
        )

        ctk.CTkLabel(tab, text="Appearance mode:").pack(
            anchor="w", padx=8, pady=(16, 4)
        )
        self._appearance_var = ctk.StringVar(value=self._config.appearance_mode)
        ctk.CTkOptionMenu(
            tab, values=["System", "Light", "Dark"], variable=self._appearance_var
        ).pack(anchor="w", padx=8, fill="x")

        ctk.CTkLabel(tab, text="Log file directory:").pack(
            anchor="w", padx=8, pady=(16, 4)
        )
        dir_row = ctk.CTkFrame(tab, fg_color="transparent")
        dir_row.pack(anchor="w", padx=8, fill="x")

        self._log_dir_var = ctk.StringVar(value=str(self._config.log_directory))
        ctk.CTkEntry(dir_row, textvariable=self._log_dir_var).pack(
            side="left", fill="x", expand=True
        )
        ctk.CTkButton(
            dir_row, text="Browse...", width=90, command=self._pick_log_directory
        ).pack(side="left", padx=(8, 0))

    def _pick_log_directory(self):
        chosen = filedialog.askdirectory(
            title="Choose Log Directory",
            initialdir=self._log_dir_var.get() or str(Path.home()),
        )
        if chosen:
            self._log_dir_var.set(chosen)

    # -- Save -------------------------------------------------------------

    def _on_save(self):
        log_dir_str = self._log_dir_var.get().strip() or str(Path.home())
        try:
            Path(log_dir_str).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror(
                "Invalid Log Directory",
                f"Could not use '{log_dir_str}' for logs: {e}",
            )
            return

        self._config.serial_port = self._port_var.get()
        try:
            self._config.baudrate = int(self._baud_var.get())
            self._config.console_timeout_minutes = int(self._timeout_var.get())
        except ValueError:
            pass
        self._config.logging_level = self._log_level_var.get()
        self._config.appearance_mode = self._appearance_var.get()
        self._config.log_directory = log_dir_str

        self._config.save()

        if self._on_saved:
            self._on_saved()

        self.grab_release()
        self.destroy()
