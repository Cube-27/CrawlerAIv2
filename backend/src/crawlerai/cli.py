"""The `crawlerai` command-line entry point."""

import argparse
import asyncio
import json
import logging
import signal
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Final

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.acquire.browser import fetch_browser
from crawlerai.acquire.browser_session import open_browser
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.impersonate import rung_impersonation
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.api.app import create_app
from crawlerai.api.webhooks import poster
from crawlerai.core.data import fetch_data
from crawlerai.core.engine_version import ENGINE_VERSION, backend_dir, data_dir
from crawlerai.core.event_loop import quiet_peer_resets
from crawlerai.core.settings import AcquireSettings, DatabaseSettings, Settings
from crawlerai.db.keys import authenticate, create_key, hash_key, revoke_key
from crawlerai.db.models import ScheduleId
from crawlerai.job_cli import add_job_commands
from crawlerai.llm.client import NO_LLM
from crawlerai.llm.providers.from_settings import llm_from_settings
from crawlerai.normalize.dispatch import warm
from crawlerai.recurring.listing_diff import close_run
from crawlerai.scheduler.loop import periodic, run_scheduler
from crawlerai.schemas.registry import PresetConflict
from crawlerai.services import schedules as schedules_service
from crawlerai.services import schemas as schemas_service
from crawlerai.services.fetch_options import FetchOptions, UnknownProxyPool, check_proxy_pool, fetch_policy
from crawlerai.services.fetching import learning_replay
from crawlerai.services.page_store import learning_extract
from crawlerai.services.records import MAX_PAGE
from crawlerai.services.runtime import check_exits, load_drift_margins, load_engine_data, open_fetching
from crawlerai.services.schedules import ScheduleListQuery, ScheduleNotFound, Submitting
from crawlerai.services.scrape_paging import learning_render
from crawlerai.storage import open_store
from crawlerai.storage.capture_bundle import encode
from crawlerai.worker.handlers.table import task_handlers
from crawlerai.worker.learn import run_learner
from crawlerai.worker.loop import run_worker

# What `crawlerai schedules` prints of a schedule: enough to find it and see whether and when it runs.
_SCHEDULE_LINE: Final = {"id", "name", "kind", "cron", "interval_s", "timezone", "paused", "next_run_at", "last_job_id"}


def _print_openapi() -> None:
    # Sorted keys and LF bytes on every platform keep `frontend/openapi.json` byte-identical across regenerations,
    # which the CI freshness check relies on.
    text = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    sys.stdout.buffer.write(text.encode())


