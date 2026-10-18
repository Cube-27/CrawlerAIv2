# Learning and Configs Specification

## Purpose

Everything learned about a site is one portable, executable config IR per (site, schema, page kind), learned,
validated, drift-checked, corrected and exported here (`backend/src/crawlerai/config_ir/`). The LLM client is in [llm](../llm/spec.md); `api_recipe` is in [adapters](../adapters/spec.md).

## Requirements

### Requirement: Config IR
A config SHALL be an `ExtractionConfigIR` (`config_ir/model.py`) with extra keys refused; it may hold site strings
because it is per-site data (C3), the package holds none. Its `schema` reference SHALL hold the schema's name and the
digest of its document at learning; a config whose digest is not the stored document's is neither activated nor
corrected (a schema is edited in place). Refs: §12.1, D-0462, D-0465, D-0950, D-1375. (Previously: the reference held
the name only.)
#### Scenario: Config learned before a schema edit
- **WHEN** a schema's field description is edited after a config was learned for it
- **THEN** activating that config raises `ConfigMismatch`, and correcting it is a 409

### Requirement: Portable steps
Each step SHALL have exactly one selector key, limited to forms both executors run: XPath 1.0 only (`xpath1.py`), CSS
stored with its pinned cssselect translation, a regex subset Python and PCRE both accept (`portable_regex.py`),
JSONPath of RFC 9535 name, wildcard and index segments only (`json_doc.select`), and the post ops in `model.py`. LLM
output is never executed (INV-17, [llm](../llm/spec.md)). Refs: §12.1, D-0034, D-0460, D-1501.
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

### Requirement: Progressive mode
Each (site, schema, page kind) SHALL have a `progressive_state` in mode `cold`, `learning` (pages still served cold)
or `active`; a record has `mode=config` exactly when a config executor ran, else `adhoc`. A schema edit suspends its
active configs and sends its states to `cold`, keeping `pages_extracted`. Refs: §8.4, §5.2, D-0546, D-0614, D-0950.
#### Scenario: Eighth page
- **WHEN** a cold state's eighth `extracted` or `partial` page is stored
- **THEN** a `learn` job is created and the mode becomes `learning`

### Requirement: Learning trigger, sample and job
Learning SHALL start when 8 pages are extracted (or 8 more after a failed run), or on `POST /v1/sites/{host}/learn`;
5 pages form the sample and the rest (≥ 3) are held out. A run is a `job(kind='learn')` charged for role A; every
non-activating end (failure, budget, expiry, shutdown, cancel, schema edit) returns the state to cold with a retry.
Refs: §8.3, D-0030, D-0547, D-0549, D-0622.

### Requirement: Induction, then role A synthesis
Learning's oracle SHALL be the engine's published values, role C's grounded ones (a verbatim span, a DOM claim)
included: fields published on all sample pages are first induced without an LLM from their locators, anchoring only on
stable attributes (`induction.py`), and a listing's row selector and row fields from the item layer's blocks paired with
the published rows, verified by the engine executor (`listing_induction.py`). Role A (`strong`) SHALL run only when
induction leaves a required field, or a whole required group, that some sample page published; it is then asked for
every field left, returns selectors only, verified on the sample with up to 3 repair rounds; a field still failing gets
no steps. Role A's requests SHALL share one system prompt and cache the field definitions and sample pages; a repair
SHALL send the first sample page only, in the first request's output schema, and a sample page's input SHALL be at most
60,000 characters. Refs: §8.3, D-0031, D-0551, D-0585, D-1680, D-1683, D-1720, D-1722, D-1723.

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

