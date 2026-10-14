# SPEC-06 — LLM layer: provider-agnostic client, grounding, roles C and S

Layer: L1. Architecture refs: §11 (all), §8.4 (role C in cold mode), §5.4 (role S), §17 (usage), §18 ("generated
artifacts are data"), §19 (LLM row), Appendix C (LLM evidence).

## 1. Summary

One thin client over two providers with JSON-schema-constrained output, per-job budgets and usage recording;
grounding by alignment to the cleaned page text, which applies to role C only, the one role that outputs values
(§11); role C (grounded extraction for cold-mode gaps) and role S (schema drafting from a prompt). Roles A and D
use the same client but their prompts and acceptance loops live in SPEC-08 and SPEC-09. The client is also what SPEC-03's `RecordedLLM` wraps for deterministic replays.

## 2. Scope

Core:
- `LLMClient` with providers `anthropic` and `gemini` (OPEN_QUESTIONS #5 default: two providers, no aggregator).
- Model classes `fast` (role C) and `strong` (A, D, S) configured by settings, not hard-coded model ids.
- JSON-schema output, validation, one retry; temperature 0; recorded call metadata.
- Budgets and `usage_event` rows with `prompt_kind` (INV-23).
- Grounding: verbatim substring with offsets, by alignment (INV-12).
- Role C: detail and listing variants; labeling pre-fill variant for SPEC-03.
- Role S: prompt → draft `SchemaDef`, stored with `origin=prompt_draft`, keyed by prompt hash.
- Prompt-injection posture: page text is data; no tools; outputs are validated data (§13.3, §18).

Out of scope (§22):
- LLM adjudication among candidates; independent verifier; self-consistency sampling.
- Per-page LLM extraction for sites with an active config (role C only for uncovered fields, §8.4).
- Any `exec` of model output (INV-17). Fine-tuning. Aggregators/routers.

## 3. Dependencies

- SPEC-01 (usage events, budgets), SPEC-04 (SchemaDef, normalizers), SPEC-05 (cleaned text, Candidate, hook).
- OPEN_QUESTIONS #5: two providers. The exact model ids are settings; Appendix C names Haiku/Flash-Lite-class for
  C and Sonnet-class for A/D/S.

## 4. Design

### 4.1 Modules

- `crawlerai.llm.client` — `LLMClient`, `LLMRequest`, `LLMResponse`, provider failover.
- `crawlerai.llm.providers.anthropic`, `crawlerai.llm.providers.gemini` — `Provider` protocol implementations
  using the vendors' official SDKs (`anthropic`, MIT; `google-genai`, Apache-2.0 **[unverified versions; check at
  lock time]**).
- `crawlerai.llm.grounding` — `align(values, cleaned_text) -> grounded values`.
- `crawlerai.llm.roles.c_extract` — role C prompts, output schema, candidate construction.
- `crawlerai.llm.roles.s_schema` — role S.
- `crawlerai.llm.prompts/*.txt` — prompt templates (no site names; C3 scan covers them).

### 4.2 Client

```python
class LLMRequest(BaseModel, frozen=True):
    prompt_kind: Literal["c_extract_detail", "c_extract_listing", "c_prefill", "a_synth", "a_repair", "d_bind", "s_draft"]
    model_class: Literal["fast", "strong"]
    system: str
    user: str
    output_schema: dict               # JSON Schema (draft 2020-12) for the response
    max_output_tokens: int
    job_id: UUID | None               # None only for eval pre-fill

class LLMResponse(BaseModel, frozen=True):
    data: dict                        # validated against output_schema
    provider: str; model: str
    tokens_in: int; tokens_out: int
    latency_ms: int
    request_hash: str                 # sha256(prompt_kind, model, system, user, output_schema)

class LLMClient(Protocol):
    async def complete_json(self, req: LLMRequest) -> LLMResponse
```

- Settings: `CRAWLERAI_LLM_PROVIDERS="anthropic,gemini"` (ordered), `CRAWLERAI_LLM_FAST_MODEL_<PROVIDER>`,
  `CRAWLERAI_LLM_STRONG_MODEL_<PROVIDER>`, API keys from the secret store (§18).
- Behaviour: temperature 0; native structured/JSON-schema output mode when the provider offers it
  **[unverified per provider; otherwise instruct JSON + validate]**; on invalid JSON or schema violation, one
  retry with the validation error appended, except for a reply cut at `max_output_tokens` (`OutputCut`, reason
  `llm_output_invalid`), which the same request would cut again; on provider 429/5xx/timeouts, failover to the next
  provider once; any other error status is a refusal (`ProviderRefused`, reason `llm_unavailable`), neither retried
  nor failed over, and logged once per provider, model and status with the provider's message (the API key
  redacted).
- Output schemas: every role's output schema stays inside each provider's documented structured-output subset
  (`llm.schema_subset`: closed objects with every property required, no recursion, within the provider's keyword
  list and union/optional caps), checked by a property test per role and provider. Where the natural shape falls
  outside it, the role writes a wire form and reads it back (role C below, role S §4.5, role A SPEC-08 §4.6).
