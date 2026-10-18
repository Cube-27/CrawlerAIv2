# Extraction Specification

## Purpose

Extraction turns one capture into owned, located candidates from standards-based collectors (`collect/`) and renders
page content formats; a listing's rows are in [listings](../listings/spec.md), and what publishes is in
[resolution](../resolution/spec.md).
Rationale: ARCHITECTURE §8 ([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-05, SPEC-07.

## Requirements

### Requirement: Parse once (INV-26)
Within one pipeline run or `scrape` request the system SHALL decode each capture body once and parse it at most once
per parser into one shared `ParsedPage` (`content/page.py`, lxml built lazily); collectors, text, formats, pagination
and the config executor read it, never the raw body (the release executor, INV-20, excepted). Refs: §8, D-0281.
Enforced by: a test counting parser constructions in `extract_page` and `scrape`; active.
#### Scenario: Scrape with records and formats
- **WHEN** a `scrape` request asks for records, `markdown` and `html` of one capture
- **THEN** selectolax and lxml are each constructed at most once for that body

### Requirement: Cleaned text and visibility index
The system SHALL render cleaned text in one walk that drops non-rendered and HTML-hidden elements and joins inline text
per CSS Text 3 (`content/text.py`); an element whose text ends in an ellipsis and whose `title` extends it reads as
that title; the walk records each shown link (`a[href]`) and image (`img[src]`) with its span, path, target and
announced name; `visible(value)` is a whole-word match on that text plus shown elements' `alt`, `title`, `value` and
`content`. (Previously: links and images were not recorded.) Refs: SPEC-05 §4.4, D-0334..D-0339, D-1154, D-1624.
#### Scenario: Price split across inline elements
- **WHEN** the page shows `$<span>19</span>.99`
- **THEN** the cleaned text holds `$19.99` and `visible("9.99")` is false

### Requirement: Run every cheap collector
The system SHALL run every collector on every served capture in the order of `collect/run.py`; skipping only ever
skips the LLM or the browser. A collector MUST NOT raise: an error becomes an empty result plus a diagnostic.
Refs: §8.1, §8.2 rule 1, D-0387, D-0959.

### Requirement: Shells are not observations (INV-11)
Blocked and shell captures SHALL yield zero candidates and zero records; the outcome is the block class (`blocked`,
`shell`, `not_found`) with no fields. Refs: §8.2 rule 2, D-0354.
Enforced by: unit tests on the pipeline entry; active.
#### Scenario: Challenge page
- **WHEN** a capture's block class is `blocked`
- **THEN** the extraction has no candidates and no record is stored

### Requirement: Structured-data collectors
The system SHALL read JSON-LD (RFC 8259, `@graph`/`@id` resolved, schema.org terms only under a schema.org context,
`rdfs:subPropertyOf` for identifiers), microdata and RDFa Lite (HTML Standard item and value rules; a URL-attribute or
RDFa IRI value is a URL, never text, D-1153) and Open Graph
(one fixed table of OGP-defined properties: basic and optional metadata, `og:description` filling a long_text
description, and the `product:` namespace; no translation, site-default blocks skipped) through the field's
`schema_org` path; a property no published standard defines is left to learned configs (owner, Appendix A #48). A
node is an entity of every type it declares (JSON-LD 1.1 §3.5, a microdata `itemtype` list), and a text value holding
element markup, also written escaped (`&lt;p&gt;`), is read as the fragment's rendered text. Refs: §8.1,
D-0388..D-0406, D-0940, D-1180, D-1183, D-1186, D-1486.
#### Scenario: Escaped markup
- **WHEN** a text value is block markup written escaped (`&lt;p&gt;…&lt;/p&gt;&lt;ul&gt;…`)
- **THEN** it normalizes as the unescaped markup does; an escaped `<` that makes no element (`1 &lt; 2`) stays text
#### Scenario: gtin13 for a gtin field
- **WHEN** a Product states `gtin13` and the schema's identifier field maps `Product.gtin`
- **THEN** the `gtin13` value is a candidate for that field
#### Scenario: Two types
- **WHEN** a JSON-LD node is typed `["VideoGame", "Product"]` and states an Offer
- **THEN** the node is a Product for intent and ownership, and its Offer's price publishes
#### Scenario: og:description
- **WHEN** a page states only `og:description` for its product
- **THEN** that text is the `description` candidate, ranked behind JSON-LD and microdata

### Requirement: Embedded JSON state and XHR admission
The system SHALL admit a scalar from `<script>` JSON, JS assignments or captured XHR bodies only when it equals another
kind's candidate (`independent=false`, owned by that candidate's entity), or when the field has none, the value is
visible and its type is checkable (`collect/admission.py`); text-like types admit by equality only. A value admitted by
visibility inside an array row (an object item of an array holding two or more objects, or an array's only object when
its own scope writes a URL that names a document, not a media file) is owned by that row's `array_row` entity, whose
`urls` are the URLs in its scope up to nested rows; elsewhere it is owned by `page`. An array row writing a URL is an
`array_row` entity even when it owns no value, so a listing's rows bind to it ([listings](../listings/spec.md)). Each
field, normalized value and owner is one candidate, the one with the shortest locator. (Previously: only a row owning a
value was an entity.) Refs: §8.1, Appendix A #34, #55, D-0418, D-0943, D-1250–D-1252, D-1254, D-1343, D-1345.
#### Scenario: Visible text in state
- **WHEN** a visible state string is the only candidate for a `text` field
- **THEN** it is not admitted
#### Scenario: Price in a row of state
- **WHEN** a visible state price is the only candidate for a `money` field and sits in the second object of an array
  of two objects
- **THEN** it is owned by that object's `array_row` entity, not by `page`
#### Scenario: Related item alone in its array
- **WHEN** an array's only object writes another page's URL and a visible price
- **THEN** the price is owned by that object's `array_row` entity and is not the detail target's

### Requirement: Structural DOM values
On a detail page the system SHALL take label–value pairs from two-cell `tr` rows and `dl` groups whose label's words
equal the field's or its schema.org property's name, and the main image of the one `main`/`role=main`/`article`
outside chrome, decorative images and link cards (`collect/dom.py`); values MUST be visible. Refs: Appendix A #42, D-0955, D-1096.

### Requirement: No generic DOM heuristics
Collectors SHALL contain no hostname, class fragment, phrase list or card selector; per-site selectors live only in
configs. Repeated-structure rows and typed value spotting are read only by the item layer
([listings](../listings/spec.md)), from structure, field types and named standards. (Previously: repeated-structure
extraction and typed value spotting were not built.) Refs: C2, C3, C13, owner #67.
#### Scenario: Site literal in a collector
- **WHEN** a change adds a hostname or class fragment under `collect/`
- **THEN** the site-literal scan fails

### Requirement: Locator on every candidate
Every candidate SHALL carry one `<scheme>:<address>` locator in the spellings of `collect/locator.py` (JSONPath per
RFC 9535, XPath from `/`), which reads back to the raw value. Refs: §8.1, SPEC-05 §4.3, D-0352, D-0910.
#### Scenario: Locator reads back
- **WHEN** a JSON-LD price candidate has locator `jsonld:0:$['offers']['price']`
- **THEN** evaluating that path on block 0 of the capture returns the candidate's raw value

### Requirement: Ownership from structure
A candidate SHALL belong to the entity whose JSON object or DOM item contains it; entities form a tree (`parent`,
`via`, `urls`), and page-level candidates belong to `page`. Resolution applies it as a stage. Refs: §8.2 rule 3, D-0389, D-0785.

### Requirement: URL parameter values (INV-13)
A candidate any of whose values equals a non-empty decoded query value of the request URL SHALL be rejected
`url_param` unless `visible` finds it. Refs: §8.2 rule 4, D-0441.
Enforced by: resolver test; active.
#### Scenario: Currency copied from the URL
- **WHEN** the request URL has `?currency=EUR`, a state value is `EUR` and no `EUR` is shown
- **THEN** that candidate is rejected with reason `url_param`

### Requirement: Page content formats
The system SHALL produce `markdown`, `html`, `raw_html`, `links` and `metadata` from the `ParsedPage` with no per-site
cleaning (`content/`); `markdown` is `""` when there is no main content, keeps the space after an inline element in a
`div`, `td` or `li`, and a listing capture appends the first of the page's ranked repeated item groups
(`ParsedPage.item_groups`, [listings](../listings/spec.md)) as a list, a listing without one being read in recall
mode. A JSON body (an `api` capture's) is never read as HTML: its `links` are its absolute http(s) URL string values
in document order, never markup inside a value; its `markdown` (and `markdown_fit`) is the answer pretty-printed in
one fenced `json` code block; its `html` is `""`. (Previously: the group with the most structural evidence was chosen
by the format itself.) Refs: §8.5, SPEC-07 §4.5, D-0401, D-0993, D-1275, D-1276, D-1277, D-1450, D-1473, D-1474;
endpoint in [rest-api](../rest-api/spec.md).
#### Scenario: No main content
- **WHEN** trafilatura finds no main content
- **THEN** `markdown` is the empty string
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards are the listed items
#### Scenario: API answer
- **WHEN** an adapter's JSON answer holds a posting URL and a description whose markup links elsewhere
- **THEN** `links` holds the posting URL and nothing read from the description's markup, `markdown` is the answer in a
  `json` code block and `html` is empty

### Requirement: Fit markdown and chunks
`markdown_fit` SHALL be the page's markdown pruned by deterministic block scores (link density, text density, and
repetition of a block across the page), keeping at most `fit.max_blocks`; with `fit.query` it keeps the blocks that
rank by BM25 (Robertson and Zaragoza, 2009) over the blocks. `chunks` SHALL split the markdown (or `markdown_fit`)
by `heading`, `sentence` or `token` strategy with a `size` and `overlap` in words, each chunk carrying its heading
path. Neither uses an LLM. Refs: D-1422, D-1423.
#### Scenario: Query keeps relevant blocks
- **WHEN** `fit.query` names a topic of one block
- **THEN** that block is kept and unrelated blocks are not
