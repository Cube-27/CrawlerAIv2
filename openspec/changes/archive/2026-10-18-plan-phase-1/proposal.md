# Change: master plan phase 1 — acquisition robustness

## Why

The golden-set failure analysis behind the master plan (owner-approved 2026-10-18, phase 1 "Acquisition robustness")
puts 32% of the missed values in acquisition. Three classes are engine defects rather than vendor blocks: a non-UTF-8
page crashes classification (selectolax decodes raw bytes as strict UTF-8 when it reads an attribute), the render-need
check runs the whole extraction, role C included, inside the fetch and still misses client-rendered and
stream-rendered listings (`hidden` containers, structured lists shorter than the DOM's), and a single-URL listing never
grows past its first screen in `auto`. Besides those, four front-ends repeat robots, rate, fetch and back-off with
three back-off rules between them, the browser rung loads every image, font and media file it does not read, a
challenge that never clears holds the browser for 40% of its budget, and a vendor block is retried like an engine
fault.

## What Changes

- **Decode once.** A body is decoded once at acquisition by HTML encoding sniffing (`capture_bundle.decode_html`), and
  `classify`, `interstitial`, `lacks_site_structure`, the listing rule and the challenge readers take the decoded text.
- **One polite fetch.** `services/polite.py` replaces `services/scrape.polite_fetch`, `worker/polite.py`,
  `services/fetching._polite_json`/`PoliteHttp` and the fetch composition of `worker/handlers/steps.py`: robots.txt,
  the host's rate, the fetch, the observation and one back-off rule (`acquire/politeness.backoff`: `Retry-After`, else
  30 s doubling per try, at most 15 min) for every caller, waiting in place or postponing as the caller does.
- **Structural render need.** `services/scrape_steps.ContentCheck` (a full extraction inside the fetch) is replaced by
  `RenderNeed`: an HTTP `ok` listing is rendered when its DOM shows fewer than `MIN_ITEMS` item blocks, when text inside
  `hidden` or `display:none` containers outweighs the visible text, or when a structured list names fewer entries than
  the DOM shows item blocks; a detail page as before (no offer data, owner #49). Role C runs once, on the kept capture.
- **Resource blocking and a bounded interstitial wait.** The browser rung aborts image, font and media requests by
  resource type (never by hostname) unless the page is captured as a file or the site opted out; a site whose
  resource-blocked render of a listing showed fewer item blocks than its HTTP page opts out. The interstitial wait is
  at most 10 s.
- **Bounded listing growth by default** for a single-URL listing scrape in `auto` that renders (scroll and structural
  next/load-more up to `records`, default 100), never for batch or crawl (owner decision 11; amends #52).
- **Blocked as an outcome.** A vendor-labelled block ends `blocked` with reason `challenge: <vendor>`; a worker task
  gets at most one retry after the back-off first; the eval import retries a page's acquisition up to 3 times with the
  back-off and keeps the best capture.

## Impact

- Capabilities: [acquisition](../../../specs/acquisition/spec.md), [rest-api](../../../specs/rest-api/spec.md),
  [jobs](../../../specs/jobs/spec.md), [evaluation](../../../specs/evaluation/spec.md).
- Code: `backend/src/crawlerai/acquire/` (`classify`, `challenge`, `http`, `browser`, `rungs`, `politeness`,
  `render_need`), `backend/src/crawlerai/adapters/challenges.py`, `backend/src/crawlerai/storage/capture_bundle.py`,
  `backend/src/crawlerai/services/` (`polite`, `fetching`, `scrape`, `scrape_steps`, `scrape_paging`, `extract`,
  `map`), `backend/src/crawlerai/worker/` (`handlers/steps`, `handlers/crawl`; `polite.py` deleted),
  `backend/src/crawlerai/eval/label_file.py`, `backend/src/crawlerai/cli.py`, the baseline migration (`site`).
- Owner decisions: master plan 2026-10-18 recommendations 11 (listing growth by default for single-URL scrapes) and 12
  (resource blocking by type, per-site opt-out); decision 7 deferred (no managed access or residential proxies:
  vendor blocks stay a `blocked` outcome naming the vendor).