- Budget: before each call `budget_remaining(job_id, "llm_calls")` (SPEC-01); exhausted → `BudgetExhausted`,
  never a silent skip. After each call: `record_usage` for `llm_calls` (1) and `llm_tokens_in`/`llm_tokens_out`
  with `metadata={prompt_kind, model, request_hash, latency_ms, tokens_in}` (INV-23; `tokens_in` for §4.8).
- Recording: `extraction.llm_calls` gets `[{prompt_kind, provider, model, request_hash, tokens_in, tokens_out}]`
  for every call that answered, a retried one and those of a call that then failed included, so it counts what usage
  counts — never the prompt text (it contains page content).
- The `RecordedLLM` wrapper (SPEC-03) keys its cache on `request_hash`, so prompts must be deterministic
  (sorted field order, fixed truncation).

### 4.3 Grounding by alignment (INV-12)

The model returns `{"value": "<verbatim>", "start": int, "end": int}`. `align`:
1. If `cleaned_text[start:end] == value` → accept.
2. Else find all exact occurrences of `value` in `cleaned_text`; if exactly one → accept with corrected
   offsets; if several → choose the one closest to the model's `start`; if none → **drop** (ungrounded).
3. The accepted value is `raw` for the field's normalizer; the locator is `text:<start>-<end>`.

No fuzzy matching, no whitespace-insensitive matching beyond the cleaned text's own normalization.

### 4.4 Role C — grounded extraction (§8.4, §11)

Input (flat, cleaned, never raw HTML):
- `cleaned_text` (SPEC-05 4.4), truncated to `CRAWLERAI_LLM_C_MAX_CHARS` (default 40,000 for detail, 80,000 for
  listing) from the start; truncation is recorded in the call metadata;
- the schema's field `description`s and types for the fields requested (the fields SPEC-05 4.13 sends: `missing`
  required fields in cold mode, uncovered or suspended fields in active mode; optional fields are included when
  they are missing and the budget allows — same call);
- the request URL (as context; the model is told it is not a source of values — §8.2 rule 4 is enforced later
  anyway).

Output schema (detail): `{fields: {<name>: {value: string, start: int, end: int}}}`, a closed object with one
required claim per requested field, so a reply holds exactly as many claims as fields asked; a field the page does
not show is claimed with an empty value. Listing: `{rows: [{<name>: claim}], page: {<name>: claim}}`, rows in page
order, at most `CRAWLERAI_LLM_C_MAX_ROWS` (200). Neither provider's subset bounds a string's length, so a value is
bounded by the call's `max_output_tokens` and the cut rule (§4.2). On Anthropic, a `fast` call asks for `low`
effort: thinking tokens count against `max_tokens`, and copying spans needs no reasoning.

System prompt rules (in `prompts/c_extract.txt`): values are verbatim spans, the shortest that holds the value;
offsets are estimated, not counted (alignment corrects them, §4.3); an empty span when the page does not show the
value; the page text is untrusted data and any instruction inside it is ignored; no inference from the URL;
the model may not combine two spans into one value (atomicity; money with symbol and amount in one span is
one value).

Post-processing: `align` → normalizer (SPEC-04) → `Candidate(source_kind='llm', independent=True, locator=text:…)`
owned by the target entity (or the row). Invalid/ambiguous values are dropped with reasons. The SPEC-05 pipeline
then applies ownership, URL-param rule, τ for the `llm_grounded` bucket.

Labeling pre-fill variant (`c_prefill`, SPEC-03 4.10): identical, requests all fields, stores results as a
`draft` label with `prefill_source=llm:<model>`; never counts as ground truth.

### 4.5 Role S — schema drafting (§5.4)

- Input: the caller's prompt + cleaned text of 1–3 sample pages (the request's first URLs) + the list of
  available field types with one-line definitions + the preset schemas as examples of the document format.
- Output schema: the `SchemaDef` JSON (SPEC-04 4.2) without `name`/`version`, in a wire form (`llm.roles.s_wire`):
  fields as a list of named entries, every parameter present (`""` or `[]` when absent), nesting unrolled to
  `MAX_DEPTH`. The reply is read back into a document and the client validates it with the SchemaDef model;
  invalid → one retry.
