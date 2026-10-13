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

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy
from crawlerai.api.app import create_app
from crawlerai.core.settings import AcquireSettings, Settings
from crawlerai.scheduler.loop import PERIODIC, run_scheduler
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
    await run_scheduler(Settings(), PERIODIC, _stop_on_signals())


async def _fetch(url: str, out: Path, connector: SafeConnector | None = None) -> None:
    result = await fetch_http(
        url,
        FetchPolicy(),
        # The package version until SPEC-01 PR 7 provides ENGINE_VERSION.
        engine_version=version("crawlerai"),
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


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="crawlerai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('crawlerai')}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("openapi", help="print the API's OpenAPI document as JSON")
    commands.add_parser("worker", help="run a worker: claim queued tasks and run them until SIGINT or SIGTERM")
    commands.add_parser("scheduler", help="run the scheduler: periodic upkeep, such as releasing expired leases")
    fetch = commands.add_parser("fetch", help="fetch one URL over HTTP into a capture bundle file")
    fetch.add_argument("url")
    fetch.add_argument("--out", type=Path, required=True, help="the bundle file to write (zstd-compressed tar)")
    args = parser.parse_args(argv)
    if args.command == "openapi":
        _print_openapi()
    elif args.command == "worker":
        asyncio.run(_work())
    elif args.command == "scheduler":
        asyncio.run(_schedule())
    elif args.command == "fetch":
        asyncio.run(_fetch(args.url, args.out))
