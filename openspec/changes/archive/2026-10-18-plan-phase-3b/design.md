# Design: plan phase 3b, the label–value collector reads every two-column structure

The DOM collector (`collect/dom.py`) reads pairs in the page's content region and one typed value per money or
checked-identifier field. Shape: a pair is `(label text, value element, value text, kind)`, kind one of `table`
(rows, `dl`), `line` or `siblings`; a typed spot is the item layer's `Spot` (`collect/items/spot.py`, moved out of
`align.py` so both layers share it without an import cycle).

## Decisions

### D-1640 — Lines and sibling pairs are read, and a field they give several values reads none from them
- Date: 2026-10-18 · Change/PR: plan-phase-3b (#282) · Status: decided (owner-delegated 2026-10-17)
- Decision: An element whose first child holds a label and a colon (U+003A or U+FF1A) gives the text after it, and
  sibling containers of one shape (two or more) each of a label element and a value element give their pairs. For a
  field, these two kinds read their values only when they give one distinct value; rows and `dl` groups keep their
  earlier reading.
- Why: such lines and pairs repeat for related products and variants (a golden detail page lost a correct `sku` to
  three lines of other items before the rule); rows and `dl` groups are the page's own specification by the HTML
  Standard.
- Reversible: yes

### D-1641 — Pairs are read in the main region, else the body, outside tangential content
- Date: 2026-10-18 · Change/PR: plan-phase-3b (#282) · Status: decided (owner-delegated 2026-10-17)
- Decision: The region is the collector's main region (`main`, `role=main`, the one `article`), else the body; values
  in `nav`, `header`, `footer`, `aside`, dialogs and media fallback are not read. This replaces the whole-document
  `tr` and `dl` reading.
- Why: the task asks for the page's main content; a footer's or a drawer's table is not the entity's. On the golden
  detail pages the narrower scope lost no true positive.
- Reversible: yes

### D-1642 — Labels still map by schema words; the document language selects nothing
- Date: 2026-10-18 · Change/PR: plan-phase-3b (#282) · Status: decided (owner-delegated 2026-10-17)
- Decision: A label names a field only through the field's name and the schema.org property words of its path, as
  before. No per-language label vocabulary is added, so `lang` is not read.
- Why: neither the schemas nor the pinned schema.org vocabulary carry translated or synonym labels, and C4 forbids a
  phrase list; the golden labels whose page labels are another language or a synonym (a stock-code label, a model
  label) therefore stay `no_candidates`. Follow-up: an owner-approved label vocabulary source.
- Reversible: yes

### D-1643 — Typed spotting in the main region reads money and checked identifiers only, one shown value
- Date: 2026-10-18 · Change/PR: plan-phase-3b (#282) · Status: decided (owner-delegated 2026-10-17)
- Decision: In the main region (with none, nothing is spotted), the text an element holds itself, at most 64
  characters, not struck (`s`, `del`), not set apart and shown, that a money field's or a check-digit identifier's
  normalizer parses; one distinct value publishes, several publish nothing. Counts and ratings have no checkable
  syntax, so they are read only from labelled pairs.
- Why: a bare number is no count or rating without its label; an amount or a checked identifier is a value by its
  syntax, and a single one in the main region is the item's. The length cap bounds normalizer calls, not a vocabulary.
- Reversible: yes

### D-1644 — Measured effect on the golden detail pages
- Date: 2026-10-18 · Change/PR: plan-phase-3b (#282) · Status: decided (owner-delegated 2026-10-17)
- Decision: Detail cells with no LLM (`eval run --split dev --labels all`, drafts included) went from TP/FP/FN
  198/57/56 to 200/57/54; `no_candidates` from 37 to 35 (colour and price gained a correct value, material a
  disagreeing one). The 20–28 target is not reached: most remaining values sit under labels the schema words do not
  name (D-1642) or only in structured data and scripts.
- Why: recorded as the PR's measure; a dev-draft report is no gate (owner #65).
- Reversible: yes
