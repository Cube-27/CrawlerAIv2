# Tasks: antibot-stack

## 1. B1: one client, adaptive rate, pools, labels

- [x] 1.1 Owner decision #58 and the §22 edit admitting the anti-bot measures chosen (no CAPTCHA solving, no real
  Chrome); acquisition spec delta (#249)
- [x] 1.2 `acquire/curl_client.py`: one curl_cffi session builder, guard (pinned or CONNECT tunnel), caps, reasons,
  cookies and redirects, used by `fetch_http` and `fetch_json`; `fetch_json` ported from httpx; the httpx tunnel
  transport removed (#249)
- [x] 1.3 JSON calls: per-request headers merged into the impersonation defaults, Fetch Metadata, `Referer`, `Origin`,
  `Priority` and a `fetch()`'s header order (#249)
- [x] 1.4 Startup check: the impersonation target against the installed Patchright Chromium major (warn, nearest
  profile when unset) (#249)
- [x] 1.5 Per-host adaptive rate in `politeness.py`, fed by the worker and the services (#249)
- [x] 1.6 Proxy pools of several endpoints, `rotate`/`sticky`, per-endpoint health quarantine; INV-16 tests over every
  endpoint (#249)
- [x] 1.7 `acquire/challenge.py` structural signal, `adapters/challenges.py` vendor signatures, `AttemptRecord.challenge`
  and per-label counts (#249)

## 2. B2: site session cookie handoff

- [ ] 2.1 `acquire/session.py`: `SiteSession` (site, registrable domain, proxy endpoint, user agent, jar, 30 min,
  200 fetches) in worker memory, keyed by site and proxy endpoint; `FetchCookies.seed()`
- [ ] 2.2 Browser rung: after an `ok` that follows a blocked or shell HTTP attempt, a read-only export of the context's
  cookies and the user agent into the session when the challenge label is portable or unlabelled
- [ ] 2.3 HTTP, JSON and recipe rungs use the session (jar, sticky endpoint, user agent); `blocked` drops it;
  `remember_fetch_method` keeps HTTP while a session serves
- [ ] 2.4 INV-29 amendment applied with cross-site, cross-proxy and no-persistence tests
