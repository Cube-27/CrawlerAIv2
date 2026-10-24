"""Which path-gated CI jobs a pull request needs, from the files it changes (owner, 2026-10-15).

Reads changed paths, one per line (`git diff --name-only base...head`), on stdin and prints `<job>=true|false` per
job for `$GITHUB_OUTPUT`. With `--all` it prints every job as `true` and reads nothing: a push to main runs them all.

A job runs when any changed path starts with one of its inputs: the directories it checks, the files its commands
read, the workflow itself and tools/dev.py, which holds every job's steps (`dev.py check-<job>`). Jobs that are cheap
(site literals, data manifest, size gates) are not gated.
"""

import argparse
import sys
from collections.abc import Iterable

WORKFLOW = ".github/workflows/ci.yml"
DEV = "tools/dev.py"
BACKEND = "backend/"

# The path prefixes each gated job reads. Directory prefixes end in "/".
JOB_INPUTS: dict[str, tuple[str, ...]] = {
    # Migrations and tests of backend/; the job runs infra/postgres/init.sql.
    "backend": (BACKEND, "infra/", DEV, WORKFLOW),
    # Lint, types, import contracts and complexity of backend/; complexipy also covers ../tools.
    "backend_static": (BACKEND, "tools/", WORKFLOW),
    # The frontend checks.
    "frontend": ("frontend/", "tools/theme_only_check.py", DEV, WORKFLOW),
    # The API client freshness check: regenerates the client from backend/ with the frontend's generator.
    "api_client": ("frontend/", BACKEND, DEV, WORKFLOW),
    # The dependency licence scan reads only the lockfiles, the manifests they come from, and its own scripts.
    "licenses": (
        "backend/pyproject.toml",
        "backend/uv.lock",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "frontend/pnpm-workspace.yaml",
        "tools/license_scan.sh",
        "tools/license_policy.py",
        DEV,
        WORKFLOW,
    ),
    # The worker/queue model (.claude/skills/verify-worker-queue/SKILL.md): the code it models, and itself.
    "verify_worker_queue": (
        "backend/src/snowcrawl/worker/loop.py",
        "backend/src/snowcrawl/worker/handlers/",
        "backend/src/snowcrawl/db/queue.py",
        "backend/src/snowcrawl/db/jobs.py",
        "backend/src/snowcrawl/db/usage.py",
        "backend/src/snowcrawl/crawl/frontier.py",
        "backend/src/snowcrawl/scheduler/loop.py",
        "backend/src/snowcrawl/services/polite.py",
        "backend/src/snowcrawl/acquire/politeness.py",
        "backend/src/snowcrawl/acquire/shared_browser.py",
        "tools/verify/",
        DEV,
        WORKFLOW,
    ),
    # The verify-money skill's one command (.claude/skills/verify-money/SKILL.md): the money code it runs, its test
    # file and profile, the libraries whose data it reads, and the skill itself.
    "verify_money": (
        "backend/src/snowcrawl/normalize/money.py",
        "backend/src/snowcrawl/normalize/numbers.py",
        "backend/src/snowcrawl/normalize/units.py",
        "backend/src/snowcrawl/normalize/base.py",
        "backend/src/snowcrawl/llm/grounding.py",
        "backend/tests/property/test_money_properties.py",
        "backend/tests/conftest.py",
        "backend/pyproject.toml",
        "backend/uv.lock",
        ".claude/skills/verify-money/",
        DEV,
        WORKFLOW,
    ),
    # The SDKs: regenerated from the API document and checked.
    "sdk": ("sdk/", "frontend/openapi.json", DEV, WORKFLOW),
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
