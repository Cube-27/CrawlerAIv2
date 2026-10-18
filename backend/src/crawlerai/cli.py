"""The `crawlerai` command-line entry point."""

import argparse
import asyncio
import json
import logging
import signal
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing, asynccontextmanager, suppress
from dataclasses import asdict, replace
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Final, get_args

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.acquire.api import fetch_json
from crawlerai.acquire.browser import BrowserSession, fetch_browser, open_browser
from crawlerai.acquire.browser_tab import Drive, fetch_listing
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.impersonate import rung_impersonation
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs, adapter_registry
from crawlerai.acquire.session import CookieExport, SiteSessions
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult, PagedFetch
from crawlerai.api.app import create_app
from crawlerai.api.webhooks import poster
from crawlerai.core.data import fetch_data
from crawlerai.core.engine_version import ENGINE_VERSION, backend_dir, data_dir
from crawlerai.core.event_loop import quiet_peer_resets
from crawlerai.core.settings import AcquireSettings, DatabaseSettings, Settings
from crawlerai.db.keys import create_key, revoke_key
from crawlerai.db.models import EvalCategory, PageKind, ScheduleId
from crawlerai.eval import calibrate, label_file, learn_sim, rekey
from crawlerai.eval.cli import (
    EvalCliError,
    PageRequest,
    active_schemas,
    check_urls,
    http_host,
    parse_site_list,
    report,
    run_capture,
)
from crawlerai.eval.engine import PipelineEngine
from crawlerai.eval.git_head import GitUnavailable, head_commit
from crawlerai.eval.labels import LabelStatus
from crawlerai.eval.metrics import CHECKED, build_report
from crawlerai.eval.replay import CappedLLM, replay_split
from crawlerai.eval.store import EvalNotFound, EvalRunRow, dev_store
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.llm.providers.from_settings import llm_from_settings
from crawlerai.recurring.listing_diff import close_run
from crawlerai.resolve.pipeline import EngineData
from crawlerai.scheduler.loop import periodic, run_scheduler
from crawlerai.schemas.registry import PresetConflict
from crawlerai.schemas.types import SchemaDef
from crawlerai.services import schedules as schedules_service
from crawlerai.services import schemas as schemas_service
from crawlerai.services.fetch_options import FetchOptions, UnknownProxyPool, check_proxy_pool, fetch_policy
from crawlerai.services.fetching import Fetching, PagePlan, TargetRejected, fetch_now, learning_replay, site_rungs
from crawlerai.services.records import MAX_PAGE
from crawlerai.services.runtime import fetching_from_settings
from crawlerai.services.schedules import ScheduleListQuery, ScheduleNotFound, Submitting
from crawlerai.services.scrape_paging import learning_render
from crawlerai.services.scrape_steps import load_drift_margins, load_engine_data, render_need, site_row
from crawlerai.storage import open_store
from crawlerai.storage.capture_bundle import encode
from crawlerai.worker.browser import SharedBrowser
from crawlerai.worker.handlers.table import task_handlers
from crawlerai.worker.learn import run_learner
from crawlerai.worker.loop import run_worker

# What `crawlerai schedules` prints of a schedule: enough to find it and see whether and when it runs.
_SCHEDULE_LINE: Final = {"id", "name", "kind", "cron", "interval_s", "timezone", "paused", "next_run_at", "last_job_id"}


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


