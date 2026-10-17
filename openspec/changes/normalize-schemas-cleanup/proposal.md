# Change: normalizer, schema and worker cleanups

## Why

Eleven follow-ups left by merged PRs (#208, #210, #215, #216, #221, #223, #240, #247, #248) are each too small for a
change of their own and touch neighbouring code: the normalizers still miss two text forms the ATS adapters hand over,
money keeps its own copy of the number steps, a country code list includes reserved codes, a location cannot say "not
stated", schema documents and config IRs are not tied to the vocabulary and document they were written for, and a few
constants, signatures and spec texts disagree with the code.

## What Changes

- **Normalizers**: the range normalizer reads an interval stated as text (`1 YEAR`, `per year`, ISO 8601 durations,
  UN/CEFACT codes) and the date normalizer reads `2026-10-15 09:31:36 UTC`; money reads its amount through
  `numbers.stated`; `iso_3166_alpha2` drops ISO 3166-1's exceptional reservations; a location's `remote_flag` is `true`
  or `null`.
- **Schemas and configs**: `schema_org` paths and `schema:` references of a created or edited schema are checked against
  the pinned schema.org vocabulary; `SchemaRef` carries the schema document's digest, so a config learned before an
  edit is neither activated nor corrected.
- **API and worker**: `fetch_failed` is dropped (nothing raises it); the LLM setup docstring names the codes; the page
  handlers require their `llm` client (tests pass `NO_LLM`).
- **Jobs**: INV-28 is amended: LLM provider and model settings are deployment settings, recorded per call, not pinned.
- **Shared constants**: `core/retry.py` holds the first backoff (the queue's and politeness's) and the transient-status
  rule (LLM providers and the Shopify adapter).
- **Specs**: identity and intent move from `resolution` into the new `identity-and-intent` capability.

## Impact

- Capabilities: [normalization](../../specs/normalization/spec.md), [schemas](../../specs/schemas/spec.md),
  [learning-configs](../../specs/learning-configs/spec.md), [jobs](../../specs/jobs/spec.md),
  [resolution](../../specs/resolution/spec.md), new `identity-and-intent`; `openspec/project.md` capability table.
- Design: D-0960, D-0240, D-0950, D-0631, D-1305, D-1263; INV-28.
- Files: `backend/src/crawlerai/{normalize,collect/schema_org_map.py,services/{schemas,configs}.py,config_ir,core/retry.py,
  db/queue.py,acquire/politeness.py,llm,adapters/shopify.py,worker/handlers}`.
