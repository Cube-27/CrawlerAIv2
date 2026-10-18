## ADDED Requirements

### Requirement: Prompt caching
A request SHALL be able to name leading parts of its user message that repeat across requests (`cached`); a provider
that caches prompts SHALL cache the prompt up to the end of each part. The client SHALL report each call's tokens read
from and written to the cache, record them in the usage metadata of the call's rows (the call's prompt length counts
them) and price them at the model's cache prices; a call whose cache tokens have no cache price is unpriced (C7).
Refs: D-1720, D-1721.

## MODIFIED Requirements

### Requirement: Deterministic request hash
`request_hash` SHALL be sha256 of canonical JSON of (prompt_kind, model_class, system, user, output_schema and, when the
request has any, its cached parts), so `RecordedLLM` replays hit their cache (INV-10, owned by
[evaluation](../evaluation/spec.md)). Refs: D-0350, D-1721.
(Previously: without the cached parts.)

### Requirement: Estimated cost from versioned prices
The system SHALL estimate cost for visibility, not billing, from `backend/data/llm/<provider>-pricing.json`
(`llm/pricing.py`), cache read and write tokens at the file's cache prices; tokens no price covers are
`unpriced_tokens` and make the sum's `estimated_usd` null (C7). `GET /v1/usage/llm` and `/v1/usage/llm/jobs` serve it by
UTC day. Refs: §17, D-0719, D-0724, D-1721.
(Previously: input and output tokens only.)
