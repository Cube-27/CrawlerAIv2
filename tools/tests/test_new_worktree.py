"""Behaviour of `tools/orchestrator/new_worktree.sh`, run under bash against a real throwaway repository (a main
checkout and a bare `origin`). It creates `<main>/../CrawlerAIv2-worktrees/NAME` on a new branch off a freshly
fetched origin/main, and refuses, creating nothing, when the path or the branch already exists."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from scan_repo import IDENTITY

NEW_WORKTREE = Path(__file__).resolve().parents[1] / "orchestrator" / "new_worktree.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")
NAME = "spec-01-pr-1-3"
BRANCH = "spec-01/pr-1-3-thing"

pytestmark = pytest.mark.skipif(BASH is None or GIT is None, reason="needs bash and git")


@dataclass(frozen=True)
class Repo:
    main: Path
    origin: Path
    worktree: Path


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [str(GIT), *args],
        cwd=cwd,
        env={**os.environ, **IDENTITY},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Repo:
    origin = tmp_path / "origin.git"
    main = tmp_path / "main"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", origin.as_posix())
    git(tmp_path, "init", "-q", "-b", "main", main.as_posix())
    git(main, "commit", "-q", "--allow-empty", "-m", "base")
    git(main, "remote", "add", "origin", origin.as_posix())
    git(main, "push", "-q", "-u", "origin", "main")
    return Repo(main, origin, tmp_path / "CrawlerAIv2-worktrees" / NAME)


def advance_origin(repo: Repo, tmp_path: Path) -> str:
    """A commit pushed to origin/main from another clone, so the main checkout's origin/main is stale."""
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", repo.origin.as_posix(), other.as_posix())
    git(other, "commit", "-q", "--allow-empty", "-m", "newer")
    git(other, "push", "-q", "origin", "main")
    return git(other, "rev-parse", "HEAD")


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [str(BASH), NEW_WORKTREE.as_posix(), *args],
        cwd=cwd,
        env={**os.environ, **IDENTITY},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_creates_the_worktree_beside_main_off_fresh_origin_main(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    newest = advance_origin(repo, tmp_path)
    result = run(repo.main, NAME, BRANCH)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == repo.worktree
    assert git(repo.worktree, "rev-parse", "HEAD") == newest
    assert git(repo.worktree, "branch", "--show-current") == BRANCH


def test_existing_path_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.worktree.mkdir(parents=True)
    result = run(repo.main, NAME, BRANCH)
    assert result.returncode == 1
    assert result.stderr.strip() == f"ERROR {repo.worktree.as_posix()} already exists"
    assert git(repo.main, "branch", "--list", BRANCH) == ""


def test_existing_local_branch_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo.main, "branch", BRANCH)
    result = run(repo.main, NAME, BRANCH)
    assert result.returncode == 1
    assert result.stderr.strip() == f"ERROR branch {BRANCH} already exists"
    assert not repo.worktree.exists()


def test_existing_remote_branch_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo.main, "push", "-q", "origin", f"main:refs/heads/{BRANCH}")
    result = run(repo.main, NAME, BRANCH)
    assert result.returncode == 1
    assert result.stderr.strip() == f"ERROR branch {BRANCH} already exists on origin"
    assert not repo.worktree.exists()


@pytest.mark.parametrize("name", ["a/b", "..", ""])
def test_a_name_that_is_a_path_is_refused(tmp_path: Path, name: str) -> None:
    result = run(tmp_path, name, BRANCH)
    assert result.returncode == 2
    assert result.stderr.strip() == f"ERROR NAME must be a directory name, not a path: '{name}'"


def test_wrong_argument_count_prints_usage(tmp_path: Path) -> None:
    result = run(tmp_path, NAME)
    assert result.returncode == 2
    assert result.stderr.strip() == "usage: new_worktree.sh NAME BRANCH"
