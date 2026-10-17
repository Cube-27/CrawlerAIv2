# Change: acquisition polish

## Why

Merged PRs (#151, #219, #221, #244, #246, #248) left follow-ups in acquisition, crawling, recurring runs and adapters
(`backlog.md` "Follow-ups"): one page kind's render sends a site's other kind to the browser, no rung records proxy
traffic, a crawl fetches a redirected page again as its target's task, a wordless listing is always extracted, adapter
declines live in one process's memory, Shopify collections stop at 250 products and skip locale-prefixed URLs, a branded
career page is rendered before its Workday referral, and a recipe learner's own error fails the whole learning run.

## What Changes

- The remembered fetch method is kept per site and page kind (`site_fetch_method`), re-checked per kind.
- Every attempt records the bytes it moved; a fetch through a proxy pool counts them as `proxy_bytes` usage, a learning
  run's recipe replays included, which go through the site's proxy pool.
- Each `url_task` stores its canonical final URL; a crawl takes no URL a task of the job was already fetched at.
- A listing whose visible text has no words is fingerprinted from its links; `url_state.record_fingerprint` is dropped.
- An adapter's decline of a host is stored on the site row (`site.adapter_declined`); an adapter request on the page's
  own host goes by the robots.txt rules the caller already read.
- Shopify: collections page through the Storefront API's cursor (up to the adapter row cap), and a collection URL under a
  locale prefix is served in that language.
- An `ok` HTTP page that would be rendered for lacking content is first offered to its adapter referral or canonical
  URL; the render runs only when no adapter serves it.
- A recipe learning error that is not an LLM failure is reported as a refused recipe instead of failing the run.

## Impact

- Capabilities: [acquisition](../../../specs/acquisition/spec.md), [adapters](../../../specs/adapters/spec.md),
  [jobs](../../../specs/jobs/spec.md).
- Database: the baseline migration gains `site_fetch_method`, `site.adapter_declined` and `url_task.final_url`, and loses
  `site.fetch_method`, `site.fetch_method_checked_at` and `url_state.record_fingerprint` (greenfield, recreated).
- No API shape changes.
