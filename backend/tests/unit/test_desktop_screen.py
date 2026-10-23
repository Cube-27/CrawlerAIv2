"""A site profile's screen (owner 2026-10-23): drawn from the profile's name alone, so the same profile presents the
same screen on every launch, in every process and on every machine, and the profiles together present every common
screen. What a page reads on it: `test_browser_fetch.py`."""

import os
import subprocess
import sys

from crawlerai.acquire import desktop_screen as module
from crawlerai.acquire.desktop_screen import desktop_screen

_COUNT = 500
# The draws of `_COUNT` profile names, as another process prints them.
_DRAW = f"""from crawlerai.acquire.desktop_screen import desktop_screen
print([desktop_screen(f"profile-{{i}}") for i in range({_COUNT})])"""


def test_a_profile_has_one_screen_everywhere_and_the_profiles_cover_every_screen() -> None:
    drawn = [desktop_screen(f"profile-{i}") for i in range(_COUNT)]

    assert set(drawn) == {screen for screen, _ in module._SCREENS}
    # Another process, with another salt for Python's per-process `hash()`, draws the same screens.
    seed = "2" if os.environ.get("PYTHONHASHSEED") == "1" else "1"
    other = subprocess.run(  # noqa: S603  (this interpreter, a constant script)
        [sys.executable, "-c", _DRAW], env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True, text=True
    )
    assert (other.returncode, other.stdout.strip()) == (0, str(drawn))
