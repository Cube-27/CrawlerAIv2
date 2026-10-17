## MODIFIED Requirements

### Requirement: Validity, intent and ownership
Every candidate SHALL pass its type normalizer ([normalization](../normalization/spec.md)), else it is rejected
`invalid`/`ambiguous`. Entities of one most specific type that share an IRI, an identifier value (unless their item
URLs differ) or, across collectors, an item URL other than a page URL are one entity before intent
(`resolve/identity.py`). `select_target` picks one primary-type entity (`resolve/intent.py`) or none, which makes every
field `conflict`/`intent_ambiguous`; a detail page's related items and its product's group do not make intent
ambiguous (D-1151); candidates the target does not own are rejected `not_owned`. An `array_row` entity's candidates
are the target's only where page values are, when that row and every row enclosing it names a page URL or the
target's URL (`resolve/ownership.py`). Refs: §8.2 rule 3, Appendix A #55, D-0413, D-0785, D-0942, D-1151, D-1253,
D-1255, D-1290, D-1291.
(Previously: only the JSON-LD collector merged root nodes of one identity, keeping the first node of each value.)
#### Scenario: Related item's price in state
- **WHEN** a detail page's state holds an array of two items, the related one with its own URL and a visible price
- **THEN** that price is rejected `not_owned`, and a row naming the page URL keeps its price as the target's
#### Scenario: One product in two syntaxes
- **WHEN** a JSON-LD Product and a microdata Product state one sku, and only the microdata one states an Offer
- **THEN** they are one target, its title `agreed`, and the Offer's price publishes

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in the type's order
in `backend/data/source_precedence.yaml` that has a valid owned candidate; unranked kinds never win, and disagreement
within the winning kind is `conflict` unless independent candidates of the first other kind in that order that names
one of its values settle it. Image values naming the same files (`resource_key`: authority and path, any scheme or
query; a list's as the set of its files) are renditions: they agree, and of renditions the first whose URLs are all
`https` publishes. Refs: §10, D-0439, D-0944, D-1182, D-1292.
(Previously: a list's files compared as a multiset, the first rendition published, and another kind's rendition did
not count as agreeing.)
#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph ranking before `dom`
#### Scenario: An http twin
- **WHEN** two merged JSON-LD blocks state one image over `http` and over `https?w=800`
- **THEN** `image_url` publishes the `https` URL
