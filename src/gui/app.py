"""
DM41L Explorer: a CustomTkinter GUI for DM41L_Explorer.

Design, per the 2026-08-12 rebuild request: menu items instead of toolbar
buttons for every basic function, a status bar pinned to the bottom of the
window, and a tabbed main view (Overview / Flags / Data Registers / XM
Files, with more tabs planned as other memory regions get
reverse-engineered).

Tabs render lazily -- only the tab currently on screen is (re)built; the
others are marked dirty and build themselves the next time they're
selected. This matters a lot for Data Registers in particular: earlier,
all tabs rendered eagerly at startup, every render rebuilt every widget
from scratch, and CustomTkinter widgets are individually much more
expensive to construct than plain Tk ones -- profiling a plain startup
(an empty, never-loaded Memory(), which decodes R00 as 0x000) showed it
trying to build 512 register rows x ~5 widgets each (~7700 widgets) for a
tab nobody was even looking at yet, which alone took several seconds. See
gui/memory_ranges.py for the R00 sanity check that also stops that
specific pathological case, and gui/data_registers_tab.py for why that
tab was additionally moved off CustomTkinter widgets entirely.
"""

import logging
from pathlib import Path
from datetime import datetime
import platform
from tkinter import filedialog, messagebox, Menu

import customtkinter as ctk

from memory import Memory
from serial_manager import SerialManager
from engine.command_engine import CommandEngine
from engine.commands import (
    BatteryCheckCommand,
    GetTimeCommand,
    SetTimeCommand,
    MemoryStringCommand,
    LoadMemoryStringCommand,
    ConsoleTimeoutCommand,
)

from config import ProjectConfig
from gui.port_dialog import PortSelectionDialog
from gui.preferences_dialog import PreferencesDialog
from gui.overview_tab import OverviewTab
from gui.flags_tab import FlagsTab
from gui.data_registers_tab import DataRegistersTab
from gui.xm_files_tab import XMFilesTab

try:
    from dm41lversion import _version
except ImportError:
    _version = "unknown"

ENGINE_POLL_MS = 50

PLATFORM_SYSTEM = platform.system()

logger = logging.getLogger("DM41L Explorer")


def _setup_logging(config_store):
    level = getattr(logging, config_store.logging_level.upper(), logging.INFO)

    log_dir = config_store.log_directory
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path.home()
    log_file = log_dir / "dm41l_explorer.log"

    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    file_handler.setLevel(level)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)


