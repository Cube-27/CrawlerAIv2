# Design: one browser render for a listing with no rows at HTTP

## Shape

- **One check.** `services/scrape_steps.ContentCheck` (owner #49's `OfferCheck`, renamed) is the `needs_render` of
  `acquire`. A detail schema keeps `lacks_offer_data`; a listing schema runs `extract_page` on the capture (structured
  rows, the config's rows, then role C) and asks for the render when `resolve.pipeline.lacks_rows` holds. It keeps
  each capture's parse and each listing extraction by capture id.
- **Reuse.** The scrape (`_derive`, `known`) and the worker (`extract_records`) take the check's extraction of the
  kept capture (`checked_extraction`) instead of extracting it again. The worker's `fetch_page` takes the role C
  client (`llm`) for that.
- **Kept capture.** `acquire.rungs._better` is unchanged: the render is kept when it is `ok` and the check no longer
  holds on it, which for a listing whose HTTP capture gave no rows is "the render gives more rows".

## Decisions

### D-1246 — "No rows" is judged on the extraction, role C included
- Date: 2026-10-17 · Change/PR: listing-render-once (#242) · Status: decided
- Decision: the check runs the page's own extraction, role C included, and renders when it gives no rows. Role C
  is asked at most once per capture: the check keeps the extraction and the kept capture is stored with it. A
  rendered page is read by role C twice, once per capture, only when its HTTP capture gave no rows.
- Alternatives: a pre-LLM judgement (no structured and no config rows) renders every listing whose rows come only
  from role C (13 of 15 listings with rows in reference eval round 2, D-1024) and cannot tell which capture has more
  rows; a structural test of the item blocks (D-1245 option (b)) was not chosen by the owner.
- Why: the repeated blocks of a client template (related posts, filters) cannot be told from items before role C
  reads them; owner #54 accepted one more role C call on listings that gave nothing.
- Reversible: yes

### D-1247 — One check for detail and listing pages
- Date: 2026-10-17 · Change/PR: listing-render-once (#242) · Status: decided
- Decision: `OfferCheck` becomes `ContentCheck` (`content_check`) with an optional role C hook; no second render path
  (C8). Scrape, batch and crawl pass it to `acquire` as before. A listing scrape with browser actions (owner #52) goes
  through the listing rung, which takes no check, so it is never rendered twice.
- Why: owner #54 is the listing counterpart of owner #49; the render decision stays in one place.
- Reversible: yes

### D-1248 — A failed extraction or role C call counts as no rows
- Date: 2026-10-17 · Change/PR: listing-render-once (#242) · Status: decided
- Decision: an extraction with outcome `error` gives no rows: on the HTTP page it asks for the render, and a render
  whose extraction fails is never kept over the HTTP page. A role C call that fails (provider unavailable, budget)
  leaves the extraction without rows too, so the page is rendered: the render may hold structured rows that need no
  role C.
- Alternatives: never render on a failed HTTP extraction (as `lacks_offer_data`); then `_better` would keep a render
  whose extraction failed, since the check would no longer hold on it (review of #242).
- Why: the render is kept only when its extraction gives rows, as owner #54 states; the extraction is the one the
  page is stored with.
- Reversible: yes

### D-1249 — The HTTP capture's role C calls are charged, not stored, when the render is kept
- Date: 2026-10-17 · Change/PR: listing-render-once (#242) · Status: decided
- Decision: when the render is kept, the role C calls made on the HTTP capture count as the job's usage (the client
  commits them, D-0346) but have no stored extraction; only the kept capture's extraction and records are stored.
  A recurring job's check runs before the unchanged-content test, so an unchanged listing without structured rows
  still pays its role C call (follow-up).
- Why: one capture and one extraction per fetch, as before; usage stays truthful.
- Reversible: yes
