# Plan phase 2b: role C on listings reads the item layer's blocks

## Why

Role C on a listing still reads the page as phase 2 found it: the whole items' text view (`content/item_text.py`),
one row per claim, each row then placed on a block by guessing which block's links its values sit next to
(`collect/item_links.py`, `_placed`), and rows read from blocks alone replaced by role C's rows. The item layer now
binds one row per block, so role C only has to fill the fields those rows lack. Three deferred findings sit in this
path: the first listing chunk's output budget omits the page-field claims, the 200-row cap is per call rather than
per page, and page fields are read from the item text only.

## What Changes

- **Input**: one line per block of the bound group, under its locator (its position in the group and its item URL):
  the block's span of the cleaned text with each line break shown as a space. Only blocks whose row lacks a row field
  are sent, each with the fields its row lacks; the item URL is never asked.
- **Output**: claims `{block, field, value}`; each value is grounded as a verbatim span of that block's text (INV-12)
  and fills that block's row. Role C makes no rows, and no row is placed by its URL.
- **Page fields**: one detail-form call over the whole cleaned text, only when a required page field is missing.
- **Budgets**: at most 200 blocks per page across calls, each call within 80,000 characters and its reply's token cap.
- **A/B**: the old text-view prompt and the per-block prompt run on the golden set's listings with a live LLM before
  the switch; chosen by TP/FP.
- **Deleted**: `collect/item_links.py`, `content/item_text.py`, the pipeline's row placement and replacement, the
  `none_listed` no-rows cause, and their tests and spec text.

## Impact

- Specs: llm ("Role C input, claims and candidates", "When role C is asked"), listings ("Item groups", "Rows from
  captured calls", "Role C rows"), rest-api ("Scrape outcomes"), frontend ("A listing's page fields and why it has no
  rows").
- Code: `collect/items/bind.py`, new `collect/items/lines.py`, `llm/roles/c_extract.py` and its listing prompt,
  `config_ir/role_c.py`, `resolve/pipeline.py`, `eval/prefill.py`, the playground's no-rows sentence.
- Golden set: listing TP/FP/FN with and without an LLM; fewer listing tokens.
