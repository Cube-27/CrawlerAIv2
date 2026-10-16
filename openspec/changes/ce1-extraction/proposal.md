# Change: extraction fixes from the ce1 reference run

## Why

A replay of 80 stored commerce detail captures (dev reference run "ce1") showed classes of extraction failures in
collect, resolve and normalize, each confirmed in code:
- a node typed with several schema.org types counts only as its first, so a `["VideoGame","Product"]` node is not a
  Product and every value is `not_owned`;
- rows that share one key value join even when a more specific key tells them apart, and the joined cluster is then
  dropped `row_key_conflict` (sizes sharing one colour URL, or one sku with distinct gtins);
- candidate agreement is pairwise, so a page with thousands of price candidates takes about 30 s to resolve;
- the same image in another rendition does not name its original when only the scheme differs, two sources that name
  different gallery members leave the image a conflict, and two copies of one gallery in different renditions
  disagree;
- a JSON-LD description that is an HTML fragment publishes with its markup;
- an `AggregateRating` with `reviewCount` 0 publishes a rating of a product nobody rated.

The owner also answered two questions (2026-10-16): a product without variants publishes no `variants` list (the
list appears only with two or more variant rows), and INV-38 stays as written.

## What Changes

- An entity carries every declared type; ownership and intent test any of them (JSON-LD 1.1 §3.5, microdata).
- Row keys are matched in the preset's key order, most specific first: a key never joins rows that state different
  values of an earlier key.
- Agreement checks group candidates by their equality key, comparing pairs only for types with no key. No behaviour
  change.
- Image renditions: `resource_key` ignores the scheme; candidates that name one of an entity's values are taken by
  source kind in precedence order; image values (and lists of them, as multisets) naming the same files agree.
- A structured-data text value with element markup is read as the fragment's text.
- A number given with `reviewCount` 0 (`ratingValue+reviewCount`) is `Invalid("no_ratings")`.
- A row-mapped field publishes only when two or more rows publish.

## Impact

- Capabilities: [extraction](../../specs/extraction/spec.md), [resolution](../../specs/resolution/spec.md),
  [normalization](../../specs/normalization/spec.md), [variants](../../specs/variants/spec.md) (deltas in `specs/`).
- Design: owner decisions #44 (kept) and a new #48 (variants list only with two or more rows).
- Files: `collect/base.py`, `collect/jsonld.py`, `collect/microdata.py`, `collect/adapter.py`, `collect/api.py`,
  `collect/og.py`, `collect/schema_org_map.py`, `content/text.py`, `config_ir/executor.py`, `llm/roles/c_extract.py`,
  `resolve/ownership.py`, `resolve/rows.py`, `resolve/preference.py`, `normalize/url.py`, `normalize/dispatch.py`,
  `normalize/number.py`, `schemas/presets/commerce_detail.json`, and their tests.
- Not in this change: `og:description` as a description source and Shopify's `og:price:*` (open owner design
  question), and acquisition (browser wait, retries).
