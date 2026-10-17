# Design: site-test-40-fixes

## Input

A 40-page run of the engine at `main` 41721946 through `POST /v1/scrape` (10 pages each of the four presets), with
each output judged against the live page. The report and the raw answers stay outside the repo: they name real sites
(C3). Captures were replayed through `extract_page` without role C, and role C's listing rows were rebuilt from their
grounded spans (`text:<start>-<end>` locators of the answers) to replay `row_links`.

## Triage

Verdicts: **fix** (a generic rule for the class, C2/C5), **by design** (the basis that states the behaviour), **owner**
(a `needs-owner` decision). Page counts are of the site test.

| # | Class | Pages | Verdict | Basis or action |
|---|---|---|---|---|
| A | Client-rendered listing stays on HTTP with 0–1 rows | 3 | owner (D-1245) | The listing-shell rule (D-0933, D-1158) fires only on a listing without repeated items; two of these HTTP bodies hold other repeated linked blocks (related posts, search filters), so the rule as stated keeps them `ok`. A render on "no rows at HTTP" is an acquisition policy like owner #49, which covers detail pages only. The third page's HTTP body holds 20 item blocks but role C read one row; not reproducible without the LLM recording (follow-up). |
| B1 | Listing price: structured `price` written with its sign (`"$295.99"`, `priceCurrency` USD) | 1 (117 rows) | fix (D-1240) | schema.org `priceCurrency` states the currency; the text reader (CLDR) reads the amount and any sign must denote that currency. |
| B2 | Listing price: `$` on a `lang="en"` page that states no currency | 3 | by design | C7; normalization "money" scenario *Ambiguous dollar*. A `$ 7.59` with a stated currency already reads. |
| B3 | Listing price: bare `24.99`, no currency on the page | 1 | by design | C7, D-0301: no sign is `Invalid`. |
| B4 | Listing price: adapter rows unpriced (`Rs. 12,300` on the page) | 1 | by design | SPEC-15: a shop presenting several currencies gets its rows without Offers (`_UNPRICED_LISTING`); the answer's currency may not be the page's (C7). |
| B5 | Row URL: title cut with an ellipsis, full title in `title` | 1 (10 rows) | fix (D-1241) | The cleaned text completes such a cut (D-1154), so role C grounds the full title; the block text must be read the same way. |
| B6 | Row URL: a title that is part of another item's title (`X` and `X 2`), duplicate titles | 2 (16 rows) | fix (D-1242) | A value that is an element's whole text (HTML structure) picks its block; all of the row's grounded values (price, location) count, not only text fields. |
| B7 | Row URL: a card linking to several documents (title, author, "editions") | 2 (70 rows) | fix (D-1243) | HTML Standard §4.5.1: an `a` element's content labels its link; the one document the block's links labelled with a row value lead to. |
| B8 | Row URL: a pager outnumbers a five-card grid | 1 | fix (D-1244) | The rows are looked for in every repeated item group; the group holding most rows wins (D-0934's follow-up for markdown stays). |
| B9 | Row URL: a one-job listing | 1 | by design | Fewer than `MIN_ITEMS` blocks is no repeated structure (`acquire.items`). |
| B10 | Row title: microdata `itemprop="name"` on an `a href` | 1 | by design | HTML Standard microdata: an `a` element's value is its URL (D-1153); rows from structured data skip role C (§8.6). |
| C | `next_page_url` never set | 6 | not this change | Change `listing-browser-actions` (parallel). |
| D1 | No `variants` though the page offers some | 3 | by design | Rows come only from structured data (variants "Scope and sources of rows"; owner #48): one page lists variants only as DOM options with an `AggregateOffer` (never a row), two state one Offer in JSON-LD and the rest only in theme JSON. |
| D2 | One size's sku and gtin as the product's | 1 | by design | The JSON-LD `Product` states that sku and gtin itself; no structured variants contradict it (INV-38 covers the target's Offers). |
| D3 | Standalone `Product` beside its `ProductGroup` (no `isVariantOf`): colour, gender, material, variants `not_owned` | 1 | by design | Open follow-up D-0966 (now 2 pages: one eval, one here); linking the two needs a group-identity decision. |
| D4 | Main image `conflict`: `og:image` is a CDN fetch URL wrapping the JSON-LD image | 1 | by design | Open follow-up D-0944 (a rendition rule). |
| E | Description from `og:description` boilerplate; one cut to a sentence | 3 | by design | Owner #48: `og:description` fills a long_text description behind JSON-LD and microdata (both empty there). The cut one is role C's grounded span (INV-12), not a code class. |
| F | `AggregateOffer` `lowPrice` not published as the price | 1 | by design | INV-15: an `AggregateOffer` range never publishes as the price. |
| G | Dates declined | 2 | by design | `09/04/2026`: normalization "date" scenario *Day-month order unknown*. An embedded-JSON date the page does not show: owner #34 (state admits a visible value or by equality). `1 day ago`: no standard date form. |
| H1 | Several places in one location text | 2 | by design | Owner #44: the location publishes as written, never split. |
| H2 | `remote_flag` false on postings from remote boards | 2 | by design | Location "as stated": only `jobLocationType` TELECOMMUTE or a remote phrase in the location sets it; neither page states either. `false` is the normalizer's "not stated" (follow-up: a tri-state). |
| H3 | `locality`, `region`, `country` null | all | by design | Owner #43: only a `PostalAddress`'s stated parts; no gazetteer. |
| I | Blocked pages | 6 | by design | One URL holds a query name robots.txt disallows (`Disallow: /*<name>`, RFC 9309; robots.txt answered 200, not 403); two challenge pages after HTTP and browser (owner #50, §22); three robots disallows. |
| J | Outcome `partial` with every stated field, `extracted` with no prices | 2 | by design | Resolution "Incomplete pages": `date_posted` is required in `job_detail`; `price` is optional in `commerce_listing`. |
| K | Adapter rows beyond the visible page (API page of 250) | 1 | by design | Adapters serve the API's first page (backlog: ATS adapters); not wrong values. |
| — | Availability "Sold" declined | 1 | by design | INV-37 first-clause rule; the vocabulary grows only under C10 (C4). |
