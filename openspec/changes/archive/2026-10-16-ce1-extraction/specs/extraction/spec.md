# Delta: extraction

## MODIFIED Requirements

### Requirement: Structured-data collectors
The system SHALL read JSON-LD (RFC 8259, `@graph`/`@id` resolved, schema.org terms only under a schema.org context,
`rdfs:subPropertyOf` for identifiers), microdata and RDFa Lite (HTML Standard item and value rules; a URL-attribute or
RDFa IRI value is a URL, never text, D-1153) and Open Graph
(one fixed table of OGP-defined properties: basic and optional metadata, `og:description` filling a long_text
description, and the `product:` namespace; no translation, site-default blocks skipped) through the field's
`schema_org` path; a property no published standard defines is left to learned configs (owner, Appendix A #48). A
node is an entity of every type it declares (JSON-LD 1.1 §3.5, a microdata `itemtype` list), and a text value holding
element markup is read as the fragment's rendered text. (Previously: an entity had only its most specific type;
markup was read as text; no `og:description`.) Refs: §8.1, D-0388..D-0406, D-0940, D-1180, D-1183, D-1186.
#### Scenario: gtin13 for a gtin field
- **WHEN** a Product states `gtin13` and the schema's identifier field maps `Product.gtin`
- **THEN** the `gtin13` value is a candidate for that field
#### Scenario: Two types
- **WHEN** a JSON-LD node is typed `["VideoGame", "Product"]` and states an Offer
- **THEN** the node is a Product for intent and ownership, and its Offer's price publishes
#### Scenario: og:description
- **WHEN** a page states only `og:description` for its product
- **THEN** that text is the `description` candidate, ranked behind JSON-LD and microdata
