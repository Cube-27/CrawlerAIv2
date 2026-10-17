## MODIFIED Requirements

### Requirement: schema.org paths
`schema_org` SHALL be a dotted path from a schema.org type through properties; `+` joins a second property into one
atomic value and `|` separates up to four pooled, equal-ranked alternatives. A path's root SHALL be a type and each
step a property of the pinned schema.org vocabulary, and a `schema:` `vocab` reference an enumeration of it; a schema
a caller creates or edits that names others is refused with the error at the field (a process without the vocabulary
file checks syntax only). Refs: §5.2, D-0240, D-1374. (Previously: paths and `vocab` references were checked for
syntax only.)
#### Scenario: Five alternatives
- **WHEN** a path has five `|`-separated alternatives
- **THEN** the document is refused
#### Scenario: Unknown property
- **WHEN** a field's path is `Product.colour` and the vocabulary has no property `colour`
- **THEN** the schema is refused with an error at `fields.<name>.schema_org`
