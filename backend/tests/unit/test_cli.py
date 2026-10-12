import asyncio
import json
import shutil
import subprocess
import sysconfig
from datetime import timedelta

import pytest

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.core.settings import Settings
from crawlerai.scheduler.loop import PERIODIC


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
    assert list(document["paths"]) == ["/healthz"]
    assert out == json.dumps(document, indent=2, sort_keys=True) + "\n"


def test_installed_console_script_writes_identical_lf_only_openapi_on_every_run() -> None:
    script = shutil.which("crawlerai", path=sysconfig.get_path("scripts"))
    assert script is not None, "the `crawlerai` console script is not installed in this environment"

    runs = [subprocess.run([script, "openapi"], capture_output=True, check=True).stdout for _ in range(2)]  # noqa: S603

    assert runs[0] == runs[1]
    assert b"\r" not in runs[0]
    assert runs[0].endswith(b"}\n")


def test_worker_runs_the_worker_loop_with_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai")
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///srv/objects")
    calls: list[tuple[str, dict[str, object], bool]] = []

    async def run_worker(settings: Settings, handlers: dict[str, object], stop: asyncio.Event) -> None:
        calls.append((settings.database_url.get_secret_value(), handlers, stop.is_set()))

    monkeypatch.setattr(cli, "run_worker", run_worker)

    main(["worker"])

    assert calls == [("postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai", {}, False)]


def test_scheduler_runs_the_scheduler_loop_with_its_periodic_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai")
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///srv/objects")
    calls: list[tuple[str, object, bool]] = []

    async def run_scheduler(settings: Settings, entries: object, stop: asyncio.Event) -> None:
        calls.append((settings.database_url.get_secret_value(), entries, stop.is_set()))

    monkeypatch.setattr(cli, "run_scheduler", run_scheduler)

    main(["scheduler"])

    assert calls == [("postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai", PERIODIC, False)]


def test_the_scheduler_releases_expired_leases_every_minute() -> None:
    assert [(entry.name, entry.interval) for entry in PERIODIC] == [("release_expired_leases", timedelta(minutes=1))]
