# Tasks: acquisition polish

## 1. Fetch method per page kind (D-1260)
- [ ] 1.1 `site_fetch_method` (site, page kind, method, checked_at) replaces `site.fetch_method`; a fetch with no page
  kind shares the detail memory; `site_row` and learning read the kind's method; the re-check runs per kind

## 2. Proxy traffic (D-1264)
- [ ] 2.1 Attempts record the bytes they moved (HTTP and JSON rungs: the HTTP messages; browser rungs: the bytes the
  guard relayed); fetch usage counts them as `proxy_bytes` for a fetch through a pool
- [ ] 2.2 A learning run's recipe replays go through the site's proxy pool and count their usage on the learn job

## 3. Crawl final URLs (D-1285)
- [ ] 3.1 `url_task.final_url`; the frontier takes no URL a task of the job was fetched at (replacing the start page's
  special case)

## 4. Recurring wordless listings (D-1283)
- [ ] 4.1 A listing page without words is fingerprinted from its links; `url_state.record_fingerprint` dropped

## 5. Adapter declines and robots (D-1078, #219)
- [ ] 5.1 A host's adapter decline is stored on its site row and read per fetch
- [ ] 5.2 An adapter request on the page's host goes by the caller's robots.txt rules

## 6. Shopify (#219, #221)
- [ ] 6.1 Collections over 250 products page through the Storefront API cursor
- [ ] 6.2 Locale-prefixed collection URLs are served in their language
- [ ] 6.3 Several presentment currencies: decided without code (D-1387)

## 7. Referral before render (#248)
- [ ] 7.1 An HTTP page lacking content is offered to its adapter referral before the render

## 8. Recipe errors (#151)
- [ ] 8.1 A non-LLM recipe learning error is a refused recipe
