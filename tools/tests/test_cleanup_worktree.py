"""Behaviour of `tools/orchestrator/cleanup_worktree.sh`, run under bash against a real throwaway repository (a main
checkout, a bare `origin` and one worktree), with fake `gh` and `docker` on PATH. It deletes a branch only when the
branch's PR is merged, or when the branch has no PR and is merged into origin/main; otherwise it keeps everything."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_bin import fake_bin
from scan_repo import IDENTITY

CLEANUP = Path(__file__).resolve().parents[1] / "orchestrator" / "cleanup_worktree.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")
WT = "spec-01-pr-1"
BRANCH = "spec-01/pr-1-thing"
FAKE_GH = """#!/bin/bash
if [[ -n ${FAKE_GH_FAIL:-} ]]; then echo "GraphQL: Something went wrong" >&2; exit 1; fi
printf '%s' "$FAKE_GH_PRS"
"""
FAKE_DOCKER = '#!/bin/bash\necho "$*" >> "$FAKE_DOCKER_LOG"\n'

pytestmark = pytest.mark.skipif(BASH is None or GIT is None, reason="needs bash and git")


@dataclass(frozen=True)
class Repo:
    main: Path
    worktree: Path
    docker_log: Path
    env: dict[str, str]


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


def make_repo(tmp_path: Path, *, branch_ahead: bool) -> Repo:
    origin = tmp_path / "origin.git"
    main = tmp_path / "main"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", origin.as_posix())
    git(tmp_path, "init", "-q", "-b", "main", main.as_posix())
    git(main, "commit", "-q", "--allow-empty", "-m", "base")
    git(main, "remote", "add", "origin", origin.as_posix())
    git(main, "push", "-q", "-u", "origin", "main")
    worktree = tmp_path / "CrawlerAIv2-worktrees" / WT
    git(main, "worktree", "add", "-q", "-b", BRANCH, worktree.as_posix())
    if branch_ahead:
        git(worktree, "commit", "-q", "--allow-empty", "-m", "work")
    git(worktree, "push", "-q", "origin", BRANCH)
    docker_log = tmp_path / "docker.log"
    env = fake_bin(tmp_path, {"gh": FAKE_GH, "docker": FAKE_DOCKER}, FAKE_DOCKER_LOG=docker_log.as_posix())
    return Repo(main, worktree, docker_log, env)


def run_cleanup(repo: Repo, *, prs: tuple[str, ...] = (), gh_fails: bool = False) -> subprocess.CompletedProcess[str]:
    env = {**repo.env, "FAKE_GH_PRS": "\n".join(prs)}
    if gh_fails:
        env["FAKE_GH_FAIL"] = "1"
    return subprocess.run(  # noqa: S603
        [str(BASH), CLEANUP.as_posix(), WT, BRANCH],
        cwd=repo.main,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def tip(repo: Repo) -> str:
    return git(repo.worktree, "rev-parse", "HEAD")


def branch_state(repo: Repo) -> tuple[bool, bool]:
    local = git(repo.main, "branch", "--list", BRANCH) != ""
    remote = git(repo.main, "ls-remote", "--heads", "origin", BRANCH) != ""
    return local, remote


def assert_kept(repo: Repo, result: subprocess.CompletedProcess[str], reason: str) -> None:
    assert result.returncode == 1
    assert result.stderr.splitlines()[-1] == (
        f"ERROR {reason}: kept the worktree {WT}, the branch {BRANCH} and the containers"
    )
    assert repo.worktree.is_dir()
    assert branch_state(repo) == (True, True)
    assert not repo.docker_log.exists()


def assert_removed(repo: Repo, result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stderr
    assert not repo.worktree.exists()
    assert branch_state(repo) == (False, False)
    assert repo.docker_log.exists()


def test_merged_pr_at_the_tip_removes_worktree_and_branches(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=True)
    assert_removed(repo, run_cleanup(repo, prs=(f"MERGED {tip(repo)}",)))


def test_open_pr_keeps_everything(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=True)
    prs = (f"MERGED {tip(repo)}", f"OPEN {tip(repo)}")
    assert_kept(repo, run_cleanup(repo, prs=prs), f"a PR for {BRANCH} is open")


def test_no_pr_and_merged_into_main_removes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=False)
    assert_removed(repo, run_cleanup(repo))
