# SPEC-06 decisions

Decisions for [SPEC-06 — LLM layer: provider-agnostic client, grounding, roles C and S](../specs/SPEC-06-llm-layer.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0346 — Usage is committed in its own transaction
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `MeteredClient` holds an `AsyncEngine` and records each call's usage with `engine.begin()`, not on the caller's connection; a caller must not hold an uncommitted write to the job row when it calls the client.
- Alternatives: Return usage in a result for the handler to record; catch provider errors in handlers.
- Why: Closes the ACTIVE.md note for SPEC-06 for every caller at once; the typed exceptions (§4.7) can propagate without losing usage (D-0151's concern).
- Reversible: yes

### D-0347 — Only answered LLM calls are charged
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: A provider error records no usage; an invalid reply that is retried is two charged calls.
- Alternatives: Charge every attempt.
- Why: A failed call has no token counts and no cost; the budget is checked before each attempt either way.
- Reversible: yes

### D-0348 — No LLM budget or usage without a job
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `job_id=None` (eval pre-fill only, SPEC-06 §4.2) skips the budget check and usage rows; `usage_event.job_id` is NOT NULL.
- Alternatives: A synthetic job for pre-fill.
- Why: Matches the spec's field comment; SPEC-06 PR 5 revisits if pre-fill needs metering.
- Reversible: yes

### D-0349 — The root output schema is a closed object
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `LLMRequest` refuses an `output_schema` whose root is not `{"type": "object", "additionalProperties": false}`, including an omitted `additionalProperties`.
- Alternatives: Refuse only an explicit `additionalProperties: true` (§4.6's literal wording).
- Why: An omitted keyword allows extra properties too, which is what §4.6 guards against; the most conservative reading.
- Reversible: yes

### D-0350 — `request_hash` keeps SPEC-03's key
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: sha256 of the canonical JSON array (prompt_kind, model_class, system, user, output_schema), excluding `max_output_tokens` and `job_id`; `request_key` renamed `request_hash` and moved to `llm.client`.
- Alternatives: Hash the concrete model (§4.2's wording).
- Why: The provider picks the model after the request exists, and existing recordings keep their keys.
- Reversible: yes

### D-0351 — `jsonschema` for LLM output validation
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `jsonschema` (MIT) validates replies against draft 2020-12 schemas; `types-jsonschema` (Apache-2.0) is a dev dependency for mypy.
- Alternatives: A hand-written validator.
- Why: The standard implementation; licence-clean.
- Reversible: yes

### D-0370 — Anthropic calls send no `temperature`
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: The Anthropic provider sends no sampling parameters; Gemini sends `temperature: 0`. Narrows D-0023's "temperature 0" to the providers that accept it.
- Alternatives: Send `temperature: 0` everywhere (§4.2).
- Why: Claude Haiku 5.5 and Sonnet 5.5 reject non-default sampling values with a 400; replay determinism comes from the recorded cache (INV-10), not from temperature.
- Reversible: yes

### D-0371 — Failover is per call, from the first provider, at most once
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: Each provider call, including the one validity retry, asks the configured providers in order; a client has one or two providers. A call that does not answer is not charged (D-0347); the budget is checked once before each call.
- Alternatives: Keep using the provider that answered for the retry.
- Why: Simplest reading of "failover to the next provider once" (§4.2); `LLMResponse.provider` names the one that answered.
- Reversible: yes

### D-0372 — Only "no answer" fails over
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: 408, 429, 5xx (RFC 9110, RFC 6585), timeouts and connection errors become `ProviderError`; other statuses (bad key, unknown model, refused schema) propagate as the SDK's exception.
- Alternatives: Fail over on any error.
- Why: Another provider would not fix a misconfiguration; it should fail loudly.
- Reversible: yes

### D-0373 — SDK retries are off
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: Anthropic `max_retries=0`; Gemini without retry options (one attempt).
- Alternatives: Keep the SDKs' backoff retries.
- Why: They would multiply latency up to the 60/120 s timeouts and hide the failover the spec defines.
- Reversible: yes

### D-0374 — Default model ids in settings
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: fast: `claude-haiku-5-5`, `gemini-3.5-flash-lite`; strong: `claude-sonnet-5-5`, `gemini-3.8-flash`; each overridable by `CRAWLERAI_LLM_{FAST,STRONG}_MODEL_<PROVIDER>`.
- Alternatives: No defaults; `gemini-3.1-pro-preview` for strong.
- Why: Appendix C names Haiku/Flash-Lite-class and Sonnet-class models; Gemini Pro is a preview, 3.8 Flash is the current stable mid-tier model.
- Reversible: yes

### D-0375 — Provider settings and keys
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: `CRAWLERAI_LLM_PROVIDERS` is comma-separated, defaults to `anthropic,gemini`, and refuses duplicates and unknown names; keys are `CRAWLERAI_LLM_API_KEY_<PROVIDER>` (SecretStr); `providers_from_settings` refuses a listed provider without a key.
- Alternatives: The vendors' own env vars (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).
- Why: One `CRAWLERAI_*` namespace (SPEC-00 §4.4); no client is built half-configured.
- Reversible: yes

### D-0376 — LLM output token counts include thinking
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: Gemini `tokens_out` = candidates + thinking tokens; Anthropic's `output_tokens` already includes thinking; a Gemini response without usage metadata records 0.
- Alternatives: Candidate tokens only.
- Why: Thinking tokens are billed as output.
- Reversible: yes

### D-0377 — LLM provider SDK dependencies
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: `anthropic` (MIT) and `google-genai` (Apache-2.0), as SPEC-06 §4.1 names; `httpx` moved from dev to runtime and `httpx2` added (the providers catch their transport errors and take test clients).
- Alternatives: Raw HTTP.
- Why: The spec names the official SDKs.
- Reversible: yes

### D-0379 — Grounding aligns one claim at a time
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 3 (#76) · Status: decided
- Decision: `align` takes one claim (`SpanClaim`) and returns `GroundedSpan | None`; role C maps it over its fields. Two occurrences equally near the claimed `start` resolve to the earlier one. An empty value is dropped. Offsets count code points of the cleaned text (Python `str` indices), as SPEC-05's `CleanedText` does.
- Alternatives: `align(values, text)` over a mapping (spec's sketch); dropping on a tie.
- Why: One value per call keeps the function independent of role C's output shape (detail fields vs listing rows); a fixed tie-break keeps replays deterministic (INV-10); an empty span holds no value and is not a valid `text:` locator.
- Reversible: yes

### D-0448 — Role S output is checked by the client, within its one retry
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 6 (#92) · Status: decided
- Decision: The role S output schema is `SchemaDocument`'s Pydantic JSON Schema without `name` and `version`. `LLMClient.complete_json` takes an optional reply check (`ReplyCheck`: why a schema-valid reply is invalid, or None); role S passes the `SchemaDocument` validation, so a schema mismatch and an invalid document share the client's one retry (at most two calls), then `OutputInvalid`. `RecordedLLM` passes the check to its live client.
- Alternatives: A hand-written JSON Schema encoding every document rule; a second retry in role S on top of the client's (up to four calls).
- Why: One definition of the document (SPEC-04 types); JSON Schema can't express "every field described" or required-group rules; §4.5 says "the client validates it with the SchemaDef model; invalid → one retry", and roles A and D can reuse the check. Whether each provider's structured-output mode accepts the recursive `$ref` is unverified until keys exist (H4).
- Reversible: yes

### D-0449 — Role S keys drafts on the whitespace-normalized prompt
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 6 (#92) · Status: decided
- Decision: The prompt is normalized by collapsing Unicode whitespace runs to one space and stripping the ends; the hash and the request use the normalized text. An empty prompt is refused. The stored draft is returned whatever its status.
- Alternatives: Hash the raw prompt; also hash the sample pages or page kind.
- Why: §4.5 "the same prompt text (after whitespace normalization)" and "keyed by prompt hash"; one prompt, one schema.
- Reversible: yes

### D-0450 — Role S input limits
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 6 (#92) · Status: decided
- Decision: Each sample's cleaned text is cut to its first 40,000 characters (role C's detail limit, D-0025); 1–3 samples are required; `max_output_tokens` is 8,192.
- Alternatives: A new setting for role S's limit; no cut.
- Why: Bounds the request without a new setting; 8,192 tokens holds a schema of several dozen fields.
- Reversible: yes

### D-0518 — Role C is bound in `config_ir.role_c`
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: `role_c(client, *, job_id) -> RoleC` lives in `crawlerai.config_ir.role_c`; `llm.roles.c_extract` returns `Filled` (lower-layer types only). `eval.engine.PipelineEngine` binds it on the harness's `RecordedLLM` with `job_id=None`.
- Alternatives: `eval.engine` (production code would import eval); a new top-level package; changing the layering contract.
- Why: `resolve | llm` are independent (D-0483); `config_ir` is the first layer above both, and both the replay engine and the worker (services) can import it.
- Reversible: yes

### D-0519 — Role C failure reasons
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: Each `LLMFailure` carries a `field_reason`: `BudgetExhausted` → `llm_budget`, `ProviderUnavailable` → `llm_unavailable`, `OutputInvalid` → `llm_output_invalid`. The asked fields stay `missing` with it, plus a diagnostic `role C: <reason>`; a failed call adds no `llm_calls` record.
- Alternatives: Fold `OutputInvalid` into `llm_unavailable`; map the reason inside each role.
- Why: SPEC-06 §4.7 names two reasons for three exceptions; keeping the client's own code is more informative, and one mapping on the failure serves every role.
- Reversible: yes

### D-0520 — Missing optional fields ride along with a required gap
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: When a required field (or a member of an unmet required group) is `missing`, every `missing` optional field joins the same role C call; optional gaps alone never trigger a call. Partly supersedes D-0489.
- Alternatives: Required fields only (D-0489 as written).
- Why: SPEC-06 §4.4 and D-0025; one call either way.
- Reversible: yes

### D-0521 — Type-invalid role C values stay candidates
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: An aligned value its normalizer declines is proposed with its `Invalid`/`Ambiguous` result; preference rejects it and the candidate row keeps the reason. Ungrounded values are dropped with the diagnostic `role C: <field> ungrounded` (no value text, which is page content).
- Alternatives: Drop them before resolution, as SPEC-06 §4.4/§6 words it ("dropped").
- Why: Same as every collector; the reason reaches `candidate.reject_reason`. A clarifying spec edit may follow.
- Reversible: yes

### D-0522 — Role C truncation and limits
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: `DETAIL_MAX_CHARS = 40_000` is a constant (D-0025; role S's `SAMPLE_MAX_CHARS` reuses it). Spans are aligned to the text the model read, so a value past the cut is ungrounded; truncation is recorded as a diagnostic. `max_output_tokens = 4096`; fields are listed sorted by name.
- Alternatives: A `CRAWLERAI_LLM_C_MAX_CHARS` setting now; record truncation on `LLMCallRecord`.
- Why: Matches role S's precedent; `extraction.llm_calls` stores a count, so a diagnostic is what persists.
- Reversible: yes

### D-0534 — Role C listing call only when structured data gives no rows
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 5 (#111) · Status: decided
- Decision: A cold listing calls role C once when `listing_rows` finds no row and the schema has row fields, asking every row field and the page fields still `missing`. With structured rows there is no call; their gaps stay missing (D-0516).
- Alternatives: Also call for gaps in structured rows or page fields.
- Why: ARCHITECTURE §8.6, rows come from structured data *or* role C; merging LLM rows into structured ones needs a matching rule the spec doesn't define.
- Reversible: yes

### D-0535 — LLM row entities
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 5 (#111) · Status: decided
- Decision: A role C row is `Entity(id="llm:rows[<position in reply>]", kind="page", parent=None)`; a row whose every value is null or ungrounded is no row. Page fields' candidates are owned by the page entity.
- Alternatives: Kind = the schema's primary type; keep empty rows.
- Why: The model states no schema.org type (`Entity.kind` falls back to `page`); an empty row would be a record without values.
- Reversible: yes

### D-0536 — `RoleC` is a protocol with `detail` and `listing`
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 5 (#111) · Status: decided
- Decision: `RoleC.detail(GapRequest) -> GapReply` and `RoleC.listing(ListingGapRequest) -> ListingGapReply` (adds `rows`); `config_ir.role_c` returns one object with both. `c_extract.Filled.reply` is `LLMResponse | LLMFailure`; c_extract functions take the requested `FieldSpec`s, not the schema.
- Alternatives: A second hook argument to `extract_page`; one callable over a union.
- Why: A listing reply has a different shape (rows); the pre-fill has field specs, not a `SchemaDef`.
- Reversible: yes

### D-0537 — Role C listing limits and prompt
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 5 (#111) · Status: decided
- Decision: `LISTING_MAX_CHARS = 80_000`, `LISTING_MAX_ROWS = 200` are constants (D-0025, D-0522). The row cap is in the prompt and applied to the reply (cut, with a diagnostic), not a schema `maxItems`. `max_output_tokens = 16_384`. The listing system prompt is `c_extract.txt` + `c_extract_listing.txt`, so the detail request hash is unchanged.
- Alternatives: `maxItems` (an over-long reply becomes a retry); settings.
- Why: As D-0522; provider support for `maxItems` is unverified. Review (#111) noted 16,384 tokens may not hold 200 rows on wide schemas.
- Reversible: yes

### D-0538 — Pre-fill draft content and API
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 5 (#111) · Status: decided
- Decision: Only grounded values whose normalizer returns `Ok` become field labels (normalized value + `text:` locator); null, ungrounded and declined values stay unlabeled, never `absent`. The draft has no labeler (`put_labels` takes `who: str | None`). `POST prefill` returns the stored `Labels` with an `ETag`, replaces a draft (honouring `If-Match`), answers 409 on a labeled or checked page, and stores nothing on an LLM failure (503/502).
- Alternatives: Mark nulls absent; require a labeler in the body; overwrite any labels.
- Why: `absent` is the labeler's claim (G2); a pre-fill never counts as ground truth and must not erase a human pass.
- Reversible: yes

### D-0719 — Estimated LLM cost shown for visibility
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided (owner, 2026-10-14)
- Decision: Show an estimated LLM cost for visibility; it is not billing. ARCHITECTURE §1, §13.1 and §17 amended (rev 11).
- Alternatives: Tokens and calls only.
- Why: Owner request (2026-10-14).
- Reversible: yes

### D-0720 — LLM usage event time comes from the UUIDv7 id
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: `usage_event` has no time column; an event's time and day come from its UUIDv7 id (RFC 9562 §5.7, `core.ids.uuid7_floor`), so a day range is an id range on the primary key.
- Alternatives: Add `usage_event.created_at` (a SPEC-01 schema change); use `job.created_at` (wrong for long jobs).
- Why: No schema change other specs rely on.
- Reversible: yes; a later column changes only the expression

### D-0721 — The client records `tokens_in` on each usage row of a call
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: Each of a call's usage rows carries the call's input tokens in its metadata, so output tokens are priced at the call's prompt-length tier. Older rows of a tiered model without it are unpriced.
- Alternatives: Pair the input and output rows by metadata (fragile on retries).
- Why: SPEC-06 §4.8.
- Reversible: yes

### D-0722 — Unpriced tokens make a cost null, not partial
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: Any total, day, breakdown row or job that includes tokens without a price has `estimated_usd: null` and reports `unpriced_tokens`. Prices start at their checked date; model ids match exactly (no prefix matching), so a suffixed reply id is unpriced until listed.
- Alternatives: Partial sums; nearest-model prices.
- Why: C7.
- Reversible: yes

### D-0723 — Calls without a job are not in the cost history
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: The labeling pre-fill and an eval replay's live recording call the client with `job_id=None`, write no usage event, and so have no cost history; learning runs, scrape, extract and crawl have a job and are counted. The API and the Settings screen say so. `usage_event.job_id` is unchanged.
- Alternatives: A nullable `job_id` or a separate table (a schema change other specs rely on; escalation).
- Why: No spec allows a nullable FK.
- Reversible: yes

### D-0724 — One price file per provider; source URL only in the manifest
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: Prices live in `backend/data/llm/<provider>-pricing.json`, one manifest entry each; the source URL is in the manifest only, since the C3 scan flags hostnames in data files and the manifest is its exempt data file.
- Alternatives: One combined file; the URL inside each file.
- Why: C3, C4.
- Reversible: yes

### D-0725 — Range presets on the Settings screen
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: The LLM cost section offers last 7, 30, 90 or 365 days through today (UTC) in a Select, not a date-range picker; the API takes any range up to 366 days.
- Alternatives: HeroUI DateRangePicker.
- Why: The smallest keyboard-friendly control before UAT.
- Reversible: yes

### D-0726 — Index `usage_event (job_id, id)`
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: Migration 0016 adds `ix_usage_event_job_id_id`, so the job summary's `llm_cost_usd` (jobs list, job page, events, webhooks) reads a job's events by index, not by a table scan; added with its query per the ACTIVE.md index rule.
- Alternatives: Counters on `job`; no index.
- Why: Reviewer and /simplify follow-up.
- Reversible: yes

### D-0727 — The SQL join is the one price-matching rule
- Date: 2026-10-14 · Spec/PR: SPEC-06 PR 7, SPEC-10 PR 10, SPEC-12 PR 11 (#148) · Status: decided
- Decision: `services/llm_costs.py`'s join is the only rule matching a call to its price; the Python copy used only by tests was removed. Price periods compare as UUIDv7 id bounds.
- Alternatives: Keep a Python lookup beside the SQL.
- Why: Two copies could drift untested.
- Reversible: yes

### D-0935 — The LLM setup is checked at start and reported by `/healthz`
- Date: 2026-10-16 · Spec/PR: reference eval round 1 (#206) · Status: decided
- Decision: API, MCP stdio and worker ask each provider's model lookup (no tokens) about the configured model ids, on the client's own providers; a refused model, an unanswered check, a listed provider without its key or no provider listed is logged at ERROR, and `GET /healthz` reports `llm: checking | ok | unavailable` while staying 200.
- Alternatives: fail `/healthz`; list the problems in it.
- Why: reference eval §7 (every scrape `partial` with only a WARNING); the probe is unauthenticated, so it names no model or key, and an API that serves all but LLM calls stays up.
- Reversible: yes
