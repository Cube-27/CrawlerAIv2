# Implementation tracker

The live state of implementation. The orchestrator (`/run-plan`) is its only writer; a solo agent with no orchestrator updates it in its PR
(`CLAUDE.md` §3). One row
is one PR from a spec's PR plan. Spec dependencies are listed in `specs/README.md`. A row is ready when everything
it needs is available: the code it touches or builds on is merged, or what it needs from unmerged work is fully
specified (types, API shapes, table columns). Readiness is per row (owner, 2026-10-13).

**Statuses:**
- `todo`
- `done (#n)`: merged, with the PR number.
- `blocked`: the Notes link a `DECISIONS.md` entry.
- `human`: waits on a human-only task (below).

Updated: 2026-10-14.

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

- Data accuracy by failure class (UAT re-run backlog): money page currency #161 and markdown links and whitespace #162 merged. Next: learn report says why, js_state visible admission for opaque types (owner: agreed), `commerce_detail` with brand optional (owner). To investigate, not decided (owner): variants incl. availability and stock; learned config approval before it becomes a reusable recipe; D-0355 url from the final URL; an "absent" field status. Next test target after the crawler-test sites: Shopify stores (owner). Open: drift_margins.json (OQ #20 / D-0576), sites list (D-0656).
- Follow-ups from #158: job results paging cost grows with job size (the `task_record` IN-subquery builds the job's whole record set per page); measure a results page on a ~100k-task job before redesigning (paging by task id is the likely cheaper fix). A clarifying SPEC-11 §4.2 edit naming `task_record` in place of `url_task.record_id` (D-0762).
- Follow-ups from #154 review: labeling prefill of a listing schema whose fields are all page-scoped sends an empty claim object for `rows`.
- Follow-ups from #159: confirm in UAT with one real call that the configured `fast` Anthropic model accepts `output_config.effort` (D-0766); a listing row now claims every row field, so a sparse 200-row listing spends ~14 output tokens per absent field per row: measure before reshaping; Gemini's thinking is not lowered for role C (the setting could move onto the request, mapped per provider).
- Follow-ups from #153: a task still adds to `job.usage` mid-transaction (`record_usage`, role C's usage in `_visit`), which locks the job row until the task commits; recording usage at the task's end would let no later network I/O hold up a cancel. Declare `anyio` as a direct dependency (`services/events.py`, `mcp_server` import it).
- Follow-ups from #149 review: a learn job whose request cannot be parsed is re-picked by the learner; shutdown waits for a running learn run. SPEC-09 discovery, role D and recipe validation are not yet called from learning (needed with R7).
- Follow-ups from #150 review: a max_age-reused api capture can meet a config with no recipe; config_recipe parses the recipe a second time.
- Follow-up from #151 review (optional): report non-LLM errors in recipe learning as a refused recipe rather than failing the run.
- Follow-ups from #148: an installed wheel has no backend/data, so pricing is empty and every cost reads unknown (joins the D-0492 packaging item); top jobs rank a job with unknown cost by its priced part.
- Follow-up for SPEC-10 (from #144 review): wrap the MCP tools so the text of an unexpected exception is not sent to clients, as REST's `_on_unexpected` does.
- Follow-up for SPEC-08 PR 8 / SPEC-10 (from #125): pagination/rows discovery is open (D-0604).
- Follow-up for `/v1/schemas` (from #81 review, D-0395): retiring the latest version freezes the name (POST says it exists; PUT says retired or not latest). Decide between un-retiring, reusing the name, or PUT on a retired latest.
- Follow-ups from #81 (cleanup): `InvalidSchema` should reuse `eval.labels.from_pydantic` (drops pydantic's "Value error, " prefix, indexes as `a[0]`); move `SchemaContent` into `schemas/types.py` as `SchemaDocument`'s base; one shared `database` dependency for `auth`, `health` and routers; map service errors to problems at app level once more routers use services.
- Before SPEC-05's first real run: settle the GeoNames pin (D-0311, OPEN_QUESTIONS #18); the pinned daily dump stops matching, so `crawlerai data fetch` refuses.
- Workflow (owner, 2026-10-13): recurring agent mistakes become checks or skill rules (`docs/plans/RECURRING.md`, `/run-plan` §2a); orchestrator process management lives in `tools/orchestrator/` (`/run-plan` §1a).
- For SPEC-03 PR 7 or the custodian runbook (from #34): a rotation lowers hidden `n_pages`, so the next hidden gate fails `n_pages_dropped` against the pre-rotation baseline until replacements are captured or a new baseline is recorded. Promoted pages re-record their LLM responses on their first dev replay.
- Done (#100, D-0491): an unreadable recording (not an `LLMResponse`, or a cache row whose object is missing) drops the page as `ReplayFailed`.
- Follow-ups for SPEC-03 PR 9 (from #35): guard `PUT labels` against a labeler/checker race (`WHERE labels = <read>` or a version); compare labeler names casefolded, as `parse_labels` does; the `javascript:` strip should drop tab and newline characters first (WHATWG URL parsing).
- Follow-ups for SPEC-10's page-fetching handler (from #31): pass `fetch_politely` the HTTP rung for robots.txt and `acquire` for the page (a robots.txt classifies as `shell` and would trigger a browser retry); admit the browser retry through `HostLimiter`, or log that one immediate retry per fetch is accepted; check every attempt, not only the kept result, for `SLOW_DOWN`.
- Follow-ups for SPEC-03 PR 7 (from #32): run the gate (baseline lookup) before `put_run` on a push to `main`, or exclude the candidate's sha, since otherwise the candidate's own run becomes its baseline; store the unsuppressed report as the run's `metrics` (an exported aggregate makes `gate` raise `GateInputInvalid`); check out with `fetch-depth: 0`.
- Note for the owner once labels exist (from #32): the gate compares precision only (§4.8), so a required type the engine stops publishing shows up only as lower coverage, which the gate doesn't measure.
- Note (from #26): the robots snapshot is per site, but robots.txt is per scheme, host and port (RFC 9309 §2.3); a site served on both `http` and `https` or a non-default port shares one snapshot.
- Open (deferred by #100, D-0492): `VERSION` and `data/calibration.json` don't ship in the wheel, so CI and the image report `ENGINE_VERSION = unknown+cal.none`. Before the first deployment, one PR decides where `EngineData.load(data_dir)` gets its directory (package data or a settings path), ships GeoNames data and calibration with it, and makes the build write `VERSION`.
- Done: `claim_tasks` no longer claims more than `n` tasks (#24, D-0153).
- Done: SonarCloud security findings that failed the gate on `main` fixed in code (#21, D-0141, D-0142).
- Follow-up (when their queries land): indexes on `record.job_id` (SPEC-10, SPEC-07), `extraction.url_task_id`, and `capture (site_id, fetched_at)` (SPEC-08 §4.4), each added with its query.
- Follow-up (scale, not yet due): `release_expired_leases` handles all expired leases in one transaction; add a per-run batch limit if many workers die at once (#19 review). The `job_event (job_id, id)` index comes with SPEC-10's SSE query.
- Done: the C3 scan now reads schema-defined `table.column` strings as columns (#15, D-0111). Optional tightening from its review: take schema sources only from non-exempt paths, and add a `--staged` test.
- Done: markdown targets are absolute (document base URL, on a tree copy) and layout whitespace is dropped (#162, D-0774, D-0775). Follow-ups from its review: `_tidy` strips the indent of a list item's continuation lines; `markdown` deep-copies the tree twice per call (ours, then trafilatura's). Heading link text under `favor_precision` (item 1) stays: no trafilatura mode is clean; measure on dev before changing SPEC-07 §4.5's setting.
- Done: a page's stated currency (schema.org `priceCurrency`, OGP `product:price:currency`) settles a text symbol (#161, D-0773). Follow-up from its review: a replay pinning R1b. A synthetic AggregateOffer page with a role-C-only price publishes it (no Offer-rooted kept candidate makes an anchor); the real page split because it also had availability on the AggregateOffer. Pin it with a schema that has an Offer-rooted availability field.
- Done: adopting a prompt draft asks for a new name; screen tests connect by paste under one test budget (#160, D-0771, D-0772).
- Done: task failure and block reasons, `task_failed` events and `cancel_requested` in the jobs API and UI (#157, D-0745 answered (a), D-0760, D-0761). Follow-up from its review: `TruncatedText` makes every event data and Reason cell a tab stop.
- Done: UAT re-run D1, the LLM layer: role C replies bounded by the fields asked, cut replies not retried, failed calls counted on the extraction, refusals logged, hermetic settings tests (#159, F27, F29, F30, F33, D-0765 to D-0770).

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
| 3 | JSON-LD collector + schema.org map | done (#78) | Locators address each block as written, not an expanded graph; SPEC-05 §4.3 and the `collect/locator.py` comment say "expanded graph" (needs a spec clarification). |
| 4 | Microdata/RDFa Lite collector | done (#83) | Follow-up from review: in mixed-syntax scopes, an `itemprop` inside a `typeof`-only element nested in an `itemscope` item is dropped. |
| 5 | OpenGraph collector | done (#79) | |
| 6 | Ownership + intent | done (#85) | Follow-ups for PR 7: an Offer whose `itemOffered` references the Product by `@id` is the Product's parent, so `owned_by` doesn't give it the Product; a node referenced under both `isRelatedTo` and `isSimilarTo` gets `via=None` and isn't excluded. |
| 7 | Preference + atomic offers + URL-param rule + derivations | done (#90) | The initial `source_precedence.yaml` is not committed: INV-05 vs SPEC-05 (D-0444, needs-owner). Derived `canonical_link`/`final_url` values stay a separate `Derived` result until D-0355 is answered. From review: PR 9 decides whether collectors get `base_url` (with it, `absolutize` never fires). |
| 8 | Evidence buckets, calibration loader, τ, records | done (#94) | `data/calibration.json` not committed (D-0444); a missing file means every field is uncalibrated. Page-URL derivations stay `missing` (`no_provenance`) until D-0355. Follow-ups from review: a visible lone js_state/xhr value abstains with `no_bucket`; an `absolutize` value drops the preference's rejected candidates. |
| 9 | Pipeline `extract_page` + worker handler for scrape tasks + blocked/shell | done (#100) | Scrape step is `resolve.task.extract_task`; registration is SPEC-10 PR 2 (D-0485). Migration 0008 adds `extraction.diagnostics`. Precedence types decline as `unranked` until D-0444 (D-0486). Config mode and listings raise `ModeNotSupported` until SPEC-08 PR 2 / PR 12 (D-0490). |
| 10 | js_state + xhr collectors with admission rule | done (#86) | `AdmittingCollector` takes the other kinds' candidates; PR 9 runs it after them (D-0418). Follow-up from review: js_state reads only a script's first assignment, so `var n = 1; window.X = {...}` gives no document; could take the first assignment whose value is an object or array. |
| 11 | Adapter collector | done (#91) | PR 9 builds `AdapterCollector(adapter, page_kind)` for `api` captures from the bundle's `url` (D-0445). Follow-up from review: a list field mapped through a nested wildcard would become one candidate per item; no current map does this. |
| 12 | Cold listings + pagination | done (#106) | D-0509–D-0517. `next_pages` is on `ExtractionResult` for SPEC-10's frontier; scrape still refuses listing records. Follow-ups from review: a page with the same items in JSON-LD and microdata gives a row per syntax (one record only once row URLs rank, D-0444); the `T.url` path check is in both `records._row_key` and `derive.is_page_url_field`. |
| 13 | calibrate / fit-precedence logic | done (#109) | D-0531–D-0533; replaces the interim fits of D-0229. No `calibration.json` or `source_precedence.yaml` committed (D-0444, milestone M). Follow-up from review (optional): make `Chosen.kept`/`Unpublished.kept` required instead of defaulting to `()`. |

## [SPEC-06 — LLM layer: provider-agnostic client, grounding, roles C and S](../specs/SPEC-06-llm-layer.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Client protocol, request/response models, fake provider, budgets, usage | done (#69) | Usage commits in its own transaction (D-0346); replay uses `llm.client` (D-0218 retired). |
| 2 | Anthropic and Gemini providers with JSON-schema output + failover | done (#74) | Fails over once on 408/429/5xx/timeout (D-0371); Anthropic sends no temperature (D-0370). |
| 3 | Grounding alignment | done (#76) | |
| 4 | Role C detail + pipeline hook wiring | done (#107) | Bound in `config_ir.role_c` (D-0518); a failed call leaves fields `missing` with `LLMFailure.field_reason` (D-0519); missing optional fields ride along with a required gap (D-0520). |
| 5 | Role C listing + labeling pre-fill endpoint | done (#111) | D-0534–D-0538. Role C reads a listing's rows only when structured data gives none. Follow-ups from review: `max_output_tokens` 16,384 may not hold 200 rows on wide schemas (a cut reply fails as `OutputInvalid`); the pre-fill's diagnostics (truncation, ungrounded values) are not returned to the labeler. |
| 6 | Role S + prompt-hash reuse | done (#92) | `complete_json` takes an optional reply check sharing the one retry (D-0448); drafts keyed on the normalized prompt (D-0449). |
| 7 | Prices as data + estimated LLM cost (with SPEC-10 PR 10, SPEC-12 PR 11) | done (#148) | D-0719–D-0727. ARCHITECTURE rev 11 (owner). Prices in `backend/data/llm/`; client adds `tokens_in` to usage metadata. |

## [SPEC-07 — API foundation, authentication, page content formats and `scrape`](../specs/SPEC-07-api-foundation-and-scrape.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | App factory, problem details, healthz, OpenAPI export wiring | done (#70) | Also mapped an unreadable capture in `GET /v1/eval/pages/{id}` to a 500 problem (#35 follow-up). |
| 2 | API keys: CLI, hashing, bearer auth, rate limiter | done (#77) | Follow-ups in #77's READY comment: key store to `db/`, one CLI transaction helper, `Forwarded`/XFF precedence and quoted commas. |
| 3 | Content formats | done (#80) | INV-26 counts parses of the capture body; markdown keeps relative links as written (D-0399–D-0403). |
| 4 | Service layer + `POST /v1/scrape` (formats only) | done (#88) | `records` refused (422) and `max_age` not reused until PR 5 (D-0427). |
| 5 | `records` format with schema id/inline + `max_age` | done (#105) | Inline schemas stored or matched by name, 409 on a differing one; `max_age` reuses only `ok` captures; no engine data is a 503 (D-0501–D-0508). Follow-up: two concurrent first uses of one new inline name make the second a 409 (re-read on `SchemaExists`). |
| 6 | `schema.prompt` via role S | done (#96) | Drafted only from a reached page; LLM failures fail the job as problems; the API starts without provider keys (D-0466–D-0468). PR 5 passes the draft to `records`. |
| 7 | `/v1/schemas` CRUD | done (#81) | Edits name the latest version; DELETE retires one version; presets read-only (D-0394–D-0398). |
| 8 | `/v1/records`, `/v1/captures/{id}/replay` | done (#108) | Replay uses the records' schema versions, cold, and keeps what a page task stores (listing rows each); D-0469's hand shapes replaced by the generated client (D-0523–D-0526). Migration 0010: `record` indexes for the job/schema filters and replay. |

## [SPEC-08 — Config IR, executor, learning, progressive mode, drift and exporters](../specs/SPEC-08-config-ir-learning-progressive.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | IR model + validation (XPath 1.0, regex subset, css→xpath) | done (#95) | D-0460–D-0465. Follow-ups: loader re-translates or pins css→xpath across cssselect upgrades (PR 2/10); regex subset follows the PHP `/u` choice for non-ASCII and `(?i)` (PR 11). |
| 2 | Engine executor + SPEC-05 injection | done (#98) | D-0475–D-0482. Follow-up for PR 6: an absolute `//` row-field XPath escapes its row; validation must require one match per row. |
| 3 | Release executor + import contract | done (#110) | D-0527–D-0530. Follow-ups for PR 11: release JSON-LD typing ignores `@context` (errs to `manual`); listing-row step rules could move into `ListingSpec` validation. |
| 4 | Progressive state + learning trigger + `learn` job kind | done (#114) | D-0546–D-0550. Migration 0011. Follow-ups: PRs 5–7 end the run (`learning_failed`) on every failed or cancelled `learn` job, or a cold state stays `learning`; PR 6 checks that `active_config_id` matches the state's (site, schema version, page_kind). |
| 5 | Induction | done (#116) | D-0551–D-0558. Follow-up for PR 6/7: a `config:` locator does not record its step kind, so earlier `css`/`attr`/`regex`/`jsonld` steps are never induced; record the kind or pass the active IR's steps into induction. |
| 6 | Validation, corroboration, validation_report, activation | done (#118) | D-0563–D-0570. Follow-ups: PR 7/8 load held-out pages and structured/adapter references and call `learning_failed` when validation refuses; PR 10 needs its own activation entry (`activate` requires a learning run in flight). |
| 7 | Role A synthesis + repair loop | done (#122) | D-0585–D-0591. Follow-up for PR 8: wire the learn job end to end (D-0591). |
| 8 | Active-mode extraction (role C only for uncovered fields) | done (#127) | D-0614–D-0624. Follow-ups for SPEC-10 PR 2: run learn jobs from the worker; a `_start` failure leaves the job `queued` (picked on every poll); a run whose process dies or whose `_finish` raises stays `running`/`learning` until a lease or timeout exists; record drift (`active.record_page`) in the worker's page handler. |
| 9 | Drift tracking + suspension + re-learn | done (#119) | D-0571–D-0576. Migration 0012 adds `extraction_config.drift_window`. `drift_margins.json` not committed: nothing is suspended until OQ #19 / D-0576 is answered. Follow-ups for PR 8: call `observe` + `record_run` after each active-config page and load the margins with `load_margins`; measure a listing's per-page yield the way §4.7 does (an empty listing page counts row fields as misses). |
| 10 | Config API + operator corrections | done (#123) | D-0592–D-0598. `POST /v1/sites/{host}/learn` takes `{schema_id, force}` (D-0592). Follow-ups for PR 8: reuse `config_ir/held_out.py` for held-out pages (D-0597); decide whether a learning run may replace an operator's active config (D-0598). |
| 11 | Exporters json/platform_draft + release check + export endpoint | done (#124) | D-0605–D-0610. Follow-up: a clarifying edit to SPEC-08 §4.11 for the `platform_draft` shape (D-0606). |
| 12 | Record exporters (json/csv/markdown) | done (#115) | D-0544–D-0545. Follow-up for SPEC-10/12: CSV formula injection, if CSV is served as a download. |

## [SPEC-09 — API-backed pages: discovery, recipe binding (role D), validation, execution](../specs/SPEC-09-api-backed-pages.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | `ApiRecipe` model + binders + property tests | done (#102) | |
| 2 | Discovery from network bodies | done (#113) | D-0540–D-0543 |
| 3 | Header minimization + replay | done (#117) | D-0559–D-0562 |
| 4 | Held-out validation + IR integration | done (#121) | D-0581–D-0584 |
| 5 | Execution rung + `api` collector + pagination | done (#125) | D-0599–D-0604 (D-0604 supersedes D-0543). |
| 6 | Role D | done (#126) | D-0611–D-0613. Follow-up from review: the shared test `ScriptedClient` ignores its `ReplyCheck` argument. |
| 7 | PHP hint template in `platform_draft` | done (#129) | D-0625–D-0627 |

## [SPEC-10 — Async jobs, map, crawl frontier, extract, batch, SSE, webhooks and the MCP server](../specs/SPEC-10-jobs-crawl-extract-mcp.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Job summary/status/cancel/results endpoints | done (#120) | D-0577–D-0580. Follow-up from review: the INV-27 property's markdown leg compares with the exporter fed stored values; parse the table cells back. |
| 2 | `batch/scrape` + worker handler registration | done (#128) | D-0628–D-0636. Migration 0013 adds `job.pinned`. Page outputs are made from captures on read (D-0630 supersedes D-0580). Follow-ups: #31's browser retry through `HostLimiter` and `SLOW_DOWN` on every attempt (D-0634). |
| 3 | Canonicalization + sitemaps + `map` | done (#130) | D-0649–D-0655. Follow-ups from review: PR 4 decides whether `include` globs admit any host or only subdomains (D-0037) before the frontier fetches what `Scope` admits; an unexpected exception leaves a `map` job `running`, as it does a `scrape` job; `include`/`exclude` lists are unbounded. |
| 4 | Frontier, rules, `crawl` | done (#137) | D-0672–D-0678. Shared page-task steps in `worker/handlers/steps.py`; `TargetsRejected`/`check_targets` replace `BatchRejected`. Follow-ups: the start task reads sitemaps again on a transient retry (seeds deduplicate); one `TargetRejected` with an optional member, and `insert_job`/`JobPins` out of `services.batch` into a shared submit module (simplify review). |
| 5 | `extract` with globs and prompt | done (#140) | D-0681–D-0686. No migration. `batch.job_pins`/`batch.insert_tasks` shared by batch and extract. Follow-ups: lock the job row before a prompt job's tasks are inserted (a cancel during the draft); a process that dies during a draft leaves the job `running`. |
| 6 | SSE events + webhooks | done (#132) | D-0639–D-0646. Migration 0014 adds `job.api_key_id`, `webhook_delivery` and the `job_event (job_id, id)` and `extraction (url_task_id)` indexes. Follow-ups: `crawl` and `extract` (PRs 4, 5) set `job.api_key_id` from the authenticated key, as `batch/scrape` does, or their webhooks end `failed` unsent; from review, a live stream can skip an event committed out of uuid7 order (D-0646). |
| 7 | MCP server (stdio + HTTP) | done (#144) | D-0696–D-0699. `api/keys.py` moved to `services/keys.py`; runtime setup in `services/runtime.py`; `api` layered over `mcp_server`. Follow-ups: unexpected exception text reaches MCP clients (from review); each later markdown page rebuilds the capture's markdown; the worker still builds its fetching by hand beside `fetching_from_settings`. |
| 8 | Endpoint-level SSRF matrix | done (#145) | D-0705–D-0706. Tests only, plus the worker's up-front guard check of a page task's URL. Follow-up from review: run the same matrix over the MCP tools (#144). |
| 9 | `GET /v1/jobs` list | done (#146) | D-0707–D-0709. ARCHITECTURE rev 10 (D-0700). No migration. Follow-ups: one shared keyset-page helper for `list_records`, page outputs and `list_jobs`; a covering `url_task (job_id, status, outcome)` index or counters on `job` if listing large crawls is measured slow. |
| 10 | `GET /v1/usage/llm`, `GET /v1/usage/llm/jobs`, job `llm_cost_usd` | done (#148) | D-0719–D-0727. Migration 0016 adds `ix_usage_event_job_id_id`. No MCP tool. |

## [SPEC-11 — Recurring crawls: conditional GET, fingerprints, record versions, listing diff](../specs/SPEC-11-recurring-crawls.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | `url_state` helpers + conditional GET | done (#131) | |
| 2 | SimHash + content fingerprint skip | done (#135) | D-0661–D-0665. `url_task.record_id` (unchanged tasks pointing at their standing record) is deferred to PR 3 (D-0664). D-0665 (Hamming ≤ 3 lets a one-word change pass as unchanged) is needs-owner. |
| 3 | Record fingerprint + versions + `changed_since` | done (#136) | D-0666–D-0671. No migration. Follow-ups: (a) with #135, a page whose text moves > 3 bits while its required fields stay equal gets `last_changed_at` set but no new record, so `standing_record` (`created_at >= last_changed_at`) finds none and the page is re-extracted every run; an equal fingerprint also returns a record of another mode/config, which `standing_record` rejects. Fix: when the fingerprint is equal, touch the standing record or compare against the record's fingerprint in `standing_record`. (b) `url_task.record_id` (D-0664) is still not built. (c) From review: an unchanged re-scrape emits no `task.abstained` (task_events reads `Record.extraction_id`); `changed_since` on `created_at` can miss a late-committing row for non-overlapping pollers. (d) Unchanged scrapes answer with the stored record but the current mode/confidence; that capture is not replayable. (e) SPEC-11 §5 cites INV-10/INV-11 wrongly; §4.4's `url_state.record_fingerprint` wording needs a clarifying edit. |
| 4 | Listing diff + `gone_at` | done (#142) | D-0689–D-0695. Migration 0015 adds `url_state.last_seen_job_id`. SPEC-11 §4.5 clarified (D-0694). Follow-ups: `extract` jobs are not runs yet (`close_run` diffs `crawl` jobs only); a sitemap read that times out is not counted as a partial run; the start host comes from the raw request URL, not `CrawlRequest.start` (a mismatch skips the diff). |
| 5 | Drift/`pages_extracted` exclusions for unchanged pages | done (#139) | D-0679. No production change: an unchanged task ends before extraction. Follow-up: a handler that adopts the unchanged skip (`extract`, SPEC-10 PR 5; `crawl`, D-0678) must end the task before `store_page_record`, as `batch_scrape` does. From review: move the duplicated `site` fixture into `tests/db/conftest.py`. |

## [SPEC-12 — Frontend application screens](../specs/SPEC-12-frontend-application.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Connect screen + auth context + 401 handling | done (#68) | |
| 2 | Shared field components | done (#73) | |
| 3 | Scrape screen | done (#82) | |
| 4 | Schemas screens | done (#87) | |
| 5 | Records screen + inspector + replay | done (#97) | |
| 6 | Sites & configs + StepsEditor + corrections + export | done (#134) | |
| 7 | Jobs screens + EventLog (SSE) + exports | done (#143) | |
| 8 | Change feed in Records | done (#141) | |
| 9 | Labeling nav integration + shared shell polish | done (#93) | |
| 10 | Jobs table on /jobs | done (#147) | D-0700. Uses `GET /v1/jobs` (#146). |
| 11 | Settings screen with LLM usage & cost | done (#148) | D-0719, D-0725. Range presets; tables only. |

