"""The `crawlerai` command-line entry point."""

import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import version

from crawlerai.api.app import create_app
from crawlerai.core.settings import Settings
from crawlerai.worker.loop import run_worker


def _print_openapi() -> None:
    # Sorted keys and LF bytes on every platform keep `frontend/openapi.json` byte-identical across regenerations,
    # which the CI freshness check (SPEC-00 §4.5) relies on.
    text = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    sys.stdout.buffer.write(text.encode())


async def _work() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        # Not available on Windows, where Ctrl+C interrupts the worker and its leases expire instead.
        with suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, stop.set)
    # Later specs register a handler for each job kind here.
    await run_worker(Settings(), {}, stop)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="crawlerai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('crawlerai')}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("openapi", help="print the API's OpenAPI document as JSON")
    commands.add_parser("worker", help="run a worker: claim queued tasks and run them until SIGINT or SIGTERM")
    args = parser.parse_args(argv)
    if args.command == "openapi":
        _print_openapi()
    elif args.command == "worker":
        asyncio.run(_work())