def _stop_on_signals() -> asyncio.Event:
    """An event set on SIGINT or SIGTERM, for a process to stop cleanly."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        # Not available on Windows, where Ctrl+C interrupts the process instead, and a worker's leases then expire.
        with suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, stop.set)
    return stop


async def _work() -> None:
    quiet_peer_resets(asyncio.get_running_loop())
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        async with open_fetching(settings, database=engine) as fetching:
            # The normalizers' all-locale tables are built before the first task, not by it.
            await asyncio.to_thread(warm)
            store, adapters = fetching.store, fetching.rungs.adapters
            llm, setup = llm_from_settings(settings, engine)
            data, margins = load_engine_data(adapters), load_drift_margins()
            handlers = task_handlers(fetching, data, margins, llm=llm)
            stop = _stop_on_signals()
            # A records crawl that completes is diffed against its earlier runs.
            work = [run_worker(settings, handlers, stop, ending=close_run), setup.verify()]
            if data is not None:  # learning reads the vocabulary from the data files
                learner = run_learner(
                    engine,
                    store,
                    llm,
                    stop,
                    vocabulary=data.vocabulary,
                    max_chars=settings.llm_a_max_chars,
                    replay=learning_replay(engine, fetching),
                    render=learning_render(engine, fetching),
                    extract=learning_extract(data, llm),
                )
                work.append(learner)
            await asyncio.gather(*work)
    finally:
        await engine.dispose()


async def _schedule() -> None:
    settings = Settings()
    fetch = partial(
        fetch_http,
        engine_version=ENGINE_VERSION,
        impersonate=await rung_impersonation(settings, browser_rung=True),  # its `open_fetching` renders too
        pools=settings.proxy_pools,
        direct=settings.direct,
    )
    # A schedule's run submits its job with the schema its creation resolved, so it drafts nothing: no LLM client.
    async with open_fetching(settings) as fetching:
        submitting = Submitting(fetching, load_engine_data(fetching.rungs.adapters), NO_LLM)
        entries = periodic(open_store(settings.object_store), fetch, poster(SafeConnector()), submitting)
        await run_scheduler(settings, entries, _stop_on_signals())


async def fetch_to_file(
    url: str,
    out: Path,
    connector: SafeConnector | None = None,
    options: FetchOptions | None = None,
    *,
    headful: bool = False,
) -> None:
    """Fetch `url` into a bundle at `out`: over HTTP, or in the browser when `options` ask for it or for page steps,
    with the caller's request context and proxy pool; `headful` runs the browser headful whatever
    `CRAWLERAI_BROWSER_HEADLESS` says."""
    settings = AcquireSettings()
    if headful:
        settings = settings.model_copy(update={"browser_headless": False})
    options = options or FetchOptions()
    policy = fetch_policy(options, None)
    check_exits(settings.proxy_pools, settings.direct)
    if options.in_browser:
        async with open_browser(
            settings.browser_profiles, settings.direct, headless=settings.browser_headless
        ) as session:
            result = await fetch_browser(
                url,
                policy,
                session=session,
                engine_version=ENGINE_VERSION,
                connector=connector,
                pools=settings.proxy_pools,
            )
    else:
        result = await fetch_http(
            url,
            policy,
            engine_version=ENGINE_VERSION,
            impersonate=await rung_impersonation(settings, browser_rung=False),
            connector=connector,
            pools=settings.proxy_pools,
            direct=settings.direct,
        )
    out.write_bytes(encode(result.bundle))
    manifest = result.bundle.manifest
    summary = {
        "capture_id": str(manifest.capture_id),
        "final_url": manifest.final_url,
        "status_code": manifest.status_code,
        "block_class": manifest.block_class,
        "error": result.attempts[-1].error,
    }
    if steps := result.attempts[-1].steps:
        summary["steps"] = [step.model_dump(mode="json") for step in steps]
    print(json.dumps(summary))


@asynccontextmanager
async def _transaction() -> AsyncIterator[AsyncConnection]:
    """One transaction on the configured database, for a command that writes once; the engine closes with it."""
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            yield conn
    finally:
        await engine.dispose()


async def _sync_presets() -> None:
    async with _transaction() as conn:
        written = await schemas_service.sync_presets(conn)
    for schema in written:
        print(f"wrote preset {schema.name}")
    print(f"{len(written)} preset(s) inserted or updated")


async def _apikey_create(label: str) -> None:
    async with _transaction() as conn:
        created = await create_key(conn, label)
    # The key is printed this once; only its hash is stored. The webhook secret, which verifies the
    # signature of the key's webhooks, is printed with it.
    print(
        json.dumps(
            {
                "id": str(created.id),
                "label": created.label,
                "key": created.key,
                "webhook_secret": created.webhook_secret,
            }
        )
    )


async def _apikey_ensure(label: str, path: Path) -> None:
    """Keep a live key for `label` in the file `path`: nothing to do while the key in it is unrevoked, else create one
    and write it there (the only copy outside its hash), for the process that attaches it to the web UI's requests."""
    async with _transaction() as conn:
        current = path.read_text(encoding="ascii").strip() if path.is_file() else ""
        if current and await authenticate(conn, hash_key(current)) is not None:
            return
        created = await create_key(conn, label)
    path.write_text(created.key, encoding="ascii")
    print(f"created the {label} API key in {path}")


async def _apikey_revoke(parser: argparse.ArgumentParser, key_id: uuid.UUID) -> None:
    async with _transaction() as conn:
        outcome = await revoke_key(conn, key_id)
    if outcome == "not_found":
        parser.exit(2, f"crawlerai apikey revoke: no API key {key_id}\n")
    print(json.dumps({"id": str(key_id), "revoked": outcome == "revoked"}))


