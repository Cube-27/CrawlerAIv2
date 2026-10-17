# Extraction Specification

## Purpose

Extraction turns one capture into owned, located candidates from standards-based collectors (`collect/`), finds
listing rows and next pages, and renders page content formats; what publishes is [resolution](../resolution/spec.md).
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
that title; `visible(value)` is a whole-word match on that text plus shown elements' `alt`, `title`, `value` and
`content`. Refs: SPEC-05 §4.4, D-0334..D-0339, D-1154.
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
element markup is read as the fragment's rendered text. Refs: §8.1, D-0388..D-0406, D-0940, D-1180, D-1183, D-1186.
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
kind's candidate (`independent=false`), or when the field has none, the value is visible and its type is checkable
(`collect/admission.py`); text-like types admit by equality only. Refs: §8.1, Appendix A #34, D-0418, D-0943.
#### Scenario: Visible text in state
- **WHEN** a visible state string is the only candidate for a `text` field
- **THEN** it is not admitted

### Requirement: Structural DOM values
On a detail page the system SHALL take label–value pairs from two-cell `tr` rows and `dl` groups whose label's words
equal the field's or its schema.org property's name, and the main image of the one `main`/`role=main`/`article`
outside chrome, decorative images and link cards (`collect/dom.py`); values MUST be visible. Refs: Appendix A #42, D-0955, D-1096.

### Requirement: No generic DOM heuristics
Collectors SHALL contain no hostname, class fragment, phrase list or card selector; per-site selectors live only in
configs. Repeated-structure extraction and typed value spotting are not built (§22). Refs: C2, C3, C13.
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

### Requirement: Cold listing rows and pagination
On a listing the system SHALL take rows from `ItemList`/`ListItem` entities, else from 3 or more top-level primary
entities, else from role C; a role C row whose grounded values lie in exactly one block of the repeated item group
holding most rows (block text as the cleaned text shows it; a value that is an element's whole text picks its block),
a block no other row has, takes as a `dom` item-URL candidate the one document the block's hyperlinks, else its
hyperlinks labelled with a row value, lead to (`collect/item_links.py`, Appendix A #47, D-1122, D-1241–D-1244); next
pages come from `rel=next`, then the current+1 integer link, then a config's `listing.next` (`resolve/listing.py`,
`resolve/pagination.py`). Refs: §8.6, D-0509, D-0514.
#### Scenario: Title cut short
- **WHEN** a card shows `Widget with a lo…` with `title="Widget with a long name"` and role C grounds the full title
- **THEN** the row takes that card's link

### Requirement: Page content formats
The system SHALL produce `markdown`, `html`, `raw_html`, `links` and `metadata` from the `ParsedPage` with no per-site
cleaning (`content/`); `markdown` is `""` when there is no main content, and a listing capture appends its largest
repeated linked-item group as a list. Refs: §8.5, SPEC-07 §4.5, D-0401, D-0993; endpoint in [rest-api](../rest-api/spec.md).
#### Scenario: No main content
- **WHEN** trafilatura finds no main content
- **THEN** `markdown` is the empty string
