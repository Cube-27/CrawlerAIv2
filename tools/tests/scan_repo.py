"""Shared by the site-literal scan tests: the scan script and a git repository built from synthetic files."""

import os
import subprocess
from pathlib import Path

SCAN = Path(__file__).resolve().parents[1] / "site_literal_scan.py"


def make_repo(root: Path, files: dict[str, str | bytes]) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)  # noqa: S603, S607
    return root


# Set through the environment: `git -c` would put dotted config keys in the scanned test source.
IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(root: Path, *args: str) -> None:
    env = {**os.environ, **IDENTITY}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)  # noqa: S603, S607


def commit(root: Path) -> None:
    """Commit what `make_repo` staged."""
    git(root, "commit", "-q", "--no-verify", "-m", "c")
