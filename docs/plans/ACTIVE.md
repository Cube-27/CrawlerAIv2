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
| H4 | Provide LLM provider API keys (OPEN_QUESTIONS #5) as CI and runtime secrets. | SPEC-06 PR 2 | deferred (owner, 2026-10-13: not needed yet) |
| H5 | Answer the `needs-owner` entries in `DECISIONS.md`, and confirm or override the `pending-owner` entries. | As they come up | done for now (D-0234) |
| H6 (M) | Monthly: sample and label 20–30 fresh sites (OPEN_QUESTIONS #7). | After M | deferred |
| H7 | Optional: configure a proxy pool (OPEN_QUESTIONS #10). | SPEC-02 PR 7 (can be tested with a stub) | todo |

## Current focus

- Exit predicate (run-plan, extended 2026-10-13): every L0 and L1 row is `done` or `human`, and CI on `main` is green. L0 is done except SPEC-03 PR 7 (`human`).
- Next: SPEC-04 PR 2 (#47) in review, then SPEC-04 PRs 3–8 in parallel; SPEC-02 PRs 7, 8 in progress, then 9; SPEC-05 after SPEC-04.
- Before SPEC-05's first real run: settle the GeoNames pin (D-0311, OPEN_QUESTIONS #18); the pinned daily dump stops matching, so `crawlerai data fetch` refuses.
- Workflow (owner, 2026-10-13): recurring agent mistakes become checks or skill rules (`docs/plans/RECURRING.md`, `/run-plan` §2a); orchestrator process management lives in `tools/orchestrator/` (`/run-plan` §1a).
- For SPEC-03 PR 7 or the custodian runbook (from #34): a rotation lowers hidden `n_pages`, so the next hidden gate fails `n_pages_dropped` against the pre-rotation baseline until replacements are captured or a new baseline is recorded. Promoted pages re-record their LLM responses on their first dev replay.
- Follow-ups from #33: decide whether unreadable recordings (`LLMResponse` validation, a cache row whose object is missing) drop the page as `ReplayFailed` or stop the run, and write it down (SPEC-05 PR that wires the engine).
- Follow-ups for SPEC-03 PR 9 (from #35): guard `PUT labels` against a labeler/checker race (`WHERE labels = <read>` or a version); compare labeler names casefolded, as `parse_labels` does; the `javascript:` strip should drop tab and newline characters first (WHATWG URL parsing).
- Follow-ups for SPEC-10's page-fetching handler (from #31): pass `fetch_politely` the HTTP rung for robots.txt and `acquire` for the page (a robots.txt classifies as `shell` and would trigger a browser retry); admit the browser retry through `HostLimiter`, or log that one immediate retry per fetch is accepted; check every attempt, not only the kept result, for `SLOW_DOWN`.
- Follow-ups for SPEC-03 PR 7 (from #32): run the gate (baseline lookup) before `put_run` on a push to `main`, or exclude the candidate's sha, since otherwise the candidate's own run becomes its baseline; store the unsuppressed report as the run's `metrics` (an exported aggregate makes `gate` raise `GateInputInvalid`); check out with `fetch-depth: 0`.
- Note for the owner once labels exist (from #32): the gate compares precision only (§4.8), so a required type the engine stops publishing shows up only as lower coverage, which the gate doesn't measure.
- Note (from #26): the robots snapshot is per site, but robots.txt is per scheme, host and port (RFC 9309 §2.3); a site served on both `http` and `https` or a non-default port shares one snapshot.
- Open (SPEC-04 PR 7 / SPEC-05): `VERSION` and `data/calibration.json` don't ship in the wheel, so CI and the image report `ENGINE_VERSION = unknown+cal.none`. Decide how runtime data ships (package data or a settings path) together with GeoNames data and calibration; the build must write `VERSION`.
- For SPEC-06 PR 4 (from #69): the LLM client commits usage on its own connection (D-0346), so a handler must not hold an uncommitted write to the job row when it calls the client.
- Done: `claim_tasks` no longer claims more than `n` tasks (#24, D-0153).
- Done: SonarCloud security findings that failed the gate on `main` fixed in code (#21, D-0141, D-0142).
- Follow-up (when their queries land): indexes on `record.job_id` (SPEC-10, SPEC-07), `extraction.url_task_id`, and `capture (site_id, fetched_at)` (SPEC-08 §4.4), each added with its query.
- Follow-up (scale, not yet due): `release_expired_leases` handles all expired leases in one transaction; add a per-run batch limit if many workers die at once (#19 review). The `job_event (job_id, id)` index comes with SPEC-10's SSE query.
- Done: the C3 scan now reads schema-defined `table.column` strings as columns (#15, D-0111). Optional tightening from its review: take schema sources only from non-exempt paths, and add a `--staged` test.
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
| 9 | Pre-commit hooks and `make check` | done (#12) | Windows eslint hook timing: D-0110, resolved by D-0227. |
| 10 | Root documents | done (#10) | |

## [SPEC-01 — Persistence, job queue and capture storage](../specs/SPEC-01-persistence-queue-storage.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Core tables: project, api_key, site, schema_def | done (#11) | |
| 2 | Job, url_task, job_event tables and state machine | done (#14) | |
| 3 | Queue claim/lease/retry + worker loop skeleton | done (#17) | Adds `url_task` UNIQUE (`job_id`, `canonical_url`) (migration 0004). |
| 4 | Scheduler loop + lease release | done (#19) | Also closed #17's follow-ups (D-0132–D-0135). |
| 5 | Object store (fs, s3) + capture bundle format | done (#13) | |
| 6 | capture, extraction, candidate, record, url_state, progressive_state, extraction_config tables | done (#20) | Migration 0005. |
| 7 | usage_event + budgets + engine_version | done (#23) | Migration 0006; also renamed the double-prefixed CHECKs. |
| 8 | Retention jobs | done (#25) | Bounded batches (D-0155). SPEC-01 complete. |

## [SPEC-02 — Acquisition: HTTP, browser, adapters, politeness, SSRF, captures](../specs/SPEC-02-acquisition.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Acquisition types, classify, SSRF guard | done (#16) | Ran ahead of SPEC-01 PRs 3–8; it needs no SPEC-01 table. |
| 2 | HTTP fetch (curl_cffi) with manual redirects and caps | done (#18) | |
| 3 | Persist capture + `crawlerai fetch` CLI | done (#22) | Also closed #18's follow-ups. |
| 4 | Politeness + robots + backoff via requeue | done (#26) | Also closed #23's follow-ups. |
| 5 | Rung selection + fetch_method memory + re-check scheduler task | done (#31) | SPEC-02 L0 rows complete. |
| 6 | Patchright browser rung with network capture | done (#46) | SSRF guard is a per-fetch SOCKS5 proxy (D-0249). Optional follow-ups: cap `json_responses` at append time; keep the first hop's exchange when the guard rejects a later redirect. |
| 7 | Proxy pools | done (#53) | Follow-up: record `proxy_bytes` and `http_requests` usage per attempt once the worker writes usage events. |
| 8 | Adapter protocol + Greenhouse | done (#52) | Follow-ups: proxy support in `fetch_json` and a per-adapter settings flag, once PR 7 merges. |
| 9 | Lever adapter | done (#62) | |
| 10 | Tests named for INV-29 and INV-30 (cookies stay inside one fetch; oversize bodies are errors) | done (#64) | Fixed JSON-fetch cookie matching and the browser's `max_body_bytes` (D-0320, D-0321). Follow-ups: CDP streaming for the browser's memory bound; public-suffix data for `Domain=` cookies. |

## [SPEC-03 — Evaluation and measurement](../specs/SPEC-03-evaluation-and-measurement.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Private database, roles, `EvalStore` protocol + both stores | done (#28) | Private chain `p0001`; agents never hold custodian credentials (D-0178). |
| 2 | Label model + validation + equality | done (#27) | `equal` hooks are exact-equality stubs until SPEC-04 PR 9. |
| 3 | `eval capture` and `import-sites` CLI | done (#30) | Obeys robots.txt and per-host spacing (D-0195). |
| 4 | Replay harness + RecordedLLM + determinism test | done (#33) | Interim LLM/engine protocols until SPEC-05/06 (D-0218). |
| 5 | Metrics + aggregate report + min-cell suppression | done (#29) | Secondary suppression: D-0187 (needs-owner, not blocking). |
| 6 | Gate + baseline lookup | done (#32) | |
| 7 | Protected job wired (replace placeholder) + dev report in `backend` job | human (H1, H2) | Needs the private eval credentials and the protected environment; changes the protected job (CLAUDE.md §4). Follow-ups from #32 below. |
| 8 | Labeling API | done (#35) | Dev split only (D-0207); hidden/fresh labeling at M is D-0214. |
| 9 | Labeling screen | done (#42) | Save-path follow-up fixed in #44. |
| 10 | Promote/rotate commands | done (#34) | `rotate_hidden` skips hosts that also have fresh pages (#37, D-0225). |
| 11 | `calibrate` / `fit-precedence` entry points (write files; logic lands in SPEC-05) | done (#39) | Interim fits until SPEC-05 PR 13 (D-0229). |
| 12 | Complementary suppression for hidden/fresh aggregates | done (#44) | Groups include `by_category`/`acquisition` and `usage` (D-0246). |

## [SPEC-04 — Schemas as data and type normalization](../specs/SPEC-04-schemas-and-normalization.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Schema models, registry, presets, sync | done (#43) | C3 `schema_org` exemption tightened in #48 (D-0248). |
| 2 | Normalizer base, dispatcher, text, url | done (#47) | |
| 3 | money (CLDR via Babel + price-parser) | done (#58) | |
| 4 | enum + vocab framework + availability `en` | done (#54) | Follow-up for SPEC-05 or a preset bump: `commerce_detail` availability is `schema:ItemAvailability`, so DOM availability text won't normalize unless the field also reads `type:availability`. |
| 5 | date/datetime | done (#57) | |
| 6 | identifier | done (#59) | |
| 7 | Data manifest + GeoNames fetch + location | done (#60) | |
| 8 | range | done (#56) | |
| 9 | `equal` per type + list/object recursion | done (#66) | Also closed the follow-ups of rows 5 and 8, #47 and #27 (D-0322–D-0329). Optional follow-ups: period words count only in the page's languages; move range's `to` separator into `vocab/`. |

## [SPEC-05 — Structured extraction, ownership, resolution and confidence](../specs/SPEC-05-extraction-and-resolution.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Cleaned text + visible index | done (#67) | |
| 2 | Candidate/Entity/Outcome models, locator format | done (#72) | |
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
| 1 | Client protocol, request/response models, fake provider, budgets, usage | done (#69) | Usage commits in its own transaction (D-0346); replay uses `llm.client` (D-0218 retired). |
| 2 | Anthropic and Gemini providers with JSON-schema output + failover | todo | |
| 3 | Grounding alignment | todo | |
| 4 | Role C detail + pipeline hook wiring | todo | |
| 5 | Role C listing + labeling pre-fill endpoint | todo | |
| 6 | Role S + prompt-hash reuse | todo | |

## [SPEC-07 — API foundation, authentication, page content formats and `scrape`](../specs/SPEC-07-api-foundation-and-scrape.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | App factory, problem details, healthz, OpenAPI export wiring | done (#70) | Also mapped an unreadable capture in `GET /v1/eval/pages/{id}` to a 500 problem (#35 follow-up). |
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
| 1 | Connect screen + auth context + 401 handling | done (#68) | |
| 2 | Shared field components | done (#73) | |
| 3 | Scrape screen | todo | |
| 4 | Schemas screens | todo | |
| 5 | Records screen + inspector + replay | todo | |
| 6 | Sites & configs + StepsEditor + corrections + export | todo | |
| 7 | Jobs screens + EventLog (SSE) + exports | todo | |
| 8 | Change feed in Records | todo | |
| 9 | Labeling nav integration + shared shell polish | todo | |

