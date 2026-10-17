# Tasks

## 1. Request context

- [x] 1.1 `fetch.headers`, `fetch.cookies` (secret values), `fetch.wait_for`, `fetch.cache` and a checked
      `fetch.proxy_pool` on scrape, batch, crawl and extract; refusals are 422. (#262)
- [x] 1.2 The HTTP and JSON rungs send caller headers and cookies to the page's host only; the browser adds the cookies
      to its context before navigating; no site session is taken or opened by a fetch with a caller context. (#262)
- [x] 1.3 Header and cookie values are redacted in captures, job requests as answered, and logs. (#262)
- [x] 1.4 Cache modes in the scrape service and the workers. (#262)

## 2. Page actions

- [x] 2.1 One step vocabulary (`config_ir/page_actions.py`) translated to the browser's steps; cap 20, per-step timeouts,
      password and credential fields refused. (#262)
- [x] 2.2 The browser rung runs the steps after the settle and before the read, and reports each step on the attempt;
      batch and crawl apply them per page. (#262)

## 3. Surfaces

- [x] 3.1 MCP tools and `crawlerai fetch` flags; OpenAPI client regenerated. (#262)
- [x] 3.2 The playground's Options: an Advanced section (headers, cookies, proxy pool, wait for, cache) and an actions
      editor. (#262)
- [x] 3.3 Live verification: a click that reveals content, a cookie-gated page, `wait_for` on a JS-rendered page,
      `cache` `only` and `bypass`. (#262)
