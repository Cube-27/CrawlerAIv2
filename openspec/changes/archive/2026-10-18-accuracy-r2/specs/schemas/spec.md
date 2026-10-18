## MODIFIED Requirements

### Requirement: schema.org paths
`schema_org` SHALL be a dotted path from a schema.org type through properties; `+` joins a second property into one
atomic value, `|` separates pooled alternatives and `>` ranks them (those after it are read on an entity only where
those before it reach no value), up to four alternatives in all. A path's root SHALL be a type and each step a
property of the pinned schema.org vocabulary, and a `schema:` `vocab` reference an enumeration of it; a schema a
caller creates or edits that names others is refused with the error at the field (a process without the vocabulary
file checks syntax only). `job_detail.apply_url` is `JobPosting.potentialAction.target>JobPosting.url`. Refs: §5.2,
D-0240, D-1374, D-1493. (Previously: alternatives were equal-ranked only, and `apply_url` was `JobPosting.url`.)
#### Scenario: Five alternatives
- **WHEN** a path has five `|`- or `>`-separated alternatives
- **THEN** the document is refused
#### Scenario: Unknown property
- **WHEN** a field's path is `Product.colour` and the vocabulary has no property `colour`
- **THEN** the schema is refused with an error at `fields.<name>.schema_org`
#### Scenario: Stated apply link
- **WHEN** a JobPosting states a `potentialAction` with a `target` and a `url`
- **THEN** `apply_url` publishes the target, without a conflict; without the action, the `url`
