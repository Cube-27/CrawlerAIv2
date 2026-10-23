"""The display a headful browser's windows open on (`CRAWLERAI_BROWSER_HEADLESS=false`).

On Windows and macOS, and on a Linux desktop (`DISPLAY` set), it is the machine's own: the browser is a visible window.
On Linux with no X display (a container, a server), the process starts one virtual X display, an Xvfb server
(X.Org's X virtual framebuffer, through `xvfbwrapper`), the first time a headful driver starts, and keeps it until it
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
    Raises `FileNotFoundError` when Xvfb is not installed, `RuntimeError` when it does not start."""
    if _STARTED or not sys.platform.startswith("linux") or os.environ.get("DISPLAY"):
        return
    from xvfbwrapper import Xvfb  # Linux and macOS only: it imports fcntl

    display = Xvfb(width=_WIDTH, height=_HEIGHT, colordepth=_DEPTH)
    display.start()
    atexit.register(display.stop)
    _STARTED.append(display)
