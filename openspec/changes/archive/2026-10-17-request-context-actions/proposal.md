## Why

Callers cannot reach pages that need their own request context (a session cookie, an API token, a chosen proxy pool),
pages that show their content only after a wait or a click, or choose whether a stored capture is reused. The owner
delegated the design (2026-10-17) and asked for a crawler that is usable beyond the backlog; this change adds the caller
request context and general page actions as one generic layer of acquisition, on every surface.

## What Changes

- `fetch` of scrape, batch, crawl and extract takes `headers`, `cookies`, `wait_for`, `actions` and `cache`; its
  `proxy_pool` is checked against the configured pools (422). Header and cookie values are secrets: never in captures,
  logs or answers.
- The HTTP and JSON rungs send the caller's headers and cookies to the page's own host only; the browser gets the
  cookies only (`add_cookies` before the navigation), never headers (INV-44 unchanged).
- Page actions: an ordered list of at most 20 steps (`wait`, `click`, `scroll`, `press`, `type`) run in the browser
  after the page settles and before it is read, each with its own timeout, reported per step on the attempt. A `type`
  into a password or credential field is refused. Batch and crawl apply them to every page.
- `cache`: `default` (reuse within `max_age`), `bypass` (always fetch), `only` (a stored capture or fail).
- Surfaces: REST (OpenAPI, `make api-client`), MCP tools (they take the request models), `crawlerai fetch` flags, and
  an Advanced section with an actions editor in the playground's Options.
- §22 "browser actions" admitted for general caller steps (owner delegation 2026-10-17); INV-29 amended for caller
  cookies.

## Impact

Capabilities: acquisition, rest-api, jobs, frontend. Code: `acquire/` (types, curl client, browser, page steps),
`config_ir/page_actions.py` (the step vocabulary), `services/` (scrape, batch, crawl, extract, jobs), worker handlers,
`cli.py`, `frontend/src/screens/playground/`. No schema migration.
