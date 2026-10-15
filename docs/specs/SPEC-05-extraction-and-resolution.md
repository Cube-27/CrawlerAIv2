# SPEC-05 — Structured extraction, ownership, resolution and confidence

Layer: L1. Architecture refs: §8.1, §8.2, §8.6 (cold listings, pagination), §10 (all), §6 (`extraction`,
`candidate`, `record`), §15 (replay signature), §16.3 (buckets), C2, C7, C9.

## 1. Summary

The generic layer: standards-based collectors (JSON-LD, microdata, OpenGraph, embedded JSON state, captured XHR
JSON, adapters, configs), the three structural resolution stages (validity, ownership, intent), the simple
preference rule, evidence buckets with dev-measured calibration, and the record/field-meta assembly. It
implements the `replay_page` function whose signature SPEC-03 fixed, so live runs and replays share one path
(G7). No DOM heuristics exist here (§8.1, C2).

## 2. Scope

Core:
- Cleaned page text with a char-offset map (for grounding, visibility checks and role C input).
- Collectors: `adapter`, `jsonld`, `microdata`, `og`, `js_state`, `xhr`, `config` (executor from SPEC-08 behind a
  protocol; `api` source kind is produced by SPEC-09).
- Entities and ownership; `select_target`; the `conflict` outcome.
- Preference: agreement for exact-match types; `source_precedence.yaml` for text/url/image.
- Atomic offers; URL-parameter rule; derived values with `derived_by`.
- Evidence buckets; `calibration.json`; τ abstention; `calibrated` flag; record confidence.
- Record and `field_meta` assembly; incomplete pages (`partial` / `no_match`, §10); zero records for blocked/shell.
- Cold listings from structured data; generic pagination (`rel=next` + structural numbered links).
- The LLM gap-filling call site (role C is SPEC-06; this spec defines the hook).
- `crawlerai eval calibrate` / `fit-precedence` logic (entry points from SPEC-03).

