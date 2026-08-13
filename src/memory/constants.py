"""
Shared address-range and sentinel-register constants used across the
memory package.
"""

from .registers import Register

STATUS_REGISTERS_RANGE = (0x00, 0x0F)
VOID_RANGE = (0x10, 0x3F)
KEY_ASSIGNMENTS_RANGE = (0xC0, 0xC0)  # Key assignments are variable length.
PRIMARY_DATA_END = 0x1FF

ZERO_REGISTER_HEX = "00000000000000"
ZERO_REGISTER = Register(size=7)
EOM_REGISTER_HEX = "ffffffffffffff"
EOM_REGISTER = Register.from_hex(EOM_REGISTER_HEX)

# Labels for the 16 status registers, in address order.
STATUS_REGISTER_LABELS = [
    "T",
    "Z",
    "Y",
    "X",
    "LastX",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "F",
    "a",
    "b",
    "c",
    "d / Flags",
    "e",
]

# The extended-memory regions the calculator can address. Regions 0 and 1
# are always present in the DM41L emulator.
XM_REGIONS = [(0x40, 0xBF), (0x201, 0x2EF)]
