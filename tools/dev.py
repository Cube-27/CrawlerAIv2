"""Development commands: the API client and SDK generators, and every check CI runs, the same on Windows and Linux.

    uv run tools/dev.py <command>        (from the repo root; `uv run tools/dev.py` lists the commands)

This runs no part of the app: `docker compose up` does. Needs `uv` and `pnpm`; the backend's database steps need
Docker (`docker compose up -d postgres`). CI sets `UV_RUN` to run against an environment it has already installed.
"""

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
SDK = ROOT / "sdk"
UV_RUN = shlex.split(os.environ.get("UV_RUN") or "uv run")

# The scratch databases the backend checks recreate each run, so the dev database keeps its data: the tests run in
# parallel (`-n auto`), each xdist worker in its own copy of the migrated `crawlerai_check` (`_gw0`, ...).
# 127.0.0.1, not localhost: asyncpg can hang resolving localhost on Windows.
CHECK_DATABASE_URL = "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai_check"


def run(cwd: Path, *argv: str, env: dict[str, str] | None = None, stdin: str | None = None) -> None:
    """Run a command in `cwd`, echoing it; the first failure ends the whole run."""
    print(f"+ ({cwd.relative_to(ROOT)}) {shlex.join(argv)}", flush=True)
    done = subprocess.run(  # noqa: S603
        argv, cwd=cwd, env={**os.environ, **(env or {})}, input=stdin, text=stdin is not None, check=False
    )
    if done.returncode != 0:
        sys.exit(done.returncode)


def capture(cwd: Path, *argv: str) -> str:
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
    return done.stdout


def uv(cwd: Path, *argv: str, env: dict[str, str] | None = None) -> None:
    run(cwd, *UV_RUN, *argv, env=env)


# --- generators ---


