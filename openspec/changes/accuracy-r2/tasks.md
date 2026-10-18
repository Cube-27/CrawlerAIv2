# Tasks

## 1. Role C listing rows

- [ ] 1.1 Role C grounds each listing row's values in one item of the view (most values, page order); values found
      only in another item are left out with a diagnostic.
- [ ] 1.2 Row item URLs are placed by the offsets of the row's grounded values; links refined by a query, or holding a
      grounded value, name the item; a role C row without its required item URL is left out.
- [ ] 1.3 Land the `hreflang` self-reference rule (D-1482) and measure it on the dev eval.

## 2. Currencies, apply links and generic rows

- [ ] 2.1 Shopify listing rows take the API's price when the page states that currency for its prices.
- [ ] 2.2 `apply_url` maps a stated apply link (an answer's apply member, schema.org `potentialAction` ApplyAction
      `target`) ranked above the posting URL.
- [ ] 2.3 Generic listing row URLs that differ from the item block's link by a trailing slash or an added query take
      the block's link.

## 3. Long listings

- [ ] 3.1 Measure a second role C call over the items past the first call's on the dev listings; implement it if
      precision holds.
- [ ] 3.2 Dev eval before and after; apply the deltas and archive this change.
