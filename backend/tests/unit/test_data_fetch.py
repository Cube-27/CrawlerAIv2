"""`crawlerai data fetch` (schemas spec, INV-05): the manifest's fetched entries are downloaded, checked against their
pinned sha256 and written under the data directory; nothing else is written."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from crawlerai.core.data import DataReport, fetch_data

CONTENT = b"geonameid\tname\n"


def _entry(path: str, content: bytes = CONTENT, *, fetched: bool = True, url: str | None = None) -> dict[str, object]:
    return {
        "path": path,
        "url": url or f"https://data.example.org/{path}",
        "version": "2026-10-01",
        "sha256": hashlib.sha256(content).hexdigest(),
        "license": "CC-BY-4.0",
        "justification": "Synthetic data for tests.",
        "fetched": fetched,
    }


def _data_dir(tmp_path: Path, *entries: dict[str, object]) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({"entries": list(entries)}), encoding="utf-8")
    return directory


def _serving(files: dict[str, bytes], calls: list[str]) -> Callable[[str], bytes]:
    def download(url: str) -> bytes:
        calls.append(url)
        return files[url]

    return download


def test_a_fetched_entry_is_downloaded_and_written(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("geo/cities.txt"))
    calls: list[str] = []

    report = fetch_data(directory, _serving({"https://data.example.org/geo/cities.txt": CONTENT}, calls))

    assert (directory / "geo" / "cities.txt").read_bytes() == CONTENT
    assert report == DataReport(written=["fetched geo/cities.txt"], refused=[])


def test_a_download_that_does_not_match_its_hash_is_refused_and_not_written(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("cities.txt"))
    download = _serving({"https://data.example.org/cities.txt": b"changed upstream"}, [])

    report = fetch_data(directory, download)

    got = hashlib.sha256(b"changed upstream").hexdigest()
    assert report.refused == [
        f"cities.txt: sha256 {got} does not match the manifest; the source changed, so the entry needs re-pinning"
    ]
    assert sorted(p.name for p in directory.iterdir()) == ["manifest.json"]


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/outside.txt"])
def test_an_entry_path_outside_the_data_directory_is_refused(tmp_path: Path, path: str) -> None:
    directory = _data_dir(tmp_path, _entry(path))
    download = _serving({f"https://data.example.org/{path}": CONTENT}, [])

    report = fetch_data(directory, download)

    assert report.refused == [f"{path}: outside the data directory"]
    assert not (tmp_path / "outside.txt").exists()


def test_only_https_urls_are_fetched(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("cities.txt", url="http://data.example.org/cities.txt"))
    calls: list[str] = []
    download = _serving({}, calls)

    report = fetch_data(directory, download)

    assert report.refused == ["cities.txt: http://data.example.org/cities.txt is not an https URL"]
    assert calls == []
