"""A site profile's screen (owner 2026-10-23): drawn from the profile's name alone, so the same profile presents the
same screen on every launch, in every process and on every machine, and the profiles together present every common
screen. What a page reads on it: `test_browser_fetch.py`."""

from crawlerai.acquire import desktop_screen as module
from crawlerai.acquire.desktop_screen import DesktopScreen, desktop_screen


def test_a_profile_has_one_screen_everywhere_and_the_profiles_cover_every_screen() -> None:
    names = [f"profile-{i}" for i in range(500)]

    drawn = [desktop_screen(name) for name in names]

    assert drawn == [desktop_screen(name) for name in names]
    assert set(drawn) == {screen for screen, _ in module._SCREENS}
    # A digest of the name, not Python's per-process `hash()`: the draw is the same in another process or machine.
    assert desktop_screen("profile-2") == DesktopScreen(1366, 768)
