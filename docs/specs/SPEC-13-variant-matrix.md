# SPEC-13 — Variant matrix: per-variant rows from structured data

Layer: admitted candidate (ARCHITECTURE §22, Appendix A #37); builds on L1 (SPEC-04, SPEC-05) and on variants
step A (Appendix A #36, PR #168). Architecture refs: §5.1, §5.2, §5.3, §8.1, §8.2 rule 3, §8.3, §8.4, §10 (atomic
offers, evidence), §13.1, §16.2, §16.3, C2, C3, C4, C7, C8, C9, C10.

## 1. Summary

A product page often offers several variants (sizes, colours), each with its own identifiers, price and
availability. Core resolves one price and one availability per page, so a page whose variants differ in price is a
`conflict` (`offers_disagree`), and the per-variant data is lost. This spec adds:

1. a schema grammar for a `list` of `object` field whose rows are structured-data nodes and whose sub-fields map
   through their own `schema_org` paths, plus `|` alternatives in any `schema_org` path;
2. row resolution: rows found from the target entity, matched across sources by a declared key, each sub-field
   resolved by the §10 rules inside its row, with provenance per sub-field;
3. preset `commerce_detail` with an optional `variants` field;
4. a common-value rule for the single `price`, `availability`, `sku` and `gtin`: they publish only a value every
   variant shares, and what varies is published only in `variants` (owner, 2026-10-16; Appendix A #44);
5. the label format and eval scoring for row-valued fields.

Only the structured collectors (JSON-LD, microdata/RDFa Lite) produce rows in this version. Learning, role C,
`js_state`/`xhr` and adapters produce no rows (§4.9). Everything is generic: schema.org types and properties name
the structure, and no platform, store or page shape is named in code (C2, C3).

**Evidence (owner review, 2026-10-15).** A baseline run without an LLM over 49 multi-variant product pages on 10
stores of one hosted commerce platform:
- `price` published on 41% of pages, `availability` on 37%; 14% of pages were complete;
- 44 of 49 pages carry several Offers or `hasVariant`;
- 9 of 10 stores publish one Offer per variant in JSON-LD: 357 Offers, each with price, currency and
  availability; a distinct sku on 237 and a gtin on 183;
- failures by class: `offers_disagree` on 12 pages; Offers only under `hasVariant` on 19 pages; variants that
  repeat the group URL on 5 pages. Step A (#168) fixes the last two classes; this spec addresses the first and
  publishes the matrix.

Prices can depend on where the page is fetched from (the currency served). A record states the currency the
capture served; nothing here converts or defaults one (C7).

## 2. Scope

Core (admitted by the owner, Appendix A #37):
- `schema_org` alternatives (`A|B`) for every field (SPEC-04 §4.2 grammar).
- Row-mapped `list<object>` fields: a row path, sub-field paths, a `key`.
- Row discovery, row matching, per-row preference (agreement, precedence, atomic offers), evidence and τ per
  sub-field.
- `FieldOutcome.items` and `record.field_meta.<field>.items`; the records API shape (additive).
- Preset `commerce_detail`: `variants`, optional.
- Common values for top-level offer fields, and variant fill for empty top-level identifier fields.
- Role C and learning skip row-mapped fields (stated limits, §4.9).
- Label format extension and eval scoring for row-valued fields (code and synthetic tests; no labels).

Out of scope:
- Platform JSON adapters, including any commerce platform's product JSON endpoint (owner: not now; §22 "More
  platform adapters").
- Rows from `js_state`, `xhr`, Open Graph, configs, role C or adapters.
- Top-level variants linked only by `isVariantOf` (§9).
- A top-level `object` field mapped by sub-field paths (it keeps reading literal JSON keys, SPEC-04 §4.4).
- Currency conversion. Stock quantities (`inventoryLevel`) and availability read from page text are SPEC-04's
  (rows 10–11, D-0782); `stock_quantity` is a sub-field of each row (§4.7).
- The labeling screen's row editor and a variants table in the records screen (§9).
- Any default variant, including one a page URL names (owner, 2026-10-16). schema.org has no "default variant"
  property.

## 3. Dependencies

- SPEC-04: `FieldSpec`, the path grammar, `normalize`/`equal` for `list` and `object`.
- SPEC-05: collectors, `EntityGraph`, `select_target`, `Resolver` (preference, atomic offers), evidence, records.
  Step A (#168, Appendix A #36) must be merged first: `hasVariant` members are excluded from target candidates
  and their Offers are the target's.
- SPEC-03 §4.3 and §4.6: label format and metrics. SPEC-06 §4.4: role C gap request. SPEC-07: record output.
  SPEC-08 §4.5: induction. SPEC-11 §4.4: `changed_fields`.

## 4. Design

### 4.1 Path grammar (SPEC-04 §4.2, extended)

```
schema_org   := alternative ('|' alternative){0,3}
alternative  := Type ('.' property)+ ('+' property)?       // as today
```

- **Alternatives** (at most 4). For a value field, the candidates are the union of every alternative's
  candidates; the same value at the same locator reached twice is one candidate. Agreement (exact-match types) or
  precedence (text, url, image) then decides as today (§10). No alternative outranks another: an order would be a
  precedence rule nobody fitted (C7). Example: `"Product.sku|Offer.sku"` (schema.org defines `sku` on both).
- `parse_paths(path) -> tuple[MappedPath, ...]` replaces `parse_path` for every consumer: `collect/adapter`,
  `collect/og` (a field's role is the property its alternatives name on their root type, when every two-step
  alternative names the same one; otherwise none; the `.name` text-stands-in rule stays in
  `schema_org_map.select`), `resolve/derive`, `resolve/intent` (primary
  types are the roots of every alternative), `resolve/preference` (an Offer field is one whose every alternative
  starts at `Offer` or a subtype), `resolve/records`.
- Every alternative is checked against the pinned schema.org vocabulary as today.

### 4.2 Row-mapped `list<object>` fields

A `list` field whose `item` is an `object` and which has a `schema_org` path is **row-mapped**:

```jsonc
"variants": {
  "type": "list", "description": "...",
  "schema_org": "ProductGroup.hasVariant|Product.offers|Product.offers.offers",   // the row path
  "key": ["gtin", "sku", "url"],                                                   // sub-fields that identify a row
  "item": { "type": "object", "fields": {
      "sku":   { "type": "identifier", "scheme": "sku", "description": "...", "schema_org": "Product.sku|Offer.sku" },
      "price": { "type": "money", "description": "...", "schema_org": "Offer.price+priceCurrency" } } }
}
```

Rules, checked by the schema document model:
- The **row path** names nodes, not values: no `+`. Its root is the type of the entity the rows belong to (the
  holder). Each step must reach typed entities; a value that is not an entity reaches no row.
- Each **sub-field** has its own `schema_org` path (or none: then no structured source fills it). Sub-fields of a
  row-mapped field are leaf types (not `list` or `object`); with `MAX_DEPTH = 3` this is already the deepest level.
- **`key`** is required on a row-mapped field and allowed nowhere else. It names one to three sub-fields, each of
  type `identifier` or `url`: an identifier identifies a thing by definition (GS1, ISO 2108, a seller's sku), and a
  URL identifies a resource (RFC 3986 §1.1).
- A `list<object>` field without `schema_org` keeps today's behaviour (SPEC-04 §4.4: literal keys).

Collectors (`schema_org_map.field_candidates`, shared by JSON-LD and microdata, so the two stay at parity): for a
row-mapped field, the row path yields **no** candidates; each sub-field yields candidates exactly as a top-level
field does (every entity of the alternative's root type, every value its path reaches), with
`Candidate.field = "<field>.<sub-field>"` (for example `variants.price`). `Name` allows no `.`, so the name cannot
clash. The candidate is owned by the entity that holds the value, and its locator is that value's own locator.
Rows are found during resolution, from the entity graph (§4.3), not by the collectors.

### 4.3 Row discovery (`resolve/rows.py`)

Given the target `T` (SPEC-05 §4.6) and a row-mapped field:

1. **Reach.** For each alternative whose root `T` is an instance of (vocabulary subclass), follow its steps through
   `Entity.parent`/`Entity.via`: step `p` from entity `E` reaches the entities whose parent is `E` and whose `via`
   is `p`. JSON-LD nodes referenced by `@id` already have their referrer as parent (SPEC-05 §4.5). Only paths
   starting at `T` count, so a variant's own `offers` are not rows of the group.
2. **Not rows.** An `AggregateOffer` is never a row: schema.org defines it as a summary of several offers, not an
   offer of one item; its `lowPrice`/`highPrice` never become a row's price (§10). A reached entity with another
   reached entity of the same field below it is not a row either: rows do not nest, and the outer node groups
   them (structural).
3. **Scope.** A row's scope is the row entity and the entities below it, stopping at another row and at entities
   under `isRelatedTo`, `isSimilarTo` or inside an `ItemList` (the SPEC-05 §4.6 exclusions). A sub-field candidate
   belongs to the row whose scope holds its owner. A sub-field candidate in no row's scope is rejected
   `not_in_row`.

Evidence of the shapes this covers (baseline above): a `ProductGroup` with `hasVariant` products, each with an
`offers` Offer (step 1, first alternative; the Offer is in the variant's scope); a `Product` with one Offer per
variant (second alternative); an `AggregateOffer` holding `offers` (third alternative, step 2). Microdata gives
the same graph through `itemprop` (SPEC-05 §4.5), so the same rules apply.

### 4.4 Row matching

The same variant can appear several times: in JSON-LD and in microdata, or as a `hasVariant` product and as an
Offer of the group. Rows are matched by key, never by position.

- A row's **key values** are the `Ok` normalized values of its key sub-fields' candidates in its scope, screened
  for INV-13 (URL parameters) as usual.
- A `url` key value equal (url equality, SPEC-04 §4.5) to the request, final or canonical URL, or to the target's
  own `url`, IRI or `mainEntityOfPage`, is not a key value: it names the page or the group, not one variant. The
  target's Offers' `url` values are not excluded (`Entity.urls` includes them, SPEC-05 §4.2): in the
  one-Offer-per-variant shape each Offer's url is its row's key. A url that both the target and one of its Offers
  carry is that row's key only when no other row carries it; repeated by several rows, it names the group and is
  not a key value. The baseline shows
  variants that repeat the group URL (5 pages).
- Rows **link** when they share a value of some key sub-field. Linked rows form a cluster (connected
  components; the order of comparison does not matter).
- A cluster in which one key sub-field has two different values is dropped as `row_key_conflict`: two variants
  were joined, or one source is wrong, and the engine cannot tell which (C7). A row with no key value is dropped
  as `no_row_key`.
- **Order.** Clusters are ordered by their earliest row entity in collector order (JSON-LD blocks, then microdata,
  each in document order). The order is deterministic for a given capture. `changed_fields` compares canonical
  JSON (SPEC-11 §4.4), so a site that reorders its variants shows `variants` as changed. That is reported, not
  hidden.

### 4.5 Per-row resolution

Each cluster is resolved like an entity, by the existing `Resolver` stages, with the cluster's scope as the owner:
- **Validity, URL parameters**: unchanged.
- **Preference**: exact-match sub-fields (money, identifier, enum) publish when every kept candidate in the cluster
  agrees, else `conflict` (INV-14). Text and url sub-fields use `source_precedence.yaml` for their type.
- **Atomic offers per row** (INV-35): a row's `price` and `availability` come from one Offer in the row's scope.
  With several Offers in one row, the `offers_disagree` / `offer_split` rule of SPEC-05 §4.8 applies inside the
  row.
- **Evidence and τ** per sub-field: the §10 buckets, keyed `list.<type>|<evidence>` in `calibration.json` (for
  example `list.money|agreed`). They are separate from the top-level buckets because a row value can be wrong in
  a way a page value cannot (wrong row match). τ is 0.97 when the list field and the sub-field are both required,
  else 0.95. A sub-field below τ abstains on its own.
- **A row publishes** when at least one key sub-field publishes; otherwise it is dropped as `key_unpublished`.
  Its other sub-fields publish or not one by one, each with its status and reason.

**The field's outcome.**
- `published` when at least one row publishes. `value` is the list of rows, each an object holding only its
  published sub-fields (SPEC-04 types, as at top level).
- Field-level attributes required by INV-22: `evidence` is `agreed` when every published sub-field of every row is
  `agreed`, else `structured` (the only buckets structured sources give); `confidence` is the minimum over the
  published sub-fields, and `calibrated` is true only when all are; `source_kind` and `locator` are those of the
  first published row's entity (a `jsonld:` or `microdata:` locator).
- `items`: one entry per published row, aligned with `value` by index, holding a `FieldOutcome` per sub-field
  (published or not, with reason). `dropped`: the rows that did not publish, each with its row locators and
  reason. Sub-field outcomes use the same model as top-level ones, so INV-22 holds per sub-field (INV-34).
- No row publishes: `abstained` (`below_tau`) when every row was dropped because its sub-fields abstained,
  else `missing` with the furthest reason reached (`no_rows`, `no_row_key`, `row_key_conflict`,
  `key_unpublished`).

### 4.6 Common values and the single offer fields (§10 atomic offers)

Owner, 2026-10-16 (Appendix A #44, D-0945): "no default — all variant schema goes into variants and common schema
stays out of variants, simple." `price`, `availability`, `stock_quantity`, `sku` and `gtin` at the top level mean the
product's value when every variant has the same one. A value that varies across variants is published only in the
row-mapped `variants` field (§4.5). This rule does not depend on whether the schema has a `variants` field.

- **Offer fields.** Every Offer of the target and of its `hasVariant` members joins the atomic-offer rule (SPEC-05
  §4.8), so the fields publish only when all agree, else `conflict` (`offers_disagree`). No variant is selected:
  a request, final or canonical URL that names one variant does not make its Offer the source. A product with a
  single variant (or a single Offer) publishes its values at the top level.
- **Variant fill** applies to the identifier fields only: a top-level `sku` or `gtin` field (type `identifier`)
  for which the target itself has no owned candidate takes its variants' candidates only when every variant has
  one and all agree. No other top-level field is filled (`name`, `brand`, `image_url`, `url`, `color` stay the
  target's own), and a value the target states itself is never replaced. This refines D-0785: a variant's sku is
  published as the page's sku only when all variants agree.
- **Superseded (2026-10-16).** The earlier selected-variant rule (`select_variant`, the `other_variant` rejection:
  a URL naming exactly one variant made it the source of the offer fields) is removed. A page URL is no default.

### 4.7 Preset `commerce_detail`: `variants`

One optional field. The required fields and `required_groups` are unchanged, so completeness and
`record_fingerprint` (required fields only) are unchanged.

| Sub-field | Type | `schema_org` |
|---|---|---|
| `variant_id` | identifier (custom; Appendix A #42) | `Product.productID` |
| `sku` | identifier (sku) | `Product.sku\|Offer.sku` |
| `gtin` | identifier (gtin) | `Product.gtin\|Offer.gtin` |
| `price` | money | `Offer.price+priceCurrency` |
| `availability` | enum `schema:ItemAvailability` | `Offer.availability` |
| `stock_quantity` | count (version 4, D-0782) | `Offer.inventoryLevel` |
| `url` | url | `Product.url\|Offer.url` |
| `name` | text | `Product.name\|Offer.name` |
| `size` | text | `Product.size.name` |
| `color` | text | `Product.color` |
| `material` | text | `Product.material.name` |
| `pattern` | text | `Product.pattern.name` |

- Field `variants`: `list` of that object; row path `ProductGroup.hasVariant|Product.offers|Product.offers.offers`;
  `key: ["gtin", "sku", "url"]`; description "Every variant the buyer can choose (for example a size or colour),
  one entry each, with its own identifiers, price and availability".
- The distinguishing attributes are the schema.org `Product` properties that `variesBy` names in schema.org's own
  definition and examples (size, color, material, pattern), plus the variant's `name`. `size`, `material` and
  `pattern` accept a thing or text, so their paths end in `.name` (the text-stands-in rule, SPEC-05 §4.5).
  `variesBy` itself is not read: a property it names outside these four reaches the record only through `name`
  (§9).
- Each sub-field carries a description (SPEC-04 §4.2). `sync_presets` inserts version 3; version 2 rows stay.
- Version 4 (owner, 2026-10-16, D-0782; ARCHITECTURE Appendix A #39) adds the optional count `stock_quantity`
  (`Offer.inventoryLevel`) at the top level and in each row, and the row description names it ("…, price,
  availability and stock quantity"). A row's stock quantity comes from the row's own Offer, as its price and
  availability do; a variant whose Offer states none has none. Required fields are unchanged.
- `variant_id` (owner, 2026-10-16; ARCHITECTURE Appendix A #42, edited in place) is the `productID` a variant
  states, in its own scheme. It is not a key: `key` stays `["gtin", "sku", "url"]`. A variant that states none has
  none.

### 4.8 Records and API (SPEC-07)

- `record.data.variants`: the list of row objects, for example
  `[{"sku": {"scheme": "sku", "value": "A-1"}, "price": {"amount": "19.90", "currency": "EUR"},
  "availability": "InStock", "size": "M"}]`. CSV keeps encoding nested values as JSON (SPEC-08 §4.11).
- `record.field_meta.variants`: the usual `FieldMeta`, plus `items: [{fields: {<sub>: {status, reason, evidence,
  confidence, calibrated, source_kind, locator}}}]` aligned with `data.variants`, and
  `dropped: [{locators: [...], reason}]`. Both are optional keys on `FieldMeta` (absent for other fields), so
  the change is additive to the API and MCP shapes. `make api-client` regenerates the frontend types. The records
  screen shows the value as JSON, as it does today for lists (§9).
- `candidate` rows: sub-field candidates are stored with `field = "<field>.<sub>"`. No new column.

### 4.9 Learning, role C and other sources in this version

- **Learning (SPEC-08) produces no steps for a row-mapped field.** The validation report records
  `not_learned: row_field`. Reasons: induction generalizes one locator per field per page (§8.3), and a row field
  needs a row selector, sub-field selectors relative to it and row matching. The IR has that shape only for listing
  rows, which are separate records. In `config` mode the structured collectors still run (§8.4), so `variants`
  still publishes from structured data. Drift does not track the field.
- **Role C (SPEC-06) is never asked for a row-mapped field** (nor for any `object`-typed field). `_gaps` leaves
  them out, including as optional fields that ride along. Reasons: a role C claim is one verbatim span per field
  (SPEC-06 §4.4), a span cannot hold a row of typed sub-fields, and rows read from text could not be matched to the
  structured rows by key without the values role C would invent. A required row-mapped field in a custom schema
  that no structured source fills leaves the page `partial`. The labeling pre-fill skips the field the same way.
- **`js_state`, `xhr`, Open Graph, adapters**: no sub-field candidates. Embedded JSON has no standard keys, and
  admitting row values by equality needs a row structure the admission rule (§8.1) does not have.

### 4.10 Labels and eval (SPEC-03 §4.3, §4.6)

**Label format** (`label_version` 2; version 1 labels stay valid, and their row fields are unlabeled, so they are
not scored):

```jsonc
"variants": {
  "absent": false,                        // true: the page offers no variant choice
  "rows": [                               // one per variant shown on the page, in page order
    { "fields": {
        "sku":   { "value": {"scheme": "sku", "value": "A-1"}, "absent": false, "locator": "jsonld:0:$['offers'][0]['sku']" },
        "price": { "value": {"amount": "19.90", "currency": "EUR"}, "absent": false, "locator": "..." },
        "color": { "value": null, "absent": true, "locator": null } } } ],
  "distractor_keys": [ { "field": "sku", "value": {"scheme": "sku", "value": "B-7"} } ]   // other products' variants
}
```

**Scoring.**
- Engine rows are matched to label rows by the field's `key`, with the §4.4 rule: they share a key value and differ
  on none. An engine row that matches several label rows, or a label row that several engine rows match, counts as
  unmatched.
- For a matched pair, each sub-field is counted TP / FP / FN / TN as a top-level field is (SPEC-03 §4.6).
  An unmatched engine row is FP for each published sub-field. An unmatched label row is FN for each sub-field not
  labeled `absent`.
- An engine row whose key value appears in `distractor_keys` counts toward wrong product (WP, must be 0; the gate
  fails on any, §16.4).
- Reported per `(split, list.<type>)`, per `(split, schema, field.sub)`, and per `(split, list.<type>, evidence)`
  for calibration, plus row precision (matched engine rows / engine rows) and row recall (matched label rows /
  label rows). Hidden and fresh cells follow §16.3 suppression.
- `variants` is optional, so the precision gate on required field types does not cover it. The common-value rule
  (§4.6) governs required `price` and `availability` and is gated as usual.

### 4.11 Error handling

Row discovery and matching are pure functions of the graph and candidates. A cycle or an unknown parent cannot
occur (`CollectResult` checks the tree). An exception in row resolution fails the page as `error` like any
resolution bug (SPEC-05 §4.14), and nothing is partly published. Bodies are already bounded (INV-30); there is no
separate row cap.

## 5. Invariants

New (appended to `docs/INVARIANTS.md`):
- **INV-33**: A published row of a `list<object>` field holds only sub-field values owned by the entities of one
  key-matched cluster. Rows with conflicting key values, or with no published key sub-field, do not publish.
- **INV-34**: Every sub-field outcome of a published row carries status and reason. Every published sub-field
  carries `evidence`, `confidence`, `calibrated`, `source_kind` and `locator` (INV-22 per row).
- **INV-35**: A variant row's price, currency and availability come from one Offer in that row (INV-15 per row).
- **INV-36** (superseded by INV-38, 2026-10-16): A detail page's top-level offer fields come from a single variant
  only when the request, final or canonical URL names exactly that variant by its own URL. Otherwise they publish
  only when every Offer agrees.
- **INV-38**: A detail page's top-level offer fields, and a top-level `sku` or `gtin` filled from its variants,
  publish only a value every Offer (or every variant) states alike; no variant is a default, whatever a page URL
  names. Values that vary publish only in the row-mapped `variants` field.

Existing invariants that apply: INV-13, INV-14, INV-15, INV-22, INV-27.

## 6. Testing strategy

All fixtures are synthetic (`example.test`, generated product names, C3, C9). No test is named after a site or
platform.
- **Property (Hypothesis)**: generated schema documents with alternatives and row-mapped fields round-trip, and
  invalid ones (a `+` in a row path, a `key` naming a text sub-field, a nested list in a row) are rejected.
  Generated variant sets rendered as JSON-LD and as microdata give equal `variants` values (`equal`, multiset), so
  the parity is tested and not assumed. Row matching does not depend on row order: shuffling rows and sources
  gives the same clusters. Two rows with different keys never merge. A disagreeing sub-field in a cluster is
  `conflict` and never a value.
- **Unit**: each §4.3 shape (hasVariant with Offers; one Offer per variant; AggregateOffer with offers; an
  AggregateOffer alone gives no row); one Offer per variant whose Offers carry only a url (each Offer is a row);
  a ProductGroup with both direct Offers and `hasVariant` rows (matched by key); variants repeating the group URL
  (not a key value); a request URL naming one variant selects nothing (the offer fields stay `offers_disagree`
  when the variants differ); a price every variant shares publishes; variant fill does not replace the group's own
  value; `_gaps` never asks role C for a row-mapped field; learning reports `not_learned: row_field`.
- **Replay** (SPEC-03): dev captures before and after each PR. PR 1 must give identical records for presets v1/v2.
  PRs 2–3 report the differences.

## 7. Acceptance criteria

- Preset `commerce_detail` v3 loads. On synthetic fixtures of each §4.3 shape, `variants` publishes one row per
  variant with per-sub-field meta, in JSON-LD and microdata alike.
- On a synthetic page where the variants' Offers disagree, `price` and `availability` stay `conflict`
  (`offers_disagree`) whether or not the request URL names one variant, and each variant's price is in its
  `variants` row; where every variant agrees, the value publishes at the top level.
- INV-33–INV-35 and INV-38 each have a test that fails when the rule is removed.
- The eval computes per-sub-field and row metrics from synthetic labels in `label_version` 2.
- **Milestone M (not required to mark this spec done):** variant labels on dev; precision per `list.<type>` and
  row recall reported.

## 8. PR plan

Each PR writes its tests first. A PR that changes extraction includes the C10 evaluation section (the gate reports
`no_baseline` until M; acceptance rests on tests, replays and review, and the dev replay diff is in the PR body).

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Path alternatives and row-mapped `list<object>` grammar; sub-field candidates | `schemas/types` (`\|` pattern, `key`, row rules), `collect/schema_org_map` (`parse_paths`, sub-field candidates), consumers listed in §4.1, SPEC-04 §4.2 text, `make api-client` | property, unit; replay: identical records for existing presets | The grammar validates; JSON-LD and microdata emit equal sub-field candidates for generated variant sets. No extraction change. |
| 2 | Row resolution, record shape, preset v3 | `resolve/rows` (new), `resolve/preference` (reuse per cluster), `resolve/evidence` (`list.` buckets), `resolve/types` + `records` (`items`, `dropped`), API DTO + api-client, `_gaps` and learning skip, preset `commerce_detail` v3, SPEC-05/06/07/08 text | property, unit, replay; C10 section (dev: rows published per page; top-level fields unchanged) | INV-33–INV-35 tests pass; v3 publishes `variants` on every §4.3 shape. |
| 3 | Selected variant and variant fill | `resolve/intent` (`select_variant`), `resolve/preference` (anchor, `other_variant`), `resolve/ownership` (fill), SPEC-05 §4.6/§4.8 text | unit, property, replay; C10 section (dev: price/availability coverage and conflicts before/after; hidden non-regression on required types) | INV-36 test passes; on pages without a naming URL the only top-level changes are `sku`/`gtin` fills where every variant agrees. |
| 4 | Row labels and scoring | `eval/labels` (`label_version` 2), `eval/metrics` (row matching, `list.<type>` cells, row precision/recall, WP from `distractor_keys`), aggregate suppression of the new cells, pre-fill skip, SPEC-03 §4.3/§4.6 text | unit on synthetic labels | Metrics computed; suppression holds (INV-25). |

PR 2 depends on PR 1. PR 3 depends only on step A (#168) and can run beside PR 2. PR 4 depends on PR 2.

## 9. Open issues

- **`isVariantOf` without `hasVariant`.** Variants published as top-level `Product`s that point to their group
  only through `isVariantOf` are not in the baseline. They stay primary candidates, so intent decides by URL and
  is often `intent_ambiguous`. Treating `isVariantOf` as the inverse of `hasVariant` (schema.org declares them
  inverses) is the likely fix. It is deferred until a dev page shows the shape.
- **Attributes outside the four.** A variant that differs by a property `variesBy` names other than size, color,
  material or pattern reaches the record only through `name`. An open attribute map is not a §5.1 type, and adding
  one would be a new type (C8) for a schema that needs it.
- **Top-level `sku`/`gtin` from Offers.** In the one-Offer-per-variant shape, the top-level `sku` path stays
  `Product.sku`, so an `sku` every Offer shares is not read. Adding `|Offer.sku` to the top-level paths is
  a preset change to measure on dev first.
- **Field-level evidence for mixed sources.** §4.5 defines field-level `evidence` for the two buckets structured
  sources give. A later source of rows (config, role C) needs a rule.
- **Row order and `changed_fields`.** Reordered variants count as a change (§4.4). Comparing by type equality
  (multiset) would hide real reorders. This is kept literal until recurring crawls show the noise is material.
- **UI.** The records screen shows `variants` as JSON; a row table, and the labeling screen's row editor needed
  at milestone M, are SPEC-12/SPEC-03 follow-ups.
- **Role S drafts.** Role S's wire form carries no `key`, so a draft row-mapped field fails validation and the draft
  is repaired or rejected like any invalid draft. Teaching role S row paths waits for a user who needs it.
- **Several sellers per variant.** Two Offers in one row with different prices are a `conflict` inside the row
  (INV-35). Per-seller rows are not modelled.