class DM41LExplorerApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.config_store = ProjectConfig()
        _setup_logging(self.config_store)

        ctk.set_appearance_mode(self.config_store.appearance_mode)
        ctk.set_default_color_theme(self.config_store.color_theme)

        self.title("DM41L Explorer")
        self.geometry("1080x768")

        self.serial = SerialManager(error_callback=self._handle_serial_error)
        self.engine = CommandEngine(self.serial)
        self.memory = Memory()
        self.memory_source = None
        self.dirty = False
        self._command_pending = False

        self._build_layout()
        self._menubar = self._build_menus()
        self._bind_keys()

        self._start_engine_pump()
        self._render_tabs()

        # Kick off the auto-connect sequence once the window is up.
        self.after(100, self.attempt_auto_connect)

    def _handle_serial_error(self, msg: str):
        logger.error("Serial error: %s", msg)
        self._set_status("Not connected")
        self._command_pending = False
        # No self.serial.disconnect() call here (unlike the other error
        # handlers below): this callback runs directly on SerialManager's
        # own background thread (see _run_loop's error_callback invocation),
        # and disconnect() calls self._thread.join(), which raises
        # RuntimeError if a thread tries to join itself. SerialManager
        # already closes its own port handle and clears is_connected before
        # invoking this callback -- see serial_manager.py's _run_loop -- so
        # there's nothing left to clean up from here.
        self.after(0, lambda: messagebox.showerror("Error", "Disconnected."))

    # -- Layout ---------------------------------------------------------

    def _build_layout(self):
        # Status bar first, pinned to the bottom, so the tab view above it
        # gets whatever space is left -- packing order (not just `side`)
        # is what keeps it pinned regardless of window resizing.
        status_bar = ctk.CTkFrame(self)
        status_bar.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        self._status_label = ctk.CTkLabel(
            status_bar, text="Not connected", font=ctk.CTkFont(size=13)
        )
        self._status_label.pack(side="left", padx=8, pady=6)
        self._modified_label = ctk.CTkLabel(
            status_bar, text="", font=ctk.CTkFont(size=13), text_color="#d9822b"
        )
        self._modified_label.pack(side="left", padx=8, pady=6)
        self._battery_label = ctk.CTkLabel(
            status_bar, text="", font=ctk.CTkFont(size=13)
        )
        self._battery_label.pack(side="right", padx=16, pady=6)
        self._calc_time_label = ctk.CTkLabel(
            status_bar, text="", font=ctk.CTkFont(size=13)
        )
        self._calc_time_label.pack(side="right", padx=16, pady=6)
        self._source_label = ctk.CTkLabel(
            status_bar, text="(new, unsaved buffer)", font=ctk.CTkFont(size=13),
            text_color="gray60",
        )
        self._source_label.pack(side="right", padx=16, pady=6)

        self.tabview = ctk.CTkTabview(self, command=self._on_tab_changed)
        self.tabview.pack(side="top", fill="both", expand=True, padx=8, pady=8)
        self.tabview.add("Overview")
        self.tabview.add("Flags")
        self.tabview.add("Data Registers")
        self.tabview.add("XM Files")

        self.overview_tab = OverviewTab(
            self.tabview.tab("Overview"), on_change=self._on_memory_changed
        )
        self.overview_tab.pack(fill="both", expand=True)

        self.flags_tab = FlagsTab(
            self.tabview.tab("Flags"), on_change=self._on_memory_changed
        )
        self.flags_tab.pack(fill="both", expand=True)

        self.data_registers_tab = DataRegistersTab(
            self.tabview.tab("Data Registers"), on_change=self._on_memory_changed
        )
        self.data_registers_tab.pack(fill="both", expand=True)

        self.xm_files_tab = XMFilesTab(
            self.tabview.tab("XM Files"), on_change=self._on_memory_changed
        )
        self.xm_files_tab.pack(fill="both", expand=True)

        # Which tabs are showing stale content -- see _render_active_tab().
        self._tabs = {
            "Overview": self.overview_tab,
            "Flags": self.flags_tab,
            "Data Registers": self.data_registers_tab,
            "XM Files": self.xm_files_tab,
        }
        self._tabs_dirty = {name: True for name in self._tabs}

    def _build_menus(self):
        """Builds the application's menu bar. Every basic function lives
        here rather than in toolbar buttons, per the current design."""

        acc = "Command" if PLATFORM_SYSTEM == "Darwin" else "Control"

        menubar = Menu(self)

        if PLATFORM_SYSTEM == "Darwin":
            self.createcommand("tkAboutDialog", self._show_about)

        # File Menu
        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="New Memory Buffer",
            command=self.new_memory_buffer,
            accelerator=f"{acc}+N",
            underline=0,
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Open Dump...",
            command=self.load_dump_from_file,
            accelerator=f"{acc}+O",
            underline=0,
        )
        file_menu.add_command(
            label="Save Dump",
            command=self.save_dump_to_file,
            accelerator=f"{acc}+S",
            underline=0,
        )
        file_menu.add_command(
            label="Save Dump As...",
            command=self.save_dump_as,
            underline=13,
        )
        file_menu.add_separator()
        if PLATFORM_SYSTEM != "Darwin":
            file_menu.add_command(label="About Box", command=self._show_about, underline=0)
        file_menu.add_command(
            label="Preferences",
            command=self.show_preferences,
            accelerator=f"{acc}+,",
            underline=0,
        )
        if PLATFORM_SYSTEM != "Darwin":
            file_menu.add_separator()
            file_menu.add_command(
                label="Quit", command=self.on_close, accelerator=f"{acc}+Q", underline=0
            )
        menubar.add_cascade(label="File", menu=file_menu)

        # Connect Menu
        connect_menu = Menu(menubar, tearoff=0)
        connect_menu.add_command(
            label="Connect / Reconnect...", command=self.show_connect_dialog, underline=0
        )
        connect_menu.add_command(
            label="Disconnect", command=self.disconnect, underline=0
        )
        connect_menu.add_separator()
        connect_menu.add_command(
            label="Set Calculator Time", command=self.set_calculator_time, underline=4
        )
        connect_menu.add_separator()
        connect_menu.add_command(
            label="Get Dump from DM41L", command=self.get_dump_from_calculator, underline=0
        )
        connect_menu.add_command(
            label="Send Dump to DM41L", command=self.send_dump_to_calculator, underline=0
        )
        menubar.add_cascade(label="Connect", menu=connect_menu)

        # View Menu
        view_menu = Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Refresh Tabs", command=self._render_tabs, accelerator="F5", underline=0
        )
        menubar.add_cascade(label="View", menu=view_menu)

        # Help Menu
        help_menu = Menu(menubar, tearoff=0)
        if PLATFORM_SYSTEM != "Darwin":
            help_menu.add_command(label="About DM41L Explorer", command=self._show_about)
        else:
            help_menu.add_command(label="Read Me", state="disabled")
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)
        return menubar

    def _bind_keys(self):
        acc = "Command" if PLATFORM_SYSTEM == "Darwin" else "Control"

        self.bind(f"<{acc}-n>", lambda e: self.new_memory_buffer())
        self.bind(f"<{acc}-o>", lambda e: self.load_dump_from_file())
        self.bind(f"<{acc}-s>", lambda e: self.save_dump_to_file())
        self.bind(f"<{acc}-q>", lambda e: self.on_close())
        self.bind("<F5>", lambda e: self._render_tabs())

    def _show_about(self):
        messagebox.showinfo(
            "About DM41L Explorer",
            f"Read and Write DM41L memory files\n\n"
            f"Version:\n{_version}\n\n"
            "Written by Michael Heinz.\n",
        )

    def _set_status(self, text: str):
        self._status_label.configure(text=text)

    def _on_memory_changed(self):
        self.dirty = True
        self._modified_label.configure(text="* Modified")
        # The tab that made this edit already re-rendered itself (each
        # tab's own edit handler calls its render() directly, for
        # immediate feedback) -- just mark every *other* tab stale so it
        # picks up the change next time it's actually shown, instead of
        # re-rendering tabs nobody's looking at right now.
        active = self.tabview.get()
        for name in self._tabs_dirty:
            if name != active:
                self._tabs_dirty[name] = True

    def _on_tab_changed(self):
        self._render_active_tab()

    def _render_active_tab(self):
        """Renders only the tab currently on screen, if it's stale.

        Tabs render lazily rather than all at once: building a tab's
        widgets from scratch for a big register table is genuinely slow
        (see the module docstring), so there's no reason to pay that cost
        for tabs the user hasn't looked at yet, or to pay it twice for a
        tab that's already showing current content.
        """
        name = self.tabview.get()
        if not self._tabs_dirty.get(name, True):
            return
        self._tabs[name].render(self.memory)
        self._tabs_dirty[name] = False

    def _render_tabs(self):
        """Invalidates every tab (e.g. after loading a whole new dump) and
        immediately re-renders whichever one is currently visible; the
        rest pick up the new memory next time they're selected."""
        for name in self._tabs_dirty:
            self._tabs_dirty[name] = True
        self._render_active_tab()

    def _update_source_label(self):
        text = str(self.memory_source) if self.memory_source else "(new, unsaved buffer)"
        self._source_label.configure(text=text)

    # -- Engine pump (drives CommandEngine off the Tk main loop) ---------

    def _start_engine_pump(self):
        self._pump_engine()

    def _pump_engine(self):
        try:
            while self.engine.process_incoming_data():
                pass
        except Exception as e:
            logger.error("Engine pump error: %s", e)
        self.after(ENGINE_POLL_MS, self._pump_engine)

    # -- Connection -------------------------------------------------------

    def attempt_auto_connect(self):
        """Entry point: try the configured default port; on failure, prompt."""
        default_port = self.config_store.serial_port
        ports = self.serial.get_available_ports()

        if default_port in ports:
            self._connect_and_verify(default_port)
        else:
            self._prompt_for_port(
                f"Could not find the configured port '{default_port}'. "
                "Please select a serial port to connect to the DM41L, or "
                "cancel to work offline."
            )

    def _prompt_for_port(self, message: str): dialog = PortSelectionDialog(
            self, self.serial, default_port=self.config_store.serial_port,
            message=message,) self.wait_window(dialog) if dialog.result:
        self._connect_and_verify(dialog.result) elif self.serial.is_connected:
            # Cancelling out of Reconnect leaves the existing connection
            # untouched -- don't overwrite the status bar with "Not
            # connected".
            self._set_status(f"Connected to {self.serial.serial_inst.port}")
        else: self._set_status("Not connected")

    def show_connect_dialog(self):
        self._prompt_for_port(None)

    def disconnect(self):
        if not self.serial.is_connected:
            return
        self.serial.disconnect()
        self._set_status("Not connected")
        self._battery_label.configure(text="")
        self._calc_time_label.configure(text="")

    def _connect_and_verify(self, port: str):
        self._set_status(f"Connecting to {port}...")
        success, message = self.serial.connect(
            port, baudrate=self.config_store.baudrate
        )
        if not success:
            self._set_status("Not connected")
            self._prompt_for_port(f"Connection to '{port}' failed: {message}")
            return

        self.config_store.serial_port = port
        self.config_store.save()
        self._set_status(f"Connected to {port} -- verifying...")

        self.engine.execute(
            BatteryCheckCommand(timeout=2.0),
            self._on_startup_battery,
            self._on_verify_failed,
        )

    def _on_verify_failed(self, message: str):
        # This callback runs on the main Tk thread (via the engine pump in
        # _pump_engine), so it's safe to call disconnect() directly here --
        # unlike _handle_serial_error above, which runs on SerialManager's
        # own background thread and can't join itself.
        if self.serial.is_connected:
            self.serial.disconnect()
        self._set_status("Not connected")
        self.after(
            0,
            lambda: self._prompt_for_port(
                f"Connected to the port, but the DM41L did not respond ({message}). "
                "Please select a different serial port."
            ),
        )

    # -- Startup sequence: battery -> timeout -> time -> memory dump

    def _on_startup_battery(self, voltage_mv):
        logger.info("Battery: %s", voltage_mv)
        self._battery_label.configure(text=f"Battery: {voltage_mv} mV")
        self._set_status(f"Connected to {self.serial.serial_inst.port}")
        self.after(
            10,
            lambda: self.engine.execute(
                ConsoleTimeoutCommand([self.config_store.console_timeout_minutes]),
                self._on_timeout_command,
                self._on_command_error,
            ),
        )

    def _on_timeout_command(self, result):
        logger.info("Timeout: %s", result)
        self.after(
            10,
            lambda: self.engine.execute(
                GetTimeCommand(), self._on_startup_time, self._on_command_error
            ),
        )

    def _on_startup_time(self, time_str):
        logger.info("Time: %s", time_str)
        self._calc_time_label.configure(text=f"Calc time: {time_str}")
        self.after(10, self._fetch_memory_dump)

    def _fetch_memory_dump(self):
        self._set_status("Reading memory dump...")
        self.after(
            10,
            lambda: self.engine.execute(
                MemoryStringCommand(), self._on_dump_received, self._on_command_error
            ),
        )

    def _on_dump_received(self, dump):
        logger.info("Dump received.")
        try:
            self.memory = Memory.from_string(dump)
            self.memory_source = None
            self.dirty = False
            self._modified_label.configure(text="")
            self._update_source_label()
            self._render_tabs()
            self._set_status("Connected -- memory dump loaded.")
        except Exception as e:
            self._on_command_error(f"Failed to parse memory dump: {e}")

    # -- Command callbacks -------------------------------------------------

    def _on_command_error(self, message: str):
        logger.error("%s", message)
        self._command_pending = False
        self._set_status("Not connected")
        # Runs on the main Tk thread (engine callback via _pump_engine), so
        # a direct disconnect() call here is safe -- see _on_verify_failed.
        if self.serial.is_connected:
            self.serial.disconnect()
        # Deferred for the same reason as the previous GUI: showing a modal
        # dialog immediately would open a nested Tk event loop while the
        # engine is mid-reset, risking reentrant calls into
        # process_incoming_data().
        self.after(0, lambda: messagebox.showerror("Error", message))

    # -- File menu actions --------------------------------------------------

    def new_memory_buffer(self):
        if self.dirty and not messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved changes and start a new buffer?"
        ):
            return
        self.memory = Memory()
        self.memory_source = None
        self.dirty = False
        self._modified_label.configure(text="")
        self._update_source_label()
        self._render_tabs()
        self._set_status("Started a new, empty memory buffer.")

    def set_calculator_time(self):
        if not self.serial.is_connected:
            messagebox.showwarning("Not Connected", "Connect to the DM41L first.")
            return
        now = datetime.now()
        args = [now.strftime("%Y%m%d"), now.strftime("%H%M%S")]
        self.engine.execute(
            SetTimeCommand(args), self._on_time_set, self._on_command_error
        )

    def _on_time_set(self, result):
        logger.info("Time set: %s", result)
        self._calc_time_label.configure(text="Calc time set to system time")
        self.after(
            0,
            lambda: messagebox.showinfo(
                "Success", "Calculator clock set to system time."
            ),
        )

    def save_dump_to_file(self):
        if self.memory_source is None:
            self.save_dump_as()
            return
        try:
            self.memory.to_file(self.memory_source)
            self.dirty = False
            self._modified_label.configure(text="")
            messagebox.showinfo("Saved", f"Memory dump written to {self.memory_source}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save dump: {e}")

    def save_dump_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".dm41",
            filetypes=[("DM41L dump", "*.dm41"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.memory.to_file(path)
            self.memory_source = Path(path)
            self.dirty = False
            self._modified_label.configure(text="")
            self._update_source_label()
            messagebox.showinfo("Saved", f"Memory dump written to {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save dump: {e}")

    def load_dump_from_file(self):
        if self.dirty and not messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved changes and load a different dump?"
        ):
            return
        path = filedialog.askopenfilename(
            filetypes=[("DM41L dump", "*.dm41"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            self.memory = Memory.from_file(path)
            self.memory_source = Path(path)
            self.dirty = False
            self._modified_label.configure(text="")
            self._update_source_label()
            self._render_tabs()
            self._set_status(f"Loaded dump from {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not load dump: {e}")

    # -- Connect menu actions -----------------------------------------------

    def send_dump_to_calculator(self):
        if not self.serial.is_connected:
            messagebox.showwarning("Not Connected", "Connect to the DM41L first.")
            return
        if not messagebox.askyesno(
            "Send Dump to Calculator",
            "This will overwrite the calculator's current memory with the "
            "currently loaded dump. Continue?",
        ):
            return

        dump_text = self.memory.to_string()

        command = LoadMemoryStringCommand([dump_text], serial=self.serial)
        accepted = self.engine.execute(
            command,
            self._on_dump_sent,
            self._on_io_failed,
        )
        if not accepted:
            messagebox.showwarning(
                "Busy",
                "Another command is still in progress. Please wait a moment and try again.",
            )
            return
        command.trigger_transfer()

    def _on_dump_sent(self, result):
        logger.info("Dump sent: %s", result)
        self.after(
            0,
            lambda: messagebox.showinfo("Sent", "Memory dump sent to the calculator."),
        )

    def _on_io_failed(self, message):
        self._on_command_error(message)

    def get_dump_from_calculator(self):
        if not self.serial.is_connected:
            messagebox.showwarning("Not Connected", "Connect to the DM41L first.")
            return
        if self.dirty and not messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved changes and read the calculator's memory?"
        ):
            return
        self._set_status("Reading memory dump...")
        self.after(
            10,
            lambda: self.engine.execute(
                MemoryStringCommand(), self._on_dump_received, self._on_io_failed
            ),
        )

    def show_preferences(self):
        PreferencesDialog(
            self, self.config_store, self.serial, on_saved=self._on_preferences_saved
        )

    def _on_preferences_saved(self):
        ctk.set_appearance_mode(self.config_store.appearance_mode)
        _setup_logging(self.config_store)

    # -- Shutdown -----------------------------------------------------------

    def on_close(self):
        if self.dirty and not messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved changes and quit?"
        ):
            return
        # Runs on the main Tk thread (window-close handler), so a direct
        # disconnect() call here is safe -- see _on_verify_failed.
        if self.serial.is_connected:
            self.serial.disconnect()
        self.destroy()


def main():
    app = DM41LExplorerApp()
    logger.debug(main.__name__)
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
