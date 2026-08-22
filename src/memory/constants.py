'''
Shared address-range and sentinel-register constants used across the
memory package.
'''

from .registers import Register

STATUS_REGISTERS_RANGE = (0x00, 0x0F)
VOID_RANGE = (0x10, 0x3F)
KEY_ASSIGNMENTS_RANGE = (0xC0, 0xC0)  # Key assignments are variable length.
PRIMARY_DATA_END = 0x1FF

# The lowest R00 could sensibly be on real hardware: right where the Key
# Assignments region starts (0xc0) -- R00 itself must be at least one
# register above that. A brand new, never-loaded Memory() decodes R00 as 0
# (register c, 0x0d, is all-zero before any real dump is loaded), which
# isn't a real partition boundary, just "there's no dump here yet". Treat
# anything below this as that case, rather than as a dump with an
# implausibly huge (up to 512-register) data segment.
MIN_SANE_R00 = 0xC1

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
