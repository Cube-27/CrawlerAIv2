# SPEC-05 decisions

Decisions for [SPEC-05 — Structured extraction, ownership, resolution and confidence](../specs/SPEC-05-extraction-and-resolution.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0334 — Page text is rendered from the tree; `ParsedPage` caches it
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: `content.text.render(root)` returns the cleaned text and the shown attribute values in one walk of the selectolax tree. `ParsedPage.cleaned_text` and `ParsedPage.visible_values` cache the result; SPEC-05 §4.1 writes these as `cleaned_text(page)` and `visible_values(page)`.
- Alternatives: functions that take the page, which need a circular import and let a caller skip the cache.
- Why: one walk, one cache, one import direction.
- Reversible: yes

### D-0335 — Inline text joins as rendered
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: text nodes are concatenated, and whitespace collapses as CSS Text 3 §4.1 collapses it, with Unicode White_Space as the collapsible set (as SPEC-04 collapses). Table cells are separated by a space; line boxes and `br` by `\n`. SPEC-05 §4.4's "inline text joined by space" is read this way.
- Alternatives: a space between every inline node, which turns `$<span>19</span>` into `$ 19`, text that is not on the page.
- Why: grounding (INV-12) needs verbatim page text.
- Reversible: yes

### D-0336 — Visibility index entries are lines, not runs
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: the index holds every cleaned-text line, plus the `alt`, `title`, `value` and `content` attributes of visible elements, in the SPEC-04 text form. `visible(value)` is a substring match that doesn't split a word, with letters and digits as an approximation of UAX #29 word boundaries.
- Alternatives: exact membership of a run, which misses values split across inline elements.
- Why: lines contain every run. Matching whole words keeps `9.99` from matching inside `19.99`.
- Reversible: yes

### D-0337 — The hidden set comes from the HTML Standard
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: content counts as hidden when it is one of:
  - the HTML Standard rendering section's "Hidden elements", which include `head`, `title`, `meta`, `input[type=hidden]` and a closed `dialog`;
  - `noscript` and `svg`, from SPEC-05 §4.4;
  - `iframe`, whose content is raw text.

  `visibility` is inherited, and a descendant with `visible` is shown again (CSS 2 §11.2). As a result, `meta[content]` is never in the index.
- Alternatives: only the elements §4.4 lists.
- Why: a standard decides what is hidden, not a list grown page by page (C2, C4).
- Reversible: yes

### D-0338 — One decode for both parsers
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: `storage.capture_bundle.decode_body` decodes the body once, in the Content-Type charset, else UTF-8 (as D-0213); the labeling view uses it too. lxml gets the decoded text re-encoded as UTF-8 with that encoding named, so an XML encoding declaration doesn't break it. An empty document gives an empty `html` element.
- Alternatives: give each parser the raw bytes.
- Why: lexbor decodes bytes wrongly (non-ASCII came out as U+FFFD), and both parsers must read the same characters.
- Reversible: yes

### D-0339 — Node paths: absolute indexed XPath in the selectolax tree
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: `TextRun.node_path` and `ScriptBlock.xpath` are XPath 1.0 location paths into the selectolax (HTML-standard) tree, with every step indexed (`/html[1]/body[1]/div[3]`). A tag that is not an NCName (`o:p`) gets `*[name()='o:p'][n]`. One formatter, `content.text.xpath_step`, builds every step. A path may not resolve in `lxml_tree`, because libxml2 builds HTML trees differently (no implied `tbody`, different handling of misnested tags).
- Alternatives: paths computed in the lxml tree, which would need lxml for every page.
- Why: a path must name the tree its text came from.
- Reversible: yes

### D-0352 — Locator grammar
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: decided
- Decision: Locator address parts split on `:` and the last part takes the rest (XPath, JSONPath, CSS and `og:` names hold `:`); `js_state` splits after the first `script[n]` step, which `ParsedPage` ends a script path with. Indices are ASCII digits without a leading zero, a `text:` span is non-empty (`start < end`), JSONPath starts with `$` (RFC 9535) and XPath with `/`.
- Alternatives: Escaping `:` inside parts.
- Why: Every SPEC-05 §4.3 form stays readable as written, and each locator has one spelling.
- Reversible: yes, until collectors persist locators

### D-0353 — `collect` sits above `content` in the layering
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: decided
- Decision: `collect` and `content` were independent siblings in `.importlinter`; `collect` now sits one layer above `content`.
- Alternatives: A page protocol inside `collect`.
- Why: SPEC-05 §4.1 and INV-26: every collector takes the `ParsedPage`.
- Reversible: yes

### D-0354 — Extraction model shapes
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: decided
- Decision: `Candidate.raw` is SPEC-04's `Raw` (any JSON value: JSON-LD prices are numbers), not `str | dict | list`; sequences are tuples; `FieldSet = dict[str, FieldOutcome]`; `LLMCallRecord` has SPEC-06 §4.2's fields; `Evidence` moves to `resolve.types`. An unpublished field holds no value and states a reason; `blocked`/`shell`/`not_found` results have no candidates and no fields (INV-11); an `error` result has no fields but keeps its candidates (§4.14).
- Alternatives: The spec's literal annotations.
- Why: The most conservative reading that the later rows can rely on.
- Reversible: yes

### D-0383 — OpenGraph field roles
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: A field's OGP role is the single property its `schema_org` path names on the root type (`Product.name` → `name`, `Offer.price+priceCurrency` → `price`); a path through another object (`Product.brand.name`) has none. So `og:title` maps to `Product.name` but not to `Product.brand.name`, though both end in `.name` (SPEC-05 §4.5). The same rule, with the field type, keys `og:image`, `og:url`, `product:availability` and `product:price:*`; a list field matches by its item type.
- Alternatives: The literal "ends in `.name`", which would propose the page title as the brand.
- Why: `og:title` is the title of the object the page describes, not of a related object; the most conservative reading. Review note: the root type is not checked, so `Organization.name` also gets `og:title`; revisit with ownership and intent (SPEC-05 PR 6).
- Reversible: yes

### D-0384 — Repeated OpenGraph properties
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: A repeated property gives a scalar field its first value and a list field every value in document order (`og:image` and `og:image:url` read as one property); the locator names the first value's property.
- Alternatives: One candidate per occurrence.
- Why: Open Graph protocol, "Arrays": the first tag is preferred in a conflict. Several candidates from one source would disagree with themselves at preference.
- Reversible: yes

### D-0385 — OpenGraph values are not translated
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: `product:price:*` becomes the money normalizer's structured form `{amount, currency}` from the first of each; a missing currency is left out, so the candidate declines (`no_currency`). `product:availability` passes through unchanged, so values outside the schema.org member names (`in stock`) are declined by the `schema:ItemAvailability` enum normalizer.
- Alternatives: An OGP-value → schema.org-member table in the collector.
- Why: Value translation belongs to the enum module (C7, C8); whether a vocabulary for OGP availability values is worth adding is measured on dev.
- Reversible: yes

### D-0386 — The Open Graph protocol is cited by name
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: Code cites the Open Graph protocol by name, not by its host, so `tools/site_literal_allowlist.txt` is unchanged.
- Alternatives: Allowlist the OGP host as a standards body.
- Why: The smallest change; no allowlist edit for one module.
- Reversible: yes

### D-0387 — Collector diagnostics
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: `CollectResult` gains `diagnostics: tuple[str, ...] = ()`. A JSON-LD block that is not JSON (including `NaN` and nesting the parser refuses) and a value the `Candidate` model refuses (nested deeper than its validator recurses) are skipped and named there.
- Alternatives: Log only.
- Why: SPEC-05 §4.5: a collector never raises and returns a diagnostic; the PR 2 model had no place for one.
- Reversible: yes

### D-0388 — schema.org scope in JSON-LD
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: A bare term (`Product`, `name`) is read as schema.org only under a schema.org context: the namespace as a string, `@vocab`, or an array of contexts, http or https, with or without the trailing slash. Full `http(s)://schema.org/` IRIs are read anywhere. A block with no context has no entities, and a remote context other than schema.org's is not fetched.
- Alternatives: Assume schema.org when there is no context.
- Why: JSON-LD 1.1 §4.1; the most conservative reading (C7).
- Reversible: yes

### D-0389 — JSON-LD entities and parents
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: Every object typed with a vocabulary type is an entity, at any depth. Its parent is the nearest enclosing entity; a node defined on its own takes the one entity that references it by `@id`, unless that would make a cycle; a node referenced from two or more entities has no parent. For references, the first definition of an `@id` wins. `Entity.kind` is the most specific listed type: the first one that no other listed type is a subtype of.
- Alternatives: Merge duplicate `@id` definitions (JSON-LD flattening).
- Why: The simplest rule that keeps entities a tree (SPEC-05 §4.6).
- Reversible: yes

### D-0390 — Entity URLs from JSON-LD
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: An entity's `urls` are its `url`, its own `@id`, its `mainEntityOfPage` (a string, or that node's `url`/`@id`) and its offers' `url`, canonicalized by the url normalizer. An `@id` with a fragment is left out.
- Alternatives: Include fragment `@id`s.
- Why: RFC 3986 §3.5: a fragment names part of a document, not a page; fragment `@id`s would all canonicalize to the page URL and make intent ambiguous.
- Reversible: yes

