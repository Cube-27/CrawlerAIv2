# SPEC-08 decisions

Decisions for [SPEC-08 — Config IR, executor, learning, progressive mode, drift and exporters](../../specs/archive/SPEC-08-config-ir-learning-progressive.md).
Template, statuses and rules: [DECISIONS.md](../../DECISIONS.md).

### D-0460 — IR `attr` step is its own selector key
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: `attr` is a selector key of its own (an attribute of the context node, e.g. a listing row), not a modifier on `xpath`/`css`; XPath reads attributes with `@name`. `when_type` goes only with `jsonld`; `source` is required with `jsonpath`.
- Alternatives: `attr` as a modifier on `css`/`xpath` steps.
- Why: SPEC-08 §4.2 lists `attr` among the exactly-one selector keys and §4.3 runs it on the tree beside `xpath`/`css`; the literal reading.
- Reversible: yes

### D-0461 — CSS translation is authoritative
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: `css` is translated with cssselect's `HTMLTranslator` at validation and stored as `xpath`; an IR whose stored `xpath` differs from the translation of its `css` is refused. Pseudo-elements are refused.
- Alternatives: Keep a supplied `xpath` as is; overwrite it silently.
- Why: Executors run the `xpath`; a hand-edited mismatch would export something other than the readable `css` says. A cssselect upgrade that changes translations is handled by the loader rows (review follow-up).
- Reversible: yes

### D-0462 — `api_recipe` waits for SPEC-09
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: The IR model has no `api_recipe` field yet (`extra="forbid"` refuses one); SPEC-09 adds it with `ApiRecipe`.
- Alternatives: An untyped `dict` placeholder.
- Why: SPEC-09 owns the shape; a placeholder would let unvalidated recipes into stored IRs.
- Reversible: yes

### D-0463 — Portable regex subset
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: Patterns allow literals, `\d\D\s\S\w\W\b\B\n\t\r\f\A`, punctuation escapes, `\xhh`, `\1` to `\9`, classes without nesting, POSIX classes or set-operation doubles, counted quantifiers `{n}`/`{n,}`/`{n,m}`, `(?:`, lookarounds, `(?P<name>`/`(?P=name)` (names up to 32 characters) and the `i`/`m`/`s` flags. Replacements allow only `\1` to `\9` naming existing groups. Python compiles with `re.ASCII` (`PCRE_FLAGS`).
- Alternatives: Translating between dialects; a PCRE binding in tests.
- Why: D-0034 asks for a conservative check; refusing is safer than translating. Non-ASCII under PHP `/u` is settled on the PR 11 row (review follow-up).
- Reversible: yes

### D-0464 — XPath 1.0 check refuses variables and namespace prefixes
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: Besides the D-0034 function allowlist, variable references and namespace prefixes are refused.
- Alternatives: Allow them and fail at run time.
- Why: A config carries no bindings for them; libxml2 compiles both and fails only on evaluation.
- Reversible: yes

### D-0465 — IR field and post-op shape
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: A field has at least one step; a field without steps is absent from `fields`. Normalizer post ops exist for every field type except `list`/`object` and take `{}`. `FieldStatus` moves to `db.models` beside the other `extraction_config` enums.
- Alternatives: Empty step lists; a second `FieldStatus` copy in `eval`.
- Why: An empty step list carries a status for nothing; C8, one definition.
- Reversible: yes

### D-0475 — The pipeline takes a config executor bound to its IR
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `crawlerai.collect.config.ConfigExecutor` is `execute(page, schema, ctx) -> Executed` plus `field_status`, implemented by `EngineExecutor(ir, vocabulary)`; SPEC-05 §4.5 and SPEC-08 §4.3 now state this signature (clarifying edit).
- Alternatives: SPEC-05 §4.5's literal `execute(ir, page, schema) -> list[Candidate]`.
- Why: `.importlinter` puts `config_ir` above `collect` and `resolve`, so the pipeline cannot name the IR type; candidates need `ctx` to normalize, listings need row entities, resolution needs field status (§10).
- Reversible: yes — only the PR 8 wiring uses it

### D-0476 — Config candidates carry no `page` entity
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `Executed.rows` holds only listing rows (`config:row:<n>`, kind `ListItem`, roots); page-level candidates name `page`.
- Alternatives: Return a `CollectResult` that includes `page`.
- Why: The OpenGraph collector emits `page` and `EntityGraph.of` adds it when missing; a second one would be a duplicate id (as `Admitted` for js_state/xhr).
- Reversible: yes

### D-0477 — The engine reads JSONPath with `json_doc`'s RFC 9535 subset, not jsonpath-ng
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: Queries outside the name/wildcard/index subset are refused per step with an `unsupported_jsonpath` diagnostic.
- Alternatives: Add jsonpath-ng to the engine as SPEC-08 §4.1 lists.
- Why: C8: one JSONPath reader in the engine; locator paths are in the subset; the release executor (PR 3) uses jsonpath-ng, keeping the two independent (INV-20).
- Reversible: yes — swap the reader in `_select_all`

