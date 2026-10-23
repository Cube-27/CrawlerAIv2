"""Behaviour of `tools/data_manifest_check.py`, run as CI runs it."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

CHECK = Path(__file__).resolve().parents[1] / "data_manifest_check.py"
CONTENT = b"AAA\nBBB\n"


def entry(path: str, content: bytes = CONTENT, **overrides: str) -> dict[str, str]:
    fields = {
        "path": path,
        "url": "https://data.example.org/list.txt",
        "version": "2026-10-01",
        "sha256": hashlib.sha256(content).hexdigest(),
        "license": "CC-BY-4.0",
        "justification": "Synthetic vocabulary for tests.",
    }
    return fields | overrides


def make_root(root: Path, files: dict[str, bytes], manifest: Any) -> Path:
    data = root / "backend" / "data"
    data.mkdir(parents=True)
    for name, content in files.items():
        (data / name).parent.mkdir(parents=True, exist_ok=True)
        (data / name).write_bytes(content)
    if manifest is not None:
        (data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def run_check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CHECK), "--root", str(root)], capture_output=True, text=True, check=False
    )


CALIBRATION = json.dumps({"calibration_version": 1, "source_split": "dev", "buckets": {}}).encode()


def test_listed_files_and_absent_fetched_entries_pass_and_dev_stamped_files_need_no_entry(tmp_path: Path) -> None:
    # A fetched file is downloaded by `crawlerai data fetch` and never committed.
    entries = [entry("vocab/list.txt"), entry("geo/cities.txt") | {"fetched": True}]
    files = {"vocab/list.txt": CONTENT, "calibration.json": CALIBRATION}

    result = run_check(make_root(tmp_path, files, {"entries": entries}))

    assert (result.returncode, result.stdout) == (0, "data-manifest: ok, 2 files\n")


@pytest.mark.parametrize(
    ("files", "entries", "expected"),
    [
        (
            {"a.txt": CONTENT, "b.txt": b"x"},
            [entry("a.txt")],
            "backend/data/b.txt: not listed in backend/data/manifest.json",
        ),
        ({"a.txt": b"other"}, [entry("a.txt")], "backend/data/a.txt: sha256 does not match the manifest"),
        ({}, [entry("a.txt")], "backend/data/a.txt: listed in the manifest but missing"),
        ({}, [entry("../x.txt")], "backend/data/manifest.json: entry 0 has an invalid path '../x.txt'"),
        (
            {"calibration.json": b'{"source_split": "fresh"}'},
            [],
            "backend/data/calibration.json: a dev-fitted file needs the stamp 'source_split: dev'",
        ),
    ],
)
def test_manifest_violations_fail_with_one_message(
    tmp_path: Path, files: dict[str, bytes], entries: list[dict[str, str]], expected: str
) -> None:
    result = run_check(make_root(tmp_path, files, {"entries": entries}))

    assert result.returncode == 1
    assert result.stdout.splitlines() == [expected]