### Requirement: Activation and active-mode extraction
A validated config with at least one field SHALL become version max+1 and the one `active` config (the previous one
`suspended`), unless the project's `require_config_approval` is on: then it is stored `pending_approval`, what served
before goes on serving, no run starts while it waits (a forced run may, and replaces it), `POST /v1/configs/{id}/approve`
activates it and `POST /v1/configs/{id}/reject` suspends it, the state then waiting for 8 more pages before it learns
again. In `active` mode a field the config runs SHALL NOT be asked of role C, even when its step misses.
(Previously: no reject.) Refs: §8.3, §8.4, D-0569, D-0615, D-0783, D-1342, D-1391.
#### Scenario: Covered field missing
- **WHEN** a covered field's steps match nothing on a page
- **THEN** it stays `missing` and no LLM call is made for it
#### Scenario: Approval required
- **WHEN** a run validates a config while `require_config_approval` is on
- **THEN** the config is `pending_approval`, pages are served as before, and it serves only once approved
#### Scenario: Rejected
- **WHEN** a `pending_approval` config is rejected
- **THEN** it is `suspended`, the config serving before stays active, and no run starts until 8 more pages are extracted

### Requirement: Drift suspension
Config-mode pages SHALL feed a per-field 50-page window; from 3 pages, a field whose yield or validity falls below its
baseline minus the margins in `backend/data/drift_margins.json` (fitted on the golden set only,
[evaluation](../evaluation/spec.md)) is `suspended`, falls back to cold extraction and triggers re-learning.
Refs: §8.3, D-0032, D-0571.
#### Scenario: Layout change
- **WHEN** a field matches on 1 of the last 10 pages after validating at yield 1.0
- **THEN** it is suspended, role C may fill it, and a learn job runs

### Requirement: Operator corrections and config API
The system SHALL serve config list, read and `PUT /v1/configs/{id}` on the latest version (else 409). A correction is
version+1 with `origin=operator`, validated on the 8 latest pages; it activates only if every operated field is kept,
else it is stored `draft` while the previous version serves (C5). Refs: §13.1, D-0033, D-0593.
#### Scenario: Correction fails validation
- **WHEN** an operator's new steps are not reproduced on the held-out pages
- **THEN** a `draft` version with the report is returned and the active version is unchanged

### Requirement: Config and record exporters
`POST /v1/configs/{id}/export` SHALL return `json` (the IR) or `platform_draft` (`draft: true` until OPEN_QUESTIONS
#1) with the release-check report. Record exports (`exporters/records.py`) keep values as published (INV-27);
`csv_safe=true` prefixes `'` to formula-like cells, default unchanged. Refs: §12.2, D-0606, D-0879.
#### Scenario: Formula-like cell
- **WHEN** a published value is `=1+1`
- **THEN** the CSV cell is `'=1+1` with `csv_safe=true` and `=1+1` without

### Requirement: Release check (INV-20)
An exported field SHALL reproduce the engine's value on every held-out page while fewer than 10, and on ≥ 95% from 10
on, or be marked `manual` (INV-20). The release executor imports nothing from `crawlerai` but the IR model and is the
one allowed second parse (INV-26). Enforced by: `tests/unit/test_release_check.py`, `test_release_executor.py`
(unit and property); active. Refs: §12.3, D-0527, D-0605.
#### Scenario: 94% of 20 pages
- **WHEN** a field reproduces on 18 of 20 held-out pages
- **THEN** the export marks it `manual: true`

### Requirement: Absent fields
On a detail schema, learning SHALL list in the config's `absent` (field status `absent`) each required field or
required-group member that no page of the run published or gave a valid candidate for from any source while role C was
asked on every page outside config mode, where it is asked for every gap (`config_ir/absent.py`). Role C is not asked for it in config mode, where it stays `missing` with
reason `absent`; a config page that publishes it removes it and starts a forced re-learn. Refs: D-0784, D-1341, D-1347.
#### Scenario: A field no page states
- **WHEN** a required sku is stated by no source on any of the 8 pages a run reads, and role C was asked on each
- **THEN** the config lists `sku` as absent and a config-mode page asks role C nothing for it

### Requirement: Executability classes
Each field of a config, each row field and a listing's `next` SHALL have an executability class from its steps alone:
`static-html` (the page's HTML, its JSON-LD or the JSON of its inline scripts), `needs-browser` (a captured response),
`api-call` (the response of the config's API recipe) or `unexecutable` (a suspended field, or an `api` source without a
recipe); a field with several steps takes the most demanding. The config release check SHALL report each field's class
and the count of fields per class. Enforced by: `tests/unit/test_config_executability.py`, `test_release_check.py`; active.
Refs: D-1724, D-1725.
