import hashlib
from pathlib import Path

import pytest

from crawlerai.core.engine_version import backend_dir, engine_version

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


def test_any_change_to_the_calibration_changes_the_version(tmp_path: Path) -> None:
    first = engine_version(_backend(tmp_path, SHA, b'{"tau": 0.9}'))
    second = engine_version(_backend(tmp_path, SHA, b'{"tau": 0.91}'))

    assert first != second
    assert first.split("+")[0] == second.split("+")[0] == SHA


def test_a_tree_without_a_build_or_a_calibration_says_so(tmp_path: Path) -> None:
    assert engine_version(_backend(tmp_path, None, None)) == "unknown+cal.none"


def test_no_backend_tree_says_so() -> None:
    assert engine_version(None) == "unknown+cal.none"


@pytest.mark.parametrize("content", ["", "main", "0123abz", "0123", f"{SHA} dirty"])
def test_a_version_file_that_is_not_a_git_sha_is_refused(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match="VERSION"):
        engine_version(_backend(tmp_path, content, None))


def test_a_source_tree_is_found_from_the_module_path(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    module = tmp_path / "src" / "crawlerai" / "core" / "engine_version.py"

    assert backend_dir(module) == tmp_path


def test_an_installed_package_has_no_backend_tree(tmp_path: Path) -> None:
    module = tmp_path / "lib" / "python3.12" / "site-packages" / "crawlerai" / "core" / "engine_version.py"

    assert backend_dir(module) is None
