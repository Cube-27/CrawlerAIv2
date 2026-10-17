# Design: listing browser actions

## Shape

- **Request.** `browser_actions: {records: int ≥ 1 = 100, hint: Hint | None}` on `ScrapeRequest` only
  (`acquire/types.py` `BrowserActions`, so the rung and the service share one model).
- **Tab seam.** `acquire/browser_tab.py` defines `Tab`, the few things the driver does to a rendered page: its URL,
  its serialized DOM, the rendered area of elements named by element-index paths, a click, a scroll, a navigation,
  the count of requests the page made, a mutation counter, and `keep()`, which turns the current document state into
  a `FetchResult` of its own. The Patchright implementation evaluates only in the isolated world (INV-44), marks
  nothing in the page's DOM, and opens the context exactly as `fetch_browser` does (it reuses its open, navigate and
  settle steps), so INV-42–INV-44 hold unchanged.
- **Driver.** `crawl/paging.py` decides from the serialized DOM, parsed with lxml as every other reader does:
  `acquire/items.item_groups` gives the groups of repeated linked items, the tab's areas rank them (the largest
  rendered area is the listing; probe class A), and each item's identity is its first link no other item shares
  (class B). Next and numbered links come from `resolve/pagination.next_page_candidates`, so the pagination rule has
  one home (C8). The driver is a loop over `Tab`, so its stop and keep rules are property-tested over a fake tab.
- **Result.** `PagedFetch(pages: tuple[FetchResult, ...], report: ActionsReport)`. `report` holds `mechanism`,
  `stop`, `actions`, `pages` and `items` (distinct identities seen).
- **Kept states.** A state is kept (`Tab.keep`) right before an action that replaces the items (next, numbered
  link or pager control) when it shows an identity no kept state holds, and once at the end on the same test.
  Scroll and load-more grow one document, so they keep one state. Each kept state is its own capture, extraction and
  records under the scrape's one task: every record keeps a locator into the document it came from (SPEC-05 §4.3).

## Mechanisms (structural rules, C2)

- **next / pagination by link.** `rel=next` (HTML §4.6.7) then the +1 integer link (`resolve/pagination.py`),
  followed by navigating the tab to it; the gate checks robots.txt and waits for the site's rate first.
- **Numbered pager controls.** A parent after the last item (document order), outside `header`/`footer` and the
  `banner`/`contentinfo` roles (a pager may sit in `nav`; class D), with ≥ 3 control children (`a[href]`, `button`,
  `[role=button]`, HTML §4.6.1, §4.10.6, WAI-ARIA 1.2) of which ≥ 2 are labelled only by an integer (the page's
  ordinal). The current page is the control with `aria-current` (WAI-ARIA 1.2 §6.7), else the pages turned so far
  plus one; `pagination` clicks the integer one higher, `next` the control right after the current one.
- **Scroll.** Scroll the document to its end (CSSOM View `scrollTo`); two rounds without growth rule it out
  (class J).
- **Load more / show more.** The visible enabled controls after the last item, inside the group's container or its
  following siblings, up to three ancestor levels, outside items, chrome and forms; the first three are tried in
  order. A click that changes the URL is undone (class F). Growth with no request since the click is `show_more`,
  else `load_more`; both hints use this mechanism.
- No text is matched: no "Load more", "Next" or consent words (C4). An overlay that intercepts a click stops the
  run with `click_intercepted`.

## Waits and caps

- After an action, poll every 250 ms (re-reading the DOM only when the mutation counter moved) until a new identity
  appears or the first item changes; at most 5 s (class C). Navigation waits for `domcontentloaded` first.
