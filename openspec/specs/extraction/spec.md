# Extraction Specification

## Purpose

Extraction turns one capture into candidates: it parses the capture once, runs the standards-based collectors
(JSON-LD, microdata/RDFa Lite, Open Graph, embedded JSON state, captured XHR JSON, structural DOM values, adapters,
configs), gives every candidate an owner entity and a locator, finds listing rows and next pages, and renders the
page content formats. Choosing what publishes is [resolution](../resolution/spec.md); per-variant rows are
[variants](../variants/spec.md); learned configs are [learning-configs](../learning-configs/spec.md).
Design rationale: [ARCHITECTURE §8](../../design/extraction.md). History: [SPEC-05](../../changes/archive/2026-10-16-spec-05-extraction-and-resolution/SPEC-05-extraction-and-resolution.md) and its [decisions](../../changes/archive/2026-10-16-spec-05-extraction-and-resolution/decisions.md); content formats in [SPEC-07](../../changes/archive/2026-10-13-spec-07-api-foundation-and-scrape/SPEC-07-api-foundation-and-scrape.md) §4.5 and its [decisions](../../changes/archive/2026-10-13-spec-07-api-foundation-and-scrape/decisions.md).

## Requirements

### Requirement: Parse once (INV-26)
Within one pipeline run (or one `scrape` request) the system SHALL parse each capture body at most once per parser
(selectolax, lxml) into one shared `ParsedPage`, which holds the selectolax tree, the lxml tree (built lazily, only
when an XPath step or trafilatura needs it), the `<script>` blocks, the captured network bodies, the cleaned text and
the visibility index. Collectors, cleaned text, content formats, pagination and the config executor MUST read the
`ParsedPage`, never the raw body; the release executor (INV-20) is the only exception. The body is decoded once, in
the Content-Type charset else UTF-8, for both parsers.
Refs: §8, Appendix A #31, SPEC-05 §4.1, D-0281, D-0338, D-0399, D-0422.
Enforced by: a test that counts parser constructions in `extract_page` and `scrape`; status: SPEC-05 (`content.page`), SPEC-07, SPEC-08.

#### Scenario: Scrape with records and formats
- **WHEN** a `scrape` request asks for records, `markdown` and `html` of one capture
- **THEN** selectolax and lxml are each constructed at most once for that capture body

### Requirement: Cleaned text and visibility index
The system SHALL render cleaned text from the selectolax tree in one walk, dropping `script`, `style`, `noscript`,
`template`, `svg`, `iframe` and the HTML Standard's hidden elements (`hidden`, `aria-hidden="true"`, inline
`display:none`, inherited `visibility:hidden`), joining inline text as rendered (CSS Text 3 whitespace collapsing)
and recording `(start, end, node_xpath)` per run. `visible(value)` SHALL be a whole-word substring match against the
cleaned-text lines plus the `alt`, `title`, `value` and `content` attributes of shown elements.
Refs: SPEC-05 §4.4, D-0334, D-0335, D-0336, D-0337, D-0339.

#### Scenario: Price split across inline elements
- **WHEN** the page shows `$<span>19</span>.99`
- **THEN** the cleaned text holds `$19.99` and `visible("9.99")` is false

### Requirement: Run every cheap collector
The system SHALL run every collector on every served capture, in the order adapter / API recipe, structured
(JSON-LD, microdata, Open Graph), structural DOM, then js_state and xhr admission, then the active config; skipping
only ever skips the LLM or the browser. A collector MUST NOT raise: an error becomes an empty result with a
diagnostic on the extraction.
Refs: §8.1, §8.2 rule 1, SPEC-05 §4.5, §4.14, D-0387, D-0484, D-0959.

#### Scenario: One malformed JSON-LD block
- **WHEN** one `application/ld+json` block fails to parse
- **THEN** that block is skipped with a diagnostic and every other collector's candidates are kept

### Requirement: Shells are not observations (INV-11)
Blocked and shell captures SHALL yield zero candidates and zero records; `extract_page` returns the block class
(`blocked`, `shell`, `not_found`) as the outcome with no fields.
Refs: §7.1, §8.2 rule 2, SPEC-05 §4.8, D-0354.
Enforced by: unit tests on the pipeline entry; status: SPEC-05.

#### Scenario: Challenge page
- **WHEN** a capture's block class is `blocked`
- **THEN** the extraction has no candidates and no record is stored

### Requirement: JSON-LD collector
The system SHALL parse every `application/ld+json` block as JSON (RFC 8259), accepting raw U+0000–U+001F inside
strings and repairing nothing else, expand `@graph`, resolve `@id` within the page, and read bare terms as
schema.org only under a schema.org context. Every object typed with a vocabulary type is an entity; root nodes of
one type that share a resolved `@id`, or an identifier value without URLs naming different items, are one entity.
Each field's `schema_org` path gives candidates per entity of its root type (or subtype); an `identifier` field's
last property also reaches its `rdfs:subPropertyOf` descendants, and on a path ending `.name` a text value stands for
the thing's name.
Refs: §8.1, SPEC-05 §4.5, D-0388, D-0389, D-0390, D-0391, D-0392, D-0942, D-0958, D-0965.

