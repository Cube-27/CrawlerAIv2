import asyncio
import json
import shutil
import subprocess
import sysconfig
from datetime import timedelta
from functools import partial
from pathlib import Path

import pytest

from crawlerai import cli
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.cli import main
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.settings import AcquireSettings, Settings
from crawlerai.scheduler.loop import periodic
from crawlerai.storage.fs import FsStore


def test_version_flag_prints_package_version_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "crawlerai 0.1.0\n"


def test_installed_console_script_reports_version() -> None:
    script = shutil.which("crawlerai", path=sysconfig.get_path("scripts"))
    assert script is not None, "the `crawlerai` console script is not installed in this environment"

    result = subprocess.run([script, "--version"], capture_output=True, text=True, check=False)  # noqa: S603

    assert result.returncode == 0
    assert result.stdout == "crawlerai 0.1.0\n"


def test_openapi_prints_the_app_schema_as_sorted_json_with_trailing_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["openapi"])

    out = capsys.readouterr().out
    document = json.loads(out)
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "CrawlerAI"
    assert sorted(document["paths"]) == [
        "/healthz",
        "/v1/eval/capture",
        "/v1/eval/pages",
        "/v1/eval/pages/{page_id}",
        "/v1/eval/pages/{page_id}/labels",
        "/v1/eval/pages/{page_id}/normalize",
        "/v1/eval/pages/{page_id}/prefill",
    ]
    assert out == json.dumps(document, indent=2, sort_keys=True) + "\n"


def test_installed_console_script_writes_identical_lf_only_openapi_on_every_run() -> None:
    script = shutil.which("crawlerai", path=sysconfig.get_path("scripts"))
    assert script is not None, "the `crawlerai` console script is not installed in this environment"

    runs = [subprocess.run([script, "openapi"], capture_output=True, check=True).stdout for _ in range(2)]  # noqa: S603

    assert runs[0] == runs[1]
    assert b"\r" not in runs[0]
    assert runs[0].endswith(b"}\n")


def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai")
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///srv/objects")


def test_the_worker_command_runs_its_loop_with_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _environment(monkeypatch)
    calls: list[tuple[str, object, bool]] = []

    async def run(settings: Settings, handlers: object, stop: asyncio.Event) -> None:
        calls.append((settings.database_url.get_secret_value(), handlers, stop.is_set()))

    monkeypatch.setattr(cli, "run_worker", run)

    main(["worker"])

    assert calls == [("postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai", {}, False)]


def test_the_scheduler_command_runs_the_entries_for_the_configured_object_store_and_the_http_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch)
    calls: list[tuple[str, object, bool]] = []

    async def run(settings: Settings, entries: object, stop: asyncio.Event) -> None:
        calls.append((settings.database_url.get_secret_value(), entries, stop.is_set()))

    monkeypatch.setattr(cli, "run_scheduler", run)
    monkeypatch.setattr(cli, "open_store", lambda url: ("store at", url))
    fetches: list[object] = []

    def entries_for(store: object, fetch: object) -> tuple[str, object]:
        fetches.append(fetch)
        return ("entries for", store)

    monkeypatch.setattr(cli, "periodic", entries_for)

    main(["scheduler"])

    expected_entries = ("entries for", ("store at", "fs:///srv/objects"))
    assert calls == [("postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai", expected_entries, False)]
    [fetch] = fetches
    assert isinstance(fetch, partial)
    assert (fetch.func, fetch.args) == (fetch_http, ())
    assert fetch.keywords == {
        "policy": FetchPolicy(),
        "engine_version": ENGINE_VERSION,
        "impersonate": AcquireSettings().impersonate,
    }


def test_the_scheduler_releases_leases_every_minute_and_expires_and_rechecks_hourly() -> None:
    async def fetch(url: str) -> FetchResult:
        raise AssertionError("not called")

    entries = periodic(FsStore(Path("unused")), fetch)

    assert [(entry.name, entry.interval, entry.batch) for entry in entries] == [
        ("release_expired_leases", timedelta(minutes=1), None),
        ("expire_captures", timedelta(hours=1), 1000),
        ("expire_candidates", timedelta(hours=1), 1000),
        ("recheck_fetch_method", timedelta(hours=1), 1),
    ]
