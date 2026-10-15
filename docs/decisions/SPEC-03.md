# SPEC-03 decisions

Decisions for [SPEC-03 — Evaluation and measurement](../specs/SPEC-03-evaluation-and-measurement.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0166 — Normalizer `equal` stubs are exact JSON equality
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 2 (#27) · Status: decided
- Decision: Each type module's `equal(a, b)` returns `a == b` on normalized values until SPEC-04 PR 9 implements §4.5.
- Alternatives: Raise `NotImplementedError`.
- Why: Metrics (SPEC-03 PR 5) land in L0 before SPEC-04; exact equality only undercounts matches, never invents one.
- Reversible: yes; SPEC-04 PR 9 replaces the bodies

### D-0167 — `FieldShape` stands in for SPEC-04's `FieldSpec`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 2 (#27) · Status: decided
- Decision: `eval.labels` defines `ScalarShape | ListShape | ObjectShape`; list/object recursion lives in `values_equal` for now. SPEC-04 PRs 1/9 migrate callers and delete `FieldShape`.
- Alternatives: Add `schemas.types.FieldSpec` and `normalize.base` now.
- Why: Keeps this row inside `eval/labels` and the hook stubs.
- Reversible: yes

### D-0168 — Labeled and checked pages label every schema field; drafts may be partial
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 2 (#27) · Status: decided
- Decision: Missing fields are an error unless `status == "draft"`; a missing field is labeled `absent: true` explicitly.
- Alternatives: Allow partial labels at any status.
- Why: §4.6 scores every field of a checked page.
- Reversible: yes

### D-0169 — Private DB migrations: one Alembic env, two revision chains
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `alembic.ini` gets a `[private]` section with the same `env.py` and `version_locations = migrations/private_versions`; `env.py` uses `PrivateBase.metadata` and `CRAWLERAI_EVAL_PRIVATE_DATABASE_URL` (`EvalPrivateDatabaseSettings`) for it. Private revisions are `p0001`, ….
- Alternatives: A second `migrations_private/` env; one chain with conditional tables.
- Why: The private DDL evolves on its own, and the custodian runs it on their own machine.
- Reversible: yes

### D-0170 — Main eval tables hold dev only; private ones hold hidden/fresh only
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `CHECK split = 'dev'` on main `eval_page`/`eval_run`; `CHECK split IN ('hidden','fresh')` on the private tables.
- Alternatives: A free `split` column guarded only by the store.
- Why: Makes INV-01 structural for anything writing to the main DB.
- Reversible: yes

### D-0171 — `eval_capture` replaces `site_id` with `host` and `category`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `eval_capture` copies the `capture` columns without `site_id` or `expires_at`, and adds `split`.
- Alternatives: A private `site` table.
- Why: C1: a hidden host must not enter the main `site` table; eval captures never expire.
- Reversible: yes

### D-0172 — `eval_page.schema_name` plumbing
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: Both DBs have `schema_id` and `schema_name`; in the main DB the pair references `schema_def(id, name)` (new `uq_schema_def_id_name`); in the private DB it is unchecked.
- Alternatives: The dev store joins `schema_def` while the private DB stores a name.
- Why: `list_pages(schema_name)` works in both stores; the private DB has no `schema_def`.
- Reversible: yes

### D-0173 — `eval_run.git_sha` and `latest_run(sha)`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `eval_run` gets `git_sha` and `created_at`; `latest_run(None)` returns the newest run of the split, `latest_run(sha)` the newest of that commit.
- Alternatives: Parse the sha out of `engine_version`.
- Why: SPEC-03 §4.8 baseline lookup; deciding which commits are on `main` is the gate's job (PR 6).
- Reversible: yes

### D-0174 — LLM cache layout
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: Values are objects: dev at `eval/dev/llm/{key}.json`, private at `llm/{key}.json` (shared by hidden and fresh). In the private store an `eval_llm_cache` row, written after the object, makes a key a hit; the dev store has no table. Keys are lowercase hex sha256.
- Alternatives: Bytes in a table.
- Why: Follows SPEC-03 §4.2's object layout and keeps the `eval_llm_cache` table the row asks for.
- Reversible: yes

### D-0175 — Two-pass labeling rule in the DB
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `CHECK (checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler))`; a labeler pass clears `checker`.
- Alternatives: Enforce only in the store or the API.
- Why: §16.2 requires two different people, and a new labeler pass invalidates an earlier check.
- Reversible: yes

### D-0176 — Dev pages must reference a dev eval capture
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: The dev store accepts only a `capture` with `object_key = eval/dev/{id}.bundle.zst` and `expires_at IS NULL`; otherwise `EvalNotFound`. `eval_page.capture_id` references `capture` with no cascade.
- Alternatives: A trigger; `expires_at IS NULL` alone (accepts non-expiring production captures).
- Why: SPEC-03 §4.2; an expiring capture would make `expire_captures` fail on the foreign key.
- Reversible: yes

### D-0177 — `get_store` refuses a private config that isn't separate
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `PrivateStoreNotSeparate` when the private DB URL names the main database, or one object root is or contains the other.
- Alternatives: No check.
- Why: INV-01 ("separate DB + object prefixes"); SPEC-01 §5.
- Reversible: yes

### D-0178 — Private store tests use a throwaway `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: Tests use a throwaway database named by this variable (skipped without it); CI creates `crawlerai_private_test`, `make check` creates `crawlerai_private_check`, both owned by `app`.
- Alternatives: Give `custodian` a login in CI.
- Why: C1 and D-0067: no custodian credential exists anywhere agents run.
- Reversible: yes

### D-0179 — `put_capture` reads `duration_ms` from `timings_ms["total"]`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `put_capture` takes only a bundle; the fetchers record the whole fetch as `total`.
- Alternatives: Take a `FetchResult`.
- Why: Keeps the SPEC-03 §4.2 signature.
- Reversible: yes

### D-0180 — An empty checked listing scores
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: A `checked` listing with `rows: []` counts in `n_pages`; its page-level fields are scored, every published field of every engine row is FP, and it is zero-touch only if the engine published no rows.
- Alternatives: Skip it.
- Why: An empty listing is a legitimate label; skipping it would hide false rows from precision.
- Reversible: yes

### D-0181 — Min cell applies to each cell's own n
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: Field cells (`by_field_type`, `by_field`) are suppressed below 10 scored fields; bucket and config-status cells below 10 published fields; `by_category`, `acquisition` and `usage` below 10 pages. SPEC-03 §4.7 wording updated.
- Alternatives: Count labeled fields for every cell.
- Why: Pages ≤ fields, so counting pages is the stricter reading of §16.3 for page-level cells.
- Reversible: yes

### D-0182 — Pages kept only on dev; the full report stays in the job
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `build_report` includes `pages` only for `split == "dev"`; `export_aggregate` produces what leaves the protected job; the gate (PR 6) reads the unsuppressed report inside the job, so a suppressed `wrong_product` still fails it.
- Alternatives: Suppress at build time.
- Why: The gate needs every wrong-product count; nothing per-page is held for hidden/fresh.
- Reversible: yes

### D-0183 — Per-field cells stay in the job for hidden/fresh
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `export_aggregate` empties `by_field` when `split != "dev"`; the dev report and the in-job report keep it.
- Alternatives: Export it with min-cell suppression.
- Why: §4.7's aggregate schema and C10 expose aggregates per field type and evidence bucket only; `by_field` keys name schemas (possibly custom to a hidden site), and its suppressed cells can be recovered by subtraction.
- Reversible: yes

### D-0184 — Usage cells carry their n (spec clarification)
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `usage` is `{mode: {"llm_calls_per_1k_pages": x, "n": pages}}`, per 1k pages of that mode. SPEC-03 §4.7's example updated.
- Alternatives: A bare number per mode over all pages.
- Why: Keeps n with the number and lets small mode cells be suppressed.
- Reversible: yes

### D-0185 — Zero-touch is literal
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: Every judgment of a required field must be TP (labeled-absent is not TP); a required group needs a TP member and no FP member per entity; any unmatched engine row fails it.
- Alternatives: Count TN as success.
- Why: §4.6: "every required field … is TP".
- Reversible: yes

### D-0186 — `list`/`object` fields report under the shape type
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `by_field_type` keys on `FieldShape.type`, so a list of money is reported under `list`.
- Alternatives: The item type.
- Why: SPEC-04 `FieldSpec` will decide; until then no field mixes into a scalar type's precision.
- Reversible: yes

### D-0187 — Secondary suppression of aggregate cells for hidden/fresh
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: confirmed 2026-10-13
- Question: `by_bucket` and `by_config_status` cells are subsets of `by_field_type`, so one suppressed cell can be derived by subtracting the visible cells from the type total. §16.3 asks only for primary suppression (cells under 10), while its goal is that aggregates "can't identify individual cases". Add secondary suppression?
- Options: (a) keep primary suppression only, as §16.3 says; (b) add complementary suppression: when exactly one cell in a group is suppressed, suppress the next-smallest too; (c) report bucket and config-status tables only for dev.
- Recommendation: (b). It closes the subtraction path at little cost, and the gate reads unsuppressed numbers inside the job anyway (D-0182).
- Blocked: nothing. Ships with primary suppression; changing it touches ARCHITECTURE §16.3, so it needs the owner.
- Owner answer: option (b), complementary suppression (D-0234; ARCHITECTURE Appendix A #30, §16.3).

### D-0188 — Wrong products fail the gate even without a baseline
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: A first run with a wrong product gives `["no_baseline", "wrong_product:<t>"]` and fails.
- Alternatives: Pass every first run with `no_baseline` only.
- Why: INV-21 (wrong-product count on hidden is 0) needs no baseline; most conservative reading of §4.8.
- Reversible: yes

### D-0189 — Types without precision on both sides aren't compared
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: A field type with no precision on either side, or missing from one report, is not compared for precision.
- Alternatives: Fail it.
- Why: §4.8's rule compares precision; an abstention can't be a wrong publish, and dropped pages are caught by `n_pages_dropped`.
- Reversible: yes

### D-0190 — The 0.5 pt boundary uses `math.isclose`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: A drop of exactly 0.5 pt passes.
- Alternatives: Raw float `<`.
- Why: §16.4 says "more than 0.5 pt"; `0.97 - 0.965 > 0.005` is true in binary floats.
- Reversible: yes

### D-0191 — The gate refuses suppressed or mismatched input
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: `gate` raises `GateInputInvalid` on a suppressed `by_field_type` cell or a split mismatch.
- Alternatives: Skip suppressed cells.
- Why: D-0182: the gate reads the unsuppressed in-job report; a suppressed cell can hide a wrong product.
- Reversible: yes

### D-0192 — `GateResult` adds per-type pass/fail
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: `GateResult` adds `by_field_type: {type: pass}` to §4.7's `{baseline_git_sha, passed, reasons}`.
- Alternatives: Derive per-type results from reasons in PR 7.
- Why: §4.8: "its output is pass/fail per field type and the reasons".
- Reversible: yes

### D-0193 — Baseline lookup walks `git rev-list`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: Walk `git rev-list <ref>` newest first and take the first commit with a run (`latest_run(sha)`); return `None` at once when the store has no runs. The protected job needs full history.
- Alternatives: A store query over a sha set.
- Why: No store or migration change; cheap until milestone M.
- Reversible: yes

### D-0194 — `REQUIRED_FIELD_TYPES` is a constant until presets exist
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: The §4.8 list as a constant.
- Alternatives: Derive from presets now.
- Why: SPEC-04 PR 1 isn't merged.
- Reversible: yes; derive from presets later

### D-0195 — Eval capture obeys robots.txt and spaces requests per host
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: `eval capture` and `import-sites` read robots.txt once per origin per run; a disallowed page, or any page on an origin whose robots.txt is unreachable (RFC 9309 §2.3.1.4), is skipped. Pages of one host are spaced by `politeness.interval(None, Crawl-delay)`, and the CLI sleeps through the wait. Nothing is written to `site.robots_snapshot`.
- Alternatives: Fetch with no robots check (the literal reading of §4.4); an override flag.
- Why: ARCHITECTURE §7.1 / SPEC-02 §4.6 politeness applies to every fetch we make; no hidden host enters the main DB.
- Reversible: yes

### D-0196 — Every fetched page is stored, whatever its outcome
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: Blocked, shell, not_found and error outcomes are stored as eval captures and pages; the command exits 0 and reports each outcome.
- Alternatives: Store only `ok` captures; exit non-zero on a non-`ok` outcome.
- Why: §4.6 reports the acquisition outcome mix per category; dropping failures would hide them.
- Reversible: yes

### D-0197 — Site list format: `<category> <schema> <url>` per line
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: `#` comments and blank lines are ignored; `--pages-per-site N` (required) keeps a host's first N pages; any malformed line, unknown category, non-http(s) URL or duplicate URL rejects the whole file before fetching; errors give line numbers only.
- Alternatives: Site URLs with page discovery (SPEC-10); a CSV with a header.
- Why: §16.1 stratifies by category and page kind; leaving content out of errors keeps hidden hosts out of logs (C1).
- Reversible: yes

### D-0198 — Schemas resolve to their newest active version for every split
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: `--schema NAME` resolves to the highest active `version` in the main `schema_def`; `capture --page-kind` must equal the schema's page kind. Private pages store the resolved id and name (D-0172).
- Alternatives: A `--schema-version` flag; let `--page-kind` override.
- Why: The private DB has no `schema_def`; a mismatched page kind would mislabel pages.
- Reversible: yes

### D-0199 — Eval CLI output names pages by input position, never by URL
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: Each output line is `{n, capture_id, page_id, status_code, block_class, error}` or `{n, skipped}`.
- Alternatives: Print the URL.
- Why: C1: a hidden host must not reach a log or CI transcript.
- Reversible: yes

### D-0200 — `EvalStore.aclose()`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: The protocol gains `aclose()`, which disposes the store's engine; use with `contextlib.aclosing(get_store(...))`.
- Alternatives: Callers reach into the engine; leave engines undisposed.
- Why: `get_store` created an engine nobody could close, leaking connections.
- Reversible: yes

### D-0201 — `import-sites --file` is read only from under the working directory
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: Resolved against the working directory; exit 2 if outside.
- Alternatives: Read any path; mark the Sonar finding safe.
- Why: Same rule as `fetch --out` (D-0146); a real fix for S8707.
- Reversible: yes

### D-0202 — Unexpected failures on private splits report their type only
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: On `hidden`/`fresh`, an unexpected exception exits 1 with `failed with <Type>; details withheld for the <split> split`; on `dev` it propagates with its traceback.
- Alternatives: Print tracebacks for every split.
- Why: C1: a DB error's `DETAIL` or an exception message could carry a hidden URL or row values.
- Reversible: yes

### D-0207 — The labeling API serves the dev split only
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: The router holds a `DevEvalStore` from the main settings and never calls `get_store`; `split` accepts only `dev` (422 otherwise); private settings are ignored even when set.
- Alternatives: Serve whichever split `get_store` can open (§1, §4.10 on a custodian machine).
- Why: C1 / INV-01, most conservative reading; hidden/fresh labeling at M is D-0214.
- Reversible: yes

### D-0208 — Label values are checked for structure only until the normalizers exist
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `PUT labels` validates the document, schema fit and two-pass rule; running values through type normalizers and `POST /normalize` wait for SPEC-04 PRs 2–8 (`/normalize` returns 501).
- Alternatives: Refuse every label until then; hand-check value shapes.
- Why: Hand checks would duplicate a type module's logic (C8).
- Reversible: yes; SPEC-04 adds the check

### D-0209 — Pass rules at the API
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `draft`/`labeled` is the labeler's pass and names its labeler; `checked` is allowed only over a `labeled`/`checked` page and keeps the stored labeler.
- Alternatives: Trust the document's names.
- Why: §16.2 / §4.10: `checked` only on confirmation by a different name.
- Reversible: yes

### D-0210 — Problem responses are local until SPEC-07
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: The router returns SPEC-07 §4.3 problems itself; FastAPI's request validation keeps its default 422; no auth until SPEC-07 PR 2.
- Alternatives: Install app-wide handlers now.
- Why: Those are SPEC-07 PR 1's scope.
- Reversible: yes

### D-0211 — The OpenAPI document always includes the eval routes
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `crawlerai openapi` builds the app with `eval_ui=True`; at runtime they mount only with `CRAWLERAI_EVAL_UI=true`.
- Alternatives: Export only what the default app mounts.
- Why: The labeling screen needs the types, and the export must not depend on the environment.
- Reversible: yes

### D-0212 — Capture through the API is limited to 20 URLs per request
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `POST /v1/eval/capture` runs `run_capture` into dev within the request.
- Alternatives: A background job (SPEC-10).
- Why: Fetches are polite and sequential, so a request must stay short.
- Reversible: yes

### D-0213 — Sanitized HTML for the labeling view
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: Removes `script`, `iframe`, `frame`, `frameset`, `object`, `embed`, `meta[http-equiv]`, `on*` attributes and `javascript:` URLs; inserts one `<base href>` at the final URL or the page's own base resolved against it (D-0012); decodes in the Content-Type charset, else UTF-8.
- Alternatives: Only §4.10's list; strip `src`.
- Why: The extra elements also run script or navigate (HTML standard).
- Reversible: yes

### D-0214 — How hidden/fresh pages get labeled at milestone M
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: confirmed 2026-10-13
- Question: The labeling API serves dev only (D-0207). SPEC-03 §1/§4.10 suggest the same screen could label hidden/fresh on a custodian machine. How should hidden/fresh labeling work?
- Options: (a) a custodian-only process: the same app run on the custodian machine with a private backend, never deployed; (b) this router gains a private backend behind a custodian-only setting; (c) label hidden/fresh with a separate CLI.
- Recommendation: (a). It keeps the main deployment unable to reach private data, and it reuses the screen.
- Blocked: nothing now. Needed before H3 (milestone M).
- Owner answer: option (a), a custodian-machine instance with a private backend, never deployed (D-0234; Appendix A #30).

### D-0215 — `RecordedLLM` keys on the requested model class
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: sha256 of the canonical JSON array `[prompt_kind, model_class, system, user, output_schema]` (sorted keys, no whitespace); SPEC-06's `request_hash` should use the same function.
- Alternatives: The concrete model name.
- Why: The provider picks the concrete model after the request exists (SPEC-06 failover); an array keeps parts from running together.
- Reversible: yes (re-records the cache)

### D-0216 — `replay_split` builds the `RecordedLLM` itself
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: `replay_split` takes `live: LLMClient | None` and returns `list[EvalCase]` (§4.5's `PageResult`).
- Alternatives: A separate `PageResult` type; the caller builds the `RecordedLLM`.
- Why: Every replay LLM call goes through recording by construction; `EvalCase` is what `build_report` scores.
- Reversible: yes

### D-0217 — `replay_page` takes no `calibration` argument (spec clarification)
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: The engine holds calibration and `engine.version` names it, so SPEC-03 §4.5's `replay_page(..., calibration: Calibration, ...)` drops that parameter. SPEC-05 implements this signature.
- Alternatives: Pass calibration separately.
- Why: Matches ARCHITECTURE §15: `(capture, engine_version, config, schema_version) → record`.
- Reversible: yes

### D-0218 — Interim LLM and engine protocols live in `eval/replay`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: `LLMRequest`/`LLMResponse`/`LLMClient` and the `Engine` protocol stay in `eval/replay` until SPEC-05/06 bring the real types.
- Alternatives: Create `crawlerai.llm.client` now.
- Why: Building SPEC-06's module here would pre-empt its PR (same pattern as `metrics.PageOutput`).
- Reversible: yes

### D-0219 — Replay drops pages on data problems and stops on setup errors
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: A missing recording or an invalid `config_snapshot` drops the page (`ReplayFailed`); an unknown schema, a page-kind mismatch or labels that don't fit the schema stop the run.
- Alternatives: Drop on everything; raise on everything.
- Why: Per-page problems trip the `n_pages` gate as §4.11 intends; setup errors would silently drop every page.
- Reversible: yes

### D-0220 — Promote moves whole sites, by default only fully checked ones
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: Without `--all`, a fresh site moves only when every page is `checked`; `--all` moves every fresh site; pages never move one by one.
- Alternatives: Move checked pages individually; `--all` meaning every split.
- Why: §16.1 splits are sets of sites; splitting one would put a host in dev and a private split at once; `checked` is the only measured status (§4.3).
- Reversible: yes

### D-0221 — A fresh site whose host also has hidden pages is not promoted
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: It stays in fresh even with `--all`.
- Alternatives: Promote it anyway.
- Why: C1 / §16.1: moving it would put a hidden host in dev. Most conservative reading.
- Reversible: yes

### D-0222 — Rotation is stratified by category, rounding half up, at random
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: Per category, `floor(F·n_sites + 0.5)` hosts are chosen by `SystemRandom.sample`; a site's category is its first page's; `--fraction` in (0, 1).
- Alternatives: One draw over all sites; floor rounding.
- Why: §16.1 stratifies hidden by category; with 0.33 and 3 sites, round-half-up moves 1.
- Reversible: yes

### D-0223 — Interrupted moves converge
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: Copy (`put_capture` converges, `put_page` skipped when the dev page exists), then `remove_page` (no-op when missing); a rerun finishes a partial move.
- Alternatives: A two-phase commit across databases.
- Why: The dev and private stores are separate databases (INV-01); §4.4 fixes the order.
- Reversible: yes

### D-0225 — Rotation skips a hidden host that also has fresh pages
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 follow-up (#37) · Status: decided
- Decision: `rotate_hidden` leaves out hidden hosts that have fresh pages before choosing, and the per-category fraction is a share of the hosts that can rotate. `import-sites` is unchanged. A host in both hidden and fresh stays in both until one copy is removed by hand, since `promote` skips it too.
- Alternatives: (b) `import-sites` refuses a fresh host already in hidden or dev; (c) both.
- Why: Fresh means sites nobody has seen, and a site moves whole (§16.1). This mirrors `promote`'s guard and changes no input contract; (b) changes the custodian's import and needs a lookup across stores at capture time.
- Reversible: yes

### D-0229 — Interim calibration and precedence fits in `eval/calibrate` until SPEC-05
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: Calibration is the dev run's `by_bucket` cells (`n`, precision; a suppressed cell keeps `n` with no precision). Precedence is the current order, unchanged. Both are default parameters that SPEC-05 PR 13 replaces.
- Alternatives: The commands exit "not available until SPEC-05".
- Why: Both follow SPEC-05 §4.11's rules applied to the data the report has today, so the commands are usable and tested end to end.
- Reversible: yes

### D-0230 — `fit-precedence` refuses without a current `source_precedence.yaml`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: With no current file it exits 2 and does not invent an initial order.
- Alternatives: Write SPEC-05 §4.7's default order.
- Why: The initial order is SPEC-05's to commit (D-0020); a default here would be a guess (C7).
- Reversible: yes

### D-0231 — `calibrate`/`fit-precedence` refuse non-dev splits themselves
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: `--split` accepts dev, hidden or fresh; non-dev exits 2 with an INV-02 message before any store is opened.
- Alternatives: `choices=["dev"]` in argparse.
- Why: The refusal is the command's own, stated and tested, as INV-02 requires.
- Reversible: yes

### D-0232 — `EvalStore.get_run(run_id)`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: A protocol method on both stores that reads one run of the store's split by id, raising `EvalNotFound`.
- Alternatives: A dev-store-only method.
- Why: `--run <id>` needs it, and both stores share the run table code.
- Reversible: yes

### D-0233 — PyYAML is a direct dependency
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: `pyyaml>=6,<7` (MIT), with `types-pyyaml` for mypy; only `safe_load`/`safe_dump`.
- Alternatives: Write YAML by hand.
- Why: SPEC-05 reads the file with a YAML parser; the safe functions never construct objects.
- Reversible: yes

### D-0235 — Labels carry an ETag; `PUT labels` takes `If-Match`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: The ETag is sha256 of the stored labels' canonical JSON. `If-Match` is optional (`*` or a list of tags); a mismatch is 412. The store also writes only `WHERE labels = <labels the API read>`, and a miss is 409. `EvalStore.put_labels` gains a required keyword `expected`.
- Alternatives: Only the in-request `WHERE` guard; a version column (a migration on a shared table).
- Why: The #35 review follow-up; standard HTTP conditional requests (RFC 9110 §13.1.1), additive to §4.10's API.
- Reversible: yes

### D-0236 — `GET /v1/eval/pages/{id}` returns the schema's field shapes
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: `PageDetail.fields` holds the page's schema fields (type, scope, nesting), which the form renders.
- Alternatives: Wait for `/v1/schemas` (SPEC-07 PR 7).
- Why: §4.10's form needs one row per schema field, and nothing else serves them before SPEC-07.
- Reversible: yes

### D-0237 — The labeling frame is `sandbox="allow-same-origin"`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: No `allow-scripts`, forms, popups or top navigation; the same origin lets the screen read clicks for click-to-copy, and it prevents link navigation. SPEC-03 §4.10 is clarified to match.
- Alternatives: `sandbox=""`, under which click-to-copy cannot work.
- Why: §4.10 asks for both a sandboxed frame and click-to-copy; this is the narrowest sandbox that allows both, and the API strips script (D-0213).
- Reversible: yes

### D-0238 — Label values are entered as JSON until `/normalize` exists
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: The value field takes a JSON value; `/normalize`'s `{value}` or `{reason}` fills it when it answers.
- Alternatives: Per-type inputs (client-side normalization, out of scope, C8).
- Why: The most conservative reading.
- Reversible: yes

### D-0239 — The labeling screen calls its own origin; `pnpm dev` proxies `/v1`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: `sameOriginClient()` uses `window.location.origin`; the Vite dev server forwards `/v1` to the local API.
- Alternatives: CORS on the API; a configured base URL (SPEC-12 PR 1's connect screen).
- Why: No CORS and no connect screen exist yet.
- Reversible: yes

### D-0246 — Complementary groups include `by_category` (with `acquisition`) and `usage`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 12 (#44) · Status: decided
- Decision: Besides §4.7's bucket and config-status groups, category and usage cells are complemented, since their `n` sums to the reported `n_pages`.
- Alternatives: Only the two groups §4.7 names.
- Why: The ACTIVE row asks for every group that sums to a reported total; the conservative reading (§16.3).
- Reversible: yes

### D-0247 — A one-cell group gets no complement; ties break by key
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 12 (#44) · Status: decided
- Decision: A group with one suppressed cell gets no complement; among equal-`n` candidates the first key is suppressed.
- Alternatives: Suppress the group total too.
- Why: A one-cell group equals its total, which §16.3 reports at its own size; key order keeps exports deterministic.
- Reversible: yes

### D-0253 — Capture and import-sites refuse a host that has pages in another split
- Date: 2026-10-13 · Spec/PR: SPEC-03 follow-up (#49; D-0225 option b) · Status: decided
- Decision: `eval capture` and `eval import-sites` refuse the whole input before any fetch when one of its hosts already has pages in another split, reporting counts only (per split), never a host or line. Re-capturing into the host's own split is allowed. A dev capture is checked against hidden/fresh only when custodian settings are present.
- Alternatives: skip offending lines and report line numbers (a line number points at a hidden host); require private credentials for every dev capture (contradicts C1's custodian-only credentials).
- Why: A site sits in one split (§16.1); counts-only output keeps C1. Remaining gap by design: a non-custodian dev capture of a hidden/fresh host can't be detected; `promote` and `rotate-hidden` still guard moves.
- Reversible: yes
