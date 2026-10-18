"""Which Chrome the HTTP and JSON rungs impersonate (SPEC-02 §4.7, D-1325): the browser rung's Chromium major, read
from Patchright's `browsers.json`, or the nearest curl_cffi profile to it; an operator's explicit choice is kept."""

import json
import logging
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import get_args

import pytest
from curl_cffi.requests import BrowserTypeLiteral

from crawlerai.acquire import impersonate
from crawlerai.acquire.impersonate import browser_major, rung_impersonation
from crawlerai.core.settings import AcquireSettings

_PROFILES = sorted(
    int(name[6:]) for name in get_args(BrowserTypeLiteral) if name[6:].isdigit() and name[:6] == "chrome"
)


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
