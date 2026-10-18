import os
import shutil
import subprocess
from pathlib import Path

import pytest

from crawlerai.eval.git_head import GitUnavailable, head_commit

GIT = shutil.which("git")


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_head_commit_is_the_checked_out_commit(tmp_path: Path) -> None:
    assert GIT is not None
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603
            [GIT, "-C", str(tmp_path), *args], capture_output=True, text=True, check=True, env=env
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "first")
    git("commit", "-q", "--allow-empty", "-m", "second")
    second = git("rev-parse", "HEAD")
    git("checkout", "-q", "HEAD~1")

    assert head_commit(tmp_path) == git("rev-parse", "HEAD")
    assert head_commit(tmp_path) != second


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_a_repository_without_commits_fails(tmp_path: Path) -> None:
    assert GIT is not None
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)  # noqa: S603

    with pytest.raises(GitUnavailable, match="rev-parse"):
        head_commit(tmp_path)
