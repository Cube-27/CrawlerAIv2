# Tasks

## 1. Extraction fixes

- [x] 1.1 Multi-typed nodes: `Entity.types` holds every declared type, most specific first; `EntityGraph.is_a` tests
      any of them. Unit and property tests; replay. (#227)
- [x] 1.2 Row keys by specificity: a key sub-field joins two rows only when they state no different value of a key
      sub-field listed before it. Property test against pairwise linking; replay. (#227)
- [x] 1.3 Agreement in linear time: `_all_agree` and `_offer_split` group by equality key. Property test (equals the
      pairwise result) and a 6,000-candidate test. (#227)
- [x] 1.4 Image renditions: (a) `resource_key` without the scheme; (b) namers by source kind in precedence order;
      (c) image values and lists naming the same files agree. Unit and property tests; replay. (#227)
- [x] 1.5 HTML fragments in structured-data text: a text value with element markup is read as the fragment's text.
      Unit and property tests; replay. (#227)
- [x] 1.6 og:description (owner, 2026-10-16): OGP `og:description` fills a long_text description, ranked behind
      JSON-LD and microdata; only OGP-defined properties are read. Unit tests; replay. (#227)
- [x] 1.7 Rating with zero reviews: `rating` maps `Product.aggregateRating.ratingValue+reviewCount`; a count of 0 is
      `Invalid("no_ratings")`. Unit tests; replay. (#227)
- [x] 1.8 Variants list only with two or more rows (owner, 2026-10-16): one published row leaves the field `missing`
      (`single_row`). Unit tests; replay. (#227)
- [x] 1.9 Apply the deltas to `openspec/specs/` and archive this change. (#227)
