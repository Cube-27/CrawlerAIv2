# Design: sweep fixes 2

## Decisions

### D-1470 — A vendor's stand-in marker makes a 2xx page `blocked` (INV-24 amended)
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: `ChallengeSignature.stand_in_markers` (`adapters/challenges.py`) holds markup that appears only in the
  document a vendor serves in place of the page (a waiting room, failover, block or challenge page). A 2xx HTML
  document showing one is `blocked` with that vendor's label (`acquire.challenge.block_class_of`, used by the HTTP and
  browser rungs), so `auto` gives it one browser attempt and ends `blocked` when the render is still the stand-in.
  Cookies, header names and script paths still only label: a vendor sets them on the pages it lets through too.
- Alternatives: labels only, with a structural rule alone (misses a stand-in that links to the site); cookies or script
  paths as evidence (every page behind the vendor would be blocked).
- Why: the sweep's 200 failover document was kept as the product page and published only `url`; it shows the edge's
  template marker. Replaying its capture now gives `blocked`, label of the vendor.
- Reversible: yes

### D-1471 — A self-refreshing 2xx document that links to no web page is `blocked`
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: `classify` calls a 2xx HTML document `blocked` when it declares a refresh (`meta http-equiv=refresh` or the
  `Refresh` header, HTML Standard §4.2.5.3) and none of its hyperlinks is relative or http(s) (only `mailto:`/`tel:`,
  RFC 6068, RFC 3966). The generic guard beside D-1470: the same capture is `blocked` by structure alone.
- Alternatives: a visible-text threshold (the stand-in had 890 characters of contact text); every page whose links are
  all non-web (no self-navigation: a contact page's shape, too broad).
- Why: a page of a site links to other pages of it; a document that navigates itself on and offers only a mail address
  and a phone number stands in for one.
- Reversible: yes

### D-1472 — In `auto`, an HTTP network error gets one browser attempt
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: an HTTP attempt that ends `error` with a `network_error` reason (a transport failure: a reset HTTP/2 stream,
  curl 92, or connection) is retried in the browser once, kept only when `ok`, as a shell or block is; a timeout, a
  body cap, a decoding error or an SSRF refusal is not.
- Alternatives: no retry (the sweep's case ended `failed`); retry on every error (a timeout or cap would cost a render
  for nothing).
- Why: a bot filter may reset a client whose TLS or HTTP/2 fingerprint it distrusts; the browser's own stack may pass.
  Live, the sweep page still resets the browser (`net::ERR_HTTP2_PROTOCOL_ERROR`), at one more attempt.
- Reversible: yes

### D-1473 — A JSON body's markdown is the answer pretty-printed in a `json` code block
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: `content.markdown` of a JSON body (`ParsedPage.json_body`) is the answer re-serialized with two-space
  indentation, characters as written, in one fenced code block with the info string `json` and a fence longer than any
  backtick run inside (CommonMark §4.5); `""` for a body that is no JSON. `markdown_fit` and `chunks` read it.
- Alternatives: the answer's text values only (loses the structure and keys a reader needs); empty (an LLM consumer of
  `markdown` would get nothing for adapter-served pages).
- Why: the JSON read as HTML gave escaped fragments and broken links (`<api>/\"https:/...`).
- Reversible: yes

### D-1474 — A JSON body's `html` is empty
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: `cleaned_html` of a JSON body is `""`; `raw_html` stays the body as received.
- Alternatives: the HTML-bearing string values (a description) as the page's main content (which value is "main" is a
  per-platform guess, C4); the whole JSON parsed as HTML (the defect).
- Why: an API answer is no HTML document; markup inside a value is data, which the `markdown` block and the records hold.
- Reversible: yes

### D-1475 — A listing without rows says why: `no_rows: <cause>`
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: `ExtractionResult.reason` is `no_rows: not_asked` (no role C hook, no row fields, or a config running a row
  field), `no_rows: <role C failure reason>` (`llm_unavailable`, `llm_budget`, `llm_output_invalid`, ...) or
  `no_rows: none_listed` for a listing that gave no rows; the scrape's `reason` and the task's `last_error` (scrape,
  batch, crawl) carry it.
- Alternatives: a new page outcome (changes the enum every job count reads); diagnostics only (not in the answer).
- Why: `records: []` alone could not tell "role C is off" from "the page lists nothing".
- Reversible: yes

### D-1476 — A listing that kept no record answers its page fields as `page`
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: `ScrapeResult.page` holds the schema's `scope: page` fields in the record field shape, present only for a
  listing that kept no record (rows' records already hold the page fields).
- Alternatives: always for a listing (a second copy of what each record holds); a record of page fields alone (a record
  stands for an entity).
- Why: a resolved `next_page_url` was dropped with the rows, so a caller could not page on.
- Reversible: yes

### D-1477 — `job_listing.locations` is a list of locations
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: the preset's `location` becomes `locations` (`list` of `location`, `JobPosting.jobLocation`), as in
  `job_detail`, edited in place (greenfield). The adapters' shapes map schema.org properties, so they are unchanged.
- Alternatives: publish the primary place (the adapter's `also` order) and drop the others (data the page states would
  stay unpublished).
- Why: 96 of 167 postings of one board published `conflict`/`disagree`; after the change all 167 publish, 96 with
  several places.
- Reversible: yes

### D-1478 — Role C reads a listing's item blocks, mapped back to the cleaned text
- Date: 2026-10-17 · Change/PR: sweep-fixes-2 (#266) · Status: decided (owner-delegated 2026-10-17)
- Decision: on a listing whose repeated item blocks (`acquire.items.item_blocks`) cover `MIN_ITEMS` or more items in the
  cleaned text, role C reads those items' spans of the cleaned text joined by line breaks (`content.item_text`), cut to
  the items whose rows' claims fit the reply's 16,384-token cap at 96 tokens a claim (`ROW_CLAIM_TOKENS`); each grounded
  span maps back to its cleaned-text offsets, and a span joining two items is ungrounded.
- Alternatives: a larger output cap (cost and latency of a 16k reply: 53 s); several calls per listing (later, if
  recall past the cap matters); the markdown view (no offsets in the cleaned text).
- Why: on a collection page with 146 items behind 80,000 characters of menus, role C gave 3 to 8 rows from 28k input
  tokens. With the item text: 55 rows from 3.4k tokens live (85 at 64 tokens a claim, but one of five 85-row replies ran
  to the cap); the other sweep listings keep all their rows (24, 20, 20 then 23 live) with fewer input tokens (6.5k to
  2.4k, 6.2k to 5.1k, 3.5k to 2.1k).
- Reversible: yes
