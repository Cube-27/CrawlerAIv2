## MODIFIED Requirements

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in the type's order
in `backend/data/source_precedence.yaml` that has a valid owned candidate; unranked kinds never win, and disagreement
within the winning kind is `conflict` unless independent candidates of the first other kind in that order that names
one of its values settle it. A candidate that is a fragment of another of the field's candidates ranks nowhere
(`resolve/supersede.py`): a `long_text` that is a prefix or ellipsis-cut prefix of a longer one, or an Open Graph
description beside a longer one of another kind; a `text` that is another kind's value plus ` - ` or ` | ` and more
text. Image values naming the same files (`resource_key`: authority and path without the size, conversion and options the path states, any scheme or query; a list's as the set of its files) are renditions: they agree, and of renditions the first whose URLs are all
`https` publishes. (Previously: no fragment rule; the key kept a stated size.) Refs: §10, D-0439, D-0944, D-1182,
D-1292, D-1660. Enforced by: resolver tests; active.
#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph ranking before `dom`
#### Scenario: An http twin
- **WHEN** two merged JSON-LD blocks state one image over `http` and over `https?w=800`
- **THEN** `image_url` publishes the `https` URL
#### Scenario: A truncated description
- **WHEN** JSON-LD states a description cut at 250 characters and `dom` states the full text
- **THEN** `description` publishes the full text
