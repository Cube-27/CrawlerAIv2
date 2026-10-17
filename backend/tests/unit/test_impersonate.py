"""Which Chrome the HTTP and JSON rungs impersonate (SPEC-02 §4.7, D-1325): the browser rung's Chromium major, read
from Patchright's `browsers.json`, or the nearest curl_cffi profile to it; an operator's explicit choice is kept."""

import json
import logging
from importlib.machinery import ModuleSpec
from itertools import pairwise
from pathlib import Path
from typing import get_args

import pytest
from curl_cffi.requests import BrowserTypeLiteral

from crawlerai.acquire import impersonate
from crawlerai.acquire.impersonate import browser_major, nearest_target, rung_impersonation
from crawlerai.core.settings import AcquireSettings

_PROFILES = sorted(
    int(name[6:]) for name in get_args(BrowserTypeLiteral) if name[6:].isdigit() and name[:6] == "chrome"
)


def test_the_nearest_profile_is_the_exact_major_when_curl_cffi_has_it() -> None:
    major = _PROFILES[len(_PROFILES) // 2]

    assert nearest_target(major) == f"chrome{major}"


def test_a_major_past_the_newest_profile_gets_the_newest() -> None:
    assert nearest_target(_PROFILES[-1] + 7) == f"chrome{_PROFILES[-1]}"


def test_a_tie_between_two_profiles_goes_to_the_newer() -> None:
    older, newer = next((a, b) for a, b in pairwise(_PROFILES) if (b - a) % 2 == 0)

    assert nearest_target((older + newer) // 2) == f"chrome{newer}"


def test_unset_the_target_follows_the_browser(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(impersonate, "browser_major", lambda: _PROFILES[-1] + 3)

    with caplog.at_level(logging.WARNING):
        target = rung_impersonation(AcquireSettings())

    assert target == f"chrome{_PROFILES[-1]}"
    assert f"Chromium {_PROFILES[-1] + 3}" in caplog.text


def test_an_explicit_target_is_kept_with_a_warning_when_it_differs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(impersonate, "browser_major", lambda: _PROFILES[-1])
    monkeypatch.setenv("CRAWLERAI_IMPERSONATE", f"chrome{_PROFILES[0]}")

    with caplog.at_level(logging.WARNING):
        target = rung_impersonation(AcquireSettings())

    assert target == f"chrome{_PROFILES[0]}"
    assert "differs" in caplog.text


def test_a_matching_target_is_kept_silently(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(impersonate, "browser_major", lambda: _PROFILES[0])
    monkeypatch.setenv("CRAWLERAI_IMPERSONATE", f"chrome{_PROFILES[0]}")

    with caplog.at_level(logging.WARNING):
        assert rung_impersonation(AcquireSettings()) == f"chrome{_PROFILES[0]}"

    assert caplog.text == ""


def test_the_browser_major_is_read_from_patchrights_browsers_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "patchright"
    (package / "driver" / "package").mkdir(parents=True)
    browsers = {
        "browsers": [{"name": "firefox", "browserVersion": "9.0"}, {"name": "chromium", "browserVersion": "140.0.1"}]
    }
    (package / "driver" / "package" / "browsers.json").write_text(json.dumps(browsers), encoding="utf-8")
    monkeypatch.setattr(
        impersonate, "find_spec", lambda _name: ModuleSpec("patchright", None, origin=str(package / "__init__.py"))
    )
    browser_major.cache_clear()
    try:
        assert browser_major() == 140
    finally:
        browser_major.cache_clear()


def test_without_the_browsers_file_there_is_no_major(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        impersonate, "find_spec", lambda _name: ModuleSpec("patchright", None, origin=str(tmp_path / "x.py"))
    )
    browser_major.cache_clear()
    try:
        assert browser_major() is None
    finally:
        browser_major.cache_clear()
