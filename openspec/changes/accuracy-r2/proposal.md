# Change: accuracy round 2 — role C listing rows, page currency, apply links

## Why

The dev eval after #266 and #267 (backlog "Sweep fixes 2" and "Draft dev baseline") shows role C listing rows that lend
each other values and miss their item URL when items repeat a title and price (one product in several colours), which
makes their prices and titles score as rows no label holds; the held-back `hreflang` rule (D-1482) waits for those
URLs. Shops with several presentment currencies keep listing rows unpriced (D-1481), a stated apply link is not mapped
(D-1485), generic listing rows whose URL adds a query or a trailing slash to the item's link match nothing, and role C
reads at most the first 56 items of a long listing. Each is a class of pages, fixed in the layer whose rule failed.

## What Changes

- Role C reads each listing row in one repeated item block: the block holding most of the row's values, in page
  order; a value found only in another item is left out. Row item URLs are placed by the offsets of the row's grounded
  values; a block whose links add a query to one link, or whose link holds a row value, still names one item. A role C
  row without its required item URL is left out.
- Money's locale set reads the `hreflang` of the alternate links to the page itself only (D-1482).
- Shopify listing rows take the price the API states when the page states the same currency for its prices.
- `apply_url` maps a stated apply link ranked above the posting URL.
- Generic listing rows whose URL differs from the item block's own link by a trailing slash or an added query take
  the block's link.
- Role C reads the rest of a long listing's items in a second call when the dev listings show it pays off.

## Impact

- Capabilities: [llm](../../specs/llm/spec.md), [extraction](../../specs/extraction/spec.md),
  [normalization](../../specs/normalization/spec.md), [adapters](../../specs/adapters/spec.md),
  [schemas](../../specs/schemas/spec.md).
- Code: `backend/src/crawlerai/llm/roles/c_extract.py`, `backend/src/crawlerai/collect/item_links.py`,
  `backend/src/crawlerai/content/` (`item_text.py`, `context.py`), `backend/src/crawlerai/resolve/pipeline.py`,
  `backend/src/crawlerai/adapters/shopify.py`, presets.
- No labels or captures change; the dev set stays outside the repo.
