"""The Makefile's default object store (SPEC-00 §4.4): an `fs:///<absolute path>` URL under the checkout, on POSIX
paths and on Windows drive-letter paths alike."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
MAKE = shutil.which("make")


def _object_store(tmp_path: Path, curdir: str) -> str:
    """`CRAWLERAI_OBJECT_STORE` as the Makefile sets it when run from `curdir`, with no `.env` setting it."""
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    env = {name: value for name, value in os.environ.items() if name != "CRAWLERAI_OBJECT_STORE"}
    show = "show: ; @echo $(CRAWLERAI_OBJECT_STORE)"
    args = [str(MAKE), "-s", "-C", str(tmp_path), "--eval", show, "show", f"CURDIR={curdir}"]
    return subprocess.run(args, capture_output=True, text=True, check=True, env=env).stdout.strip()  # noqa: S603


@pytest.mark.skipif(MAKE is None, reason="needs GNU make")
@pytest.mark.parametrize(
    ("curdir", "expected"),
    [
        ("/home/dev/repo", "fs:///home/dev/repo/.data/objects"),
        ("C:/Projects/repo", "fs:///C:/Projects/repo/.data/objects"),
    ],
    ids=["posix", "windows-drive"],
)
def test_the_default_object_store_is_an_fs_url_with_an_absolute_path(
    tmp_path: Path, curdir: str, expected: str
) -> None:
    assert _object_store(tmp_path, curdir) == expected
