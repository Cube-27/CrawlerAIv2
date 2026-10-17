# Change: fixes from the 40-page site test

## Why

A 40-page run of the engine (10 pages each of `commerce_detail`, `commerce_listing`, `job_detail` and `job_listing`),
judged field by field against the live pages, found eleven failure classes. Most are behaviour a requirement, an
owner decision or the contract states; four are generic gaps: a structured price written with its currency sign is
declined, and role C listing rows miss the item URL their repeated item block holds when the title is cut short with
an ellipsis, is a prefix of another item's title, sits in a card that links to several documents, or when a pager
outnumbers the grid. The triage of every class is in [design.md](design.md).

## What Changes

- Money: a structured `price` written as display text (a currency sign, grouping) is read like text under its stated
  `priceCurrency`; a sign it writes must denote that currency.
- Listing row URLs (`collect/item_links.py`): a block's text is read as the cleaned text shows it (an ellipsis cut
  completed by `title`, non-rendered elements left out); a row is matched with all its grounded values, and a value
  that is a block element's whole text picks that block among several; a block linking to several documents gives the
  one its hyperlinks labelled with a row value lead to; the rows are looked for in every repeated item group, not only
  the largest.
- One `needs-owner` decision: a listing that gives no rows at HTTP while its HTTP body holds other repeated blocks is
  not retried in the browser (class A).

## Impact

- Capabilities: [normalization](../../specs/normalization/spec.md) (money), [extraction](../../specs/extraction/spec.md)
  (cold listing rows).
- Files: `backend/src/crawlerai/normalize/money.py`, `backend/src/crawlerai/collect/item_links.py`,
  `backend/src/crawlerai/acquire/items.py`, `backend/src/crawlerai/content/text.py`, their tests.
- Extraction behaviour changes; the gate reports `no_baseline` until milestone M (C10).
