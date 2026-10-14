"""The `crawlerai` command-line entry point."""

import argparse
import asyncio
import json
import signal
import sys
import uuid
from collections.abc import Sequence
from contextlib import aclosing, suppress
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import get_args

from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.browser import BrowserSession, fetch_browser, open_browser
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.api.keys import create_key, revoke_key
from crawlerai.api.webhooks import poster
from crawlerai.core.data import DataFetchError, fetch_data
from crawlerai.core.engine_version import ENGINE_VERSION, backend_dir, data_dir
from crawlerai.core.settings import AcquireSettings, DatabaseSettings, Settings
from crawlerai.db.models import EvalCategory, EvalRunId, JobKind, PageKind, Split
from crawlerai.eval import calibrate, promote
from crawlerai.eval.cli import EvalCliError, PageRequest, check_urls, parse_site_list, report, run_capture
from crawlerai.eval.store import (
    EvalNotFound,
    PrivateCredentialsMissing,
    PrivateStoreNotSeparate,
    dev_store,
    private_store,
)
from crawlerai.scheduler.loop import periodic, run_scheduler
from crawlerai.schemas.registry import PresetConflict, sync_presets
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape_steps import load_drift_margins, load_engine_data
from crawlerai.storage import open_store
from crawlerai.storage.capture_bundle import encode
from crawlerai.worker.browser import SharedBrowser
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import TaskHandler, run_worker


def _print_openapi() -> None:
    # Sorted keys and LF bytes on every platform keep `frontend/openapi.json` byte-identical across regenerations,
    # which the CI freshness check (SPEC-00 §4.5) relies on. The document includes the labeling endpoints whatever
    # `CRAWLERAI_EVAL_UI` says, so the generated client has their types for the labeling screen.
    text = json.dumps(create_app(eval_ui=True).openapi(), indent=2, sort_keys=True) + "\n"
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
    settings = Settings()
    connector = SafeConnector()
    pools = settings.proxy_pools

    async def fetch_in(session: BrowserSession, url: str, policy: FetchPolicy) -> FetchResult:
        return await fetch_browser(
            url, policy, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools
        )

    http = partial(
        fetch_http, engine_version=ENGINE_VERSION, impersonate=settings.impersonate, connector=connector, pools=pools
    )
    async with aclosing(
        SharedBrowser(open_browser, fetch_in, lambda session: session.browser.is_connected())
    ) as browser:
        rungs = Rungs(http=http, browser=browser.fetch, conditional=http)
        fetching = Fetching(rungs, connector, open_store(settings.object_store), HostLimiter())
        # Later specs register a handler for each job kind here.
        data, margins = load_engine_data(), load_drift_margins()
        handlers: dict[JobKind, TaskHandler] = {
            "batch_scrape": scrape_handler(fetching, data, margins),
            "crawl": crawl_handler(fetching, data, margins),
        }
        await run_worker(settings, handlers, _stop_on_signals())


async def _schedule() -> None:
    settings = Settings()
    fetch = partial(
        fetch_http, engine_version=ENGINE_VERSION, impersonate=settings.impersonate, pools=settings.proxy_pools
    )
    entries = periodic(open_store(settings.object_store), fetch, poster(SafeConnector()))
    await run_scheduler(settings, entries, _stop_on_signals())


