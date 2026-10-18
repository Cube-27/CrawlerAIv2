# Design: plan phase 2b, role C on listings reads the item layer's blocks

The item layer binds one row per block (plan phase 2). Role C's listing job becomes filling the fields those rows lack,
block by block, so its input is the blocks' own text and its claims name a block instead of a row to be placed.

- Shape: `RowBlock(index, block, row)` from bind; `BlockText(index, url, row, start, text, fields)` from
  `collect/items/lines.py`; claims `{block, field, value}`; the reply's candidates are owned by the blocks' rows (and
  the page entity for page fields), and the listing re-resolves with them.
- The pipeline's request carries the blocks and the missing page fields; the hook (`config_ir/role_c.py`) makes the
  blocks call and, when asked, the page-fields call.
