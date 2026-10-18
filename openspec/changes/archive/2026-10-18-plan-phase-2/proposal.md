# Plan phase 2: the item layer (segment, align, bind, row key)

## Why

The engine has no deterministic path from a repeated DOM structure to a listing row (master plan §2.2, owner decision
#67): rows come from structured data, captured calls or role C, so listings whose structured data gives no rows or
only stubs lose titles, prices and item URLs (failure classes L04–L08 on the golden set). Four mechanisms already walk
the same repeated groups (`acquire/items.item_blocks`, `crawl/paging._largest`, `collect/item_links.py`'s link
helpers, `resolve/call_rows.py`) and none produces a row. Owner decision #67 admits the item layer: repeated-structure
rows and typed value spotting, with no hostname, class fragment, phrase list or card selector.

## What Changes

- **Segment** (`content/segment.py`): the page's groups of repeated item blocks, cached on `ParsedPage.item_groups`,
  ranked by one ranker: rendered area when the browser capture measured the blocks (the browser rung records
  `item_areas` in the capture manifest for listings), else structural evidence. It replaces `item_blocks` and the
  paging driver's own ranking; the markdown format, role C's item text, `xhr` and paging read it.
- **Align** (`collect/items/align.py`): each group's blocks with one item link become rows; per field a place shared
  by `max(3, 60%)` of the blocks whose values the field's normalizer accepts: name from the item link's accessible
  name or the block's heading, item URL from the one document the block's links lead to, image from the block's
  image, money/date/check-digit identifiers by typed value spotting; several money values in one block decline as
  `ambiguous_in_block`. Rows are `item_block` entities with `dom` candidates and locators.
- **Bind** (`collect/items/bind.py`): stated rows (structured, the config's, or the captured calls') and blocks meet by
  item URL (or visible text); blocks are the rows where stated rows are none or stubs and extend them otherwise; state
  and call array rows bind by URL; per-page key→field induction shares its rule with learning's induction
  (`collect/induce.py`). Replaces `resolve/call_rows.py` and `as_block_links`.
- **Row key**: a listing row's item URL is the block link, else schema.org `Offer.url`, else `mainEntityOfPage`,
  then session parameters are dropped as before.
- **Role C** stays the row reader of last resort; it is also asked when the rows publish a row field on no row, and
  its rows then fill the rows they bind to by item URL.

## Impact

- Specs: extraction (generic DOM rule, content formats; listing requirements move out), new capability `listings`,
  llm (role C on listings), acquisition (capture contents).
- Code: `content/segment.py`, `collect/items/`, `collect/induce.py`, `collect/run.py`, `collect/schema_org_map.py`,
  `resolve/pipeline.py`, `acquire/browser.py`; deleted `resolve/call_rows.py`, `acquire.items.item_blocks`,
  `item_links.as_block_links`/`group_links`/`block_links`.
- Golden set: listing rows, titles, prices and URLs without an LLM; fewer role C calls on listings.