@asynccontextmanager
async def _fetching(settings: Settings, connector: SafeConnector) -> AsyncIterator[Fetching]:
    """What a process fetches pages with, as a worker does (SPEC-02 §4.4): HTTP, the shared browser, the adapters, and
    this process's site sessions; the browser closes with it."""
    pools = settings.proxy_pools

    async def fetch_in(
        session: BrowserSession, url: str, policy: FetchPolicy, export: CookieExport | None
    ) -> FetchResult:
        return await fetch_browser(
            url, policy, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools, export=export
        )

    async def listing(url: str, policy: FetchPolicy, drive: Drive) -> PagedFetch:
        # A learning run's listing renders only (`learning_render`): rare, so a browser is launched per render.
        async with open_browser() as session:
            return await fetch_listing(
                url, policy, drive, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools
            )

    impersonate = rung_impersonation(settings)
    sessions = SiteSessions()  # this worker's site sessions (INV-29's exception), in memory only
    http = partial(
        fetch_http,
        engine_version=ENGINE_VERSION,
        impersonate=impersonate,
        connector=connector,
        pools=pools,
        sessions=sessions,
    )
    async with aclosing(
        SharedBrowser(open_browser, fetch_in, lambda session: session.browser.is_connected())
    ) as browser:
        json = partial(
            fetch_json,
            engine_version=ENGINE_VERSION,
            impersonate=impersonate,
            connector=connector,
            pools=pools,
            sessions=sessions,
        )
        rungs = Rungs(
            http=http,
            browser=browser.fetch,
            adapters=adapter_registry(settings.disabled_adapters),
            conditional=http,
            json=json,
            sessions=sessions,
            exporting=browser.fetch,
            listing=listing,
        )
        store = open_store(settings.object_store)
        yield Fetching(rungs, connector, store, HostLimiter(), frozenset(settings.proxy_pools))


async def _work() -> None:
    quiet_peer_resets(asyncio.get_running_loop())
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        async with _fetching(settings, SafeConnector()) as fetching:
            store, adapters = fetching.store, fetching.rungs.adapters
            llm, setup = llm_from_settings(settings, engine)
            data, margins = load_engine_data(adapters), load_drift_margins()
            handlers = task_handlers(fetching, data, margins, llm=llm)
            stop = _stop_on_signals()
            # A records crawl that completes is diffed against its earlier runs (SPEC-11 §4.5).
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
                )
                work.append(learner)
            await asyncio.gather(*work)
    finally:
        await engine.dispose()


async def _schedule() -> None:
    settings = Settings()
    fetch = partial(
        fetch_http, engine_version=ENGINE_VERSION, impersonate=rung_impersonation(settings), pools=settings.proxy_pools
    )
    # A schedule's run submits its job with the schema its creation resolved, so it drafts nothing: no LLM client.
    fetching = fetching_from_settings(settings)
    submitting = Submitting(fetching, load_engine_data(fetching.rungs.adapters), NO_LLM)
    entries = periodic(open_store(settings.object_store), fetch, poster(SafeConnector()), submitting)
    await run_scheduler(settings, entries, _stop_on_signals())


async def _fetch(
    url: str, out: Path, connector: SafeConnector | None = None, options: FetchOptions | None = None
) -> None:
    """Fetch `url` into a bundle at `out`: over HTTP, or in the browser when `options` ask for it or for page steps,
    with the caller's request context and proxy pool (D-1430, D-1434)."""
    settings = AcquireSettings()
    options = options or FetchOptions()
    policy = fetch_policy(options, None, None)
    if options.in_browser:
        async with open_browser() as session:
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
            impersonate=rung_impersonation(settings),
            connector=connector,
            pools=settings.proxy_pools,
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


async def _eval_capture(schema_name: str, page_kind: PageKind, category: EvalCategory, urls: Sequence[str]) -> None:
    check_urls(urls)
    requests = [PageRequest(n, url, schema_name, category) for n, url in enumerate(urls, start=1)]
    sys.stdout.write(report(await run_capture(Settings(), requests, page_kind)))


async def _eval_import_sites(file: Path, pages_per_site: int) -> None:
    sites = parse_site_list(file.read_text(encoding="utf-8"), pages_per_site)
    sys.stdout.write(report([*await run_capture(Settings(), sites.requests), *sites.over_limit]))


