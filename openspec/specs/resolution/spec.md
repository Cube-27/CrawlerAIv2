# Resolution Specification

## Purpose

Resolution decides, per schema field of a page, what publishes from [extraction](../extraction/spec.md)'s candidates
and how far it is trusted, and builds the record with per-field metadata and the page outcome (`resolve/`).

## Requirements

### Requirement: One extraction path
The system SHALL resolve every page through `extract_page`, used by the worker, `scrape` and replays alike; an
exception yields outcome `error` (stored `failed`) with no fields and no record. Refs: §8.1, D-0483, D-0506.

### Requirement: Candidate validity
Every candidate SHALL pass its type normalizer ([normalization](../normalization/spec.md)), else it is
rejected `invalid`/`ambiguous`. Which entity a candidate belongs to is
[identity-and-intent](../identity-and-intent/spec.md). Refs: §8.2, D-1379.

### Requirement: Candidate score (INV-14)
Every field SHALL publish the value of its best-scored kept candidate (valid, owned, not a request-URL value), one
mechanism for every type (`resolve/score.py`, `resolve/preference.py`). A candidate's score is its source weight times
its scope match times its value's agreement:
- Source weight: for `text`, `long_text`, `url` and `image_url` the kind's place in the type's order in
  `backend/data/source_precedence.yaml`, frozen fitted data ([evaluation](../evaluation/spec.md); the first of n kinds weighs 1, each later place 1/n less, a
  kind outside the order 0); a fragment of another of the field's candidates weighs 0 (`resolve/supersede.py`: a
  `long_text` that is a strict prefix or ellipsis-cut prefix of a longer one (white space aside; one equal to it but for white space is no cut), an Open Graph description, or a value of
  another kind stating the same text as it, beside a longer one of a kind other than Open Graph, or one that states
  another's text with fewer line breaks, white space aside (its paragraphs and line breaks flattened), or that is a
  first line, then the start of a longer one, white space aside (a section's heading kept as text); a `text` that is
  another kind's value plus ` - ` or ` | ` and more text; a list of
  images, of any kind, whose files (`same_file`: a file or a rendition of it) are all among a longer list's of another
  kind, for an Open Graph list its first file only (Open Graph "Arrays": the first is preferred; a site default after it
  is no view) (Previously: an Open Graph list only; files compared by `resource_key`, every Open Graph file)). For `money` the strength of the currency
  evidence ([normalization](../normalization/spec.md) `basis`): a stated currency 1, then `page`, `locale`, `url`,
  `unknown` each 1/(number of bases + 1) less. Every other type weighs every kind 1 (no measured order).
- Scope match: 1 for the target's own values and its anchor Offer's, 0.5 for another Offer of the target or of its
  variants (Atomic offers); another item's values are not owned at all.
- Agreement: of the field's independent candidates, per source kind its best weight, summed over the kinds stating
  the value, over the sum for every kind; 1 when no candidate is independent (an admitted state value is not).
