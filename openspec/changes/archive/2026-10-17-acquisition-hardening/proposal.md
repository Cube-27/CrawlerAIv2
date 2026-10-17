# Proposal: acquisition-hardening

## Why

Six acquisition follow-ups in `openspec/backlog.md` (#52, #64, #225, #228, #229, #242) lose pages or time on tough
sites: a client-rendered site pays for HTTP and the browser on every fetch, a listing shell whose render fails loses
the rows role C reads from its HTTP page, a 503 challenge document never reaches the browser, every structureless 403
waits 18 s in the browser whether or not it can navigate, and `fetch_json` ignores the site's proxy pool.

## What Changes

- A browser `ok` kept over an HTTP page that lacked what the caller reads (owner #49, #54) sets the site's remembered
  method to `browser`, as an HTTP shell or block already does; the 7-day re-check returns it to HTTP.
- An HTTP listing shell kept with no browser outcome is the fetch's last page and is extracted (`ok`) when it is a
  shell by the listing rule alone.
- A 503 document that `classify.interstitial` judges to stand in for the page gets one browser attempt, after the
  site's `Retry-After` (else the first backoff) is waited out through the site's limiter; 429 gets none.
- Interstitials are judged by structure: a 403/429/503 HTML document that can navigate itself (script or refresh) and
  is no page of the site (a refresh, no site structure, or no link to another page of its host). The browser waits for
  the next main-frame commit by event, and does not wait on a refusal that cannot navigate.
- `fetch_json` goes through the policy's proxy pool over CONNECT tunnels, like the other rungs.
- The browser rung checks a body's wire size before reading it, and a JSON body's size before reading it.

## Impact

- Capability: acquisition (spec delta).
- Code: `acquire/` (rungs, classify, browser, api, politeness, new tunnel module, socks_guard), the services' and the
  worker's admission (`services/fetching.py`), the processes that build the JSON rung (`cli.py`,
  `services/runtime.py`).
- No API, schema or database change.
