"""
Unit tests for the trigraph codec (memory/trigraphs.py -- docs/trigraphs.md).
"""

import pytest
from memory import encode_trigraphs, decode_trigraphs

# --- Literal passthrough ---


def test_literal_ascii_passes_through_unchanged():
    """Ordinary printable ASCII (that FOCAL hasn't reassigned) means
    itself, with no escaping at all."""
    text = "Hello, World! 123 #$%&"
    data = text.encode("ascii")
    assert encode_trigraphs(data) == text
    assert decode_trigraphs(text) == data


def test_underscore_is_literal_not_backtick():
    """Regression: tee's byte value is 0x60 (backtick), not 0x5F
    (underscore) -- underscore is an ordinary printable-ASCII byte that
    means itself, while backtick is the one that needs the \\T escape."""
    assert encode_trigraphs(b"_") == "_"
    assert decode_trigraphs("_") == b"_"
    assert encode_trigraphs(bytes([0x60])) == "\\T"


# --- Shorthand mnemonics (docs/trigraphs.md's table) ---


SHORTHAND_CASES = [
    (0x00, "\\--"),
    (0x01, "\\x"),
    (0x0C, "\\u"),
    (0x0D, "\\<)"),
    (0x1D, "\\/="),
    (0x5C, "\\\\"),
    (0x5E, "\\^|"),
    (0x60, "\\T"),
    (0x7E, "\\E"),
    (0x7F, "\\+"),
]


@pytest.mark.parametrize("byte_value,trigraph", SHORTHAND_CASES)
def test_shorthand_encode(byte_value, trigraph):
    assert encode_trigraphs(bytes([byte_value])) == trigraph


@pytest.mark.parametrize("byte_value,trigraph", SHORTHAND_CASES)
def test_shorthand_decode(byte_value, trigraph):
    assert decode_trigraphs(trigraph) == bytes([byte_value])


def test_shorthand_mixed_with_literal_text():
    """A shorthand trigraph embedded in ordinary text round-trips, and
    doesn't swallow the characters after it."""
    data = "A".encode("ascii") + bytes([0x7E]) + "B".encode("ascii")
    encoded = encode_trigraphs(data)
    assert encoded == "A\\EB"
    assert decode_trigraphs(encoded) == data


# --- Numeric fallback (\\nnn, always exactly 3 digits) ---


def test_numeric_fallback_encode_is_always_three_digits():
    # 0x02 (STX) is a control byte -- not printable ASCII, no shorthand --
    # so it must fall back to the numeric form, zero-padded to 3 digits.
    assert encode_trigraphs(bytes([2])) == "\\002"
    assert encode_trigraphs(bytes([5])) == "\\005"
    assert encode_trigraphs(bytes([200])) == "\\200"


def test_numeric_fallback_decode_requires_exactly_three_digits():
    assert decode_trigraphs("\\065") == bytes([65])
    # Fixed width means a numeric trigraph followed by more digits isn't
    # ambiguous -- "\\0651" is "\\065" (byte 65 / 'A') followed by a
    # literal "1", not "\\0" + "651" or any other split.
    assert decode_trigraphs("\\0651") == bytes([65]) + b"1"


def test_numeric_fallback_rejects_short_or_missing_digits():
    with pytest.raises(ValueError):
        decode_trigraphs("\\65")  # only 2 digits -- the doc's own typo
    with pytest.raises(ValueError):
        decode_trigraphs("\\6")
    with pytest.raises(ValueError):
        decode_trigraphs("\\")
    with pytest.raises(ValueError):
        decode_trigraphs("\\ab")  # not digits at all


def test_numeric_fallback_rejects_out_of_range_value():
    with pytest.raises(ValueError):
        decode_trigraphs("\\256")  # a byte can't exceed 255


def test_numeric_fallback_can_express_bytes_that_also_have_shorthand():
    """\\127 (Sigma's byte value, 0x7E == 126 -- use 0x7F/127, Append, to
    avoid confusion) still decodes correctly even though a shorthand also
    exists for that byte -- the numeric form is a fallback available for
    *every* byte, not just the ones without a mnemonic."""
    assert decode_trigraphs("\\127") == bytes([0x7F])
    assert decode_trigraphs("\\126") == bytes([0x7E])


# --- Round trip across every byte value ---


def test_roundtrip_every_byte_value():
    for b in range(256):
        data = bytes([b])
        assert decode_trigraphs(encode_trigraphs(data)) == data


def test_roundtrip_mixed_content():
    data = bytes([65, 0x7E, 66, 0x00, 0x20, 255, 0x5C])
    encoded = encode_trigraphs(data)
    assert decode_trigraphs(encoded) == data


# --- Error cases ---


def test_decode_rejects_unrecognized_escape():
    with pytest.raises(ValueError):
        decode_trigraphs("\\q")  # not a known shorthand or 3 digits


def test_decode_rejects_multibyte_source_character():
    with pytest.raises(ValueError):
        decode_trigraphs("€")  # Euro sign -- code point > 0xFF