- At most 40 actions; the time cap is min(60 s, half the scrape's `timeout_s`), so extraction of the kept states
  still fits in the scrape's budget (`timeout_s` ≤ 120, D-0028).
- Stop reasons: `records`, `end` (two no-growth rounds, or a pager with no further page), `no_items`,
  `no_mechanism`, `action_cap`, `time_cap`, `click_intercepted`, `not_admitted` (robots.txt, or a next page on
  another host), `error`.

## Decisions

### D-1218 — `browser_actions` is one optional request object
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: `ScrapeRequest.browser_actions: {records: int ≥ 1 = 100, hint?}`; its presence opts in. Refused (422)
  unless `page_kind` is `listing`, with `max_age` > 0 (a reused capture runs no actions) or with `method_hint` `http`.
  The response carries `browser_actions: {mechanism, stop, actions, pages, items}` only when asked.
- Alternatives: top-level `records`/`hint` members (`records` already names a format and the answer's records).
- Why: owner #52 names the two settings; one object keeps them together and the opt-in explicit.
- Reversible: yes — an API shape change while there are no users (greenfield).

### D-1219 — A tab seam in `acquire`, the driver in `crawl`
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: `acquire/browser_tab.py` exposes `Tab` (DOM, areas, click, scroll, goto, back, data requests, mutations,
  keep) over the page `browser.rendered` opens; `crawl/paging.py` decides from its own lxml parse. Elements are named
  by element-index XPath paths plus their tag, checked in the browser; nothing is written into the page's DOM.
- Alternatives: the probe's in-page JavaScript detector, marking elements with attributes (visible to the page and
  in the capture).
- Why: the layering keeps `acquire` below `resolve` and `content`, so pagination and item detection are reused (C8),
  and the driver is property-tested over a simulated tab.
- Reversible: yes.

### D-1220 — The listing is the visible group with the largest rendered area
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: `acquire.items.item_groups` (every group; `item_blocks` keeps the largest by count) ranked by the summed
  area of the members the browser renders visible; hidden members are not on the page yet. An item's identity is
  its first link no other item shares, else its first link.
- Alternatives: count ranking (picked a sidebar list in the probe, class A).
- Why: probe classes A and B.
- Reversible: yes.

### D-1221 — Caps and waits
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: 40 actions; poll every 250 ms for up to 5 s per action (re-reading only when the mutation count moved);
  two rounds without new items end scroll and load-more; three control candidates; a 4 s click timeout.
- Alternatives: the probe's 30 actions (reached only 93 rows on 3–6-per-scroll pages).
- Why: probe conclusions (classes C, J; caps).
- Reversible: yes.

### D-1222 — The actions get min(60 s, half the scrape's timeout)
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: the driver's deadline is min(60 s, `timeout_s` / 2) from the start of the paged fetch.
- Alternatives: the probe's 120 s per site (past the scrape's own cap, D-0028).
- Why: the kept states must still be extracted and stored inside `timeout_s`, or the whole scrape is a 504.
- Reversible: yes.

### D-1223 — Each kept state is a capture, an extraction and records under the one task
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: a state is kept before an action that replaces the items (a page turn, or after a growth dropped items)
  and once at the end, when it shows an item no kept state holds. Each is stored as its own capture with its own
  extraction and records, keyed by its own URL, when `records` is asked and the first state's extraction did not fail;
  `capture_id` and the formats are the first state's; the answer lists records once by id, each with its own state's
  confidence, and a further state whose extraction failed makes the outcome `partial`.
- Alternatives: merging documents into one capture (locators would no longer read back, SPEC-05 §4.3).
- Why: every record stays replayable from the document it came from (G7).
- Reversible: yes.

### D-1224 — Mechanism order and hints
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: without a hint: page turns (`rel=next`, the +1 integer link, then the pager), scroll, then the control
  after the items. `next` and `pagination` share page turns (`next` clicks the control after the current page,
  `pagination` the ordinal one higher); `load_more` and `show_more` share the control rule, and the report says
  `show_more` when the click grew the list with no fetch, XHR or document request.
- Alternatives: separate show-more detection (no real example found in the probe, class K).
- Why: the probe's no-hint order picked a working mechanism on every testable site.
- Reversible: yes.

### D-1225 — Overlays are reported; next pages stay on the host
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: a click Playwright cannot deliver in 4 s stops the run with `click_intercepted` (no JavaScript click
  fallback, no overlay dismissal); a control click that changes the URL is undone; each action waits for the site's
  rate, and a navigation is admitted only on the listing's host when robots.txt allows it (else `not_admitted`): a
  link's URL before it is followed or its control clicked, a page a script navigated to once it shows (then left).
- Alternatives: the probe's `el.click()` fallback (works around an overlay, which owner #52 rules out).
- Why: owner #52; SPEC-02 §4.6.
- Reversible: yes.

### D-1226 — `next_page_url` from `rel=next` only
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: a listing schema's page-level `next_page_url` takes the first `rel=next` link as a `dom` candidate with
  its element's locator; the +1 integer link stays a next-page candidate for crawls but fills no field.
- Alternatives: the first pagination candidate of either kind (the numbered rule infers, the page does not state).
- Why: HTML §4.6.7 states the next document; an inferred value would break C7.
- Reversible: yes.

### D-1227 — Browser action options are disabled, not hidden, outside Listing
- Date: 2026-10-17 · Change/PR: listing-browser-actions (#241) · Status: decided
- Decision: Scrape's Options always show the Browser actions switch, Records and Paging hint; they are enabled only
  for page kind Listing, and the request carries `browser_actions` only then.
- Alternatives: showing the rows only for Listing (moves the grid when the page kind changes).
- Why: the layout never shifts on interaction (frontend spec).
- Reversible: yes.