Candidates stating one value (equal after normalization; for images, renditions of one file: `resource_key`, the
authority and path without the size, conversion and options the path states, any scheme or query (a `%3F` written
into the path ends the file's name), an image proxy URL naming the file its `url` parameter names, a list's as the set
of its files) form a group scored by its best member; of those members the first publishes, for images the `https` ones
(else all), with each file at the largest rendition any member states (`images.preferred_rendition`): a single image
publishes the member stating it, a list the first member's files, in its order, each at its largest rendition wherever
another member lists it. Image values that tie for the best score as items of one list of one node publish its first
item (an array is ordered, RFC 8259 §1). The candidates of every other value are rejected `outscored`, and a field whose
kept candidates state other values publishes with the disagreement flag as its reason (`disagree`, or `offers_disagree`
/ `offer_split` for an offer field). A list of the item's facts (its items neither lists, objects, urls nor images: a
job's places) publishes instead every member its values scoring above 0 state, the best value's first: two sources stating
different members state more of the item, not rival values. A member equal to one already listed is that one, and a
location the page writes as text alone that names a listed place's locality (its region when it states none: "Austin"
or "Raleigh; Austin; Denver" for `addressLocality` Austin) stands for it, in its place; no value is outscored and no
flag is set. (Previously: a list was one value, and different lists were rivals.) When the best score is 0 the field is `missing` (`unranked`); when two values share
it the field is a `conflict` (`disagree`, C7: decline rather than guess). Money differs in one way: an unclear
currency never drops a price (tied values stating one amount in different currencies publish that amount with its
currency `null`, basis `unknown`), but amounts that differ are rival prices, each explained by its role before the
field is refused: the one amount a rendered `dom` value states on its own evidence is the visible price and beats
structured, meta and data-call amounts (the disagreement is the flag `disagree`; it is the page offer's, never a
variant row's, variants spec); the shown variant's Offer beats the Offers of other
variants and sellers (INV-38); a price a single Offer states that is not the anchor's is `offer_split`. List, was,
member and unit prices are not rivals: a money field's path predicates give it its price role (schemas spec,
"Presets"), so the active price reads an Offer's `price` and its `priceSpecification` without a `priceType`,
`validForMemberTier` or `referenceQuantity`, and collectors read struck, per-unit and per-period text only for the
fields of those roles (extraction spec, "Structural DOM values"). A `dom` amount of an active-price field equal to a
bound of a stated price range (an AggregateOffer's `lowPrice` or `highPrice`, the two bounds differing; in the range's
currency, or either currency unknown) is that range's bound, rejected `range_bound`; a user-added `price_range` publishes the range. An amount of the same role for the same variant that nothing explains leaves the field a
`conflict` (`disagree`, `offers_disagree` or `offer_split`): accuracy before coverage, and a price range is no price
unless the page states one amount for the product (a low bound is never derived from disagreeing Offers). (Previously:
collectors read an Offer's own `price` only, never a `priceSpecification`, and a visible range bound was a price
candidate; a price always published, owner #68 as then read; exact-match types published only when every kept
candidate agreed, else `conflict`; money ranked by currency evidence then needed agreement, a weaker one rejected
`weaker_currency`; text, url and image published from the first source kind in the order, a disagreement within it
settled only by the first other kind naming one value; each rule had its own tie-breaks.) Refs: §10, owner #68,
owner 2026-10-19, architecture-v3 d.2. Enforced by: `tests/property/test_preference.py`,
`tests/unit/test_preference.py`; active.
#### Scenario: A visible range bound
- **WHEN** JSON-LD states an AggregateOffer from 80 to 120 EUR and no Offer price, and the page shows `€80`
- **THEN** `price` is `missing`, the `dom` candidate rejected `range_bound`, and a user-added `price_range` publishes
  80–120 EUR
#### Scenario: Places from structured data and the page
- **WHEN** JSON-LD states a job's place `Brooklyn, New York, USA` (locality Brooklyn) and the page shows `New York City`
- **THEN** `locations` publishes both, `Brooklyn, New York, USA` then `New York City`
#### Scenario: Two prices disagree
- **WHEN** JSON-LD says 19.90 EUR and microdata says 21.00 EUR for the target
- **THEN** `price` publishes 19.90 EUR with reason `disagree` and the microdata candidate is rejected `outscored`
  (Previously: `conflict` with no value.)