### D-0391 — Text standing in for a Thing
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: On a path ending in `.name` (`Product.brand.name`), a text value where the path expects a node (`"brand": "Acme"`) is taken as that thing's name.
- Alternatives: No candidate.
- Why: schema.org data model, "Conformance": text is accepted where a Thing is expected.
- Reversible: yes

### D-0392 — Structured-data candidate shapes and locators
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: Each value of an array property is its own candidate. A `list` field gets one candidate per node, holding all values and located at the first. A `+` path gives one object per value of the first property (`{"price": …, "priceCurrency": …}`), located at the first property; several second values stay an array, so the normalizer declines. JSON-LD locators are RFC 9535 normalized paths into the block as written (SPEC-05 §4.3 says "expanded graph"); a referenced node's values are located where it is defined. `null`, value objects holding a non-scalar, and arrays nested inside an array of values are not values.
- Alternatives: Locators into an expanded form; one candidate per list item.
- Why: Locators that read back the raw value from the capture (tested as a property).
- Reversible: yes

### D-0393 — schema.org vocabulary loading
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: `collect.schema_org_map.default_vocabulary()` reads `backend/data/schemaorg/schemaorg-all-https.jsonld` once and raises `VocabularyMissing` ("run `crawlerai data fetch`") when it is absent, as the gazetteer does. Tests use a synthetic vocabulary file in the same format.
- Alternatives: Derive and commit a type-hierarchy file.
- Why: One source for the vocabulary (the manifest pin, D-0018); CI never fetches.
- Reversible: yes

