# Design: ce1-extraction

## Decisions

### D-1180 — An entity carries all its types
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided
- Decision: `Entity.kind` is replaced by `Entity.types` (every declared schema.org type, most specific first; `page`
  for the page and role C rows); `EntityGraph.is_a` tests any of them. All callers moved; no alias kept.
- Alternatives: keep `kind` and add `types` (two fields to keep in step); pick a "primary" type by the schema (a
  second rule for one fact).
- Why: JSON-LD 1.1 §3.5 and microdata `itemtype`: a node is an instance of each type. A node typed
  `["VideoGame","Product"]` had every value `not_owned` in the ce1 replay.
- Reversible: yes

### D-1181 — Row keys join by specificity
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided
- Decision: `linked` takes the key sub-fields in the preset's `key` order (most specific first: gtin, sku, url); a key
  joins two rows only when they state no different value of an earlier key. Rows in one equality bucket are compared
  pairwise for that check (rows are tens, not thousands).
- Alternatives: drop the url key (loses pages keyed only by an Offer URL); split a conflict cluster after the fact
  (order-dependent).
- Why: in the ce1 replay, sizes of one colour URL with their own skus, and sizes of one sku with their own GTINs, were
  joined and then dropped `row_key_conflict` (3 pages; now 24, 7 and 24 rows).
- Reversible: yes

### D-1182 — Renditions: scheme-free resource key, namers by precedence, same files agree
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided
- Decision: `url.resource_key` is authority and path (no scheme, no query); a list of image_url values keys as the
  multiset of its items' keys. The kinds that name one of an entity's several values decide one at a time in the
  type's precedence order (unranked kinds last). Image values (or lists) of the winning kind, or named by one kind,
  that share one resource key agree, and the first in collector order publishes.
- Alternatives: rank renditions by size parameters (no standard); keep http and https apart (RFC 9110 §4.2.2 gives
  them no shared identity, but the key only tells which of the page's own values another source names).
- Why: the ce1 replay had 3 image_url and 3 additional_images conflicts that were one file in two renditions, or an
  og:image over http naming an https gallery member.
- Reversible: yes

### D-1183 — Markup in structured-data text is read as the fragment's text
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided
- Decision: a text or long_text value from JSON-LD, microdata or an adapter that parses to at least one element is
  rendered with `content.text.render` (`content.text.fragment_text`); the text is escaped again before the text
  normalizer, so references decode once. The candidate's `raw` stays as the page states it.
- Alternatives: strip tags with a regex (no block boundaries; misreads `a < b`); decode twice (breaks a literal
  `&amp;`).
- Why: three ce1 descriptions published with `<p>`/`<ul>` markup; job adapters' HTML descriptions now read the same way.
- Reversible: yes

### D-1184 — A rating with reviewCount 0 is no rating
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided
- Decision: `rating` maps `Product.aggregateRating.ratingValue+reviewCount`; the number normalizer reads that object
  and declines `no_ratings` when the count is 0; a missing or non-numeric count leaves the value as stated.
- Alternatives: `ratingCount` (a joined path takes one property; a page with ratings but `reviewCount` 0 now loses its
  rating: a missing value, not a wrong one); `worstRating` (needs the same join).
- Why: one ce1 page published rating 0 from `{ratingValue: 0, reviewCount: 0}`.
- Reversible: yes

### D-1185 — A variant list needs two published rows
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided (owner answer, Appendix A #48)
- Decision: with one published row the field is `missing` (`single_row`); that row's candidates are rejected with the
  same reason, and dropped rows are kept. Counted on published rows, so a variant left alone by dropped rows also gives
  no list.
- Why: owner, 2026-10-16: a product without variants shows all its fields normally; `variants` appears only with 2 or
  more variants. 9 ce1 pages lose a one-row list; their top-level values are unchanged.
- Reversible: yes

### D-1186 — og:description fills the long_text description
- Date: 2026-10-16 · Change/PR: ce1-extraction (#227) · Status: decided (owner answer, Appendix A #48)
- Decision: the OGP table gains `og:description` for a long_text field whose role is `description`; it ranks behind
  JSON-LD and microdata by the long_text order. A site-default block (an `og:title` naming the site) drops it with
  `og:title` and `og:image`.
- Why: owner: generic code reads the closed set of properties a published standard defines; `og:description` is OGP
  optional metadata. 12 ce1 pages gain a description; some are store boilerplate (accepted: an optional field).
- Reversible: yes
