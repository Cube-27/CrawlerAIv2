# Design: accuracy-r2

## Decisions

### D-1490 — A role C listing row is read in one item block, and placed by where its values are grounded
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: on a listing read through its items' text, each row's claims are aligned inside one piece of the view (one
  repeated item block): of the pieces holding most of the row's shown values, the first after the previous row's
  piece (the reply lists rows in page order), else the one nearest the row's first claimed offset; a value found only
  in another piece is dropped as `outside its item`. `row_links` places a row in the block whose cleaned-text span
  holds every grounded value's offsets, instead of looking for its values' text. In the block, links that only add a
  query to one link (swatches choosing a variant) refine it, and a hyperlink whose content holds a grounded value
  labels the item, beside one whose whole text is a row value.
- Alternatives: keep text matching with the row's position as a tie-break (still lends values across items); trust
  the model's offsets (on one collection page they drift by a piece within ten rows).
- Why: one block renders one item (ARCHITECTURE §8.6); model offsets are a hint (D-0024); the offsets of grounded
  values are where the values are. On the dev listings the role C rows of a colour-variant collection went from 2 to
  55 placed rows of 57.
- Reversible: yes.

### D-1491 — A role C row without the item URL its schema requires is left out
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: after role C's rows resolve, a row that does not publish every required item URL field (`Thing.url`
  fields `row_links` fills) is dropped, with the diagnostic `role C: rows without their item URL left out: <n>`; with
  an optional URL field the row stays without it. Rows of structured data and of captured calls are not touched.
- Alternatives: keep the row as a partial record keyed by its position (it names no item a later scrape can match).
- Why: a record's key is its row URL; without it the row is text of the page, not an item. On dev these rows matched
  no label row and scored every published value as wrong.
- Reversible: yes.

### D-1492 — The page's presentment currency is not read for platform listings
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: no change (D-1481 stands). Measured on the three dev shops with several presentment currencies: none
  states a schema.org `priceCurrency` on its collection page (the source the platform's theme documentation names for
  the presentment currency), and the platform's documented localization form states a country or nothing; the only
  statement all three carry is a storefront script global the platform does not document. `og:price:currency` is
  excluded (owner #48).
- Alternatives: read the undocumented script global (not a standard, not documented); fetch the page and query the
  API `@inContext(country:)` from the localization form (one of three shops states a country there; a second request
  per listing for no measured row).
- Why: C2 and C13: a source is admitted by a standard or the platform's documentation and by measured effect; this one
  has neither on the dev set. The dev captures of these listings hold the API answer only, so any rule needs new
  captures to measure.
- Reversible: yes.

### D-1493 — Ranked schema.org path alternatives; `apply_url` takes a stated apply link first
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: a `schema_org` path may separate alternatives with `>` as well as `|` (four in all): an alternative after
  a `>` reads no entity on which an earlier rank reached a stated value (a string or number; a node reached at the end
  of a path states none). The page-URL derivation looks at the last rank. `job_detail.apply_url` is
  `JobPosting.potentialAction.target>JobPosting.url`; the Lever and SmartRecruiters posting answers map their
  documented `applyUrl` as the posting's ApplyAction `target` (`adapters.base.apply_action`).
- Alternatives: pool the apply link with `url` (a conflict whenever both are stated, D-1485); a per-field rank list in
  the schema document (a second mechanism for alternatives); type-checked steps (`potentialAction` is an Action of the
  posting; schema.org's examples and the adapters only state ApplyAction there).
- Why: the posting states which URL takes an application; ranking keeps one value per entity. Dev: `apply_url` 7 to 8
  TP, no new FP.
- Reversible: yes.

### D-1494 — The `hreflang` self-reference rule lands
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: D-1482's rule is applied: the context's `hreflang` holds only the languages of the alternate links to the
  page itself (final URL or canonical link, resolved against the base URL).
- Why: with D-1490 and D-1491 the role C rows it prices carry their URL; on dev, money went from 88.3 to 91.4
  precision and 11.8 to 16.6 coverage at that step (bounded report).
- Reversible: yes.

### D-1495 — A structured row URL that respells an item block's link takes the page's link
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: on a listing, a row's item URL from structured data, a config or a captured call that equals exactly one
  link of the page's repeated item blocks but for its path's trailing slash or query parameters that link does not
  carry is replaced by that link as a `dom` candidate at its anchor; a URL that is a block link, or matches none or
  several, stays.
- Alternatives: strip queries from row URLs (a query can name the item, RFC 3986 §3.4); compare by the labels' form.
- Why: RFC 3986 §3.3: the same path on the same authority; the page's own link is how the page names the item. Dev:
  url 95.6 to 95.9, money 91.4 to 94.4 precision at that step.
- Reversible: yes.

### D-1496 — A long listing's items are read in further role C calls, up to the row cap
- Date: 2026-10-18 · Change/PR: accuracy-r2 (#270) · Status: decided (owner-delegated 2026-10-17)
- Decision: the items' view is read in calls of as many items as their claims fit the reply (`16384 // (row fields
  x 96)`), one after the other, up to `LISTING_MAX_ROWS` (200) items; the first call asks the page fields, the rows of
  later calls continue the numbering, a call without a valid reply ends the reading with the rows so far, and every
  call is recorded and charged.
- Measured: five dev listings were cut (60 to 147 items); the further calls (7 calls) added 286 placed rows. At that
  step url went 95.9 to 96.0 precision (59.0 to 62.5 coverage), money 94.4 to 95.7 (17.2 to 22.6), location 79.7 to
  79.8 (45.9 to 48.6); text went 90.4 to 88.0 (56.4 to 59.3), all of it rows whose label titles add a variant or the
  company the page shows apart from the title, and still above the 87.0 before the change.
- Alternatives: one further call only (a 146-item listing stays cut); a bigger reply cap (a reply cut at its cap is
  invalid and gives no row, D-1478).
- Reversible: yes.
