# SPEC-07 decisions

Decisions for [SPEC-07 — API foundation, authentication, page content formats and `scrape`](../specs/SPEC-07-api-foundation-and-scrape.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0361 — `create_app` keeps `eval_ui` and reads settings at startup
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `create_app(eval_ui=None)`; the app lifespan reads `DatabaseSettings()` and creates the one engine the routers share (`app.state.database`).
- Alternatives: `create_app(settings)` as SPEC-07 §4.1 sketches.
- Why: `crawlerai openapi` and uvicorn's `--factory` build the app without a database or object store configured.
- Reversible: yes

### D-0362 — Problem `instance` is the request path; no request-id middleware yet
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `Problem.instance` is the request path (RFC 9457 §3.1.5).
- Alternatives: A per-request id (`urn:uuid:…`) and an `X-Request-ID` header.
- Why: Nothing logs or reads a request id yet. When logging lands, switch `instance` to the request id (#70 review).
- Reversible: yes

### D-0363 — Unreadable capture of a labeling page is 500 `capture_unreadable`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `ObjectNotFound`/`CorruptBundle` from `get_bundle` in `GET /v1/eval/pages/{id}` answer 500 with type `capture_unreadable`.
- Alternatives: 404 `not_found`; the generic 500 problem.
- Why: The page exists; a missing or damaged stored object is the server's fault, and a distinct type tells the labeling screen why.
- Reversible: yes

### D-0364 — Problems for framework errors
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: Unknown path → `not_found`; other HTTP errors and unexpected exceptions → `about:blank` with the status phrase (RFC 9457 §4.2.1), message withheld on 500; `/healthz` without a database → 503 `unavailable`. These extend SPEC-07 §4.3's types for statuses it doesn't name.
- Alternatives: FastAPI's default bodies.
- Why: Every error the API answers is one shape the client reads.
- Reversible: yes

### D-0365 — `/healthz` reports `eval_ui`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `GET /healthz` answers `{"status":"ok","eval_ui":bool}` after a `SELECT 1` bounded at 5 s; `eval_ui` is the plumbing field SPEC-12 §4.3 (D-0042) reads for its labeling nav.
- Alternatives: A separate endpoint for the flag.
- Why: One unauthenticated call tells the UI the API is up and which screens to show.
- Reversible: yes

### D-0366 — 422 problem declared per router; supersedes D-0210
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: Routers that take input declare `responses={422: PROBLEM_RESPONSE}` (the eval router does), replacing FastAPI's `HTTPValidationError` in OpenAPI; `/healthz`, which takes no input, declares none. The OpenAPI document is served at `/v1/openapi.json` (SPEC-07 §4.6). D-0210 (problems local until SPEC-07) is superseded.
- Alternatives: One app-level `responses={422: …}`, which also documents a 422 on `/healthz`.
- Why: The document should list only errors an operation can return.
- Reversible: yes

### D-0380 — Keyless requests are rate limited by client address
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 2 (#77) · Status: decided
- Decision: A request without a bearer key is rate limited by client address (trusted-proxy aware); with one, by `sha256(key)[:16]` as specified. Only authenticated routes are limited; `/healthz` and the eval API are not.
- Alternatives: limit only keyed requests; a per-address bucket on every request in addition to the per-key one.
- Why: keyless requests cannot be sent without limit, and INV-32's client address has a use; the second bucket would add a limit the spec doesn't define.
- Reversible: yes

### D-0381 — Trusted proxies and how forwarded hops are read
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 2 (#77) · Status: decided
- Decision: `CRAWLERAI_TRUSTED_PROXIES` is a JSON list of addresses or networks, empty by default. Hops are read right to left through trusted proxies; the first untrusted hop is the client; an unreadable hop (`unknown`, an obfuscated id, garbage) stops the walk at the last readable address. `Forwarded` is preferred to `X-Forwarded-For`.
- Alternatives: leftmost hop (client-controlled); a header-specific hop count.
- Why: RFC 7239 §8.1; the most conservative reading.
- Reversible: yes

### D-0382 — `apikey` CLI output and repeated revocation
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 2 (#77) · Status: decided
- Decision: `apikey create` prints JSON `{id, label, key}`; `apikey revoke` prints `{id, revoked}` (`false` when already revoked, keeping the first `revoked_at`) and exits 2 for an unknown id. The webhook secret is 32 random bytes in hex, drawn at creation and not printed.
- Alternatives: print the webhook secret too; reset `revoked_at` on a second revoke.
- Why: SPEC-10 owns how webhook secrets reach clients; revocation time is an audit fact.
- Reversible: yes

### D-0394 — `PUT /v1/schemas/{id}` must name the latest version
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: The body is the whole new document without name and version (`SchemaContent`). It becomes version latest+1 with `origin=user`, and the answer is 200 with the new row. If `{id}` is not the latest version, or is retired, the answer is 409 `conflict`, and the detail names the latest version's id. A concurrent insert of the same version is also 409. The registry's `new_version` takes `base_version` and raises `NotLatest`.
- Alternatives: Build silently on whatever is latest; PATCH-style partial changes.
- Why: An edit made to an old version would otherwise drop the versions added since without anyone noticing. PUT replaces the whole document (RFC 9110 §9.3.4).
- Reversible: yes

### D-0395 — `DELETE /v1/schemas/{id}` retires that one version
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: The answer is 204, and a repeated DELETE is also 204. Other versions keep their status. `PUT` doesn't retire the version it builds on. Retiring the latest version freezes the name; that is a follow-up (ACTIVE, from the #81 review).
- Alternatives: Retire every version of the name; retire the previous version on PUT.
- Why: The id names a version, and records and configs reference versions (§5.2, D-0029, D-0243).
- Reversible: yes

### D-0396 — Presets are read-only through the API
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: PUT or DELETE on an `origin=preset` row, and POST with a name from the preset files, answer 409 `conflict`.
- Alternatives: Allow both.
- Why: A `user` version under a preset's name would make the next `crawlerai schemas sync` raise `PresetConflict` (D-0242). Presets change only through their files (§5.3).
- Reversible: yes

### D-0397 — Problem type `conflict` (409)
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: Added to SPEC-07 §4.3's types for a name that is taken, a stale edit, or a change to a preset or retired schema.
- Alternatives: 422 `validation`.
- Why: The request is valid, but the stored state doesn't allow it (RFC 9110 §15.5.10). This extends §4.3 the way D-0364 did.
- Reversible: yes

### D-0398 — `crawlerai.services` is its own layer under `api | mcp_server`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: Added to the layering contract and to the forbidden-import source lists. Input models (`NewSchema`, `SchemaContent`) live in the service, so REST and MCP share them. `GET /v1/schemas` answers `{items: [...]}` sorted by name then version, with optional `name` and `status` filters. POST answers 201 with `Location`.
- Alternatives: Services beside `crawl | eval`; input models in `api.dto`.
- Why: SPEC-07 §4.7 says REST and MCP call the same functions.
- Reversible: yes

### D-0399 — INV-26's count for the content formats counts parses of the capture body
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: trafilatura's readability fallback parses readability's own summary, a new document with only the main content, and that parse is not counted. The test tells the two apart by a `<head>` JSON-LD block that readability's output never contains.
- Alternatives: `fast=True`, which skips the fallback and changes the extraction §4.5 specifies; counting every lxml construction, which this fallback always fails.
- Why: INV-26 is about the capture body. A mutation check shows the test catches a re-parse of the body.
- Reversible: yes

### D-0400 — `normalize.url.canonical` and `canonical_url` are public
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: `canonical(raw, base)` is public, and `canonical_url(raw, base) -> str | None` wraps it for callers outside a field. The content formats (`links`, `content.dom`, `metadata.canonical`) call it directly, not through the dispatcher.
- Alternatives: `dispatch.normalize` with a synthetic `FieldSpec(url)` and a `Context` (it needs a `captured_at` the formats don't have); a copy of the URL rules in `content` (C8).
- Why: A link is not a field value, and one module owns the URL rules (C8).
- Reversible: yes

### D-0401 — The `html` format cleans a clone of the selectolax tree
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: `LexborHTMLParser.clone()` (a copy, no parse), serialized by lexbor. Every attribute whose value parses as a `javascript:` URL is removed, whatever its name; comments stay. The eval sanitizer uses the same `content.html.remove_scripting_attributes`.
- Alternatives: A deep copy of the lxml tree (libxml2's HTML4-era tree building); a fixed list of URL attributes.
- Why: The shared tree stays as parsed (INV-26), lexbor follows the HTML standard, and one function serves both sanitizers.
- Reversible: yes

### D-0402 — `metadata` member rules
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: `og` reads `meta[property]`, else `meta[name]`, and the first value of each key wins. `structured_data_types` lists the JSON-LD `@type` values, then the microdata `itemtype` tokens; an IRI is reduced to its last path segment or fragment, and a JSON-LD term is kept as written. `@type` inside `@context` and on value objects is not a node type. A JSON-LD block that doesn't parse is skipped. `language` is the stripped `<html lang>`, else `og:locale` as written. Absent members are `None` or empty.
- Alternatives: OGP `property` only; full type IRIs; expanding JSON-LD contexts.
- Why: `name` is read the way SPEC-05 §4.2's `meta:` locator reads it; the reduced names match §4.4's example; resolving a context is the JSON-LD collector's job (SPEC-05).
- Reversible: yes

### D-0403 — `markdown` is `""` when there is no main content
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: trafilatura finding nothing gives `""`, not `None`.
- Alternatives: `None`.
- Why: The §4.4 response shape gives `markdown` as a string.
- Reversible: yes

### D-0423 — Scrape formats only for a reached page
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: Formats are returned only when `block_class` is ok (outcome `extracted`); a blocked, shell, not_found or failed page answers 200 with its outcome and no format members.
- Alternatives: Return the formats of whatever body came back.
- Why: §4.8: no partial formats on failure; a block page's markdown would read as content.
- Reversible: yes

### D-0424 — Without `records` a reached page is `extracted`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: A scrape without `records` whose page was reached has outcome `extracted`.
- Alternatives: `links_only` (not in §4.4's outcome list).
- Why: §4.4 lists the outcomes a scrape returns; PR 5 adds `partial`.
- Reversible: yes

### D-0425 — A page robots.txt keeps from a scrape is `blocked`, without fetch members
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: A robots.txt disallow, or an unreachable robots.txt (RFC 9309 §2.3.1.4), gives outcome `blocked` (task `last_error` `robots` / `robots_unreachable`), and the answer's `capture_id`, `final_url`, `fetched_at` and `fetch` are `null`. The scrape screen hides them when null.
- Alternatives: A problem response; synthetic fetch members.
- Why: §4.8: a page not fetched is an outcome; these four are the only nullable additions to §4.4's shape.
- Reversible: yes

### D-0426 — Every SSRF rejection is a 422 `ssrf_rejected` problem
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: Any SSRF rejection, DNS failure included, is a 422 problem `ssrf_rejected` with the guard's reason as `detail`. A refused target is checked before the job is created; a refused redirect hop fails the job and stores no capture.
- Alternatives: 400; DNS failure as outcome `failed`.
- Why: INV-16; the guard fails closed, and one rule is simpler.
- Reversible: yes

### D-0427 — `records` refused until SPEC-07 PR 5; `max_age` accepted
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: `records` is refused with 422 until PR 5. `max_age` is accepted and every scrape fetches anew. `budget.llm_calls` defaults to 10 (§4.4's example).
- Alternatives: Accept `records` and ignore it; 501.
- Why: Never answer as though records were extracted; the frontend sends `max_age` when set.
- Reversible: yes

### D-0428 — The scrape service takes the engine and commits in steps
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: `services.scrape.scrape(engine, fetching, request)`, not a session: the job and its claimed task commit first, the fetch runs outside any transaction, and its results commit in one transaction; formats are computed before that write. The site's rate is awaited in place within `timeout_s`. Scrape jobs and new sites belong to the `default` project; `api_key` is not passed (no column records it).
- Alternatives: One transaction (§4.7's sketch); postpone like a worker.
- Why: A timed-out scrape must still fail its job (§4.4 step 4); a slow page holds no connection or row lock; the caller waits anyway.
- Reversible: yes

### D-0429 — The API's browser rung launches Chromium per fetch
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: In the API process the browser rung opens a browser for each browser fetch.
- Alternatives: One browser per API process (SPEC-02 §4.8 says so for workers).
- Why: The browser is used only on evidence (ARCHITECTURE §7.1); an API process should not hold one it rarely uses. Revisit if measured.
- Reversible: yes

### D-0430 — Scrape usage per fetch attempt
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: `http_requests` +1 per `http`/`api` attempt, robots.txt included; `browser_seconds` = ceil(attempt duration) per browser attempt (SPEC-02 §4.7, §4.8). The answer's `usage` is read back from `job.usage`.
- Alternatives: Count the page fetch only.
- Why: Every request made is visible.
- Reversible: yes

### D-0431 — Format members are omitted, never null
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: A format's member is left out when not requested (`exclude_if`) and the OpenAPI document gives it no null branch (`markdown?: string`); `PageMetadata` members are all required in the document. `POST /v1/scrape` is generated into the frontend client; records and the draft schema stay hand-narrowed until PRs 5 and 6, and the form's request is sent as the generated type (openapi-typescript marks defaulted members required).
- Alternatives: `string | null`; keep the module augmentation.
- Why: Matches §4.4 and the shapes #82 was built against.
- Reversible: yes

### D-0466 — A prompt is drafted only from a reached page
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 6 (#96) · Status: decided
- Decision: `scrape` drafts a `schema.prompt` only when the page was fetched with outcome `extracted`, with its cleaned text as role S's one sample; otherwise the answer has no `schema` member and no call is made.
- Alternatives: Return a stored draft for a page not reached; draft before fetching.
- Why: Role S needs 1–3 sample pages (SPEC-06 §4.5), and §4.8 returns nothing derived from a page that was not reached, as for formats.
- Reversible: yes

### D-0467 — LLM failures on `scrape` are problems and fail the job
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 6 (#96) · Status: decided
- Decision: The client's errors share `LLMFailure`, whose `code` is the task's `last_error` and the problem type: 422 `budget_exhausted`, 503 `llm_unavailable`, 502 `llm_output_invalid`. The last two extend SPEC-07 §4.3's types, as D-0364 did. A blank `schema.prompt` is a 422 `validation` before any job.
- Alternatives: 200 without `schema`; one generic 500.
- Why: The request asked for a schema it cannot get; §4.8 makes that a request-level failure with nothing partial.
- Reversible: yes

### D-0468 — The API starts without LLM provider keys
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 6 (#96) · Status: decided
- Decision: `client_from_settings` returns `Unconfigured(reason)` when a listed provider has no key; its calls raise `ProviderUnavailable(reason)`, and stored drafts are still served.
- Alternatives: Fail startup; build the client per request.
- Why: Scrape without a prompt needs no LLM, and provider keys are deferred (H4).
- Reversible: yes

### D-0501 — An inline schema is stored once, or matched by name
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: An inline `schema` is stored as a `user` schema at version 1, or matched to its name's latest version when that one has the same document and is active. A name whose latest version differs or is retired is a 409 `conflict`; a document that breaks a schema rule is a 422 `validation` (`schema.inline…`). All before any job.
- Alternatives: Add a new version when it differs; run inline schemas without storing them.
- Why: A record needs a stored `schema_id`; an inline schema never edits a stored one (ARCHITECTURE §5.2); the same body twice reuses one row.
- Reversible: yes

### D-0502 — A schema `records` cannot use is a validation problem
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: A schema id that is unknown, retired, or for another page kind than `page_kind` is a 422 `validation` problem on `schema`, before any job. A prompt draft of another page kind is the same problem and fails the job (`invalid_schema`). `records` needs `schema` and `page_kind`; listing records are refused until SPEC-05 PR 12.
- Alternatives: 404 for an unknown id; extract against the schema's own page kind.
- Why: The id is a request member; D-0490 refuses listings in `extract_page`.
- Reversible: yes

### D-0503 — `max_age` reuses a recent `ok` capture of the canonical URL
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: `max_age` reuses the latest capture of the request's canonical URL (found through the tasks that fetched it) in the same site, fetched within `max_age` seconds, `ok` and not expired; a capture whose bundle is gone is fetched anew. A reused capture skips robots.txt and the rate limit, counts no usage, and `fetch` is the capture's original fetch. Index `capture (site_id, fetched_at)` added (migration 0009).
- Alternatives: Reuse blocked or shell captures too; match `capture.url` exactly.
- Why: A blocked page is worth retrying; §4.4 names the canonical URL; the query needs the index.
- Reversible: yes

### D-0504 — A page whose resolution fails is `failed` with nothing derived
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: When resolution fails (SPEC-05 §4.14), the scrape answers 200 with outcome `failed`, no formats, records or draft; the task fails with `extraction_error`.
- Alternatives: A 500 problem; return the formats anyway.
- Why: SPEC-07 §4.8: a page's failure is an outcome, and nothing partial is returned.
- Reversible: yes

### D-0505 — Without the engine's data files, `records` is a 503
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: The API loads `EngineData` from `backend/data/` of the source tree at startup. Without it, `records` is a 503 problem `records_unavailable` before any job, and the other formats work. This extends SPEC-07 §4.3's problem types, as D-0467 did.
- Alternatives: Fail startup; load per request.
- Why: D-0492 defers shipping the data files; the API should still serve formats.
- Reversible: yes

### D-0506 — `extract_page` takes the caller's parse; storing is its own step
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: `extract_page(..., parsed=)` takes the caller's `ParsedPage`; `resolve.task.store_extraction` stores an `ExtractionResult` (`extract_task` uses it too), and `Stored` carries the `RecordDraft`. The scrape extracts outside its write transaction, as it computes formats (D-0428).
- Alternatives: Call `extract_task` inside the write transaction.
- Why: INV-26: one parse per request; no connection held while the page resolves.
- Reversible: yes

### D-0507 — Scrape records run `adhoc` without role C for now
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: Records run in `adhoc` mode with no role C hook until SPEC-06 PR 4 binds it. `job.schema_id` is set for a schema by id or inline; a draft is known only after the job starts, and its records name it.
- Alternatives: Set `job.schema_id` after drafting.
- Why: Smallest change; records carry `schema_id` either way.
- Reversible: yes

### D-0508 — The INV-26 parser counter is shared by all tests
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: The `parses` fixture moves to `tests/conftest.py` so DB tests can count parses; the records tests are `tests/db/test_scrape_records.py`, with their own small stub web.
- Alternatives: Keep them in `test_scrape_service.py` (over 800 lines).
- Why: C11: split along a logical boundary; test modules cannot import each other (importlib mode).
- Reversible: yes

### D-0523 — Replay uses the records' schema versions, cold
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: A capture replays against each schema version its stored records follow (the recorded version, not the latest), cold (`adhoc`, no config, no role C), and returns the records a page task would store (`resolve.task.page_records`: one per listing row, deduplicated by row URL). A capture with no record answers 409 `conflict`; an unknown capture or an expired bundle answers 404.
- Alternatives: A `schema_id` in the replay body (an API member SPEC-07 doesn't define); the latest schema version (the diff would compare different schemas).
- Why: A capture carries no schema; schemas are immutable per version (§5.2), so the recorded version keeps the replay comparable with the stored record. SPEC-07 §4.4 runs cold until SPEC-08 exists.
- Reversible: yes

### D-0524 — `allow_llm` accepted, unused until role C binds on replay
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: The replay body takes `allow_llm` (default false), but no replay calls an LLM yet: replay passes no role C to `extract_page`.
- Alternatives: Leave the member out until then.
- Why: SPEC-07 §4.6 defines the body; the default keeps replays cheap and deterministic (D-0029).
- Reversible: yes

### D-0525 — `GET /v1/records` pages by a keyset cursor, newest first
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: `{items, next_cursor}`, newest first by record id (UUIDv7), cursor = the last id; `limit` 50 by default, at most 200; every filter optional; `site` is the host, compared without case (RFC 4343). A listed record is the §4.4 record plus `capture_id` (null once the capture expired), `schema_id` and `version`; its `confidence` is recomputed from `field_meta` and the schema (§10). Migration 0010 indexes `record (job_id, id)`, `(schema_id, id)` and `(extraction_id)`.
- Alternatives: Offset paging; an opaque encoded cursor; requiring a filter.
- Why: D-0469's envelope; a keyset cursor is stable while records are added; extractions keep a NULL `capture_id` after expiry (SPEC-01 §4.2).
- Reversible: yes

### D-0526 — The Records screen follows SPEC-07's shapes
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: Where #97's hand shapes (D-0469) differed, the frontend follows SPEC-07: replayed records carry no `id`; `capture_id` is nullable (the inspector then offers no replay); the generated client marks `allow_llm` required, so the screen sends `{allow_llm: false}`. `RecordList` keys records by their position title. D-0469's module augmentation is deleted.
- Alternatives: A synthetic id on replayed records.
- Why: An id would name nothing stored (§13.1: replays are not persisted).
- Reversible: yes

### D-0774 — Markdown targets are resolved by lxml on a tree copy, not by trafilatura's `url=`
- Date: 2026-10-15 · Spec/PR: SPEC-07 §4.5, UAT accuracy markdown item 2 (#162) · Status: decided
- Decision: `content.markdown` resolves every link and resource target against the document base URL with `make_links_absolute` on a deep copy of the lxml tree, then runs trafilatura without `url`.
- Alternatives: trafilatura's `url=` (resolves link targets against the host only, not RFC 3986 §5.2); rewriting targets in the Markdown output.
- Why: RFC 3986 resolution against the HTML Standard's document base URL, and the shared tree stays as parsed (INV-26).
- Reversible: yes

### D-0775 — Markdown layout whitespace is dropped per line after extraction
- Date: 2026-10-15 · Spec/PR: SPEC-07 §4.5, UAT accuracy markdown item 3 (#162) · Status: decided
- Decision: Outside fenced code, a line's leading whitespace is dropped unless the line is a list item, and runs of blank lines become one (CSS Text Level 3 `white-space: normal`; CommonMark §4.4, §4.9, §5.2).
- Alternatives: Collapse text-node whitespace on the tree before trafilatura, which merged separate `div` blocks into one paragraph.
- Why: Per line, list nesting and code survive and blocks stay apart.
- Reversible: yes

### D-0807 — The OpenAPI document declares the bearer API key
- Date: 2026-10-15 · Spec/PR: SPEC-07 §4.2 (#175) · Status: decided
- Context: The API key was checked by a hand-written dependency, so the OpenAPI document declared no security (a static-analysis finding).
- Decision: A non-refusing `HTTPBearer(auto_error=False)` is a sub-dependency of `require_api_key`; every operation but `/healthz` declares `HTTPBearer`. Auth still runs in `require_api_key`.
- Alternatives: A global `security` entry with `/healthz` exempted by hand.
- Why: The requirement is stated per operation, from the dependency that enforces it, with no behaviour change.
- Reversible: yes