Out of scope (§22 unless noted):
- Learned ranker, LLM adjudication, independent verifier, self-consistency.
- Generic structural DOM collectors (repeated structure, label–value pairs, typed value spotting).
- Variant matrices: SPEC-13 (admitted, ARCHITECTURE Appendix A #37). Page-type gate (§23). Any `[class*=…]`, bare `h1`, card selectors (§8.1).
- Learning/induction (SPEC-08); role C prompt (SPEC-06).

## 3. Dependencies

- SPEC-01, SPEC-02 (bundle, block class, adapters), SPEC-03 (harness, calibration entry points), SPEC-04 (types,
  equality). SPEC-06 provides `LLMClient` and role C; until then the hook is a no-op stub.
- OPEN_QUESTIONS #3: τ = 0.97 core, 0.95 optional (§10).

## 4. Design

### 4.1 Modules

- `crawlerai.content.page` — `ParsedPage.of(bundle)`: built once per capture per pipeline run (§8, Appendix A #31,
  INV-26). It lazily holds the selectolax tree, the lxml tree (only when an XPath step or trafilatura asks), the
  `<script>` blocks (`application/ld+json`, `application/json`, inline), `cleaned_text` and `visible_values`. Every
  consumer below takes the `ParsedPage`, never the raw body.
- `crawlerai.content.text` — `cleaned_text(page) -> CleanedText` (text + `offsets: list[(start, end, node_path)]`),
  `visible_values(page) -> VisibleIndex` (set of normalized text tokens/strings for visibility checks).
- `crawlerai.collect.base` — `Candidate`, `Entity`, `Collector` protocol: `collect(page, schema, ctx) -> CollectResult`.
- `crawlerai.collect.jsonld`, `.microdata`, `.og`, `.js_state`, `.xhr`, `.adapter`, `.config` (protocol only; the
  executor is injected by SPEC-08).
- `crawlerai.collect.schema_org_map` — resolves `schema_org` paths against entities (shared by jsonld/microdata).
- `crawlerai.resolve.ownership` — entity graph, `owner_of(candidate)`.
- `crawlerai.resolve.intent` — `select_target(request_url, final_url, canonical, entities)`.
- `crawlerai.resolve.preference` — agreement + `source_precedence.yaml` loader.
- `crawlerai.resolve.evidence` — bucket assignment; `Calibration` loader; τ.
- `crawlerai.resolve.pipeline` — `extract_page(...)` = `replay_page(...)` (SPEC-03 signature).
- `crawlerai.resolve.records` — record/field_meta assembly, `no_match`, fingerprint input.
- `crawlerai.resolve.pagination` — `next_page_candidates(page)`.
- `crawlerai.resolve.calibrate` — logic behind SPEC-03's `calibrate`/`fit-precedence`.

### 4.2 Core types

```python
class Entity(BaseModel, frozen=True):
    id: str                       # "jsonld:0:$.@graph[2]" | "microdata:/html/body/div[3]" | "adapter:job" | "page"
    kind: str                     # schema.org type name when known ("Product", "Offer", "JobPosting", "ItemList", "ListItem"), else "page"
    urls: tuple[str, ...]         # canonicalized url/@id/mainEntityOfPage/offers.url values found on the entity
    parent: str | None

class Candidate(BaseModel, frozen=True):
    field: str
    entity_id: str
    source_kind: SourceKind       # §6 enum
    raw: str | dict | list
    normalized: NormalizeResult
    locator: str                  # see 4.3
    independent: bool             # False for js_state/xhr values admitted only by equality to another candidate

class FieldOutcome(BaseModel, frozen=True):
    status: Literal["published", "missing", "conflict", "abstained"]
    reason: str | None            # "invalid", "ambiguous", "not_owned", "below_tau", "no_candidates", "disagree", "uncalibrated_optional"...
    value: Any | None
    evidence: Evidence | None     # §10 buckets
    confidence: float | None
    calibrated: bool
    source_kind: SourceKind | None
    locator: str | None
    derived_by: str | None
    chosen: Candidate | None
    rejected: list[tuple[Candidate, str]]

class ExtractionResult(BaseModel, frozen=True):
    outcome: Literal["extracted", "partial", "no_match", "blocked", "shell", "not_found", "error"]  # = url_task.outcome (§6); "error" is stored as "failed"
    entity: FieldSet | None                 # detail: one; listing: page-level fields
    rows: list[FieldSet]                    # listing rows
    candidates: list[Candidate]
    llm_calls: list[LLMCallRecord]
    mode: Literal["adhoc", "config"]
    record_confidence: float | None
```

### 4.3 Locator format (defined here; §6 only names it)

A string `"<scheme>:<address>"`:
- `jsonld:<block_index>:<jsonpath>` — block = nth `application/ld+json` script; path within the block as written
  (not its expanded graph), so the locator reads back from the capture.
- `microdata:<xpath>` — XPath 1.0 to the `itemprop` element.
- `meta:<property>` — `<meta property|name=…>` (OpenGraph and standard meta).
- `js_state:<script_xpath>:<jsonpath>`.
- `xhr:<n>:<jsonpath>` — nth captured network body in the bundle.
- `adapter:<adapter_name>:<jsonpath>`.
- `api:<recipe_id>:<jsonpath>` (SPEC-09).
- `config:<field>:<step_index>:<selector>` (SPEC-08).
- `text:<start>-<end>` — char offsets into `cleaned_text` (role C, SPEC-06).

Induction (SPEC-08) reads these; the `jsonld`/`microdata`/`meta` forms are already site-stable or generalizable.

### 4.4 Cleaned text

Deterministic, on the `ParsedPage`'s selectolax tree (no second parse); drop `script`, `style`, `noscript`, `template`, `svg`, hidden elements
(`hidden` attribute, `aria-hidden="true"`, inline `display:none`/`visibility:hidden` — HTML/CSS standards);
emit text per block element separated by `\n`, inline text joined by space, entity-decoded, whitespace
collapsed. Each emitted run records `(start, end, node_xpath)`. The `VisibleIndex` holds every emitted run plus
every `alt`, `title`, `value` and `content` attribute of visible elements, text-normalized (SPEC-04 text rules),
for `visible(value) -> bool`.

### 4.5 Collectors (§8.1)

All run on every `ok` capture (§8.2 rule 1). Each returns candidates + entities and never raises (errors become
an empty result with a diagnostic).

- **jsonld**: parse every `application/ld+json` block (tolerate trailing commas? No — JSON only; invalid blocks
  are skipped with a diagnostic). Expand `@graph`, resolve `@id` references within the page, normalize
  `http://schema.org` ↔ `https://schema.org`. Entities = nodes with `@type` in the schema.org vocabulary file.
  For each schema field with `schema_org = "T.p[.q]"`, for each entity of type T (or subtype per the vocabulary
  file's `subClassOf`), the value at the path is a candidate owned by that entity. `+` paths produce one dict
  raw value. `Offer` values are owned by the Offer entity whose parent is the Product (atomic offers, 4.8).
- **microdata**: `itemscope`/`itemtype`/`itemprop` per the HTML standard; the same schema.org mapping; nested
  scopes nest entities. RDFa Lite (`typeof`/`property`) is handled by the same module (HTML standard); keep it
  minimal.
- **og**: `og:*` and `product:*` properties per the Open Graph protocol (ogp.me): `og:title`→text fields whose
  `schema_org` ends in `.name`, `og:image`→image fields, `og:url`→url fields, `product:price:amount` +
  `product:price:currency`→money, `product:availability`→availability. The mapping is a fixed table keyed by
  OGP property and field type/role, justified by ogp.me (C2). Entity = `page`.
- **js_state**: every `<script type="application/json">` and every `<script>` whose text, after the first `=`
  of a `window.<ident>` / `var|let|const <ident>` assignment, parses as JSON (structural; no site key names).
  Values become candidates only if (a) `equal(normalized, other.normalized)` for some candidate from another
  source kind (then `independent=False`), or (b) `visible(raw)` and `checkable(raw, spec)` (then `independent=True`):
  the field's type has a syntax its normalizer checks (money, enum, date, datetime, location, range, a gtin or isbn
  identifier, a url given absolute; `normalize.dispatch.checkable`). Text and other opaque types admit by (a) only,
  since any visible string normalizes as text (ARCHITECTURE §8.1, Appendix A #34). Keys are not mapped
  through anything; every scalar leaf is tested against the field's normalizer, which is the only filter. To
  bound cost, leaves are considered only for fields still lacking a candidate or for agreement checks.
- **xhr**: the bundle's captured JSON bodies, same admission rule as js_state. (Also feeds SPEC-09 discovery.)
- **adapter**: `source_kind='adapter'`, entity from the adapter's JSON object, locator `adapter:…`, using the
  adapter's `map(schema)`.
- **config**: `ConfigExecutor` protocol (`crawlerai.collect.config`), bound to its IR because `config_ir` sits above
  `collect` and `resolve`: `execute(page, schema, ctx) -> Executed` (listing row entities, candidates, diagnostics) and
  `field_status`; candidates have `source_kind='config'` and `independent=False`; injected when a config is active
  (SPEC-08).

No collector contains a hostname, a class-name fragment or a phrase list (C2/C3; the scan covers `collect/`).

### 4.6 Ownership and intent (§8.2 rule 3, §10)

- A candidate's owner is its entity; entities form a tree (JSON nesting / DOM nesting). `page`-owned candidates
  (og, meta, text) are owned by the page root.
- The target owns its own candidates, the page's, and those of an Offer whose parent is the target or one of the
  target's `hasVariant` variants. A variant's other values (its sku, its name) are the variant's and not owned.
- `select_target(request_url, final_url, canonical_url, entities) -> Entity | Ambiguous`:
  1. Candidates: entities of the schema's primary type (the type named by the schema's required fields'
     `schema_org` roots; e.g. `Product`, `JobPosting`) excluding entities nested inside `ItemList`/`ListItem`
     or inside another primary-type entity's `isRelatedTo`/`isSimilarTo` (schema.org relations — standard), and
     a primary-type entity's variants (schema.org `hasVariant`: members of a `ProductGroup`, which often repeat
     the group's URL).
  2. If exactly one candidate → target.
  3. Else those whose `urls` contain any of `{request_url, final_url, canonical_url}` canonicalized; exactly one →
     target; several or none → `Ambiguous`.
  4. The `page` entity is the target's ancestor, so page-level candidates (og/meta/text) are attributed to the
     target only when step 2 or 3 produced one; when the primary type is absent (no structured entity at all)
     the page itself is the target (cold pages without markup).
- Ambiguous → every field is `conflict` with reason `intent_ambiguous`; the page is incomplete and handled per
  4.10 (`partial` for caller-supplied URLs, `no_match` for crawl-discovered ones).
- `select_variant(request_url, final_url, canonical_url, graph, target) -> Entity | None` (SPEC-13 §4.6, detail
  pages): of the target's variant holders (its `hasVariant` members and the Offers directly under it; never an
  `AggregateOffer`, a summary of offers), the one whose own `urls` contain a page URL, when exactly one does: step
  3's URL test applied to variants. Whole canonicalized URLs are compared; no query parameter is read (INV-13).
  The page URL with no variant named selects none (no first or cheapest default, C7).

