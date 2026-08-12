"""
Loads flag names from docs/flags.md, so the GUI's flag names always match
whatever the docs say (rather than duplicating them in code). Falls back to
a built-in copy of the same table if the docs file can't be found or
parsed, so the Overview tab still works from a packaged install.
"""

import re
from pathlib import Path
from typing import Dict

# Two levels up from src/gui/flags_doc.py is the project root.
DOCS_FLAGS_PATH = Path(__file__).resolve().parents[2] / "docs" / "flags.md"

# Fallback copy of docs/flags.md's table, in case that file is missing.
_FALLBACK_FLAG_NAMES = {
    0: "general use", 1: "general use", 2: "general use", 3: "general use",
    4: "general use", 5: "general use", 6: "general use", 7: "general use",
    8: "general use", 9: "general use", 10: "general use",
    11: "auto execute", 12: "double wide print", 13: "lower case print",
    14: "overwrite card protection", 15: "IL-printer MAN / NORM",
    16: "IL-printer TRACE", 17: "end of record", 18: "TINTR enable",
    19: "general use", 20: "general use", 21: "printer enable",
    22: "number entry", 23: "ALPHA entry", 24: "range error ignore",
    25: "error ignore", 26: "audio enable", 27: "USER mode",
    28: "decimal point", 29: "digit grouping", 30: "CAT mode",
    31: "timer MDY / DMY", 32: "IL manio", 33: "IL lock",
    34: "ADRON / ADROFF", 35: "disable autostart", 36: "digit number 8,9",
    37: "digit number 4,5,6,7", 38: "digit number 2,3,6,7",
    39: "digit number 1,3,5,7,9", 40: "display FIX / SCI",
    41: "display ENG /FIX-ENG", 42: "trig mode DEG / GRAD",
    43: "trig mode RAD", 44: "continuous ON", 45: "system data entry",
    46: "partial key sequence", 47: "SHIFT", 48: "ALPHA", 49: "low BAT",
    50: "message", 51: "SST", 52: "PRGM mode", 53: "I/O", 54: "PSE",
    55: "Printer existence",
}

_ROW_PATTERN = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*$"
)


def load_flag_names(path: Path = DOCS_FLAGS_PATH) -> Dict[int, str]:
    """
    Parses the `| flag | description | flag | description |` markdown
    table in docs/flags.md into {flag_number: description}. Returns the
    built-in fallback copy if the file is missing or doesn't parse into at
    least one row, so callers always get a full 0-55 mapping (as complete
    as the fallback is; a partially-edited docs/flags.md still contributes
    whatever rows it has).
    """
    names: Dict[int, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return dict(_FALLBACK_FLAG_NAMES)

    for line in text.splitlines():
        match = _ROW_PATTERN.match(line.strip())
        if not match:
            continue
        a, desc_a, b, desc_b = match.groups()
        names[int(a)] = desc_a
        names[int(b)] = desc_b

    if not names:
        return dict(_FALLBACK_FLAG_NAMES)

    # Fill in anything the docs table didn't cover with the fallback, so a
    # partially-edited docs/flags.md doesn't leave gaps in the UI.
    for n, desc in _FALLBACK_FLAG_NAMES.items():
        names.setdefault(n, desc)
    return names
