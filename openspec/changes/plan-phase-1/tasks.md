# Tasks

## 1. Decode once

- [ ] 1.1 Decode a body once at acquisition (`capture_bundle.decode_html`); `classify`, `interstitial`,
      `lacks_site_structure`, the listing rule and the challenge readers take the decoded text; a non-UTF-8 page
      classifies without raising; re-import the golden set's missing page into a copy of the eval database.

## 2. One polite fetch

- [ ] 2.1 One polite fetch component (`services/polite.py`) used by the scrape, extract, map, crawl, batch and eval
      import paths, replacing the four front-ends; one `Retry-After`/back-off rule (`politeness.backoff`); the other
      fetch back-off rules deleted.

## 3. Structural render need

- [ ] 3.1 `RenderNeed` replaces `ContentCheck`: listing render on fewer than `MIN_ITEMS` item blocks, hidden text over
      visible text, or a structured list shorter than the DOM's item blocks; detail render on no offer data; role C
      once on the kept capture; the old check deleted.

## 4. Browser resources

- [ ] 4.1 Abort image, font and media requests by resource type in the browser rung; per-site opt-out when a blocked
      render of a listing shows fewer item blocks than its HTTP page; the interstitial wait bounded; browser bytes per
      page measured on the golden listing pages.

## 5. Listing growth

- [ ] 5.1 Bounded listing growth by default for a single-URL listing scrape in `auto` that renders, never for batch or
      crawl; the #52 documents amended.

## 6. Blocked as an outcome

- [ ] 6.1 A vendor-labelled block ends `blocked` with the vendor named; at most one worker retry after the back-off;
      the eval import retries acquisition up to 3 times and keeps the best capture.
- [ ] 6.2 Golden-set eval before and after (no LLM and LLM), role C calls per page; apply the deltas and archive this
      change.
