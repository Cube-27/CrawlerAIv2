"""Behaviour of `tools/orchestrator/watch_agents.sh` when herdr lists agents of two projects, run under bash with fake
`herdr`, `gh` and `powershell` on PATH: only this project's agents (cwd in the main checkout or its worktrees)
wake it."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fake_herdr import FAKE_HERDR, fake_env, herdr_list, init_main

WATCH = Path(__file__).resolve().parents[1] / "orchestrator" / "watch_agents.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="needs bash and git")


def test_another_projects_settled_agent_does_not_wake_the_watcher(tmp_path: Path) -> None:
    main, _, worktrees_cwd = init_main(tmp_path)
    # Sorted by name, the other project's idle agent comes first, so a watcher that saw it would report it.
    listing = herdr_list(
        [
            ("impl-a", r"C:\elsewhere\Other-worktrees\fix-3", "idle"),
            ("impl-b", rf"{worktrees_cwd}\spec-01-pr-1", "idle"),
        ]
    )
    executables = {"herdr": FAKE_HERDR, "gh": "#!/bin/bash\nexit 0\n", "powershell": "#!/bin/bash\necho 5000\n"}
    result = subprocess.run(  # noqa: S603
        [str(BASH), WATCH.as_posix()],
        cwd=main,
        env={**fake_env(tmp_path, executables, listing), "INTERVAL": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert (result.returncode, result.stdout) == (0, "SETTLED impl-b idle\n")