async def _fetch(url: str, out: Path, connector: SafeConnector | None = None) -> None:
    result = await fetch_http(
        url,
        FetchPolicy(),
        engine_version=ENGINE_VERSION,
        impersonate=AcquireSettings().impersonate,
        connector=connector,
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
    print(json.dumps(summary))


async def _eval_capture(
    split: Split, schema_name: str, page_kind: PageKind, category: EvalCategory, urls: Sequence[str]
) -> None:
    check_urls(urls)
    requests = [PageRequest(n, url, schema_name, category) for n, url in enumerate(urls, start=1)]
    sys.stdout.write(report(await run_capture(Settings(), split, requests, page_kind)))


async def _eval_import_sites(split: Split, file: Path, pages_per_site: int) -> None:
    sites = parse_site_list(file.read_text(encoding="utf-8"), pages_per_site)
    sys.stdout.write(report([*await run_capture(Settings(), split, sites.requests), *sites.over_limit]))


async def _eval_promote(all_pages: bool) -> None:
    settings = Settings()
    async with (
        aclosing(private_store("fresh", settings)) as fresh,
        aclosing(private_store("hidden", settings)) as hidden,
        aclosing(dev_store(settings)) as dev,
    ):
        sys.stdout.write(promote.report(await promote.promote(fresh, hidden, dev, all_pages)))


async def _eval_rotate_hidden(fraction: float) -> None:
    settings = Settings()
    async with (
        aclosing(private_store("hidden", settings)) as hidden,
        aclosing(private_store("fresh", settings)) as fresh,
        aclosing(dev_store(settings)) as dev,
    ):
        sys.stdout.write(promote.report(await promote.rotate_hidden(hidden, fresh, dev, fraction)))


async def _sync_presets() -> None:
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            inserted = await sync_presets(conn)
    finally:
        await engine.dispose()
    for schema in inserted:
        print(f"inserted preset {schema.name} version {schema.version}")
    print(f"{len(inserted)} preset version(s) inserted")


async def _apikey_create(label: str) -> None:
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            created = await create_key(conn, label)
    finally:
        await engine.dispose()
    # The key is printed this once; only its hash is stored (SPEC-07 §4.2). The webhook secret, which verifies the
    # signature of the key's webhooks (SPEC-10 §4.2), is printed with it.
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


async def _apikey_revoke(parser: argparse.ArgumentParser, key_id: uuid.UUID) -> None:
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            outcome = await revoke_key(conn, key_id)
    finally:
        await engine.dispose()
    if outcome == "not_found":
        parser.exit(2, f"crawlerai apikey revoke: no API key {key_id}\n")
    print(json.dumps({"id": str(key_id), "revoked": outcome == "revoked"}))


def _data_dir() -> Path:
    """`backend/data/` of the source tree this package runs from: the pinned data files, and the calibration and
    precedence that SPEC-05 reads."""
    backend = backend_dir(Path(calibrate.__file__))  # any module one package below `crawlerai`
    if backend is None:
        raise EvalCliError("no backend source tree: data files are read from and written to backend/data/")
    return data_dir(backend)


async def _eval_fit(command: str, run_id: EvalRunId) -> None:
    """`calibrate` or `fit-precedence`: fit on dev run `run_id` and write the file."""
    directory = _data_dir()
    # Read before the store is opened: without a current order there is nothing to refit.
    current = calibrate.read_precedence(directory) if command == "fit-precedence" else None
    async with aclosing(dev_store(Settings())) as dev:
        run = await dev.get_run(run_id)
    if current is None:
        path = calibrate.write_calibration(calibrate.calibrate(run), directory)
    else:
        path = calibrate.write_precedence(calibrate.fit_precedence(run, current), directory)
    print(json.dumps({"written": str(path), "eval_run_id": str(run.id), "source_split": run.split}))


def _add_eval_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    eval_commands = commands.add_parser("eval", help="evaluation: capture pages, move them into dev").add_subparsers(
        dest="eval_command", required=True
    )
    splits, categories, page_kinds = get_args(Split), get_args(EvalCategory), get_args(PageKind)
    capture = eval_commands.add_parser(
        "capture", help="fetch pages and store each as an unlabeled eval page of the split"
    )
    capture.set_defaults(handler=_run_eval, eval_handler=_run_eval_capture)
    capture.add_argument("--split", choices=splits, required=True)
    capture.add_argument("--schema", required=True, help="the name of an active schema")
    capture.add_argument("--page-kind", choices=page_kinds, required=True)
    capture.add_argument("--category", choices=categories, required=True)
    capture.add_argument("urls", nargs="+", metavar="URL")
    import_sites = eval_commands.add_parser(
        "import-sites", help="capture the pages of a site list (`<category> <schema> <url>` per line) into the split"
    )
    import_sites.set_defaults(handler=_run_eval, eval_handler=_run_eval_import_sites)
    import_sites.add_argument("--split", choices=splits, required=True)
    import_sites.add_argument("--file", type=Path, required=True)
    import_sites.add_argument("--pages-per-site", type=_positive_int, required=True)
    promote_command = eval_commands.add_parser(
        "promote", help="move the fresh sites whose pages are all checked into dev, keeping their labels"
    )
    promote_command.set_defaults(handler=_run_eval, eval_handler=_run_eval_promote)
    # The one move §16.1 defines for fresh; hidden moves only by `rotate-hidden`.
    promote_command.add_argument("--from", dest="source", choices=["fresh"], required=True)
    promote_command.add_argument("--to", dest="target", choices=["dev"], required=True)
    promote_command.add_argument("--all", action="store_true", help="move every fresh site, checked or not")
    rotate = eval_commands.add_parser(
        "rotate-hidden", help="move a fraction of the hidden sites, chosen per category, into dev"
    )
    rotate.set_defaults(handler=_run_eval, eval_handler=_run_eval_rotate_hidden)
    rotate.add_argument("--fraction", type=_fraction, required=True)
    for name, help_ in (
        ("calibrate", "write backend/data/calibration.json from a dev eval run"),
        ("fit-precedence", "write backend/data/source_precedence.yaml from a dev eval run"),
    ):
        fit = eval_commands.add_parser(name, help=help_)
        fit.set_defaults(handler=_run_eval, eval_handler=_run_eval_fit)
        # Every split is accepted here so that the refusal is the command's own, stated and tested (INV-02).
        fit.add_argument("--split", choices=splits, required=True, help="dev; any other split is refused")
        fit.add_argument("--run", type=uuid.UUID, required=True, help="the id of the dev eval run to fit on")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _fraction(value: str) -> float:
    try:
        return promote.check_fraction(float(value))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


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
    fetch = commands.add_parser("fetch", help="fetch one URL over HTTP into a capture bundle file")
    fetch.set_defaults(handler=_run_fetch)
    fetch.add_argument("url")
    fetch.add_argument(
        "--out", type=Path, required=True, help="the bundle file to write (zstd-compressed tar), under this directory"
    )
    schemas = commands.add_parser("schemas", help="schema definitions").add_subparsers(
        dest="schemas_command", required=True
    )
    schemas.add_parser(
        "sync", help="insert the preset schema versions the database lacks (after migrating)"
    ).set_defaults(handler=_run_schemas)
    data = commands.add_parser("data", help="the pinned data files of backend/data/manifest.json").add_subparsers(
        dest="data_command", required=True
    )
    data.add_parser(
        "fetch", help="download the fetched entries (GeoNames, schema.org) and check their sha256"
    ).set_defaults(handler=_run_data)
    apikey = commands.add_parser("apikey", help="API keys; the API never creates one (INV-32)").add_subparsers(
        dest="apikey_command", required=True
    )
    create = apikey.add_parser("create", help="create a key and print it, once, with its id")
    create.set_defaults(handler=_run_apikey_create)
    create.add_argument("--label", required=True, help="what the key is for")
    revoke = apikey.add_parser("revoke", help="revoke a key: requests with it are refused from then on")
    revoke.set_defaults(handler=_run_apikey_revoke)
    revoke.add_argument("id", type=uuid.UUID, help="the key's id, as `apikey create` printed it")
    _add_eval_commands(commands)
    return parser


def _under_cwd(parser: argparse.ArgumentParser, option: str, path: Path) -> Path:
    """`path` resolved against the working directory; a path argument never reaches outside it."""
    cwd = Path.cwd().resolve()
    resolved = (cwd / path).resolve()
    if not resolved.is_relative_to(cwd):
        parser.error(f"{option} must be under the working directory {cwd}")
    return resolved


def _run_openapi(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    _print_openapi()


def _run_worker(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    asyncio.run(_work())


def _run_scheduler(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    asyncio.run(_schedule())


def _run_fetch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # The bundle is written only under the working directory: a path argument never reaches elsewhere.
    asyncio.run(_fetch(args.url, _under_cwd(parser, "--out", args.out)))


def _run_schemas(parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    try:
        asyncio.run(_sync_presets())
    except PresetConflict as e:
        parser.exit(2, f"crawlerai schemas sync: {e}\n")


def _run_apikey_create(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_apikey_create(args.label))


def _run_apikey_revoke(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_apikey_revoke(parser, args.id))


def _run_data(parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    try:
        for line in fetch_data(_data_dir()):
            print(line)
    except (DataFetchError, EvalCliError) as e:
        parser.exit(2, f"crawlerai data fetch: {e}\n")


def _run_eval(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        args.eval_handler(parser, args)
    except (EvalCliError, EvalNotFound, PrivateCredentialsMissing, PrivateStoreNotSeparate) as e:
        parser.exit(2, f"crawlerai eval: {e}\n")
    except Exception as e:
        # Only a dev command shows its failure; `promote` and `rotate-hidden` read private splits and have none.
        split = getattr(args, "split", "private")
        if split == "dev":
            raise
        # A hidden or fresh failure is reported by its type only: a message or traceback could carry a URL or a
        # row's values (a database error's DETAIL), and hidden cases must not reach a log (C1).
        parser.exit(1, f"crawlerai eval: failed with {type(e).__name__}; details withheld for the {split} split\n")


def _run_eval_capture(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_eval_capture(args.split, args.schema, args.page_kind, args.category, args.urls))


def _run_eval_import_sites(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # The site list is read only from under the working directory, as `fetch --out` is written there.
    sites = _under_cwd(parser, "--file", args.file)
    asyncio.run(_eval_import_sites(args.split, sites, args.pages_per_site))


def _run_eval_promote(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_eval_promote(args.all))


def _run_eval_rotate_hidden(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_eval_rotate_hidden(args.fraction))


def _run_eval_fit(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # Refused before any store is opened: a private split's run is never read here (C1).
    calibrate.require_dev(args.split)
    asyncio.run(_eval_fit(args.eval_command, EvalRunId(args.run)))
