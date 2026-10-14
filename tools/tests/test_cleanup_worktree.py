"""Behaviour of `tools/orchestrator/cleanup_worktree.sh`, run under bash against a real throwaway repository (a main
checkout, a bare `origin` and one worktree), with fake `gh` and `docker` on PATH. It deletes a branch only when the
branch's PR is merged, or when the branch has no PR and is merged into origin/main; otherwise it keeps everything."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

CLEANUP = Path(__file__).resolve().parents[1] / "orchestrator" / "cleanup_worktree.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")
WT = "spec-01-pr-1"
BRANCH = "spec-01/pr-1-thing"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
# `gh pr list ... --jq length` prints a count; the fake prints the count for the queried state, or fails the merged
# query the way a transient GraphQL error does.
FAKE_GH = """#!/bin/bash
case "$*" in
  *"--state merged"*)
    if [[ -n ${FAKE_GH_FAIL:-} ]]; then echo "GraphQL: Something went wrong" >&2; exit 1; fi
    echo "$FAKE_GH_MERGED" ;;
  *"--state all"*) echo "$FAKE_GH_ALL" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
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
        env={**os.environ, **GIT_IDENTITY},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write_exe(path: Path, text: str) -> None:
    path.write_text(text, newline="\n")
    path.chmod(0o755)


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
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_exe(bin_dir / "gh", FAKE_GH)
    write_exe(bin_dir / "docker", FAKE_DOCKER)
    docker_log = tmp_path / "docker.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": docker_log.as_posix(),
    }
    return Repo(main, worktree, docker_log, env)


def run_cleanup(repo: Repo, *, merged: int, total: int, gh_fails: bool = False) -> subprocess.CompletedProcess[str]:
    env = {**repo.env, "FAKE_GH_MERGED": str(merged), "FAKE_GH_ALL": str(total)}
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
    assert repo.docker_log.read_text().splitlines()[0].startswith("ps -a")


def test_merged_pr_removes_worktree_and_branches(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=True)
    assert_removed(repo, run_cleanup(repo, merged=1, total=1))


def test_open_pr_keeps_everything(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=True)
    result = run_cleanup(repo, merged=0, total=1)
    assert_kept(repo, result, f"the PR for {BRANCH} is not merged")


def test_failed_pr_query_keeps_everything(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=True)
    result = run_cleanup(repo, merged=0, total=0, gh_fails=True)
    assert_kept(repo, result, f"could not read the PRs of {BRANCH}")


def test_no_pr_and_merged_into_main_removes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=False)
    assert_removed(repo, run_cleanup(repo, merged=0, total=0))


def test_no_pr_and_not_merged_into_main_keeps_everything(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch_ahead=True)
    result = run_cleanup(repo, merged=0, total=0)
    assert_kept(repo, result, f"{BRANCH} has no PR and is not merged into origin/main")
