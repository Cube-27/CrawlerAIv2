# Learning and Configs Specification

## Purpose

Everything learned about a site is one portable, executable config IR per (site, schema, page kind). This
capability covers the IR and its engine executor, progressive mode (cold, learning, active), learning (induction,
role A synthesis, held-out validation, corroboration, activation), drift, operator corrections, the config and record
exporters, and the release check. The LLM client and role C live in [llm](../llm/spec.md); `api_recipe` learning and
execution live in [api-backed-pages](../api-backed-pages/spec.md).
Design rationale: [ARCHITECTURE §8.3–§8.4](../../design/extraction.md), [§12](../../design/config-ir.md). History: [SPEC-08](../../changes/archive/2026-10-13-spec-08-config-ir-learning-progressive/SPEC-08-config-ir-learning-progressive.md) and its [decisions](../../changes/archive/2026-10-13-spec-08-config-ir-learning-progressive/decisions.md); cross-cutting entries in the [decisions log](../../decisions/log.md).

## Requirements

### Requirement: Config IR
A config SHALL be an `ExtractionConfigIR`: `ir_version: "1"`, `site`, `schema: {name}`, `page_kind`,
`fetch: {method: http|browser}`, `fields` (each with at least one step and a `status`), optional `listing`
`{row, fields, next}`, optional `api_recipe`, and `provenance {origin: adapter|induced|llm_synth|operator,
validated_on, learned_at, engine_version}`; extra keys are refused. Site-specific strings are allowed in the IR because
it is per-site data (C3); the `config_ir` package itself holds none.
Refs: §12.1, SPEC-08 §4.2, D-0462, D-0465, Appendix A #43.

#### Scenario: Unknown key
- **WHEN** a stored IR has a key the model does not define
- **THEN** it is refused on load

### Requirement: Portable steps
Each step SHALL have exactly one selector key: `xpath` (XPath 1.0 only: a W3C function-name allowlist, no variable
references or namespace prefixes), `css` (translated by cssselect's `HTMLTranslator` and stored with that `xpath`; a
differing stored `xpath` or a pseudo-element is refused), `jsonld` (with optional `when_type`), `jsonpath` (with
required `source`: `jsonld|js_state|xhr|api`), `regex` (a subset Python `re` and PCRE both accept, compiled
`re.ASCII`; caseless patterns ASCII only), or `attr`. Post ops: a type normalizer op (checks the value is `Ok`, never
transforms), `trim`, `regex_replace` (replacements `\1`–`\9` only), `absolutize_url` (declines `no_base_url` without a
base, C7). LLM output is never executed (INV-17).
Refs: §12.1, SPEC-08 §4.2, D-0034, D-0460, D-0461, D-0463, D-0464, D-0478, D-0609, D-0878.

#### Scenario: XPath 2 function
- **WHEN** a step uses `matches()` in its `xpath`
- **THEN** the IR is refused

#### Scenario: cssselect upgrade
- **WHEN** a dependency bump changes one of the 32 pinned translations in `css_translations.json`
- **THEN** CI fails before stored IRs stop loading

### Requirement: Engine executor
The engine executor SHALL run each field's steps in order over the shared `ParsedPage` (no second parse, INV-26);
the first step whose value passes its post ops and normalizer wins and becomes
`Candidate(source_kind='config', independent=False, locator=config:<field>:<i>:<selector>)`. If no step is valid, the
first step that matched is proposed with its decline; a single-valued multi-match is `Invalid("multi_match")`.
`regex`, `jsonld` and `jsonpath` read the whole page and are refused in a listing row; `jsonpath` uses the engine's
RFC 9535 name/wildcard/index subset (`unsupported_jsonpath` otherwise). A config for another schema name or page kind
raises `ConfigMismatch`.
Refs: §12.1, SPEC-08 §4.3, D-0475, D-0477, D-0479, D-0480, D-0481, D-0482.

#### Scenario: First step fails, second valid
- **WHEN** step 0 matches a value the normalizer declines and step 1 gives an `Ok` value
- **THEN** the candidate is step 1's value

