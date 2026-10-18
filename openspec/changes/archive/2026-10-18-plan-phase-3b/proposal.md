# Plan phase 3b: the label–value collector reads every two-column structure

## Why

On detail pages, labelled values the page shows (colour, material, a part number, a stock count) resolve with reason
`no_candidates` because the DOM collector reads only two-cell `tr` rows and `dl` groups over the whole document. Pages
also write `Label: value` lines and repeated label/value element pairs, and show one price or checked identifier
without a label. Master plan phase 3 asks for the collector to be generalized.

## What Changes

- **Pairs**: besides two-cell rows and `dl` groups, an element starting with `Label:` (the value in the text after the
  colon or in the one element that holds it) and sibling containers of one shape (two or more, each a label element and
  a value element). Labels still map through the field name and its schema.org property words (no vocabulary list).
- **Scope**: the page's main region (`main`, `role=main`, the one `article`), else the body, outside tangential
  content, dialogs and media fallback; lines and sibling pairs that give a field several values are the listed items'
  and are dropped.
- **Typed spotting**: in the main region, a money field's or a checked identifier's value shown once (one distinct
  value, not struck, not set apart), read with the item layer's spotting (`collect/items/spot.py`, now shared).
- **Deleted**: the whole-document `tr`/`dl` reading and its list-item helper, replaced by the region reading.

## Impact

- Specs: extraction ("Structural DOM values", "No generic DOM heuristics").
- Code: `collect/dom.py`, `collect/items/spot.py` (new, moved out of `align.py`), `collect/items/align.py`,
  `collect/items/bind.py`.
- Golden set: detail `no_candidates` and TP/FP per field, no LLM.
