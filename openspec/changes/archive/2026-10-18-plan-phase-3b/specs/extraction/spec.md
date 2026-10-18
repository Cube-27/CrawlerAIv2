## MODIFIED Requirements

### Requirement: Structural DOM values
On a detail page the system SHALL take label–value pairs from the page's main region (`main`, else the one
`role=main`, else the one `article`, else the body) outside chrome, dialogs and media fallback: two-cell `tr` rows, `dl`
groups, elements starting with `Label:` and sibling containers of one shape (two or more) holding a label element and a
value element, whose label's words equal the field's or its schema.org property's name; lines and sibling pairs that
give a field several values are dropped. It SHALL also take a money or check-digit identifier field's one shown value
in the main region (`collect/items/spot.py`; none when several differ), and the main image of the one
`main`/`role=main`/`article` outside chrome, decorative images and link cards (`collect/dom.py`); values MUST be
visible. (Previously: only two-cell rows and `dl` groups of the whole document.) Refs: Appendix A #42, D-0955, D-1096,
D-1640, D-1641, D-1642, D-1643.
#### Scenario: Label line
- **WHEN** the main region holds `Brand: <span>Example Brand</span>`
- **THEN** `brand` has the candidate `Example Brand` located at the span
#### Scenario: Lines of listed items
- **WHEN** the page holds `SKU: A-1` and `SKU: A-2` lines
- **THEN** `sku` has no candidate from them
#### Scenario: One price
- **WHEN** the main region shows one amount and a struck amount
- **THEN** `price` has the shown amount as a candidate; with two shown amounts, none

### Requirement: No generic DOM heuristics
Collectors SHALL contain no hostname, class fragment, phrase list or card selector; per-site selectors live only in
configs. Repeated-structure rows are read only by the item layer ([listings](../listings/spec.md)), from structure,
field types and named standards; the DOM collector reads a typed value only when the main region shows one. (Previously:
typed value spotting was read only by the item layer.) Refs: C2, C3, C13, owner #67, D-1643.
#### Scenario: Site literal in a collector
- **WHEN** a change adds a hostname or class fragment under `collect/`
- **THEN** the site-literal scan fails
