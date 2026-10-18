# Design: master plan phase 1 — acquisition robustness

The owner approved the master plan's recommendations on 2026-10-18; phase 1 is its "Acquisition robustness". Its
approved decisions are cited as "owner (2026-10-18, master plan)"; the implementor's own are "decided (owner-delegated
2026-10-17)".

## Shape

- **One decoder.** `storage.capture_bundle.decode_html(body, headers, method)` decodes a body once per rung response;
  every classification rule (`acquire.classify`, `acquire.challenge`, `adapters.challenges`) reads that text.
- **One polite fetch.** `services.polite.polite_fetch` is generic in the fetch it runs (a page through `acquire`, an
  API request, a plain HTTP sitemap read, the listing rung): rules (`HostRules`, read by `ReadRules` in a connection
  or in a transaction of their own), a turn (`Waiting`: `IN_PLACE` for a caller that waits, `QUEUED` for a worker),
  the fetch, the observation, and the host paused by `politeness.backoff` when the fetch kept no `ok` answer after a
  429 or 503. It answers the fetch's result, `Refused(reason)` or `Later(wait)`; callers map those to their own
  outcomes (`services.fetching.fetch_now`, `worker.handlers.steps.fetch_queued`).
- **One page composition.** `services.fetching.PagePlan` + `page_fetch` build the `acquire` call (adapters, API recipe
  and its listing pages, render check, validators, growth) for both orchestrators.
- **Structural render need.** `content.render_need.listing_needs_render(page, over)` and
  `services.scrape_steps.RenderNeed`; `acquire.rungs.RenderCheck` is asked of a render `over` the HTTP page it would
  replace.

## Decisions

### D-1540 — The polite fetch lives in `services`, not `acquire`
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: the one polite fetch is `services/polite.py`; the page composition beside it in `services/fetching.py`.
- Alternatives: `acquire/polite.py`, as the master plan's table names it.
- Why: it reads robots.txt snapshots from the database and binds active configs' API recipes (`config_ir`), both above
  `acquire` in the import layers (`.importlinter`).
- Reversible: yes — a module move.

### D-1541 — One back-off rule for every fetch
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: `politeness.backoff(attempt, tries)`: the `Retry-After`, else `core.retry.backoff_delay(tries)` (30 s
  doubling), at most 15 min; None past 15 min (the work ends `blocked`). It replaces `asked_pause`, the worker's own
  Retry-After rule and the JSON path's; the queue's `retry_delay` became `backoff_delay`. Webhook delivery and LLM
  retries are not fetch back-offs and keep their rules.
- Alternatives: keep the per-caller rules with shared constants (the audit's "share constants but not policy").
- Why: master plan §4 item 5; one rule a reader finds in one place.
- Reversible: yes.

### D-1542 — A caller that waits waits in place up to one minute, and pauses the host after a slow-down
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: the services' first turn is waited for in place up to `IN_PLACE.bound` (1 min, D-1263's bound), and a turn
  further off ends `blocked`, reason `slow_down`, with nothing sent; a slow-down to a service's fetch pauses the host by
  the back-off, as a worker's did.
