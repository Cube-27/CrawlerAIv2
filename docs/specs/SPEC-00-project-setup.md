# SPEC-00 — Project setup and engineering foundations

Layer: L0. Architecture refs: §2 (C1–C13), §4, §18, §19, §21.

## 1. Summary

Create the monorepo, toolchain, CI, hooks and root documents that every later spec builds on. Nothing in this
spec extracts anything. Its purpose is to make the generalization contract (§2.2) mechanically enforced from the
first commit: the site-literal scan (C3), the import contract (C8), the license deny-list (§18), the protected
eval job placeholder (C1), the aggregate-report PR requirement (C10), and the absence of size gates (C11).

## 2. Scope

Core:
- Repo layout, backend and frontend toolchains, one-command local start (§19).
- GitHub Actions CI with the checks listed in §4 below.
- Local checks and git hooks.
- Root files: extend the existing `README.md`; check the existing `CLAUDE.md` (the agent instruction file) against
  4.9 and add what is missing; create `docs/INVARIANTS.md`, `docs/DESIGN.md`, `.env.example`, `CONTRIBUTING.md`,
  `.github/pull_request_template.md`. Already in the repo and not recreated here: `LICENSE` (AGPL-3.0),
  `CLAUDE.md`, `README.md`, `docs/DECISIONS.md` (agent decisions log), `docs/plans/ACTIVE.md` (implementation
  tracker).
- Backend package skeleton (empty packages with `__init__.py`) so that the import-linter contracts (C8) exist before
  the first normalizer is written.
- Frontend application skeleton: routing, theme, generated API client, one placeholder screen.

Out of scope:
- Any extraction, acquisition, eval or API behaviour (SPEC-01 onward).
- LOC, complexity, coverage-percentage or file-size gates (C11). Do not add them in any form, including "soft"
  warnings.
- §22 candidates: all. In particular no "site health dashboard" and no "review queue UI" in the frontend skeleton.
- Deployment to any cloud; only `docker-compose` for local development and a Dockerfile that builds the single
  backend image (§4).

## 3. Dependencies

- None (first spec).
- OPEN_QUESTIONS #9 (license), resolved: the project is **AGPL-3.0** (Appendix A #26); the `LICENSE` file already
  exists in the repository and this spec does not recreate it. The dependency deny-list (AGPL, GPL, SSPL,
  non-commercial) stays in CI: keeping dependencies permissive preserves the owner's option to license the
  project differently later (§18). LGPL is **not** on the deny list in the architecture; this spec treats LGPL as
  allowed and flags it (§9).
- OPEN_QUESTIONS #6 (custodian): default owner + one engineer. Only affects the protected-job placeholder here.

## 4. Design

### 4.1 Repo layout

```
/
  README.md  CLAUDE.md  LICENSE          # exist already; never recreated (README, CLAUDE.md extended)
  AGENTS.md                              # optional: one line pointing to CLAUDE.md
  CONTRIBUTING.md  NOTICE  .env.example  .gitignore
  .pre-commit-config.yaml
  .github/workflows/{ci.yml, eval-protected.yml}
  .github/pull_request_template.md
  docs/ARCHITECTURE.md  docs/OPEN_QUESTIONS.md  docs/DECISIONS.md  docs/plans/ACTIVE.md  docs/specs/
  docs/INVARIANTS.md  docs/DESIGN.md
  tools/site_literal_scan.py  tools/license_scan.sh  tools/data_manifest_check.py
  infra/docker-compose.yml  infra/Dockerfile  infra/postgres/init.sql
  backend/
    pyproject.toml  uv.lock  .importlinter  mypy.ini (or [tool.mypy] in pyproject)
    alembic.ini  migrations/
    data/manifest.json          # pinned external data (CLDR via Babel is a package; GeoNames snapshot is listed here)
    src/crawlerai/
      core/        settings, ids, errors, engine_version, logging (redaction)
      db/          SQLAlchemy models, session, queue claim queries
      storage/     object store backends, capture bundle format
      acquire/     http, browser, ssrf, politeness, robots, outcome classification
      adapters/    THE ONLY PACKAGE ALLOWED TO CONTAIN HOSTNAMES (C3)
      schemas/     field types, registry, presets
      normalize/   one module per field type (C8)
      collect/     jsonld, microdata, og, js_state, xhr, config_exec
      resolve/     ownership, intent, preference, calibration
      llm/         client, providers, grounding, roles
      config_ir/   IR model, executor, induction, synthesis, validation, drift, exporters, api_recipe
      content/     cleaned text, markdown, links, metadata
      api/         FastAPI app, routers, auth
      mcp_server/
      crawl/       frontier, map, sitemaps
      recurring/   fingerprints, listing diff
      eval/        splits, labels, replay harness, metrics, report
      worker/      task loop
      scheduler/   periodic maintenance
      cli.py       `crawlerai` entry point
    tests/
      unit/  property/  replay/  contracts/
  frontend/
    package.json  pnpm-lock.yaml  vite.config.ts  tsconfig.json  eslint.config.js  .prettierrc
    src/api/schema.d.ts (generated)  src/api/client.ts
    src/app/ (router, shell, theme)  src/screens/  src/components/
```

