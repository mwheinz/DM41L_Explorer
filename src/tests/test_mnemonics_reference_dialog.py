"""Tests for gui/mnemonics_reference_dialog.py and its Help menu entry.

Requires a real Tk display (Xvfb in CI/sandboxes) -- same requirement as
test_app.py.
"""

import pytest

pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

import customtkinter as ctk

from gui.mnemonics_reference_dialog import MnemonicsReferenceDialog
from memory.mnemonic_doc import mnemonic_reference_rows


@pytest.fixture
def root():
    r = ctk.CTk()
    r.withdraw()
    yield r
    r.destroy()


def test_shows_every_instruction_unfiltered(root):
    dlg = MnemonicsReferenceDialog(root)
    assert len(dlg.visible_displays()) == len(mnemonic_reference_rows())
    assert "instructions" in dlg._count_label.cget("text")


def test_filter_finds_sigma_instructions_by_ascii_word(root):
    dlg = MnemonicsReferenceDialog(root)
    dlg._filter_var.set("sigma")
    shown = dlg.visible_displays()
    assert set(shown) == {"Σ+", "Σ-", "CLΣ", "ΣREG", "ΣREG?"}
    assert (
        dlg._count_label.cget("text")
        == f"5 of {len(mnemonic_reference_rows())} instructions"
    )


def test_filter_matches_dialect_spelling(root):
    dlg = MnemonicsReferenceDialog(root)
    dlg._filter_var.set("goto")
    assert dlg.visible_displays() == ["GTO"]


def test_clearing_filter_restores_all_rows(root):
    dlg = MnemonicsReferenceDialog(root)
    dlg._filter_var.set("sigma")
    dlg._filter_var.set("")
    assert len(dlg.visible_displays()) == len(mnemonic_reference_rows())


def test_substitution_and_trigraph_tabs_exist(root):
    dlg = MnemonicsReferenceDialog(root)
    for name in ("Instructions", "Substitutions", "Trigraphs"):
        dlg._tabs.set(name)
        assert dlg._tabs.get() == name
