## MODIFIED Requirements

### Requirement: Evidence, confidence and min_confidence
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #59; `state` for a value of the page's state JSON) and
the fitted dev confidence of its `(type, evidence)` bucket from `calibration.json`, which holds only buckets measured on
at least 20 labelled values (the others are uncalibrated, `calibrated=false`). Every chosen value publishes with that
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

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in the type's order
in `backend/data/source_precedence.yaml` that has a valid owned candidate; unranked kinds never win, and disagreement
within the winning kind is `conflict` unless independent candidates of the first other kind in that order that names
one of its values settle it. A candidate that is a fragment of another of the field's candidates ranks nowhere
(`resolve/supersede.py`): a `long_text` that is a prefix or ellipsis-cut prefix of a longer one, or an Open Graph
description beside a longer one of another kind; a `text` that is another kind's value plus ` - ` or ` | ` and more
text. Image values naming the same files (`resource_key`: authority and path without the size, conversion and options the path states, any scheme or query; a list's as the set of its files) are renditions: they agree, and of renditions the first whose URLs are all
`https` publishes. A value of the page's state JSON (`js_state`) ranks after every other kind. (Previously: no `js_state` rank; no fragment rule; the key kept a stated size.) Refs: §10, D-0439, D-0944, D-1182,
D-1292, D-1660, D-1773. Enforced by: resolver tests; active.
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
#### Scenario: A state value beside a page value
- **WHEN** a `title` has a state value and a `dom` value that differ
- **THEN** `title` publishes the `dom` value, and a state value alone publishes