Rules encoded by layout:
- `backend/src/crawlerai/adapters/` is the only source directory where the C3 scan allows hostnames.
- `backend/data/manifest.json` lists every external data snapshot (URL, version/date, sha256, license,
  justification). Any data file under `backend/data/` not listed in the manifest fails CI (`tools/data_manifest_check.py`).
  This is the mechanical form of C4: vocabularies come from versioned external data, not from incidents.

### 4.2 Backend toolchain

| Tool | Choice | License | Why |
|---|---|---|---|
| Python | 3.12 (§19) | PSF | Owner decision. |
| Package/env manager | `uv` | MIT/Apache-2.0 | Lockfile (`uv.lock`), fast, one tool for venv + resolution. |
| Lint + format | `ruff` (lint + `ruff format`) | MIT | One tool; enables `S102` (`exec`), `S307` (`eval`) to support §18 "never exec LLM output". |
| Type checker | `mypy --strict` with the pydantic plugin | MIT | Boring and complete; pydantic v2 plugin keeps model typing honest. |
| Tests | `pytest`, `pytest-asyncio`, `hypothesis` (test-only) | MIT, Apache-2.0, MPL-2.0 | §19. Hypothesis is MPL-2.0 (weak copyleft, test-only, not on the deny list). |
| Import contracts | `import-linter` | BSD-2 | C8 (§5 of this spec). |
| Web | `fastapi`, `pydantic` v2, `pydantic-settings`, `uvicorn` | MIT | §19. |
| DB | `sqlalchemy` 2.x (async), `asyncpg`, `alembic` | MIT, Apache-2.0, MIT | asyncpg chosen over psycopg (LGPL) so the deny-list question never arises. Alembic is the migrations tool. |
| HTTP | `httpx`, `curl_cffi` | BSD-3, MIT | §19. |
| Object storage | `boto3` (S3) plus a filesystem backend for dev/CI | Apache-2.0 | §15; MinIO is AGPL and must not be used, even locally. |
| Compression | `zstandard` | BSD-3 | §15 capture bundles. |
| Licenses | `pip-licenses --fail-on` **[verified]** | MIT | §18 deny list. |
| SBOM | `cyclonedx-bom` **[unverified: license, check at adoption]** | Apache-2.0 | §18. |

Versions are pinned in `uv.lock`; `pyproject.toml` uses `>=` lower bounds with the major pinned. The tooling
choices in 4.2 and 4.3 are recorded as entries in `docs/DECISIONS.md` (§19).

Commands (all via `uv run`): `ruff check .`, `ruff format --check .`, `mypy src tests`, `pytest`,
`lint-imports`, `alembic upgrade head`, `crawlerai` (CLI).

### 4.3 Frontend toolchain

