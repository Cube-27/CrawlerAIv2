# Identity and Intent Specification

## Purpose

Identity and intent decide which entity of a page a record is about: structured entities that state one thing are
merged, one primary-type entity is picked as the target, and a candidate is published for the target only when the
target owns it (`resolve/identity.py`, `intent.py`, `ownership.py`); the entity key names the record.
What then publishes and how far it is trusted is [resolution](../resolution/spec.md); where the entities come from is
[extraction](../extraction/spec.md). History: SPEC-05.

## Requirements

### Requirement: Entity identity, intent and ownership
Entities of one most specific type that share an IRI, an identifier value (unless their item URLs differ) or, across
collectors, an item URL other than a page URL SHALL be one entity before intent (`resolve/identity.py`). The root
of an identity-checked data call's answer (acquisition spec "Data calls") SHALL be one entity with the page's single
root entity of its most specific type, and stay apart when the page states none or several.
`select_target` SHALL pick one primary-type entity (`resolve/intent.py`) or none, which makes every field
`conflict`/`intent_ambiguous`; a detail page's related items and its product's group do not make intent ambiguous
(D-1151), nor does the item a primary entity's review or rating names (`itemReviewed`), which is that entity;
candidates the target does not own are rejected `not_owned`. An `array_row` entity's candidates are the
target's only where page values are, when that row and every row enclosing it names a page URL or the target's URL
(`resolve/ownership.py`). Refs: §8.2 rule 3, Appendix A #55, D-0413, D-0785, D-0942, D-1151, D-1253, D-1255, D-1290,
D-1291, D-1379.
#### Scenario: Related item's price in state
- **WHEN** a detail page's state holds an array of two items, the related one with its own URL and a visible price
- **THEN** that price is rejected `not_owned`, and a row naming the page URL keeps its price as the target's
#### Scenario: One product in two syntaxes
- **WHEN** a JSON-LD Product and a microdata Product state one sku, and only the microdata one states an Offer
- **THEN** they are one target, its title `agreed`, and the Offer's price publishes
#### Scenario: Product markup and its platform product JSON
- **WHEN** a detail page's JSON-LD Product has no identifier and its identity-checked Shopify product JSON states the
  sku and price on its variants
- **THEN** the page has one target, owning the JSON-LD description and the JSON's price and variant sku
#### Scenario: A product's rating names the product
- **WHEN** a Product's `aggregateRating` holds an `itemReviewed` Product naming the page URL
- **THEN** the outer Product is the target and intent is not ambiguous

### Requirement: Entity key
`entity_key` SHALL be the hex sha256 of `site_id` + the task's canonical URL; a listing row uses its `T.url`, else
`<task canonical URL>#<row position>`. Refs: D-0459, D-0512.
