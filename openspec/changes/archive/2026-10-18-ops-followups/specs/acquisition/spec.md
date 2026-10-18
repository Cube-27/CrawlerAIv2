## MODIFIED Requirements

### Requirement: Listing browser actions
Only for a scrape that asks for them, the browser rung SHALL run the caller's `fetch.actions` and `wait_for` on the
settled page first (the site's API recipe is not used then), and then act on the item group (the
`acquire/items.py` group with the largest rendered area; on a page with no linked items, the rows of the first series
of its latest data calls, `collect/network_match.py`) through Patchright's isolated world (`crawl/paging.py`): the
hinted mechanism, else next or numbered links, a numbered pager's integer controls, scroll (two rounds), then the
visible control after the last item; it waits up to 5 s per action for new items or a new first item, keeps a document
state before each page turn, and before each scroll or control click a state it drops again when the state after still
shows all its items, and stops at `records` distinct items, at the list's end, at 40 actions or at its time cap, with
the reason. A control click that changes the URL is undone and not taken as load-more. (Previously: the caller's steps
were refused with browser actions.) Refs: owner #52, D-1218–D-1225, D-1404, D-1405, D-1513.
Enforced by: `tests/unit/test_paging_browser.py` (synthetic pages per mechanism) and `tests/property/test_paging.py`;
active.
#### Scenario: Load-more control
- **WHEN** a listing shows 20 items and a button after the last one adds 20 per click, and `records` is 50
- **THEN** the run clicks it twice, stops with reason `records`, and keeps one capture holding 60 items
#### Scenario: Nothing to page
- **WHEN** a listing shows 12 items and no next link, pager, growth on scroll or control after its items
- **THEN** the run stops with reason `no_mechanism` and keeps one capture
#### Scenario: Virtualised list
- **WHEN** a scroll listing of 48 items keeps only its last 16 in the document
- **THEN** the kept captures together hold all 48 items
#### Scenario: Consent layer
- **WHEN** a load-more listing sits under a layer whose button removes it, and the caller's first step clicks that button
- **THEN** the run clicks the control to the list's end, and the first kept state's attempt reports the step as `done`