### Requirement: Progressive mode
Each (site, schema, page kind) SHALL have a `progressive_state` with `mode` `cold` (new, or its schema was edited;
collectors, resolution and role C for gaps; record `mode=adhoc`), `learning` (a run in flight, pages still served
cold; `adhoc`) or `active` (collectors plus the active config; `mode=config`). The record mode is `config` exactly
when a config executor runs. Database checks tie `learning` to `learning_started_at` and `active` to
`active_config_id`.
Refs: §8.4, Appendix A #23, SPEC-08 §4.4, §4.8, D-0546, D-0550, D-0614.

#### Scenario: New site
- **WHEN** a schema extracts a page of a site seen for the first time
- **THEN** the record has `mode=adhoc` and the state is `cold`

### Requirement: Learning trigger and sample
Learning SHALL start when `pages_extracted` (outcome `extracted` or `partial`) reaches 8 (or `retry_at_pages` after a
failed run, set to `pages_extracted + 8`), checked by the scheduler's `trigger_learning` every minute, or on
`POST /v1/sites/{host}/learn {schema_id, force=false}` (202 `{job_id}`; 409 while a run is in flight or when active
without `force`; 404 for an unknown site or schema). A run reads the 8 latest extracted pages: the 5 with the most
published required values form the sample, the rest (≥ 3) are held out, and later pages join the held-out set. An
active state re-learns only when forced and keeps serving its config meanwhile.
Refs: §8.3, SPEC-08 §4.4, D-0030, D-0547, D-0548, D-0592, D-0621.

#### Scenario: Eighth page
- **WHEN** a cold state's eighth `extracted` or `partial` page is stored
- **THEN** a `learn` job is created and the mode becomes `learning`

### Requirement: Learn job lifecycle
A run SHALL be a queued `job(kind='learn')` naming its state, polled by the worker every 30 s and charged for role A.
It ends `completed` when it activates; `failed` on refusal, an LLM failure, an error, `expired` (still running after
1 h, by `expire_learn_runs`), `shutdown` (the worker stops) or `schema_edited`; `cancelled` on a cancel before it
activates. Every non-activating end returns the state to cold with a retry; the `learning_finished` event carries
`config_id`, `reason` and the validation report. A run whose state got an operator config while in flight ends
`operator_config` without activating.
Refs: SPEC-08 §4.8, §4.13, D-0549, D-0588, D-0622, D-0623, D-0711, D-0712, D-0713, D-0836, D-0876, D-0950.

#### Scenario: Budget exhausted during synthesis
- **WHEN** role A raises `BudgetExhausted`
- **THEN** the job ends `failed`, nothing activates and the state retries after 8 more pages

