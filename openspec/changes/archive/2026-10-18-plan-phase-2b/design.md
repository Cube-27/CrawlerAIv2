# Design: plan phase 2b, role C on listings reads the item layer's blocks

The item layer binds one row per block (plan phase 2). Role C's listing job becomes filling the fields those rows lack,
block by block, so its input is the blocks' own text and its claims name a block instead of a row to be placed.

- Shape: `RowBlock(index, block, row)` from bind; `BlockText(index, url, row, start, text, fields)` from
  `collect/items/lines.py`; claims `{block, field, value}`; the reply's candidates are owned by the blocks' rows (and
  the page entity for page fields), and the listing re-resolves with them.
- The pipeline's request carries the blocks and the missing page fields; the hook (`config_ir/role_c.py`) makes the
  blocks call and, when asked, the page-fields call.

## Decisions

### D-1600 — The per-block prompt replaces the text-view prompt, chosen by a live A/B on the golden set
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: On the golden set's 40 listing pages, with a live fast model and fresh recordings, listing cells scored
  TP/FP/FN 935/181/926 without an LLM (both code bases), 937/225/924 with the text-view prompt (30 listing calls,
  96k input and 97k output tokens) and 935/216/926 with the per-block prompt (22 calls, 71k input and 25k output
  tokens). The per-block prompt is kept: 9 fewer FP for 2 fewer TP (one row on one page), and a quarter of the output
  tokens.
- Why: the task's rule, TP/FP; the TP difference is within one row's noise, the FP and cost gains are not.
- Reversible: yes (the prompt and request are one module)

### D-1601 — A block's line is its span of the cleaned text, line breaks shown as spaces
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: A block is read as the cleaned-text span its node path carries (`ParsedPage.text_spans`), each line break
  shown as one space so offsets stay equal; a value claimed across a break is not in the text and is dropped. A block
  whose path carries no span (no rendered text, or a malformed-markup tree mismatch) is not read. Accessible names
  outside the text (an `alt` or `aria-label`) are not shown: a value from them could not be grounded (INV-12).
- Why: INV-12 grounds in the cleaned text only; one line per block keeps the locator unambiguous.
- Reversible: yes

### D-1602 — Claims `{block, field, value}`, without offsets, grounded in their block only
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: The reply is one array of closed objects whose `field` is an enum of the fields asked; a claim of a block
  or field not asked, an empty value or a second claim of one block and field is not taken; the value is aligned to
  its first occurrence in the block's text and located at that offset in the cleaned text.
- Why: an enum and one array stay inside every provider's subset whatever the field count; offsets in a short line
  add tokens and no information (the nearest-occurrence rule would pick the same span).
- Reversible: yes

### D-1603 — Which blocks are asked, and for what
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: Role C is asked when some row field is published on no row, or some block's row lacks a required row
  field; then every block whose row lacks a row field is sent with exactly those fields. The item URL is never asked
  (it is the block's link, which its text does not show). Rows not bound to a block (call rows without a block) get no
  role C values. Never beside a config that runs a row field.
- Why: the phase-2 trigger, narrowed to the fields each row lacks; the smallest request that can fill them.
- Reversible: yes

### D-1604 — Page fields in their own call over the whole cleaned text
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: The missing page fields are asked in a detail-form call over the whole cleaned text (40,000 characters),
  only when a required page field is missing, with every missing page field in that call; the reply's failure is that
  call's failure.
- Why: fixes the deferred findings that page fields were read from the item text only and were left out of the first
  chunk's budget; it mirrors the detail page's rule.
- Reversible: yes

### D-1605 — Role C makes no rows; one no-rows cause
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: A listing's rows are the bound rows only; role C fills them. A listing with no rows is never asked for
  rows, so its reason is always `no_rows: not_asked`; the `none_listed` cause, the failure-reason causes and their
  playground sentences are deleted. The "role C reads the items elsewhere" path goes with URL placement.
- Why: the task's "no URL-guessing placement"; the A/B shows no TP from role C rows outside the item layer.
- Reversible: yes

### D-1606 — Budgets: 200 blocks per page, 80,000 characters and a reply's claims per call
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: At most 200 blocks are read across a page's calls (the rest recorded in a diagnostic); a call holds as
  many blocks as fit 80,000 characters and `16,384 / (fields × 80)` claims, 80 output tokens per claim being about
  twice the 41 measured on the golden set's listings. A failed call ends the page's calls and keeps the values read
  before it.
- Why: fixes the deferred finding that the 200-row cap was per call; a reply cut at its token cap is invalid and fills
  nothing, so the budget keeps a margin.
- Reversible: yes

### D-1607 — The listing pre-fill asks the first aligned group's blocks
- Date: 2026-10-18 · Change/PR: plan-phase-2b (#279) · Status: decided (owner-delegated 2026-10-17)
- Decision: The labeling pre-fill aligns the page with the schema's fields (no stated rows to bind), asks each block
  of the first aligned group for every row field but the item URL, and asks the page fields in their own call; a block
  that labels no field is no row. `align` takes the schema's content (`SchemaContent`), so the pre-fill needs no
  stored schema.
- Why: one listing call form for extraction and labeling.
- Reversible: yes
