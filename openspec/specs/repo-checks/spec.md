# Repository Checks Specification

## Purpose

The mechanical checks that enforce the generalization contract (C1–C13, in [project.md](../../project.md)) and the
supply-chain rules on every change: the CI jobs in `.github/workflows/ci.yml`, their path gating, the local
`make check` mirror and the pre-commit hooks. It covers lint, types and import contracts, C11's two size checks and
nothing more, the site-literal and hidden-host scans, the data manifest check, the license deny-list and SBOMs, the
decision-ID check and the theme-only check. The protected evaluation job's gate is in
[evaluation](../evaluation/spec.md).
Design rationale: [ARCHITECTURE §2](../../design/generalization.md), [§18, §19](../../design/operations.md),
[Appendix A #33](../../design/owner-decisions.md). History:
[SPEC-00](../../changes/archive/2026-10-12-spec-00-project-setup/SPEC-00-project-setup.md), its
[decisions](../../changes/archive/2026-10-12-spec-00-project-setup/decisions.md) and the cross-cutting
[decisions log](../../decisions/log.md).

## Requirements

### Requirement: Required CI jobs
CI SHALL run, on every pull request and push to `main`, the jobs `backend`, `frontend`, `site-literals`,
`data-manifest`, `licenses` and `no-size-gates`, and every job SHALL pass before merge. The `changes` job
(`tools/ci_changes.py`) gates `backend`, `frontend` and `licenses` by the paths a PR changes (a job runs when any
changed path starts with one of its inputs; a skipped job counts as passed); a push to `main` runs every job. The
cheap jobs are never gated.
Refs: SPEC-00 §4.6, D-0970.

#### Scenario: Docs-only PR
- **WHEN** a PR changes only files under `docs/`
- **THEN** `backend`, `frontend` and `licenses` are skipped and `site-literals`, `data-manifest` and `no-size-gates` run

#### Scenario: Lockfile change
- **WHEN** a PR changes `frontend/pnpm-lock.yaml`
- **THEN** the `licenses` and `frontend` jobs run

### Requirement: Backend job
The `backend` job SHALL install dependencies from `uv.lock` wheels only (`uv sync --frozen --no-build
--no-binary-package crawlerai --no-editable`) and then run, without re-syncing: `ruff check` (with `S102`/`S307`
against `exec`/`eval`), `ruff format --check`, `mypy src tests migrations` (strict, pydantic plugin),
`lint-imports`, `complexipy --no-ignore`, the Alembic upgrade/downgrade/upgrade round trip on a service Postgres
initialised by `infra/postgres/init.sql`, and `pytest -n 4` with per-worker main and private test databases.
Refs: SPEC-00 §4.2, §4.6, D-0058, D-0141, D-0970.

#### Scenario: Type error
- **WHEN** a PR adds a mypy error under `backend/tests/`
- **THEN** the `backend` job fails

### Requirement: Import contracts
`backend/.importlinter` SHALL hold the C8 contracts checked by `lint-imports`: `normalize-independence` (one module
per field type), `normalize-internals`, `normalize-libs` (only `crawlerai.normalize` imports `babel`,
`price_parser`, `dateparser`), `adapters-isolated` (only `acquire` and `collect` import `adapters`), `layers`, and the
release-executor isolation contracts. A new field-type module is added to the contracts in the PR that creates it.
INV-08 itself is owned by [normalization](../normalization/spec.md).
Refs: C8, SPEC-00 §5, D-0055, D-0056, D-0057.

#### Scenario: Collector imports Babel
- **WHEN** `crawlerai.collect` imports `babel`
- **THEN** `lint-imports` fails the `backend` job

### Requirement: Frontend job
The `frontend` job SHALL run `tools/theme_only_check.py`, `pnpm install --frozen-lockfile`, `pnpm check` (Vite+:
Oxfmt format check, Oxlint including the cognitive-complexity rule, tsgo type-check), `pnpm test`, `pnpm build`, and
the API client freshness check: `make api-client` followed by `git diff --exit-code` on `frontend/openapi.json` and
`frontend/src/api/schema.d.ts`, failing with "API client out of date".
Refs: SPEC-00 §4.3, §4.5, D-0071, D-0226.

#### Scenario: Stale client
- **WHEN** a backend change alters the OpenAPI document and the generated files are not committed
- **THEN** the `frontend` job fails with "API client out of date"

### Requirement: Theme-only check
`tools/theme_only_check.py` SHALL fail when a tracked file under `frontend/src/` (except `app/theme.css`, tests and
generated files) adds a CSS file other than the entry CSS, a color literal, a Tailwind arbitrary value, a Tailwind
palette color utility, a `style=` prop, or an import of a package outside the allow-list (`@heroui/react`, its one
icon set, and the non-UI runtime packages). It prints `path:line: rule: text` per finding.
Refs: DESIGN.md Theming and Stack, D-0356, D-0358.

#### Scenario: Hex color in a component
- **WHEN** a component under `frontend/src/screens/` contains `#ff0000`
- **THEN** the check reports it and exits 1

### Requirement: No site literals (INV-03, INV-09)
No hostname or URL literal SHALL appear outside `backend/src/crawlerai/adapters/`, docs, lockfiles and the justified
allowlist, and no test file, test name or fixture SHALL contain a hostname or retailer name. `tools/site_literal_scan.py
--public` flags URL hosts and dotted tokens whose last label is in the pinned IANA TLD list; path exemptions are
`adapters/`, `docs/`, `.github/`, `*.lock`, `pnpm-lock.yaml`, `package.json`, `pyproject.toml`, `LICENSE`, `NOTICE`
and `backend/data/manifest.json`; tests are not exempt. Non-host tokens are recognised by class only (code outside
string literals and comments, tracked file extensions, module paths, schema `table.column` references, schema.org
paths from tracked schema documents, single-label and non-global IP URL hosts). `tools/site_literal_allowlist.txt`
holds only standards, tooling and RFC 2606/6761 names, each with a `# justification` (else exit 2); adding a
commercial site is a C3 violation. Enforced by: `tools/site_literal_scan.py --public` in CI (`site-literals`) and
pre-commit (`--staged`, index content); the INV-03 scan covers `tests/`; status: active.
Refs: C3, C9, SPEC-00 §4.7, D-0059, D-0060, D-0062, D-0107, D-0111, D-0142, D-0846.

#### Scenario: Planted host
- **WHEN** a PR adds `shop.example-retailer.com` to `backend/src/crawlerai/collect/`
- **THEN** the scan prints `path:line: host` and the `site-literals` job fails

#### Scenario: Reserved test host
- **WHEN** a test fixture uses `item.example.test`
- **THEN** the scan passes it through the allowlist entry `.test`

### Requirement: Hidden-host scan (INV-04)
No hidden or fresh host SHALL appear anywhere in the repo. `site_literal_scan.py --hidden-hosts-from-env HIDDEN_HOSTS`
scans every tracked file with no exemption or allowlist, matches a host and its subdomains case-insensitively, and
prints only `path:line` (`path:0` for a host in a path, with the host replaced by `[hidden]`), never a host. An unset
or empty list passes with `hidden-hosts: pass, no host list configured`. It runs only in the protected job, not in
`make check`. Enforced by: the protected scan in `eval-protected.yml`; status: active, the host list exists from
milestone M.
Refs: C1, C3, SPEC-00 §4.6, §4.7, D-0081, D-0082, D-0083, D-0109.

#### Scenario: Seeded hidden host
- **WHEN** `HIDDEN_HOSTS` holds `seeded.test` and a scratch file names `a.seeded.test`
- **THEN** the job log shows that file's `path:line` and never the host

### Requirement: Pinned external data (INV-05)
Every external data file under `backend/data/` SHALL come from a pinned external source listed in
`backend/data/manifest.json` with `path`, `url`, `version`, `sha256`, `license` and `justification`, and its bytes
SHALL match the hash; an entry marked `"fetched": true` may be absent but must match when present. The dev-fitted
files `source_precedence.yaml`, `calibration.json` and `drift_margins.json` are not pinned and SHALL instead carry the
top-level stamp `source_split: dev`; pinning one, or a missing or non-dev stamp, fails. Enforced by:
`tools/data_manifest_check.py` (CI `data-manifest`); status: active. (INVARIANTS.md names two dev-fitted files;
`drift_margins.json` was added by D-0576/D-0913.)
Refs: C4, SPEC-00 §4.1, D-0063, D-0444, D-0576, D-0756.

#### Scenario: Unlisted vocabulary
- **WHEN** a PR adds `backend/data/words.txt` without a manifest entry
- **THEN** the `data-manifest` job fails naming the file

### Requirement: License deny-list and SBOMs
`tools/license_scan.sh` SHALL collect `pip-licenses --from=all` (all dependency groups, transitive, without the
project itself) and `pnpm licenses list`, write CycloneDX SBOMs for both ecosystems, and fail through
`tools/license_policy.py` when a declared license is AGPL, GPL, SSPL or non-commercial (the SPEC-00 §4.6 SPDX list,
plus the seven PyPI trove classifiers for AGPL/GPL). Matching SHALL be by SPDX expression and whole identifier,
never substring (`OR` passes on any clean branch, `AND` needs all), so LGPL passes; `UNKNOWN` is reported but passes.
The `licenses` job uploads the reports and SBOMs as the `license-report` artifact.
Refs: §18, SPEC-00 §4.6, D-0074, D-0075, D-0076, D-0077, D-0078, D-0080.

#### Scenario: AGPL dependency
- **WHEN** a dependency declaring `AGPL-3.0-only` is added to `uv.lock`
- **THEN** the `licenses` job fails naming the package

### Requirement: C11 size checks and no others (INV-18)
CI and hooks SHALL contain no size, complexity or coverage-threshold gate other than C11's two: cognitive complexity
of at most 15 per function, a failing check (`complexipy --no-ignore` over backend `src`, `tests`, `migrations` and
`tools/`, limit only in `[tool.complexipy]`; the `crawlerai/cognitive-complexity` Oxlint rule in `vp check`), and
`tools/file_length.py`, which warns (a workflow annotation in CI) for tracked source files over 800 lines and always
exits 0. No ratchets. `tools/no_size_gates.py` scans workflows, `.pre-commit-config.yaml`, `Makefile` and the tool
configs they run for line-count tools, `max-*`/mccabe/`PLR09` limits, Oxlint `pedantic`/`style`/`restriction`
categories, coverage thresholds and complexity settings other than 15. Enforced by: `tools/no_size_gates.py` (CI
`no-size-gates`); status: active.
Refs: C11, Appendix A #33, SPEC-00 §4.6, D-0084, D-0228, D-0330, D-0331, D-0332.

#### Scenario: Coverage threshold added
- **WHEN** a PR adds `--cov-fail-under=80` to the pytest options
- **THEN** `no-size-gates` fails with `path:line: line`

#### Scenario: Long file
- **WHEN** a source file grows to 850 lines
- **THEN** `file_length.py` prints a warning and CI stays green

### Requirement: Decision-ID check
`tools/decision_ids.py` SHALL fail when one `### D-NNNN` heading heads more than one entry across `docs/DECISIONS.md`
and `docs/decisions/**/*.md`, printing every `path:line` of each duplicate. It runs in the `site-literals` job, with
ruff, `mypy --strict` and pytest over `tools/`.
Refs: D-0820, D-0823.

#### Scenario: Reused ID
- **WHEN** two spec decision files both contain `### D-0999`
- **THEN** the `site-literals` job fails listing both locations

### Requirement: Local make check and hooks
`make check` SHALL run every CI check locally in CI order, stopping at the first failure, with the migration round
trip and tests on scratch databases (`crawlerai_check`, `crawlerai_private_check`) recreated each run; it leaves out
the protected hidden-host scan. `.pre-commit-config.yaml` SHALL run fast checks on staged files only: merge-conflict,
end-of-file and whitespace fixers, ruff check and format, complexipy, the site-literal scan (`--public --staged`),
the theme-only check and `vp check --fix`, using the versions pinned in the lockfiles. No hook counts lines.
Refs: SPEC-00 §4.4, §4.8, D-0106, D-0108, D-0109, D-0227.

#### Scenario: Staged host
- **WHEN** a commit stages a file containing a non-allowlisted host
- **THEN** the `site-literals` hook fails the commit
