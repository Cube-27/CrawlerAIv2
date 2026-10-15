"""Behaviour of `tools/orchestrator/start_agent.sh` on its NAME argument, run under bash with fake `powershell` and
`herdr` on PATH that log each call. herdr agent names are lowercase, so a bad NAME fails before the script reads
memory or opens a tab."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fake_herdr import FAKE_HERDR, fake_env, herdr_list, init_main
from scan_repo import git

START_AGENT = Path(__file__).resolve().parents[1] / "orchestrator" / "start_agent.sh"
BASH = shutil.which("bash")
# The fake `powershell` reports 100 MB free, so a valid NAME stops at the memory check without opening a tab.
FAKE_POWERSHELL = '#!/bin/bash\necho "powershell $*" >> "$FAKE_LOG"\necho 100\n'

pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="needs bash and git")


def start(cwd: Path, env: dict[str, str], name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [str(BASH), START_AGENT.as_posix(), name, "some-worktree", "a prompt"],
        cwd=cwd,
        env={**env, "HERDR_WORKSPACE_ID": "w1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def run_start_agent(tmp_path: Path, name: str) -> tuple[subprocess.CompletedProcess[str], str]:
    git(tmp_path, "init", "-q", tmp_path.as_posix())
    env = fake_env(tmp_path, {"powershell": FAKE_POWERSHELL, "herdr": FAKE_HERDR}, herdr_list([]))
    return start(tmp_path, env, name), (tmp_path / "calls.log").read_text()


@pytest.mark.parametrize("name", ["impl-uatA", "Reviewer-pr1", "impl_s05", "impl s05", "-impl", ""])
def test_bad_name_fails_before_any_herdr_or_memory_call(tmp_path: Path, name: str) -> None:
    result, calls = run_start_agent(tmp_path, name)
    assert result.returncode == 1
    assert result.stderr.startswith("ERROR agent name must be lowercase")
    assert f"'{name}'" in result.stderr
    assert calls == ""


@pytest.mark.parametrize("name", ["impl-uata", "reviewer-pr152", "impl-s05p7"])
def test_valid_name_passes_to_the_memory_check(tmp_path: Path, name: str) -> None:
    result, calls = run_start_agent(tmp_path, name)
    assert result.returncode == 1
    # Off Windows the path fallback (no `cygpath`) makes `tr` warn first; the error is the last line either way.
    assert result.stderr.endswith("ERROR low memory: 100MB free < 1500MB\n")
    assert calls.startswith("powershell ")
    assert "herdr" not in calls


OTHER_PROJECT = [(f"impl-fix{i}", rf"C:\elsewhere\Other-worktrees\fix-{i}", "working") for i in range(1, 5)]


def run_with_listing(tmp_path: Path, own_workers: int) -> subprocess.CompletedProcess[str]:
    """start_agent.sh for a worker, with enough memory, while herdr lists four workers of another project, OWN_WORKERS
    of this one and one reviewer of this one."""
    main, main_cwd, worktrees_cwd = init_main(tmp_path)
    (tmp_path / "CrawlerAIv2-worktrees" / "some-worktree").mkdir(parents=True)
    own = [(f"impl-{i}", rf"{worktrees_cwd}\w{i}", "working") for i in range(own_workers)]
    listing = herdr_list([*OTHER_PROJECT, *own, ("reviewer-pr1", main_cwd, "working")])
    env = fake_env(tmp_path, {"powershell": "#!/bin/bash\necho 5000\n", "herdr": FAKE_HERDR}, listing)
    return start(main, env, "impl-new")


def test_other_projects_workers_do_not_count_toward_the_limit(tmp_path: Path) -> None:
    result = run_with_listing(tmp_path, own_workers=3)
    assert result.returncode == 1
    # Past the worker limit, the fake herdr's empty `tab create` output is the next failure.
    assert result.stderr.endswith("ERROR tab create failed\n")
    assert "herdr tab create --workspace w1" in (tmp_path / "calls.log").read_text()


def test_this_projects_workers_count_toward_the_limit(tmp_path: Path) -> None:
    result = run_with_listing(tmp_path, own_workers=4)
    assert result.returncode == 1
    assert result.stderr.endswith("ERROR worker limit: 4 alive, max 4\n")
    assert "tab create" not in (tmp_path / "calls.log").read_text()
