import hashlib
from pathlib import Path

import pytest

from snowcrawl.core.engine_version import engine_version

SHA = "0123456789abcdef0123456789abcdef01234567"


def _backend(tmp_path: Path, version: str | None, calibration: bytes | None) -> Path:
    if version is not None:
        (tmp_path / "VERSION").write_text(version)
    if calibration is not None:
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "data" / "calibration.json").write_bytes(calibration)
    return tmp_path


def test_the_version_joins_the_build_sha_and_the_calibration_hash(tmp_path: Path) -> None:
    calibration = b'{"buckets": []}'

    version = engine_version(_backend(tmp_path, f"{SHA}\n", calibration))

    assert version == f"{SHA}+cal.{hashlib.sha256(calibration).hexdigest()[:12]}"


@pytest.mark.parametrize("content", ["", "0123abz", "0123", f"{SHA} dirty"])
def test_a_version_file_that_is_not_a_git_sha_is_refused(tmp_path: Path, content: str) -> None:
    backend = _backend(tmp_path, content, None)

    with pytest.raises(ValueError, match="VERSION"):
        engine_version(backend)