def api_client() -> None:
    """Regenerate frontend/openapi.json and the TS client types from the backend. CI fails on a diff."""
    argv = [*UV_RUN, "crawlerai", "openapi"]
    done = subprocess.run(argv, cwd=BACKEND, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        sys.exit(done.stderr)
    (FRONTEND / "openapi.json").write_text(done.stdout, encoding="utf-8", newline="\n")
    run(FRONTEND, "pnpm", "gen:api")


def sdk() -> None:
    """Regenerate the Python and TypeScript SDKs' generated files from frontend/openapi.json (after `api-client`)."""
    run(SDK / "python", "bash", "generate.sh")
    run(SDK / "typescript", "pnpm", "install", "--frozen-lockfile")
    run(SDK / "typescript", "pnpm", "gen")


def stale(paths: list[str], hint: str) -> None:
    """Fail when the regenerated `paths` differ from the committed ones, naming the command that regenerates them."""
    # `git status`, not `git diff`: a committed file the generators recreate shows only as untracked.
    changed = capture(ROOT, "git", "status", "--porcelain", "--", *paths)
    if changed.strip():
        print(changed)
        sys.exit(f"{hint} is out of date: run it and commit the result.")


def verify_worker_queue() -> None:
    """Model-check the worker/queue concurrency with TLC (.claude/skills/verify-worker-queue/SKILL.md)."""
    run(ROOT, sys.executable, "tools/verify/worker_queue.py")


# --- checks, in CI's order per job ---


def check_data() -> None:
    uv(BACKEND, "python", "../tools/data_manifest_check.py")


def check_size_gates() -> None:
    """C11: no gate beyond the two allowed; files over 800 lines only warn."""
    uv(BACKEND, "python", "../tools/no_size_gates.py")
    uv(BACKEND, "python", "../tools/file_length.py")


def check_complexity() -> None:
    """C11: cognitive complexity of at most 15 per function in the backend and tools/ ([tool.complexipy])."""
    uv(BACKEND, "complexipy", "--no-ignore")


def check_theme() -> None:
    """Visual values only in frontend/src/app/theme.css, UI only from @heroui/react (docs/rules.md)."""
    uv(BACKEND, "python", "../tools/theme_only_check.py")


def check_tools() -> None:
    uv(BACKEND, "ruff", "check", "../tools")
    uv(BACKEND, "ruff", "format", "--check", "../tools")
    uv(BACKEND, "mypy", "--strict", "../tools")
    uv(BACKEND, "pytest", "../tools/tests")
    uv(BACKEND, "python", "../tools/site_literal_scan.py", "--public")


def psql(sql: str) -> None:
    run(ROOT, "docker", "compose", "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "postgres",
        stdin=sql)  # fmt: skip


def check_backend() -> None:
    """The same steps and order as CI's backend-static and backend jobs. `browser` tests are skipped where Google
    Chrome is not installed (`uv run patchright install chrome` once)."""
    run(ROOT, "docker", "compose", "up", "-d", "--wait", "postgres")
    uv(BACKEND, "ruff", "check")
    uv(BACKEND, "ruff", "format", "--check")
    uv(BACKEND, "mypy", "src", "tests", "migrations")
    uv(BACKEND, "lint-imports")
    env = {"CRAWLERAI_DATABASE_URL": CHECK_DATABASE_URL}
    psql("DROP DATABASE IF EXISTS crawlerai_check;\nCREATE DATABASE crawlerai_check OWNER app;\n")
    for target in ("head", "base", "head"):
        verb = "upgrade" if target == "head" else "downgrade"
        uv(BACKEND, "alembic", verb, target, env=env)
    workers = int(os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS") or os.cpu_count() or 1)
    psql("".join(
        f"DROP DATABASE IF EXISTS crawlerai_check_gw{i}; "
        f"CREATE DATABASE crawlerai_check_gw{i} TEMPLATE crawlerai_check OWNER app;\n"
        for i in range(workers)
    ))  # fmt: skip
    uv(BACKEND, "pytest", "-n", "auto", env={"CRAWLERAI_TEST_DATABASE_URL": CHECK_DATABASE_URL})


def check_frontend() -> None:
    run(FRONTEND, "pnpm", "check")
    run(FRONTEND, "pnpm", "test")
    run(FRONTEND, "pnpm", "build")


def check_api_client() -> None:
    api_client()
    run(ROOT, "git", "diff", "--exit-code", "--", "frontend/openapi.json", "frontend/src/api/schema.d.ts")


def check_sdk() -> None:
    """CI's sdk job: the regenerated files must match the committed ones; then each SDK's checks and tests."""
    sdk()
    stale(["sdk"], "the SDK (`uv run tools/dev.py sdk`)")
    run(SDK / "typescript", "pnpm", "check")
    run(SDK / "typescript", "pnpm", "test")
    python = SDK / "python"
    run(python, "uv", "sync", "--frozen", "--no-build", "--no-binary-package", "crawlerai-sdk", "--extra", "dev", "-q")
    for tool in (("ruff", "check", "src", "tests"), ("mypy", "src", "tests"), ("pytest", "-q")):
        run(python, "uv", "run", "--no-sync", *tool)


def check_licenses() -> None:
    """Writes the reports and SBOMs to license-report/ (gitignored), as CI does."""
    run(ROOT, "bash", "tools/license_scan.sh", "license-report")


def check() -> None:
    """Everything CI runs, in the same order per job, failing at the first error."""
    for step in (check_data, check_size_gates, check_complexity, check_theme, check_tools, check_backend,
                 check_frontend, check_api_client, check_sdk, check_licenses):  # fmt: skip
        step()


COMMANDS: dict[str, Callable[[], None]] = {
    name.replace("_", "-"): function
    for name, function in globals().items()
    if callable(function)
    and (name in ("api_client", "sdk", "verify_worker_queue", "check") or name.startswith("check_"))
}


def main(argv: list[str]) -> None:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        sys.exit("usage: uv run tools/dev.py <command>\n" + "\n".join(f"  {name}" for name in COMMANDS))
    COMMANDS[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
