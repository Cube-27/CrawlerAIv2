# SPEC-00 decisions

Decisions for [SPEC-00 — Project setup and engineering foundations](../specs/SPEC-00-project-setup.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0046 — CLI uses stdlib `argparse`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: `crawlerai` is built on `argparse`, not Typer or Click.
- Alternatives: Typer (MIT), Click (BSD).
- Why: There is one flag today. No dependency until subcommands need one.
- Reversible: yes

### D-0047 — Settings shape
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: `database_url` and `object_store` are required. The two database URLs are `SecretStr`. Object stores must match `fs:///<abs>` or `s3://<bucket>[/<prefix>]`. `eval_private_*` are unset by default, `log_redact_urls` defaults to false, and `role` is optional. An empty value counts as unset (`env_ignore_empty`). No `.env` loading yet.
- Alternatives: a required `role`; plain `str` URLs; empty string as a value.
- Why: The most conservative reading of SPEC-00 §4.4. Unset CI secrets arrive as `""`.
- Reversible: yes

### D-0048 — Build backend hatchling, Python `>=3.12,<3.13`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: hatchling builds the package, and Python is pinned to `>=3.12,<3.13`.
- Alternatives: `uv_build` or setuptools; `>=3.12`.
- Why: ARCHITECTURE §19 fixes Python 3.12, and hatchling is MIT-licensed.
- Reversible: yes

### D-0049 — `NOTICE` unchanged
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: No attributions are added. Nothing third-party is vendored, and dependency attribution comes from the SBOM in SPEC-00 PR 7.
- Alternatives: list the dependencies in `NOTICE` now.
- Why: Installed dependencies are not bundled.
- Reversible: yes

### D-0050 — CI backend job lands in SPEC-00 PR 1
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: `ci.yml` runs `uv sync --frozen`, ruff (lint and format check), `mypy src tests` and `pytest`. Actions are pinned to commit SHAs and uv to 0.11.28. Later SPEC-00 rows add `lint-imports`, the replay split, alembic and the other jobs.
- Alternatives: wait for later SPEC-00 rows to add CI.
- Why: The owner asked for the first PR to carry the setup, so CI gates every later row.
- Reversible: yes

### D-0051 — HeroUI is MIT-licensed, not Apache-2.0
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
- Decision: `@heroui/react` and `@heroui/styles` 3.2.6 declare MIT. SPEC-00 §4.3 says Apache-2.0; both are permissive, so nothing changes. The spec table is corrected in SPEC-00 PR 10.
- Alternatives: none.
- Why: Verified from the published packages.
- Reversible: yes

### D-0052 — Frontend versions pinned exactly
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: superseded by D-0226
- Decision: Exact pins: HeroUI 3.2.6, React 19.3.0, Vite 8.3.4, Tailwind 4.3.3, react-router 8.4.0, Vitest 5.0.3, TypeScript 5.9.3, ESLint 9.39.5. TypeScript stays on 5.x and ESLint on 9 for the spec's toolchain (typescript-eslint, jsx-a11y peers). Bump ESLint once jsx-a11y supports 10.
- Alternatives: `^` ranges; ESLint 10 without jsx-a11y.
- Why: Reproducible installs and the SPEC-00 §4.3 tool list.
- Reversible: yes

### D-0053 — Node 24 in CI; pnpm pinned by `packageManager`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
- Decision: CI uses Node 24 LTS; `packageManager: pnpm@11.22.0`; `engines.node >= 22`.
- Alternatives: Node 26.
- Why: The LTS line, and pnpm pinned in one place.
- Reversible: yes

### D-0054 — Theme: only an explicit choice is persisted
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
- Decision: `localStorage["crawlerai.theme"]` is written only when the viewer toggles, so a viewer who never chose follows `prefers-color-scheme`. Applied before paint. The control is a HeroUI `Switch`, "Dark theme".
- Alternatives: persist the resolved theme on first load.
- Why: The most conservative reading of SPEC-00 §4.9.
- Reversible: yes

### D-0055 — Normalize independence contract uses `crawlerai.normalize.*`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: The independence contract matches every module under `crawlerai.normalize` with a wildcard, not SPEC-00 §5's concrete list.
- Alternatives: the concrete list, extended as modules land.
- Why: import-linter errors on modules that don't exist yet. The wildcard covers new type modules automatically. A shared dispatcher inside `normalize` would need the contract narrowed in its PR.
- Reversible: yes

### D-0056 — Layers: `acquire : adapters`, all other siblings independent
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: SPEC-00 §5's `|` siblings stay independent, except acquire and adapters (`:`), because the adapters-isolated contract lets acquire import adapters. `normalize | schemas` forbids normalize→schemas; SPEC-04 relaxes it with a logged decision if needed.
- Alternatives: `|` everywhere; `:` everywhere.
- Why: The strictest reading that is consistent with the adapters contract.
- Reversible: yes

### D-0057 — Forbidden-import contracts check direct imports only
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: The normalize-libs and adapters-isolated contracts set `allow_indirect_imports = True`.
- Alternatives: check indirect chains.
- Why: With indirect checking, collect couldn't call a normalizer that uses Babel. The layers contract still covers the chains.
- Reversible: yes

### D-0058 — CI tool steps run with `uv run --no-sync --no-build`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: `lint-imports` runs without syncing or building, because `uv sync --frozen` earlier in the job already installed the environment.
- Alternatives: `uv run --frozen` (SonarCloud S8541); `--frozen --no-build` (fails on the editable package).
- Why: Nothing needs to be resolved or built at that step.
- Reversible: yes

### D-0059 — Site-literal scan excludes non-host dotted tokens by class
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: In Python (via `tokenize`, including `*.py.*` templates) and JS/TS files, only string literals and comments are scanned. A two-label token whose last label is a tracked file's extension is a file name. A token equal to a tracked Python module path is a module name. URL hosts are always checked.
- Alternatives: exclude TLDs that are also file extensions (drops `.ai`, `.me`, `.br`); an inline ignore pragma.
- Why: The spec's bare regex gave 95 false findings (file names, attribute access). Each rule handles a class using repo data, with no lists (C4).
- Reversible: yes

### D-0060 — Allowlist matching and justification
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: Entries starting with `.` cover the name and its subdomains; plain entries match exactly. Every entry needs a `# justification`, or the scan exits 2. RFC 2606 `.example` is included.
- Alternatives: suffix-match every entry.
- Why: The most conservative reading that still lets fixtures use any RFC 2606 subdomain.
- Reversible: yes

### D-0061 — `ghcr.io` allowlisted as a tooling host
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: GitHub's container registry is on the allowlist, like `pypi.org` and `registry.npmjs.org`.
- Alternatives: leave it for SPEC-00 PR 2 to add.
- Why: PR 2 pins a tool image from it.
- Reversible: yes

### D-0062 — Single-label URL hosts and non-global IPs are not findings
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: `localhost`, compose service names and non-global IP literals in URLs are not flagged.
- Alternatives: flag every URL host not on the allowlist.
- Why: They can't name a public site, and compose and `.env` files need them.
- Reversible: yes

### D-0063 — Data manifest schema
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: `{"entries": [{path, url, version, sha256, license, justification, …}]}`, `path` relative to `backend/data/`. A listed file that is missing fails the check. The IANA TLD list is committed (about 10 KB).
- Alternatives: fetch the TLD list in CI (needs the network, non-deterministic).
- Why: The most conservative reading of SPEC-00 §4.1. SPEC-04 PR 7 can extend it for fetched snapshots.
- Reversible: yes

### D-0064 — Tool tests live in `tools/tests/`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: They run through the backend uv environment; `tools/ruff.toml` extends the backend config.
- Alternatives: put them under `backend/tests/`.
- Why: The tools run as CI runs them (subprocess) and need no package of their own.
- Reversible: yes

### D-0065 — Minimal `/healthz` lands with `make dev`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `crawlerai/api/app.py` has `create_app()` with `GET /healthz` → 200 `{"status":"ok"}`. SPEC-07 PR 1 extends the factory and adds the DB ping.
- Alternatives: wait for SPEC-07; add the DB ping now.
- Why: SPEC-00 PR 2's done-when needs an API answering `/healthz`; this is the smallest shape that does.
- Reversible: yes

### D-0066 — `make dev` starts only what exists
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: compose up `--wait` → `uv sync` → `alembic upgrade head` → `uvicorn --reload`. The rows that add the worker, scheduler and `pnpm dev` also add a process runner.
- Alternatives: honcho now, with placeholders.
- Why: There's nothing else to run yet.
- Reversible: yes

### D-0067 — Local credentials and the `custodian` role
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: Compose uses throwaway passwords bound to `127.0.0.1`. `custodian` is `NOLOGIN` locally, and `.env.example` leaves `EVAL_PRIVATE_*` empty. `make dev` copies `.env.example` to `.env` if missing and exports it (Settings doesn't read `.env`, D-0047).
- Alternatives: a custodian password in the repo; `.env` loading in Settings.
- Why: No custodian credential ever exists in the repo (C1).
- Reversible: yes

### D-0068 — Alembic layout
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `backend/alembic.ini` + `backend/migrations/`. The URL comes from `DatabaseSettings` (the `database_url`-only base of `Settings`). Offline mode is refused. Revision IDs are sequential (`0001`). `target_metadata` stays `None` until SPEC-01.
- Alternatives: read the env var in `env.py`; full Settings; hex revision IDs.
- Why: One settings boundary; sequential IDs make review order obvious.
- Reversible: yes

### D-0069 — Backend Dockerfile in `infra/`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `infra/Dockerfile`, built from `backend/`: `python:3.12-slim` + uv 0.11.28, runs as non-root `crawlerai`, copies only what it runs, and its default command runs the API.
- Alternatives: leave it to a later row.
- Why: SPEC-00 §2 asks for one backend image, and the row's scope is `infra/*`.
- Reversible: yes

### D-0070 — CI and the image install dependencies from wheels only
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: superseded by D-0141
- Decision: `uv sync --frozen --no-build --no-install-project`, then `uv build --wheel` + `uv pip install --no-build --no-deps` for the project. Later steps use `uv run --no-sync --no-build`. Local dev keeps the editable sync. SonarCloud S8544 on the wheel install is a false positive (it resolves nothing).
- Alternatives: `uv sync --frozen` (builds sdist dependencies; S8541).
- Why: No third-party build script runs in CI or the image.
- Reversible: yes

### D-0071 — `crawlerai openapi` output is byte-stable JSON
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 4 (#9) · Status: decided
- Decision: `indent=2`, `sort_keys=True`, a trailing newline, written as UTF-8 bytes to stdout (no CRLF on Windows).
- Alternatives: FastAPI insertion order; an `--output` flag.
- Why: The freshness check (SPEC-00 §4.5) compares bytes; stdout keeps the spec's `> frontend/openapi.json` form.
- Reversible: yes

### D-0072 — Generated API files are excluded from Prettier
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 4 (#9) · Status: superseded by D-0226
- Decision: `openapi.json` and `src/api/schema.d.ts` are in `.prettierignore`.
- Alternatives: run Prettier inside `gen:api`.
- Why: One source of formatting keeps the freshness diff simple.
- Reversible: yes

### D-0073 — API key is optional in `createApiClient`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 4 (#9) · Status: decided
- Decision: `createApiClient({ baseUrl, apiKey? })` sends `Authorization: Bearer` only when a key is given; there is no default base URL.
- Alternatives: require a key; a base URL from the Vite env.
- Why: `/healthz` is unauthenticated; the UI holds the key in memory (ARCHITECTURE §18, SPEC-07 §4.2).
- Reversible: yes

### D-0074 — License policy script instead of `--fail-on`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `pip-licenses` and `pnpm licenses` only collect data. `tools/license_policy.py` decides with SPDX expression semantics (OR: any clean branch; AND: all; WITH checks the exception; `+` maps to the base ID), using the same matcher for both ecosystems.
- Alternatives: `pip-licenses --fail-on` and `license-checker-rseidelsohn --failOn` as SPEC-00 §4.6 names them.
- Why: `--fail-on` matches whole strings: `MIT AND GPL-3.0-only` passes it, and trove names never match SPDX IDs.
- Reversible: yes

### D-0075 — Denied licenses also matched as trove classifiers
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: The seven PyPI trove classifiers for AGPL/GPL v2/v3, matched as whole names. LGPL is not included.
- Alternatives: SPDX IDs only (misses packages from before PEP 639); substring matching (forbidden).
- Why: The same deny-list in the standard classifier vocabulary, so not a list that grows per incident (C4).
- Reversible: yes

### D-0076 — Python license declaration precedence
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: Use `License-Expression` (PEP 639) if present. Otherwise fail if any classifier is denied. Otherwise use the `License` field.
- Alternatives: check all three; require every classifier to be denied.
- Why: PEP 639 is authoritative, and failing on any denied classifier is conservative.
- Reversible: yes

### D-0077 — Undeclared or unknown licenses don't fail the scan
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `UNKNOWN` declarations are reported in the JSON artifacts but pass.
- Alternatives: fail on unknown.
- Why: SPEC-00 defines a deny-list, not an allow-list.
- Reversible: yes

### D-0078 — Frontend licenses and SBOM come from pnpm's built-ins
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `pnpm licenses list` and `pnpm sbom --sbom-format cyclonedx`, with no new frontend dependency.
- Alternatives: `license-checker-rseidelsohn` plus `@cyclonedx/cyclonedx-npm` or `cdxgen`.
- Why: Fewer dependencies, and pnpm reads its own lockfile.
- Reversible: yes

### D-0079 — `licenses` uv dependency group
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `pip-licenses>=5,<6` (MIT) and `cyclonedx-bom>=7,<8` (Apache-2.0, verified) live in their own group. The scan syncs `--all-groups` and runs `pip-licenses --with-system`, so the scan tools are checked too.
- Alternatives: put them in `dev`.
- Why: The backend job doesn't install about 30 extra packages.
- Reversible: yes

### D-0080 — The project itself is excluded from the license scan
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: The scan syncs with `--no-install-project`.
- Alternatives: scan the project too.
- Why: The project is AGPL-3.0 (LICENSE); the deny-list applies to dependencies.
- Reversible: yes

### D-0081 — A missing hidden-host list passes visibly
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 8 (#8) · Status: decided
- Decision: An unset or empty list prints `hidden-hosts: pass, no host list configured`. SPEC-03 can make a missing list fail once H2 is done.
- Alternatives: fail when the secret is missing.
- Why: SPEC-00 §4.6: the job must pass until milestone M; the line makes the skip visible.
- Reversible: yes

### D-0082 — Hidden-host scan tokenizes on `[a-z0-9.-]` and redacts by substring
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 8 (#8) · Status: decided
- Decision: Each `[a-z0-9.-]` run in a file or path is looked up case-insensitively against the host set, by every run of its labels, so `_` and every other character separate tokens. A path naming a host is reported as `path:0`. Printed paths have every case-insensitive occurrence of every host replaced with `[hidden]`, independent of tokenizing.
- Alternatives: a regex alternation over all hosts for content (7.2 s/MB at 3,000 hosts vs 0.25 s/MB); `DOTTED`'s `\w` boundaries (leaked a host through `_` in review round 1).
- Why: The most conservative reading of C1/C3: redaction by substring can't leak through a tokenizing gap.
- Reversible: yes

### D-0083 — The hidden-host list is split leniently
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 8 (#8) · Status: decided
- Decision: The secret is split on whitespace and commas, lowercased, with leading and trailing dots stripped.
- Alternatives: one host per line only.
- Why: Tolerant of how the custodian pastes it; it doesn't change what is printed.
- Reversible: yes

### D-0084 — No-size-gates is a tested script covering tool configs
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: decided
- Decision: `tools/no_size_gates.py` (stdlib) scans workflows, `.pre-commit-config.yaml`, `Makefile` and the configs of the tools they run (pyproject, ruff, package.json, ESLint/Vite/Vitest) for line-count tools, size or complexity limits (mccabe/`C901`, pylint `PLR09`, ESLint `max-*`/`complexity`) and coverage thresholds.
- Alternatives: the spec's one-line grep over workflows and hooks.
- Why: An inline grep matches its own patterns, and a gate can be switched on in a tool config just as easily (C11).
- Reversible: yes

### D-0085 — INVARIANTS.md has a Status column
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: decided
- Decision: Each invariant says whether its enforcement runs today (`active`) or which spec adds it.
- Alternatives: the four spec columns only.
- Why: Docs make no claim a check doesn't back (CLAUDE.md §6).
- Reversible: yes

### D-0086 — Escalations copy `needs-owner` entries to OPEN_QUESTIONS.md
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: confirmed 2026-10-13
- Decision: CLAUDE.md §5 step 1: the escalation writer copies the `needs-owner` entry as a row in `OPEN_QUESTIONS.md`. This is the only agent edit to that file without owner approval.
- Alternatives: the owner copies them.
- Why: SPEC-00 §4.9 item 13 and OPEN_QUESTIONS.md's own text require the copy; CLAUDE.md §6 otherwise reserves the file to the owner.
- Reversible: yes
- Owner answer: confirmed as written (D-0234).

### D-0087 — SPEC-00 §4.3 HeroUI row corrected (clarifying edit)
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: decided
- Decision: `@heroui/react` and `@heroui/styles` 3.2.6, MIT, per D-0051.
- Alternatives: none.
- Why: Matches the published packages; no architecture change.
- Reversible: yes

### D-0106 — Pre-commit tool hooks are `repo: local`
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: The ruff, prettier and eslint hooks run the versions pinned in `backend/uv.lock` and `frontend/pnpm-lock.yaml`.
- Alternatives: `ruff-pre-commit` and `mirrors-prettier` pinned in the config.
- Why: One version source per tool, so hooks can't drift from CI.
- Reversible: yes

### D-0107 — `--staged` scans the index
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: `--staged` is a flag of the scanner's public mode and reads index content (`git show :path`), not a list of file paths.
- Alternatives: Pass filenames and read the working tree.
- Why: §4.8 names `--staged`; reading the index scans exactly what gets committed.
- Reversible: yes

### D-0108 — `make check` round-trips migrations on a scratch database
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: `check-migrations` runs upgrade, downgrade, upgrade on a scratch `crawlerai_check` database recreated each run, and backend tests run against it, not the dev database.
- Alternatives: Use `crawlerai`, as CI does on its throwaway service.
- Why: `downgrade base` would wipe local dev data on every `make check`.
- Reversible: yes

### D-0109 — `make check` leaves out the protected hidden-host scan
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: The hidden-host scan runs only in the protected CI job.
- Alternatives: Run it with an empty `HIDDEN_HOSTS`.
- Why: C1: its input exists only in the custodian environment; without it the scan is a pass-through.
- Reversible: yes

### D-0110 — eslint pre-commit hook exceeds the 10 s budget on Windows
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: superseded by D-0227
- Question: the eslint hook takes 10.6–17.4 s for a one-file frontend change on the Windows dev host (5–6 s warm on Linux), against SPEC-00 §4.8's < 10 s budget. Which wins?
- Options: (a) keep type-aware eslint in the hook and accept the Windows overage; (b) drop type-aware rules from the hook, keeping the full lint in `make check` and CI; (c) revisit the frontend lint config (`projectService`, HeroUI type depth) in a frontend row.
- Recommendation: (a) now, since hooks are not weakened; consider (c) later.
- Blocked: nothing. Python-file commits take about 2 s.

### D-0111 — The C3 scan reads schema-defined `table.column` strings as columns
- Date: 2026-10-13 · Spec/PR: SPEC-00 §4.7 follow-up (#15) · Status: decided
- Decision: `table.column` is a column reference, not a host, only when the repository's schema (Alembic ops, `Table`, declarative models in tracked Python files) defines both the table and the column.
- Alternatives: allowlist table names (C4); exempt any `identifier.identifier` in Python strings (hides real two-label hosts); treat `_`-adjacent tokens as identifiers.
- Why: structural and derived from the repo, like the file-extension and module-path rules; a host escapes only if a table and column with exactly its two labels exist in the schema.
- Reversible: yes

### D-0141 — One locked `uv sync` installs CI and the image
- Date: 2026-10-13 · Spec/PR: SPEC-00 follow-up (#21) · Status: decided
- Decision: `uv sync --frozen --no-build --no-binary-package crawlerai --no-editable` (`--no-dev` in the image) replaces D-0070's `--no-install-project` + `uv build` + `uv pip install`. Only the project is built from source; every dependency stays wheel-only from `uv.lock`. Later steps still use `uv run --no-sync --no-build`.
- Alternatives: keep D-0070's commands and mark SonarCloud S8544 as a false positive.
- Why: Same property as D-0070 (no third-party build script runs), and every install now comes from the lockfile, which clears S8544 in code.
- Reversible: yes

### D-0142 — The site-literal scan's allowlist must lie inside `--root`
- Date: 2026-10-13 · Spec/PR: SPEC-00 follow-up (#21) · Status: decided
- Decision: the default allowlist is `<root>/tools/site_literal_allowlist.txt`; an explicit `--allowlist` must resolve inside `--root`, else `UsageError`.
- Alternatives: read any path given (SonarCloud S8707).
- Why: The scanned repository is the natural base; default CI and hook runs are unchanged.
- Reversible: yes

### D-0226 — Frontend toolchain is Vite+
- Date: 2026-10-13 · Spec/PR: SPEC-00 §4.3 follow-up (#38, owner request) · Status: decided
- Decision: `vite-plus` 1.1.0 (MIT), pinned exactly, replaces ESLint, Prettier, `tsc -b` and the separate Vite/Vitest setup; lint (Oxlint), fmt (Oxfmt), type-check (tsgo), test and build are configured in `frontend/vite.config.ts`. pnpm stays. Generated API files are excluded through `fmt.ignorePatterns`. TypeScript 5.9.3 stays only as the `openapi-typescript` peer and for editors. `engines.node` follows vite-plus (`^22.18.0 || ^24.11.0 || >=26.0.0`); CI uses Node 24. Plugins are a plain array (`lazyPlugins` fails `exactOptionalPropertyTypes`). Supersedes the ESLint/Prettier/Vitest parts of D-0003, D-0052 and D-0072.
- Alternatives: keep ESLint + Prettier; Biome.
- Why: The owner asked for one toolchain in one PR. SPEC-00 §4.3 and DESIGN.md were edited in the same PR under that request.
- Reversible: yes, with churn

### D-0846 — The C3 scan reads schemas only from non-exempt files
- Date: 2026-10-15 · Spec/PR: SPEC-00 §4.7 follow-up (#15, #193) · Status: decided
- Decision: Tables (Python) and schema documents (JSON) under the exempt paths define no names the scan accepts, in full and `--staged` mode. Names of tracked files, modules and manifest extensions still come from every tracked file: they are file names, not file contents.
- Alternatives: read every tracked file (an exempt file could excuse a host it is free to hold).
- Why: An exempt file is not scanned, so what it defines must not exempt tokens elsewhere.
- Reversible: yes
