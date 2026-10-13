"""Warn about tracked source files longer than 800 lines (C11, INV-18, ARCHITECTURE Appendix A #33).

800 lines is a soft limit: this check prints one warning per file past it and always exits 0. A file past the limit
is split along logical boundaries (cohesive modules, field types per C8), never mechanically to meet the number.
Source files are the tracked Python, JavaScript, TypeScript and shell files; generated files are not counted. In
GitHub Actions (`GITHUB_ACTIONS=true`) each warning is a workflow annotation on its file.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

LIMIT = 800
SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".sh")
# Written by `make api-client` from the backend's OpenAPI document, never by hand.
GENERATED = frozenset({"frontend/src/api/schema.d.ts"})


def source_files(root: Path) -> list[str]:
    # Git writes paths as UTF-8 bytes; decoding them with the locale's encoding would misread non-ASCII names.
    output = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [path for path in output.split("\0") if path.endswith(SOURCE_SUFFIXES) and path not in GENERATED]


def line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def warning(path: str, count: int, *, github: bool) -> str:
    text = (
        f"{path} has {count} lines, over the soft limit of {LIMIT}. "
        "Split it along logical boundaries, not to meet the number."
    )
    return f"::warning file={path}::{text}" if github else f"warning: {text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    args = parser.parse_args(argv)

    github = os.environ.get("GITHUB_ACTIONS") == "true"
    paths = source_files(args.root)
    long = [(path, count) for path in paths if (count := line_count(args.root / path)) > LIMIT]
    for path, count in long:
        print(warning(path, count, github=github))
    if long:
        print(f"file-length: {len(long)} of {len(paths)} source files over {LIMIT} lines (a warning, not a failure)")
    else:
        print(f"file-length: ok, {len(paths)} source files within {LIMIT} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
