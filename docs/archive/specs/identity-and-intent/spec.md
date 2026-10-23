# Identity and Intent Specification

## Purpose

Identity and intent decide which entity of a page a record is about: structured entities that state one thing are
merged, one primary-type entity is picked as the target, and a candidate is published for the target only when the
target owns it (`resolve/identity.py`, `intent.py`, `ownership.py`); the entity key names the record.
What then publishes and how far it is trusted is [resolution](../resolution/spec.md); where the entities come from is
[extraction](../extraction/spec.md). History: SPEC-05.

## Requirements

### Requirement: Entity identity, intent and ownership
Entities that share an IRI, when the most specific types of all entities stating it are each other's or subtypes of
one another (JSON-LD 1.1 node map generation merges node objects with one `@id`; with one unrelated pair, only those of
one most specific type), and entities of one most specific type that share an identifier value
(unless their item URLs differ) or, across collectors, an item URL other than a page URL SHALL be one entity before
intent (`resolve/identity.py`); so SHALL roots of the page's own markup, of most specific types each other's or a
subtype of one another, whose every item URL names the page's document (RFC 3986 authority and path; a relative `@id`
or `url` resolved against the page) and that state the same schema.org `name` values: each says it is the item the page is about; the merged entity holds every member's types, most specific first. The root
of an identity-checked data call's answer (acquisition spec "Data calls") SHALL be one entity with the page's single
root entity of its most specific type, and stay apart when the page states none or several; it states the product
with every variant it has, so it never joins a product group's `hasVariant` member, whichever variant's identifiers it
states as the one the page shows (adapters spec, Shopify); one of a repeated set of
microdata items (three or more elements whose XPaths differ only in one step's position: a carousel, a comparison
table) is not counted, as intent reads it as another page's item, and the root is the page's own when one of its
merged members names the page or none names another document. A page URL, by which an entity names the page, is
the request, final or canonical URL (RFC 6596) or an alternate version the page declares by language (HTML Living
Standard §4.6.7.1, `link rel="alternate"` with `hreflang`): a translation or regional version of the page is the
same document.
`select_target` SHALL pick one primary-type entity (`resolve/intent.py`) or none, which makes every field
`conflict`/`intent_ambiguous`; a detail page's related items and its product's group do not make intent ambiguous
(D-1151), nor does the item a primary entity's review or rating names (`itemReviewed`), which is that entity;
candidates the target does not own are rejected `not_owned`. An `array_row` entity's candidates are the
target's only where page values are, when that row and every row enclosing it names a page URL or the target's URL
(`resolve/ownership.py`). An AggregateRating a detail page states apart from its item (schema.org `aggregateRating`:
a sibling node, a review widget's own microdata item, one no entity of the path's root type holds as its
`aggregateRating`; `collect/schema_org_map.py` reads the field's path through it from that node) SHALL be the
target's only when the target is the page's one primary-type entity, holds no `aggregateRating` of its own, and every
such rating on the page (standing alone, or within the target but in no Offer: an Offer's seller rates itself) states
the same values; else its candidates stay `not_owned` (owner 2026-10-22, OD-4). Refs: §8.2 rule 3, Appendix A #55, D-0413, D-0785, D-0942, D-1151, D-1253, D-1255, D-1290,
D-1291, D-1379.
#### Scenario: Related item's price in state
- **WHEN** a detail page's state holds an array of two items, the related one with its own URL and a visible price
- **THEN** that price is rejected `not_owned`, and a row naming the page URL keeps its price as the target's
#### Scenario: A review widget's rating beside the product
- **WHEN** a detail page states one JSON-LD Product without a rating and, elsewhere, a microdata AggregateRating item
  in no other item
- **THEN** its `ratingValue` is the Product's rating; with a second Product, or a second such rating stating other
  values, or the AggregateRating in an Organization node, it is `not_owned`
#### Scenario: One product in two syntaxes
- **WHEN** a JSON-LD Product and a microdata Product state one sku, and only the microdata one states an Offer
- **THEN** they are one target, its title `agreed`, and the Offer's price publishes
#### Scenario: Product markup and its platform product JSON
- **WHEN** a detail page's JSON-LD Product has no identifier and its identity-checked Shopify product JSON states the
  sku and price on its variants
- **THEN** the page has one target, owning the JSON-LD description and the JSON's price and variant sku
#### Scenario: Product markup naming the page's regional version
- **WHEN** a detail page's only JSON-LD Product states its `url` on another host, which the page declares as its
  alternate by `hreflang`, and an identity-checked product JSON names the page
- **THEN** the two are one target, and the JSON-LD Offer's availability publishes
#### Scenario: A comparison table beside the page's product
- **WHEN** a detail page states a JSON-LD Product, its identity-checked product JSON, and a comparison table of
  microdata Products, the first of which names the page URL
- **THEN** the JSON joins the JSON-LD Product, which is the target, and intent is not ambiguous
#### Scenario: A product group and a product under one IRI
- **WHEN** a JSON-LD ProductGroup and a separate JSON-LD Product with an `aggregateRating` state one `@id`
- **THEN** they are one target, which owns the rating; a WebPage, an Organization and a Thing under one `@id` stay apart
#### Scenario: One product stated twice by the page
- **WHEN** a detail page states a JSON-LD ProductGroup with a relative `@id` and `url` and a separate JSON-LD Product with
  the page's absolute `url`, both of one `name`, and a WebPage of that name
- **THEN** the group and the product are one target and intent is not ambiguous; the WebPage stays apart
#### Scenario: A product's rating names the product
- **WHEN** a Product's `aggregateRating` holds an `itemReviewed` Product naming the page URL
- **THEN** the outer Product is the target and intent is not ambiguous

### Requirement: Entity key
`entity_key` SHALL be the hex sha256 of `site_id` + the task's canonical URL; a listing row uses its `T.url`, else
`<task canonical URL>#<row position>`. Refs: D-0459, D-0512.
