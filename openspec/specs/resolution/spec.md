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
  `backend/data/source_precedence.yaml`, fitted on dev (the first of n kinds weighs 1, each later place 1/n less, a
  kind outside the order 0); a fragment of another of the field's candidates weighs 0 (`resolve/supersede.py`: a
  `long_text` that is a prefix or ellipsis-cut prefix of a longer one, or an Open Graph description beside a longer
  one of another kind; a `text` that is another kind's value plus ` - ` or ` | ` and more text; an Open Graph list of
  images whose files are all among a longer list's of another kind). For `money` the strength of the currency
  evidence ([normalization](../normalization/spec.md) `basis`): a stated currency 1, then `page`, `locale`, `url`,
  `unknown` each 1/(number of bases + 1) less. Every other type weighs every kind 1 (no measured order).
- Scope match: 1 for the target's own values and its anchor Offer's, 0.5 for another Offer of the target or of its
  variants (Atomic offers); another item's values are not owned at all.
- Agreement: of the field's independent candidates, per source kind its best weight, summed over the kinds stating
  the value, over the sum for every kind; 1 when no candidate is independent (an admitted state value is not).
Candidates stating one value (equal after normalization; for images, renditions of one file: `resource_key`, the
authority and path without the size, conversion and options the path states, any scheme or query, an image proxy URL
naming the file its `url` parameter names, a list's as the set of its files) form a group scored by its best member; of those
members the first publishes, for images the `https` ones (else all) and of a single image's renditions the largest
(`url.largest_rendition`). The candidates of every other value are rejected `outscored`, and a field whose kept
candidates state other values publishes with the disagreement flag as its reason (`disagree`, or `offers_disagree` /
`offer_split` for an offer field). When the best score is 0 the field is `missing` (`unranked`); when two values share
it the field is a `conflict` (`disagree`, C7: decline rather than guess). Money differs in one way: an unclear
currency never drops a price (tied values stating one amount in different currencies publish that amount with its
currency `null`, basis `unknown`), but amounts that differ are rival prices, each explained by its role before the
field is refused: the one amount a rendered `dom` value states is the visible price and beats structured, meta and
data-call amounts (the disagreement is the flag `disagree`); the shown variant's Offer beats the Offers of other
variants and sellers (INV-38); a price a single Offer states that is not the anchor's is `offer_split`. List, was
and unit prices are not rivals: collectors read an Offer's own `price` (never a `priceSpecification`), and the DOM
collector skips struck text. An amount of the same role for the same variant that nothing explains leaves the field a
`conflict` (`disagree`, `offers_disagree` or `offer_split`): accuracy before coverage, and a price range is no price
unless the page states one amount for the product (a low bound is never derived from disagreeing Offers). (Previously:
a price always published, owner #68 as then read; exact-match types published only when every kept
candidate agreed, else `conflict`; money ranked by currency evidence then needed agreement, a weaker one rejected
`weaker_currency`; text, url and image published from the first source kind in the order, a disagreement within it
settled only by the first other kind naming one value; each rule had its own tie-breaks.) Refs: §10, owner #68,
owner 2026-10-19. Enforced by: `tests/property/test_preference.py`, `tests/unit/test_preference.py`; active.
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
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph weighing more than `dom`
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
The anchor's values score as the target's own and another Offer's at half (Candidate score). Where Offers state other
values an offer field publishes only the shown variant's value, else it is `conflict` `offers_disagree` (a price
also publishes when the visible price explains the difference, Candidate score). A value only another Offer than the
anchor states is `conflict` `offer_split`; a field no Offer states publishes from the target's own values (its Open
Graph, page state or text), and an `AggregateOffer` range never publishes as the price. (Previously: a price whose
Offers disagreed, or only another Offer stated, published flagged.) Refs: §10, owner #68, owner 2026-10-19; per-row and common-value rules in
[variants](../variants/spec.md). Enforced by: resolver test; active.
#### Scenario: Price and availability from two Offers
- **WHEN** Offer A states only price and Offer B states only availability
- **THEN** `availability`, which the anchor lacks, is `conflict` with reason `offer_split`
#### Scenario: Variant Offers without a price
- **WHEN** the target's only Offer states availability and no price, and its `og:price:amount` states one
- **THEN** `price` publishes the Open Graph amount and `availability` the Offer's

### Requirement: Derived values (INV-07)
Derived values SHALL fill only `missing` fields and carry `derived_by`; the only derivations are `absolutize`, then for
a detail page's `T.url` field (`T.url` in every alternative of its path) `canonical_link` (RFC 6596), then
`final_url`, each a named function (`resolve/derive.py`). (Previously: a field whose last rank was `T.url`, such as
`apply_url`, took the page URL too.) Refs: §9, §10, Appendix A #40, D-0442, D-0910, D-1625. Enforced by: resolver
tests; active.
#### Scenario: No url candidate
- **WHEN** a detail page has no url candidate and `<link rel=canonical href="https://example.com/p/1">`
- **THEN** `url` publishes that URL with `derived_by=canonical_link`, source kind `derived`, evidence `derived`
#### Scenario: No stated apply link
- **WHEN** a job page states no apply link and role C claims none
- **THEN** `apply_url` stays `missing`

### Requirement: Evidence, confidence and min_confidence
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #59; `state` for a value of the page's state JSON) and
the fitted dev confidence of its `(type, evidence)` bucket from `calibration.json`, which holds only buckets measured on
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
stores the record as `partial` and a crawl-discovered URL is `no_match` with no record. Refs: §10, §23, D-0513, D-0930.
#### Scenario: Crawl page missing price
- **WHEN** a crawl-discovered detail page leaves the required `price` missing
- **THEN** the outcome is `no_match` and no record is stored

### Requirement: Render-bound fields
A detail field still `missing` (for any reason but `out_of_stock`) whose source in the site's active config is the
browser (`ConfigExecutor.browser_fields`: until per-field sources land with architecture v3 PR 5, every field a config
learned from browser captures runs, `fetch.method` `browser`), on a page no render ran for (the capture is not the
browser's and no browser attempt is among its `fetch_policy.attempts`: the fetch did not render, for budget or
`method_hint http`), SHALL be `interaction_required` with reason `render_bound`. Every other unpublished field stays
`missing` with its furthest-stage reason; a page without a config leaves a field it does not carry `missing` with
`no_candidates`. (Previously: a field `missing/no_candidates` on an unrendered page whose document carried a state
document of at least `STATE_MIN_VALUES` scalar values, `content/state.holds_state`, was `interaction_required` with
reason `script_rendered`.) Refs: owner plan 2026-10-19 P3, P9; architecture v3 a.5.
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
The system SHALL ask role C ([llm](../llm/spec.md)) once per detail page only for missing required fields and unfilled
required groups (in `active` mode only those the config neither covers nor lists as absent, which stay `missing` with
reason `absent`); `conflict`, `abstained`, `object` and `list<object>` fields are never sent, and its candidates pass
the same stages as `llm_grounded`. Refs: §8.4, D-0489, D-0797, D-1341.

### Requirement: Nothing after resolution changes a value (INV-27)
No layer after resolution (storage, exporters, API, MCP, UI) SHALL change a published value; fixes go to extraction,
a config or an operator correction (C5). Opt-in `csv_safe` only prefixes `'` to formula-like cells. Refs: §10, D-0879.
Enforced by: a property test that exported and API values equal the stored record's, and review; active.
#### Scenario: Records API
- **WHEN** a record is read through `GET /v1/records` and the MCP server
- **THEN** each published value equals the stored record's value
