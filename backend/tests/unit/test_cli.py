import asyncio
import json
import shutil
import subprocess
import sysconfig
from collections.abc import Mapping
from datetime import timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from crawlerai import cli
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.cli import main
from crawlerai.core.data import DataFetchError
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.proxy import ProxyEndpoint
from crawlerai.core.settings import AcquireSettings, Settings
from crawlerai.recurring.listing_diff import close_run
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
        "/v1/batch/scrape",
        "/v1/captures/{capture_id}/replay",
        "/v1/configs/{config_id}",
        "/v1/configs/{config_id}/export",
        "/v1/crawl",
        "/v1/eval/capture",
        "/v1/eval/pages",
        "/v1/eval/pages/{page_id}",
        "/v1/eval/pages/{page_id}/labels",
        "/v1/eval/pages/{page_id}/normalize",
        "/v1/eval/pages/{page_id}/prefill",
        "/v1/extract",
        "/v1/jobs",
        "/v1/jobs/{job_id}",
        "/v1/jobs/{job_id}/events",
        "/v1/jobs/{job_id}/results",
        "/v1/map",
        "/v1/records",
        "/v1/schemas",
        "/v1/schemas/{schema_id}",
        "/v1/scrape",
        "/v1/sites/{host}/configs",
        "/v1/sites/{host}/learn",
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
    calls: list[tuple[str, list[str], bool, object]] = []

    async def run(settings: Settings, handlers: Mapping[str, object], stop: asyncio.Event, *, ending: object) -> None:
        calls.append((settings.database_url.get_secret_value(), sorted(handlers), stop.is_set(), ending))

    learners: list[tuple[object, int, bool]] = []

    async def learn(*args: object, vocabulary: object, max_chars: int) -> None:
        stop = args[3]
        assert isinstance(stop, asyncio.Event)
        learners.append((vocabulary, max_chars, stop.is_set()))

    vocabulary = object()
    monkeypatch.setattr(cli, "run_worker", run)
    monkeypatch.setattr(cli, "run_learner", learn)
    monkeypatch.setattr(cli, "load_engine_data", lambda: SimpleNamespace(vocabulary=vocabulary))
    monkeypatch.setenv("CRAWLERAI_LLM_A_MAX_CHARS", "5000")

    main(["worker"])

    # A records crawl that completes is diffed against its earlier runs (SPEC-11 §4.5).
    url = "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai"
    assert calls == [(url, ["batch_scrape", "crawl", "extract"], False, close_run)]
    # Learn jobs have no tasks: the worker's learner runs them beside the task loop (D-0624).
    assert learners == [(vocabulary, 5000, False)]


def test_the_scheduler_command_runs_the_entries_for_the_configured_object_store_and_the_http_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch)
    monkeypatch.setenv("CRAWLERAI_PROXY_POOLS", '{"dc": "http://proxy.example.com:3128"}')
    calls: list[tuple[str, object, bool]] = []

    async def run(settings: Settings, entries: object, stop: asyncio.Event) -> None:
        calls.append((settings.database_url.get_secret_value(), entries, stop.is_set()))

    monkeypatch.setattr(cli, "run_scheduler", run)
    monkeypatch.setattr(cli, "open_store", lambda url: ("store at", url))
    fetches: list[object] = []
    posts: list[object] = []

    def entries_for(store: object, fetch: object, post: object) -> tuple[str, object]:
        fetches.append(fetch)
        posts.append(post)
        return ("entries for", store)

    monkeypatch.setattr(cli, "periodic", entries_for)

    main(["scheduler"])

    expected_entries = ("entries for", ("store at", "fs:///srv/objects"))
    assert calls == [("postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai", expected_entries, False)]
    [fetch] = fetches
    assert isinstance(fetch, partial)
    assert (fetch.func, fetch.args) == (fetch_http, ())
    assert fetch.keywords == {
        "engine_version": ENGINE_VERSION,
        "impersonate": AcquireSettings().impersonate,
        "pools": {"dc": ProxyEndpoint("proxy.example.com", 3128)},
    }
    [post] = posts  # webhooks go through the SSRF guard (SPEC-10 §4.2)
    assert isinstance(post, partial)
    assert type(post.keywords["connector"]) is SafeConnector


def test_the_scheduler_entries_and_their_intervals() -> None:
    async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("not called")

    async def post(url: str, body: bytes, headers: Mapping[str, str]) -> int:
        raise AssertionError("not called")

    entries = periodic(FsStore(Path("unused")), fetch, post)

    assert [(entry.name, entry.interval, entry.batch) for entry in entries] == [
        ("release_expired_leases", timedelta(minutes=1), None),
        ("expire_captures", timedelta(hours=1), 1000),
        ("expire_candidates", timedelta(hours=1), 1000),
        ("recheck_fetch_method", timedelta(hours=1), 1),
        ("trigger_learning", timedelta(minutes=1), 100),
        ("expire_learn_runs", timedelta(minutes=5), 100),
        ("deliver_webhooks", timedelta(seconds=5), 1),
    ]
    # A job its last expired lease ends is diffed too (SPEC-11 §4.5).
    release = entries[0].run
    assert isinstance(release, partial)
    assert release.keywords == {"ending": close_run}


def test_data_fetch_reports_each_fetched_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)

    def fetch_data(directory: Path) -> list[str]:
        calls.append(directory)
        return ["present geonames/countryInfo.txt", "fetched geonames/cities15000.zip"]

    monkeypatch.setattr(cli, "fetch_data", fetch_data)

    main(["data", "fetch"])

    assert calls == [tmp_path]
    assert capsys.readouterr().out == "present geonames/countryInfo.txt\nfetched geonames/cities15000.zip\n"


def test_data_fetch_exits_2_on_a_refused_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)

    def fetch_data(directory: Path) -> list[str]:
        raise DataFetchError("geonames/countryInfo.txt: sha256 0 does not match the manifest")

    monkeypatch.setattr(cli, "fetch_data", fetch_data)

    with pytest.raises(SystemExit) as exit_info:
        main(["data", "fetch"])

    assert exit_info.value.code == 2
    assert capsys.readouterr().err == (
        "crawlerai data fetch: geonames/countryInfo.txt: sha256 0 does not match the manifest\n"
    )


@pytest.mark.parametrize(
    "argv",
    [["apikey", "create"], ["apikey", "revoke", "not-a-uuid"], ["apikey"]],
    ids=["create-without-label", "revoke-without-uuid", "no-subcommand"],
)
def test_apikey_arguments_are_checked_before_the_database_is_opened(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == 2
