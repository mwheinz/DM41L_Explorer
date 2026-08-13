"""
Shared layout helpers so the tab modules (Flags, Data Registers, XM Files,
...) don't each hand-roll a slightly different header row and drift apart
visually over time.
"""

import customtkinter as ctk

# Font family used for any field that displays or edits raw register/file
# *content* (hex bytes, addresses, decoded numbers, alpha text) -- as
# opposed to labels, names, or descriptive prose. A fixed-width font keeps
# these fields' columns aligned and makes it easy to eyeball hex digit
# counts. Centralized here so every tab/dialog that shows register content
# uses the same family instead of each hard-coding "Courier" separately.
MONOSPACE_FONT_FAMILY = "Courier"

# Alternating-row background shade, shared by every tab with a table (Data
# Registers' ttk.Treeview, and the XM Files/Programs tabs' CTkScrollableFrame
# grids) so odd rows get the exact same subtle tint everywhere instead of
# each tab inventing its own slightly different color. Values match what
# data_registers_tab.py used before this was centralized here.
STRIPE_BG_DARK = "#2b2b2b"
STRIPE_BG_LIGHT = "#f4f4f4"


def stripe_bg_color() -> str:
    """The alternating-row background color for the current appearance
    mode (dark vs. light)."""
    return STRIPE_BG_DARK if ctk.get_appearance_mode() == "Dark" else STRIPE_BG_LIGHT


def build_tab_header(master, button_kwargs: dict = None):
    """Builds the standard fixed tab header: a bold status label on the
    left (defaulting to the shared "no memory loaded" text every tab
    shows before a dump is loaded) and, optionally, a single primary
    action button on the right.

    Packed into `master` with the same padding every tab uses, so the
    header stays put at the top of the tab while whatever scrollable
    body sits below it does the scrolling.

    `button_kwargs`, if given, is passed straight through to CTkButton
    (e.g. {"text": "Add File...", "width": 100, "command": ...}).

    Returns (header_frame, status_label).
    """
    header = ctk.CTkFrame(master, fg_color="transparent")
    header.pack(fill="x", padx=8, pady=8)

    label = ctk.CTkLabel(
        header, text="(no memory dump loaded)", font=ctk.CTkFont(weight="bold")
    )
    label.pack(side="left")

    if button_kwargs:
        ctk.CTkButton(header, **button_kwargs).pack(side="right")

    return header, label
