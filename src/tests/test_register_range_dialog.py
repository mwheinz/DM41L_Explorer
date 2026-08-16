"""
Tests for gui/register_range_dialog.py's RegisterRangeDialog (GitHub issue
#15: export register range) and RegisterImportLocationDialog (GitHub issue
#14: import destination).

These test the dialogs' own validation directly (constructing the real
widget and driving its entry vars / confirm button), the same way
test_xm_import_export.py tests XMFileDialog directly. Tab-level wiring
(DataRegistersTab._export_registers()/_import_registers() actually opening
these dialogs and acting on their callback) is covered in
test_xm_import_export.py's "DataRegistersTab: Export / Import" section.

Requires a real Tk display (Xvfb in CI/sandboxes) -- same requirement as
test_app.py.
"""

from unittest import mock

import pytest

pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

from tkinter import messagebox
import customtkinter as ctk

from gui.register_range_dialog import RegisterRangeDialog, RegisterImportLocationDialog


@pytest.fixture
def root():
    r = ctk.CTk()
    r.withdraw()
    yield r
    r.destroy()


# ---- RegisterRangeDialog (export, issue #15) ----


def test_export_range_defaults_to_full_range(root):
    """Confirming with no changes reproduces the old 'export everything'
    behavior -- GitHub issue #15 asks for this exact default."""
    on_confirm = mock.Mock()
    dlg = RegisterRangeDialog(root, count=35, on_confirm=on_confirm)
    assert dlg._start_var.get() == "0"
    assert dlg._end_var.get() == "34"

    dlg._on_confirm_clicked()

    on_confirm.assert_called_once_with(0, 34)


def test_export_range_accepts_custom_subrange(root):
    on_confirm = mock.Mock()
    dlg = RegisterRangeDialog(root, count=35, on_confirm=on_confirm)
    dlg._start_var.set("5")
    dlg._end_var.set("10")

    dlg._on_confirm_clicked()

    on_confirm.assert_called_once_with(5, 10)


def test_export_range_rejects_start_after_end(root, monkeypatch):
    on_confirm = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    dlg = RegisterRangeDialog(root, count=35, on_confirm=on_confirm)
    dlg._start_var.set("10")
    dlg._end_var.set("5")

    dlg._on_confirm_clicked()

    on_confirm.assert_not_called()
    assert errors and "Invalid Range" in errors[0][0]
    dlg.destroy()


def test_export_range_rejects_end_past_last_register(root, monkeypatch):
    on_confirm = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    dlg = RegisterRangeDialog(root, count=35, on_confirm=on_confirm)
    dlg._end_var.set("35")  # last valid index is 34

    dlg._on_confirm_clicked()

    on_confirm.assert_not_called()
    assert errors
    dlg.destroy()


def test_export_range_rejects_non_integer_entry(root, monkeypatch):
    on_confirm = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    dlg = RegisterRangeDialog(root, count=35, on_confirm=on_confirm)
    dlg._start_var.set("abc")

    dlg._on_confirm_clicked()

    on_confirm.assert_not_called()
    assert errors and "Invalid Range" in errors[0][0]
    dlg.destroy()


# ---- RegisterImportLocationDialog (import, issue #14) ----


def test_import_location_defaults_to_start_of_range(root):
    """Confirming with no changes reproduces the old 'import must cover
    every displayed register starting at R00' default location."""
    on_confirm = mock.Mock()
    dlg = RegisterImportLocationDialog(
        root, count=35, import_count=35, on_confirm=on_confirm
    )
    assert dlg._start_var.get() == "0"

    dlg._on_confirm_clicked()

    on_confirm.assert_called_once_with(0)


def test_import_location_accepts_offset_within_bounds(root):
    """The scenario from the issue: a 30-register file imported into
    registers 05-35 of a larger buffer."""
    on_confirm = mock.Mock()
    dlg = RegisterImportLocationDialog(
        root, count=40, import_count=30, on_confirm=on_confirm
    )
    dlg._start_var.set("5")

    dlg._on_confirm_clicked()

    on_confirm.assert_called_once_with(5)


def test_import_location_rejects_destination_past_last_register(root, monkeypatch):
    on_confirm = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    # 30 registers starting at R10 would run through R39, past the last
    # available register (R34, count=35).
    dlg = RegisterImportLocationDialog(
        root, count=35, import_count=30, on_confirm=on_confirm
    )
    dlg._start_var.set("10")

    dlg._on_confirm_clicked()

    on_confirm.assert_not_called()
    assert errors and "Invalid Location" in errors[0][0]
    dlg.destroy()


def test_import_location_rejects_negative_start(root, monkeypatch):
    on_confirm = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    dlg = RegisterImportLocationDialog(
        root, count=35, import_count=5, on_confirm=on_confirm
    )
    dlg._start_var.set("-1")

    dlg._on_confirm_clicked()

    on_confirm.assert_not_called()
    assert errors
    dlg.destroy()


def test_import_location_rejects_non_integer_entry(root, monkeypatch):
    on_confirm = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    dlg = RegisterImportLocationDialog(
        root, count=35, import_count=5, on_confirm=on_confirm
    )
    dlg._start_var.set("five")

    dlg._on_confirm_clicked()

    on_confirm.assert_not_called()
    assert errors and "Invalid Location" in errors[0][0]
    dlg.destroy()
