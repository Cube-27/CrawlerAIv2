# Delta: llm

## ADDED Requirements

### Requirement: Per-key cap on uncharged role S calls
A model call no job pays for (a field-names draft: `POST /v1/schemas/draft`, `schema.fields`) SHALL count against its
API key's `draft_calls` and be refused with `draft_cap_reached` (429) once the key has made `project.draft_call_cap`
of them; null is no cap. A stored draft needs no call and counts nothing. Refs: §17, D-0926, D-1282.
#### Scenario: Key at the cap
- **WHEN** a key with a cap of 1 drafts two different sets of field names
- **THEN** the first is drafted and the second is a 429 with no model call; the first set again is returned stored
