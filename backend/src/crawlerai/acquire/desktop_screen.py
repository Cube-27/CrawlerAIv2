"""The desktop screen a site profile's browser presents (owner 2026-10-23): one of the common desktop screens, the same
for the profile on every launch, in every process and on every machine, rather than one size for every profile.

The screen is Chrome headless mode's virtual screen (`--screen-info`, Chromium components/headless/screen_info), its
work area that screen less a taskbar at the bottom, and the window maximised in it (`--window-size`, at the work area's
origin): the page reads `screen.width` >= `outerWidth` >= `innerWidth`, `screen.availHeight` = `screen.height` less the
taskbar = `outerHeight`, and `outerHeight` - `innerHeight` = the height of the browser's own toolbars, which Chrome
reserves itself. Nothing is emulated (no Playwright viewport, `Emulation.setDeviceMetricsOverride`): the page lays out
in the window as in a user's browser.
"""

import hashlib
from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from typing import Final

__all__ = ["DesktopScreen", "desktop_screen"]


@dataclass(frozen=True)
class DesktopScreen:
    """A desktop screen as a page reads it (CSSOM View `screen.width`/`height`, in CSS pixels) and its
    `devicePixelRatio`."""

    width: int
    height: int
    scale: float = 1.0

    def launch_args(self) -> list[str]:
        """Chrome's switches for this screen: `--screen-info` takes physical pixels, `--window-size` and
        `--window-position` CSS pixels."""
        physical = f"{round(self.width * self.scale)}x{round(self.height * self.scale)}"
        taskbar = round(_TASKBAR * self.scale)
        return [
            f"--screen-info={{{physical} devicePixelRatio={self.scale:g} workAreaBottom={taskbar}}}",
            "--window-position=0,0",
            f"--window-size={self.width},{self.height - _TASKBAR}",
        ]


# StatCounter Global Stats, desktop screen resolution worldwide, September 2026: the five most common screens by share
# (in hundredths of a percent), as pages read them in CSS pixels. 1280x1200 (3.64%, sixth) is left out: no desktop
# display has its 16:15 shape. 1536x864 and 1280x720 are 1920x1080 panels at Windows' 125% and 150% display scaling
# (CSSOM View: CSS pixels are device pixels divided by `devicePixelRatio`); the others are read at 100%.
_SCREENS: Final = (
    (DesktopScreen(1920, 1080), 2807),
    (DesktopScreen(1536, 864, 1.25), 1000),
    (DesktopScreen(1366, 768), 795),
    (DesktopScreen(1280, 720, 1.5), 471),
    (DesktopScreen(2560, 1440), 395),
)
_BOUNDS: Final = tuple(accumulate(weight for _, weight in _SCREENS))
# The Windows 11 taskbar's height in CSS pixels at any scaling, at the bottom of the screen: the most common desktop
# work area.
_TASKBAR: Final = 48


def desktop_screen(profile: str) -> DesktopScreen:
    """The screen of the profile named `profile` (`acquire.browser_profiles.profile_name`), drawn by the screens'
    shares from a SHA-256 digest of the name, so a profile has the same screen wherever it is opened."""
    point = int.from_bytes(hashlib.sha256(profile.encode()).digest()[:8], "big") % _BOUNDS[-1]
    return _SCREENS[bisect_right(_BOUNDS, point)][0]
