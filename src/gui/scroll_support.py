"""
macOS trackpad ("Magic Trackpad" / built-in trackpad two-finger scroll)
support for CTkScrollableFrame.

Ported from Project Voyager's gui/memory_view.py. CustomTkinter's
CTkScrollableFrame wraps a plain Canvas that, on macOS, doesn't respond to
a trackpad scroll gesture the way native widgets do -- only Tk's
synthesized <TouchpadScroll> event carries that gesture, and nothing wires
it to the canvas by default. Without this, scrolling one of these frames
only works with an external mouse wheel (or a Magic Mouse), not the
trackpad.

Native ttk widgets (e.g. ttk.Treeview, used by the Data Registers tab)
don't need this -- they already receive trackpad scroll events correctly
on their own.

<TouchpadScroll> is a macOS-only virtual event -- Tk's X11 build (Linux)
doesn't define it at all, and registering a bind_all() for an unknown
event type raises TclError immediately (confirmed while testing this in
a Linux sandbox). Non-macOS platforms fall back to whatever normal
<MouseWheel>/<Button-4>/<Button-5> handling CTkScrollableFrame already has
built in, so this is skipped there rather than guessed at.
"""

import logging
import platform

logger = logging.getLogger(__name__)

PLATFORM_SYSTEM = platform.system()


def bind_touchpad_scroll(scrollable_frame):
    """Enables trackpad scrolling on a CTkScrollableFrame. Call once per
    frame, after it's been created. No-op on non-macOS platforms."""
    if PLATFORM_SYSTEM != "Darwin":
        return

    def _decode_touchpad_delta(raw_delta):
        raw = raw_delta & 0xFFFFFFFF
        delta_y = raw & 0xFFFF
        delta_x = (raw >> 16) & 0xFFFF
        if delta_y >= 0x8000:
            delta_y -= 0x10000
        if delta_x >= 0x8000:
            delta_x -= 0x10000
        return delta_x, delta_y

    def _trackpad_scroll(event):
        # <TouchpadScroll> is delivered via bind_all (see below), so every
        # frame using this helper gets a callback on every trackpad
        # gesture anywhere in the window, not just ones over its own
        # area -- winfo_ismapped() is what limits the actual scrolling to
        # whichever tab is actually visible right now.
        if not scrollable_frame.winfo_ismapped():
            return None
        _, delta_y = _decode_touchpad_delta(event.delta)
        # yview() == (0.0, 1.0) means the whole scrollregion is already
        # visible -- i.e. this tab's content fits inside the window with
        # room to spare. Tk's Canvas doesn't clamp yview_scroll() to a
        # no-op in that case the way it does once content overflows: when
        # the scrollregion is smaller than the canvas, yview_scroll happily
        # slides the (already fully visible) content around inside the
        # extra space instead of refusing the move, which is exactly what
        # let a two-finger trackpad gesture drag Overview's cards up/down
        # even though nothing was actually clipped. Mirrors the same guard
        # CTkScrollableFrame's own built-in `_mouse_wheel_all()` already
        # uses for regular <MouseWheel>/<Button-4>/<Button-5> scrolling
        # (see customtkinter/windows/widgets/ctk_scrollable_frame.py) --
        # <TouchpadScroll> just never had it, since this handler is this
        # project's own addition, not part of CTkScrollableFrame itself.
        if delta_y and scrollable_frame._parent_canvas.yview() != (0.0, 1.0):
            scrollable_frame._parent_canvas.yview_scroll(-delta_y, "units")
        return "break"

    # bind_all (not bind): the event's target widget is whatever's under
    # the cursor -- often a child label/checkbox, not the scrollable frame
    # itself -- so a plain instance-level bind() would frequently miss it.
    try:
        scrollable_frame.bind_all("<TouchpadScroll>", _trackpad_scroll, add="+")
    except Exception as e:
        # Defensive: some Tk/Aqua build without this virtual event
        # shouldn't take the whole app down over a scroll nicety.
        logger.debug("Could not bind <TouchpadScroll>: %s", e)