async def _eval_import_labels(file: Path) -> None:
    """Capture a label file's pages into dev through the worker's acquisition path, one page at a time, and store
    their labels as drafts (D-1460)."""
    settings = Settings()
    pages = label_file.read_label_file(file.read_text(encoding="utf-8"))
    database_url = settings.database_url.get_secret_value()
    schemas = await active_schemas(database_url, label_file.schema_names(pages))
    labeled = label_file.labeled_pages(pages, schemas)
    engine = create_async_engine(database_url)
    try:
        async with aclosing(dev_store(settings)) as store, _fetching(settings, SafeConnector()) as fetching:
            data = load_engine_data(fetching.rungs.adapters)
            fetch = partial(_polite_page, engine, fetching, data)
            outcomes = await label_file.import_pages(store, schemas, labeled, fetch, await store.page_urls())
    finally:
        await engine.dispose()
    sys.stdout.write(label_file.report(outcomes))


async def _eval_rekey(file: Path) -> None:
    """Recompute the draft labels of a label file's pages already in the golden set against their stored captures, and
    mark the label rows the captures do not show (evaluation spec, "Label re-keying")."""
    settings = Settings()
    pages = label_file.read_label_file(file.read_text(encoding="utf-8"))
    schemas = await active_schemas(settings.database_url.get_secret_value(), label_file.schema_names(pages))
    labeled = label_file.labeled_pages(pages, schemas)
    async with aclosing(dev_store(settings)) as store:
        outcomes = await rekey.rekey_pages(store, schemas, labeled)
    sys.stdout.write(rekey.report(outcomes))


async def _polite_page(
    engine: AsyncEngine, fetching: Fetching, data: EngineData | None, url: str, schema: SchemaDef
) -> FetchResult | str:
    """The page as a worker fetches it for `schema` (`fetch_now`): robots.txt, the site's rate, its adapters, and
    a render when the HTTP page lacks what the schema reads; or why it was not fetched."""
    host = http_host(url)
    if host is None:  # `labeled_pages` refuses such a URL
        raise EvalCliError("not an http or https URL with a host")
    async with engine.begin() as conn:
        site = await site_row(conn, host, schema.page_kind)
    policy = FetchPolicy(
        page_kind=schema.page_kind, proxy_pool=site.proxy_pool, block_resources=not site.load_all_resources
    )
    page = PagePlan(site_rungs(fetching, host, site), site, policy, [], needs_render=render_need(schema, data, None))
    try:
        # A page not reached is fetched again after the back-off, and the closest capture kept (`best_fetch`).
        return await label_file.best_fetch(lambda: fetch_now(engine, fetching, url, replace(page, attempts=[])))
    except TargetRejected:
        return "target_rejected"


async def _eval_run(
    statuses: frozenset[LabelStatus],
    llm_mode: str,
    out: Path | None,
    max_calls: int | None = None,
    min_confidence: float | None = None,
) -> None:
    """Replay the dev split through the pipeline and score it; store the run when it scores checked pages only and
    asked no minimum confidence (a gated run measures only what the gate let through, so a fit on it would be of its
    own selection)."""
    settings = Settings()
    data = load_engine_data(adapter_registry(settings.disabled_adapters))
    if data is None:
        raise EvalCliError("the engine's data files are missing: run `crawlerai data fetch`")
    database_url = settings.database_url.get_secret_value()
    pipeline = PipelineEngine(data.with_min_confidence(min_confidence), await active_schemas(database_url))
    git_sha = head_commit(_data_dir().parent.parent)
    db = create_async_engine(database_url)
    try:
        async with aclosing(dev_store(settings)) as store:
            cases = await replay_split(
                store, pipeline, live=_replay_llm(llm_mode, settings, db, max_calls), statuses=statuses
            )
            # D-1480: the report scores the engine rows of the labeled page (`rows="labeled"`), and every row too.
            result = build_report(cases, "dev", pipeline.version, git_sha, statuses, rows="labeled")
            all_rows = build_report(cases, "dev", pipeline.version, git_sha, statuses)
            # A stored run is what calibration fits on: drafts never become one (labels spec: two passes). It keeps
            # every engine row.
            run = None
            if statuses == CHECKED and min_confidence is None:
                metrics = all_rows.model_dump(mode="json")
                run = await store.put_run(
                    EvalRunRow(split="dev", engine_version=pipeline.version, git_sha=git_sha, metrics=metrics)
                )
    finally:
        await db.dispose()
    if out is not None:
        out.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        all_rows_out = out.with_name(f"{out.stem}.all-rows{out.suffix}")
        all_rows_out.write_text(all_rows.model_dump_json(indent=2) + "\n", encoding="utf-8")
    dropped = sum(page.error is not None for page in result.pages or ())
    summary = {
        "eval_run_id": None if run is None else str(run),
        "n_pages": result.n_pages,
        "dropped": dropped,
        "label_statuses": list(result.label_statuses),
        "by_field_type": {k: v.model_dump(mode="json") for k, v in result.by_field_type.items()},
        "by_field_type_all_rows": {k: v.model_dump(mode="json") for k, v in all_rows.by_field_type.items()},
    }
    print(json.dumps(summary))