async def _schedules_list() -> None:
    cursor: ScheduleId | None = None
    async with _transaction() as conn:
        while True:
            page = await schedules_service.list_schedules(conn, ScheduleListQuery(cursor=cursor, limit=MAX_PAGE))
            for schedule in page.items:
                print(schedule.model_dump_json(include=_SCHEDULE_LINE))
            if page.next_cursor is None:
                return
            cursor = page.next_cursor


async def _schedules_pause(parser: argparse.ArgumentParser, schedule_id: uuid.UUID, *, paused: bool) -> None:
    try:
        async with _transaction() as conn:
            schedule = await schedules_service.set_paused(conn, ScheduleId(schedule_id), paused=paused)
    except ScheduleNotFound as e:
        parser.exit(2, f"crawlerai schedules: {e}\n")
    print(schedule.model_dump_json(include=_SCHEDULE_LINE))


def main(argv: Sequence[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    # Each command's parser names its handler (`set_defaults(handler=...)`); no command runs nothing.
    handler = getattr(args, "handler", None)
    if handler is not None:
        handler(parser, args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crawlerai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('crawlerai')}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("openapi", help="print the API's OpenAPI document as JSON").set_defaults(handler=_run_openapi)
    commands.add_parser(
        "worker", help="run a worker: claim queued tasks and run them until SIGINT or SIGTERM"
    ).set_defaults(handler=_run_worker)
    commands.add_parser(
        "scheduler", help="run the scheduler: release expired leases, expire old data, re-check fetch methods"
    ).set_defaults(handler=_run_scheduler)
    fetch = commands.add_parser("fetch", help="fetch one URL over HTTP, or in the browser, into a capture bundle file")
    fetch.set_defaults(handler=_run_fetch)
    fetch.add_argument("url")
    fetch.add_argument(
        "--out", type=Path, required=True, help="the bundle file to write (zstd-compressed tar), under this directory"
    )
    _add_fetch_options(fetch)
    fetch.add_argument(
        "--headful", action="store_true", help="run the browser headful (CRAWLERAI_BROWSER_HEADLESS=false), this once"
    )
    schemas = commands.add_parser("schemas", help="schema definitions").add_subparsers(
        dest="schemas_command", required=True
    )
    schemas.add_parser("sync", help="insert or update the preset schemas in place (after migrating)").set_defaults(
        handler=_run_schemas
    )
    data = commands.add_parser("data", help="the pinned data files of backend/data/manifest.json").add_subparsers(
        dest="data_command", required=True
    )
    data.add_parser("fetch", help="download the fetched entries (schema.org) and check their sha256").set_defaults(
        handler=_run_data
    )
    apikey = commands.add_parser("apikey", help="API keys; the API never creates one").add_subparsers(
        dest="apikey_command", required=True
    )
    create = apikey.add_parser("create", help="create a key and print it, once, with its id")
    create.set_defaults(handler=_run_apikey_create)
    create.add_argument("--label", required=True, help="what the key is for")
    ensure = apikey.add_parser("ensure", help="keep a live key in a file, creating one when it holds none")
    ensure.set_defaults(handler=_run_apikey_ensure)
    ensure.add_argument("--label", required=True, help="what the key is for")
    ensure.add_argument("file", type=Path, help="the file that holds the key")
    revoke = apikey.add_parser("revoke", help="revoke a key: requests with it are refused from then on")
    revoke.set_defaults(handler=_run_apikey_revoke)
    revoke.add_argument("id", type=uuid.UUID, help="the key's id, as `apikey create` printed it")
    _add_schedule_commands(commands)
    add_job_commands(commands)
    return parser


def _add_schedule_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """`schedules list|pause|resume`: the recurring schedules (§22 "Recurring schedule storage"), one JSON line each;
    `/v1/schedules` creates and edits them."""
    schedules = commands.add_parser("schedules", help="recurring schedules: list, pause, resume").add_subparsers(
        dest="schedules_command", required=True
    )
    schedules.add_parser("list", help="print the schedules, newest first, one JSON line each").set_defaults(
        handler=_run_schedules_list
    )
    for name, help_ in (("pause", "stop a schedule's runs"), ("resume", "run a schedule again from its next time")):
        command = schedules.add_parser(name, help=help_)
        command.set_defaults(handler=_run_schedules_pause, paused=name == "pause")
        command.add_argument("id", type=uuid.UUID, help="the schedule's id")


def _under_cwd(parser: argparse.ArgumentParser, option: str, path: Path) -> Path:
    """`path` resolved against the working directory; a path argument never reaches outside it."""
    cwd = Path.cwd().resolve()
    resolved = (cwd / path).resolve()
    if not resolved.is_relative_to(cwd):
        parser.error(f"{option} must be under the working directory {cwd}")
    return resolved


def _run_openapi(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    _print_openapi()


def _log_to_stderr() -> None:
    """Send the package's INFO and above to stderr, for the long-running commands: the API's are uvicorn's to set up."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("crawlerai")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _run_worker(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    _log_to_stderr()
    asyncio.run(_work())


def _run_scheduler(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    _log_to_stderr()
    asyncio.run(_schedule())


def _run_fetch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # The bundle is written only under the working directory: a path argument never reaches elsewhere.
    out = _under_cwd(parser, "--out", args.out)
    options = _fetch_options(parser, args)
    try:
        check_proxy_pool(options, AcquireSettings().proxy_pools)
    except UnknownProxyPool as e:
        parser.error(str(e))
    asyncio.run(fetch_to_file(args.url, out, options=options, headful=args.headful))


def _add_fetch_options(fetch: argparse.ArgumentParser) -> None:
    """The request's `fetch` members as flags: the same names and checks as the API's."""
    fetch.add_argument("--browser", action="store_true", help="fetch in the browser rather than over HTTP")
    fetch.add_argument("--proxy-pool", help="a configured proxy pool (CRAWLERAI_PROXY_POOLS) to send through")
    fetch.add_argument(
        "--header", action="append", default=[], metavar="NAME:VALUE", help="a request header (HTTP only); repeats"
    )
    fetch.add_argument("--cookie", action="append", default=[], metavar="NAME=VALUE", help="a cookie; repeats")
    fetch.add_argument("--wait-for", metavar="MS|SELECTOR|network_idle", help="what the browser waits for first")
    fetch.add_argument(
        "--action", action="append", default=[], metavar="JSON", help='a page step, e.g. {"type": "click", ...}'
    )


def _fetch_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> FetchOptions:
    wait_for: int | str | None = args.wait_for
    if isinstance(wait_for, str) and wait_for.isdigit():
        wait_for = int(wait_for)
    try:
        return FetchOptions.model_validate(
            {
                "method_hint": "browser" if args.browser else "auto",
                "proxy_pool": args.proxy_pool,
                "headers": _pairs(args.header, ":"),
                "cookies": _pairs(args.cookie, "="),
                "wait_for": wait_for,
                "actions": [json.loads(action) for action in args.action],
            }
        )
    except (ValueError, ValidationError) as e:
        parser.error(f"invalid fetch options: {e}")


def _pairs(values: Sequence[str], separator: str) -> dict[str, str]:
    pairs = {}
    for value in values:
        name, found, rest = value.partition(separator)
        if not found:
            raise ValueError(f"expected NAME{separator}VALUE, got {name!r}")
        pairs[name.strip()] = rest.strip()
    return pairs


def _run_schemas(parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    try:
        asyncio.run(_sync_presets())
    except PresetConflict as e:
        parser.exit(2, f"crawlerai schemas sync: {e}\n")


def _run_apikey_create(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_apikey_create(args.label))


def _run_apikey_ensure(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_apikey_ensure(args.label, args.file))


def _run_apikey_revoke(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_apikey_revoke(parser, args.id))


def _run_schedules_list(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    asyncio.run(_schedules_list())


def _run_schedules_pause(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_schedules_pause(parser, args.id, paused=args.paused))


def _data_dir() -> Path | None:
    """`backend/data/` of the source tree this package runs from, where the pinned data files go; None for an
    installed package."""
    backend = backend_dir(Path(schemas_service.__file__))  # any module one package below `crawlerai`
    return None if backend is None else data_dir(backend)


def _run_data(parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    directory = _data_dir()
    if directory is None:
        parser.exit(2, "crawlerai data fetch: no backend source tree: data files are written to backend/data/\n")
    report = fetch_data(directory)
    for line in report.written:
        print(line)
    if report.refused:
        parser.exit(2, "".join(f"crawlerai data fetch: {line}\n" for line in report.refused))
