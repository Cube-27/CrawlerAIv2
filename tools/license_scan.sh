#!/usr/bin/env bash
# Dependency license deny-list and SBOMs (CI job 3).
#
# Usage: tools/license_scan.sh [OUT_DIR]   (default: license-report/ at the repo root)
#
# Writes to OUT_DIR the license reports and a CycloneDX SBOM for the backend (the synced uv environment, every
# dependency group, transitive dependencies included) and the frontend (pnpm, dev dependencies included), then
# fails if any dependency's license is denied (tools/license_policy.py). Expects `uv` and `pnpm` on PATH and the
# frontend dependencies installed (`pnpm install --frozen-lockfile`).
set -euo pipefail

# `pwd -W` gives Git Bash on Windows a path that native tools accept; elsewhere it fails and `pwd` is used.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && { pwd -W 2>/dev/null || pwd; })"
out="${1:-$root/license-report}"
mkdir -p "$out"
out="$(cd "$out" && { pwd -W 2>/dev/null || pwd; })"

cd "$root/frontend"
pnpm licenses list --json >"$out/node-licenses.json"
pnpm sbom --sbom-format cyclonedx >"$out/node-sbom.cdx.json"

cd "$root/backend"
# An environment of its own: syncing the project's `.venv` would remove the files of a running worker or scheduler,
# which Windows refuses while they are in use, and would uninstall the project from the developer's environment.
venv="$root/backend/.venv-licenses"
export UV_PROJECT_ENVIRONMENT="$venv"
# Dependencies only, so nothing is built (SonarCloud S8541) and the project itself (AGPL-3.0, LICENSE) is not
# installed: the deny-list applies to what it depends on.
uv sync --frozen --all-groups --all-extras --no-build --no-install-project
uv run --no-sync --no-build pip-licenses --from=all --format=json --with-system >"$out/python-licenses.json"
uv run --no-sync --no-build cyclonedx-py environment --pyproject pyproject.toml --output-reproducible "$venv" \
  >"$out/python-sbom.cdx.json"
uv run --no-sync --no-build python "$root/tools/license_policy.py" \
  --python "$out/python-licenses.json" --node "$out/node-licenses.json"
