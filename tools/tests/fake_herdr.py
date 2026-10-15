"""Shared by the orchestrator script tests: a `herdr agent list` listing and fake executables on PATH."""

import json
import os
import subprocess
from pathlib import Path

from scan_repo import git

# Logs every call; `herdr agent list` prints the listing in $FAKE_HERDR_LIST.
FAKE_HERDR = """#!/bin/bash
echo "herdr $*" >> "$FAKE_LOG"
if [[ "$1 $2" == "agent list" ]]; then cat "$FAKE_HERDR_LIST"; fi
"""


def herdr_list(agents: list[tuple[str | None, str, str]]) -> str:
    """`herdr agent list` JSON for (name, cwd, status) triples."""
    rows = [{"name": name, "cwd": cwd, "agent_status": status} for name, cwd, status in agents]
    return json.dumps({"result": {"agents": rows}})


def herdr_cwd(path: Path) -> str:
    """PATH as herdr prints an agent's cwd: the path git reports, with Windows backslashes."""
    top = subprocess.run(  # noqa: S603
        ["git", "-C", path.as_posix(), "rev-parse", "--show-toplevel"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return top.stdout.strip().replace("/", "\\")


def init_main(tmp_path: Path) -> tuple[Path, str, str]:
    """A main checkout at TMP_PATH/repo, with its cwd and its worktrees root's as herdr prints them."""
    main = tmp_path / "repo"
    git(tmp_path, "init", "-q", main.as_posix())
    main_cwd = herdr_cwd(main)
    return main, main_cwd, main_cwd.rsplit("\\", 1)[0] + r"\CrawlerAIv2-worktrees"


def fake_env(tmp_path: Path, executables: dict[str, str], listing: str) -> dict[str, str]:
    """An environment with EXECUTABLES (name -> script) first on PATH, a call log and the herdr LISTING."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for exe, text in executables.items():
        (bin_dir / exe).write_text(text, newline="\n")
        (bin_dir / exe).chmod(0o755)
    (tmp_path / "calls.log").touch()
    (tmp_path / "herdr_list.json").write_text(listing, newline="\n")
    return {
        **os.environ,
        "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": (tmp_path / "calls.log").as_posix(),
        "FAKE_HERDR_LIST": (tmp_path / "herdr_list.json").as_posix(),
    }
