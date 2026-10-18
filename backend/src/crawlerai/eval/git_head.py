"""The commit an eval run is stamped with: the source tree's `HEAD`."""

import shutil
import subprocess
from pathlib import Path


class GitUnavailable(Exception):
    """git is not on PATH, or the directory is not in a repository with a commit."""


def head_commit(repo: Path) -> str:
    """The full sha of `HEAD` in the repository at `repo`."""
    git = shutil.which("git")
    if git is None:
        raise GitUnavailable("git is not on PATH")
    # A fixed argv with no shell; `--verify` prints exactly one object name or fails.
    result = subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise GitUnavailable(f"git rev-parse HEAD failed: {result.stderr.strip()}")
    return result.stdout.strip()
