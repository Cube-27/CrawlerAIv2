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


def test_fetched_entry_may_be_absent(tmp_path: Path) -> None:
    # SPEC-04 §4.6: a fetched file is downloaded by `crawlerai data fetch` and never committed.
    root = make_root(tmp_path, {}, {"entries": [entry("geo/cities.txt") | {"fetched": True}]})

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "data-manifest: ok, 1 files\n"


def test_fetched_entry_that_is_present_must_match_its_hash(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"geo/cities.txt": b"other"}, {"entries": [entry("geo/cities.txt") | {"fetched": True}]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/data/geo/cities.txt: sha256 does not match the manifest"]


@pytest.mark.parametrize("value", ["true", 1, None])
def test_fetched_must_be_a_boolean(tmp_path: Path, value: object) -> None:
    root = make_root(tmp_path, {"list.txt": CONTENT}, {"entries": [entry("list.txt") | {"fetched": value}]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/data/manifest.json: entry 0 has a 'fetched' that is not true or false"
    ]


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


# --- dev-fitted files (D-0444, D-0576, owner answers 2026-10-14 and 2026-10-16): exempt from the pin, checked by
# their stamp ---

PRECEDENCE = b"source_split: dev\ntext:\n- jsonld\n- og\n"
CALIBRATION = json.dumps({"calibration_version": 1, "source_split": "dev", "buckets": {}}).encode()
MARGINS = json.dumps({"yield": 0.2, "validity": 0.1, "source_split": "dev", "fit": "spec default, unfitted"}).encode()


def test_dev_fitted_files_need_no_manifest_entry(tmp_path: Path) -> None:
    files = {
        "list.txt": CONTENT,
        "source_precedence.yaml": PRECEDENCE,
        "calibration.json": CALIBRATION,
        "drift_margins.json": MARGINS,
    }
    root = make_root(tmp_path, files, {"entries": [entry("list.txt")]})

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "data-manifest: ok, 1 files\n"


@pytest.mark.parametrize(
    "content",
    [b"source_split: 'dev'\n", b'source_split: "dev"  # fitted on dev\n', b"text: [jsonld]\nsource_split: dev\n"],
)
def test_a_precedence_stamp_may_be_quoted_commented_or_not_first(tmp_path: Path, content: bytes) -> None:
    root = make_root(tmp_path, {"source_precedence.yaml": content}, {"entries": []})

    result = run_check(root)

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "content",
    [
        b"text:\n- jsonld\n",  # no stamp
        b"source_split: hidden\ntext:\n- jsonld\n",  # fitted on another split
        b"text:\n  source_split: dev\n",  # nested, so not the file's stamp
    ],
)
def test_a_precedence_file_without_a_dev_stamp_fails(tmp_path: Path, content: bytes) -> None:
    root = make_root(tmp_path, {"source_precedence.yaml": content}, {"entries": []})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/data/source_precedence.yaml: a dev-fitted file needs the stamp 'source_split: dev'"
    ]


@pytest.mark.parametrize(
    "content",
    [b"{}", b'{"source_split": "fresh"}', b'[{"source_split": "dev"}]', b"{not json"],
)
def test_a_calibration_without_a_dev_stamp_fails(tmp_path: Path, content: bytes) -> None:
    root = make_root(tmp_path, {"calibration.json": content}, {"entries": []})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/data/calibration.json: a dev-fitted file needs the stamp 'source_split: dev'"
    ]


@pytest.mark.parametrize("content", [b'{"yield": 0.2, "validity": 0.1}', b'{"source_split": "hidden"}'])
def test_drift_margins_without_a_dev_stamp_fail(tmp_path: Path, content: bytes) -> None:
    root = make_root(tmp_path, {"drift_margins.json": content}, {"entries": []})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/data/drift_margins.json: a dev-fitted file needs the stamp 'source_split: dev'"
    ]


def test_only_the_top_level_fitted_files_are_exempt(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"vocab/calibration.json": CALIBRATION}, {"entries": []})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/data/vocab/calibration.json: not listed in backend/data/manifest.json"
    ]


def test_a_dev_fitted_file_is_not_pinned_in_the_manifest(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"calibration.json": CALIBRATION}, {"entries": [entry("calibration.json", CALIBRATION)]})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/data/manifest.json: entry 0 pins 'calibration.json', a dev-fitted file checked by its stamp instead"
    ]