### D-0404 — Microdata and RDFa Lite items
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 4 (#83) · Status: decided
- Decision: An item is an element with `itemscope` or `typeof`; an element with both is one item, with the types of both syntaxes. Both syntaxes' property elements belong to their nearest enclosing item; `itemref` adds microdata properties per the HTML Standard's crawl (each element once; the item's own element excluded). A nested item (a property element that is an item) is its holder's child; an item that is no property is top-level, so DOM nesting alone gives no parent. A parent is the nearest entity up a chain of single holders (untyped items skipped), unless that would make a cycle; an item that two items hold has no parent.
- Alternatives: Parent by DOM nesting; read the two syntaxes as separate item sets.
- Why: The HTML Standard's top-level and nested items; one entity per element keeps the `microdata:<xpath>` ids unique. A property never crosses into another item's scope, so a related item's values are never attributed to the outer item.
- Reversible: yes

### D-0405 — Vocabulary scope of microdata and RDFa names
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 4 (#83) · Status: decided
- Decision: A short `itemprop` name is a schema.org term only in an item with a schema.org `itemtype` (http or https). An untyped item is in no vocabulary, even when nested in a schema.org item. RDFa terms resolve under a schema.org `vocab` in scope (an empty `vocab` clears it), and the `schema:` prefix of the RDFa 1.1 initial context is read. Full schema.org IRIs are read anywhere. `prefix` declarations are not read.
- Alternatives: An untyped nested item inherits its holder's vocabulary.
- Why: The HTML Standard ties names to the item's type; the most conservative reading (C7). RDFa Core 1.1 §7.4.3 and the initial context.
- Reversible: yes

### D-0406 — Microdata values and item JSON
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 4 (#83) · Status: decided
- Decision: Values follow the HTML Standard's "Values" (`meta` content; `src`/`href`/`data` URL attributes as written, the empty string when absent; `data`/`meter` value; `time` datetime; else text content). RDFa values: `content`, then `time` datetime, then `resource`/`href`/`src`, then text content. URLs are kept as written; the url normalizer resolves them against the base URL. An item value's raw is its JSON-LD-shaped object (`@type`, `@id`, then each property, one value bare and several as an array), what the normalizers read. Each item appears once in that object, so `itemref` cycles and shared items keep it as large as the page. The locator of an item value is its element. A blank `itemid` or `resource` names nothing.
- Alternatives: The HTML Standard's microdata-to-JSON form (`{"type", "properties"}`), which the normalizers do not read; resolved URLs as raw.
- Why: The same raw shapes as JSON-LD, so one normalizer reads both; raw values match the capture.
- Reversible: yes

### D-0412 — Entity `via`: the parent's schema.org property holding it
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: `Entity.via` is the schema.org property of the parent entity that holds the entity: a full schema.org IRI anywhere, or a bare term under a schema.org context. Through untyped objects it is the property on the entity, not on the object in between. A node referenced by `@id` takes the property of its one reference, and gets none if its one referrer references it under two properties. Microdata: the one name the holder's element gives the item (or the untyped item on the way); an element naming two properties names none.
- Alternatives: Exclude every primary entity nested in another primary entity; parse the property out of the locator.
- Why: §4.6 names relation properties, and an `@id` reference or a microdata item doesn't show its property in its id.
- Reversible: yes

### D-0413 — Primary types are the required fields' roots without Offer
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: The root types of the required fields' `schema_org` paths, without Offer (and its subtypes) unless Offer is the only root. `required_groups` members don't count.
- Alternatives: Include Offer, which would make every Offer of the product a competing candidate.
- Why: An Offer belongs to the item it offers (schema.org `offers`/`itemOffered`; §4.5, §4.7).
- Reversible: yes

### D-0414 — Intent excludes entities in lists and under relation properties
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: An entity is excluded when any ancestor is an `ItemList` or `ListItem` (or a subtype), or when somewhere up its chain it sits under `isRelatedTo`/`isSimilarTo` of a primary entity. A primary entity nested through another property stays a candidate, and the URL decides.
- Alternatives: Exclude every nested primary entity.
- Why: The literal reading of §4.6 step 1.
- Reversible: yes

### D-0415 — All primary entities excluded is `intent_ambiguous`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: When primary-type entities exist but all of them are excluded, the result is `AmbiguousTarget(candidates=())`, not the `page` entity. `page` is the target only when the page has no primary-type entity at all.
- Alternatives: Fall back to `page`.
- Why: §4.6 step 4 says "primary type absent", and a list of products is not a page about one of them. This is the conservative reading.
- Reversible: yes

### D-0416 — Only an Offer child of the target is the target's
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: `owned_by` accepts an Offer (or subtype, so also AggregateOffer) whose parent is the target. An Offer nested inside an AggregateOffer is not owned.
- Alternatives: Any Offer descendant.
- Why: §4.5 and §4.7 say "an Offer child of the target". Atomic offers and `lowPrice` belong to PR 7.
- Reversible: yes

### D-0417 — Page-level candidates belong to the target whatever the field's root
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: Page-level candidates (OG, meta, text) belong to the target whatever the root type of the field's path, so an `Organization.name` field still gets `og:title`.
- Alternatives: Own page-level candidates only for fields rooted at the target's type.
- Why: §4.6 step 4 attributes page values to the target without a type condition; this answers D-0383's review note. Measure on dev before changing it.
- Reversible: yes

### D-0418 — js_state and xhr admit against the other kinds' candidates
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: `js_state` and `xhr` implement `AdmittingCollector.collect(page, schema, ctx, others) -> Admitted`, not `Collector`. `Admitted` holds candidates and diagnostics but no entities: its candidates name entities of `others`, or `page`. PR 9 runs these two after the other collectors, passes their candidates, and adds the admitted candidates to the merged graph.
- Alternatives: Return a `CollectResult` that copies the referenced entities (duplicate ids on merge).
- Why: Admission depends on the other kinds' candidates (§8.1), and a `CollectResult` must hold every entity its candidates name.
- Reversible: yes

### D-0419 — An admitted value is owned by the entity it equals, else by the page
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: A value admitted by equality is owned by the entity of each candidate it equals, one candidate per entity. A value admitted by visibility is owned by `page`.
- Alternatives: Own every admitted value by `page`.
- Why: A state value equal to a related product's price is evidence about that product. Owning it by `page` would put it on the target and cause spurious conflicts.
- Reversible: yes

### D-0420 — A field with any other-kind candidate admits by equality only
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: A field that has any candidate from another source kind, even one that did not normalize, admits state values by equality only. So a value both equal and visible is not independent. A candidate of the same kind is never an anchor.
- Alternatives: Count only valid candidates; let visibility make an equal value independent.
- Why: The conservative reading of §4.5 ("leaves are considered only for fields still lacking a candidate or for agreement checks"): fewer admissions, and no independent vote for a value that only agrees.
- Reversible: yes

### D-0421 — State is a script's first assignment, and only an object or array
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: js_state reads a `<script type="application/json">` whole. In any other non-JSON-LD script it reads only the first `window.<ident> =` or `var|let|const <ident> =` assignment, and only when its JSON value is an object or array. Booleans and `null` are never candidates.
- Alternatives: Every assignment in a script; scalar initializers.
- Why: The locator addresses one document per script. A scalar initializer is a script variable, not state. `true`, `false` and `null` are values of no field type.
- Reversible: yes

### D-0422 — `ParsedPage` carries the captured network bodies
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: `ParsedPage(html, network=())`; `ParsedPage.of` passes `bundle.network`.
- Alternatives: Pass the bundle to the xhr collector.
- Why: Collectors read the `ParsedPage`, never the bundle (§4.1, INV-26).
- Reversible: yes

### D-0437 — Preference returns `Chosen` or `Unpublished`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: Preference returns `Chosen(chosen, agreeing, rejected)` or `Unpublished(missing|conflict, reason, rejected)`. Evidence, confidence and `FieldOutcome` come in PR 8. For an exact-match type the chosen candidate is the first kept one, in the order the collectors give.
- Alternatives: Return `FieldOutcome` now, with placeholder evidence.
- Why: INV-22 forbids a published outcome without evidence. `agreeing` is what PR 8 needs for the `agreed` bucket.
- Reversible: yes

### D-0438 — A missing field states the furthest screening stage
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: A `missing` field's reason is the furthest screening stage a candidate reached (`invalid` < `ambiguous` < `not_owned` < `url_param`), or `no_candidates` when the field has none. Every rejected candidate keeps its own reason.
- Alternatives: A generic `no_valid_candidates`.
- Why: It names the stage that blocked the field.
- Reversible: yes

### D-0439 — Unranked kinds never win; a split winning kind is a conflict
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: In precedence types, a source kind absent from the type's order never wins: if only such candidates exist, the field is `missing` with reason `unranked`. Equal values still count as agreeing. Two candidates of the winning kind that disagree make the field `conflict`/`disagree`. A `list` field follows its item type's rule; an `object` field publishes on agreement.
- Alternatives: Unranked kinds rank last; the first candidate of the winning kind wins.
- Why: The order is fitted on dev (INV-02), and an unranked kind has no dev measurement. When two values tie, nothing settles which is right (C7).
- Reversible: yes

### D-0440 — Atomic offers anchor on one Offer
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: The anchor Offer is the one holding kept candidates for the most Offer-rooted fields; on a tie, the first one seen. Candidates from two different Offers that disagree make the field `offers_disagree`. An Offer field with no kept candidate from the anchor is `offer_split`, which includes an Open Graph price beside a JSON-LD Offer that states only availability. Page-level values that agree with the anchor's value count as agreeing.
- Alternatives: Per-field agreement only, which can take price and availability from different Offers.
- Why: INV-15 says one source object; this is the conservative reading.
- Reversible: yes

### D-0441 — The URL-parameter rule compares every scalar of the raw value
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: INV-13 compares every string and number inside the raw value (including inside objects and arrays, such as `priceCurrency`), in the SPEC-04 text form, against the request URL's query values decoded as application/x-www-form-urlencoded (WHATWG). Empty values are ignored. A match is kept only when `visible` finds it on the page.
- Alternatives: Compare only top-level strings.
- Why: A currency or code copied from the URL is a value taken from a URL code (C7).
- Reversible: yes

### D-0442 — Derivations fill only missing fields, in a fixed order
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: Derivations fill only `missing` fields, never `conflict`. The order is `absolutize` (the field's own relative candidate, put through preference again), then `canonical_link`, then `final_url`. The page-URL field is the url field of a detail schema whose path is `T.url`, for a primary type T. Derived page URLs pass through the url normalizer.
- Alternatives: Fill conflicts too, or put the canonical link first.
- Why: A conflict is a field whose values disagree; filling it would hide that. A candidate's own value is closer to the field than a page-level URL.
- Reversible: yes

### D-0443 — `source_precedence.yaml` has one reader
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: `load_precedence` requires `source_split: dev`, an order for each of text, long_text, url and image_url, known source kinds, and no other types. `parse_orders` is shared with `eval/calibrate`, and a test checks that its stamp keys match the `Precedence` model.
- Alternatives: Let `long_text` fall back to `text`'s order.
- Why: INV-02, and no defaults (C7).
- Reversible: yes

### D-0444 — Dev-fitted files under `backend/data/` and INV-05
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: answered 2026-10-14
- Decision: Question: INV-05 says every file under `backend/data/` comes from a pinned external source listed in `manifest.json`. SPEC-05 puts the dev-fitted `source_precedence.yaml` (§4.7) and `calibration.json` (PR 8) there, and the fit commands rewrite them, which would break a pinned sha256. Options: (a) `data_manifest_check` exempts the two fitted, stamped artifacts and checks their `source_split: dev` stamp instead, with INV-05 reworded to "external data"; (b) a manifest entry per fitted file, whose url names the eval run and whose sha256 the fit commands rewrite; (c) move fitted files out of `backend/data/`. Recommendation: (a). Blocked: committing the initial order (D-0020), which PR 9 needs to run `extract_page`, and PR 8's empty `calibration.json`. Copied to OPEN_QUESTIONS #19.
- Alternatives: See options.
- Why: The specs contradict each other (CLAUDE.md §4).
- Reversible: yes
- Owner answer: option (a) (owner 2026-10-14; OPEN_QUESTIONS #19). Implemented in #156 (D-0756–D-0758).

### D-0445 — The adapter collector is built per capture with the adapter and the detected page kind
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 11 (#91) · Status: decided
- Decision: `AdapterCollector(adapter, page_kind)` implements the `Collector` protocol. The pipeline (PR 9) builds it for `api` captures from `registry.detect(bundle.url)` and that adapter's `detect(bundle.url).page_kind`.
- Alternatives: Detect from `ctx.page_url`, which for an API capture is the endpoint, not the page.
- Why: Only the bundle's `url` holds the page URL.
- Reversible: yes

### D-0446 — The adapter entity is the node at the mapped query's last wildcard
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 11 (#91) · Status: decided
- Decision: Entity id `adapter:<name>:<normalized path>` (`$` for detail, `$['jobs'][0]` per listing row). Kind is the single schema.org root type of the mapped paths; a map spanning several types is skipped with a diagnostic. `urls` come from `adapter.map({"url": "<Type>.url"})`.
- Alternatives: Add `root(page_kind)` to the `Adapter` protocol.
- Why: Structural (RFC 9535); the adapters need no change.
- Reversible: yes

### D-0447 — `json_doc.select` takes name, wildcard and index segments
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 11 (#91) · Status: decided
- Decision: RFC 9535 queries limited to name, wildcard and non-negative index segments, so every normalized path (and so every locator path) is a query; other queries raise `ValueError`.
- Alternatives: A JSONPath library.
- Why: Adapter maps use only this subset (D-0266); no dependency needed.
- Reversible: yes

### D-0454 — An uncalibrated published field may have no confidence
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: A published field's `confidence` is its bucket's dev precision, and is `None` only when the field is `calibrated=false` (the bucket has no dev measurement). INV-22's "carries `confidence`" is read as the attribute being present, as §13.1 says of every field.
- Alternatives: Keep `confidence` mandatory (PR 2), so nothing publishes until dev is labeled.
- Why: §10 publishes uncalibrated buckets with the flag set, and §21 L1 is done when every published field carries evidence and `calibrated=false`; with no labels there is no precision.
- Reversible: yes

### D-0455 — Evidence bucket priority; a lone state value has no bucket
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: `adapter` (adapter or api chosen) > `agreed` (at least 2 distinct source kinds among the independent candidates of chosen + agreeing) > the chosen kind's bucket: `structured` for jsonld/microdata/og, `config_corroborated`/`config_uncorroborated` from a caller-given set of corroborated fields, `llm_grounded`. A lone js_state/xhr value fits no §10 bucket and abstains with reason `no_bucket`.
- Alternatives: Count js_state/xhr as `structured`.
- Why: §10 names no bucket for embedded state; publishing without a bucket breaks INV-22.
- Reversible: yes

### D-0456 — τ and record confidence cover required-group members
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: τ 0.97 applies to required fields and to every member of a required group; others use 0.95. Record confidence takes the same set. `calibrated` requires n ≥ 30 and a precision. A `below_tau` field keeps `evidence`, `confidence` and `calibrated` in `field_meta`, and its chosen candidate moves to `rejected` with `below_tau`.
- Alternatives: Group members as optional.
- Why: The stricter reading (C7); the meta says why the field abstained.
- Reversible: yes

### D-0457 — Derived values publish only with a source candidate
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: An `absolutize` value publishes with its source candidate's kind, locator and bucket, and `derived_by`. A page-URL derivation (`canonical_link`, `final_url`) has no candidate and stays `missing` with reason `no_provenance` until D-0355 is answered.
- Alternatives: Publish it without provenance.
- Why: INV-22 as the models enforce it.
- Reversible: yes

### D-0458 — `Calibration` lives in `resolve.evidence`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: `Calibration` and `Bucket` move to `resolve.evidence`, and `eval.calibrate` imports them, so the writer and the engine's reader share one model. `load_calibration` returns `None` for a missing file (every field uncalibrated).
- Alternatives: Two models.
- Why: C8; `resolve` sits below `eval` in the layering.
- Reversible: yes

### D-0459 — Entity key
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: `entity_key` is the hex sha256 of `str(site_id) + canonical_url`; the caller passes the target's canonicalized URL.
- Alternatives: A separator between the parts.
- Why: A UUID string has one length, so the concatenation is unambiguous.
- Reversible: yes, until records are stored

### D-0483 — The pipeline lives in `resolve.pipeline`; role C is a hook, not an LLM client
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `extract_page` takes `role_c: Callable[[GapRequest], Awaitable[GapReply]] | None` where SPEC-03's signature has `llm`; the caller binds the client. `eval.engine.PipelineEngine.replay_page(bundle, schema, config, llm, mode)` keeps SPEC-03's signature.
- Alternatives: Import `LLMClient` in `resolve` (breaks the `resolve | llm` independence contract); a new top-level package.
- Why: The import contracts stay as they are; SPEC-06 PR 4 binds role C from the client in a layer above both.
- Reversible: yes

### D-0484 — The collectors are assembled in `collect.run`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `collect_page` runs JSON-LD, microdata, OG, and the adapter collector for an `api` capture whose page URL an active adapter detects (D-0445), each isolated: one that raises gives a diagnostic and no candidates. js_state and xhr then admit against the rest (D-0418).
- Alternatives: Build the adapter collector in `resolve` (forbidden: only acquire and collect import adapters).
- Why: §4.14; import contracts.
- Reversible: yes

### D-0485 — The scrape task's handler step is `resolve.task.extract_task`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: This row supplies the step after the fetch: extract, store `extraction`/`candidate`/`record`, return the outcome; the caller settles the task. The fetch and worker registration stay with SPEC-07's scrape function and SPEC-10 PR 2.
- Alternatives: A second fetching handler beside `services.scrape`.
- Why: SPEC-07 §4.4 and SPEC-10 §4.2 make the scrape function the handler; a second fetch path would duplicate it.
- Reversible: yes

### D-0486 — No fitted precedence means every precedence type declines
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `EngineData.load` uses `UNRANKED` (empty orders) when `source_precedence.yaml` is absent: text, long_text, url and image_url fields are `missing`/`unranked`. Exact-match types still publish on agreement.
- Alternatives: Commit SPEC-05's default order (blocked by D-0444).
- Why: C7: decline rather than follow an unmeasured order; consistent with a missing calibration meaning uncalibrated.
- Reversible: yes

### D-0487 — Normalization context from page evidence only
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `content.context.page_context` sets `html_lang`, `og_locale`, `hreflang` (`link rel~=alternate`), `base_url`, `page_url` and `captured_at`. `page_currencies` and `cctld_territory` stay empty for now.
- Alternatives: Fill them from the page's structured data and CLDR territories.
- Why: An empty value makes money decline rather than guess (C7); filling them is a follow-up with its own tests.
- Reversible: yes

### D-0488 — Entity key uses the task's canonical URL
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `record.entity_key = sha256(site_id + url_task.canonical_url)` for detail pages.
- Alternatives: The target entity's own URL.
- Why: Stable across runs of one URL, and the key `url_state` (SPEC-11) uses.
- Reversible: yes

### D-0489 — Role C is asked only for real gaps
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: In schema order: required fields that are `missing`, and `missing` members of required groups no member fills. Conflicts and abstentions are never sent. Role C runs once per page; its exceptions propagate.
- Alternatives: Every member of every required group.
- Why: §4.13; fewer LLM calls; a replay's missing recording reaches the harness.
- Reversible: yes

### D-0490 — Config mode and listings are refused for now
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `extract_page` raises `ModeNotSupported` for a config or a listing schema until SPEC-08 PR 2 and SPEC-05 PR 12.
- Alternatives: Resolve page-scoped listing fields only, or ignore the config.
- Why: A partial answer would be scored as a real one.
- Reversible: yes

### D-0491 — Unreadable recordings drop the page (follow-up from #33)
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: A recording that doesn't parse as an `LLMResponse`, or whose cache row points at a missing object, raises `RecordingUnreadable`; `replay_split` drops the page as `ReplayFailed("recording unreadable: …")`.
- Alternatives: Stop the run.
- Why: A per-page data problem, like a missing recording (D-0219); the `n_pages` gate catches it.
- Reversible: yes

### D-0492 — Runtime data shipping deferred (follow-up from SPEC-04 PR 7)
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: Shipping `VERSION`, `calibration.json` and GeoNames data goes to its own PR before the first deployment. `EngineData.load(data_dir)` takes the directory explicitly, so that PR only chooses where it comes from (package data or a settings path) and makes the build write `VERSION`.
- Alternatives: Settle it here.
- Why: It changes `infra/Dockerfile` and packaging, outside this row; D-0444 already blocks committing the fitted files.
- Reversible: yes

### D-0509 — Listing rows
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: Rows are the primary-type entities with an `ItemList`/`ListItem` ancestor and no primary-type entity between them and the list. With no such entity, the rows are the top-level primary entities, when there are at least 3 and intent gives `AmbiguousTarget`.
- Alternatives: Count every primary entity under a list, related items included.
- Why: A related or offered item belongs to its holder (§4.6 step 1). Fewer than 3, or one named by the page URL, is what a detail page looks like (§4.7).
- Reversible: yes

### D-0510 — Rows take no page-level value
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `EntityGraph.owned_by(..., page_values=False)` for rows: og/meta values are no row's. Page-scoped fields resolve against the page entity. `primary_types` reads only required row fields.
- Alternatives: Detail ownership for every row.
- Why: A page value describes the listing, not one of its rows (§4.6, §5.2).
- Reversible: yes

### D-0511 — A listing record holds the page fields
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: Each row's record is `{**page_fields, **row_fields}`, so `field_meta` covers every schema field (INV-22). Completeness and record confidence are computed over that merged set; the page's `record_confidence` is its least confident row's, `None` when any row's is.
- Alternatives: A separate page record; rows without the page fields.
- Why: INV-22; §4.10 gives one record per row.
- Reversible: yes

### D-0512 — Row entity key
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `sha256(site_id + url)`, where `url` is the row's published value of its first row-scoped url field with path `T.url`; without one, `<task canonical URL>#<row position>`. A URL listed twice gives one record, the first.
- Alternatives: The entity's `@id`; no record for a row without a URL.
- Why: §4.10 "keyed by row url"; position is stable for unchanged markup; SPEC-11 versions records by `(site_id, entity_key)`.
- Reversible: yes

### D-0513 — Listing outcome
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `extracted` when there is at least one row and every row is complete; `no_match` when no record is kept (no rows, or a crawl where every row is incomplete); otherwise `partial`, including a crawl that drops some incomplete rows.
- Alternatives: `partial` with no record for a listing with no rows.
- Why: §4.10 applied per row; `no_match` means "no record".
- Reversible: yes

### D-0514 — `next_page_url` is not filled from pagination in cold mode
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `next_page_candidates` goes into `ExtractionResult.next_pages`. The schema's `next_page_url` field stays `missing` unless a source states it: a config's `next` step (D-0480).
- Alternatives: A `rel_next` derivation.
- Why: A derived value without a candidate has no source kind or bucket (INV-22, D-0355); §4.8 lists the only derivations in core (C13).
- Reversible: yes

### D-0515 — The structural pagination rule needs the integer in the page URL
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: With no integer segment or parameter in the page URL, no structural candidate is taken; `rel=next` still applies. A repeated query parameter name is skipped.
- Alternatives: Read a missing parameter as page 1.
- Why: §4.12 "differ from the current URL only in one integer…"; guessing the first page's number skips a page on 0-based sequences (C7). The crawl frontier still gets every link.
- Reversible: yes

### D-0516 — Role C is not called for listings
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: The detail gap hook (§4.13) runs for detail pages only; role C for listings is SPEC-06 PR 5.
- Alternatives: Send each row's gaps as a detail request.
- Why: Role C's listing call returns rows, a different shape (ARCHITECTURE §8.6).
- Reversible: yes

### D-0517 — `Stored.records`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `store_extraction` returns every record it inserted as `StoredRecord(id, draft)` pairs (0 or 1 for a detail page, one per kept row for a listing), inserted in one statement; `services.scrape` reads the first, since the request refuses listing records.
- Alternatives: Keep `record_id`/`record` and add listing fields beside them.
- Why: One shape for both page kinds.
- Reversible: yes

### D-0531 — Per-kind precision for `fit-precedence` is scored on every kind's kept values, in a dev-only `by_source` table
- Date: 2026-10-14 · Spec/PR: SPEC-05 PR 13 (#109) · Status: decided
- Decision: The dev report gains `by_source` (`rule_type|source_kind` → precision, coverage, n). For each judged field and each source kind with kept candidates, the cell is TP when every value of that kind equals the label, FP otherwise (including an absent label); coverage is TP over the type's fields whose label holds a value. A list is keyed by its item type. Only dev reports carry it. Supersedes the interim fits of D-0229.
- Alternatives: Score only the published value's kind.
- Why: §4.11 asks for per-kind precision on dev; the order decides between competing kinds, so each is measured where it competes, not only where it won.
- Reversible: yes

### D-0532 — A precedence fit reorders only the kinds already in the order
- Date: 2026-10-14 · Spec/PR: SPEC-05 PR 13 (#109) · Status: decided
- Decision: `fit-precedence` never adds or removes a source kind; kinds measured on ≥ 30 fields are sorted by precision, then coverage, in the slots they hold, and every other kind keeps its place.
- Alternatives: Add any kind measured with n ≥ 30.
- Why: Membership is the committed initial order (D-0020); §4.11 orders kinds, it does not add them.
- Reversible: yes

### D-0533 — Preference records its kept candidates
- Date: 2026-10-14 · Spec/PR: SPEC-05 PR 13 (#109) · Status: decided
- Decision: `Chosen`, `Unpublished` and `FieldOutcome` carry `kept`: the candidates that passed validity, ownership and the URL-parameter rule, whether the field publishes, is declined or abstains. A derived value and an ambiguous intent keep none.
- Alternatives: Rebuild the set from reject reasons (a deny-list that counts any new reason as kept), or from `ExtractionResult.candidates` (ambiguous across listing rows).
- Why: The resolver is the one place that knows which candidates were screened out.
- Reversible: yes

### D-0780 — Which field types admit a visible js_state/xhr value on its own
- Date: 2026-10-15 · Spec/PR: SPEC-05 §4.5, ARCHITECTURE §8.1, Appendix A #34 (#166) · Status: decided
- Decision: `normalize.dispatch.checkable`: money, enum, date, datetime, location and range always; an identifier under `gtin` or `isbn` (check digit); a url or image_url only when the raw value is an absolute http(s) URL; a list as its item; text, long_text and object never.
- Alternatives: Count relative URLs too (any token resolves against the page); count every identifier scheme.
- Why: Owner answer to accuracy Q2, option (a): visibility is evidence only where the normalizer rejects arbitrary text.

### D-0785 — What a product group owns of its variants
- Date: 2026-10-15 · Spec/PR: SPEC-05 §4.6, §4.8; ARCHITECTURE §8.2 rule 3, Appendix A #36 (#168) · Status: decided
- Decision: Under a primary entity, `hasVariant` children are excluded from target candidates; an Offer whose parent is such a variant is owned by the target and joins the atomic-offer rule. The variant's own values (sku, name, gtin, image) are not owned. Only `hasVariant` makes a member; an Offer of a product nested under any other property stays its own.
- Alternatives: Own the variants' values too (a variant sku would be published as the group's, the error the Shopify baseline saw as F7); treat `isVariantOf` from a top-level variant the same way (not in the baseline shapes; left for SPEC-13).
- Why: Owner approval of the variants proposal step A; schema.org `hasVariant` "indicates a Product that is a member of this ProductGroup".
- Reversible: yes

### D-0851 — js_state reads every JSON assignment of a script
- Date: 2026-10-15 · Spec/PR: SPEC-05 §4.5 (#196) · Status: decided; supersedes D-0421's "first assignment"
- Decision: Every `window.<ident> =` / `var|let|const <ident> =` whose value is an object or array is a state document, in script order; each search starts after the value just parsed. A script's documents share its address (`js_state:<script_xpath>:<path>`). The release executor reads state the same way (INV-20).
- Alternatives: The first assignment whose value is an object or array; an assignment index in the locator (changes the §4.3 format).
- Why: State is often not the first assignment (`var n = 1; window.X = {...}`); induction does not read js_state locators.
- Reversible: yes

### D-0852 — A microdata `itemprop` belongs to its nearest `itemscope` element
- Date: 2026-10-15 · Spec/PR: SPEC-05 §4.5 (#196) · Status: decided
- Decision: `itemprop` names and `itemref` lookups use the nearest `itemscope` element (HTML Standard, "Associating names with items"); an RDFa `property` keeps the nearest item of either syntax.
- Alternatives: RDFa strictly by `typeof` too (RDFa Core): moves existing RDFa values in mixed markup, unmeasured.
- Why: Microdata knows no `typeof`; the conservative reading changes only what was dropped.
- Reversible: yes

### D-0853 — A listing row another collector already gave is left out
- Date: 2026-10-15 · Spec/PR: SPEC-05 §4.7 (#196) · Status: decided
- Decision: Rows stay in collector order; a row is dropped when an earlier row of a different collector shares a canonical URL with it, page URLs excluded. Rows of one collector are never dropped here.
- Alternatives: Merge both entities into one row (needs multi-entity ownership; a follow-up); dedupe records by row URL only (needs the url field to publish, D-0444).
- Why: schema.org `url` and `@id` name the item; one record per item without touching ownership.
- Reversible: yes

### D-0854 — An adapter list field mapped through its own wildcard is one candidate of the map's entity
- Date: 2026-10-15 · Spec/PR: SPEC-05 §4.5 (#196) · Status: decided
- Decision: The list field's entity is the longest entity query of the map's other fields and its `url` query that starts its query; the values its rest selects are one list candidate, located by that rest with its wildcards (RFC 9535 §2.5.1.2).
- Alternatives: Split at the second-to-last wildcard (wrong for a list field without an item wildcard); one candidate per item (the old behaviour).
- Why: The entity is the posting, not each item of its list.
- Reversible: yes

### D-0880 — The wheel carries the engine's data (closes D-0492)
- Date: 2026-10-16 · Spec/PR: follow-up (#200) · Status: decided
- Decision: A hatchling build hook (`backend/hatch_build.py`) writes `VERSION` (from `CRAWLERAI_GIT_SHA`, else `git rev-parse HEAD`) and packs it, the files `data/manifest.json` lists that are present, and the dev-fitted files under `crawlerai/_engine/`. `engine_dir()` reads the source tree's `backend/` first, else that copy; every loader goes through `engine_data_dir()`.
- Alternatives: A settings path to a data directory.
- Why: An installed wheel or the image is self-contained with no new setting, and the manifest stays the one list of what ships (C4). ARCHITECTURE is unchanged.
- Reversible: yes

### D-0881 — The image build continues past a refused fetch
- Date: 2026-10-16 · Spec/PR: follow-up (#200) · Status: decided
- Decision: The Dockerfile runs the pinned fetch before building the project, prints refused entries and leaves them out; the engine reports them missing at run time.
- Alternatives: Fail the build on any refusal.
- Why: The GeoNames pin goes stale daily until D-0311 is answered; failing would make the image unbuildable.
- Reversible: yes

### D-0903 — The sdist carries VERSION and the data files; a build with no commit fails (completes D-0880)
- Date: 2026-10-16 · Spec/PR: follow-up (#202) · Status: decided
- Decision: The build hook also runs for the sdist, which carries `VERSION` and the manifest's data files at their own paths; a wheel built from an unpacked sdist (`PKG-INFO` present) reads that `VERSION`; with no `CRAWLERAI_GIT_SHA`, sdist `VERSION` or git commit the build raises. The image builds in two stages: `core/data.py` (stdlib-only, pinned by a test) fetches the data before `src/` is copied, and the image keeps only the installed environment.
- Alternatives: Keep `unknown` and document it.
- Why: D-0880 intends a wheel that names its build; `uv build` failed outright on the missing manifest.
- Reversible: yes

### D-0910 — The locator of a derived page URL is `derived:<derivation>`
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.3, §4.8 (#204) · Status: decided
- Decision: A page-URL derivation carries `derived:canonical_link` or `derived:final_url`; an absolutized value keeps its source candidate's locator. The two derivations are one `PageUrlDerivation` literal shared by the locator grammar and `Derivation`.
- Alternatives: An XPath to `<link rel=canonical>`; a `meta:` locator.
- Why: The final URL has no DOM node, and the derivation name reads back from the capture (the link relation or `capture.final_url`).
- Reversible: yes

### D-0911 — `derived` is a member of the §6 `SourceKind`
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.8, §4.9 (#204) · Status: decided
- Decision: `derived` joins the shared `SourceKind`; migration 0019 widens `ck_candidate_source_kind`, and `REFERENCE_KINDS` excludes it. No candidate row holds it.
- Alternatives: An outcome-only source-kind type, with no migration.
- Why: The owner's answer to D-0355 puts the source kind in §6 with a migration.
- Reversible: costly — a migration.

### D-0940 — An og:title naming the site is not the entity's; nor is the og:image beside it
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.5, round-1 eval class 1 (#207) · Status: decided
- Decision: `og:title` names the site when, folded (NFKC, casefold, letters and digits), it equals `og:site_name` or a separator run of it, or the first label of the host's registrable domain (PSL, `PublicSuffixes.registrable_domain`); then `og:title` and `og:image` are not read (a diagnostic says so), `og:url` is.
- Alternatives: The same og value across a host's pages (cross-page state); JSON-LD `WebSite.name`; an `og:url` test (on the failing pages og:url names the product).
- Why: Client-rendered pages publish the site's default og block as the product's (OGP basic metadata describes one object).
- Reversible: yes

### D-0941 — og:title is normalized without trailing segments that name the site
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.5, round-1 class 8 (#207) · Status: decided
- Decision: A separator is one P*/S* character between spaces. Trailing segments are dropped while one is a site name (D-0940) or its first whole words spell the host's label ("Example.com", not "Exampleton"); the first segment always stays, leading segments are kept, and `raw` stays verbatim.
- Alternatives: A prefix match on the label (review #207: strips real text); stripping leading segments too.
- Why: The presets ask for titles without the store name; the rule uses only the page's own site name and its host (C2, C4).
- Reversible: yes

### D-0942 — JSON-LD root nodes of one identity are one entity
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.5–§4.6, round-1 class 2 (#207) · Status: decided
- Decision: In the JSON-LD collector, root nodes of one most specific type that share a resolved `@id` (always; JSON-LD node map merge, RFC 3986 §5) or a value of a schema.org identifier property (`identifier` and its `rdfs:subPropertyOf` descendants, from the vocabulary) are merged into the first, the latter only when their own URLs (`url`, `@id`, `mainEntityOfPage`, not Offer URLs) don't name different items. Resolution's rules then apply: Offers that disagree are `offers_disagree`.
- Alternatives: A cross-collector merge in `EntityGraph` (follow-up); merging by name.
- Why: Duplicate theme blocks left pages `intent_ambiguous` or silently ignored a contradicting Offer.
- Reversible: yes

### D-0943 — JS-state admission indexes anchors by equality key
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.5, round-1 class 3 (#207) · Status: decided
- Decision: Each field's anchors are indexed by `equality_key` once; a value looks up its key once, and a value repeated across documents is read once. A field whose equality has no key (location) compares pairwise.
- Alternatives: Caching `url.canonical` only.
- Why: Admission was O(scalars × anchors) with uncached canonicalization (67.8 s → 1.8 s on the round-1 capture, same fields).
- Reversible: yes

### D-0944 — An independent value selects one of an entity's several values
- Date: 2026-10-16 · Spec/PR: SPEC-05 §4.7 (ARCHITECTURE §10 reading), round-1 class 4 (#207) · Status: decided
- Decision: When the top-ranked kind's candidates disagree but are one entity's values (a JSON-LD array, a repeated itemprop), the one value that independent candidates of other kinds equal publishes; failing equality, an image_url value naming the same file (scheme, authority, path; query aside, `resource_key`) selects it. Otherwise conflict.
- Alternatives: First member (JSON-LD arrays are unordered sets, §4.3.1); rendition parameter lists (C4); applying the file key to page URLs (a query can name a variant).
- Why: `Product.image` arrays left image_url a conflict on gallery pages; precedence alone cannot decide inside one kind.
- Reversible: yes

### D-0946 — Round-1 classes 10, 11 and 13 are not built in core
- Date: 2026-10-16 · Spec/PR: round-1 eval (#207) · Status: decided
- Decision: Class 10 (image_url from the DOM) and class 13 (an external apply link) need generic DOM heuristics, which ARCHITECTURE §8.1 excludes from core (structural collectors are a §22 candidate, C13); class 11 (location macro-regions and an "or" split) needs a new location representation (SPEC-04 / ARCHITECTURE §9 design).
- Alternatives: Build them here.
- Why: Out of this batch's authority; recorded as follow-ups with the eval evidence.
- Reversible: yes
