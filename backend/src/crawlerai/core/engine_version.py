"""The engine version stamped on jobs, extractions, and capture manifests:
`<git sha>+cal.<calibration hash>`, so a replay can tell which code and which calibration produced a result.

The build writes the git SHA to `backend/VERSION`; the calibration is `backend/data/calibration.json`.
Both are read from the engine directory: the backend source tree the package runs from, or in an installed wheel the
copy of `VERSION` and `data/` that the build puts inside the package (`backend/hatch_build.py`). A missing file reports
`unknown` or `none` rather than a guess.
"""

import hashlib
import re
from pathlib import Path
from typing import Final

# A git object name: 7 to 40 hex digits (SHA-1, abbreviated or full) or 64 (SHA-256 repositories).
_GIT_SHA: Final = re.compile(r"[0-9a-f]{7,40}|[0-9a-f]{64}")
_CALIBRATION_HASH_DIGITS: Final = 12
CALIBRATION_FILE: Final = "calibration.json"
# Where a wheel holds its copy of `VERSION` and `data/`, inside the `crawlerai` package (`backend/hatch_build.py`).
PACKAGED_ENGINE_DIR: Final = "_engine"


def backend_dir(module_file: Path) -> Path | None:
    """The `backend/` directory when `module_file` (this module) is `backend/src/crawlerai/core/...` of a source tree,
    recognised by its `pyproject.toml`; `None` for an installed package."""
    candidate = module_file.resolve().parents[3]
    return candidate if (candidate / "pyproject.toml").is_file() else None


def engine_dir(module_file: Path) -> Path | None:
    """The directory holding `VERSION` and `data/` for `module_file` (a module one package below `crawlerai`): the
    source tree's `backend/`, else the installed package's copy; `None` when there is neither."""
    backend = backend_dir(module_file)
    if backend is not None:
        return backend
    packaged = module_file.resolve().parents[1] / PACKAGED_ENGINE_DIR
    return packaged if packaged.is_dir() else None


def data_dir(backend: Path) -> Path:
    """Where the engine's data files live under `backend`: its calibration, precedence and vocabularies."""
    return backend / "data"


def engine_version(backend: Path | None) -> str:
    """The version of the engine whose build output and calibration are under `backend` (`None`: no engine
    directory)."""
    if backend is None:
        return "unknown+cal.none"
    version_file = backend / "VERSION"
    try:
        sha = version_file.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        sha = "unknown"
    else:
        if not _GIT_SHA.fullmatch(sha):
            raise ValueError(f"{version_file.name} does not hold a git SHA: {sha!r}")
    try:
        calibration_bytes = (data_dir(backend) / CALIBRATION_FILE).read_bytes()
    except FileNotFoundError:
        calibration = "none"
    else:
        calibration = hashlib.sha256(calibration_bytes).hexdigest()[:_CALIBRATION_HASH_DIGITS]
    return f"{sha}+cal.{calibration}"


ENGINE_DIR: Final = engine_dir(Path(__file__))
ENGINE_VERSION: Final = engine_version(ENGINE_DIR)


def engine_data_dir() -> Path | None:
    """The engine directory's `data/`: its calibration, precedence, vocabularies and fetched files; `None` without
    an engine directory."""
    return None if ENGINE_DIR is None else data_dir(ENGINE_DIR)
