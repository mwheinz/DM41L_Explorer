"""
Small shared constants for sanity-checking R00 before trying to render
anything derived from it.
"""

# The lowest R00 could sensibly be on real hardware: right where the Key
# Assignments region starts (0xc0) -- R00 itself must be at least one
# register above that. A brand new, never-loaded Memory() decodes R00 as
# 0 (register c, 0x0d, is all-zero before any real dump is loaded), which
# isn't a real partition boundary, just "there's no dump here yet". Treat
# anything below this as that case, rather than as a dump with an
# implausibly huge (up to 512-register) data segment.
MIN_SANE_R00 = 0xC1
