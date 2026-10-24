"""Site profiles (`acquire.browser_profiles`): one holder at a time, a temporary profile for the next, which is deleted
when it closes, and a discarded profile deleted. No browser runs."""

import json
from pathlib import Path

from snowcrawl.acquire.browser_profiles import discard_profile, open_profile, profile_name


def test_a_held_profile_gives_the_next_holder_a_temporary_one_and_a_discard_waits_for_its_release(
    tmp_path: Path,
) -> None:
    name = profile_name("example.test", None, None)
    held = open_profile(tmp_path, name)
    other = open_profile(tmp_path, name)

    assert held.directory == tmp_path / name
    assert other.directory.parent != tmp_path
    preferences = json.loads((other.directory / "Default" / "Preferences").read_text())
    assert preferences["webrtc"]["ip_handling_policy"] == "disable_non_proxied_udp"
    other.close()
    assert not other.directory.exists()

    discard_profile(tmp_path, name)
    assert held.directory.exists()
    held.close()
    discard_profile(tmp_path, name)
    assert not held.directory.exists()
