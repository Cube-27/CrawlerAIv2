## ADDED Requirements

### Requirement: Scrape browser actions
`POST /v1/scrape` SHALL take an optional `browser_actions` (`records`, a soft row target, default 100; `hint`:
`load_more`, `show_more`, `pagination`, `next` or `scroll`), refused 422 unless `page_kind` is `listing`, and with
`max_age` > 0 or `method_hint` `http`; batch has no such member. With `records` asked, each further kept document
state is a capture with its own extraction under its own URL, stored once the first state's did not fail; the answer
lists records once each (a failed further state makes it `partial`), `capture_id` and formats are the first state's,
and `browser_actions` reports the mechanism, stop reason, actions, pages and items. Refs: owner #52, D-1218, D-1222, D-1223.
#### Scenario: Detail page
- **WHEN** a scrape with `page_kind` `detail` sets `browser_actions`
- **THEN** the answer is a 422 problem naming `browser_actions` and no job is created