### 4.7 Preference (§10)

- Valid, owned candidates only (`normalized` is `Ok`, owner == target or an `Offer` child of the target).
- Exact-match types (`money`, `identifier`, `enum`, `date`, `datetime`, `range`, `location`): if all agree
  (`equal`) → publish; else → `conflict` (INV-14). `location` is included here as exact-match because its
  normalized form is a code tuple; note in Open issues.
- `text`, `long_text`, `url`, `image_url`: the first source kind in `source_precedence.yaml[type]` that has a
  valid owned candidate wins; candidates of lower-ranked kinds that disagree are recorded as `rejected` with
  reason `precedence`.
- `source_precedence.yaml` (repo file `backend/data/source_precedence.yaml`, stamped `source_split: dev`,
  INV-02): `{text: [adapter, api, jsonld, microdata, og, config, llm], url: [...], image_url: [...]}`. Initial
  order is this default; `fit-precedence` (4.11) rewrites it from dev.
- Listings (`page_kind=listing`): rows are entities of the row type (`ItemList.itemListElement` items, or every
  top-level `Product`/`JobPosting` when ≥ 3 exist and no detail target exists); each row resolves its row-scoped
  fields with the same rules; page-scoped fields resolve against the page entity.

### 4.8 Rules from §8.2 and §10

