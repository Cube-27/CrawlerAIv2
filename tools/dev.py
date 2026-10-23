"""Development commands: the API client and SDK generators, and every check CI runs, the same on Windows and Linux.

    uv run tools/dev.py <command>        (from the repo root; `uv run tools/dev.py` lists the commands)

This runs no part of the app: `docker compose up` does. Needs `uv` and `pnpm`; the backend's database steps need
Docker (`docker compose up -d postgres`). Each CI job is one `check-<job>` command here, so a green `check` is a green
CI: the workflow only checks out, installs and starts services, then runs `python3 tools/dev.py check-<job>`, with
`UV_RUN` set to run against the environment it has installed and `PSQL` to reach its Postgres service.
"""

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TOOLS = "../tools"  # from backend/, where the tool checks run
FRONTEND = ROOT / "frontend"
SDK = ROOT / "sdk"
UV_RUN = shlex.split(os.environ.get("UV_RUN") or "uv run")

# The scratch databases the backend checks recreate each run, so the dev database keeps its data: the tests run in
# parallel (`PYTEST_WORKERS`, default one per CPU), each xdist worker in its own copy of the migrated
# `crawlerai_check` (`_gw0`, ...). 127.0.0.1, not localhost: asyncpg can hang resolving localhost on Windows.
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


def tool(*argv: str) -> None:
    """A standard-library script under tools/, run by this interpreter, so it needs no installed environment."""
    run(ROOT, sys.executable, *argv)


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


# --- checks: one per CI job, named after it (`check-<job>`), in CI's order ---


def check_data_manifest() -> None:
    """C4: every file under backend/data/ is pinned in the manifest."""
    tool("tools/data_manifest_check.py")


def check_no_size_gates() -> None:
    """C11: no gate beyond the two allowed; files over 800 lines only warn."""
    tool("tools/no_size_gates.py")
    tool("tools/file_length.py")


def check_site_literals() -> None:
    """C3: no site literals outside adapters/; also lints, type-checks and tests the repo tools."""
    uv(BACKEND, "ruff", "check", TOOLS)
    uv(BACKEND, "ruff", "format", "--check", TOOLS)
    uv(BACKEND, "mypy", "--strict", TOOLS)
    uv(BACKEND, "pytest", f"{TOOLS}/tests")
    uv(BACKEND, "python", f"{TOOLS}/site_literal_scan.py", "--public")


def check_backend_static() -> None:
    """The backend's lint, format, types and import contracts, and C11: cognitive complexity of at most 15 per function
    in src, tests, migrations and tools/ ([tool.complexipy]; `--no-ignore`: an inline suppression does not exempt a
    function)."""
    uv(BACKEND, "ruff", "check")
    uv(BACKEND, "ruff", "format", "--check")
    uv(BACKEND, "mypy", "src", "tests", "migrations")
    uv(BACKEND, "lint-imports")
    uv(BACKEND, "complexipy", "--no-ignore")


def psql(sql: str) -> None:
    """Run `sql` as the postgres superuser: with `PSQL` where Postgres already runs (CI's service), else in the compose
    service."""
    argv = shlex.split(os.environ.get("PSQL") or "docker compose exec -T postgres psql -U postgres")
    run(ROOT, *argv, "-v", "ON_ERROR_STOP=1", "-q", stdin=sql)


def check_backend() -> None:
    """The migrations upgraded, downgraded and upgraded again, then the tests. `browser` tests are skipped where Google
    Chrome is not installed (`uv run patchright install chrome` once); `--durations=20` lists the slowest tests."""
    if not os.environ.get("PSQL"):
        run(ROOT, "docker", "compose", "up", "-d", "--wait", "postgres")
    env = {"CRAWLERAI_DATABASE_URL": CHECK_DATABASE_URL}
    psql("DROP DATABASE IF EXISTS crawlerai_check;\nCREATE DATABASE crawlerai_check OWNER app;\n")
    for target in ("head", "base", "head"):
        verb = "upgrade" if target == "head" else "downgrade"
        uv(BACKEND, "alembic", verb, target, env=env)
    workers = int(os.environ.get("PYTEST_WORKERS") or os.cpu_count() or 1)
    psql("".join(
        f"DROP DATABASE IF EXISTS crawlerai_check_gw{i}; "
        f"CREATE DATABASE crawlerai_check_gw{i} TEMPLATE crawlerai_check OWNER app;\n"
        for i in range(workers)
    ))  # fmt: skip
    test_env = {"CRAWLERAI_TEST_DATABASE_URL": CHECK_DATABASE_URL}
    uv(BACKEND, "pytest", "-n", str(workers), "--durations=20", env=test_env)


def check_verify_money() -> None:
    """The verify-money skill's one command (.claude/skills/verify-money/SKILL.md): the money property checks with the
    `verify` Hypothesis profile."""
    uv(BACKEND, "pytest", "tests/property/test_money_properties.py", "-q", "--hypothesis-profile=verify")


def check_verify_worker_queue(*args: str) -> None:
    """Model-check the worker/queue concurrency with TLC (.claude/skills/verify-worker-queue/SKILL.md). `args` go to
    the script: CI runs it in three shards (`--shard i/3`)."""
    tool("tools/verify/worker_queue.py", *args)


def check_frontend() -> None:
    """Visual values only in theme.css, UI only from @heroui/react (docs/rules.md); Vite+'s format check, lint and
    strict type-check in one pass; the tests; the build."""
    tool("tools/theme_only_check.py")
    run(FRONTEND, "pnpm", "check")
    run(FRONTEND, "pnpm", "test")
    run(FRONTEND, "pnpm", "build")


def check_api_client() -> None:
    """The committed API client matches one generated from the backend."""
    api_client()
    stale(
        ["frontend/openapi.json", "frontend/src/api/schema.d.ts"], "the API client (`uv run tools/dev.py api-client`)"
    )


def check_sdk() -> None:
    """The regenerated SDK files must match the committed ones; then each SDK's checks and tests."""
    sdk()
    stale(["sdk"], "the SDK (`uv run tools/dev.py sdk`)")
    run(SDK / "typescript", "pnpm", "check")
    run(SDK / "typescript", "pnpm", "test")
    python = SDK / "python"
    run(python, "uv", "sync", "--frozen", "--no-build", "--no-binary-package", "crawlerai-sdk", "--extra", "dev", "-q")
    for step in (("ruff", "check", "src", "tests"), ("mypy", "src", "tests"), ("pytest", "-q")):
        run(python, "uv", "run", "--no-sync", *step)


def check_licenses() -> None:
    """The dependency licence deny-list; writes the reports and SBOMs to license-report/ (gitignored), as CI does."""
    run(ROOT, "bash", "tools/license_scan.sh", "license-report")


def check() -> None:
    """Every CI job, in order, failing at the first error."""
    for step in (check_data_manifest, check_no_size_gates, check_site_literals, check_backend_static, check_backend,
                 check_verify_money, check_verify_worker_queue, check_frontend, check_api_client, check_sdk,
                 check_licenses):  # fmt: skip
        step()


COMMANDS: dict[str, Callable[..., None]] = {
    name.replace("_", "-"): function
    for name, function in globals().items()
    if callable(function) and (name in ("api_client", "sdk", "check") or name.startswith("check_"))
}
# The one command that passes its arguments on, to its script.
TAKES_ARGS = "check-verify-worker-queue"


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in COMMANDS or (argv[1:] and argv[0] != TAKES_ARGS):
        sys.exit("usage: uv run tools/dev.py <command>\n" + "\n".join(f"  {name}" for name in COMMANDS))
    COMMANDS[argv[0]](*argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
