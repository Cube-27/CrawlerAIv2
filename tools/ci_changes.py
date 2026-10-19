"""Which path-gated CI jobs a pull request needs, from the files it changes (owner, 2026-10-15).

Reads changed paths, one per line (`git diff --name-only base...head`), on stdin and prints `<job>=true|false` per
job for `$GITHUB_OUTPUT`. With `--all` it prints every job as `true` and reads nothing: a push to main runs them all.

A job runs when any changed path starts with one of its inputs: the directories it checks, the files its commands
read, and the workflow itself. Jobs that are cheap (site literals, data manifest, size gates) are not gated.
"""

import argparse
import sys
from collections.abc import Iterable

WORKFLOW = ".github/workflows/ci.yml"

# The path prefixes each gated job reads. Directory prefixes end in "/".
JOB_INPUTS: dict[str, tuple[str, ...]] = {
    # Lint, types, migrations and tests of backend/; complexipy also covers ../tools; the job runs
    # infra/postgres/init.sql; `make` targets live in the Makefile.
    "backend": ("backend/", "tools/", "infra/", "Makefile", WORKFLOW),
    # The frontend checks, plus the API client freshness step, which regenerates the client from backend/ through
    # the Makefile.
    "frontend": ("frontend/", "backend/", "tools/theme_only_check.py", "Makefile", WORKFLOW),
    # The dependency licence scan reads only the lockfiles, the manifests they come from, and its own scripts.
    "licenses": (
        "backend/pyproject.toml",
        "backend/uv.lock",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "frontend/pnpm-workspace.yaml",
        "tools/license_scan.sh",
        "tools/license_policy.py",
        WORKFLOW,
    ),
    # The worker/queue model (.claude/skills/verify-worker-queue/SKILL.md): the code it models, and itself.
    "verify_worker_queue": (
        "backend/src/crawlerai/worker/loop.py",
        "backend/src/crawlerai/worker/handlers/steps.py",
        "backend/src/crawlerai/db/queue.py",
        "backend/src/crawlerai/db/jobs.py",
        "backend/src/crawlerai/scheduler/loop.py",
        "backend/src/crawlerai/services/polite.py",
        "backend/src/crawlerai/acquire/politeness.py",
        "backend/src/crawlerai/acquire/shared_browser.py",
        "tools/verify/",
        WORKFLOW,
    ),
}


def needed(changed: Iterable[str]) -> dict[str, bool]:
    """For each gated job, whether any of `changed` is one of its inputs."""
    paths = [path.strip() for path in changed if path.strip()]
    return {job: any(path.startswith(inputs) for path in paths) for job, inputs in JOB_INPUTS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="every job runs (a push to main)")
    args = parser.parse_args()
    jobs = dict.fromkeys(JOB_INPUTS, True) if args.all else needed(sys.stdin)
    for job, run in jobs.items():
        print(f"{job}={'true' if run else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
