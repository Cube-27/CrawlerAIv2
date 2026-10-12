"""The `crawlerai` command-line entry point."""

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version

from crawlerai.api.app import create_app


def _print_openapi() -> None:
    # Sorted keys and LF bytes on every platform keep `frontend/openapi.json` byte-identical across regenerations,
    # which the CI freshness check (SPEC-00 §4.5) relies on.
    text = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    sys.stdout.buffer.write(text.encode())


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="crawlerai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('crawlerai')}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("openapi", help="print the API's OpenAPI document as JSON")
    args = parser.parse_args(argv)
    if args.command == "openapi":
        _print_openapi()
