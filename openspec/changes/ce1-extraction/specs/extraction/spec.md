# Delta: extraction

## MODIFIED Requirements

### Requirement: Structured-data collectors
The system SHALL read JSON-LD (RFC 8259, `@graph`/`@id` resolved, schema.org terms only under a schema.org context,
`rdfs:subPropertyOf` for identifiers), microdata and RDFa Lite (HTML Standard item and value rules; a URL-attribute or
RDFa IRI value is a URL, never text, D-1153) and Open Graph
(one fixed table, no translation, site-default blocks skipped) through the field's `schema_org` path. A node is an
entity of every type it declares (JSON-LD 1.1 §3.5, a microdata `itemtype` list), and a text value holding element
markup is read as the fragment's rendered text. (Previously: an entity had only its most specific type; markup was
read as text.) Refs: §8.1, D-0388..D-0406, D-0940, D-1180, D-1183.
#### Scenario: gtin13 for a gtin field
- **WHEN** a Product states `gtin13` and the schema's identifier field maps `Product.gtin`
- **THEN** the `gtin13` value is a candidate for that field
#### Scenario: Two types
- **WHEN** a JSON-LD node is typed `["VideoGame", "Product"]` and states an Offer
- **THEN** the node is a Product for intent and ownership, and its Offer's price publishes
