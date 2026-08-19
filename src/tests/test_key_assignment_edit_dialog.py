"""Tests for gui/key_assignment_edit_dialog.py's KeyAssignmentEditDialog.

Two areas: the pre-existing Function tab typed-input normalization
(GitHub issue #17) -- typing a lowercase or ASCII-approximated function
name ("cos", "x^2", "sigma+", "x<=y?") must resolve to the real
assignment, the same way picking it from the dropdown would -- and the
newer Program tab (global-label assignments, docs/key_assignments.md sec
4.6), including the on_save(kind, value) contract both tabs now share.

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


def _make_dialog(
    root,
    on_save=None,
    on_delete=None,
    assignment=None,
    program_assignment=None,
    program_names=(),
):
    return KeyAssignmentEditDialog(
        root,
        key_number=1,
        shifted=False,
        assignment=assignment,
        program_assignment=program_assignment,
        program_names=list(program_names),
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

    on_save.assert_called_once_with("function", expected_bytes)


def test_typed_ascii_native_xrom_name_is_not_mangled(root):
    """'X<=NN?' is already spelled with literal ASCII in the real table --
    typing it (in any case) must resolve to itself, not get corrupted by
    the "<=" -> "≤" substitution meant for 'X≤Y?'."""
    on_save = mock.Mock()
    dlg = _make_dialog(root, on_save=on_save)
    dlg._function_var.set("x<=nn?")

    dlg._on_save_clicked()

    on_save.assert_called_once_with("function", (0xA6, 0x7C))


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


def test_raw_hex_two_digits_saves_as_function(root):
    on_save = mock.Mock()
    dlg = _make_dialog(root, on_save=on_save)
    dlg._tabs.set("Raw Hex")
    dlg._hex_var.set("40")

    dlg._on_save_clicked()

    on_save.assert_called_once_with("function", 0x40)


def test_raw_hex_four_digits_saves_as_xrom_function(root):
    on_save = mock.Mock()
    dlg = _make_dialog(root, on_save=on_save)
    dlg._tabs.set("Raw Hex")
    dlg._hex_var.set("A681")

    dlg._on_save_clicked()

    on_save.assert_called_once_with("function", (0xA6, 0x81))


# ---- Program tab (docs/key_assignments.md sec 4.6) ----


def test_program_tab_saves_chosen_name(root):
    on_save = mock.Mock()
    dlg = _make_dialog(root, on_save=on_save, program_names=["AAA", "BBB"])
    dlg._tabs.set("Program")
    dlg._program_var.set("BBB")

    dlg._on_save_clicked()

    on_save.assert_called_once_with("program", "BBB")


def test_program_tab_defaults_to_current_program_assignment(root):
    """If the key's current assignment is a global label, the Program tab
    opens pre-selected to it and is the tab that opens by default."""
    program = mock.Mock(name="AAA")
    program.name = "AAA"
    dlg = _make_dialog(
        root, program_assignment=program, program_names=["AAA", "BBB"]
    )

    assert dlg._tabs.get() == "Program"
    assert dlg._program_var.get() == "AAA"


def test_program_tab_with_no_programs_shows_message_and_rejects_save(root):
    on_save = mock.Mock()
    errors = []
    with mock.patch.object(
        messagebox, "showerror", lambda title, msg: errors.append((title, msg))
    ):
        dlg = _make_dialog(root, on_save=on_save, program_names=[])
        dlg._tabs.set("Program")

        dlg._on_save_clicked()

    assert dlg._program_var is None
    on_save.assert_not_called()
    assert errors and errors[0][0] == "Invalid Value"


def test_function_assignment_takes_display_priority_over_program(root):
    """Per docs sec 4.7's real lookup order, a Key Assignment Register
    entry shadows a global-label one on the same key -- callers should
    only ever pass one of `assignment`/`program_assignment`, but the
    dialog's default-tab logic should still prefer `assignment` if both
    were somehow passed."""
    program = mock.Mock(name="AAA")
    program.name = "AAA"
    dlg = _make_dialog(
        root,
        assignment={
            "key_number": 1, "shifted": False,
            "fn_byte1": 0x40, "fn_byte2": None, "name": "+",
            "raw_key_byte": 0x01,
        },
        program_assignment=program,
        program_names=["AAA"],
    )

    assert dlg._tabs.get() == "Function"
    assert "Currently assigned: +" in dlg.winfo_children()[0].cget("text")
