"""Behaviour of `tools/ci_changes.py`, run as CI runs it: changed paths on stdin, job flags on stdout."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "ci_changes.py"
MODEL = "verify_worker_queue=true\n"
NO_MODEL = "verify_worker_queue=false\n"
MONEY, NO_MONEY = "verify_money=true\n", "verify_money=false\n"
SDK, NO_SDK = "sdk=true\n", "sdk=false\n"


def run(*args: str, stdin: str = "") -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), *args], input=stdin, capture_output=True, text=True, check=True
    )
    return result.stdout


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (
            "docs/specs/SPEC-99.md\nREADME.md\n",
            f"backend=false\nbackend_static=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}{NO_SDK}",
        ),
        (
            "backend/src/crawlerai/normalize/money.py\n",
            "backend=true\nbackend_static=true\nfrontend=false\napi_client=true\nlicenses=false\n"
            + NO_MODEL
            + MONEY
            + NO_SDK,
        ),
        (
            "backend/uv.lock\n",
            f"backend=true\nbackend_static=true\nfrontend=false\napi_client=true\nlicenses=true\n{NO_MODEL}{MONEY}{NO_SDK}",
        ),
        (
            "backend/src/crawlerai/db/queue.py\n",
            f"backend=true\nbackend_static=true\nfrontend=false\napi_client=true\nlicenses=false\n{MODEL}{NO_MONEY}{NO_SDK}",
        ),
        (
            "tools/verify/worker_queue/WorkerQueue.tla\n",
            "backend=false\nbackend_static=true\nfrontend=false\napi_client=false\nlicenses=false\n"
            + MODEL
            + NO_MONEY
            + NO_SDK,
        ),
        (
            "infra/postgres/init.sql\n",
            f"backend=true\nbackend_static=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}{NO_SDK}",
        ),
        (
            "frontend/src/App.tsx\n",
            f"backend=false\nbackend_static=false\nfrontend=true\napi_client=true\nlicenses=false\n{NO_MODEL}{NO_MONEY}{NO_SDK}",
        ),
        (
            "frontend/openapi.json\n",
            f"backend=false\nbackend_static=false\nfrontend=true\napi_client=true\nlicenses=false\n{NO_MODEL}{NO_MONEY}{SDK}",
        ),
        (
            "sdk/python/src/crawlerai_sdk/client.py\n",
            f"backend=false\nbackend_static=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}{SDK}",
        ),
        (
            "",
            f"backend=false\nbackend_static=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}{NO_SDK}",
        ),
    ],
)
def test_each_job_runs_only_when_a_changed_path_is_one_of_its_inputs(changed: str, expected: str) -> None:
    assert run(stdin=changed) == expected


def test_a_path_that_only_shares_a_name_prefix_with_a_directory_is_not_its_input() -> None:
    expected = (
        "backend=false\nbackend_static=false\nfrontend=false\napi_client=false\nlicenses=false\n"
        + NO_MODEL
        + NO_MONEY
        + NO_SDK
    )
    assert run(stdin="frontend-notes.md\nbackend_old/readme.md\n") == expected


def test_all_runs_every_job_without_reading_input() -> None:
    assert (
        run("--all")
        == f"backend=true\nbackend_static=true\nfrontend=true\napi_client=true\nlicenses=true\n{MODEL}{MONEY}{SDK}"
    )


def test_every_ci_job_runs_its_one_dev_py_command() -> None:
    """A job's checks live only in `tools/dev.py check-<job>`, so a green `dev.py check` is a green CI."""
    workflow = (TOOL.parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = re.findall(r"^  ([a-z][a-z-]*):$", workflow.split("\njobs:\n", 1)[1], flags=re.MULTILINE)
    missing = [job for job in jobs if job != "changes" and f"tools/dev.py check-{job}" not in workflow]
    assert len(jobs) > 1
    assert missing == []