- **Atomic offers** (INV-15): `price`, `availability` (and `currency` within money) must come from the same
  `Offer` entity. When several Offers exist, the target's own and its variants' (§4.6), the field is `conflict`
  (`offers_disagree`) unless all Offers agree; `AggregateOffer.lowPrice/highPrice` are never published as price
  (they feed `range` fields only).
- **Selected variant** (INV-36, SPEC-13 §4.6): when `select_variant` selects a holder, the Offer fields come only
  from its Offers (the selected Offer, or the selected variant's); other holders' Offer candidates are rejected
  `other_variant`, and INV-15 holds inside the holder.
- **Variant fill** (SPEC-13 §4.6): a `gtin` or `sku` identifier field for which no candidate is the target's takes
  the selected variant's own candidates; with no variant selected, its variants' only when every variant has one
  and all agree (else it stays as it was). A value the target states is never replaced; no other field is filled.
- **Row-mapped fields** (SPEC-13 §4.3 to §4.5, `resolve/rows.py`): on a detail page, a row-mapped `list<object>`
  field's rows are the entities its row path reaches from the target; sub-field candidates belong to the row whose
  scope holds their owner (else `not_in_row`); rows are matched by key into variants (`no_row_key`,
  `row_key_conflict`); each variant resolves its sub-fields with these rules, its scope as owner (atomic offers per
  row, INV-35), in the `list.<type>|<evidence>` buckets; the field's outcome carries `items` and `dropped`.
- **URL parameters** (INV-13): a candidate whose raw value equals a query-parameter value of the request URL is
  rejected (`url_param`) unless `visible(raw)`.
- **Derived values** (C7, INV-07): the only derivations in core: `url` (detail) ← `<link rel=canonical>` else
  `final_url` with `derived_by = "canonical_link" | "final_url"`; relative `image_url`/`url` absolutized with
  `derived_by = "absolutize"` — only when the field has no published candidate. Each derivation is a named
  function in `resolve/derive.py` with a standards justification; adding one is a C2/C13 review item.
- **Blocked/shell** (INV-11): `extract_page` returns `outcome = block_class` with no candidates when
  `block_class != ok`.

### 4.9 Evidence, calibration, τ (§10, INV-02)

Bucket of a published field:
- `adapter` if source kind is adapter or api;
- `agreed` if ≥ 2 **independent** candidates of different source kinds agree with the chosen value (js_state/xhr
  candidates with `independent=False` do not count — see Open issues);
- `structured` if one structured kind (jsonld/microdata/og);
- `config_corroborated` / `config_uncorroborated` from the config's field status (SPEC-08; for `operator` fields
  see SPEC-08 Open issues);