### D-0478 — Post ops: a normalizer op checks, it does not transform
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `{"<type>": {}}` requires the value to be `Ok` for its type and passes it on unchanged; `trim`, `regex_replace` and `absolutize_url` take text only; `absolutize_url` without a base URL declines `no_base_url` (C7); a failed post op declines the step and the next step runs.
- Alternatives: Let the normalizer op transform the value.
- Why: SPEC-04 owns normalization (C8); normalizing twice is not idempotent for every type.
- Reversible: yes

### D-0479 — Without a valid step, the first match is proposed with its decline
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: If no step gives `Ok`, the first step that matched is proposed with its `Invalid`/`Ambiguous` result (a multi-match carries the matches as `raw`); no match gives no candidate; selector errors are diagnostics.
- Alternatives: Propose only `Ok` values.
- Why: Other collectors propose invalid candidates too; drift (§4.9) and validation (§4.7) need "matched but not valid".
- Reversible: yes

### D-0480 — Scope of config steps
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `regex`, `jsonld` and `jsonpath` read the whole page and are refused in a listing row; a row step is an `xpath`/`css` step selecting elements; `when_type` matches subtypes through the JSON-LD collector's vocabulary; `next` fills the schema's `next_page_url` field (ARCHITECTURE §5.3) when present.
- Alternatives: Run regex on a row's serialized HTML.
- Why: Most conservative reading of SPEC-08 §4.3; a serialization the release executor cannot reproduce exactly.
- Reversible: yes

### D-0481 — A config for another schema version or page kind raises `ConfigMismatch`
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `EngineExecutor.execute` refuses a schema whose name, version or page kind differs from the IR's.
- Alternatives: Run it anyway.
- Why: Configs are per schema version (ARCHITECTURE §5.2, §6); a mismatch is a wiring bug, not page content.
- Reversible: yes

### D-0482 — Config candidates are never independent
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: Every `source_kind='config'` candidate has `independent=False`.
- Alternatives: `independent=True`.
- Why: A config is learned from the page's other sources and a `jsonld` step reads the node the JSON-LD collector reads, so an equal value is one piece of evidence, not `agreed` (ARCHITECTURE §8.1, §10) (#98 review).

### D-0527 — The release executor learns the schema through `FieldRule`s
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: `release_run(ir, ReleasePage, rules)` takes one `FieldRule(many, accepts)` per field: `many` for list fields, `accepts(value, type | None)` for normalizer post-op checks and the field's own validity, built by the release check from the schema and SPEC-04's normalizers. A field without a rule does not run (diagnostic); only valid values are returned (no decline as in D-0479).
- Alternatives: Import `schemas`/`normalize` (breaks the contract); return each step's raw matches for the caller to pick.
- Why: "First valid step wins" (§12.1) needs validity, and §4.1 forbids every `crawlerai` import but the model; the release check compares only reproduced values.
- Reversible: yes

### D-0528 — Release `when_type` matches by type name, without subtypes
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: A JSON-LD node is any object with `@type`; `when_type` matches a declared type's name with or without the `http(s)://schema.org/` prefix. Subtypes are not matched; `@context` is not read.
- Alternatives: Load the schema.org vocabulary into the release executor.
- Why: §12.3 says "no engine logic". An exported config's consumer has no vocabulary either, so a field that holds only through a subtype should be marked `manual`.
- Reversible: yes

### D-0529 — The release executor reads script state with its own reader
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: `js_state` reads `application/json` scripts and the object or array after a `window.x =` / `var|let|const x =` assignment (ECMAScript syntax) with `json.JSONDecoder.raw_decode`; `xhr` reads UTF-8 JSON network bodies; an `api` source is a diagnostic (SPEC-09).
- Alternatives: Take the engine's parsed documents as input.
- Why: Independence (INV-20): the same syntax read by separate code is what makes agreement meaningful.
- Reversible: yes

### D-0530 — jsonpath-ng capped below 1.9
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: `jsonpath-ng>=1.8,<1.9`. It accepts queries outside the engine's RFC 9535 subset (D-0477), such as `$..name`; where the engine refuses such a step the executors may disagree, and the release check marks the field `manual`.
- Alternatives: The latest release.
- Why: 1.9.x and 1.10.x were under two weeks old; SPEC-08 §4.1 names jsonpath-ng.
- Reversible: yes

