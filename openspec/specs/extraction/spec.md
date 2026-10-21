# Extraction Specification

## Purpose

Extraction turns one capture into owned, located candidates from standards-based collectors (`collect/`) and renders
page content formats; a listing's rows are in [listings](../listings/spec.md), and what publishes is in
[resolution](../resolution/spec.md).

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
announced name; `visible(value)` is a whole-word match on that text plus shown elements' `alt`, `title` and
`content`, and the `value` of an `input` whose state shows it as text or as its button's label (HTML Standard §4.10.5;
an `option`'s, `button`'s, `data`'s or `li`'s `value` is a form or machine value, not shown). An element concealed by the `hidden` attribute or an inline `display: none` that holds the document's one
`h1` and a form, or that is a child of the `main` element none of whose children renders and holds a heading (`h1`-`h6`)
and more text than any other concealed child, is the page's own content a script reveals after load (a content-gating
app), and is shown (`content.text.script_revealed`, also for the item groups, listings spec); any other concealed
element stays hidden. (Previously: every element's `value` attribute was visible; links and images were not recorded; a concealed wrapper around the page's
title and form hid them; a concealed main landmark content without the document's `h1` stayed hidden.) Refs: SPEC-05 §4.4, D-0334..D-0339, D-1154, D-1624.
#### Scenario: Price split across inline elements
- **WHEN** the page shows `$<span>19</span>.99`
- **THEN** the cleaned text holds `$19.99` and `visible("9.99")` is false
#### Scenario: Script-revealed product block
- **WHEN** the page's one `h1` and its product form sit in a `div style="display:none"`, beside a hidden variant block
  holding another price
- **THEN** the title and the form's price are in the cleaned text and the variant block's price is not

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
The system SHALL read JSON-LD (RFC 8259, with the §9 extensions of raw control characters in strings and of a number
written with leading zeros, read as the string of its digits; `@graph`/`@id` resolved, schema.org terms only under a schema.org context,
`rdfs:subPropertyOf` for identifiers), microdata and RDFa Lite (HTML Standard item and value rules; a URL-attribute or
RDFa IRI value is a URL, never text, D-1153) and Open Graph
(one fixed table of OGP-defined properties: basic and optional metadata, `og:description` filling a long_text
description, and the `product:` namespace: `product:price`/`og:price` amount and currency, `product:sale_price`
as the active price (unless `product:sale_price_dates:end` is before the capture) with the stated price beside it
as the list price, `product:original_price` as the list price,
`og:availability`, `product:condition`, `product:retailer_item_id` and `product:brand`; no translation, site-default
blocks skipped, an `og:title` read without trailing segments naming the site and, when words of its own come before a
run of its words that the document's one `h1` states (two words or more), as that run, else before a run that a slug
segment of the page URL path spells (the last such segment the title holds), as that run) through the field's role, the property of its root type its `schema_org` path reads (a final `.name`
standing in for that thing; a path through another thing, `Product.offers.seller.url`, has none); a property no published standard defines is left to learned configs (owner, Appendix A #48). A
node is an entity of every type it declares (JSON-LD 1.1 §3.5, a microdata `itemtype` list), and a text value holding
element markup, also written escaped (`&lt;p&gt;`), is read as the fragment's rendered text; a text value that is the
IRI of a schema.org enumeration member (`suggestedGender`: `https://schema.org/Male`) is read as the member's name
(`Male`), as an enum field publishes it. A url or image field
whose path ends at a node (schema.org `image`: ImageObject or URL) reads the node's `contentUrl`, else its `url`. A
platform's documented
product JSON that a detail page's HTTP fetch joined after its identity check (acquisition spec, "Data calls") is read
as that platform documents its members (`adapters/platforms.answer_shapes`, `collect/platform_json.py`): `adapter`
candidates of the requested product, amounts in the minor unit the documentation states, and no Offer when its
variants are priced differently (the page states the selected one). Refs: §8.1,
D-0388..D-0406, D-0940, D-1180, D-1183, D-1186, D-1486, owner decision 2026-10-19 on #326, architecture-v3 d.6.
(Previously: Open Graph read `product:price` alone, whatever the money field's price role; an `image` written as an
ImageObject was an invalid value.)
#### Scenario: OG sale price
- **WHEN** a page states `product:price:amount` 100 and `product:sale_price:amount` 80, and the schema has `price` and
  a user-added `list_price`
- **THEN** `price` has the candidate 80 and `list_price` the candidate 100
#### Scenario: Escaped markup
- **WHEN** a text value is block markup written escaped (`&lt;p&gt;…&lt;/p&gt;&lt;ul&gt;…`)
- **THEN** it normalizes as the unescaped markup does; an escaped `<` that makes no element (`1 &lt; 2`) stays text
#### Scenario: gtin13 for a gtin field
- **WHEN** a Product states `gtin13` and the schema's identifier field maps `Product.gtin`
- **THEN** the `gtin13` value is a candidate for that field
#### Scenario: Two types
- **WHEN** a JSON-LD node is typed `["VideoGame", "Product"]` and states an Offer
- **THEN** the node is a Product for intent and ownership, and its Offer's price publishes
#### Scenario: Image objects
- **WHEN** a Product's `image` is two ImageObjects, one stating `contentUrl` and one only `url`
- **THEN** the image list candidate holds both files
#### Scenario: og:description
- **WHEN** a page states only `og:description` for its product
- **THEN** that text is the `description` candidate, ranked behind JSON-LD and microdata
#### Scenario: og:title around a slug
- **WHEN** `og:title` is `Buy Kettle 2L for Kitchens Online` on a page at `/kettle-2l/p/12`
- **THEN** the title candidate reads `Kettle 2L`, and so it does at `/kettle-2l/12/item-page`, a fixed last segment
  the title does not hold
#### Scenario: og:title around the h1
- **WHEN** `og:title` is `Buy Acme Kettle 2L Online at Example` and the page's one `h1` is `Acme Kettle 2L`
- **THEN** the title candidate reads `Acme Kettle 2L`

### Requirement: Source documents
`ParsedPage` SHALL read the HTML document after four structural pre-passes, applied in this order to the raw document
before any text or DOM collector runs (`content/page.py::prepassed`; no script runs, each pass matches its documented
form only, and a document none applies to is not reparsed):
- **Declarative shadow DOM** (HTML Standard, `template` `shadowrootmode` `open` or `closed`): the template's content
  takes its place among its host's children; slotted light-DOM children stay where they are.
- **Completed streaming boundaries** (React Fizz instruction set, `completeBoundary`): for each inline script's
  `$RC("<boundary id>", "<content id>")` call, the children of the (hidden) element with the content id take the place
  of the `template` with the boundary id, and the fallback after it, up to the boundary's closing `<!--/$-->` comment,
  is removed; a `$RX` call leaves the fallback.
- **Eager fragment inclusion** (Hotwire Turbo, Frames): the children of each eager `<turbo-frame id src>` are replaced
  by those of the element with the same id in the captured 2xx HTML answer to its `src`
  ([acquisition](../acquisition/spec.md), "Eager fragments"); a frame without an answer keeps its own.
- **Fetched partials** (htmx-style swaps, frames the browser filled): each captured 2xx HTML answer that is no whole
  document (it does not start, after white space and comments, with a DOCTYPE or an `html`, `head` or `body` tag), is
  no answer a frame included, and whose visible text the document's visible text does not already hold is appended to
  the body in an element naming its URL (`data-fragment-src`), in capture order, so the text, DOM and item collectors
  read its values and rows as the page's and a locate run places them as it places the page's
  ([acquisition](../acquisition/spec.md), "Network body capture"); a whole document (a Turbo Drive visit) is not.
  (Previously: a fetched answer was read only as a frame's.) Refs: architecture v3 a.3, a.4 item 5.
The `NOT_RENDERED` set and the hidden rules of `content/text.py` then apply unchanged. A `template` left after the
pre-passes is an ordinary one whose content is inert (HTML Standard §4.12.3), so the text and DOM collectors and the
listing induction still drop it. Refs: architecture v3 a.4 item 1.
The system SHALL read a page's embedded state as source documents, by documented structure and never by a variable name
or key (`content/state.py`, `content/js_literal.py`, `content/state_decoders.py`). In every inline script but JSON-LD's,
in script order: the text of a `<script type="application/json">`; the object or array literal after the `=` of
`window.X =`, `var|let|const X =` or a bare `X =` (ECMAScript assignment); and each object literal argument of a call
`X(...)` or `X.y(...)` whose arguments before it are literals or references (ECMAScript CallExpression: GA4
`dataLayer.push`, Meta Pixel `fbq`, SvelteKit `kit.start`). Values are read by the JS literal reader: the ECMAScript
literal subset (object and array literals with identifier, string or numeric keys and trailing commas, string literals
in either quote with their escapes, numeric literals, `true|false|null`, `undefined` and `void 0` as `null`,
parentheses) and the devalue IIFE `(function(a,...){return <literal>}(<args>))` with each parameter replaced by its
argument (Nuxt 2 `window.__NUXT__=`). Comments and string and template literals hold no statement. A value holding
anything else (a function, a call, an operator), or followed by more of its expression, is code and gives no document;
nesting deeper than 128 or more than 10^6 values gives none either. Each document is then decoded by shape: a **devalue
flat array** (element 0 an object whose every value is an in-range index after it, or a Nuxt reviver tuple naming one;
Nuxt 3 `__NUXT_DATA__`) becomes the tree its indices reference, with the `Reactive`, `Ref`, `ShallowRef`,
`ShallowReactive`, `EmptyRef`, `EmptyShallowRef`, `NuxtError` revivers and devalue's `Date`, `Map`, `Set`, `null` types
read as JSON; a **normalized cache** (an object of objects holding `{"__ref": key}` members; Apollo `InMemoryCache`) is
read with every `__ref` replaced by the entry it names, `ROOT_QUERY` first. References on their own path are not
followed, and a decoded tree past the same bounds leaves the document as written. A page's **RSC Flight** stream is one
more document (`content/rsc.py`, React `ReactFlightClient.js`; Next.js App Router): the string chunks (segment 1,
UTF-8) and base64 chunks (segment 3) of its `self.__next_f.push([<segment>, <chunk>])` calls, joined in script order
whatever row they split, read as rows `<hex id>:<tag?><payload>`, where tags `T A O o b U S s L l G g M m V` take a
`<hex byte length>,` prefix and that many bytes (`T` UTF-8 text, which may hold line ends) and every other row ends at
a line end; untagged rows are the JSON model, decoded as above and keyed by row id in the document (addressed by the
first pushing script). A `$`-prefixed string is read by its tag (`parseModelString`): `$$` reads as `$`, a Date
(`$D`) and a BigInt (`$n`) as the text after the tag, `$-0` as the number zero, and any other (a reference `$L`, `$@`, `$<id>`, or a special value
such as `$undefined`) as null, as it states no text of the page (`"$1"` is no count). (Previously: references were kept
as written.)
A captured `text/x-component` body is read by the same reader, one document per body. A malformed row adds a
diagnostic and the other rows are read; a stream over 10^7 bytes is not read.
A `<script type="text/x-magento-init">` (Adobe Commerce) is read as a JSON script. After the scripts and the Flight
document, in document order, the value of each attribute a framework documents as JSON is a document when, as the parser
unescapes it, it starts with `{` or `[` and is RFC 8259 JSON (`content/attr_json.py`): Inertia `data-page`, Livewire
`wire:snapshot`, WooCommerce `data-product_variations`, Adobe Commerce `data-mage-init`, and Astro's `props` on
`astro-island`, revived from its `[type, value]` tuples (`content/state_decoders.py`). No other attribute is read,
whatever its value. Its locator is `attr:<element xpath>@<name>:<path>`, and a config's `jsonpath` step reads these
documents as source `attr`.
#### Scenario: Nuxt 2 devalue state
- **WHEN** a script writes `window.__NUXT__=(function(a,b){return {data:[{price:a,currency:b}]}}(19.99,"EUR"))`
- **THEN** its document is `{"data": [{"price": 19.99, "currency": "EUR"}]}`
#### Scenario: Analytics payload
- **WHEN** a script calls `dataLayer.push({event: "view_item", ecommerce: {currency: "USD", value: 30.03}})`
- **THEN** that object is a state document, admitted by the rule of "Embedded JSON state and XHR admission" and its
  `currency` a declared page currency
#### Scenario: Documented JSON attribute
- **WHEN** a form carries `data-product_variations="[{&quot;display_price&quot;: 18, ...}]"`, and another element
  `data-config="{&quot;price&quot;: 1}"` or `data-mage-init="{&quot;configurable&quot;: {"`
- **THEN** the variations are a document, with locator `attr:<form xpath>@data-product_variations:$[0]['display_price']`
  for the first price, and the other two attributes give none and no error
#### Scenario: Flight rows split across chunks
- **WHEN** `self.__next_f.push([1, …])` chunks split a JSON row and a `T` text row, and a `[3, …]` chunk holds another
  row
- **THEN** the document holds each JSON row's value under its row id, `"$$19.99"` read as `"$19.99"` and `"$L1"` as null
#### Scenario: Code in a value
- **WHEN** an assigned object holds `f: function () { return 1; }` or `at: stamp()`
- **THEN** it gives no document and no error
#### Scenario: Shadow content
- **WHEN** a host holds `<template shadowrootmode="open">` with a label and its value
- **THEN** the text and DOM collectors read the value, and its candidate's XPath addresses the flattened node; an
  ordinary `template`'s content is read by neither
#### Scenario: Late Suspense segment
- **WHEN** a document holds `<div hidden id="S:1">`, `<template id="B:1">` and a script calling `$RC("B:1","S:1")`
- **THEN** the segment is visible text in the boundary's place and the fallback is gone; with `$RX` the fallback stays

### Requirement: Embedded JSON state and XHR admission
The system SHALL admit a scalar from the state documents ("Source documents": JS literals, decoded state, RSC rows) or
captured XHR bodies (JSON or Flight payloads; other than an identity-checked data call's, "Structured-data
collectors") only when it equals another
kind's candidate (`independent=false`, owned by that candidate's entity), or when the field has none, the value is
visible and its type is checkable (`collect/admission.py`) and the value shows the type's checked syntax (`Ok.checked`:
money with a currency sign or code); text-like types admit by equality only. A value admitted by
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

### Requirement: Label vocabulary
A field's labels SHALL be its name, the schema.org property its path names, its description and the synonyms role S
drafted for the schema (`schema_def.labels`, [llm](../llm/spec.md)), compared as NFKC case-folded words
(`collect/labels.py`); collectors hold no phrase list. Without drafted synonyms the vocabulary is the schema's own
words. A schema.org `PropertyValue` under an entity's `additionalProperty` or `identifier` whose `name` or
`propertyID` is a field's label gives that field its scalar `value`, owned by that entity
(`collect/property_values.py`). A list of values (not of lists or objects) has labels too: a label-value pair naming
it gives the items of the lists its value holds (HTML Standard §4.4.5-§4.4.8 `li`), each shown, else its one value;
on a detail page, a shown heading naming it gives the shown items of the lists in its section (`collect/dom_text.py`), and sections
listing different items give none. (Previously: a label matched only the field's name or schema.org property; a list
field had no labels.)
#### Scenario: Drafted synonym
- **WHEN** a schema's `sku` has the synonym `Item no.` and a row reads `Item no. | W-100`
- **THEN** `sku` has the candidate `W-100`; without the synonym, none
#### Scenario: Listed under a heading
- **WHEN** a detail page's heading `Requirements` is followed by a `ul` of two items, and the schema has a list field
  `requirements` of text
- **THEN** `requirements` has the candidate of those two items, from `dom`
#### Scenario: Related item's property value
- **WHEN** a related Product's `PropertyValue` is labelled with a field's label
- **THEN** its candidate is owned by the related Product, not the page's item

### Requirement: Structural DOM values
On a detail page the system SHALL take label–value pairs from the page's main region (`main`, else the one
`role=main`, else the one `article`, else the body) outside chrome, dialogs, media fallback and other items' content
(microdata `isRelatedTo`, `isSimilarTo`, `review`, Review items; sibling blocks that each link to one other document;
other items' cards, below):
two-cell `tr` rows, `dl` groups, elements starting with `Label:` and sibling containers of one shape (two or more)
holding a label element and a value element, whose label is one of the field's labels; lines and sibling pairs that
give a field several values, or one value at the same place in each of three or more sibling blocks of one
template (XPaths differing only in one step's position: each review's `Reviews: 1`; a responsive copy elsewhere in the
layout is not one), are dropped, and an identifier field given two values by any pairs reads none. (Previously: one value
repeated in many places was read.) It SHALL
also take a money or check-digit identifier field's one shown value in the main region (`collect/items/spot.py`, which
spots only text showing the type's checked syntax, `Ok.checked`: a number without a currency sign is not money; for
an identifier also an unlabelled pair's value, never inside a hyperlink to another document; none when several
differ); an identifier without a check digit is read only next to one of its labels. A money field reads by the
price role its path gives it (schemas spec, "Presets"): struck text (`s`, `del`, `strike`, HTML Standard; an inline
`style` whose `text-decoration` or `text-decoration-line` holds `line-through`, CSS Text Decoration 3) only for a list
price; an amount followed by a CLDR per pattern and a CLDR mass, volume, length, area or item unit (`€25/kg`,
`$0.50 per 100 ml`; `normalize/units.py`, the page's and the root locale's CLDR unit data) only for a unit price; an
amount per a CLDR duration unit (`$25/mo`) for no money field; a member price from its labels only. The item layer's
rows read by the same rule (`collect/items/align.py`). It SHALL take as the main image the first shown image (in that
region, else in the body) whose file (`same_file`: the file, or a rendition an image server writes into the path,
under a prefix, below the file or with parameters after a directory) is the main image the page's own structured data
or Open Graph states (an image field's value, a list's first), else the first image of
the one `main`/`role=main`/`article`, outside chrome, decorative images and link cards (`collect/dom_images.py`), an
image's source being its `src` unless its `srcset` has width descriptors or a candidate of pixel density 1 (one without
a descriptor too; HTML Standard §4.8.4.3: `src` is then out of the source set), when it is the widest candidate, else
the first; a lazy loader's `data-srcset` and `data-src` (custom data attributes named after the standard ones, §3.2.6.6)
stand for `srcset` and `src`; and for a list of images whose path names schema.org `image`, the main
image's gallery: from the main image up, the first block with siblings of its tag gives, per such block, its image at
the main image's tag path, shown or not (a carousel hides the slides but the current one), a source several blocks give
left out; none when a block links to another document or fewer than two remain. Both DOM passes (these values and the DOM description block) leave out the cards of other
items (`collect/dom.py` `product_apart`): a shown price that is none of the prices structured data states for the
schema's money fields (only the page product's: not those of an item in another item's scope, `collect/scope.py`: a
value of `isRelatedTo` or `isSimilarTo`, an `ItemList` or `ListItem` and what it holds, or a root item naming only other
documents while another root item of its kind names the page) belongs to the one other document its nearest block holding hyperlinks leads to (HTML Standard
§4.6.1), or that hyperlink's parent when it leads nowhere else, and that block is set apart unless it shows a stated
price or holds the page's title (the main content's first shown `h1`); a block whose hyperlinks lead to several
documents is no card, and without a stated price no card is set apart. Product microdata items, nested or not, that do
not hold the title are set apart too. Values MUST be visible.
(Previously: labels were only names, and other items' content was read; `src` was read before `srcset`, and beside a `1x` candidate; lazy sources, hidden slides and renditions in the path were not read; no list of
images was read; a recommendation card that was not one of two or more sibling cards was read; an other item's
structured price counted as stated, so its card was read; struck text was `s` and `del` only, and an amount per unit
or per period was a price candidate; a page without a main landmark had no main image and no gallery.) Refs: Appendix A #42, D-0955,
D-1096, D-1640, D-1641, D-1642, D-1643.
#### Scenario: Gallery slides
- **WHEN** the main image is one of three sibling slides, two of which hold an image whose `src` is a shared placeholder
  and whose `srcset` lists widths
