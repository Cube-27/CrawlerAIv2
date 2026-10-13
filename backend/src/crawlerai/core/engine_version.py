"""The engine version stamped on jobs, extractions, capture manifests and eval runs (SPEC-01 §4.7):
`<git sha>+cal.<calibration hash>`, so a replay can tell which code and which calibration produced a result.

The build writes the git SHA to `backend/VERSION`; the calibration is `backend/data/calibration.json` (SPEC-05). Both
are read from the backend source tree the package runs from. A missing file reports `unknown` or `none` rather than a
guess, and so does an installed wheel, which has no backend tree (shipping both in the image is a follow-up).
"""

import hashlib
import re
from pathlib import Path
from typing import Final

# A git object name: 7 to 40 hex digits (SHA-1, abbreviated or full) or 64 (SHA-256 repositories).
GIT_SHA: Final = re.compile(r"[0-9a-f]{7,40}|[0-9a-f]{64}")
CALIBRATION_HASH_DIGITS: Final = 12


def backend_dir(module_file: Path) -> Path | None:
    """The `backend/` directory when `module_file` (this module) is `backend/src/crawlerai/core/...` of a source tree,
    recognised by its `pyproject.toml`; `None` for an installed package."""
    candidate = module_file.resolve().parents[3]
    return candidate if (candidate / "pyproject.toml").is_file() else None


def engine_version(version_file: Path, calibration_file: Path) -> str:
    try:
        sha = version_file.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        sha = "unknown"
    else:
        if not GIT_SHA.fullmatch(sha):
            raise ValueError(f"{version_file.name} does not hold a git SHA: {sha!r}")
    try:
        calibration = hashlib.sha256(calibration_file.read_bytes()).hexdigest()[:CALIBRATION_HASH_DIGITS]
    except FileNotFoundError:
        calibration = "none"
    return f"{sha}+cal.{calibration}"


BACKEND_DIR: Final = backend_dir(Path(__file__))
ENGINE_VERSION: Final = (
    engine_version(BACKEND_DIR / "VERSION", BACKEND_DIR / "data" / "calibration.json")
    if BACKEND_DIR
    else "unknown+cal.none"
)
