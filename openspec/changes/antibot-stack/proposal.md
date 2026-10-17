# Proposal: antibot-stack

## Why

Blocked and shell outcomes are the main way acquisition loses pages, and the stack that meets them is uneven. The JSON
rung, which adapters and API recipes use, speaks with Python's TLS stack over HTTP/1.1 and a `python-httpx` user agent,
which bot managers refuse at the edge before the application sees the request. Its calls also do not carry the headers a
page's own `fetch()` sends. A host that answers 429 keeps getting requests at the configured rate once its pause is
over. A pool holds one proxy, with no way to rotate or to leave out a failing endpoint. Nothing records which challenge
refused a page, so nobody can tell which measure would help. The owner delegated the admission of anti-bot measures
from §22 on 2026-10-17 (owner decision #58). CAPTCHA solving and real Chrome stay out.

## What Changes

- **B1 (this PR):**
  - one curl_cffi client (`acquire/curl_client.py`) for the HTTP and JSON rungs: Chrome impersonation, the SSRF guard
    (also through a CONNECT tunnel), caps, reasons and cookies, in one place;
  - JSON calls send what a page's script would send: the impersonation's identity, Fetch Metadata, `Referer`, `Origin`,
    `Priority`, in the header order of a `fetch()`;
  - a startup check matches the impersonation target to the installed Patchright Chromium major;
  - a per-host adaptive rate (multiplicative backoff on 429/503/challenge, slow recovery);
  - proxy pools with several endpoints, `rotate` or `sticky`, and per-endpoint health quarantine;
  - challenge labels on attempts: a generic structural signal, plus vendor signatures kept as adapter data.
- **B2 (next PR):** an in-memory site session that hands the cookies of a browser solve to later HTTP and JSON fetches
  of the same site and proxy endpoint. It is never persisted or captured, and it is dropped on `blocked` (an INV-29
  amendment).

## Impact

- Capability: acquisition (spec delta). Design: `openspec/design/overview.md` §22 and owner decision #58.
- Code: `acquire/` (new `curl_client`, `challenge` and `impersonate`; `http`, `api`, `politeness`, `outcome` and `types`
  ported or extended; `tunnel` loses its httpx transport), `core/proxy.py`, new `core/proxy_health.py`, new
  `adapters/challenges.py`. Small hooks in `worker/polite.py` and `services/` feed the adaptive rate. `cli.py`,
  `services/runtime.py` and `eval/cli.py` resolve the impersonation target.
- API: `AttemptRecord.challenge` (nullable string) is added to the response shapes that list attempts.
- Settings: `CRAWLERAI_PROXY_POOLS` also takes `{"endpoints": [...], "mode": "rotate" | "sticky"}`. The old one-URL form
  still works.
- No database change.
