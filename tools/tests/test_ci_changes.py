"""Behaviour of `tools/ci_changes.py`, run as CI runs it: changed paths on stdin, job flags on stdout."""

import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "ci_changes.py"
MODEL = "verify_worker_queue=true\n"
NO_MODEL = "verify_worker_queue=false\n"
MONEY, NO_MONEY = "verify_money=true\n", "verify_money=false\n"


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
            f"backend=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}",
        ),
        (
            "backend/src/crawlerai/normalize/money.py\n",
            "backend=true\nfrontend=false\napi_client=true\nlicenses=false\n" + NO_MODEL + MONEY,
        ),
        ("backend/uv.lock\n", f"backend=true\nfrontend=false\napi_client=true\nlicenses=true\n{NO_MODEL}{MONEY}"),
        (
            "backend/src/crawlerai/db/queue.py\n",
            f"backend=true\nfrontend=false\napi_client=true\nlicenses=false\n{MODEL}{NO_MONEY}",
        ),
        (
            "tools/verify/worker_queue/WorkerQueue.tla\n",
            "backend=true\nfrontend=false\napi_client=false\nlicenses=false\n" + MODEL + NO_MONEY,
        ),
        (
            "frontend/src/App.tsx\n",
            f"backend=false\nfrontend=true\napi_client=true\nlicenses=false\n{NO_MODEL}{NO_MONEY}",
        ),
        ("", f"backend=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}"),
    ],
)
def test_each_job_runs_only_when_a_changed_path_is_one_of_its_inputs(changed: str, expected: str) -> None:
    assert run(stdin=changed) == expected


def test_a_path_that_only_shares_a_name_prefix_with_a_directory_is_not_its_input() -> None:
    expected = f"backend=false\nfrontend=false\napi_client=false\nlicenses=false\n{NO_MODEL}{NO_MONEY}"
    assert run(stdin="frontend-notes.md\nbackend_old/readme.md\n") == expected


def test_all_runs_every_job_without_reading_input() -> None:
    assert run("--all") == f"backend=true\nfrontend=true\napi_client=true\nlicenses=true\n{MODEL}{MONEY}"