async def _eval_learn_sim(pages: int, llm_mode: str, role_a: str, max_calls: int | None, out: Path | None) -> None:
    """Simulate learning on each dev host's first `pages` pages and print the aggregates (`eval.learn_sim`)."""
    settings = Settings()
    data = load_engine_data(adapter_registry(settings.disabled_adapters))
    if data is None:
        raise EvalCliError("the engine's data files are missing: run `crawlerai data fetch`")
    database_url = settings.database_url.get_secret_value()
    pipeline = PipelineEngine(data, await active_schemas(database_url))
    db = create_async_engine(database_url)
    try:
        strong = llm_from_settings(settings, db)[0] if role_a == "live" else None
        async with aclosing(dev_store(settings)) as store:
            runs = await learn_sim.simulate(
                store,
                pipeline,
                pages=pages,
                live=_replay_llm(llm_mode, settings, db, max_calls),
                role_a=None if strong is None else CappedLLM(strong, max_calls or learn_sim.ROLE_A_CALLS),
                max_chars=settings.llm_a_max_chars,
            )
    finally:
        await db.dispose()
    if out is not None:
        out.write_text(json.dumps([asdict(run) for run in runs], indent=2) + "\n", encoding="utf-8")
    print(json.dumps(learn_sim.summary(runs, learn_sim.usd_per_char(settings.llm_strong_model_anthropic))))


def _replay_llm(mode: str, settings: Settings, db: AsyncEngine, max_calls: int | None) -> LLMClient | None:
    """What answers a call no recording holds (`RecordedLLM`): nothing, so the page is dropped (`recorded`, as in CI);
    a client that answers none, so its fields stay missing (`unanswered`, D-1464); or the configured providers, whose
    responses are recorded (`live`), at most `max_calls` of them when given."""
    match mode:
        case "unanswered":
            return NO_LLM
        case "live":
            live = llm_from_settings(settings, db)[0]
            return live if max_calls is None else CappedLLM(live, max_calls)
        case _:
            return None


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


def _data_dir() -> Path:
    """`backend/data/` of the source tree this package runs from: the pinned data files, and the calibration and
    precedence that SPEC-05 reads."""
    backend = backend_dir(Path(calibrate.__file__))  # any module one package below `crawlerai`
    if backend is None:
        raise EvalCliError("no backend source tree: data files are read from and written to backend/data/")
    return data_dir(backend)


def _eval_fit(command: str, report_path: Path) -> None:
    """`fit-calibration` or `fit-precedence`: fit on the dev report at `report_path` and write the file."""
    directory = _data_dir()
    report = calibrate.read_report(report_path)
    if command == "fit-calibration":
        path = calibrate.write_calibration(calibrate.fit_calibration(report), directory)
    else:
        current = calibrate.read_precedence(directory)
        path = calibrate.write_precedence(calibrate.fit_precedence(report, current), directory)
    print(json.dumps({"written": str(path), "git_sha": report.git_sha, "source_split": report.split}))


