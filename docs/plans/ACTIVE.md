# Implementation tracker

The live state of implementation. The orchestrator (`/run-plan`) is its only writer; a solo agent with no orchestrator updates it in its PR
(`CLAUDE.md` §3). One row
is one PR from a spec's PR plan. Spec dependencies are listed in `specs/README.md`. A row can start once every row
it depends on is `done`. Within a spec, rows run in order unless the spec says otherwise.

**Statuses:**
- `todo`
- `done (#n)`: merged, with the PR number.
- `blocked`: the Notes link a `DECISIONS.md` entry.
- `human`: waits on a human-only task (below).

Updated: 2026-10-12.

## Human-only tasks

Agents can't do these. Rows that depend on them are marked `human` until they're finished. Tasks marked
**M** belong to milestone M (ARCHITECTURE §21). Labeling is deferred until the crawler works, so they block no row:
the protected eval job stays a `no_baseline` placeholder, and tests run against local throwaway databases.

| # | Task | Needed by | Status |
|---|---|---|---|
| H1 (M) | Choose the custodian(s) of the hidden and fresh sets (OPEN_QUESTIONS #6). Create the private eval database role and credentials, and store them only in the protected GitHub environment. | Milestone M (CI uses throwaway credentials before then) | deferred |
| H2 (M) | Create the GitHub protected environment for the eval job, with required reviewers and the secret hidden-host list. GitHub auto-created `eval-protected` on the first run with no protection rules, so add the custodians as required reviewers and set the secrets. | Milestone M (the placeholder job runs without it) | deferred |
| H3 (M) | Label dev from a review of crawler output, then draw and label hidden from sites development never touched (§21 rule). | Milestone M | deferred |
| H4 | Provide LLM provider API keys (OPEN_QUESTIONS #5) as CI and runtime secrets. | SPEC-06 PR 2 | todo |
| H5 | Answer the `needs-owner` entries in `DECISIONS.md`, and confirm or override the `pending-owner` entries. | As they come up | todo |
| H6 (M) | Monthly: sample and label 20–30 fresh sites (OPEN_QUESTIONS #7). | After M | deferred |
| H7 | Optional: configure a proxy pool (OPEN_QUESTIONS #10). | SPEC-02 PR 7 (can be tested with a stub) | todo |

## Current focus

- Exit predicate (run-plan, 2026-10-12): every L0 row (SPEC-00, SPEC-01, SPEC-02 PRs 1–5, SPEC-03) is `done`, and CI on `main` is green.
- Next: SPEC-01 PR 3 (in progress); SPEC-02 PR 2; then SPEC-01 PR 4/6/7.
- Done: the C3 scan now reads schema-defined `table.column` strings as columns (#15, D-0111). Optional tightening from its review: take schema sources only from non-exempt paths, and add a `--staged` test.
- Follow-up: `url_task` UNIQUE (`job_id`, `canonical_url`) is needed by SPEC-10 §4 but not listed in SPEC-01 §4.2; SPEC-01 PR 3 or SPEC-10 adds it. Indexes on `url_task.job_id` and `job_event (job_id, id)` come with the rows that add those queries (SPEC-01 PR 3, SPEC-10), each justified by its query.
- Blocked: none.

## [SPEC-00 — Project setup and engineering foundations](../specs/SPEC-00-project-setup.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Repo skeleton and backend toolchain | done (#1) | Includes the CI backend job (owner request). |
| 2 | Postgres via compose, alembic baseline, `make dev` | done (#3) | Also adds the minimal `/healthz` app and `infra/Dockerfile`. |
| 3 | Frontend skeleton with HeroUI v3 | done (#4) | Follow-ups: theme should track live OS changes (SPEC-12); fix SPEC-00 §4.3's HeroUI licence and version in PR 10. |
| 4 | OpenAPI → TS client pipeline | done (#9) | |
| 5 | C3 site-literal scan + data manifest check | done (#5) | |
| 6 | import-linter contracts (C8) | done (#6) | |
| 7 | License deny-list + SBOM | done (#7) | |
| 8 | Protected eval job placeholder + hidden-host scan mode | done (#8) | |
| 9 | Pre-commit hooks and `make check` | done (#12) | Windows eslint hook timing: D-0110 (needs-owner, not blocking). |
| 10 | Root documents | done (#10) | |

## [SPEC-01 — Persistence, job queue and capture storage](../specs/SPEC-01-persistence-queue-storage.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Core tables: project, api_key, site, schema_def | done (#11) | |
| 2 | Job, url_task, job_event tables and state machine | done (#14) | |
| 3 | Queue claim/lease/retry + worker loop skeleton | todo | |
| 4 | Scheduler loop + lease release | todo | |
| 5 | Object store (fs, s3) + capture bundle format | done (#13) | |
| 6 | capture, extraction, candidate, record, url_state, progressive_state, extraction_config tables | todo | |
| 7 | usage_event + budgets + engine_version | todo | |
| 8 | Retention jobs | todo | |

## [SPEC-02 — Acquisition: HTTP, browser, adapters, politeness, SSRF, captures](../specs/SPEC-02-acquisition.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Acquisition types, classify, SSRF guard | done (#16) | Ran ahead of SPEC-01 PRs 3–8; it needs no SPEC-01 table. |
| 2 | HTTP fetch (curl_cffi) with manual redirects and caps | todo | |
| 3 | Persist capture + `crawlerai fetch` CLI | todo | |
| 4 | Politeness + robots + backoff via requeue | todo | |
| 5 | Rung selection + fetch_method memory + re-check scheduler task | todo | |
| 6 | Patchright browser rung with network capture | todo | |
| 7 | Proxy pools | todo | |
| 8 | Adapter protocol + Greenhouse | todo | |
| 9 | Lever adapter | todo | |

## [SPEC-03 — Evaluation and measurement](../specs/SPEC-03-evaluation-and-measurement.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Private database, roles, `EvalStore` protocol + both stores | todo | |
| 2 | Label model + validation + equality | todo | |
| 3 | `eval capture` and `import-sites` CLI | todo | |
| 4 | Replay harness + RecordedLLM + determinism test | todo | |
| 5 | Metrics + aggregate report + min-cell suppression | todo | |
| 6 | Gate + baseline lookup | todo | |
| 7 | Protected job wired (replace placeholder) + dev report in `backend` job | todo | |
| 8 | Labeling API | todo | |
| 9 | Labeling screen | todo | |
| 10 | Promote/rotate commands | todo | |
| 11 | `calibrate` / `fit-precedence` entry points (write files; logic lands in SPEC-05) | todo | |

## [SPEC-04 — Schemas as data and type normalization](../specs/SPEC-04-schemas-and-normalization.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Schema models, registry, presets, sync | todo | |
| 2 | Normalizer base, dispatcher, text, url | todo | |
| 3 | money (CLDR via Babel + price-parser) | todo | |
| 4 | enum + vocab framework + availability `en` | todo | |
| 5 | date/datetime | todo | |
| 6 | identifier | todo | |
| 7 | Data manifest + GeoNames fetch + location | todo | |
| 8 | range | todo | |
| 9 | `equal` per type + list/object recursion | todo | |

## [SPEC-05 — Structured extraction, ownership, resolution and confidence](../specs/SPEC-05-extraction-and-resolution.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Cleaned text + visible index | todo | |
| 2 | Candidate/Entity/Outcome models, locator format | todo | |
| 3 | JSON-LD collector + schema.org map | todo | |
| 4 | Microdata/RDFa Lite collector | todo | |
| 5 | OpenGraph collector | todo | |
| 6 | Ownership + intent | todo | |
| 7 | Preference + atomic offers + URL-param rule + derivations | todo | |
| 8 | Evidence buckets, calibration loader, τ, records | todo | |
| 9 | Pipeline `extract_page` + worker handler for scrape tasks + blocked/shell | todo | |
| 10 | js_state + xhr collectors with admission rule | todo | |
| 11 | Adapter collector | todo | |
| 12 | Cold listings + pagination | todo | |
| 13 | calibrate / fit-precedence logic | todo | |

## [SPEC-06 — LLM layer: provider-agnostic client, grounding, roles C and S](../specs/SPEC-06-llm-layer.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Client protocol, request/response models, fake provider, budgets, usage | todo | |
| 2 | Anthropic and Gemini providers with JSON-schema output + failover | todo | |
| 3 | Grounding alignment | todo | |
| 4 | Role C detail + pipeline hook wiring | todo | |
| 5 | Role C listing + labeling pre-fill endpoint | todo | |
| 6 | Role S + prompt-hash reuse | todo | |

## [SPEC-07 — API foundation, authentication, page content formats and `scrape`](../specs/SPEC-07-api-foundation-and-scrape.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | App factory, problem details, healthz, OpenAPI export wiring | todo | |
| 2 | API keys: CLI, hashing, bearer auth, rate limiter | todo | |
| 3 | Content formats | todo | |
| 4 | Service layer + `POST /v1/scrape` (formats only) | todo | |
| 5 | `records` format with schema id/inline + `max_age` | todo | |
| 6 | `schema.prompt` via role S | todo | |
| 7 | `/v1/schemas` CRUD | todo | |
| 8 | `/v1/records`, `/v1/captures/{id}/replay` | todo | |

## [SPEC-08 — Config IR, executor, learning, progressive mode, drift and exporters](../specs/SPEC-08-config-ir-learning-progressive.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | IR model + validation (XPath 1.0, regex subset, css→xpath) | todo | |
| 2 | Engine executor + SPEC-05 injection | todo | |
| 3 | Release executor + import contract | todo | |
| 4 | Progressive state + learning trigger + `learn` job kind | todo | |
| 5 | Induction | todo | |
| 6 | Validation, corroboration, validation_report, activation | todo | |
| 7 | Role A synthesis + repair loop | todo | |
| 8 | Active-mode extraction (role C only for uncovered fields) | todo | |
| 9 | Drift tracking + suspension + re-learn | todo | |
| 10 | Config API + operator corrections | todo | |
| 11 | Exporters json/platform_draft + release check + export endpoint | todo | |
| 12 | Record exporters (json/csv/markdown) | todo | |

## [SPEC-09 — API-backed pages: discovery, recipe binding (role D), validation, execution](../specs/SPEC-09-api-backed-pages.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | `ApiRecipe` model + binders + property tests | todo | |
| 2 | Discovery from network bodies | todo | |
| 3 | Header minimization + replay | todo | |
| 4 | Held-out validation + IR integration | todo | |
| 5 | Execution rung + `api` collector + pagination | todo | |
| 6 | Role D | todo | |
| 7 | PHP hint template in `platform_draft` | todo | |

## [SPEC-10 — Async jobs, map, crawl frontier, extract, batch, SSE, webhooks and the MCP server](../specs/SPEC-10-jobs-crawl-extract-mcp.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Job summary/status/cancel/results endpoints | todo | |
| 2 | `batch/scrape` + worker handler registration | todo | |
| 3 | Canonicalization + sitemaps + `map` | todo | |
| 4 | Frontier, rules, `crawl` | todo | |
| 5 | `extract` with globs and prompt | todo | |
| 6 | SSE events + webhooks | todo | |
| 7 | MCP server (stdio + HTTP) | todo | |
| 8 | Endpoint-level SSRF matrix | todo | |

## [SPEC-11 — Recurring crawls: conditional GET, fingerprints, record versions, listing diff](../specs/SPEC-11-recurring-crawls.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | `url_state` helpers + conditional GET | todo | |
| 2 | SimHash + content fingerprint skip | todo | |
| 3 | Record fingerprint + versions + `changed_since` | todo | |
| 4 | Listing diff + `gone_at` | todo | |
| 5 | Drift/`pages_extracted` exclusions for unchanged pages | todo | |

## [SPEC-12 — Frontend application screens](../specs/SPEC-12-frontend-application.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Connect screen + auth context + 401 handling | todo | |
| 2 | Shared field components | todo | |
| 3 | Scrape screen | todo | |
| 4 | Schemas screens | todo | |
| 5 | Records screen + inspector + replay | todo | |
| 6 | Sites & configs + StepsEditor + corrections + export | todo | |
| 7 | Jobs screens + EventLog (SSE) + exports | todo | |
| 8 | Change feed in Records | todo | |
| 9 | Labeling nav integration + shared shell polish | todo | |

