"""The `crawlerai` command-line entry point."""

import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path
from typing import get_args

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy
from crawlerai.api.app import create_app
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.settings import AcquireSettings, Settings
from crawlerai.db.models import EvalCategory, PageKind, Split
from crawlerai.eval.cli import EvalCliError, PageRequest, check_urls, parse_site_list, report, run_capture
from crawlerai.eval.store import PrivateCredentialsMissing, PrivateStoreNotSeparate
from crawlerai.scheduler.loop import periodic, run_scheduler
from crawlerai.storage import open_store
from crawlerai.storage.capture_bundle import encode
from crawlerai.worker.loop import run_worker


def _print_openapi() -> None:
    # Sorted keys and LF bytes on every platform keep `frontend/openapi.json` byte-identical across regenerations,
    # which the CI freshness check (SPEC-00 §4.5) relies on.
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
    # Later specs register a handler for each job kind here.
    await run_worker(Settings(), {}, _stop_on_signals())


async def _schedule() -> None:
    settings = Settings()
    await run_scheduler(settings, periodic(open_store(settings.object_store)), _stop_on_signals())


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


def _add_eval_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    eval_commands = commands.add_parser("eval", help="evaluation: capture pages into a split").add_subparsers(
        dest="eval_command", required=True
    )
    splits, categories, page_kinds = get_args(Split), get_args(EvalCategory), get_args(PageKind)
    capture = eval_commands.add_parser(
        "capture", help="fetch pages and store each as an unlabeled eval page of the split"
    )
    capture.add_argument("--split", choices=splits, required=True)
    capture.add_argument("--schema", required=True, help="the name of an active schema")
    capture.add_argument("--page-kind", choices=page_kinds, required=True)
    capture.add_argument("--category", choices=categories, required=True)
    capture.add_argument("urls", nargs="+", metavar="URL")
    import_sites = eval_commands.add_parser(
        "import-sites", help="capture the pages of a site list (`<category> <schema> <url>` per line) into the split"
    )
    import_sites.add_argument("--split", choices=splits, required=True)
    import_sites.add_argument("--file", type=Path, required=True)
    import_sites.add_argument("--pages-per-site", type=_positive_int, required=True)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="crawlerai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('crawlerai')}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("openapi", help="print the API's OpenAPI document as JSON")
    commands.add_parser("worker", help="run a worker: claim queued tasks and run them until SIGINT or SIGTERM")
    commands.add_parser("scheduler", help="run the scheduler: release expired leases, expire captures and candidates")
    fetch = commands.add_parser("fetch", help="fetch one URL over HTTP into a capture bundle file")
    fetch.add_argument("url")
    fetch.add_argument(
        "--out", type=Path, required=True, help="the bundle file to write (zstd-compressed tar), under this directory"
    )
    _add_eval_commands(commands)
    args = parser.parse_args(argv)
    if args.command == "openapi":
        _print_openapi()
    elif args.command == "worker":
        asyncio.run(_work())
    elif args.command == "scheduler":
        asyncio.run(_schedule())
    elif args.command == "fetch":
        # The bundle is written only under the working directory: a path argument never reaches elsewhere.
        cwd = Path.cwd().resolve()
        out = (cwd / args.out).resolve()
        if not out.is_relative_to(cwd):
            parser.error(f"--out must be under the working directory {cwd}")
        asyncio.run(_fetch(args.url, out))
    elif args.command == "eval":
        try:
            if args.eval_command == "capture":
                asyncio.run(_eval_capture(args.split, args.schema, args.page_kind, args.category, args.urls))
            else:
                # The site list is read only from under the working directory, as `fetch --out` is written there.
                cwd = Path.cwd().resolve()
                sites = (cwd / args.file).resolve()
                if not sites.is_relative_to(cwd):
                    parser.error(f"--file must be under the working directory {cwd}")
                asyncio.run(_eval_import_sites(args.split, sites, args.pages_per_site))
        except (EvalCliError, PrivateCredentialsMissing, PrivateStoreNotSeparate) as e:
            parser.exit(2, f"crawlerai eval: {e}\n")
        except Exception as e:
            if args.split == "dev":
                raise
            # A hidden or fresh failure is reported by its type only: a message or traceback could carry a URL or a
            # row's values (a database error's DETAIL), and hidden cases must not reach a log (C1).
            parser.exit(
                1, f"crawlerai eval: failed with {type(e).__name__}; details withheld for the {args.split} split\n"
            )
