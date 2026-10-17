# Change: structural ownership of array rows in embedded state

## Why

Owner decision #34 (accuracy Q2, option (a)) admits a visible `js_state` or `xhr` value of a checkable type (money,
date, enum, check-digit identifier, absolute URL) for a field with no other candidate, and gives it to the page, so it
is the detail target's. Embedded state and API bodies also carry the page's other items: related and similar products,
recommendations, recently viewed items, each one object of an array. A visible price of such an item becomes the
target's price, or makes the target's own price `conflict`. Option (b), structural ownership of array rows, was left as
the follow-up for checkable types inside related-item arrays (#166); it is the backlog's current focus. The structured
collectors already own a related item's values by its entity (`isRelatedTo`, `isSimilarTo`, an `ItemList`, an Offer of
another product); state has no keys to read, so its rows are told apart by structure alone.

## What Changes

- **Rows in state** (`collect/admission.py`): an object item of a JSON array holding two or more objects is a row. A
  value admitted by visibility alone inside a row is owned by that row's entity (type `array_row`, parent the
  enclosing row or the page), not by the page. The row entity's `urls` are the URLs written in its scope (absolute
  http(s) URLs and path-absolute references, RFC 3986 §4.2), stopping at nested rows. Values admitted by equality keep
  the owner of the candidate they equal.
- **Row ownership** (`resolve/ownership.py`): a row's candidates are the target's only on a detail page (where page
  values are the target's), and only when the row and every row enclosing it names the target: one of its URLs equals
  a page URL (request, final, canonical) or one of the target's URLs. Any other row's candidates are `not_owned`.
- The structured collectors' related-item arrays (JSON-LD and microdata `isRelatedTo`/`isSimilarTo`, an `ItemList` on a
  detail page, the Offers of another product) keep their entity ownership; behaviour tests now pin it.
- Owner decision #55 records option (b) built beside option (a), under owner delegation 2026-10-17.

## Impact

- Capabilities: [extraction](../../../specs/extraction/spec.md) ("Embedded JSON state and XHR admission"),
  [resolution](../../../specs/resolution/spec.md) ("Validity, intent and ownership").
- Design: Appendix A #34, #55; D-0419, D-0780, D-1250–D-1255.
- Files: `backend/src/crawlerai/collect/{admission,base,run}.py`, `resolve/{ownership,intent,pipeline}.py`.
