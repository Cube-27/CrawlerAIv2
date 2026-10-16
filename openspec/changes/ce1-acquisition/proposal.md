# Change: browser waits that end on content, and the browser for client-rendered offers

## Why

The round-1 evaluation of the reference set found three acquisition defects. The browser rung waits for network
idle up to 90% of `browser_timeout_s`, and pages with steady background traffic never reach it, so a render takes
about 41 s where the content is stable after 5-15 s. The rung reads the status of the first document even when that
document navigates itself to another one. And a detail page whose offer is rendered by script answers HTTP `ok`
with no price anywhere in the capture, so it never reaches the browser, the only rung that could read it (owner
answer OQ2, 2026-10-16).

## What Changes

- The browser rung reads the page once `load` has fired and then either the DOM's structure and text have been
  unchanged for 2 s, or the network is idle (a 2xx/3xx document only); the hard cap stays.
- The browser rung reads the main frame's latest document: when the first document navigates itself (a 4xx page
  that reloads after a countdown, an interstitial that replaces itself), the response and body of the document the
  navigation lands on are kept. A wait rule only: no actions, no vendor strings.
- In `auto`, an HTTP `ok` detail page whose schema requires a money field and whose capture holds no Offer entity and
  no candidate for any money field is fetched once more in the browser; the browser capture is kept when it is `ok`
  and holds offer data.

## Impact

- Capability: [acquisition](../../specs/acquisition/spec.md) (delta in `specs/acquisition/spec.md`).
- Files: `backend/src/crawlerai/acquire/browser.py`, `acquire/rungs.py`, `resolve/pipeline.py` (the offer-data
  check), `services/scrape.py`, `worker/handlers/steps.py`.
- Owner answers OQ2 and OQ5 (2026-10-16), recorded as `owner-decisions.md` #48.