- Alternatives: wait for the first turn without bound (until the scrape's timeout), and pause nothing.
- Why: with one rule, a 429 asks every caller for the same pause; waiting it out in place would turn a polite refusal
  into a timeout.
- Reversible: yes.

### D-1543 — Render-need item blocks show more than their link
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: the "fewer than `MIN_ITEMS` item blocks" rule counts the blocks of `acquire.items.item_blocks` that hold an
  image or text in two or more runs (`items.shown_items`, the evidence D-1277 ranks groups by).
- Alternatives: count every block of the group, so three related-post links make a client-rendered listing look full.
- Why: structural; a list of bare links is chrome, not a listing's items.
- Reversible: yes.

### D-1544 — A listing render is kept when it lists more items than the HTTP page
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: besides "the check no longer holds", a listing render is kept when it lists more items (shown item blocks or
  structured entries, whichever is more) than the HTTP page; `RenderCheck` takes the page a render would replace.
- Alternatives: the plan's rule alone, which drops a render whose script wrote structured rows into a still empty grid.
- Why: owner #54, "the capture with more rows is kept", stated structurally now that no extraction runs in the check.
- Reversible: yes.

### D-1545 — The listing-shell class stays an outcome; the render check covers `ok` listings
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: `classify`'s listing-shell rule (no items and no structured rows) keeps deciding the outcome class; the
  structural check judges HTTP `ok` listings, including ones whose structured data lists every row but whose document
  shows no item blocks (owner (2026-10-18, master plan) supersedes #54's "never for an HTTP page with rows").
- Alternatives: move the listing rule out of `classify` into the render check.
- Why: `shell` is a reported outcome (INV-24) with its own last-page rule (D-1261).
- Reversible: yes.

### D-1546 — Concealed text is the `hidden` attribute and inline `display: none`
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: the hidden-text rule counts text under `hidden` or an inline `display: none` (`content.text.concealed`,
  shared with the cleaned text's hiding rules); `aria-hidden` and never-rendered elements count in neither weight.
- Alternatives: every rule of `content.text.hidden`, `aria-hidden` included.
- Why: `aria-hidden` hides from assistive technology, not from view (WAI-ARIA 1.2), and decorative duplicates are common.
- Reversible: yes.

### D-1547 — Resource blocking by request type, opted out per site on lost items
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: owner (2026-10-18, master plan) for blocking; decided
  (owner-delegated 2026-10-17) for the shape
- Decision: a context route aborts `image`, `font` and `media` requests (`FetchPolicy.block_resources`), never by host,
  and not for a screenshot or PDF; a resource-blocked render of a listing that lists fewer items than its HTTP page sets
  `site.load_all_resources`, read into later policies. No second render in the same fetch.
- Alternatives: also block tracker hosts (a host list, C4); re-render at once without blocking.
- Why: recommendation 12; a host list is a list that grows one incident at a time.
- Reversible: yes — the column is in the baseline migration (greenfield).

### D-1548 — The interstitial wait is at most 10 s
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: `min(0.4 × browser_timeout_s, 10 s)`; an unmeasured starting point.
- Alternatives: keep 40% (18 s at the default 45 s), which every challenge that never clears headless spent in full.
- Why: master plan §3.1 "bound the interstitial wait"; backlog (#244).
- Reversible: yes.

### D-1549 — Default growth where the scrape renders
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: owner (2026-10-18, master plan) decision 11; decided
  (owner-delegated 2026-10-17) for the shape
- Decision: a scrape for `records` of a listing in `auto` without `browser_actions` gets `Growth(BrowserActions())` on
  its browser rung (where `acquire` renders on evidence, or the site is remembered as `browser`), within the actions'
  share of `timeout_s`, the attempt after an HTTP refusal or shell included, which then opens no site session; not
  with a screenshot or PDF; batch, crawl and the eval import (the worker path, D-1460) never grow.
- Alternatives: always fetch single-URL listings with the listing rung (the browser by default, against #12).
- Why: "browser on evidence" stays; growth is reading, not acting.
- Reversible: yes.

### D-1550 — A vendor block names the vendor; one worker retry
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: owner (2026-10-18, master plan) decision 7 deferral; decided
  (owner-delegated 2026-10-17) for the shape
- Decision: a fetch kept `blocked` whose latest vendor-labelled attempt names a vendor ends with reason
  `challenge: <vendor>`; a worker task retries it once after `backoff_delay(1)` through the site's pool as configured,
  then ends `blocked`; a caller that waits gets the outcome at once ("at most one" retry).
- Alternatives: retry in place inside a scrape (30 s inside a 60 s default timeout).
- Why: a vendor block is an outcome, not an engine fault; no evasion (#50).
- Reversible: yes.

### D-1551 — The eval import keeps the closest of up to three captures
- Date: 2026-10-18 · Change/PR: plan-phase-1 · Status: decided (owner-delegated 2026-10-17)
- Decision: a page not reached is fetched up to 3 times in all, waiting 30 s then 60 s; the kept capture is the first
  `ok`, else the closest (`shell`, `blocked`, `not_found`, `error`, earliest of equals); a fetch that sent nothing
  (robots.txt, the guard) is not repeated.
- Alternatives: keep the last capture.
- Why: master plan §3.1; two golden pages flipped to `blocked` at import.
- Reversible: yes.
