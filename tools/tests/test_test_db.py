"""Behaviour of `tools/orchestrator/test_db.sh`, the shared local Postgres for DB tests, run under bash with a fake
`docker` on PATH that logs each call (and the first line of what it reads on stdin) and plays a container that is
absent, stopped or running."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fake_bin import fake_bin

TEST_DB = Path(__file__).resolve().parents[1] / "orchestrator" / "test_db.sh"
BASH = shutil.which("bash")
# FAKE_STATE: unset (no container), "false" (stopped) or "true" (running).
FAKE_DOCKER = """#!/bin/bash
line="$*"
if [[ $1 == exec && $2 == -i ]]; then read -r first || true; [[ -n $first ]] && line="$line < $first"; fi
echo "$line" >> "$FAKE_DOCKER_LOG"
case $1 in
  inspect) [[ -n ${FAKE_STATE:-} ]] || exit 1; [[ $2 == -f ]] && echo "$FAKE_STATE" ;;
esac
exit 0
"""
PSQL = "exec -i -e PGOPTIONS=-cclient_min_messages=warning crawlerai-test-pg psql -v ON_ERROR_STOP=1 -q -U postgres"
DROP = (
    "-c DROP DATABASE IF EXISTS crawlerai_test_spec_03_pr_8 WITH (FORCE)"
    " -c DROP DATABASE IF EXISTS crawlerai_test_spec_03_pr_8_private WITH (FORCE)"
)
CREATE = (
    "-c CREATE DATABASE crawlerai_test_spec_03_pr_8 OWNER app"
    " -c CREATE DATABASE crawlerai_test_spec_03_pr_8_private OWNER app"
)
READY = "exec crawlerai-test-pg pg_isready -q -h 127.0.0.1 -U postgres"
RUNNING = "inspect -f {{.State.Running}} crawlerai-test-pg"
EXPORTS = [
    "export CRAWLERAI_TEST_DATABASE_URL=postgresql+asyncpg://app:app@127.0.0.1:55432/crawlerai_test_spec_03_pr_8",
    "export CRAWLERAI_TEST_PRIVATE_DATABASE_URL="
    "postgresql+asyncpg://app:app@127.0.0.1:55432/crawlerai_test_spec_03_pr_8_private",
]

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def run(tmp_path: Path, *args: str, state: str | None = None) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    log = tmp_path / "docker.log"
    variables = {"FAKE_DOCKER_LOG": log.as_posix()}
    if state is not None:
        variables["FAKE_STATE"] = state
    env = fake_bin(tmp_path, {"docker": FAKE_DOCKER}, **variables)
    result = subprocess.run(  # noqa: S603
        [str(BASH), TEST_DB.as_posix(), *args],
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_up_without_a_container_creates_it_with_the_roles_then_the_databases(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "up", "Spec-03-pr-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == EXPORTS
    assert calls == [
        RUNNING,
        "inspect crawlerai-test-pg",
        "run -d --name crawlerai-test-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:55432:5432 postgres:16",
        READY,
        f"{PSQL} < -- Databases and roles for local development and CI (SPEC-00 §4.4, SPEC-03 §4.1).",
        f"{PSQL} {DROP} {CREATE}",
    ]


def test_up_with_a_running_container_only_recreates_the_databases(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "up", "spec-03-pr-8", state="true")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == EXPORTS
    assert calls == [RUNNING, f"{PSQL} {DROP} {CREATE}"]


def test_up_with_a_stopped_container_starts_it(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "up", "spec-03-pr-8", state="false")
    assert result.returncode == 0, result.stderr
    assert calls == [RUNNING, "inspect crawlerai-test-pg", "start crawlerai-test-pg", READY, f"{PSQL} {DROP} {CREATE}"]


def test_drop_drops_only_the_worktrees_databases(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "drop", "spec-03-pr-8", state="true")
    assert result.returncode == 0, result.stderr
    assert calls == [RUNNING, f"{PSQL} {DROP}"]


def test_drop_without_a_running_container_does_nothing(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "drop", "spec-03-pr-8")
    assert result.returncode == 0, result.stderr
    assert calls == [RUNNING]


def test_an_unknown_action_is_refused(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "start", "spec-03-pr-8")
    assert (result.returncode, result.stderr.strip(), calls) == (2, "usage: test_db.sh up|drop [NAME]", [])