def _add_eval_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    eval_commands = commands.add_parser(
        "eval", help="evaluation on the golden set: capture, label, replay, fit"
    ).add_subparsers(dest="eval_command", required=True)
    # One split, the golden set (evaluation spec); `--split dev` names it on every command.
    splits, categories, page_kinds = ["dev"], get_args(EvalCategory), get_args(PageKind)
    capture = eval_commands.add_parser("capture", help="fetch pages and store each as an unlabeled eval page")
    capture.set_defaults(handler=_run_eval, eval_handler=_run_eval_capture)
    capture.add_argument("--split", choices=splits, required=True)
    capture.add_argument("--schema", required=True, help="the name of an active schema")
    capture.add_argument("--page-kind", choices=page_kinds, required=True)
    capture.add_argument("--category", choices=categories, required=True)
    capture.add_argument("urls", nargs="+", metavar="URL")
    import_sites = eval_commands.add_parser(
        "import-sites", help="capture the pages of a site list (`<category> <schema> <url>` per line)"
    )
    import_sites.set_defaults(handler=_run_eval, eval_handler=_run_eval_import_sites)
    import_sites.add_argument("--split", choices=splits, required=True)
    import_sites.add_argument("--file", type=Path, required=True)
    import_sites.add_argument("--pages-per-site", type=_positive_int, required=True)
    import_labels = eval_commands.add_parser(
        "import-labels", help="capture a label file's pages into dev and store their labels as drafts"
    )
    import_labels.set_defaults(handler=_run_eval, eval_handler=_run_eval_import_labels)
    import_labels.add_argument("file", type=Path, help="the label file (JSON), under the working directory")
    # Imported labels are drafts only: a labeled or checked page takes the two passes of §16.2 (D-1460).
    import_labels.add_argument("--split", choices=["dev"], required=True)
    import_labels.add_argument("--status", choices=["draft"], required=True)
    rekey_command = eval_commands.add_parser(
        "re-key", help="recompute golden pages' draft labels from a label file and mark rows their captures lack"
    )
    rekey_command.set_defaults(handler=_run_eval, eval_handler=_run_eval_rekey)
    rekey_command.add_argument("file", type=Path, help="the label file (JSON), under the working directory")
    rekey_command.add_argument("--split", choices=["dev"], required=True)
    run = eval_commands.add_parser("run", help="replay the dev split through the engine and print its report")
    run.set_defaults(handler=_run_eval, eval_handler=_run_eval_run)
    run.add_argument("--split", choices=["dev"], required=True)
    run.add_argument(
        "--labels",
        choices=["checked", "all"],
        default="checked",
        help="score checked pages (stored as a run), or drafts and labeled pages too (D-1461; not stored)",
    )
    run.add_argument(
        "--llm",
        choices=["recorded", "unanswered", "live"],
        default="recorded",
        help="for a call no recording holds: drop the page, answer nothing, or call the configured providers",
    )
    run.add_argument("--llm-max-calls", type=_positive_int, help="with --llm live: the most provider calls to make")
    run.add_argument(
        "--min-confidence",
        type=_probability,
        help="leave unpublished a field whose calibrated confidence is below this (0 to 1; the run is not stored)",
    )
    run.add_argument(
        "--out",
        type=Path,
        help=(
            "write the full report (JSON) here, under the working directory, with the engine rows of the labeled page"
            " (D-1480); the report scoring every row goes beside it as <name>.all-rows.json"
        ),
    )
    _add_learn_sim(eval_commands)
    for name, help_ in (
        ("fit-calibration", "write backend/data/calibration.json from a dev eval report"),
        ("fit-precedence", "write backend/data/source_precedence.yaml from a dev eval report"),
    ):
        fit = eval_commands.add_parser(name, help=help_)
        fit.set_defaults(handler=_run_eval, eval_handler=_run_eval_fit)
        fit.add_argument("--split", choices=splits, required=True)
        fit.add_argument("--report", type=Path, required=True, help="the report `eval run --out` wrote, to fit on")