### D-0544 — Record export columns are in field-name order, values then statuses
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 12 (#115) · Status: decided
- Decision: All three record formats share one table: the schema's fields sorted by name, then `_status_<field>` for each in the same order. `json_records` is a JSON array of objects with those keys; `markdown` is a GFM table with those columns. A record whose `field_meta` keys are not the schema's fields is refused (`ValueError`).
- Alternatives: Declaration order; interleaving each field with its status; a per-record markdown section.
- Why: §4.11 asks for stable CSV columns, and `schema_def.fields` is JSONB, which does not keep key order. Field names start with a lowercase letter (`NAME_PATTERN`), so status columns cannot collide with fields.
- Reversible: yes

### D-0545 — Record export cells: strings as themselves, everything else compact JSON; no CSV formula escaping
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 12 (#115) · Status: decided
- Decision: An unpublished field is an empty cell (`null` in `json_records`); a string value is written as is; numbers, booleans, lists and objects are compact JSON (`ensure_ascii=False`, `allow_nan=False`). Cells starting with `=`, `+`, `-` or `@` are not prefixed. Markdown backslash-escapes every ASCII punctuation character (CommonMark §2.4) and turns line endings into `<br>`.
- Alternatives: JSON-encode every value; prefix formula-like cells with `'` (OWASP CSV injection guidance).
- Why: §4.11 JSON-encodes nested values only; INV-27 forbids changing a published value. Spreadsheet safety, if wanted, belongs to the caller (SPEC-10/SPEC-12).
- Reversible: yes

### D-0546 — An in-flight learning run is `learning_started_at IS NOT NULL`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 4 (#114) · Status: decided
- Decision: A learning run is in flight while `progressive_state.learning_started_at` is set, in any mode; it is cleared when the run ends. `last_learned_at` is stamped only when a run activates a config.
- Alternatives: A separate `learn_job_id` column; stamping `last_learned_at` on failure too.
- Why: §4.4 names these plumbing columns; one flag serves both a cold site's `learning` mode and an active site's re-learn, and lets the compare-and-set refuse a second concurrent run.
- Reversible: yes

### D-0547 — An active state re-learns only when forced and keeps its config
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 4 (#114) · Status: decided
- Decision: An `active` state re-learns only with `force` (API `force=true`, drift in PR 9), stays `active` on its current config while the run is in flight, and stays on it if the run fails.
- Alternatives: Move `active → learning` and serve cold during the re-learn.
- Why: Most conservative reading of §4.8–§4.10: nothing is deactivated without a validated replacement, and suspended fields already fall back to cold per field (§4.9).
- Reversible: yes

### D-0548 — A failed learning run retries at `retry_at_pages`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 4 (#114) · Status: decided
- Decision: The retry after a failed run (D-0030) is a nullable `progressive_state.retry_at_pages` (= `pages_extracted + 8` at failure); the trigger fires at `pages_extracted >= coalesce(retry_at_pages, 8)`, and `pages_extracted` keeps its §6 meaning.
- Alternatives: Reset `pages_extracted`; count pages since the failure from tasks.
- Why: The §6 counter stays a plain count; 8 lives in code once (`LEARN_AFTER_PAGES`).
- Reversible: yes

### D-0549 — The `learn` job is a queued job row naming its state
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 4 (#114) · Status: decided
- Decision: The `learn` job is created `queued` in the site's project, `schema_id` set, with `request = {site_id, schema_id, schema_version, page_kind, force}`; the learning pipeline (PRs 5–7) runs it and calls `learning_activated`/`learning_failed`.
- Alternatives: A url_task per sample page.
- Why: A learn run reads stored captures and fetches nothing; the request names the state it learns.
- Reversible: yes

### D-0550 — `progressive_state` checks tie modes to their plumbing
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 4 (#114) · Status: decided
- Decision: Checks `mode <> 'learning' OR learning_started_at IS NOT NULL`, `mode <> 'active' OR active_config_id IS NOT NULL` and `retry_at_pages >= 0` (migration 0011).
- Alternatives: No database checks.
- Why: The state machine's invariants hold even for writes outside `config_ir.progressive`.
- Reversible: yes

### D-0551 — Induction covers detail pages only
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: `induce` returns every field of a listing schema in `to_synthesize` (`listing`).
- Alternatives: Induce listing row fields relative to a guessed row.
- Why: §4.6 builds the `row` selector in synthesis; a row field cannot be checked without one.
- Reversible: yes

### D-0552 — A field is induced only when every sample page published it
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: A field missing on any sample page goes to synthesis (`not_published_on_every_page`).
- Alternatives: Induce from the pages that have it.
- Why: The literal reading of §4.5 ("all five", "on every sample page").
- Reversible: yes

### D-0553 — Induction checks a selector with the engine executor
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: A candidate is kept only if, on every sample page, `executor.field_candidate` gives an `Ok` value `equal` to the published one; an XPath candidate's node path must also select exactly one node.
- Alternatives: A separate check in induction.
- Why: C8; `normalize-space(...)` would hide a multi-match, so the node path is counted separately.
- Reversible: yes

### D-0554 — JSON-LD candidates are relative to each enclosing typed node
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: For each enclosing schema.org node (nearest first) and each of its types, a `jsonld` step with `when_type`, its path with indices as `[*]`, then as written.
- Alternatives: Only `[*]`.
- Why: §4.5 compares after stripping indices; keeping the written index lets a single-valued field from a multi-valued property still verify.
- Reversible: yes

### D-0555 — XPath anchors and readings
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: Anchors are `@id`, `@itemprop`, `@data-*` and stable class tokens on the element and its ancestors, nearest first; no unanchored path is proposed. Each path is read as `normalize-space(...)`, then as each of the element's attributes.
- Alternatives: An absolute unpositioned path; microdata's value-attribute table.
- Why: ARCHITECTURE §8.1 rules out bare generic paths; trying every attribute is structural and needs no copy of microdata's table (C8).
- Reversible: yes

### D-0556 — Adapter and API values come from their mapping
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: Fields whose locators are `adapter:`/`api:` with one mapping name go to `Induction.mapped`, not to IR steps; the caller sets `origin=adapter`.
- Alternatives: `jsonpath` steps with `source="api"`.
- Why: The engine refuses `api` sources (SPEC-09 executes them) and `config_ir` cannot import adapters.
- Reversible: yes

### D-0557 — Locators that do not resolve to one element are proposed as written
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: A `microdata:` or `config:` XPath that does not select exactly one element on the lxml tree is proposed as it is, and verification decides; an unresolvable selectolax path is then rejected and the field goes to synthesis.
- Alternatives: Generalize on the selectolax tree.
- Why: The executors run on lxml, so a selector is judged there; an earlier config's expression is already general.
- Reversible: yes

### D-0558 — Induced status and list fields
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 5 (#116) · Status: decided
- Decision: Induced fields are `uncorroborated` until validation (PR 6). List fields with `microdata:`/`config:` locators go to synthesis; only `jsonld` induces list fields.
- Alternatives: Generalize one located element to the item set.
- Why: One element does not give the item set without an item selector, which synthesis builds.
- Reversible: yes

### D-0563 — Validation reproduces with both executors
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: A field is reproduced on a held-out page only when the engine executor and the release executor both give the engine's published value (`equal`).
- Alternatives: Engine executor only (§4.7 "the executor").
- Why: ARCHITECTURE §8.3 step 3 names the independent release executor; the stricter reading.
- Reversible: yes

### D-0564 — A field published on no held-out page is dropped
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: Such a field is reported `dropped: never_published` and does not activate.
- Alternatives: Keep it unchecked.
- Why: Nothing activates without validation (§4.13).
- Reversible: yes

### D-0565 — Corroboration compares with the caller's structured or adapter values
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: Each held-out entity carries `Facts(published, references)`; `references` are the field's valid structured or adapter candidate values. A page is comparable with at least one; it agrees when the config's valid value equals every one.
- Alternatives: Compare only with the published value's source.
- Why: §8.3 step 4 "pages that have such a value"; disagreeing references count against corroboration (conservative).
- Reversible: yes

### D-0566 — Listing validation is row by row, in document order
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: The listing is dropped when `row` selects fewer than 3 rows on any held-out page or no row field is kept. Row fields are compared with the engine's rows in document order and are reproduced only when the config, the release executor and the engine have the same row count. `next` is validated as the page-level `next_page_url` field and dropped on its own.
- Alternatives: Match rows by value.
- Why: Most conservative reading of §4.7; an extra or missing row changes the records.
- Reversible: yes

### D-0567 — Validation report shape
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: Besides §4.7's members, each field reports `published`, `comparable` and `dropped`; `corroborated_on` is a count. The report adds `held_out` (capture ids), a `listing` section and `refused` (`too_few_held_out`, `no_field_kept`).
- Alternatives: §4.7's members only.
- Why: §4.10 returns the report so an operator sees why a field did not activate.
- Reversible: yes

### D-0568 — Validation keeps `operator` status
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: A kept field whose input status is `operator` stays `operator`; other kept fields get `corroborated` or `uncorroborated`.
- Alternatives: Recompute every status.
- Why: §4.7; PR 10 sets `operator`.
- Reversible: yes

### D-0569 — Activation lives in `config_ir/activation.py` and needs a learning run in flight
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: `activate` locks the state row, checks that the IR's site host, schema name and version and page kind match the key, suspends the previous active config, inserts version max+1 per (site, schema, page kind) and calls `learning_activated`.
- Alternatives: Put it in `progressive.py`; activate without a run.
- Why: Keeps the state machine module unchanged; PR 10's operator path adds its own entry.
- Reversible: yes

### D-0570 — `release_rules` in src
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 6 (#118) · Status: decided
- Decision: The D-0527 rule builder moves from the release-executor property test to `config_ir/release_rules.py`.
- Alternatives: Keep a copy per caller.
- Why: C8; validation and the PR 11 release check need the same rules.
- Reversible: yes

### D-0571 — Drift compares against the IR's per-field yield and validity
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 9 (#119) · Status: decided
- Decision: The drift baseline is each field's `FieldSteps.yield`/`validity` in the IR, the held-out values validation writes there (§4.7, #118), not a read of `validation_report`.
- Alternatives: Read `validation_report[field]`.
- Why: Same values; the executor already reads the IR, so drift needs no second document.
- Reversible: yes

### D-0572 — A drift window is compared only from 3 pages
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 9 (#119) · Status: decided
- Decision: A field is judged once its window holds at least 3 pages.
- Alternatives: Judge from the first page.
- Why: The validated values come from at least 3 held-out pages (§8.3); one malformed page would otherwise suspend a field and start an LLM re-learn.
- Reversible: yes

### D-0573 — Windowed validity is unmeasured when no page matched
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 9 (#119) · Status: decided
- Decision: Validity is valid / matched; with no matched page only yield is compared.
- Alternatives: Count validity as 0.
- Why: No division by zero, and yield already catches that case.
- Reversible: yes

### D-0574 — A listing row field's page observation
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 9 (#119) · Status: decided
- Decision: On a page, a row field matched when any row has its value, and is valid only when every row's value is.
- Alternatives: Count each row as an observation.
- Why: The conservative reading: one bad row counts against validity; the window stays per page (§4.9).
- Reversible: yes

### D-0575 — Drift suspension is written to the IR and `field_status`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 9 (#119) · Status: decided
- Decision: `record_run` sets `suspended` in both the stored IR (`FieldSteps.status`) and `extraction_config.field_status`.
- Alternatives: Only `field_status`.
- Why: The executor reads status from the IR; the API and reports read `field_status`.
- Reversible: yes

### D-0585 — Synthesis extends induction's config
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: `synthesize` takes the induced IR and the names in `Induction.to_synthesize`, and returns the IR with the verified steps added (`origin=llm_synth` when it added any; status `uncorroborated` until validation), the unresolved targets with their last diagnostics, and the number of repair rounds.
- Alternatives: Return bare `FieldSteps`.
- Why: Verification runs the engine executor on a whole config, and the caller validates and activates one IR.
- Reversible: yes

### D-0586 — Verification on the sample mirrors held-out validation
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: A field passes when, on every sample page where the engine published it, the engine executor's value is `equal` to it, and every value it gives on any page is valid. A row selector passes with ≥ 3 rows on every page and, where the engine published rows, exactly that many; row fields are compared row by row in document order (as D-0566). A field published on no sample page is not asked (`not_published`).
- Alternatives: Require only ≥ 3 rows.
- Why: Anything weaker fails held-out validation (§4.7) anyway. Review (#122): revisit together with D-0566 if listings rarely activate.
- Reversible: yes

### D-0587 — Repair rounds ask only for what failed
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: A repair round asks only for the failing targets, with their previous steps and up to 10 diagnostics each; verified targets are kept. A failing row selector is asked again with every unverified row field (`row_not_verified`); a verified one is shown as fixed. Steps that do not parse are dropped and the others verified; they are reported when the field fails.
- Alternatives: Ask again for every field.
- Why: §4.6 "fields still failing"; keeps selectors that pass stable.
- Reversible: yes

### D-0588 — LLM failures propagate from synthesis
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: `BudgetExhausted`, `ProviderUnavailable` and `OutputInvalid` propagate from `synthesize`; the learn job ends `failed` and calls `learning_failed`.
- Alternatives: Keep what was verified before the failure.
- Why: §4.13 (a learning job that exhausts its budget ends failed, and nothing activates); the most conservative reading.
- Reversible: yes

### D-0589 — `next_page_url` is verified as a page-level field and becomes `listing.next`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: On a listing, `next_page_url` is asked with at most one step and runs as a page-level field (how the executor runs `next`, §4.3), whatever its schema scope; without a verified listing it is left out (`no_listing`).
- Alternatives: Drop `next` along with the row.
- Why: IR §12.1 puts `next` in the listing.
- Reversible: yes

### D-0590 — What role A reads
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: Reduced HTML keeps every element except `script` and `style` (so paths match the page) and only §4.6's attributes; the cut window is centred on the published values found as HTML-escaped text (the start when none is found); JSON documents (JSON-LD, script state, captured responses) are key paths with `[*]`, `@type` values kept for `when_type`, cut to 20,000 characters; the first 10 published rows per page are shown. `CRAWLERAI_LLM_A_MAX_CHARS` (default 120,000) is a setting; `max_output_tokens = 8,192`.
- Alternatives: Drop empty elements; show every row.
- Why: §4.6; the paths the model writes must run on the real tree.
- Reversible: yes

### D-0591 — The learn job's end-to-end wiring goes to SPEC-08 PR 8
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 7 (#122) · Status: decided
- Decision: PR 8 (pipeline wiring) loads the sample and held-out pages with their published values and structured references, chains induce → synthesize → validate → activate, and calls `learning_failed` on a failure or a refusal (the PR 4 and PR 6 follow-ups).
- Alternatives: Include them in PR 7.
- Why: The PR 7 row's scope is `config_ir/synthesis` and its prompts, with unit tests on a fake LLM.
- Reversible: yes

### D-0592 — `POST /v1/sites/{host}/learn` takes `{schema_id, force=false}`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: The body is `{schema_id, force}`; the page kind comes from the schema. 202 `{job_id}`; 409 while a run is in flight, or when the state is active and `force` is not set; 404 for an unknown site or schema.
- Alternatives: Learn every state of the host (several jobs, breaks `{job_id}`); a query parameter.
- Why: Fills a gap: §4.10 gives no request body. Progressive state is keyed per (site, schema version, page kind) (§4.4, D-0549), so the narrowest reading is that the caller names the schema version; SPEC-12's "Learn now" sits on a config detail page where it is known. Agreed with the orchestrator.
- Reversible: yes

### D-0593 — A correction is the next version; it activates only if every operated field validates
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: `PUT /v1/configs/{id}` stores version+1: `active` with the validated (pruned) IR only when validation keeps every field the operator gave steps or confirmed (`Correction.operated()`), else `draft` with the operator's full IR and the report, the previous version staying active. The response is the new version (`ConfigDetail`: summary, IR, report).
- Alternatives: Activate when any field is kept (dropped the operator's field and suspended the working version; review of #123); store nothing on failure.
- Why: §4.10: version+1, activates only if validation passes, the response carries the report. A failed correction must not replace the version that serves; the draft lets the operator correct again.
- Reversible: yes

### D-0594 — Only the latest config version is corrected
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: A `PUT` on a version that is not the latest of its (site, schema version, page kind) is 409; the state row is locked (`progressive.lock_state`) while the version is taken.
- Alternatives: Branch from any version.
- Why: An edit never silently drops a version someone else added; the same rule as schema edits (SPEC-07).
- Reversible: yes

### D-0595 — Correction semantics
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: Corrected and confirmed fields become `operator`; `null` removes a field; row fields of a listing schema go to `listing.fields` and need an existing listing; every field's yield and validity are cleared and re-measured; provenance becomes `operator` with `learned_at` now. Refused with 422 and a field path: unknown field, confirming or removing a field the config lacks, confirming and correcting one field, an empty correction, a row field without a listing.
- Alternatives: Allow edits to `row`/`next` (the §4.10 body has no place for them).
- Why: Most conservative reading of §4.10's body.
- Reversible: yes

### D-0596 — Held-out pages for a correction
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: The site's 8 (`LEARN_AFTER_PAGES`) most recent captures with task outcome `extracted`/`partial` and a record of the schema version, each with its latest extraction; expired bundles are skipped; fewer than 3 pages refuse (`too_few_held_out`).
- Alternatives: The base version's `validated_on` (expires after 30 days, leaving old configs uncorrectable).
- Why: §4.4 selection rule; the operator wrote the steps from none of these pages.
- Reversible: yes

### D-0597 — `config_ir/held_out.py` is the one held-out loader
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: Published values come from `record.data`; references are `ok` candidates from structured or adapter sources (every source kind except `config` and `llm`) owned by an entity that published a field of the page; a listing's rows are its records in stored (UUIDv7) order, page-scope fields split off, with no references. SPEC-08 PR 8 and the learn-job runner reuse it.
- Alternatives: Replay cold (loses role-C-published values, so such fields could never validate).
- Why: Validation compares with what the engine stored (§4.7). Records don't store their row entity, so row references are left out (errs `uncorroborated`); a listing with an incomplete or duplicate row has fewer records than rows and validation refuses it as misaligned (D-0566).
- Reversible: yes

### D-0598 — Operator activation does not end a learning run
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 10 (#123) · Status: decided
- Decision: New progressive event `operator`: cold/learning/active → active, with or without a run in flight (`RUN_IN_FLIGHT` per event); a run in flight continues and may later activate its own config over the operator's.
- Alternatives: Cancel the run; refuse the correction while learning.
- Why: A correction must not wait on a run; whether a learned config should yield to an operator's is PR 8's.
- Reversible: yes

### D-0605 — The release check runs on the config's validated-on captures
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 11 (#124) · Status: decided
- Decision: The release check runs on the `provenance.validated_on` captures that are still stored and have a record of the config's schema version (`held_out.load_captures`); a field with no engine value on any of them is `manual`.
- Alternatives: The site's 8 most recent extracted pages (as a correction validates).
- Why: §12.3 checks the exported config on its held-out pages; an expired page can only make fields `manual`.
- Reversible: yes

### D-0606 — `platform_draft` keeps every step of a field, in order
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 11 (#124) · Status: decided
- Decision: Each field is `{steps, manual}`: steps in IR order as `xpath` (CSS as its translation, `attr` as `@name`), `regex` or `jsonpath`/`jsonld`, post ops as in the IR; a listing is `{row_xpath, fields, next: {steps, manual}}`; the draft carries `draft: true`, `regex_flags: "u"` and `api_recipe` as stored, and no `params` member.
- Alternatives: One `{xpath, regex?, params?, post}` per field (SPEC-08 §4.11 text).
- Why: The first valid step wins (§12.1), so one selector per field would export something other than what the engine runs; the IR has no named params outside `api_recipe`, whose PHP hint is SPEC-09 PR 7. A draft until OPEN_QUESTIONS #1.
- Reversible: yes

### D-0607 — One release check, on the IR, for both export formats
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 11 (#124) · Status: decided
- Decision: The release check runs on the IR; the draft's CSS-as-XPath and `attr`-as-`@name` steps read the same values in the release executor (tested).
- Alternatives: Rewrite the IR into its XPath form and check that.
- Why: One check, no IR-to-IR translation layer; INV-20 holds because the drafted steps are equivalent.
- Reversible: yes

### D-0608 — The `json` export marks `manual` in the report only
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 11 (#124) · Status: decided
- Decision: The `json` export is the IR unchanged; `manual` per field is in the response's `release` report.
- Alternatives: Add `manual` to the IR document.
- Why: §4.11: `json` is the IR as stored, and the IR model forbids extra keys.
- Reversible: yes

### D-0609 — Exported regexes run with PHP `/u`; caseless patterns are ASCII
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 11 (#124) · Status: decided
- Decision: Exported regexes run in PCRE2 UTF mode (`/u`, no UCP); the portable subset refuses a pattern that names the `i` flag and has a non-ASCII character or a `\xhh` escape above 0x7F.
- Alternatives: No `/u` (`.` and classes match bytes, unlike Python).
- Why: In UTF mode `.` and classes match code points as in Python, but PCRE2 folds case for non-ASCII letters and Python with `re.ASCII` does not. Settles the #95 follow-up (D-0463).
- Reversible: yes

### D-0610 — Config exports live in the configs router and service
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 11 (#124) · Status: decided
- Decision: `POST /v1/configs/{id}/export` is in `api/routers/configs.py` and `services/configs.export`; `held_out.load_captures` shares `load_held_out`'s latest-extraction query and page assembly; the dispatcher is `config_ir/exporters/configs.py`, the draft `exporters/platform_draft.py`.
- Alternatives: A separate router and loader (the PR's state before #123 merged); an `exporters/json.py`.
- Why: One loader for held-out pages (C8); the `json` export is the IR itself.
- Reversible: yes

### D-0614 — Config mode follows from the config
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: `extract_page(bundle, schema, config, role_c, *, data, parsed)` has no `mode` argument: the mode is `config` exactly when a config executor is passed, else `adhoc`.
- Alternatives: Keep `mode` and refuse mismatches.
- Why: One source of truth; a mismatch cannot be expressed.
- Reversible: yes

### D-0615 — A covered field is never asked of role C
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: A field the active config runs (any status but `suspended`) is not asked of role C, even when its step misses on a page; it stays `missing`, and drift catches the miss.
- Alternatives: Ask role C for covered fields that missed.
- Why: SPEC-08 §4.8 ("role C runs only for required fields the config has no steps for"); zero LLM calls on covered fields.
- Reversible: yes

### D-0616 — Listing rows in config mode
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: Structured rows win; the config's rows serve only when structured data gives none. Role C is asked for no rows while the config runs a row field, and only for page fields the config does not run.
- Alternatives: Merge config rows with structured rows.
- Why: Candidates belong to their own row entities, so the two cannot meet in one row; where structured rows exist, cold extraction is already LLM-free.
- Reversible: yes

### D-0617 — The active config is read from `extraction_config`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: `config_ir.active.active_config` reads the `status='active'` row for (site, schema version, page kind), not `progressive_state.active_config_id`.
- Alternatives: Read the state's `active_config_id`.
- Why: The config row is what drift and corrections update, and its unique index allows only one active config.
- Reversible: yes

### D-0618 — Drift records a page's config candidates
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: `drift.observe`/`record_run` take the page's `config` candidates instead of an `Executed`; only config-mode pages with outcome `extracted`/`partial` are recorded (`active.record_page`). Scrape records them now; the worker's page handler does with SPEC-10 PR 2.
- Alternatives: Carry `Executed` through `ExtractionResult`; record in `store_extraction` (`resolve` cannot import `config_ir`).
- Why: The result already holds the candidates; a page that was not served says nothing about the config.
- Reversible: yes

### D-0619 — Capture replay runs the site's current active config
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: `POST /v1/captures/{id}/replay` extracts with the site's current active config for each schema version, and adds nothing to its drift window.
- Alternatives: The config version the stored extraction used.
- Why: A replay shows what the current engine extracts.
- Reversible: yes

### D-0620 — `ConfigSnapshot.ir` is an `ExtractionConfigIR`
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: An eval page whose snapshot IR the model refuses is dropped as `invalid config_snapshot`.
- Alternatives: Fail the replay run.
- Why: The same treatment as an invalid `field_status`.
- Reversible: yes

### D-0621 — The learning sample
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: A run reads the 8 latest extracted pages (`held_out.load_pages`); the 5 with the most published required values (page and rows; most recent first on ties) are the sample, the rest held out. The induced config is `origin=adapter` when induction mapped a field, else `induced`; mapped fields are not synthesized.
- Alternatives: Only the first 8 pages ever.
- Why: §4.4's selection rule; adapter fields keep coming from the adapter (D-0556).
- Reversible: yes

### D-0622 — How a learn run ends
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: `completed` when it activates; `failed` on refusal, an LLM failure (D-0588) or an error; `cancelled` when cancel is requested before it starts or activates. Every non-activating end calls `learning_failed`; the `learning_finished` event carries `config_id`, `reason` and the validation report.
- Alternatives: Leave the state `learning` on an error.
- Why: §4.8 (a failed run leaves the state cold and retries); PR 4 follow-up.
- Reversible: yes

### D-0623 — A learning run does not replace an operator config activated during it (answers D-0598)
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: A run whose state got an operator config while it was in flight ends `operator_config` without activating. A run started while an operator config already served (forced or drift re-learn) may replace it.
- Alternatives: Always replace; never replace an operator config.
- Why: The operator wrote that config knowing the pages the run learns from; a re-learn requested over one is a request to replace it.
- Reversible: yes

### D-0624 — Learn jobs are run by the worker with SPEC-10 PR 2
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 8 (#127) · Status: decided
- Decision: `learning.next_learn_job`/`run_learn_job` are the entry points; registering them in the worker process goes to SPEC-10 PR 2 with the task handlers (as D-0485). Open there: a `_start` failure leaves the job `queued`, so it is picked again on every poll; a run whose process dies (or whose `_finish` raises) stays `running`/`learning` until a lease or timeout exists.
- Alternatives: A learn loop in `crawlerai worker` here.
- Why: SPEC-10 PR 2 owns handler registration and is in flight in parallel.
- Reversible: yes

### D-0776 — The validation report lists every schema field, with why an unlearned one has no steps
- Date: 2026-10-15 · Spec/PR: SPEC-08 §4.6, UAT accuracy R11 (#163) · Status: decided
- Decision: For each schema field neither induction nor synthesis gave steps, the report has a dropped `FieldReport` (`status: null`, zero counts, `dropped: "not_learned: <reason>"`); the reason is induction's, with synthesis's first two diagnostics of its last attempt appended, 200 characters at most. A listing's row fields go in its listing report. The config and its field statuses are unchanged.
- Alternatives: A separate `unlearned` key in the report (a new stored shape the UI would need to read); logging the reasons only.
- Why: The operator sees in the config view why a required field is missing, in the shape the report and UI already have (D-0583).
- Reversible: yes

### D-0836 — A stopping worker cancels its learn run
- Date: 2026-10-15 · Spec/PR: SPEC-08 §4.8 follow-up (#195) · Status: decided
- Decision: When the worker stops, `run_learner` cancels the run in progress, which ends as a failed run with reason `shutdown`; the state learns again as after any failed run.
- Alternatives: Wait for the run (role A calls of minutes each); a grace period, then cancel; leave the run to `expire_learn_runs` after an hour.
- Why: Shutdown stays bounded, and the state is not left `learning` until the run expires.
- Reversible: yes

### D-0876 — A stopping worker ends a learn run during its final transaction too
- Date: 2026-10-16 · Spec/PR: SPEC-08 follow-ups (#199) · Status: decided
- Decision: `_finish` runs inside the run's `try`; on `CancelledError` the run ends through `_abandon(SHUTDOWN)`, which leaves a job that already ended as it is.
- Alternatives: `asyncio.shield` the final transaction.
- Why: A cancelled commit rolled back and left the job `running` until `expire_learn_runs` (review of #195); the guard covers a cancel that comes as the commit lands.
- Reversible: yes

### D-0878 — css→xpath translations are pinned by a recorded replay
- Date: 2026-10-16 · Spec/PR: SPEC-08 follow-ups (#199) · Status: decided
- Decision: `tests/fixtures/synthetic/css_translations.json` holds 32 selectors and their translations from the locked cssselect; `test_css_translations` checks each stored pair still loads.
- Alternatives: Keep a stored `xpath` that differs from today's translation, or re-translate on load: either reverses D-0461 or changes what a validated config runs.
- Why: A cssselect bump that changes a translation fails CI before stored IRs stop loading; that PR decides how to migrate them (review of #95).
- Reversible: yes

### D-0913 — Drift margins carry a required `fit` stamp
- Date: 2026-10-16 · Spec/PR: SPEC-08 §4.9 (#204) · Status: decided
- Decision: `DriftMargins.fit` is a required, non-empty string saying how the margins were obtained; the committed `drift_margins.json` says "spec default, unfitted".
- Alternatives: An optional note.
- Why: The owner's answer to D-0576: nobody may take the spec's margins for values fitted on labels.
- Reversible: yes
