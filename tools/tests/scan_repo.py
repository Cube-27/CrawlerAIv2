"""Shared by the site-literal scan tests: the scan script and a git repository built from synthetic files."""

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
