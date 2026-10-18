## MODIFIED Requirements

### Requirement: Portable steps
Each step SHALL have exactly one selector key, limited to forms both executors run: XPath 1.0 only (`xpath1.py`), CSS
stored with its pinned cssselect translation, a regex subset Python and PCRE both accept (`portable_regex.py`),
JSONPath of RFC 9535 name, wildcard and index segments only (`json_doc.select`), and the post ops in `model.py`. LLM
output is never executed (INV-17, [llm](../../../../../specs/llm/spec.md)). Refs: §12.1, D-0034, D-0460, D-1501.
(Previously: any JSONPath starting with `$`.)
#### Scenario: Non-portable selector
- **WHEN** a step uses `matches()` in its `xpath` or `$.name` as its JSONPath, or a bump changes a pinned translation in
  `css_translations.json`
- **THEN** the IR is refused, or CI fails before stored IRs stop loading

### Requirement: Engine executor
The engine executor SHALL run each field's steps in order over the shared `ParsedPage` (no second parse, INV-26); the
first step giving an `Ok` value becomes `Candidate(source_kind='config', independent=False)`. A `jsonld` or `jsonpath`
step's value is read as the structured collectors read it (`schema_org_map.fragment_read`), in both executors. A config
for another schema or page kind raises `ConfigMismatch`. Refs: §12.1, D-0475, D-0480, D-1502.
(Previously: a structured value was taken as written.)
#### Scenario: First step fails, second valid
- **WHEN** step 0's value is declined and step 1 gives an `Ok` value
- **THEN** the candidate is step 1's value
#### Scenario: Description written as markup
- **WHEN** a long_text field's `jsonld` step selects `<h2>Role</h2><p>We</p>`
- **THEN** both executors give `Role\nWe`, the value the JSON-LD collector publishes

### Requirement: Held-out validation and corroboration
On ≥ 3 held-out pages a field SHALL be kept only when its values are `Ok` and both the engine and release executors
reproduce the engine's published value; others are dropped and listed in the `validation_report`. A listing's engine
rows are aligned with the config's in document order as a subsequence (`row_alignment.py`), here and in the release
check: an engine row aligned with none is not reproduced. A kept field is `corroborated` when it matches every
structured or adapter reference on ≥ 3 comparable pages (≥ 90% from 10 on), else `uncorroborated`; operator fields are
`operator`. Refs: §8.3, §10, D-0563, D-0565, D-0567, D-1500.
(Previously: rows were compared by position and only when the counts were equal.)
#### Scenario: Release executor disagrees
- **WHEN** the engine executor reproduces a value and the release executor does not
- **THEN** the field is dropped from the config
#### Scenario: Role C left items out
- **WHEN** the config selects rows A, B, C, D on a held-out page where the engine published B and D
- **THEN** B and D are compared with the config's B and D, and the field is kept when they agree
