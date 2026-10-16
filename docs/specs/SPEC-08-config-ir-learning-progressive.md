# SPEC-08 — Config IR, executor, learning, progressive mode, drift and exporters

Layer: L2. Architecture refs: §8.3, §8.4, §12 (all), §6 (`extraction_config`, `progressive_state`), §13.1
(config endpoints), §11 (role A), C3 (site strings allowed in IR), C5 (fix sites with data).

## 1. Summary

Everything learned about a site is one executable IR (§12.1). This spec defines the IR model, the engine
executor, LLM-free induction from published locators, role A selector synthesis with repair rounds, held-out
validation and corroboration status, activation and progressive state (§8.4), per-field drift suspension,
operator corrections through the API (C5), exporters (`json`, `platform_draft`, records formats) and the release
check with a separate minimal executor (§12.3).

## 2. Scope

Core:
- IR pydantic model, versioned (`ir_version: "1"`); steps `xpath` (1.0), `css`→XPath, `jsonld`, `jsonpath`,
  `regex`, `attr`; post ops: type normalizers, `trim`, `regex_replace`, `absolutize_url`.
- Engine executor (`ConfigExecutor` for SPEC-05) and the independent release executor.
- Learning trigger at 8 extracted pages (outcome `extracted` or `partial`, §8.3) or `learn` call; sample = 5,
  held-out ≥ 3, growing.
- Induction; role A synthesis (≤ 3 repair rounds); validation; corroboration; activation.
- Progressive state transitions `cold → learning → active`; role C only for uncovered fields in `active`.
- Drift: per-field yield/validity vs `validation_report`; suspension; re-learn.
- Config API: `GET /v1/sites/{host}/configs`, `GET/PUT /v1/configs/{id}`, `POST /v1/configs/{id}/export`,
  `POST /v1/sites/{host}/learn`.
- Exporters `json`, `platform_draft`, `json_records`, `csv_records`, `markdown`.
- Release check (§12.3) with `manual` marking.

