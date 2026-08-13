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
    0: "General Use", 1: "General Use", 2: "General Use", 3: "General Use",
    4: "General Use", 5: "General Use", 6: "General Use", 7: "General Use",
    8: "General Use", 9: "General Use", 10: "General Use",
    11: "Auto Execute", 12: "Double Wide Print", 13: "Lower Case Print",
    14: "Overwrite Card Protection", 15: "IL-printer MAN / NORM",
    16: "IL-printer TRACE", 17: "end of record", 18: "TINTR enable",
    19: "General Use", 20: "General Use", 21: "printer enable",
    22: "Number Entry", 23: "ALPHA entry", 24: "Range Error Ignore",
    25: "Error Ignore", 26: "Audio Enable", 27: "USER Mode",
    28: "Decimal Point", 29: "Digit Grouping", 30: "CAT Mode",
    31: "Timer MDY / DMY", 32: "IL Manio", 33: "IL Lock",
    34: "ADRON / ADROFF", 35: "Disable Autostart", 36: "Digit Number 8,9",
    37: "Digit Number 4,5,6,7", 38: "Digit Number 2,3,6,7",
    39: "Digit Number 1,3,5,7,9", 40: "Display FIX / SCI",
    41: "Display ENG /FIX-ENG", 42: "Trig Mode DEG / GRAD",
    43: "Trig Mode RAD", 44: "Continuous ON", 45: "System Data Entry",
    46: "Partial Key Sequence", 47: "SHIFT", 48: "ALPHA", 49: "Low BAT",
    50: "Message", 51: "SST", 52: "PRGM Mode", 53: "I/O", 54: "PSE",
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