- `llm_grounded` for role C values.

`backend/data/calibration.json`:
```jsonc
{ "calibration_version": 1, "source_split": "dev", "eval_run_id": "...", "git_sha": "...",
  "buckets": { "money|structured": {"n": 112, "precision": 0.982}, "text|llm_grounded": {"n": 12, "precision": null} } }
```
- `confidence = buckets[f"{type}|{evidence}"].precision`; `calibrated = n >= 30`.
- If `calibrated` and `confidence < τ` (0.97 required, 0.95 optional) → `abstained(below_tau)`.
- If not calibrated → publish with `calibrated=false` (§10 text; precision-first alternative noted in Open
  issues).
- `record_confidence = min(confidence over required fields that published)`; `None` if any is uncalibrated.
- `calibrate` (4.11) recomputes the file from a dev run; the engine version hash changes with it (SPEC-01 4.7).

### 4.10 Records and `no_match`

- `record.data` = published values only; `field_meta[field]` = `{status, reason, evidence, confidence,
  calibrated, source_kind, locator, derived_by}` for every schema field (INV-22).
- `entity_key` = `sha256(site_id + canonical url of the target)`; listings: one record per row keyed by row url.
- Incomplete pages (§10 "Incomplete pages"): when any required field or group is not `published`.
  - Crawl-discovered URLs (SPEC-10 `crawl`): outcome `no_match`, **no record**.
  - Caller-supplied URLs (`scrape`, `batch_scrape`, `extract`): the record is stored and returned with per-field
    statuses and `record.complete=false` (§6), outcome `partial`. The caller chose the page kind (§23), and every
    unpublished field says why.
- A page whose required fields and groups all publish has outcome `extracted` and `record.complete=true`.

### 4.11 Calibration and precedence fitting (dev only)

- `calibrate(run) -> calibration.json`: for each `(field_type, evidence)` over the dev run's published fields,
  `n` and `precision` per SPEC-03 4.6. Refuses `split != dev`.
- `fit-precedence(run)`: for each of text/url/image_url, order source kinds by per-kind precision on dev (ties
  broken by coverage), excluding kinds with `n < 30` (kept in their current position). Writes
  `source_precedence.yaml` with `source_split: dev`.

### 4.12 Pagination (§8.6)

`next_page_candidates(page) -> list[url]` (ordered):
1. `<link rel="next">` and `<a rel="next">` (HTML standard).
2. Structural numbered links: among same-document-path `<a href>` links, group those that differ from the
   current URL only in one integer path segment or one integer query parameter (parameter name irrelevant);
   the link whose integer equals current+1 is a candidate. No parameter-name list (C4).
3. An active config's `listing.next` step (SPEC-08).
Infinite scroll is not handled here (§7.2/SPEC-09).

### 4.13 LLM hook (filled by SPEC-06)

After preference, in `cold` mode, for required fields with status `missing` (no candidates) — not for
`conflict` (adjudication is a candidate): `llm.role_c(cleaned_text, schema, missing_fields, budget) ->
list[Candidate]` with `source_kind='llm'`, `locator=text:…`, owner = target. In `active` mode the hook runs only
for fields the config doesn't cover, including fields suspended by drift (§8.3, §8.4; SPEC-08 4.8–4.9). Those
candidates go through the same validity and τ stages (`llm_grounded` bucket). `conflict` fields are never sent to
the LLM.

### 4.14 Error handling

Collector exceptions are caught per collector and logged as diagnostics on the `extraction` row (`llm_calls` and
a `diagnostics` jsonb — plumbing). The pipeline never partially publishes: an exception in resolution yields
`outcome='error'` and no record.

## 5. Invariants

INV-07, INV-11, INV-12 (consumer side: the pipeline re-checks `text:` locators), INV-13, INV-14, INV-15, INV-22,
INV-02 (calibration file source split), INV-03 (no literals in `collect/` and `resolve/`), INV-26 (one parse per parser per
pipeline run: a test counts parser constructions in `extract_page`), INV-27 (resolution is the last step that
sets a value; records storage only serializes).