- **THEN** the list of images is the slides' images, each at its widest `srcset` candidate
#### Scenario: A storefront without a main landmark
- **WHEN** a page has no `main`, `role=main` or single `article`, its JSON-LD `Product.image` names one file, and the
  body shows that file as one of three sibling slides
- **THEN** `image_url` is that slide's image and the list of images is the three slides' images
#### Scenario: Label line
- **WHEN** the main region holds `Brand: <span>Example Brand</span>`
- **THEN** `brand` has the candidate `Example Brand` located at the span
#### Scenario: Lines of listed items
- **WHEN** the page holds `SKU: A-1` and `SKU: A-2` lines
- **THEN** `sku` has no candidate from them
#### Scenario: One line in each of three reviews
- **WHEN** three review blocks each hold a `Reviews: 1` line
- **THEN** `review_count` has no candidate from them
#### Scenario: One price
- **WHEN** the main region shows one amount and a struck amount
- **THEN** `price` has the shown amount as a candidate; with two shown amounts, none
#### Scenario: Per-unit and per-period amounts
- **WHEN** the main region shows `€25/kg` beside the price, or `$25/mo`
- **THEN** neither is a `price` candidate; `€25/kg` is a user-added `unit_price` field's candidate
#### Scenario: Complete-the-look card
- **WHEN** structured data states the price `$80`, and the main region shows `$80` and one card linking to another
  product with `$20` and `Brand: Other`