#### Scenario: Two sources against one
- **WHEN** JSON-LD and microdata say 19.90 EUR and a DOM text says 21.00 EUR
- **THEN** `price` publishes 19.90 EUR with reason `disagree`
#### Scenario: Unknown currency beside a stated one
- **WHEN** JSON-LD says 19.90 USD and a DOM text says `$21.00` that no evidence settles
- **THEN** `price` publishes 19.90 USD and the DOM candidate is rejected `outscored` (Previously: `weaker_currency`.)
#### Scenario: One amount in two currencies
- **WHEN** JSON-LD says 19.90 EUR and a DOM text says `19.90 USD`
- **THEN** `price` publishes 19.90 with currency `null` and basis `unknown`
#### Scenario: Two skus
- **WHEN** JSON-LD says sku A-1 and microdata says sku A-2 for the target
- **THEN** `sku` is `conflict` with reason `disagree`
#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL
#### Scenario: A main image beside the gallery
- **WHEN** JSON-LD `Product.image` states one image and the page's `dom` gallery lists it and four other views
- **THEN** the list of images publishes the gallery's five, the JSON-LD list weighing 0
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph weighing more than `dom`
#### Scenario: A thumbnail in the markup
- **WHEN** microdata states an image at `?sw=71`, Open Graph at `?sw=406` and a `dom` image at `?sw=964`
- **THEN** `image_url` publishes the `?sw=964` URL
#### Scenario: A data call's image list
- **WHEN** the only image candidates are the items of one product JSON `images` list, scoring alike
- **THEN** `image_url` publishes its first item
#### Scenario: An http twin
- **WHEN** two merged JSON-LD blocks state one image over `http` and over `https?w=800`
- **THEN** `image_url` publishes the `https` URL
#### Scenario: A proxied image
- **WHEN** JSON-LD states an image's CDN URL and Open Graph and `dom` state an image proxy URL naming it in its `url`
  parameter
- **THEN** they are one value and `image_url` publishes the JSON-LD URL
#### Scenario: A truncated description
- **WHEN** JSON-LD states a description cut at 250 characters and `dom` states the full text
- **THEN** `description` publishes the full text
#### Scenario: A state value beside a page value
- **WHEN** a `title` has a state value and a `dom` value that differ
- **THEN** `title` publishes the `dom` value with reason `disagree`, and a state value alone publishes

### Requirement: Missing reasons name the furthest stage
An unpublished field SHALL state its status and reason (the furthest screening stage reached, or the conflict or
abstain cause, per `resolve/types.py`), and a published one whose candidates disagree its flag (Candidate score);
every rejected candidate keeps its own reason, in `field_meta`. (Previously: a published field had no reason.) Refs: SPEC-05 §4.2, D-0438, D-0533.