Out of scope (§22):
- Independent verifier for configs; learned ranker; review-queue UI (SPEC-12 has config view/correction only).
- Adaptive scheduling. GMC/XML exporters. The final platform exporter (OPEN_QUESTIONS #1 — `platform_draft` only).
- `api_recipe` learning and role D (SPEC-09); this spec only executes an `api_recipe` already in the IR via
  SPEC-09's executor hook.
- Variant matrices.

## 3. Dependencies

- SPEC-01, SPEC-04, SPEC-05, SPEC-06 (client for role A), SPEC-07 (API foundation).
- OPEN_QUESTIONS #1: platform config format unknown → `platform_draft` as defined in §12.2. #12: PHP snippet from a template.

## 4. Design

### 4.1 Modules

- `crawlerai.config_ir.model` — `ExtractionConfigIR`, `FieldSteps`, `Step`, `PostOp`, `ListingSpec`,
  `ApiRecipe` (shape owned by SPEC-09), `Provenance`.
- `crawlerai.config_ir.executor` — engine executor (lxml XPath 1.0, cssselect, jsonpath-ng, regex).
- `crawlerai.config_ir.release_executor` — minimal executor; may import only `lxml`, `re`, `jsonpath_ng`,
  `json`, `cssselect` (import-linter `forbidden` contract: it must not import `crawlerai.*` except `model`).
- `crawlerai.config_ir.induction` — locator generalization.
- `crawlerai.config_ir.synthesis` — role A prompts, repair loop.
- `crawlerai.config_ir.validation` — held-out validation, corroboration, `validation_report`.
- `crawlerai.config_ir.progressive` — state machine, learning trigger, scheduler tasks.
- `crawlerai.config_ir.drift` — per-run tracking and suspension.
- `crawlerai.config_ir.exporters.{json,platform_draft,records}`.
- `crawlerai.config_ir.release_check`.
- `crawlerai.services.configs`, `crawlerai.api.routers.configs`.

### 4.2 IR model (§12.1, made precise)

```python
class Step(BaseModel, frozen=True):        # exactly one selector key
    xpath: str | None; css: str | None; jsonld: str | None; when_type: str | None
    jsonpath: str | None; source: Literal["jsonld","js_state","xhr","api"] | None   # for jsonpath
    regex: str | None; attr: str | None
    post: list[PostOp] = []
class PostOp = {"money": {}} | {"date": {}} | ... (one per type) | {"trim": {}} | {"regex_replace": {"pattern","repl"}} | {"absolutize_url": {}}
class FieldSteps(BaseModel): steps: list[Step]; status: Literal["corroborated","uncorroborated","operator","suspended"]; yield_: float | None; validity: float | None
class ListingSpec(BaseModel): row: Step; fields: dict[str, FieldSteps]; next: Step | None
class ExtractionConfigIR(BaseModel):
    ir_version: Literal["1"]; site: str; schema: {name, version}; page_kind: PageKind
    fetch: {method: "http"|"browser"}
    fields: dict[str, FieldSteps]; listing: ListingSpec | None; api_recipe: ApiRecipe | None
    provenance: {origin: "adapter"|"induced"|"llm_synth"|"operator", validated_on: list[capture_id], learned_at, engine_version}
```

Rules: `xpath` must be XPath 1.0 (validated by compiling with lxml and rejecting XPath 2+ constructs by a
grammar check on functions used — a fixed list of XPath 1.0 function names from the W3C spec, which is a
standard, C2); `css` is compiled to XPath at validation time and stored as both (`css` kept for readability).
Regex must be a subset that both Python `re` and PCRE accept (no Python-only verbs; validated by a conservative
syntax check). In config-only execution the first step whose value passes its post ops and normalizer wins.

### 4.3 Executor

`EngineExecutor(ir, vocabulary).execute(page, schema, ctx) -> Executed` (SPEC-05's `ConfigExecutor` protocol): for each field, run steps in order over the
`ParsedPage`, with no second parse (INV-26): `xpath`/`css`/`attr` on the page's lxml tree, `regex` on the body
text, `jsonld` over the page's script blocks expanded and filtered by `when_type`, `jsonpath` over the chosen source; the first `Ok` value becomes a `Candidate(source_kind='config',
locator=config:<field>:<i>:<selector>)`. Listings: `row` step selects row nodes; field steps are evaluated
relative to each row; `next` yields the page-level `next_page_url` candidate. Steps never match more than
`max_matches` (default 1 for single-valued fields; a multi-match is `Invalid("multi_match")`).

### 4.4 Learning trigger and sample (§8.3, §8.4)

- `progressive_state` per (site, schema, page_kind): `mode`, `pages_extracted` (§6: pages with outcome
  `extracted` or `partial`), plus plumbing `learning_started_at`, `last_learned_at`, `active_config_id`.
- Trigger: `pages_extracted >= 8` (scheduler task `trigger_learning`, every minute) or
  `POST /v1/sites/{host}/learn`. Creates a `job(kind='learn')` (§6; budgets and usage of role A) and sets
  `mode = learning`; pages continue to be served cold.
- Sample selection: the 8 most recent captures with outcome `extracted` or `partial` and their `extraction` rows;
  the 5 with the most published required fields form the learning sample; the rest (≥ 3) are held out. Later
  captures join the held-out set.

### 4.5 Induction (no LLM)

For each field, collect the chosen candidate's locator on each sample page:
- all five `jsonld:` with the same jsonpath (after stripping array indices) and `when_type` → one `jsonld` step;
- all five `adapter:`/`api:` → the adapter's mapping (configs for adapter sites are `origin=adapter`);
- `microdata:` or `config:` XPaths → generalize: remove positional predicates `[n]`; keep predicates on `@id`,
  `@data-*`, `@itemprop`, and `@class` tokens that are "stable" by the structural rule `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`
  with no digit run ≥ 3 (hashed class tokens contain digit/uppercase runs — structural, not a site rule); prefer
  the shortest ancestor path with such an anchor; emit `normalize-space(...)` for text, `@attr` for attributes;
- `text:` (role C) → no induction; goes to synthesis.
A selector is kept only if on **every** sample page it selects exactly one node whose value normalizes to the
published value (`equal`). Otherwise the field goes to synthesis.
A row-mapped field (SPEC-13 §4.9) is neither induced nor synthesized: the validation report records it as
`not_learned: row_field`, the structured collectors still fill it in `config` mode, and drift does not track it.

### 4.6 Synthesis (role A, §11)

- Input: field descriptions; the 5 cleaned sample pages — HTML reduced to elements with text and the attributes
  `id`, `class`, `data-*`, `itemprop`, `href`, `src`, `content`, `name`, `property`, truncated to
  `CRAWLERAI_LLM_A_MAX_CHARS` (120k) per page around the published values' locations; the published values and
  their `text:` offsets; for `jsonpath` targets, the keys of JSON state blocks (not values).
- Output schema: `{fields: {<name>: {steps: [Step]}}}` — selectors only, never values (§11). Each step is written
  in a wire form (`config_ir.step_wire`: `{selector, expression, when_type, source, post: [{op, pattern, repl}]}`,
  `""` for an absent parameter), which keeps the schema inside every provider's structured-output subset
  (SPEC-06 §4.2), and is read back into an IR `Step`.
- Loop: execute on sample pages → diagnostics per field (`no_match`, `multi_match(n)`, `value_mismatch(got,
  want)`, `invalid_xpath`) → repair prompt (`a_repair`) up to 3 times; fields still failing are left without
  steps (the config covers fewer fields; role C fills them in `active` mode, §8.4).
- Listings: the same with a `row` selector that must select ≥ 3 rows per sample page, and `next`.

### 4.7 Validation and corroboration (§8.3 steps 3–4)

On held-out pages (≥ 3):
- single-valued fields: exactly one match on every page where the engine published the field; listings: ≥ 3
  rows;
- every value `Ok` by its normalizer;
- the executor reproduces the engine's published value (`equal`) on every held-out page where one exists.
Fields failing any check are dropped from the config (not activated).

`field_status`:
- `corroborated` (§8.3 step 4): on the held-out pages that have a structured/adapter value for the field, the
  config value equals it on **every** such page while there are fewer than 10, and on ≥ 90% from 10 on. With
  fewer than 3 such pages the field is `uncorroborated` (this spec's floor; see Open issues);
- `operator`: set by `PUT /v1/configs/{id}` confirmation/correction;
- `uncorroborated`: otherwise.

`validation_report` (jsonb): per field `{pages, matched, valid, reproduced, corroborated_on, status, yield,
validity}`; `yield = matched/pages`, `validity = valid/matched`.

### 4.8 Activation and progressive state

- A validated config with ≥ 1 field becomes `active` (previous active → `suspended`), `provenance.validated_on`
  lists the held-out capture ids; `progressive_state.mode = active`.
- In `active` mode `extract_page` receives the config; candidates from `config` enter resolution like any
  other (SPEC-05); their evidence bucket is `config_corroborated`/`config_uncorroborated`; record `mode =
  config`; role C runs only for required fields the config has no steps for.
- A failed learning run leaves `mode = cold` and schedules a retry after 8 more pages.

### 4.9 Drift (§8.3)

- Each run of an active config appends per-field `(matched, valid)` to a rolling window (last 50 pages,
  `extraction_config.drift_window` jsonb — plumbing).
- A field is suspended when its windowed `yield` or `validity` falls below `validation_report` value minus the
  margin from `backend/data/drift_margins.json` (`{"yield": 0.2, "validity": 0.1, "source_split": "dev", "fit":
  "spec default, unfitted"}` — defaults until fitted on dev; INV-02 stamp, and `fit` says how the margins were
  obtained; checked by its stamp, not pinned in the manifest, D-0576). Suspension sets `field_status=suspended`; the field's pages fall
  back to cold-mode resolution (role C allowed); `trigger_learning` re-runs learning for the site.
- Suspension is logged as a `job_event(kind='drift_suspended')`.

### 4.10 Operator corrections (C5) and config API

- `GET /v1/sites/{host}/configs` → all versions with status, `field_status`, `validation_report`.
- `GET /v1/configs/{id}` → IR + report. `PUT /v1/configs/{id}` body `{fields: {<name>: {steps: [...]} | null},
  confirm: [<name>...]}` → creates version+1 with `origin=operator`; corrected/confirmed fields get
  `operator`; the new version is validated on held-out pages (4.7) and activates only if validation passes;
  the response carries the report so the operator sees why not.
- `POST /v1/sites/{host}/learn` → `{job_id}`; `force=true` re-learns even when active.
- `POST /v1/configs/{id}/export` body `{format: "json"|"platform_draft"}` → the export plus the release-check report.

### 4.11 Exporters (§12.2)

- `json`: the IR as stored.
- `platform_draft`: per field `{steps, manual}`, every step in IR order (the first valid step wins, §12.1): `xpath`
  (CSS as its translation, `attr` as `@name`), `regex` or `jsonpath`/`jsonld`, post ops as in the IR; listing
  `{row_xpath, fields, next: {steps, manual}}`; `regex_flags: "u"`; no per-field `params`, which the IR has only in
  `api_recipe` (D-0606); `api_recipe` with
  a PHP code hint rendered from `exporters/templates/api_recipe.php.j2` (jinja2, BSD-3) — a template, not
  generated code (§18). Marked `draft: true` until OPEN_QUESTIONS #1 is answered.
- `json_records` / `csv_records` / `markdown`: record exports for `GET /v1/jobs/{id}/results?format=` (SPEC-10
  wires the endpoint; the exporters live here). CSV: one column per schema field, nested values JSON-encoded,
  plus `_status_<field>` columns. With `csv_safe` (SPEC-10, D-0879) a cell starting with `=`, `+`, `-`, `@`, a tab
  or a carriage return is prefixed with `'` (OWASP CSV Injection); without it values are written as published.

### 4.12 Release check (§12.3)

`release_check(ir, held_out_bundles, engine_records) -> ReleaseReport`: the **release executor** runs the IR on
each held-out bundle; per field, it must reproduce the engine's published value on every held-out page with an
engine value while there are fewer than 10 such pages, and `reproduced / pages_with_engine_value >= 0.95` from
10 on; otherwise the export marks the field `manual: true`. The release executor shares no code with the engine
executor beyond the IR model (import-linter contract), so agreement between them is evidence that the export matches the engine (INV-20). It parses the body itself; that is the one allowed exception to INV-26, and it runs only at release check.

### 4.13 Error handling

- Invalid selectors from role A are diagnostics, never exceptions. A learning job that exhausts its LLM budget
  ends `failed` with the partial induced config discarded (nothing activates without validation).
- Executor errors on a page (malformed HTML) yield no config candidates for that page and count against yield.

## 5. Invariants

INV-20 (release check), INV-02 (drift margins stamped dev), INV-17 (no exec of selectors as code; XPath is
interpreted by lxml), INV-03 (site strings exist only inside IR rows — the `config_ir/` package itself contains
none), INV-22, INV-27 (exporters serialize published values; they never fix a value).

## 6. Testing strategy

- IR model: property tests — round trip; XPath 2+ functions rejected; CSS→XPath equivalence on generated
  simple selectors.
- Executors: the engine and release executors produce identical values on generated HTML + IR pairs (property
  test); multi-match → invalid.
- Induction: generated HTML with positional and anchored paths; hashed class tokens are dropped; a selector
  that over-matches on one sample page is rejected.
- Synthesis: fake LLM returning crafted step maps; repair loop stops at 3; values never accepted from the
  model (schema forbids).
- Validation/corroboration/drift: synthetic held-out sets hitting each threshold edge (2 vs 3 corroborating
  pages; 9 vs 10 pages, all-must-match vs 90%; 89% vs 90%; release check 94% vs 95%; margins).
- Progressive state machine: transitions table test.
- Dev replay: config-field precision per status appears in the dev report (`config_snapshot` on eval pages).
- No site-named tests.

## 7. Acceptance criteria (§21 L2 done-when)

- The report breaks precision out per config field status (`corroborated`, `uncorroborated`, `operator`),
  tested on synthetic labeled fixtures. **Milestone M (§21; not required to mark this spec done):** measured on hidden and fresh.
- Release check passes (§12.3 small-n rule) on exported dev configs, or fields are marked `manual`.
- A site that reaches 8 extracted pages (`extracted` or `partial`) on dev captures enters `active` with a validated
  config without human input;
  repeat pages are served with `mode=config` and zero LLM calls for covered fields.
- Drift suspension triggers on a synthetic layout change and re-learning restores the field.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | IR model + validation (XPath 1.0, regex subset, css→xpath) | `config_ir/model` | property | Round trip + rejections. |
| 2 | Engine executor + SPEC-05 injection | `config_ir/executor` | property | Config candidates flow. |
| 3 | Release executor + import contract | `config_ir/release_executor`, `.importlinter` | property, lint-imports | Executors agree. |
| 4 | Progressive state + learning trigger + `learn` job kind | `config_ir/progressive`, scheduler task, migration | unit | Transitions tested. |
| 5 | Induction | `config_ir/induction` | property | Anchors/indices rules. |
| 6 | Validation, corroboration, validation_report, activation | `config_ir/validation` | unit | Thresholds tested. |
| 7 | Role A synthesis + repair loop | `config_ir/synthesis`, prompts | unit (fake LLM) | ≤ 3 rounds. |
| 8 | Active-mode extraction (role C only for uncovered fields) | pipeline wiring | replay | `mode=config` records. |
| 9 | Drift tracking + suspension + re-learn | `config_ir/drift`, `data/drift_margins.json` | unit | Suspension works. |
| 10 | Config API + operator corrections | `services/configs`, router | router tests | PUT creates validated version. |
| 11 | Exporters json/platform_draft + release check + export endpoint | `config_ir/exporters`, `release_check` | unit | `manual` marking. |
| 12 | Record exporters (json/csv/markdown) | `exporters/records` | unit | CSV columns stable. |

## 9. Open issues

- **Review finding (learning input is underspecified).** Resolved in ARCHITECTURE rev 5 §8.3: 8 pages with
  outcome `extracted` or `partial` (4.4).
- **Review finding (small held-out set).** Resolved in ARCHITECTURE rev 5 §8.3 step 4 and §12.3: every held-out
  page while fewer than 10, ≥ 90% (corroboration) / ≥ 95% (release check) from 10 on (4.7, 4.12).
- **`learn` job kind.** Resolved in ARCHITECTURE rev 5 §6 (`job.kind` includes `learn`).
- **Config ↔ schema version.** Configs per schema version are resolved in ARCHITECTURE rev 5 §5.2/§6. `progressive_state`
  carries `schema_version` and a new version starts in `cold` (resolved in ARCHITECTURE rev 5 §6).
- **Corroboration floor.** §8.3 step 4 says "(where those exist)" and does not say what happens when no held-out
  page has a structured or adapter value. Resolved in ARCHITECTURE rev 5 §8.3: at least 3 comparable pages,
  otherwise `uncorroborated`.
- **Evidence bucket for `operator` fields.** §10 names `config_corroborated` and `config_uncorroborated` but no
  bucket for `operator` fields. Resolved in ARCHITECTURE rev 5 §10: `operator` fields use
  `config_uncorroborated` until labels show they need their own bucket; §16.3 reports their precision separately.
- **XPath 1.0 enforcement** by function-name list is a conservative approximation; PHP `DOMXPath` and lxml both
  use libxml2, so agreement is expected; the release executor is the real check.
- `platform_draft` is a guess until OPEN_QUESTIONS #1 is answered; it is labeled `draft: true`.
