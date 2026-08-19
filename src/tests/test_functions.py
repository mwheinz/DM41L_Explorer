"""Tests for memory/functions.py's normalize_function_name_input()
(GitHub issue #17): letting a user type an assignable function's name on a
standard keyboard -- lowercase, ASCII approximations of Sigma/the arrows/
less-than-or-equal -- and still resolve to the exact name
bytes_for_function_name() expects.
"""

import pytest

from memory.functions import (
    bytes_for_function_name,
    normalize_function_name_input,
    SINGLE_BYTE_NAMES,
    XROM_NAMES,
)


# -- Case folding -------------------------------------------------------


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("cos", "COS"),
        ("Sin", "SIN"),
        ("rtn", "RTN"),
        ("xeq", "XEQ"),
    ],
)
def test_lowercase_letters_are_uppercased(typed, expected):
    assert normalize_function_name_input(typed) == expected


# -- Symbol substitution -------------------------------------------------


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("x^2", "X↑2"),
        ("y^x", "Y↑X"),
        ("r^", "R↑"),
        ("enter^", "ENTER↑"),
        ("e^x", "E↑X"),
        ("10^x", "10↑X"),
    ],
)
def test_caret_becomes_up_arrow(typed, expected):
    assert normalize_function_name_input(typed) == expected


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("p->r", "P→R"),
        ("r->p", "R→P"),
        ("d->r", "D→R"),
        ("->hms", "→HMS"),
        ("->oct", "→OCT"),
    ],
)
def test_arrow_sequence_becomes_right_arrow(typed, expected):
    assert normalize_function_name_input(typed) == expected


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("sigma+", "Σ+"),
        ("SIGMA-", "Σ-"),
        ("clsigma", "CLΣ"),
        ("sigmareg", "ΣREG"),
        ("Sigma", "Σ"),
    ],
)
def test_sigma_word_becomes_sigma_symbol(typed, expected):
    assert normalize_function_name_input(typed) == expected


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("x<=y?", "X≤Y?"),
        ("x<=0?", "X≤0?"),
    ],
)
def test_less_or_equal_sequence_becomes_symbol(typed, expected):
    assert normalize_function_name_input(typed) == expected


# -- The X<=NN?/X>=NN? conflict ------------------------------------------
#
# These two XROM names are already spelled with literal ASCII "<=" / ">="
# (see docs/function_table.md's Extended Functions ROM table), right next
# to 'X≤Y?'/'X≤0?' which use the real ≤ glyph. Typing them out directly
# must not get mangled by the "<=" -> "≤" substitution.


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("x<=nn?", "X<=NN?"),
        ("X<=NN?", "X<=NN?"),
        ("x>=nn?", "X>=NN?"),
    ],
)
def test_ascii_native_names_are_not_mangled(typed, expected):
    assert normalize_function_name_input(typed) == expected


# -- Idempotence / passthrough -------------------------------------------


@pytest.mark.parametrize("name", ["COS", "X≤Y?", "ΣREG", "P→R", "X<>Y", "1/X"])
def test_already_canonical_names_pass_through_unchanged(name):
    assert normalize_function_name_input(name) == name


def test_leading_trailing_whitespace_is_stripped():
    assert normalize_function_name_input("  cos  ") == "COS"


def test_empty_string_is_returned_unchanged():
    assert normalize_function_name_input("") == ""


def test_unknown_input_is_normalized_but_not_rejected():
    """normalize_function_name_input() never raises -- an unmatched result
    is the caller's (bytes_for_function_name's) problem, not this
    function's."""
    result = normalize_function_name_input("not a real function")
    assert result == "NOT A REAL FUNCTION"
    with pytest.raises(ValueError):
        bytes_for_function_name(result)


# -- Integration with bytes_for_function_name -----------------------------


@pytest.mark.parametrize(
    "typed",
    [
        "cos",
        "x^2",
        "e^x-1",
        "p->r",
        "->hms",
        "sigma+",
        "clsigma",
        "x<=y?",
        "x<=nn?",
        "x>=nn?",
    ],
)
def test_normalized_input_resolves_via_bytes_for_function_name(typed):
    # Just needs to not raise -- confirms every example above actually
    # round-trips through the real lookup tables, not just the regexes.
    bytes_for_function_name(normalize_function_name_input(typed))


def test_every_known_name_is_reachable_case_insensitively():
    """Sanity check over the whole table, not just hand-picked examples:
    lowercasing (then re-normalizing) any real function name must still
    resolve to itself."""
    for name in list(SINGLE_BYTE_NAMES) + list(XROM_NAMES):
        assert normalize_function_name_input(name.lower()) == name