### Requirement: Atomic offers (INV-15)
Price, currency and availability SHALL come from one anchor Offer: the Offer of the variant the target shows (Shown
variant, [variants](../variants/spec.md)), else the one holding values for the most offer fields, the first on a tie.
On a detail page a source (a collector; each adapter and each JSON-LD block a source of its own, a block being one
document, JSON-LD 1.1 §7.1) that states one Offer alone for the target
states the item's offer, the shown variant's (Shown variant), unless that source's Offer is already named by the
target's sku or gtin; a source listing several states which is shown by its sku or gtin. (Previously: only when every
source stated one Offer each; all JSON-LD blocks were one source.)
The anchor's values score as the target's own and another Offer's at half (Candidate score). Where Offers state other
values an offer field publishes only the shown variant's value, else it is `conflict` `offers_disagree` (a price
also publishes when the visible price explains the difference, Candidate score). A value only another Offer than the
anchor states is `conflict` `offer_split`; a field no Offer states publishes from the target's own values (its Open
Graph, page state or text), and an `AggregateOffer` range never publishes as the price. An Offer's values are the item's
it offers through any Offers between them (schema.org `offers`: an AggregateOffer's `offers` offer its item).
(Previously: a price whose Offers disagreed, or only another Offer stated, published flagged; an Offer inside an
AggregateOffer was no item's.) Refs: §10, owner #68, owner 2026-10-19; per-row and common-value rules in
[variants](../variants/spec.md). Enforced by: resolver test; active.
#### Scenario: Offers inside an AggregateOffer
- **WHEN** a listed Product's `offers` is an AggregateOffer whose one Offer states 9.50 EUR
- **THEN** the row's price is 9.50 EUR
#### Scenario: Price and availability from two Offers
- **WHEN** Offer A states only price and Offer B states only availability
- **THEN** `availability`, which the anchor lacks, is `conflict` with reason `offer_split`
#### Scenario: One Offer from each source
- **WHEN** the JSON-LD Product's one Offer states `PreOrder` and the microdata Product's one Offer states its sku, gtin
  and price
- **THEN** `availability` publishes `PreOrder`
#### Scenario: One Offer beside a list of variants
- **WHEN** the JSON-LD Product's one Offer states `InStock`, and the microdata Product's Offers list each variant,
  the one of the Product's sku stating no availability and another `OutOfStock`
- **THEN** `availability` publishes `InStock` with reason `offers_disagree`
#### Scenario: Variant Offers without a price
- **WHEN** the target's only Offer states availability and no price, and its `og:price:amount` states one
- **THEN** `price` publishes the Open Graph amount and `availability` the Offer's

### Requirement: Derived values (INV-07)
Derived values SHALL fill only `missing` fields and carry `derived_by`; the only derivations are `absolutize`, then for
a detail page's `T.url` field (`T.url` in every alternative of its path) `canonical_link` (RFC 6596), then
`final_url`, each a named function (`resolve/derive.py`). Canonical links naming more than one URL designate none
(RFC 6596 §3: one per resource), so such a page states no canonical URL. Before derivation, when the canonical link and
the final URL are one URL, a kept candidate of that `T.url` field naming another document (`normalize/url_key.py` `document_key`:
another scheme, authority or path, one trailing slash of the path aside; a query or a fragment alone names none) is
rejected `other_document`, and preference decides among the rest; a relative
reference `absolutize` resolves to another document is rejected so too. A derived value publishes as the page states it
(normalization spec): an absolutized reference as written, the canonical link as its first `href` is written; the final
URL, which no page statement gives, as fetched. (Previously: a field
the page stated on its other scheme or with userinfo was its own document, and `/p` and `/p/` named one document here
but two in candidate scope (`collect/scope.py`); a field
whose last rank was `T.url`, such as `apply_url`, took the page URL too; a structured `url` built from another id than
the page's outranked its canonical URL; the first of conflicting canonical links named the page.) Refs: §9, §10, Appendix A #40, D-0442, D-0910, D-1625. Enforced by: resolver
tests; active.
#### Scenario: No url candidate
- **WHEN** a detail page has no url candidate and `<link rel=canonical href="https://example.com/p/1">`
- **THEN** `url` publishes that URL with `derived_by=canonical_link`, source kind `derived`, evidence `derived`
#### Scenario: Conflicting canonical links
- **WHEN** a detail page's first canonical link repeats its final URL with a tracking query, its second names another
  path, and its JSON-LD Product `url` is that path
- **THEN** the page states no canonical URL, and `url` publishes the JSON-LD `url`, not rejected `other_document`
#### Scenario: Structured url of another document
- **WHEN** a detail page's canonical link and final URL are `https://example.com/p-188.html` and its JSON-LD Product
  `url` is `https://example.com/p-759.html`
- **THEN** `url` publishes `https://example.com/p-188.html` (`og:url` when it states it, else `derived_by=canonical_link`),
  the JSON-LD candidate rejected `other_document`
#### Scenario: No stated apply link
- **WHEN** a job page states no apply link and role C claims none
- **THEN** `apply_url` stays `missing`

### Requirement: Evidence, confidence and min_confidence
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #59; `state` for a value of the page's state JSON) and
the fitted confidence of its `(type, evidence)` bucket from `calibration.json`, which holds only buckets measured on
at least 20 labelled values (the others are uncalibrated, `calibrated=false`). A money value whose currency only the
locale or the URL settles, or nothing settles (`basis` `locale`, `url`, `unknown`), is measured apart, in bucket
`money|<evidence>|<basis>`, for its lower confidence (owner #68, owner 2026-10-19); every published field notes its `basis` in `field_meta` when it has one. Every
chosen value publishes with that
confidence unless the request sets `min_confidence` and the bucket is calibrated below it: the field is then
`abstained` with reason `below_min_confidence`. An uncalibrated bucket never abstains. (Previously: a calibrated bucket
below τ, 0.97 required and 0.95 otherwise, abstained `below_tau`; a lone `js_state` value had no bucket.)
Refs: §10, §16.3, D-0455, D-0456, D-1316, D-1740, D-1770, D-1771, D-1773.
#### Scenario: Calibrated bucket below the minimum
- **WHEN** a money bucket has n=40 and precision 0.9 and the request sets `min_confidence` 0.95
- **THEN** the field is `abstained` with reason `below_min_confidence`, and with no `min_confidence` it publishes with
  confidence 0.9 and `calibrated=true`
#### Scenario: Bucket below the floor
- **WHEN** a bucket has n=19 and the request sets `min_confidence` 0.99
- **THEN** the field publishes with `calibrated=false`
#### Scenario: Value of a captured call
- **WHEN** a field's only candidate is a visible price read from a captured call
- **THEN** it publishes with evidence `network`, uncalibrated while that bucket is below the floor
#### Scenario: Value of state JSON
- **WHEN** a field's only candidate is a value read at a key the item layer proved
- **THEN** it publishes with evidence `state`

### Requirement: Record confidence
Record confidence SHALL be the minimum over published required fields and required-group members, null when any is
uncalibrated; a listing's records carry their least confident row's. Refs: §10, D-0456, D-0931.

### Requirement: Provenance on every field (INV-22)
Every candidate SHALL carry a locator and `field_meta` SHALL hold status and reason for every schema field, plus
`evidence`, `confidence`, `calibrated`, `source_kind` and `locator` for every published one; `record.data` holds
published values only. Refs: §6, §13.1, D-0354. Enforced by: Pydantic models and tests; active.
#### Scenario: Unpublished field metadata
- **WHEN** `brand` has no candidates
- **THEN** `field_meta.brand` has status `missing` and reason `no_candidates`, and `record.data` has no `brand`

### Requirement: Incomplete pages
A page whose required fields and groups all publish SHALL be `extracted` and complete; otherwise a caller-supplied URL
stores the record as `partial` and a crawl-discovered URL is `no_match` with no record. Either way, a page none of whose
required fields or group members (any field, for a schema that requires none) has a candidate read from the page,
published or rejected by resolution, beyond its own address (a field whose value is the `canonical_link` or
`final_url` derivation), states no entity of the schema and is `no_match` with no record: a maintenance or error page
served for the URL states prose, never what identifies the item. An extraction miss is never `no_match`: a needed
field's candidate that resolution rejected, or a page whose content the engine cannot read (its extraction raises the
`closed_shadow_root` or `obfuscated_text` signal, [jobs](../jobs/spec.md) "Job outcome summary"), keeps a
caller-supplied page's record, `partial`, its fields' reasons as they resolved (`no_candidates` on an HTTP capture is
the summary's render hint). A listing's row states its item only by a row field (the needed row fields, else any row
field), never by the page fields every row shares. (Previously: a caller-supplied URL kept such a record, even an
empty one; then a page with no published needed field was `no_match`, its rejected candidates and unreadable content
included.) Refs: §10, §23, D-0513, D-0930.
#### Scenario: Crawl page missing price
- **WHEN** a crawl-discovered detail page leaves the required `price` missing
- **THEN** the outcome is `no_match` and no record is stored
#### Scenario: Maintenance page for a caller-supplied URL
- **WHEN** a batch or scrape URL redirects to a maintenance page whose only published values are its prose as `description` and
  its final URL as `url`
- **THEN** the outcome is `no_match` and no record is stored
#### Scenario: Content in a closed shadow root
- **WHEN** a scrape URL's page holds a custom element with no light DOM and no needed field has a candidate
- **THEN** the outcome is `partial` with a record whose fields are `missing` with `no_candidates`

### Requirement: Render-bound fields
A detail field still `missing` (for any reason but `out_of_stock`) whose source in the site's active config is the
browser (`ConfigExecutor.browser_fields`: each running field whose `needs` is `browser`, [learning-configs](../learning-configs/spec.md)
"Locate run"), on a page no render ran for (the capture is not the
browser's and no browser attempt is among its `fetch_policy.attempts`: the fetch did not render, for budget or
`method_hint http`), SHALL be `interaction_required` with reason `render_bound`. Every other unpublished field stays
`missing` with its furthest-stage reason; a page without a config leaves a field it does not carry `missing` with
`no_candidates`. (Previously: a field `missing/no_candidates` on an unrendered page whose document carried a state
document of at least `STATE_MIN_VALUES` scalar values, `content/state.holds_state`, was `interaction_required` with
reason `script_rendered`; then every field of a config whose `fetch.method` was `browser` was browser-bound.) Refs: owner plan 2026-10-19 P3, P9; architecture v3 a.5.
#### Scenario: Browser field on an HTTP page
- **WHEN** the site's config reads `size` from rendered pages and an HTTP page with no browser attempt carries no `size`
- **THEN** `size` is `interaction_required` with reason `render_bound`, and the same page captured in the browser leaves
  it `missing`
#### Scenario: No config
- **WHEN** an HTTP detail page of a site without a config carries no candidate for `size`
- **THEN** `size` is `missing` with reason `no_candidates`

### Requirement: Out of stock without a price
A money field whose `schema_org` names `price`, left `missing` for want of a candidate on a page whose published
availability (an enum of `schema:ItemAvailability`) is `OutOfStock`, `SoldOut` or `Discontinued` (schema.org: nothing
can be bought), SHALL keep reason `out_of_stock` instead of `no_candidates`, and the field is not
`interaction_required`. Nothing is published for it. Refs: owner plan 2026-10-19 P9.
#### Scenario: Sold out
- **WHEN** a detail page states `SoldOut` and no price
- **THEN** `price` is `missing` with reason `out_of_stock`, and the page is `partial`

### Requirement: LLM gap hook
The system SHALL ask role C ([llm](../llm/spec.md)) in one call per detail page for every field still `missing` after
deterministic resolution, optional ones included (in `active` mode only those the config neither covers nor lists as
absent, which stay `missing` with reason `absent`), reading the product's own evidence only ([llm](../llm/spec.md)
"Role C input, claims and candidates"); `conflict`, `abstained`, `object` and `list<object>` fields are never sent, and
its candidates pass the same stages as `llm_grounded`. A field whose claimed value the evidence does not hold (INV-12)
stays `missing` with reason `unverified`, never published. (Previously: only missing required fields and groups were
asked, and an ungrounded field's reason was `no_candidates`.) Refs: §8.4, D-0489, D-0797, D-1341.
#### Scenario: Value the page does not hold
- **WHEN** role C claims `price` `$19` and the product's text holds no `$19`
- **THEN** `price` stays `missing` with reason `unverified`

### Requirement: Nothing after resolution changes a value (INV-27)
No layer after resolution (storage, exporters, API, MCP, UI) SHALL change a published value; fixes go to extraction,
a config or an operator correction (C5). Opt-in `csv_safe` only prefixes `'` to formula-like cells. Refs: §10, D-0879.
Enforced by: a property test that exported and API values equal the stored record's, and review; active.
#### Scenario: Records API
- **WHEN** a record is read through `GET /v1/records` and the MCP server
- **THEN** each published value equals the stored record's value