## 6. Testing strategy

- INV-26: a test wraps the selectolax and lxml parser constructors with counters and asserts at most one
  construction each per capture in `extract_page`.
- Property tests: INV-14 with generated candidate sets; INV-13 with generated URLs/params; INV-07 derivations;
  `agreed` requires independence.
- Unit tests on synthetic HTML/JSON-LD fixtures under `tests/fixtures/synthetic/` (hosts `example.test`,
  product names generated): multi-Product pages with recommendation lists → intent picks by URL or conflicts;
  AggregateOffer never published as price; shell → zero records; microdata nesting; og fallbacks.
- Replay tests on dev captures (SPEC-03): precision/coverage per bucket must be computed and non-regressing on
  the dev report; no assertion names a site.
- Calibration: synthetic run → file; τ abstention behaviour at n=29 vs 30 and precision 0.969 vs 0.97.
- CI gates: backend, site-literals, protected job (this package triggers the aggregate-report requirement).

## 7. Acceptance criteria (§21 L1 done-when, this spec's share)

- The report computes precision and coverage per field type and per evidence bucket from labels (tested on
  synthetic labeled fixtures); unlabeled pages report coverage only, and every field is `calibrated=false`.
- **Milestone M (§21; not required to mark this spec done):** published dev and hidden numbers; wrong-product = 0 on dev and hidden.
- All §8.2 rules and §10 stages have tests that fail if the rule is removed.
- `extract_page` is the single function used by the worker and by `replay_split`.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | `ParsedPage` + cleaned text + visible index | `content/page`, `content/text` | unit, property (offsets map back to text) | Offsets correct; one parse per parser. |
| 2 | Candidate/Entity/Outcome models, locator format | `collect/base`, `resolve` types | unit | INV-22 model tests. |
| 3 | JSON-LD collector + schema.org map | `collect/jsonld,schema_org_map` | unit | Expands @graph, nested Offers. |
| 4 | Microdata/RDFa Lite collector | `collect/microdata` | unit | Nested scopes. |
| 5 | OpenGraph collector | `collect/og` | unit | OGP table. |
| 6 | Ownership + intent | `resolve/ownership,intent` | unit | Multi-entity cases. |
| 7 | Preference + atomic offers + URL-param rule + derivations | `resolve/preference,derive` | property | INV-13/14/15/07. |
| 8 | Evidence buckets, calibration loader, τ, records | `resolve/evidence,records`, `data/calibration.json` (empty) | unit | Flags correct. |
| 9 | Pipeline `extract_page` + worker handler for scrape tasks + blocked/shell | `resolve/pipeline` | unit, replay, parser-count test | INV-11, INV-26. |
| 10 | js_state + xhr collectors with admission rule | `collect/js_state,xhr` | unit | Independence flag set. |
| 11 | Adapter collector | `collect/adapter` | unit | Greenhouse/Lever fixtures map. |
| 12 | Cold listings + pagination | `resolve/pagination`, listing rows | unit | rel=next + structural rule. |
| 13 | calibrate / fit-precedence logic | `resolve/calibrate` | unit | Files written from a dev run. |

## 9. Open issues

- **Review finding (`agreed` circularity).** Resolved in ARCHITECTURE rev 5 §8.1 and §10: the `independent` flag;
  only independent candidates count toward `agreed`.
- **Review finding (`no_match` scope).** Resolved in ARCHITECTURE rev 5 §10 "Incomplete pages": `partial` records
  with `complete=false` for caller-supplied URLs, `no_match` and no record for crawl-discovered ones (4.10).
- **Review finding (uncalibrated buckets publish).** Resolved in ARCHITECTURE rev 5 §10: publish-with-flag is a
  deliberate trade-off for progressive cold mode. Implemented as written.
- **`location` as exact-match.** Resolved in ARCHITECTURE rev 5 §10, which lists `location` among the exact-match
  types. Region-spelling disagreement becomes `conflict`; measured on dev.
- **Derived `url` field.** C7 names derived values but the architecture lists none. The canonical-link
  derivation is the only one here; confirm it is wanted.
- **Required fields in commerce_detail** (image_url) will make `no_match`/incomplete common on real pages; this is
  measured, not fixed here. `brand` is optional from preset version 2 (ARCHITECTURE Appendix A #35).