#### Scenario: gtin13 for a gtin field
- **WHEN** a Product states `gtin13` and the schema's identifier field maps `Product.gtin`
- **THEN** the `gtin13` value is a candidate for that field

### Requirement: Microdata and RDFa Lite collector
The system SHALL read `itemscope`/`itemtype`/`itemprop` per the HTML Standard and RDFa Lite `typeof`/`property`
through the same schema.org mapping as JSON-LD. An `itemprop` belongs to its nearest `itemscope` element; a nested
item is its holder's child; a short name is schema.org only in an item with a schema.org `itemtype` or under a
schema.org `vocab`; values follow the HTML Standard's "Values" rules.
Refs: §8.1, SPEC-05 §4.5, D-0404, D-0405, D-0406, D-0852.

#### Scenario: Untyped nested item
- **WHEN** an untyped item is nested inside a schema.org Product item
- **THEN** its `itemprop` names are in no vocabulary and give no candidates

### Requirement: Open Graph collector
The system SHALL map `og:*` and `product:*` properties through one fixed table justified by the Open Graph protocol:
`og:title` to text fields whose path names `name` on the root type, `og:image` to image fields, `og:url` to url
fields, `product:price:amount`+`currency` to money, `product:availability` to availability, each owned by `page`.
A repeated property gives a scalar field its first value. Values MUST NOT be translated. When `og:title` names the
site (equals `og:site_name` or the host's registrable-domain label), neither `og:title` nor `og:image` is read;
trailing title segments that name the site are dropped.
Refs: §8.1, SPEC-05 §4.5, D-0383, D-0384, D-0385, D-0940, D-0941.

#### Scenario: Site default og block
- **WHEN** `og:title` folds to the same words as `og:site_name`
- **THEN** no `og:title` or `og:image` candidate is produced and `og:url` is still read

### Requirement: Embedded JSON state and XHR admission
The system SHALL read every `<script type="application/json">` and every `window.<ident>=` / `var|let|const
<ident>=` assignment whose value is a JSON object or array, and the bundle's captured JSON bodies, without mapping
keys. A scalar leaf SHALL become a candidate only (a) when it equals another source kind's candidate for the field
(`independent=false`, owned by that candidate's entity), or (b) when the field has no other-kind candidate, the value
is visible and the type is checkable: money, enum, date, datetime, location, range, a `gtin`/`isbn` identifier, or a
url/image_url given absolute (`independent=true`, owned by `page`). Text, long_text, object and other identifiers
MUST admit by equality only.
Refs: §8.1, Appendix A #34, SPEC-05 §4.5, D-0418, D-0419, D-0420, D-0780, D-0851, D-0943.

#### Scenario: Visible text in state
- **WHEN** a visible state string is the only candidate for a `text` field
- **THEN** it is not admitted

### Requirement: Structural DOM label–value pairs
On a detail page the system SHALL take a candidate from a two-cell `tr` whose first cell heads it, and from each
`dl` group's terms and descriptions, when the label's words (NFKC, case-folded, split on non-alphanumerics and
lowerCamelCase) equal those of the field's name or of the schema.org property its path names. The value MUST be
visible; list and object fields get no pair. Candidates have source kind `dom`, entity `page`, `independent=true`
and a `dom:<xpath>` locator, with no trust of their own.
Refs: §8.1, Appendix A #42, SPEC-05 §4.5, D-0955, D-0956, D-0957.

#### Scenario: Label in the schema's words
- **WHEN** a table row reads `SKU | AB-12` and the schema has a field named `sku`
- **THEN** `AB-12` is a `dom` candidate for `sku`

### Requirement: Main image
On a detail page the system SHALL take, for `image_url` fields whose path names `image`, the first `img` of the one
`main` element (else the one `role="main"`, else the one `article`) that is outside `nav`/`header`/`footer`/`aside`
and dialogs, shown by the cleaned-text rules, outside media fallback content, not decorative (empty `alt`, roles
`none`/`presentation`), not a link card's image, and whose `src` (else first `srcset` URL) is not a `data:` URL.
A link card is the nearest block holding a hyperlink that holds no other image and links to exactly one other
document, not this page and not an `image/*` resource.
Refs: §8.1, Appendix A #42, SPEC-05 §4.5, D-1023, D-1096.

#### Scenario: Comparison card
- **WHEN** the first image in `main` sits alone in a block linking to one other product page
- **THEN** it gives no `image_url` candidate

### Requirement: No generic DOM heuristics
Collectors SHALL contain no hostname, class-name fragment, phrase list, `[class*=…]`, bare `h1` or card selector.
The only DOM selectors are per-site ones in configs and the structural rules above, each named by the HTML structure
it reads. Repeated-structure extraction and typed value spotting are not built (§22 candidates).
Refs: §8.1, C2, C3, C13, SPEC-05 §4.5.

#### Scenario: Site literal in a collector
- **WHEN** a change adds a hostname or class fragment under `collect/`
- **THEN** the site-literal scan fails

### Requirement: Locator on every candidate
Every candidate SHALL carry a locator `<scheme>:<address>` with one spelling: `jsonld:<block>:<jsonpath>` (path into
the block as written), `microdata:<xpath>`, `dom:<xpath>`, `meta:<property>`, `js_state:<script_xpath>:<jsonpath>`,
`xhr:<n>:<jsonpath>`, `adapter:<name>:<jsonpath>`, `api:<recipe_id>:<jsonpath>`, `config:<field>:<step>:<selector>`,
`text:<start>-<end>` (non-empty span of cleaned text), or `derived:canonical_link|final_url`. JSONPath starts with
`$` (RFC 9535) and XPath with `/`; the last address part takes the rest of the string.
Refs: §8.1, SPEC-05 §4.3, D-0352, D-0392, D-0910.

#### Scenario: Locator reads back
- **WHEN** a JSON-LD price candidate has locator `jsonld:0:$['offers']['price']`
- **THEN** evaluating that path on block 0 of the capture returns the candidate's raw value

### Requirement: Ownership from structure
A candidate SHALL belong to the entity whose JSON object or DOM item contains it; entities form a tree with `parent`,
`via` (the parent's property holding it) and `urls` (`url`, `@id` without fragment, `mainEntityOfPage`, offers'
`url`). Page-level candidates (og, meta, dom, text) belong to `page`. A `hasVariant` member's Offer is its group's;
its other values stay its own. Resolution applies ownership as a stage.
Refs: §8.2 rule 3, Appendix A #36, SPEC-05 §4.6, D-0389, D-0390, D-0412, D-0785; see [resolution](../resolution/spec.md).

#### Scenario: Related product's price
- **WHEN** a price sits in a Product under the target's `isRelatedTo`
- **THEN** that price is owned by the related Product, not the target

### Requirement: URL parameter values (INV-13)
The system SHALL never publish a URL query-parameter value unless the same value is visible on the page: a candidate
any of whose strings or numbers (nested ones included) equals a decoded query value of the request URL is rejected
`url_param` unless `visible` finds it. Empty values are ignored.
Refs: §8.2 rule 4, SPEC-05 §4.8, D-0441.
Enforced by: resolver test; status: SPEC-05.

#### Scenario: Currency copied from the URL
- **WHEN** the request URL has `?currency=EUR`, a state value is `EUR` and no `EUR` is shown
- **THEN** that candidate is rejected with reason `url_param`

### Requirement: Cold listing rows
On a listing schema the system SHALL take as rows the primary-type entities listed by an `ItemList`/`ListItem` (with
no primary entity between), else the top-level primary entities when at least 3 exist and intent names none of them;
a row an earlier row of another collector shares a non-page URL with is dropped. Rows take no page-level value; page
fields resolve against the page entity. With no structured rows, role C reads rows from the page text, and those
rows carry no item URL (D-1024 open).
Refs: §8.6, SPEC-05 §4.7, D-0509, D-0510, D-0853, D-1024; see [llm](../llm/spec.md).

#### Scenario: Two products only
- **WHEN** a listing page has 2 top-level Products and no ItemList
- **THEN** no structured rows are taken

### Requirement: Pagination
The system SHALL return next-page candidates in order: `<link rel=next>` and `<a rel=next>`; then, among
same-path links that differ from the current URL only in one integer path segment or one integer query parameter
(name ignored), the one equal to current+1; then an active config's `listing.next` step. With no integer in the page
URL no structural candidate is taken. `next_page_url` MUST NOT be filled from pagination in cold mode.
Refs: §8.6, SPEC-05 §4.12, D-0514, D-0515.

#### Scenario: Numbered links
- **WHEN** the page URL is `https://example.com/c?p=2` and links to `?p=1`, `?p=3`
- **THEN** `https://example.com/c?p=3` is a next-page candidate

### Requirement: Page content formats
For `scrape` formats the system SHALL produce, from the `ParsedPage` and with no per-site cleaning: `markdown`
(trafilatura, `favor_precision`, links and images, targets resolved against the document base URL, layout
whitespace dropped per line; `""` when there is no main content); `html` (a clone with `script`, `style`,
`noscript`, `template`, event-handler attributes and `javascript:` URLs removed); `raw_html` (the body as captured);
`links` (every `a[href]` and `link[rel=canonical|next|prev|alternate]`, absolutized, canonicalized, deduplicated,
document order); `metadata` (`title`, `description`, `language`, `canonical`, `og` map, `structured_data_types`).
For a capture fetched as a listing, the largest group of repeated linked items (`acquire.items`) is appended to the
markdown as a list.
Refs: §8.5, SPEC-07 §4.5, D-0401, D-0402, D-0403, D-0774, D-0775, D-0934, D-0993; endpoint in [rest-api](../rest-api/spec.md).

#### Scenario: No main content
- **WHEN** trafilatura finds no main content
- **THEN** `markdown` is the empty string

#### Scenario: Listing grid
- **WHEN** a listing capture shows 12 sibling tiles of one shape, each holding a link
- **THEN** the markdown ends with a list of those 12 items
