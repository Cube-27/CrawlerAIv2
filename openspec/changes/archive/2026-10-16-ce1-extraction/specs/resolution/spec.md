# Delta: resolution

## MODIFIED Requirements

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in the type's order
in `backend/data/source_precedence.yaml` that has a valid owned candidate; unranked kinds never win, and disagreement
within the winning kind is `conflict` unless independent candidates of the first other kind in that order that names
one of its values settle it. Image values naming the same files (`resource_key`: authority and path, any scheme or
query; a list's as a multiset) are renditions and agree. (Previously: every other kind named at once; renditions
disagreed.) Refs: §10, D-0439, D-0944, D-1182.
#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph ranking before `dom`