### Requirement: Induction without an LLM
For detail pages, a field published on all 5 sample pages SHALL be induced from its locators: `jsonld` paths (indices
as `[*]`, then as written, per enclosing typed node with `when_type`); `adapter:`/`api:` locators from their mapping
(`origin=adapter`); `microdata:`/`config:` XPaths generalized by dropping positional predicates and anchoring on
`@id`, `@itemprop`, `@data-*` or stable class tokens (`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, no digit run ≥ 3), read as
`normalize-space(...)` or an attribute. A selector is kept only if on every sample page the engine executor gives one
node and an `Ok` value equal to the published one. Role C (`text:`) fields, listing fields and list fields without
`jsonld` go to synthesis.
Refs: §8.3 step 1, SPEC-08 §4.5, D-0031, D-0551–D-0558.

#### Scenario: Hashed class token
- **WHEN** the only anchor is a class token `c-x83k21`
- **THEN** it is not used as an anchor

### Requirement: Role A synthesis
Fields not induced SHALL be sent to role A (`a_synth`, model class `strong`) with the field descriptions, the 5 sample
pages as reduced HTML (no `script`/`style`; attributes `id`, `class`, `data-*`, `itemprop`, `href`, `src`, `content`,
`name`, `property`; cut to `CRAWLERAI_LLM_A_MAX_CHARS`, default 120,000, around the published values), JSON key paths
(20,000 characters) and the published values. The reply is `{fields: [{field, steps}]}` in the `step_wire` form,
selectors only. Steps are verified on the sample; up to 3 repair rounds (`a_repair`) ask only for failing targets with
up to 10 diagnostics each (`no_match`, `multi_match(n)`, `value_mismatch`, `invalid_xpath`); fields still failing get
no steps. A listing needs a `row` selector with ≥ 3 rows per sample page; `next_page_url` becomes `listing.next`.
Row-mapped fields (SPEC-13 §4.9) are neither induced nor synthesized.
Refs: §8.3 step 2, §11, SPEC-08 §4.6, D-0585–D-0590, D-1008.

#### Scenario: Repair limit
- **WHEN** a field still fails after the third repair round
- **THEN** it has no steps and the config covers fewer fields

### Requirement: Held-out validation
On ≥ 3 held-out pages a field SHALL be kept only when: single-valued fields match exactly once wherever the engine
published them; every value is `Ok`; and both the engine executor and the release executor reproduce the engine's
published value (`equal`). A listing needs ≥ 3 rows per page, row fields compared in document order with equal row
counts. A field published on no held-out page is dropped (`never_published`); failing fields are dropped, not
activated.
Refs: §8.3 step 3, SPEC-08 §4.7, D-0563, D-0564, D-0566.

#### Scenario: Release executor disagrees
- **WHEN** the engine executor reproduces a value and the release executor does not
- **THEN** the field is dropped from the config

### Requirement: Corroboration status
Each kept field SHALL get `corroborated` when the config's value equals every structured or adapter reference on each
comparable held-out page (≥ 3 comparable pages; all of them while fewer than 10, ≥ 90% from 10 on), `operator` when
set by an operator (kept by validation), `uncorroborated` otherwise, and `suspended` by drift. Evidence buckets are
`config_corroborated` and `config_uncorroborated` (`operator` uses the latter).
Refs: §8.3 step 4, §10, SPEC-08 §4.7, D-0565, D-0568.

#### Scenario: Two comparable pages
- **WHEN** only 2 held-out pages carry a JSON-LD value for the field
- **THEN** the field is `uncorroborated`

### Requirement: Validation report
The `validation_report` SHALL list every schema field with `pages`, `matched`, `valid`, `reproduced`, `published`,
`comparable`, `corroborated_on`, `status`, `yield` (matched/pages), `validity` (valid/matched) and `dropped`; an
unlearned field reports `dropped: "not_learned: <reason>"` (at most 200 characters). The report adds `held_out`,
a `listing` section and `refused` (`too_few_held_out`, `no_field_kept`).
Refs: SPEC-08 §4.7, D-0567, D-0776.

#### Scenario: Field without steps
- **WHEN** neither induction nor synthesis gave steps for a required field
- **THEN** the report lists it with `status: null` and its `not_learned` reason

### Requirement: Activation
A validated config with at least one field SHALL be stored as version max+1 of its (site, schema, page kind) with
status `active`, the previous active version becoming `suspended`, `provenance.validated_on` listing the held-out
capture ids, and the state `active`. A refused run leaves the state `cold`.
Refs: §8.3 step 5, SPEC-08 §4.8, D-0569, D-0617.

#### Scenario: Activation
- **WHEN** validation keeps 6 fields
- **THEN** the new version is the one active config and repeat pages publish with `mode=config`

### Requirement: Active-mode extraction
In `active` mode `config` candidates SHALL enter resolution like any other; a field the config runs (any status but
`suspended`) SHALL NOT be asked of role C, even when its step misses. Structured listing rows win; config rows serve
only when structured data gives none. Capture replay runs the current active config and records no drift.
Refs: §8.4, SPEC-08 §4.8, D-0615, D-0616, D-0619.

#### Scenario: Covered field missing
- **WHEN** a covered field's steps match nothing on a page
- **THEN** it stays `missing` and no LLM call is made for it

### Requirement: Drift suspension
Each config-mode page with outcome `extracted` or `partial` SHALL add per-field `(matched, valid)` to a 50-page window.
From 3 pages, a field whose windowed yield or validity (validity unmeasured with no match) falls below its IR baseline
minus the margins in `backend/data/drift_margins.json` (`yield` 0.2, `validity` 0.1, stamped `source_split: dev` and
`fit: "spec default, unfitted"`, INV-02) SHALL become `suspended` in the IR and `field_status`, log
`job_event(kind='drift_suspended')`, fall back to cold extraction and trigger re-learning.
Refs: §8.3, SPEC-08 §4.9, D-0032, D-0571–D-0576, D-0913.

#### Scenario: Layout change
- **WHEN** a field matches on 1 of the last 10 pages after validating at yield 1.0
- **THEN** it is suspended, role C may fill it, and a learn job runs

### Requirement: Operator corrections and config API
The system SHALL serve `GET /v1/sites/{host}/configs`, `GET /v1/configs/{id}` (IR and report) and
`PUT /v1/configs/{id}` with `{fields: {<name>: {steps} | null}, confirm: [<name>]}` on the latest version only (else
409). A correction is version+1 with `origin=operator` and the operated fields `operator`; it is validated on the
site's 8 latest extracted pages (≥ 3, else `too_few_held_out`) and activates only if every operated field is kept,
else it is stored `draft` with its report while the previous version keeps serving. Invalid bodies are 422 with a
field path.
Refs: §13.1, C5, SPEC-08 §4.10, D-0033, D-0593–D-0598.

#### Scenario: Correction fails validation
- **WHEN** an operator's new steps for `price` are not reproduced on the held-out pages
- **THEN** a `draft` version with the report is returned and the active version is unchanged

### Requirement: Schema edits send configs back to learning
A changed schema document SHALL suspend the schema's active configs (drafts stay) and send its states to `cold` with
no run in flight, clearing `active_config_id` and `retry_at_pages` and keeping `pages_extracted`; a run the edit
overtook ends `failed` with `schema_edited` and touches no state.
Refs: §5.2, Appendix A #43, D-0950.

#### Scenario: Field added to schema
- **WHEN** an active site's schema gains a field
- **THEN** its config is `suspended` and its state `cold`

### Requirement: Config exporters
`POST /v1/configs/{id}/export {format: json|platform_draft}` SHALL return the export and the release-check report.
`json` is the IR as stored (`manual` only in the report). `platform_draft` gives each field `{steps, manual}` with
every step in IR order (CSS as its XPath, `attr` as `@name`), a listing as `{row_xpath, fields, next}`,
`regex_flags: "u"`, `api_recipe` with a PHP hint rendered from a template, and `draft: true` until OPEN_QUESTIONS #1.
Refs: §12.2, SPEC-08 §4.11, D-0606, D-0607, D-0608, D-0610.

#### Scenario: Draft export
- **WHEN** a config is exported as `platform_draft`
- **THEN** the document has `draft: true` and each field's `manual` flag

### Requirement: Record exporters
`json_records`, `csv_records` and `markdown` SHALL share one table: schema fields sorted by name, then
`_status_<field>` columns; strings as written, other values compact JSON, unpublished cells empty (`null` in JSON);
markdown escapes ASCII punctuation and turns line endings into `<br>`. `csv_safe=true` (only with `csv_records`, else
422) prefixes `'` to cells starting with `=`, `+`, `-`, `@`, tab or CR; the default is unchanged (INV-27).
`json_values` gives one item per task `{url, outcome, records, metadata?}`, each record the schema's published fields
in schema order (null when unpublished), no status columns.
Refs: §12.2, Appendix A #40, SPEC-08 §4.11, SPEC-14 §4.4, D-0544, D-0545, D-0879, D-0912.

#### Scenario: Formula-like cell
- **WHEN** a published value is `=1+1` and `csv_safe=true`
- **THEN** the cell is `'=1+1`; without `csv_safe` it is `=1+1`

### Requirement: Release check (INV-20)
An exported config field SHALL reproduce the engine's value on every held-out page while there are fewer than 10, and
on ≥ 95% from 10 on, or be marked `manual` (INV-20). The release executor (lxml XPath 1.0, regex, jsonpath-ng, its
own script-state reader, `when_type` by type name without subtypes) imports nothing from `crawlerai` but the IR
model, and is the one allowed second parse (INV-26). It runs on the `validated_on` captures still stored; a field with
no engine value on any is `manual`.
Enforced by: release check test; status: SPEC-08.
Refs: §12.3, SPEC-08 §4.12, D-0527–D-0530, D-0605.

#### Scenario: 94% of 20 pages
- **WHEN** a field reproduces on 18 of 20 held-out pages
- **THEN** the export marks it `manual: true`