| Tool | Choice | License | Why |
|---|---|---|---|
| Build | Vite 6+, React 19, TypeScript 5 | MIT, MIT, Apache-2.0 | Owner choice. |
| UI library | **HeroUI v3** — `@heroui/react@3.2.2` + `@heroui/styles@3.2.2` **[verified 2026-10-12]** | Apache-2.0 **[verified]** | v3 is the stable major (out of beta March 2026; 3.2.2 released 2026-06-19). It is built on React Aria Components and Tailwind CSS v4. Use the latest 3.x patch at setup time. |
| CSS | Tailwind CSS v4 via `@tailwindcss/vite` | MIT | Required by HeroUI v3 **[verified]**. Setup is two CSS imports: `@import "tailwindcss"; @import "@heroui/styles";`. No provider component is needed **[verified]**. |
| Package manager | `pnpm` | MIT | Strict node_modules, fast, lockfile. |
| Lint/format | ESLint 9 (flat config) + `typescript-eslint` + `eslint-plugin-react-hooks` + `eslint-plugin-jsx-a11y`; Prettier | MIT | a11y lint supports the React Aria accessibility goal (DESIGN.md). |
| Unit tests | Vitest + Testing Library + jsdom | MIT | Fast, Vite-native. |
| Routing | `react-router` | MIT | — |
| API client | `openapi-typescript` (types) + `openapi-fetch` (client) + `@tanstack/react-query` | MIT | Generated from `backend` OpenAPI; see 4.5. |

Notes: v3 is a different API from HeroUI v2 (NextUI lineage); do not use v2 docs or `@heroui/*` v2 packages.
Dark mode: HeroUI v3 switches on `.dark` or `data-theme="dark"` on an ancestor **[verified]**; DESIGN.md
standardizes on `data-theme`.

### 4.4 One-command local start

- `infra/docker-compose.yml`: `postgres:16` (two databases created by `infra/postgres/init.sql`: `crawlerai` and
  `crawlerai_eval_private`; two roles: `app`, `custodian`), no object store container (dev uses the filesystem
  backend at `./.data/objects`).
- `make dev` (or `just dev`; pick `make`): starts compose, `uv sync`, `alembic upgrade head`, starts `api`,
  `worker`, `scheduler` and `pnpm dev` with one process manager (`honcho`, MIT **[unverified]**, or a tiny Python
  runner — either is fine; implementation detail).
- `make check`: everything CI runs, locally.
- `.env.example` lists every setting with a comment; `pydantic-settings` reads `CRAWLERAI_*` variables.

Settings that must exist from day one (names are the contract; later specs add more):

```
CRAWLERAI_DATABASE_URL          # app role, main DB
CRAWLERAI_EVAL_PRIVATE_DATABASE_URL   # custodian only; empty for agents/developers
CRAWLERAI_OBJECT_STORE          # fs:///abs/path | s3://bucket/prefix
CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE   # custodian only
CRAWLERAI_LOG_REDACT_URLS       # true in the protected job
CRAWLERAI_ROLE                  # api | worker | scheduler
```

### 4.5 Generated API client

- Backend exports its OpenAPI document with `uv run crawlerai openapi > frontend/openapi.json` (committed).
- `pnpm gen:api` runs `openapi-typescript openapi.json -o src/api/schema.d.ts` (committed).
- CI regenerates both and fails if `git diff` is non-empty ("API client out of date").
- `src/api/client.ts` wraps `openapi-fetch` with the base URL and the API key header.

### 4.6 CI (`.github/workflows/ci.yml`)

Jobs (all required for merge, all run on every PR):

1. `backend`: `uv sync --frozen`; `ruff check`; `ruff format --check`; `mypy`; `lint-imports`; `pytest -m "not replay"`;
   `pytest -m replay` (dev captures only; empty until SPEC-03); alembic `upgrade head` + `downgrade base` + `upgrade head`
   against a service Postgres.
2. `frontend`: `pnpm install --frozen-lockfile`; `pnpm lint`; `pnpm typecheck`; `pnpm test`; `pnpm build`;
   API client freshness check (4.5).
