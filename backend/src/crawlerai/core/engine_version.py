"""The engine version stamped on jobs, extractions, capture manifests and eval runs (SPEC-01 §4.7):
`<git sha>+cal.<calibration hash>`, so a replay can tell which code and which calibration produced a result.

The build writes the git SHA to `backend/VERSION`; the calibration is `backend/data/calibration.json` (SPEC-05). A
source tree without them reports `unknown` and `none` rather than a guess.
"""

import hashlib
import re
from pathlib import Path
from typing import Final

BACKEND_DIR: Final = Path(__file__).resolve().parents[3]
VERSION_FILE: Final = BACKEND_DIR / "VERSION"
CALIBRATION_FILE: Final = BACKEND_DIR / "data" / "calibration.json"

# A git object name: 7 to 40 hex digits (SHA-1, abbreviated or full) or 64 (SHA-256 repositories).
GIT_SHA: Final = re.compile(r"[0-9a-f]{7,40}|[0-9a-f]{64}")
CALIBRATION_HASH_DIGITS: Final = 12


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


ENGINE_VERSION: Final = engine_version(VERSION_FILE, CALIBRATION_FILE)
