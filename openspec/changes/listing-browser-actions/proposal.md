# Change: browser actions for a single-URL listing scrape

## Why

A listing scrape returns only the rows its first document shows: 20 to 50 of a catalogue or job board whose further
rows sit behind numbered pages, a next link, a load-more control or infinite scroll. The owner admitted browser
actions from the candidates register (§22) narrowly, on 2026-10-17 (Appendix A #52): opt-in, for a single-URL
listing scrape only, the engine may scroll and click structural paging controls to collect more rows. A pre-build
probe on real listings (outside the repo) found structural rules that picked a working mechanism on every testable
site without a word list. Separately, the listing presets' `next_page_url` is never filled: pagination finds the
next pages, but no candidate reaches the field (0 of 18 listing outputs in a 40-site run).

## What Changes

- Owner decision #52 in `design/owner-decisions.md`; the §22 register entry and the non-goal in
  `design/overview.md`, and the acquisition requirement "Acquisition candidates stay unbuilt", cite it.
- `POST /v1/scrape` takes an optional `browser_actions` member, `{records, hint}`: `records` is a soft row target
  (default 100; the run stops once it has at least that many rows), `hint` one of `load_more`, `show_more`,
  `pagination`, `next`, `scroll`. Refused with a 422 problem unless `page_kind` is `listing`; batch has no such member.
- The browser rung gains a tab seam (`acquire/browser_tab.py`): the rendered page, read and acted on only through
  Patchright's isolated world, with each kept document state a capture of its own. Nothing about the browser's
  launch, context or identity changes (INV-42–INV-44).
- A paging driver (`crawl/paging.py`) finds the item group (the repeated items of `acquire/items.py`, ranked by
  rendered area), each item's identity, and the mechanism: next pages by `rel=next` or the +1 integer link
  (`resolve/pagination.py`), a numbered pager's integer controls, scroll, or the control after the last item. It
  waits for each action's effect, stops at the target, at the end of the list or at its caps, and reports why.
- The scrape stores a capture, an extraction and records for each kept document state, and answers with the union
  of their records and a `browser_actions` report.
- A listing's `next_page_url` field takes the first pagination candidate as a `dom` candidate.
- The playground's Scrape options show Records and Paging hint for page kind Listing only.

## Impact

- Capabilities: [acquisition](../../specs/acquisition/spec.md), [extraction](../../specs/extraction/spec.md),
  [rest-api](../../specs/rest-api/spec.md), [frontend](../../specs/frontend/spec.md).
- Design: Appendix A #21 (amended by #52), §22, §7.1, §8.6.
- Files: `backend/src/crawlerai/acquire/{browser,browser_tab,items,types}.py`, `crawl/paging.py`,
  `resolve/{pagination,pipeline}.py`, `services/{scrape,scrape_paging,runtime}.py`, `frontend/src/screens/playground/scrape/`,
  the regenerated API client.
