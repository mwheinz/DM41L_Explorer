"""Tests for gui/key_assignment_edit_dialog.py's KeyAssignmentEditDialog,
focused on the Function tab's typed-input normalization (GitHub issue #17)
-- typing a lowercase or ASCII-approximated function name ("cos", "x^2",
"sigma+", "x<=y?") must resolve to the real assignment, the same way
picking it from the dropdown would.

Same pattern as test_register_range_dialog.py: construct the real dialog
against a live (withdrawn) Tk root, drive its StringVar/button handler
directly rather than simulating keystrokes.

Requires a real Tk display (Xvfb in CI/sandboxes) -- same requirement as
test_app.py.
"""

from unittest import mock

import pytest

pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

from tkinter import messagebox
import customtkinter as ctk

from gui.key_assignment_edit_dialog import KeyAssignmentEditDialog


@pytest.fixture
def root():
    r = ctk.CTk()
    r.withdraw()
    yield r
    r.destroy()


def _make_dialog(root, on_save=None, on_delete=None, assignment=None):
    return KeyAssignmentEditDialog(
        root,
        key_number=1,
        shifted=False,
        assignment=assignment,
        on_save=on_save or mock.Mock(),
        on_delete=on_delete or mock.Mock(),
    )


@pytest.mark.parametrize(
    "typed,expected_bytes",
    [
        ("cos", 0x5A),
        ("x^2", 0x51),
        ("p->r", 0x4E),
        ("sigma+", 0x47),
        ("x<=y?", 0x46),
    ],
)
def test_typed_lowercase_or_ascii_name_resolves_on_save(root, typed, expected_bytes):
    on_save = mock.Mock()
    dlg = _make_dialog(root, on_save=on_save)
    dlg._function_var.set(typed)

    dlg._on_save_clicked()

    on_save.assert_called_once_with(expected_bytes)


def test_typed_ascii_native_xrom_name_is_not_mangled(root):
    """'X<=NN?' is already spelled with literal ASCII in the real table --
    typing it (in any case) must resolve to itself, not get corrupted by
    the "<=" -> "≤" substitution meant for 'X≤Y?'."""
    on_save = mock.Mock()
    dlg = _make_dialog(root, on_save=on_save)
    dlg._function_var.set("x<=nn?")

    dlg._on_save_clicked()

    on_save.assert_called_once_with((0xA6, 0x7C))


def test_still_rejects_genuinely_unknown_function(root, monkeypatch):
    on_save = mock.Mock()
    errors = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    )
    dlg = _make_dialog(root, on_save=on_save)
    dlg._function_var.set("not a real function")

    dlg._on_save_clicked()

    on_save.assert_not_called()
    assert errors and errors[0][0] == "Invalid Value"
