# LLM Specification

## Purpose

One provider-agnostic LLM client with constrained JSON output, per-job budgets, usage and estimated cost, plus roles C
(grounded values) and S (schema drafts); roles A and D use the client but live in
[learning-configs](../learning-configs/spec.md) and [adapters](../adapters/spec.md). Rationale: ARCHITECTURE §11, §17
([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-06.

## Requirements

### Requirement: Four roles, core only
The system SHALL use the LLM only in roles C (grounded values), A (selectors or JSONPath), D (a typed request spec)
and S (a draft schema); only role C outputs values. Adjudication, a verifier and self-consistency SHALL NOT be built
(§22, C13). Refs: §11, §22.

### Requirement: Providers, model classes and setup check
The system SHALL call providers in `CRAWLERAI_LLM_PROVIDERS` order, mapping model class `fast` (role C) and `strong`
(A, D, S) to model ids as defined in `core/settings.py`; a listed provider without a key is refused. API, MCP and
worker SHALL check model ids at start (no tokens) and `/healthz` reports `llm: checking | ok | unavailable`, staying
200. Refs: D-0023, D-0374, D-0935.

### Requirement: Constrained JSON output inside provider subsets
Every call SHALL request JSON-schema constrained output with a closed object root, kept inside each provider's subset
in `backend/data/llm/<provider>-structured-output.json` (checked by `llm/schema_subset.py`). Gemini sends
`temperature: 0`; Anthropic sends no sampling parameters, `fast` calls ask low effort. Refs: D-0349, D-0370, D-1008.
#### Scenario: Open root refused
- **WHEN** a request's output schema omits `additionalProperties: false` at the root
- **THEN** it is refused before any call

### Requirement: Validation, retry, failover and error reasons
The client SHALL validate each reply (JSON Schema 2020-12 plus an optional role check) and retry once with the error;
a second invalid or a cut reply is `llm_output_invalid`. It SHALL fail over once, only when no answer came (408, 429,
5xx, timeout, connection error); other statuses are `llm_refused`, no answer is `llm_unavailable`, and asked fields
stay `missing`, never guessed. Refs: D-0351, D-0371, D-0767, D-1009.
#### Scenario: Provider 503
- **WHEN** the first provider answers 503
- **THEN** the same request goes once to the next provider, and a 400 instead gives `llm_refused` with no failover

### Requirement: Per-job budgets
Before each call and retry the client SHALL check the job's `llm_calls` budget, else the project's `llm_call_cap`
(none by default), and raise `BudgetExhausted` (`budget_exhausted`) when spent; a call with no job (pre-fill, eval
recording, field-names draft) skips the budget. Refs: §17, D-0348, D-0723, D-1121.

### Requirement: Usage event per call (INV-23)
Every answered LLM call SHALL write a `usage_event` with its `prompt_kind` and tokens, in its own transaction, charged
to the job budget (a retried call counts twice), and be listed in `extraction.llm_calls` without prompt text.
Enforced by: `tests/db/test_llm_client.py`; active. Refs: §17, D-0346, D-0768.
#### Scenario: Retried call
- **WHEN** a reply is invalid and the retry answers validly
- **THEN** two calls are charged, each with its `prompt_kind` and tokens

### Requirement: Deterministic request hash
`request_hash` SHALL be sha256 of canonical JSON of (prompt_kind, model_class, system, user, output_schema), so
`RecordedLLM` replays hit their cache (INV-10, owned by [evaluation](../evaluation/spec.md)). Refs: D-0350.

### Requirement: Estimated cost from versioned prices
The system SHALL estimate cost for visibility, not billing, from `backend/data/llm/<provider>-pricing.json`
(`llm/pricing.py`); tokens no price covers are `unpriced_tokens` and make the sum's `estimated_usd` null (C7).
`GET /v1/usage/llm` and `/v1/usage/llm/jobs` serve it by UTC day. Refs: §17, D-0719, D-0724.

### Requirement: Grounded values (INV-12)
Every `llm` candidate value SHALL be a verbatim substring of the cleaned text at its stated offsets (INV-12): exact
match at the claim, else the single or nearest exact occurrence, else dropped; no fuzzy matching (`llm/grounding.py`).
Enforced by: `tests/property/test_grounding.py`, `tests/unit/test_grounding.py`; active. Refs: §11, D-0024, D-0379.
#### Scenario: Wrong offsets or not in text
- **WHEN** a claimed value occurs once at other offsets, or not at all
- **THEN** it is accepted with corrected offsets, or dropped as `role C: <field> ungrounded` without the value

### Requirement: Role C input, claims and candidates
Role C SHALL read flat cleaned text, never raw HTML, cut at 40,000 (detail) or 80,000 (listing) characters, and reply
one `{shown, value, start, end}` claim per asked field; a value under `shown: false` is not taken (C7). On a listing
whose first ranked item group (`ParsedPage.item_groups`, [listings](../listings/spec.md)) covers `MIN_ITEMS` or more
items in the cleaned text, it reads those items' spans of the cleaned text only (`content/item_text.py`), in calls of
as many items as their rows' claims fit the reply, up to 200 items, the page fields asked in the first call; each row's
values are grounded in one item (of those holding most of them, the first after the previous row's), a value found
only in another item is dropped, and each grounded span is mapped back to its cleaned-text offsets. Grounded values are
normalized into `Candidate(source_kind='llm', independent=True)`. (Previously: the items were `item_blocks`'.)
Refs: §8.4, D-0025, D-0521, D-1097, D-1478, D-1490, D-1496.
#### Scenario: Field not shown
- **WHEN** a claim is `{shown: false, value: "x"}`
- **THEN** no candidate is made and the field stays `missing`
#### Scenario: Listing items behind a long menu
- **WHEN** a listing's cleaned text holds 60,000 characters of menu before four item blocks
- **THEN** role C reads the four items' text, and a grounded title's locator is its offset in the cleaned text
#### Scenario: Items that repeat their values
- **WHEN** three items show the same title and price and every claim's offsets point at the first
- **THEN** the three rows are grounded in the three items, in page order
#### Scenario: Long listing
- **WHEN** a listing shows 100 items and one call's reply fits 42 rows
- **THEN** role C makes three calls, over items 1–42, 43–84 and 85–100, and records each call

### Requirement: When role C is asked
In cold mode role C SHALL be asked on a detail page only when a required field or group is `missing` (with every
missing optional field in the same call); in `active` mode only for fields the config neither runs nor lists as absent.
A listing calls it once, as [listings](../listings/spec.md) "Role C rows" states. Not in captures replay. The
`c_prefill` variant stores grounded `Ok` values only as a `draft` label, never ground truth
([evaluation](../evaluation/spec.md)). (Previously: a cold listing called it only when structured data gave no rows.)
Refs: §8.4, D-0520, D-1006, D-0538, D-1341, owner #67.

### Requirement: Role S schema drafting
Role S SHALL draft a `SchemaDef` from a prompt plus 1–3 sample pages, or from 1–50 field names and a page kind (top
level exactly those names), stored with `origin='prompt_draft'` under a name hashed from the normalized input, so a
repeat returns the stored draft without a call ([schemas](../schemas/spec.md)). Refs: §5.4, D-0026, D-0449, D-0926.
#### Scenario: Input repeated
- **WHEN** the same prompt (up to whitespace) or the same names in another order are sent again
- **THEN** one `schema_def` row exists and no LLM call is made

### Requirement: LLM output is never executed (INV-17)
Page text SHALL sit in a delimited data section, the model gets no tools, and prompts hold no site names (INV-03, see
`openspec/project.md`). LLM output SHALL never be executed (no `exec`, `eval`, `compile` or shell call); selectors,
recipes and schemas run only in our interpreters. Enforced by: ruff `S` rules and `tests/contracts/test_no_exec.py`;
active. Refs: §11, §18.
#### Scenario: New exec call
- **WHEN** a change adds `eval(` to backend code outside the allowlist
- **THEN** CI fails

### Requirement: Per-key cap on uncharged role S calls
A model call no job pays for (a field-names draft: `POST /v1/schemas/draft`, `schema.fields`) SHALL count against its
API key's `draft_calls` and be refused with `draft_cap_reached` (429) once the key has made `project.draft_call_cap`
of them; null is no cap. A stored draft needs no call and counts nothing. Refs: §17, D-0926, D-1282.
#### Scenario: Key at the cap
- **WHEN** a key with a cap of 1 drafts two different sets of field names
- **THEN** the first is drafted and the second is a 429 with no model call; the first set again is returned stored
