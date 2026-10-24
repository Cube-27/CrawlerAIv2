"""The display a headful browser's windows open on (`SNOWCRAWL_BROWSER_HEADLESS=false`).

On Windows and macOS, and on a Linux desktop (`DISPLAY` set), it is the machine's own: the browser is a visible window.
On Linux with no X display (a container, a server), the process starts one virtual X display, an Xvfb server
(the X virtual framebuffer, through `xvfbwrapper`), the first time a headful driver starts, and keeps it until it
exits: `DISPLAY` names it, so the Playwright driver and every browser it starts, which inherit the process environment,
draw on it. Its one screen is the most common desktop screen (`acquire.desktop_screen`) at 24-bit colour.
"""

import atexit
import os
import sys
from typing import Final

__all__ = ["ensure_display"]

_WIDTH: Final = 1920
_HEIGHT: Final = 1080
_DEPTH: Final = 24
# The virtual display this process started, if any: one per process, for every driver it starts.
_STARTED: list[object] = []


def ensure_display() -> None:
    """Start the process's virtual display when it is on Linux with no X display (module docstring); else nothing.
    Raises `OSError` when Xvfb is not installed or does not start, as a browser that does not start does."""
    if _STARTED or not sys.platform.startswith("linux") or os.environ.get("DISPLAY"):
        return
    from xvfbwrapper import Xvfb  # Linux and macOS only: it imports fcntl

    display = Xvfb(width=_WIDTH, height=_HEIGHT, colordepth=_DEPTH)
    try:
        display.start()
    except RuntimeError as e:  # xvfbwrapper's: Xvfb exited or its display did not open in time
        raise OSError(f"the virtual display did not start: {e}") from e
    atexit.register(display.stop)
    _STARTED.append(display)