- **THEN** `price` has the candidate `$80` and `brand` reads nothing from the card
#### Scenario: Related products' identifiers
- **WHEN** the main region shows `EAN: <gtin>` and a list of cards linking to other products, each with a GTIN
- **THEN** `gtin` has the page's GTIN as its one candidate; an identifier inside a link to another product is none

### Requirement: No generic DOM heuristics
Collectors SHALL contain no hostname, class fragment, phrase list or card selector; per-site selectors live only in
configs. Repeated-structure rows are read only by the item layer ([listings](../listings/spec.md)), from structure,
field types and named standards; the DOM collector reads a typed value only when the main region shows one. Price-role
exclusions are HTML Standard, CSS and CLDR rules (struck text, CLDR per patterns and units), never a phrase list.
(Previously: typed value spotting was read only by the item layer.) Refs: C2, C3, C13, owner #67, D-1643,
architecture-v3 d.2.
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

### Requirement: DOM description block
On a detail page the system SHALL propose for each `long_text` field the prose block of the page's main region
(`collect/dom_text.py`; as the structural DOM values, outside chrome, dialogs and media fallback, outside reviews
and related items marked by schema.org `review`, `isRelatedTo`, `isSimilarTo` or a Review `itemtype`, and outside
other items' cards) that states it in
full: the outermost block, with no table, form control, button, media or frame (an `img` or `picture` among its text
is phrasing content, HTML Standard §3.2.5.2.5), whose text begins with a candidate another collector proposed for
the field (or its ellipsis-cut form, white space aside), and the block equal to a value that is no summary (neither
Open Graph's nor one stating the same text) in place of that value's wider blocks; or, where it goes on further, the
element a microdata or RDFa value is stated on with the prose and headings of its following siblings (of the
outermost wrapper holding nothing after it, inside the element opening the item), up to one that is no prose or states
another property or item; else the section after a heading (a sibling holding a control besides its prose giving its
outermost prose elements), or named by `aria-label` or
`aria-labelledby`, whose words are the field's or its schema.org property's; else, for a field whose path names
`description` that only Open Graph (or nothing) states, the longest maximal prose block with no image that is not
mostly links, without its opening heading, unless it holds the page's title heading (`h1`, or an ARIA heading of level
1) or a price the structural pass read, or, beside an Open Graph summary, is no longer than it or holds at most half
of its words other than the title heading's (a summary with fewer words of its own than of the title heading only names
the item, and asks no words of the block). Blocks that differ are ambiguous: none. The candidate is `dom`, independent, in
the `dom` evidence bucket. (Previously: any image made a block no prose, an element-valued description was never
continued, and the main text was the longest block whatever it held; continuation stopped at the element's wrapper,
and a section panel holding a button gave no text.) Refs: C2, C4, D-1700, D-1701, D-1702, D-1703, D-1704. Enforced by: unit and replay tests; active.
#### Scenario: Summary and full text
- **WHEN** `og:description` is the first sentence of a paragraph block that goes on, and no other kind states a
  description
- **THEN** `description` publishes the block's text, from `dom`
#### Scenario: Labelled section
- **WHEN** a heading reads "Description" and prose follows it up to the next heading
- **THEN** that prose is a `description` candidate
#### Scenario: Not the item's own text
- **WHEN** a block that begins with the stated description sits in an `aside`, a dialog or a review
- **THEN** it is not a candidate
#### Scenario: Buy box is no main text
- **WHEN** only `og:description` states a description, and the longest prose block holds the `h1` and the price
- **THEN** no `dom` candidate is made, and the Open Graph summary publishes
#### Scenario: Description marked on its first section
- **WHEN** `itemprop="description"` marks a job's first `section`, and two sibling sections of prose follow in its item
- **THEN** the `dom` candidate is the three sections' text
