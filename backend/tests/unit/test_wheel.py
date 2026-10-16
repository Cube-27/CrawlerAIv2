"""The wheel carries `VERSION` and the manifest's data files, and an installed copy finds them (D-0492)."""

import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from hatchling.builders.sdist import SdistBuilder
from hatchling.builders.wheel import WheelBuilder

from crawlerai.config_ir.drift import MARGINS_FILE
from crawlerai.core import engine_version as engine_version_module
from crawlerai.core.engine_version import CALIBRATION_FILE, PACKAGED_ENGINE_DIR, engine_dir, engine_version
from crawlerai.resolve.preference import PRECEDENCE_FILE

BACKEND = Path(__file__).resolve().parents[2]
SHA = "0123456789abcdef0123456789abcdef01234567"
_HOOK = importlib.util.spec_from_file_location("hatch_build", BACKEND / "hatch_build.py")
assert _HOOK is not None
assert _HOOK.loader is not None
hatch_build = importlib.util.module_from_spec(_HOOK)
_HOOK.loader.exec_module(hatch_build)
CALIBRATION = b'{"source_split": "dev", "buckets": []}'


def _project(root: Path) -> Path:
    """A copy of the backend's build configuration and engine-version module, with synthetic data files: one listed
    and present, one listed but not fetched, dev-fitted calibration and margins, and an unlisted file."""
    root.mkdir()
    shutil.copy(BACKEND / "pyproject.toml", root)
    shutil.copy(BACKEND / "hatch_build.py", root)
    core = root / "src" / "crawlerai" / "core"
    core.mkdir(parents=True)
    (root / "src" / "crawlerai" / "__init__.py").write_text("")
    (core / "__init__.py").write_text("")
    shutil.copy(BACKEND / "src" / "crawlerai" / "core" / "engine_version.py", core)
    data = root / "data"
    (data / "listed").mkdir(parents=True)
    (data / "listed" / "words.txt").write_text("synthetic\n")
    (data / "calibration.json").write_bytes(CALIBRATION)
    (data / "drift_margins.json").write_text('{"source_split": "dev"}')
    (data / "stray.txt").write_text("not in the manifest\n")
    entries = [{"path": "listed/words.txt"}, {"path": "fetched/big.txt", "fetched": True}]
    (data / "manifest.json").write_text(json.dumps({"entries": entries}))
    return root


def _build(root: Path, out: Path) -> zipfile.ZipFile:
    [wheel] = WheelBuilder(str(root)).build(directory=str(out), versions=["standard"])
    return zipfile.ZipFile(wheel)


def test_the_wheel_holds_the_version_and_the_listed_data_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_GIT_SHA", SHA)
    root = _project(tmp_path / "project")

    with _build(root, tmp_path / "dist") as wheel:
        packaged = sorted(name for name in wheel.namelist() if name.startswith("crawlerai/_engine/"))
        version = wheel.read("crawlerai/_engine/VERSION")

    assert packaged == [
        "crawlerai/_engine/VERSION",
        "crawlerai/_engine/data/calibration.json",
        "crawlerai/_engine/data/drift_margins.json",
        "crawlerai/_engine/data/listed/words.txt",
        "crawlerai/_engine/data/manifest.json",
    ]
    assert version == f"{SHA}\n".encode()


def test_an_installed_wheel_reports_its_build_and_calibration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_GIT_SHA", SHA)
    root = _project(tmp_path / "project")
    site_packages = tmp_path / "site-packages"
    with _build(root, tmp_path / "dist") as wheel:
        wheel.extractall(site_packages)

    engine = engine_dir(site_packages / "crawlerai" / "core" / "engine_version.py")

    assert engine == site_packages / "crawlerai" / "_engine"
    assert engine_version(engine) == f"{SHA}+cal.{hashlib.sha256(CALIBRATION).hexdigest()[:12]}"


def test_a_wheel_built_from_the_sdist_carries_the_version_and_the_data_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CRAWLERAI_GIT_SHA", SHA)
    root = _project(tmp_path / "project")
    [sdist] = SdistBuilder(str(root)).build(directory=str(tmp_path / "sdist"), versions=["standard"])
    shutil.unpack_archive(sdist, tmp_path / "unpacked", filter="data")
    [unpacked] = (tmp_path / "unpacked").iterdir()
    # The unpacked sdist is no checkout, and nothing names the commit: the sdist's VERSION does.
    monkeypatch.delenv("CRAWLERAI_GIT_SHA")

    with _build(unpacked, tmp_path / "dist") as wheel:
        packaged = sorted(name for name in wheel.namelist() if name.startswith("crawlerai/_engine/"))
        version = wheel.read("crawlerai/_engine/VERSION")

    assert packaged == [
        "crawlerai/_engine/VERSION",
        "crawlerai/_engine/data/calibration.json",
        "crawlerai/_engine/data/drift_margins.json",
        "crawlerai/_engine/data/listed/words.txt",
        "crawlerai/_engine/data/manifest.json",
    ]
    assert version == f"{SHA}\n".encode()


def test_a_wheel_build_with_no_commit_to_name_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRAWLERAI_GIT_SHA", raising=False)
    root = _project(tmp_path / "project")  # no checkout, no VERSION
    out = tmp_path / "dist"

    with pytest.raises(RuntimeError, match="CRAWLERAI_GIT_SHA"):
        _build(root, out)


def test_a_build_given_something_other_than_a_sha_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_GIT_SHA", "main")
    root = _project(tmp_path / "project")
    out = tmp_path / "dist"

    with pytest.raises(ValueError, match="not a git SHA"):
        _build(root, out)


def test_the_build_hook_names_what_the_engine_reads() -> None:
    # The hook runs in the build environment, without the package, so it keeps its own copies of these names.
    assert f"crawlerai/{PACKAGED_ENGINE_DIR}" == hatch_build.PACKAGED
    assert hatch_build._GIT_SHA.pattern == engine_version_module._GIT_SHA.pattern
    assert set(hatch_build._DEV_FITTED) == {PRECEDENCE_FILE, CALIBRATION_FILE, MARGINS_FILE}