3. `licenses`: `tools/license_scan.sh` — backend: `pip-licenses --fail-on "AGPL-3.0;AGPL-3.0-only;AGPL-3.0-or-later;GPL-2.0;GPL-2.0-only;GPL-2.0-or-later;GPL-3.0;GPL-3.0-only;GPL-3.0-or-later;SSPL-1.0;CC-BY-NC-4.0;CC-BY-NC-SA-4.0;CC-BY-NC-ND-4.0;PolyForm-Noncommercial-1.0.0;Commons-Clause"`
   against the synced environment (covers transitive deps); frontend: a `license-checker`-style tool with
   `--failOn` on the same list **[unverified: pick `license-checker-rseidelsohn` or equivalent MIT tool at adoption]**.
   Both also emit a JSON report and a CycloneDX SBOM as workflow artifacts. Match on SPDX identifiers, never
   substring (so LGPL does not match GPL).
4. `site-literals`: `python tools/site_literal_scan.py --public` (4.7).
5. `data-manifest`: `python tools/data_manifest_check.py`.
6. `no-size-gates` (meta): a one-line grep that fails if any workflow or hook references LOC counts, `radon`,
   `xenon`, `--max-lines`, `--max-complexity` or a coverage threshold flag. This keeps C11 enforced against drift.

