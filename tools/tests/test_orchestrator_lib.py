"""Behaviour of `tools/orchestrator/lib.sh`, sourced under bash: the worktree root is beside the main checkout, from
the main checkout and from any of its worktrees alike."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from scan_repo import IDENTITY

LIB = Path(__file__).resolve().parents[1] / "orchestrator" / "lib.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(BASH is None or GIT is None, reason="needs bash and git")


def git(cwd: Path, *args: str) -> None:
    subprocess.run([str(GIT), *args], cwd=cwd, env={**os.environ, **IDENTITY}, check=True, capture_output=True)  # noqa: S603


def lib(cwd: Path, call: str) -> str:
    result = subprocess.run(  # noqa: S603
        [str(BASH), "-c", f'source "$1"; {call}', "lib", LIB.as_posix()],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def test_main_checkout_and_worktree_root_are_the_same_from_every_worktree(tmp_path: Path) -> None:
    main = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", main.as_posix())
    git(main, "commit", "-q", "--allow-empty", "-m", "base")
    linked = tmp_path / "CrawlerAIv2-worktrees" / "spec-01-pr-1"
    git(main, "worktree", "add", "-q", "-b", "spec-01/pr-1", linked.as_posix())

    for cwd in (main, linked):
        assert Path(lib(cwd, "main_checkout")).resolve() == main.resolve()
        assert Path(lib(cwd, "worktrees_root")).resolve() == linked.parent.resolve()
    assert lib(linked, "worktrees_root /x/y/main") == "/x/y/CrawlerAIv2-worktrees"


def test_outside_a_repository_both_print_nothing(tmp_path: Path) -> None:
    assert (lib(tmp_path, "main_checkout"), lib(tmp_path, "worktrees_root")) == ("", "")