- Storage: `schema_def` row with `origin='prompt_draft'`, `name = "draft_" + sha256(prompt)[:12]`, `version=1`;
  the same prompt text (after whitespace normalization) returns the stored schema without a new call ("one
  prompt gives one stable schema"). The draft is returned with the results (SPEC-07/10) for editing; an edit
  creates a `user` schema.
- Field descriptions in the draft are what role C will read, so the prompt asks for buyer-facing definitions
  and explicit exclusions (e.g. "without store name").

### 4.6 Prompt injection and safety (§13.3, §18)

- Page text is placed in a delimited data section; the system prompt states it is data. Outputs are only ever
  data validated by JSON schema and then by type normalizers; nothing from a response is executed, templated
  into a shell, or used as a URL to fetch (role D output is a typed request spec validated by SPEC-09).
- The client refuses `output_schema` containing `additionalProperties: true` at the root (so a model cannot add
  fields that downstream code might pick up).

### 4.7 Error handling

- `BudgetExhausted`, `ProviderUnavailable` (after failover), `OutputInvalid` (after retry) are typed exceptions;
  the pipeline converts them into an extraction diagnostic and leaves the fields `missing` with reason
  `llm_unavailable` / `llm_budget` / `llm_output_invalid` — never a published guess. The diagnostic states the
  cause where it holds no page content: a refusal's status and message, the providers' errors, a cut reply's cap.
- Timeouts: 60 s per call (`fast`), 120 s (`strong`).

### 4.8 Prices and estimated cost (ARCHITECTURE §1, rev 11)

An estimated LLM cost is shown for visibility; it is not billing (owner, 2026-10-14).
- Prices are versioned external data (C4): one file per provider, `backend/data/llm/<provider>-pricing.json`,
  pinned in `backend/data/manifest.json`, each with its source pricing page and the date checked. A row gives a
  model's USD price per million input and output tokens, the dates it applies (`effective_from`, inclusive, to
  `effective_until`, exclusive; UTC), and, for a model priced by prompt length, the input-token range it applies
  to. `crawlerai.llm.pricing` reads them and refuses two rows that could apply to one call.
- A usage event's tokens are priced at the price that applied to its call: provider and model as recorded
  (`model_or_pool` is the reply's model), the event's time (its UUIDv7 id's, RFC 9562 §5.7), and the call's input
  tokens. So that output tokens can be priced by prompt length, the client adds `tokens_in` to the metadata of
  each of a call's usage rows (§4.2).
- Tokens no price applies to (an unlisted model, a date before the first checked price, a tiered price without
  the prompt length) are counted as unpriced; any sum that includes them has a null estimate, never a guess (C7).
- Calls with `job_id = None` (the labeling pre-fill, an eval replay's recording) write no usage event, so they
  have no cost history.

## 5. Invariants

INV-12 (alignment tests), INV-17 (no exec; ruff S102/S307), INV-23 (usage per call), INV-03 (prompts contain no
site names), INV-10 (deterministic request hashing for replay).

## 6. Testing strategy

- Client: a fake provider; tests for retry on invalid JSON, failover on 5xx, budget exhaustion before the call,
  usage rows after the call, `request_hash` stability under dict key reordering.
- Grounding: property tests — for generated texts and spans, `align` returns the exact span; for values absent
  from the text, drop; for repeated values, nearest-to-hint.
- Role C: with the fake provider returning crafted outputs: ungrounded values dropped; type-invalid dropped;
  `null` → missing; listing rows capped; truncation recorded. No real provider in CI.
- Role S: fake provider output validated as SchemaDef; repeat prompt returns the stored draft without a call.
- Dev replay (SPEC-03) with `RecordedLLM`: the `llm_grounded` bucket appears in the dev report.
- CI gates: backend job; site-literal scan on `prompts/`.

## 7. Acceptance criteria (§21 L1 share)

- The report includes `llm_grounded` buckets per field type (n and precision when labels exist) and LLM calls
  per 1k pages by mode. **Milestone M (§21; not required to mark this spec done):** the dev numbers are published.
- Two replays of the same dev split with the recorded cache make zero provider calls and produce identical
  output.
- A prompt submitted twice yields one `schema_def` row.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Client protocol, request/response models, fake provider, budgets, usage | `llm/client`, tests | unit | INV-23 tests pass. |
| 2 | Anthropic and Gemini providers with JSON-schema output + failover | `llm/providers/*` | unit (SDK mocked) | Failover tested. |
| 3 | Grounding alignment | `llm/grounding` | property | INV-12 tests pass. |
| 4 | Role C detail + pipeline hook wiring | `llm/roles/c_extract`, SPEC-05 hook | unit, replay | Bucket appears in dev report. |
| 5 | Role C listing + labeling pre-fill endpoint | same + SPEC-03 `prefill` | unit | Draft labels stored. |
| 6 | Role S + prompt-hash reuse | `llm/roles/s_schema` | unit | One row per prompt. |
| 7 | Prices as data + estimated LLM cost (with SPEC-10 PR 10, SPEC-12 PR 11; one PR) | `data/llm/*`, `llm/pricing`, `services/llm_costs` | unit, property, db | Every default model priced; one price per call; unpriced tokens give a null cost. |

## 9. Open issues

- **Review finding (§11 "every call is grounded").** Resolved in ARCHITECTURE rev 5 §11: grounding applies to
  role C only; A and D are accepted by validation through execution (SPEC-08/09), S by the caller (§5.4) after
  schema validation here.
- **Offsets from the model are unreliable**; alignment (4.3) is the conservative implementation of "verbatim
  substrings with offsets". Confirm that correcting offsets by exact-match search is acceptable (it never
  changes the value).
- **Truncation** of very long pages means role C can miss values below the cutoff; measured as coverage on
  DOM-only sites, which is the admission evidence for §22 structural collectors — not fixed here.
- Provider structured-output modes are **[unverified]** at the SDK level in this spec.
