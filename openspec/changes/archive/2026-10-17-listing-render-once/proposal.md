# Change: one browser render for a listing with no rows at HTTP

## Why

The HTTP listing-shell rule (D-0933, D-1158) sends a listing to the browser only when its HTTP body shows no repeated
items and no structured data that lists items. A client-rendered listing whose HTTP body holds other repeated linked
blocks (related posts, search filters) stays `ok` at HTTP, and extraction reads no rows from it: 2 of 10 listings in
the 40-page site test, about 7 pages in the tough-site run (D-1245). The owner chose option (a) of D-1245 on
2026-10-17 (owner decision #54): in `auto`, such a listing gets one browser render and the capture with more rows is
kept, the listing counterpart of owner #49's render for detail pages without offer data.

## What Changes

- Owner decision #54 in `design/owner-decisions.md`; D-1245 answered, removed from the open owner items, and
  `OPEN_QUESTIONS.md` row 33 marked answered.
- The owner #49 render check (`services/scrape_steps.py`) also covers a listing schema: it runs the page's own
  extraction (structured rows, the config's rows, role C) on the HTTP capture, and asks for the render when that gives
  no rows; the render is kept when its extraction gives rows. The check keeps each extraction it ran, so the kept
  capture is extracted once (role C at most once per capture).
- Only in `auto`, at most one render, never for an HTTP page with rows; a listing scrape with browser actions
  (owner #52) is rendered already and is not checked.

## Impact

- Capabilities: [acquisition](../../../specs/acquisition/spec.md) ("Browser on evidence").
- Design: Appendix A #49, #54; D-1202, D-1245.
- Files: `backend/src/crawlerai/resolve/pipeline.py`, `services/{scrape,scrape_steps}.py`,
  `worker/handlers/{steps,scrape,crawl}.py`, `acquire/rungs.py` (docstring).
