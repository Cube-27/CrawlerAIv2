# Acquisition

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 7. Acquisition

Acquisition is not where the earlier versions failed (Appendix A #25). Core is the minimum needed to get pages and
record what happened.

### 7.1 Fetch

| Rung | When | Mechanism |
|---|---|---|
| **Adapter / API** | The site's platform has an adapter, or the active config has an `api_recipe` | Direct JSON with `httpx`. First adapters: Greenhouse and Lever (documented public APIs **[verified]**), then Shopify through its Storefront API (Appendix A #46, SPEC-15); others in the order of OPEN_QUESTIONS #2 (Appendix A #17). A page the adapter does not serve falls back to the page rungs. Adapters run only when `CRAWLERAI_ADAPTERS` names them. |
| **HTTP** | Default | `curl_cffi` with Chrome TLS impersonation **[verified: MIT]**. |
| **Browser** | The HTTP result is `blocked` or `shell`, or network capture is needed (§7.2) | **Patchright headless**: the owner's tested configuration (Appendix A #20). The user agent drops `HeadlessChrome`, and client hints stay consistent with it. Network JSON bodies are captured. One navigation, bounded waits. |
| **Proxy** | `site.proxy_pool` is set | The same rungs, through the configured pool. |

- **Outcome classification** uses only status codes and structure, never vendor strings (C2, C3):
  - `not_found`: status 404 or 410;
  - `blocked`: status 401, 403, 407, 429, 451 or 503;
  - `shell`: a 2xx response with almost no visible text and almost no links (thresholds in SPEC-02, confirmed on
    dev);
  - `error`: any other 4xx or 5xx status, a network failure, a timeout, or a size or decode failure;
  - a robots.txt disallow is recorded as `blocked` with reason `robots`, without fetching;
  - `ok`: otherwise.

  Challenge pages served with status 200 are not detected by content. They mostly look like shells and get a browser
  retry, and whatever remains shows up in the outcome mix as evidence for §22. Blocked and shell pages end with
  zero records. The method that worked is remembered in `site.fetch_method` and re-checked periodically against
  HTTP.
- **Politeness.**
  - Per-site rate limit (default 1 req/s).
  - Backoff on 429/503, respecting `Retry-After`.
  - robots.txt honoured by default; operator overrides are recorded on the job.
- **SSRF.** Required, because the API and MCP fetch caller-supplied URLs.
  - Resolve DNS once and connect only to that public IP.
  - Reject private, loopback, link-local, unique-local and metadata ranges on every redirect hop; redirects are
    followed manually.
  - Through a proxy, the IP can't be pinned. The hostname is still checked before each hop, and proxy endpoints
    must be explicitly configured.
- **Limits.** Body size caps, compressed-bomb guard, time budgets.

### 7.2 API-backed pages (Appendix A #4)

1. **Discovery.** Browser fetch with network capture on sample pages. Candidate endpoints are JSON responses
   containing values visible on the page.
2. **Recipe.** A typed `api_recipe` (§12): method, URL template bound from the page URL, the headers proven
   necessary by replay, and a JSONPath map. Templating is deterministic first; LLM role D (§11) runs only when that
   is ambiguous.
3. **Validation.** Replay with `httpx` on held-out URLs; the values must match the browser capture.
4. **Export.** The recipe as data, plus a PHP code hint (OPEN_QUESTIONS #12).

Acquisition candidates (anti-bot identities, cookie handoff, vendor strategies, real Chrome with a behaviour layer,
residential proxies, unblockers, a detection bench) are in §22.
