## MODIFIED Requirements

### Requirement: LLM gap hook
The system SHALL ask role C ([llm](../llm/spec.md)) once per detail page only for missing required fields and unfilled
required groups (in `active` mode only those the config neither covers nor lists as absent, which stay `missing` with
reason `absent`); `conflict`, `abstained`, `object` and `list<object>` fields are never sent, and its candidates pass
the same stages as `llm_grounded`. Refs: §8.4, D-0489, D-0797, D-1341.
