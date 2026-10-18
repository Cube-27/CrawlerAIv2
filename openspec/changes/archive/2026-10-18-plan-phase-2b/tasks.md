# Tasks

## 1. Per-block input

- [x] 1.1 Bind exposes each listed row's block and its position in the group (`Bound.blocks`); `collect/items/lines.py`
      gives a block's span of the cleaned text; the pipeline asks role C for the blocks whose rows lack a row field,
      each with the fields its row lacks, when a row field is published on no row or a row lacks a required one. (#279)

## 2. Per-block claims

- [x] 2.1 Role C's listing call reads `[n] line` per block and replies claims `{block, field, value}`, grounded in that
      block's text and owned by its row; at most 200 blocks per page across calls, each call within the character
      and reply budgets; page fields asked in their own call over the whole cleaned text. (#279)
- [x] 2.2 The pipeline's hook and the labeling pre-fill make these calls; role C's candidates re-resolve the bound
      rows. (#279)

## 3. Prompt A/B

- [x] 3.1 Run the text-view prompt and the per-block prompt on the golden set's listings with a live LLM; keep the
      better by TP/FP and record the aggregates. (#279)

## 4. Delete what this supersedes

- [x] 4.1 Delete `collect/item_links.py`, `content/item_text.py`, the pipeline's row placement and replacement, the
      `none_listed` cause and its playground sentence, with their tests and spec text. (#279)
