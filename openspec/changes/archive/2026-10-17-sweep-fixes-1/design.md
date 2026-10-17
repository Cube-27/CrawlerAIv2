# Design: sweep fixes 1

## Decisions

### D-1450 — The links of a JSON body are its absolute URL string values
- Date: 2026-10-17 · Change/PR: sweep-fixes-1 (#263) · Status: decided (owner-delegated 2026-10-17)
- Decision: `ParsedPage.json_body` is true for an `api` capture (its body is `body.json`, SPEC-01 §4.5). The `links` of
  such a page are its string values that canonicalize as absolute http(s) URLs with no base (RFC 3986 §4.3), deduplicated,
  in document order (RFC 8259 §4); it has no link elements, so `anchor_texts` is empty. The text is still parsed as
  HTML for the readers of text (role C, fingerprints, markdown), which this change leaves as they were.
- Alternatives: no links for a JSON body (crawl discovery and map would lose the posting URLs the answer states); parse
  the markup inside string values as HTML fragments (a description's links are not the page's, and relative ones have
  no base).
- Why: in the sweep every adapter-served page's links were fragments of escaped strings
  (`<api>/%5C%22https:/...`): 42 of 42 on one board's listing, 15 of 15 on another. After the change the same pages list
  the posting and apply URLs the answer states (620 and 334), none junk; a 9 MB answer reads in about 0.1 s.
- Reversible: yes

### D-1451 — The scrape answer carries `reason`
- Date: 2026-10-17 · Change/PR: sweep-fixes-1 (#263) · Status: decided (owner-delegated 2026-10-17)
- Decision: `ScrapeResult.reason` is the task's `last_error` for a page robots.txt kept from being fetched (`robots`, or
  `robots_unreachable` for a 5xx or 429 robots.txt, RFC 9309 §2.3.1.4), always present, null for a page that was
  fetched. A fetched page's failure reasons stay on `fetch.attempts[].error`. The playground shows it beside the outcome.
- Alternatives: name it `last_error` as the batch results do (a fetched page's failure would then be expected there
  too, a second copy of the attempt errors); a distinct outcome for an unreadable robots.txt (changes the outcome enum
  every job count and filter reads).
- Why: a host answering 5xx for robots.txt and a disallow both answered `blocked` with null `fetch` and nothing else,
  so a caller could not tell "the site forbids this" from "the site is down".
- Reversible: yes