def _add_learn_sim(eval_commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    sim = eval_commands.add_parser(
        "learn-sim", help="simulate learning on each dev host's first pages and print zero-touch aggregates"
    )
    sim.set_defaults(handler=_run_eval, eval_handler=_run_eval_learn_sim)
    sim.add_argument("--split", choices=["dev"], required=True)
    sim.add_argument("--pages", type=_positive_int, default=3, help="the pages per host learning reads")
    sim.add_argument("--llm", choices=["recorded", "unanswered", "live"], default="unanswered", help="role C misses")
    sim.add_argument("--role-a", choices=["abstain", "live"], default="abstain", help="count role A, or call it")
    sim.add_argument(
        "--llm-max-calls",
        type=_positive_int,
        help="with a live client: the most provider calls each makes in the whole simulation",
    )
    sim.add_argument("--out", type=Path, help="write each host's run (JSON, no host names) here")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _probability(value: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return number


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
    apikey = commands.add_parser("apikey", help="API keys; the API never creates one (INV-32)").add_subparsers(
        dest="apikey_command", required=True
    )
    create = apikey.add_parser("create", help="create a key and print it, once, with its id")
    create.set_defaults(handler=_run_apikey_create)
    create.add_argument("--label", required=True, help="what the key is for")
    revoke = apikey.add_parser("revoke", help="revoke a key: requests with it are refused from then on")
    revoke.set_defaults(handler=_run_apikey_revoke)
    revoke.add_argument("id", type=uuid.UUID, help="the key's id, as `apikey create` printed it")
    _add_schedule_commands(commands)
    _add_eval_commands(commands)
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
    asyncio.run(_fetch(args.url, out, options=options))


def _add_fetch_options(fetch: argparse.ArgumentParser) -> None:
    """The request's `fetch` members as flags (D-1430, D-1436): the same names and checks as the API's."""
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


def _run_apikey_revoke(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_apikey_revoke(parser, args.id))


def _run_schedules_list(_parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    asyncio.run(_schedules_list())


def _run_schedules_pause(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_schedules_pause(parser, args.id, paused=args.paused))


def _run_data(parser: argparse.ArgumentParser, _args: argparse.Namespace) -> None:
    try:
        report = fetch_data(_data_dir())
    except EvalCliError as e:
        parser.exit(2, f"crawlerai data fetch: {e}\n")
    for line in report.written:
        print(line)
    if report.refused:
        parser.exit(2, "".join(f"crawlerai data fetch: {line}\n" for line in report.refused))


def _run_eval(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        args.eval_handler(parser, args)
    except (EvalCliError, EvalNotFound, GitUnavailable) as e:
        parser.exit(2, f"crawlerai eval: {e}\n")


def _run_eval_capture(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_eval_capture(args.schema, args.page_kind, args.category, args.urls))


def _run_eval_import_sites(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # The site list is read only from under the working directory, as `fetch --out` is written there.
    sites = _under_cwd(parser, "--file", args.file)
    asyncio.run(_eval_import_sites(sites, args.pages_per_site))


def _run_eval_import_labels(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_eval_import_labels(_under_cwd(parser, "file", args.file)))


def _run_eval_rekey(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    asyncio.run(_eval_rekey(_under_cwd(parser, "file", args.file)))


def _run_eval_run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    out = None if args.out is None else _under_cwd(parser, "--out", args.out)
    statuses: frozenset[LabelStatus] = CHECKED if args.labels == "checked" else frozenset(get_args(LabelStatus))
    asyncio.run(_eval_run(statuses, args.llm, out, args.llm_max_calls, args.min_confidence))


def _run_eval_learn_sim(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    out = None if args.out is None else _under_cwd(parser, "--out", args.out)
    asyncio.run(_eval_learn_sim(args.pages, args.llm, args.role_a, args.llm_max_calls, out))


def _run_eval_fit(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    _eval_fit(args.eval_command, _under_cwd(parser, "--report", args.report))
