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
  `no_mechanism`, `action_cap`, `time_cap`, `click_intercepted`, `robots`, `error`.
