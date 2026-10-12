"""Behaviour of `tools/data_manifest_check.py` (SPEC-00 §4.1, INV-05), run as CI runs it."""

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


def test_listed_file_with_matching_hash_passes(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"vocab/list.txt": CONTENT}, {"entries": [entry("vocab/list.txt")]})

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "data-manifest: ok, 1 files\n"


def test_unlisted_data_file_fails(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        {"vocab/list.txt": CONTENT, "vocab/phrases.txt": b"in stock\n"},
        {"entries": [entry("vocab/list.txt")]},
    )

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/data/vocab/phrases.txt: not listed in backend/data/manifest.json"]


def test_hash_mismatch_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"list.txt": b"AAA\nCCC\n"}, {"entries": [entry("list.txt")]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/data/list.txt: sha256 does not match the manifest"]


def test_listed_but_missing_file_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path, {}, {"entries": [entry("list.txt")]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/data/list.txt: listed in the manifest but missing"]


@pytest.mark.parametrize("field", ["url", "version", "sha256", "license", "justification"])
def test_entry_missing_a_required_field_fails(tmp_path: Path, field: str) -> None:
    bad = entry("list.txt")
    del bad[field]
    root = make_root(tmp_path, {"list.txt": CONTENT}, {"entries": [bad]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"backend/data/manifest.json: entry 0 has no '{field}'"]


def test_empty_field_counts_as_missing(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"list.txt": CONTENT}, {"entries": [entry("list.txt", justification=" ")]})

    result = run_check(root)

    assert result.stdout.splitlines() == ["backend/data/manifest.json: entry 0 has no 'justification'"]


@pytest.mark.parametrize("path", ["../outside.txt", "/abs/list.txt", "manifest.json"])
def test_entry_path_must_name_a_data_file_inside_the_directory(tmp_path: Path, path: str) -> None:
    root = make_root(tmp_path, {}, {"entries": [entry(path)]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"backend/data/manifest.json: entry 0 has an invalid path {path!r}"]


def test_duplicate_entries_fail(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"list.txt": CONTENT}, {"entries": [entry("list.txt"), entry("list.txt")]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/data/manifest.json: entry 1 repeats path 'list.txt'"]


def test_missing_manifest_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"list.txt": CONTENT}, None)

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/data/manifest.json: missing"]


def test_malformed_manifest_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path, {}, None)
    (root / "backend" / "data" / "manifest.json").write_text("{not json", encoding="utf-8")

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.startswith("backend/data/manifest.json: not valid JSON")
