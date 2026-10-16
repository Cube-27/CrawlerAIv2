# Design: ce1-acquisition

## Decisions

### D-1200 — Browser content-stable exit
- Date: 2026-10-16 · Change/PR: ce1-acquisition (#228) · Status: decided
- After `load`, the browser rung reads the page once a MutationObserver (`childList`, `characterData`, subtree) has
  seen no change for 2 s, or at network idle, whichever is first; the 90% settle share stays. Attribute changes are
  left out: animations toggle attributes every frame and kept the DOM from ever being quiet in the probe.
- The observer runs in Patchright's isolated world (shared DOM, separate globals), installed on first poll per
  document, so the page cannot see it. No action is taken on the page.
- Probe (7 pages, dev set): two pages that waited 41 s now read at 7-9 s, one at 31 s; error pages at 4-6 s.

### D-1201 — The main frame's latest document
- Date: 2026-10-16 · Change/PR: ce1-acquisition (#228) · Status: decided
- The exchange and raw body come from the latest non-3xx main-frame navigation response, not the first: the body read
  is the current document, so its status must be too. A navigation in flight keeps the wait going.
- For a 4xx/5xx document, network idle does not end the wait (only quiet content does), so a page that replaces
  itself after a countdown is followed. Structural (status class), no vendor strings, no actions (owner OQ5).
- Probe: the three challenge pages answering 403 never navigated within 40 s headless; the rule costs about 2 s per
  blocked render and serves them only where the challenge clears itself.

### D-1202 — Browser for an HTTP page without offer data
- Date: 2026-10-16 · Change/PR: ce1-acquisition (#228) · Status: decided
- Trigger, decided on the capture before extraction (so role C is not paid first): `auto`, HTTP `ok` (not 304), a
  detail schema that requires a `money` field, and no Offer entity (or subtype) and no `money` candidate from any
  collector (`resolve.pipeline.lacks_offer_data`). A conflicting or abstained price has candidates, so never fires.
- The caller passes the check to `acquire` (`needs_render`), since the schema sits above `acquire`. "More complete"
  is read at the same level: the render is kept when it is `ok` and holds offer data; else the HTTP page is kept.
- `site.fetch_method` is not changed (HTTP was `ok`), so every fetch of such a page pays one render.
- Probe (5 client-rendered pages): 3 of the 4 HTTP-`ok` pages hold offer data in the render; 1 holds none.

### D-1203 — The offer check shares the page's parse
- Date: 2026-10-16 · Change/PR: ce1-acquisition (#228) · Status: decided
- `services.scrape_steps.OfferCheck` keeps the parse of the capture it read, and the scrape, batch and crawl
  extractions read that parse (INV-26: one parse per page).
