import asyncio
import json
import logging
import shutil
import subprocess
import sysconfig
from collections.abc import Iterator, Mapping
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from crawlerai import cli
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.impersonate import rung_impersonation
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.cli import main
from crawlerai.core.data import DataReport
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.proxy import ProxyEndpoint, ProxyPool
from crawlerai.core.settings import AcquireSettings, Settings
from crawlerai.db.queue import LEASE_BATCH
from crawlerai.llm.client import NO_LLM
from crawlerai.recurring.listing_diff import close_run
from crawlerai.scheduler.loop import periodic
from crawlerai.services.fetching import Fetching
from crawlerai.services.schedules import Submitting
from crawlerai.storage.fs import FsStore


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
    # The document includes the eval routes, which `frontend/openapi.json` is generated with.
    assert {"/healthz", "/v1/scrape", "/v1/eval/pages"} <= set(document["paths"])
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

    learners: list[tuple[object, int, bool, bool, bool]] = []

    async def learn(*args: object, vocabulary: object, max_chars: int, replay: object, render: object) -> None:
        stop = args[3]
        assert isinstance(stop, asyncio.Event)
        learners.append((vocabulary, max_chars, stop.is_set(), callable(replay), callable(render)))

    vocabulary = object()
    monkeypatch.setattr(cli, "run_worker", run)
    monkeypatch.setattr(cli, "run_learner", learn)
    monkeypatch.setattr(cli, "load_engine_data", lambda _adapters: SimpleNamespace(vocabulary=vocabulary))
    monkeypatch.setenv("CRAWLERAI_LLM_A_MAX_CHARS", "5000")

    main(["worker"])

    # A records crawl that completes is diffed against its earlier runs (SPEC-11 §4.5).
    url = "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai"
    assert calls == [(url, ["batch_scrape", "crawl", "extract"], False, close_run)]
    # Learn jobs have no tasks: the worker's learner runs them beside the task loop (D-0624), replaying recipes over
    # the JSON rung (SPEC-09 §2) and rendering pages without calls in the browser (Appendix A #59).
    assert learners == [(vocabulary, 5000, False, True, True)]


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

    submittings: list[object] = []

    def entries_for(store: object, fetch: object, post: object, submitting: object) -> tuple[str, object]:
        fetches.append(fetch)
        posts.append(post)
        submittings.append(submitting)
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
        "impersonate": rung_impersonation(AcquireSettings()),
        "pools": {"dc": ProxyPool((ProxyEndpoint("proxy.example.com", 3128),))},
    }
    [post] = posts  # webhooks go through the SSRF guard (SPEC-10 §4.2)
    assert isinstance(post, partial)
    assert type(post.keywords["connector"]) is SafeConnector
    [submitting] = submittings  # a schedule's run drafts nothing: its schema was resolved when it was created
    assert isinstance(submitting, Submitting)
    assert submitting.llm is NO_LLM


@pytest.fixture
def crawlerai_logger() -> Iterator[None]:
    """The package's logger, its handlers and level restored after the test."""
    logger = logging.getLogger("crawlerai")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)


@pytest.mark.usefixtures("crawlerai_logger")
@pytest.mark.parametrize(("command", "runner"), [("worker", "_work"), ("scheduler", "_schedule")])
def test_the_long_running_commands_log_info_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str, runner: str
) -> None:
    logger = logging.getLogger(f"crawlerai.{command}.loop")

    async def run() -> None:
        logger.info("started")
        logger.debug("idle")

    monkeypatch.setattr(cli, runner, run)

    main([command])

    lines = capsys.readouterr().err.splitlines()
    assert [line.split(" ", 2)[2] for line in lines] == [f"INFO crawlerai.{command}.loop: started"]


def test_a_job_its_last_expired_lease_ends_is_diffed() -> None:
    # SPEC-11 §4.5: the lease-release entry ends a job the way the worker does.
    async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("not called")

    async def post(url: str, body: bytes, headers: Mapping[str, str]) -> int:
        raise AssertionError("not called")

    store = FsStore(Path("unused"))
    fetching = Fetching(Rungs(http=fetch, browser=fetch), SafeConnector(), store, HostLimiter())
    entries = periodic(store, fetch, post, Submitting(fetching, None, NO_LLM))

    (release,) = (entry.run for entry in entries if entry.name == "release_expired_leases")
    assert isinstance(release, partial)
    assert release.keywords == {"batch": LEASE_BATCH, "ending": close_run}


def test_data_fetch_reports_each_fetched_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)

    def fetch_data(directory: Path) -> DataReport:
        calls.append(directory)
        return DataReport(written=["present schemaorg/vocabulary.jsonld", "fetched publicsuffix/list.dat"], refused=[])

    monkeypatch.setattr(cli, "fetch_data", fetch_data)

    main(["data", "fetch"])

    assert calls == [tmp_path]
    assert capsys.readouterr().out == "present schemaorg/vocabulary.jsonld\nfetched publicsuffix/list.dat\n"


def test_data_fetch_reports_every_entry_then_exits_2_on_a_refused_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)
    report = DataReport(
        written=["fetched schemaorg/vocabulary.jsonld"],
        refused=["publicsuffix/list.dat: sha256 0 does not match the manifest", "other.txt: download failed: x"],
    )
    monkeypatch.setattr(cli, "fetch_data", lambda _directory: report)

    with pytest.raises(SystemExit) as exit_info:
        main(["data", "fetch"])

    assert exit_info.value.code == 2
    assert capsys.readouterr() == (
        "fetched schemaorg/vocabulary.jsonld\n",
        "crawlerai data fetch: publicsuffix/list.dat: sha256 0 does not match the manifest\n"
        "crawlerai data fetch: other.txt: download failed: x\n",
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
