## Why
Eight follow-ups of merged PRs (#203, #207, #206, #209, #213) leave generic rules that misread a class of pages:
a spaced dash read as a minus, a mass unit beside "one", "not remote" read as remote, an identifier field pooling
every scheme, a quadratic site-name scan, a lost space after inline elements, a listing read in precision mode, and
a tag cloud outranking a grid. Owner request 2026-10-17: close the backlog.

## What Changes
- Normalize: a minus negates money and count only when it touches the number; count declines a CLDR measurement
  unit as `unitText` beside `C62`; `type:remote` in a location is stated only as a whole clause.
- Collect: a field mapped to `identifier` widens to its own scheme only; `site_names` bounds the parts it combines.
- Content: `markdown` wraps inline runs in `div`/`td`/`li` before trafilatura and reads a listing without items in
  recall mode.
- Listing items: the group with the most structural evidence (image, several text runs) wins, then size.

## Impact
`normalize/{numbers,money,count,location}.py`, `normalize/vocab`, `collect/{schema_org_map,site_names}.py`,
`content/markdown.py`, `acquire/items.py`. No API, schema or data change. Specs: normalization, extraction.
