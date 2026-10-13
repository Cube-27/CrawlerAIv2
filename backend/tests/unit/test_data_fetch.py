"""`crawlerai data fetch` (SPEC-04 §4.6, INV-05): the manifest's fetched entries are downloaded, checked against their
pinned sha256 and written under the data directory; nothing else is written."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from crawlerai.core.data import DataFetchError, fetch_data

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
    assert report == ["fetched geo/cities.txt"]


def test_a_file_that_already_matches_is_not_downloaded_again(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("cities.txt"))
    (directory / "cities.txt").write_bytes(CONTENT)
    calls: list[str] = []

    report = fetch_data(directory, _serving({}, calls))

    assert calls == []
    assert report == ["present cities.txt"]


def test_a_committed_entry_is_not_fetched(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("tlds.txt", fetched=False))
    calls: list[str] = []

    report = fetch_data(directory, _serving({}, calls))

    assert calls == []
    assert report == []


def test_a_download_that_does_not_match_its_hash_is_refused_and_not_written(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("cities.txt"))
    download = _serving({"https://data.example.org/cities.txt": b"changed upstream"}, [])

    with pytest.raises(DataFetchError, match=r"cities\.txt: sha256 .* does not match the manifest"):
        fetch_data(directory, download)

    assert sorted(p.name for p in directory.iterdir()) == ["manifest.json"]


def test_a_stale_file_is_replaced(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("cities.txt"))
    (directory / "cities.txt").write_bytes(b"old snapshot")

    report = fetch_data(directory, _serving({"https://data.example.org/cities.txt": CONTENT}, []))

    assert (directory / "cities.txt").read_bytes() == CONTENT
    assert report == ["fetched cities.txt"]


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/outside.txt", "a/../../outside.txt"])
def test_an_entry_path_outside_the_data_directory_is_refused(tmp_path: Path, path: str) -> None:
    directory = _data_dir(tmp_path, _entry(path))
    download = _serving({f"https://data.example.org/{path}": CONTENT}, [])

    with pytest.raises(DataFetchError, match="outside the data directory"):
        fetch_data(directory, download)

    assert not (tmp_path / "outside.txt").exists()


def test_only_https_urls_are_fetched(tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, _entry("cities.txt", url="http://data.example.org/cities.txt"))
    calls: list[str] = []
    download = _serving({}, calls)

    with pytest.raises(DataFetchError, match="not an https URL"):
        fetch_data(directory, download)

    assert calls == []
