"""Fetch the data files that the manifest pins but the repository does not hold (C4).

`backend/data/manifest.json` lists every data file with its source URL and sha256. An entry marked `"fetched": true`
is not committed (a third-party snapshot such as the schema.org vocabulary); `fetch_data` downloads it, checks its
bytes against the pinned hash, and only then writes it. `tools/data_manifest_check.py` checks the same manifest in CI.
"""

import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlsplit

MANIFEST = "manifest.json"
_TIMEOUT_SECONDS = 120


class _Refused(Exception):
    """An entry that could not be written as the manifest pins it."""


@dataclass(frozen=True)
class DataReport:
    """What `fetch_data` did: one line per entry it wrote or found in place (`fetched <path>`, `present <path>`), and
    one per entry it refused (`<path>: <reason>`)."""

    written: list[str]
    refused: list[str]


def _download(url: str) -> bytes:
    # `fetch_data` admits only https URLs from the manifest, so no other scheme reaches urlopen.
    with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        body: bytes = response.read()
    return body


def fetch_data(data_dir: Path, download: Callable[[str], bytes] = _download) -> DataReport:
    """Download each fetched entry of `data_dir`'s manifest that is missing or differs from its pinned sha256.

    Every entry is tried, so one that is refused leaves the others fetched. An entry is refused when its path leaves
    `data_dir`, its URL is not https, its download fails, or the download does not match its hash; a refused entry
    is not written.
    """
    root = data_dir.resolve()
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    report = DataReport(written=[], refused=[])
    for entry in manifest["entries"]:
        if entry.get("fetched") is not True:
            continue
        path = str(entry["path"])
        try:
            report.written.append(_fetch_entry(root, path, str(entry["url"]), str(entry["sha256"]).lower(), download))
        except _Refused as refused:
            report.refused.append(f"{path}: {refused}")
    return report


def _fetch_entry(root: Path, path: str, url: str, sha256: str, download: Callable[[str], bytes]) -> str:
    """Write one entry unless it is already in place; its report line. Raises `_Refused`."""
    # The manifest is data: a path that resolves outside the data directory is never written.
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise _Refused("outside the data directory")
    if urlsplit(url).scheme != "https":
        raise _Refused(f"{url} is not an https URL")
    if target.is_file() and _sha256(target.read_bytes()) == sha256:
        return f"present {path}"
    try:
        content = download(url)
    # urllib's URLError and socket timeouts are OSErrors; a body cut short is http.client's IncompleteRead.
    except (OSError, HTTPException) as e:
        raise _Refused(f"download failed: {e}") from e
    if (got := _sha256(content)) != sha256:
        raise _Refused(f"sha256 {got} does not match the manifest; the source changed, so the entry needs re-pinning")
    try:
        _write_atomically(target, content)
    except OSError as e:
        raise _Refused(f"write failed: {e}") from e
    return f"fetched {path}"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_atomically(target: Path, content: bytes) -> None:
    # A reader never sees a partial file: the bytes go to a temporary file in the same directory, then replace the
    # target in one rename (os.replace is atomic on POSIX and Windows when both are on one volume).
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