`.github/workflows/eval-protected.yml` (placeholder in this spec; filled by SPEC-03):
- Triggered on `pull_request` and `push` to `main`; uses GitHub **environment** `eval-protected` whose secrets
  (`EVAL_PRIVATE_DATABASE_URL`, `EVAL_PRIVATE_OBJECT_STORE` credentials, `HIDDEN_HOSTS`) are available only to
  that environment and whose required reviewers are the custodians (OPEN_QUESTIONS #6). Workflows from forks never
  see the secrets. Coding agents never get the environment's approval rights.
- In this spec the job posts a placeholder pass line (`no_baseline`). Until milestone M (ARCHITECTURE §21) the
  environment and its secrets may not exist; the job must then pass, not fail; the C3
  hidden-host scan (`tools/site_literal_scan.py --hidden-hosts-from-env HIDDEN_HOSTS`, reporting file:line only)
  is wired now because it needs nothing else.
- The job uploads **no** artifacts (public repo: artifacts and logs are public), writes `eval-aggregate.json` only to
  the private store, prints only pass/fail lines, and runs with `CRAWLERAI_LOG_REDACT_URLS=true`. The
  `eval-protected` environment requires reviewer approval, so fork PRs never receive its secrets unreviewed.

### 4.7 Site-literal scan (`tools/site_literal_scan.py`)

- Input: all tracked files. Regex for hostnames `(?i)\b([a-z0-9-]+\.)+(TLD)\b` where TLD is the IANA root-zone
  list downloaded and pinned in `backend/data/manifest.json` (versioned external data, C4). Also matches
  `http(s)://` URLs.
- Exemptions by path: `backend/src/crawlerai/adapters/**`, `docs/**`, `*.lock`, `pnpm-lock.yaml`, `uv.lock`,
  `package.json`, `pyproject.toml`, `.github/**`, `LICENSE`, `NOTICE`, `backend/data/manifest.json`.
- Exemptions by host: a short allowlist in `tools/site_literal_allowlist.txt`, one host per line with a
  justification, limited to standards bodies and tooling hosts (`schema.org`, `www.w3.org`, `iana.org`,
  `unicode.org`, `geonames.org`, `github.com`, `pypi.org`, `registry.npmjs.org`, and the reserved names of RFC 2606 /
  RFC 6761: `example.com/.net/.org`, `.test`, `.invalid`, `.localhost`, `localhost`). Adding a commercial site, a
  retailer or a job board to the allowlist is a C3 violation; the PR template says so.
- `--public` mode: fails on any match not exempted. Tests are **not** exempt (C9).
- `--hidden-hosts-from-env` mode (protected job): reads the secret host list, scans every file including exempted
  paths and docs, prints only `path:line` for matches, never the host. No allowlist applies in this mode.

### 4.8 Local checks and hooks

`.pre-commit-config.yaml` (fast; whole run < 10 s on a typical change):
- ruff (lint + format), mypy on changed files is too slow; run mypy only in `make check` and CI.
- `tools/site_literal_scan.py --public --staged`.
- prettier + eslint on staged frontend files.
- `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`.

No hook counts lines or complexity (C11).

### 4.9 Root files (content requirements)

**README.md** (exists; extend it, do not replace it): what the product is (one paragraph from §1), the license
(AGPL-3.0), how to start (`make dev`), where the architecture lives, the layout above, and the sentence "Agents:
read CLAUDE.md before changing anything."

**CLAUDE.md** (exists; written separately) is the agent instruction file. This spec checks that it covers the
items below in operational language and adds any that are missing; it does not rewrite the file. If an
`AGENTS.md` is kept for other tools, it is a one-line pointer to `CLAUDE.md` and holds no rules of its own.
1. The project documents you may read: `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md`, `docs/specs/*`,
   `docs/DECISIONS.md`, `docs/plans/ACTIVE.md`. The things you may never read or request: hidden/fresh eval
   cases, `HIDDEN_HOSTS`, `CRAWLERAI_EVAL_PRIVATE_*` values, the Invoro and CrawlerAI v1 repositories (C1, C12).
2. "Never add a site name, hostname, brand, retailer, or a string copied from a page anywhere except
   `backend/src/crawlerai/adapters/` or a database row" (C3).
3. "Never add a word, phrase, token, class name, selector or regex because one page failed. If a fix is specific
   to a site, it is data: re-run learning or correct the config through the API" (C4, C5).
4. "Every generic rule names its standard (schema.org, ISO, CLDR, RFC, HTML) or the structural property it uses
   in a comment next to it" (C2).
5. "Normalizers decline. Never add a default, a fallback currency, a host table, or a value taken from a URL" (C7).
6. "One module per field type; if you need the same logic twice you are in the wrong module" (C8).
7. "No test names a site or asserts one site's output; write property tests and replay tests" (C9).
8. "Do not build anything in ARCHITECTURE §22. If a task asks for it, stop and point at C13."
9. "Do not add LOC, complexity, or coverage gates, and do not split files to satisfy a size number" (C11).
10. How to read eval results (C10, §16.3–16.4): the dev report is full; the hidden report is pass/fail plus
    aggregates per field type and evidence bucket, with cells under 10 labeled fields suppressed. A change is
    accepted when it **improves dev** and **does not regress hidden** (no hidden precision drop > 0.5 pt on any
    required field type, wrong-product stays 0); a dev improvement with a hidden drop is a regression, not a
    win. Never claim an improvement from hidden results; improvement claims come only from fresh. Never try to
    infer which sites are in hidden from aggregates.
11. "A PR that changes extraction behaviour includes the aggregate report in its description" (C10).
12. The spec template and the rule that a spec change that alters a decision also updates ARCHITECTURE.md, and
    that changes to ARCHITECTURE.md are escalated to the owner (Appendix A #28).
13. Process: record implementation decisions in `docs/DECISIONS.md` (one that needs the owner is also copied to
    `docs/OPEN_QUESTIONS.md`), and keep the current implementation state in `docs/plans/ACTIVE.md` (Appendix A
    #28).

**docs/INVARIANTS.md**: the testable invariants, each with ID, statement, architecture ref, and enforcement.
Initial list (later specs may add, never remove):

| ID | Invariant | Ref | Enforced by |
|---|---|---|---|
| INV-01 | No hidden or fresh case (URL, host, label, capture) exists in the main DB, the repo, logs or CI artifacts. | C1, §6, §15 | Separate DB + object prefixes with custodian-only credentials; protected job uploads no artifacts and writes aggregates only to the private store; log redaction test (SPEC-03). |
| INV-02 | Calibration tables, `source_precedence.yaml`, drift margins and type vocabularies are derived from dev only. | C1, §10, §16 | Calibration/precedence commands refuse any split but `dev` and stamp the artifact with its source split (SPEC-03, SPEC-05). |
| INV-03 | No hostname or URL literal outside `adapters/`, docs, lockfiles and the justified allowlist. | C3 | `tools/site_literal_scan.py --public` in CI and pre-commit. |
| INV-04 | No hidden/fresh host appears anywhere in the repo. | C1, C3 | Protected scan, file:line only. |
| INV-05 | Every data file under `backend/data/` comes from a pinned external source listed in the manifest. | C4 | `tools/data_manifest_check.py`. |
| INV-06 | A normalizer never returns `Ok` for empty input, never maps an ambiguous symbol without context, never reads a host table. | C7, §9 | Hypothesis property tests per type (SPEC-04). |
| INV-07 | Derived values fill only empty fields and carry `derived_by`. | C7 | Resolver tests (SPEC-05). |
| INV-08 | Exactly one module handles each field type; only `normalize.*` imports Babel, price-parser, dateparser, GeoNames data. | C8 | import-linter contracts (`.importlinter`). |
| INV-09 | No test file, test name or fixture contains a hostname or retailer name. | C9 | INV-03 scan covers `tests/`. |
| INV-10 | Replay is deterministic: the same (bundle, schema, config, calibration) yields byte-identical records, with LLM calls replayed from recorded responses. | G7, §15 | Replay tests run twice and diff (SPEC-03). |
| INV-11 | Blocked and shell captures yield zero candidates and zero records. | §7.1, §8.2 | Unit tests on the pipeline entry (SPEC-05). |
| INV-12 | Every `llm` candidate value is a verbatim substring of the cleaned text at its stated offsets. | §11 | Grounding check test (SPEC-06). |
| INV-13 | URL query-parameter values are never published unless the same value is visible on the page. | §8.2 r4 | Resolver test (SPEC-05). |
| INV-14 | For exact-match types, two valid owned candidates that disagree produce `conflict` and no value. | §10 | Property test (SPEC-05). |
| INV-15 | Price, currency and availability of a published offer come from one source object. | §10 | Resolver test (SPEC-05). |
| INV-16 | Every outbound connection target is a public IP; each redirect hop is re-checked; proxies do not bypass the check. | §7.1, §18 | SSRF tests with a stub resolver (SPEC-02). |
| INV-17 | LLM output is never executed. | §11, §18 | ruff S102/S307 + grep for `exec(`/`eval(`/`subprocess` outside an allowlisted module. |
| INV-18 | CI and hooks contain no LOC, complexity or coverage-threshold gates. | C11 | `no-size-gates` CI job. |
| INV-19 | Every PR that touches extraction behaviour carries the dev delta report and the hidden pass/fail per field type. | C10 | PR template; protected job comment. |
| INV-20 | An exported config field reproduces the engine's value on every held-out page while there are fewer than 10, and on ≥ 95% from 10 on, or is marked `manual`. | §12.3 | Release check test (SPEC-08). |
| INV-21 | Wrong-product count on hidden is 0 or the merge fails. | G2, §16.4 | Protected job gate. |
| INV-22 | Every candidate carries a locator; every published field carries `evidence`, `confidence`, `calibrated`, `source_kind`, `locator`. | §6, §13.1 | Pydantic models + tests (SPEC-05). |
| INV-23 | Every LLM call writes a `usage_event` with `prompt_kind` and is charged to a job budget. | §11, §17 | LLM client tests (SPEC-06). |
| INV-24 | `site.fetch_method` and block classification are decided from HTTP status and structural body properties only; no vendor or challenge-page strings exist in code. | C2, C3, §7.1 | INV-03 scan; review. |

**docs/DESIGN.md** (frontend conventions on HeroUI v3):
- Theming: colors, radius, spacing come from HeroUI's CSS-variable theme layer; project overrides live in
  `src/app/theme.css` as `:root` / `[data-theme="dark"]` variables only. No hard-coded hex values in components.
- Light/dark: `data-theme` attribute on `<html>`, defaulting to `prefers-color-scheme`, persisted per viewer in
  `localStorage` (wrapped in try/catch).
- Layout: a single app shell (top bar + left nav + content), content max width 1280px, 16px gutters at phone
  width, no horizontal scroll.
- Component rules: use HeroUI components for all interactive elements (Button, TextField, Select, Table, Modal,
  Tabs, Toast); never hand-roll a focusable control; forms use React Aria's form validation; tables use the
  HeroUI Table with keyboard navigation; status is shown with text + icon, never color alone.
- Accessibility via React Aria: every control has an accessible name; keyboard reachable; `jsx-a11y` lint on;
  focus visible styles not removed.
- Data display rules specific to this product: an abstained field is rendered as "—" with its reason on hover,
  never as an empty string; `calibrated=false` is rendered as a visible badge; `confidence` is rendered as a
  number, not a bar (bars imply calibration).
- Charts (if any later): follow the dataviz guidance; not used in core screens.

**.env.example**: every `CRAWLERAI_*` setting with comments; private values empty.

**CONTRIBUTING.md** and **pull_request_template.md**:
- Checklist: "I did not add a site literal" / "I did not add a list entry for a single page" / "No §22 candidate
  implemented" / "Aggregate report attached (required if `collect/`, `normalize/`, `resolve/`, `llm/`,
  `config_ir/`, `acquire/` changed): dev delta shown, hidden gate passed, no improvement claimed from hidden
  (C10)" / "Property or replay tests added, no site-named tests" / "Decisions recorded in `docs/DECISIONS.md`".
- Where the report comes from: the protected job comment (hidden aggregates) and the `backend` job's dev report.

### 4.10 Error handling

Not applicable (no runtime behaviour); CI scripts exit non-zero with a one-line reason per failure.

## 5. Invariants

INV-03, INV-04 (scan wiring), INV-05, INV-08 (empty contracts present), INV-17, INV-18, INV-19 are established
here. `.importlinter` initial contracts:

```
[importlinter:contract:normalize-independence]
name = One module per field type
type = independence
modules = crawlerai.normalize.money, crawlerai.normalize.enum, crawlerai.normalize.date, crawlerai.normalize.location,
          crawlerai.normalize.range, crawlerai.normalize.identifier, crawlerai.normalize.text, crawlerai.normalize.url

[importlinter:contract:normalize-libs]
name = Only normalizers import normalization libraries
type = forbidden
source_modules = crawlerai  (all packages except crawlerai.normalize)
forbidden_modules = babel, price_parser, dateparser

[importlinter:contract:adapters-isolated]
name = Nothing outside adapters imports adapters except acquire and collect
type = forbidden  (source = everything except crawlerai.acquire, crawlerai.collect; forbidden = crawlerai.adapters)

[importlinter:contract:layers]
name = Layering
type = layers
layers = crawlerai.api | crawlerai.mcp_server
         crawlerai.crawl | crawlerai.recurring | crawlerai.eval
         crawlerai.config_ir
         crawlerai.resolve | crawlerai.llm
         crawlerai.collect | crawlerai.content
         crawlerai.normalize | crawlerai.schemas
         crawlerai.acquire | crawlerai.adapters
         crawlerai.db | crawlerai.storage
         crawlerai.core
```

(The `independence` contract lists concrete modules; new types are added to it in the same PR that adds the
module.)

## 6. Testing strategy

- `tools/site_literal_scan.py` has unit tests using reserved names (`example.com`) and synthetic hosts under
  `.test`; the tests assert both detection and exemption behaviour.
- `tools/data_manifest_check.py` tests with a temp directory.
- Frontend: one Vitest smoke test rendering the shell; one test asserting the theme toggle sets `data-theme`.
- CI gates: all jobs in 4.6.

## 7. Acceptance criteria

- `git clone` → `make dev` brings up Postgres, API (`GET /healthz` 200), worker, scheduler and the frontend on a
  clean machine with Docker, uv and pnpm installed.
- `make check` passes locally and all CI jobs are green on an empty-engine repo.
- The protected workflow runs on a PR, finds its environment, uploads no artifacts, and the hidden-host
  scan prints no host names in its log (test by seeding `HIDDEN_HOSTS` with a reserved `.test` name and putting it
  in a scratch file in the PR).
- The site-literal scan fails a PR that introduces `shop.example-retailer.com` into `backend/src/crawlerai/collect/`.
- `lint-imports` fails a PR that imports `babel` from `crawlerai.collect`.
- All root files from 4.9 exist with the required content.

## 8. PR plan

| # | Title | Scope / files | Checks | Done when |
|---|---|---|---|---|
| 1 | Repo skeleton and backend toolchain | `backend/pyproject.toml`, `uv.lock`, `src/crawlerai/**/__init__.py`, `core/settings.py`, `cli.py` (`crawlerai --version`), `.gitignore`, `NOTICE` (third-party attributions; `LICENSE` already exists, AGPL-3.0) | ruff, mypy, pytest (one test) | `uv run crawlerai --version` works. |
| 2 | Postgres via compose, alembic baseline, `make dev` | `infra/*`, `alembic.ini`, `migrations/env.py` (async), empty baseline revision, `Makefile`, `.env.example` | alembic up/down in CI | `make dev` starts API `/healthz`. |
| 3 | Frontend skeleton with HeroUI v3 | `frontend/*`, Tailwind v4 + HeroUI styles, app shell, theme toggle, router, placeholder screen | lint, typecheck, vitest, build | Shell renders in light and dark. |
| 4 | OpenAPI → TS client pipeline | `crawlerai openapi`, `frontend/openapi.json`, `src/api/*`, CI freshness check | frontend job | Client types regenerate deterministically. |
| 5 | C3 site-literal scan + data manifest check | `tools/site_literal_scan.py`, allowlist, `tools/data_manifest_check.py`, `backend/data/manifest.json` (IANA TLD list entry), tests | site-literals, data-manifest jobs | Scan fails on a planted literal; passes on the repo. |
| 6 | import-linter contracts (C8) | `.importlinter`, `lint-imports` in CI | backend job | Contracts pass on the skeleton. |
| 7 | License deny-list + SBOM | `tools/license_scan.sh`, CI job | licenses job | A planted AGPL dev dependency fails the job (do it in the PR, then remove). |
| 8 | Protected eval job placeholder + hidden-host scan mode | `.github/workflows/eval-protected.yml`, scan `--hidden-hosts-from-env` | protected job | Runs under the environment; no artifacts; output is pass/fail lines only. |
| 9 | Pre-commit hooks and `make check` | `.pre-commit-config.yaml`, `Makefile` | all | Hooks run < 10 s on a one-file change. |
| 10 | Root documents | extend `README.md`; fill gaps in `CLAUDE.md`; optional one-line `AGENTS.md` pointer; `docs/INVARIANTS.md`, `docs/DESIGN.md`, `CONTRIBUTING.md`, PR template, `no-size-gates` job | all | Documents contain every item in 4.9. |

## 9. Open issues

- **LGPL policy.** The architecture's deny list is AGPL/GPL/SSPL/non-commercial. LGPL is not listed; this spec
  allows it but avoids it (asyncpg instead of psycopg). Owner to confirm.
- **Review finding (C3 scan noise).** Resolved in ARCHITECTURE rev 5 C3 (a reviewed allowlist of standards hosts,
  package registries and RFC 2606 names). The allowlist in 4.7 implements it.
- **Review finding (C8 enforcement).** Resolved in ARCHITECTURE rev 5 C8 (import-linter independence and
  forbidden-import contracts, plus review); that is what INV-08 enforces.
- **UI authentication.** Resolved in ARCHITECTURE rev 5 §18: the UI sends the API key as a bearer header held in
  memory; no cookies, no sessions, no CSRF surface (SPEC-07 4.2).
- **Project license.** Resolved in ARCHITECTURE rev 5 Appendix A #26 (OPEN_QUESTIONS #9): AGPL-3.0; `LICENSE`
  already exists.
- **`docs/INVARIANTS.md` and `docs/DESIGN.md`** are documents this spec adds beyond those listed in ARCHITECTURE's
  "Role of this document". Alternative: keep the invariant table in this spec and `CLAUDE.md`, and the frontend
  conventions in SPEC-12. Owner to confirm.
- Versions marked **[unverified]** above must be checked when the lockfiles are created.
