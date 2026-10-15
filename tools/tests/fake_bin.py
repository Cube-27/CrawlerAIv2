"""Shared by the orchestrator script tests: fake executables first on PATH."""

import os
from pathlib import Path


def fake_bin(tmp_path: Path, executables: dict[str, str], **variables: str) -> dict[str, str]:
    """An environment with EXECUTABLES (name -> script) in TMP_PATH/bin, first on PATH, and the extra VARIABLES."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for exe, text in executables.items():
        (bin_dir / exe).write_text(text, newline="\n")
        (bin_dir / exe).chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}", **variables}
