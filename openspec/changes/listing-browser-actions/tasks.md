# Tasks

## 1. Owner decision

- [ ] 1.1 Append owner decision #52 to `design/owner-decisions.md`; cite it in the §22 register entry and the
      non-goal in `design/overview.md` and in the acquisition requirement "Acquisition candidates stay unbuilt".

## 2. Request and validation

- [ ] 2.1 `ScrapeRequest.browser_actions` (`records` ≥ 1, default 100; optional `hint`), refused with 422 unless
      `page_kind` is `listing`, with `max_age` > 0, or with `fetch.method_hint` `http`; batch refuses the member.

## 3. Browser tab and paging driver

- [ ] 3.1 Item groups in `acquire/items.py` (every group, not only the largest by count) and the tab seam in
      `acquire/browser_tab.py`: read the DOM, measure rendered areas, click, scroll, navigate, count requests, keep
      a document state as a capture; isolated world only, no new launch or context option.
- [ ] 3.2 `crawl/paging.py`: item group by rendered area, item identity, the mechanisms (next and numbered links,
      numbered pager controls, scroll, the control after the last item), the wait for an action's effect, the caps,
      the stop reasons and which document states are kept.
- [ ] 3.3 Browser-marked tests on synthetic local pages: numbered links, `rel=next`, AJAX pager, load more, show
      more in the DOM, infinite scroll, no paging, overshoot past `records`, the action cap; property tests of the
      driver over a fake tab.

## 4. Scrape

- [ ] 4.1 The scrape runs the driver for `browser_actions`, stores a capture, extraction and records per kept state,
      and answers with their records once each and the `browser_actions` report; usage counts the browser seconds.
- [ ] 4.2 `next_page_url` of a listing from the first pagination candidate (`dom` candidate on the page).

## 5. Playground

- [ ] 5.1 Scrape options: Records and Paging hint, shown for page kind Listing only, mapped to `browser_actions`;
      `make api-client`.

## 6. Archive

- [ ] 6.1 Apply the deltas to `openspec/specs/` and archive this change.
