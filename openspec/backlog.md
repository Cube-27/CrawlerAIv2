# Backlog

Work not yet in a change: the current focus, follow-ups left by merged PRs, and human-only tasks that no change
owns. It replaces `docs/plans/ACTIVE.md` (D-1136). Implementors add the follow-ups they leave in their tracker
commit and delete the lines their PR closes; a follow-up that grows into work becomes a change folder under
`changes/`. In-flight work is read from open PRs and `changes/`, not from here.

## Current focus

- Data accuracy: SPEC-13, SPEC-15, structural ownership of state array rows (#243) and identity merge across
  collectors with standalone variants (#247) are complete.
- Data sources, later (owner #53): discover the network/API calls a page makes for its data and read the data from
  them, generically, as a learned layer (the way listing pagination was probed before #52). Not started; needs a probe
  and the owner's admission like #52.
- Open owner items: none (D-0783, D-0784 and D-0915 answered under owner delegation, #252).

## Human-only tasks

Agents can't do these. Tasks H1, H2, H3 and H6 (milestone M) belong to the change
[wire-protected-eval-job](changes/wire-protected-eval-job/tasks.md). Labeling is deferred until the crawler works,
so they block no other work: the protected eval job stays a `no_baseline` placeholder, and tests run against local
throwaway databases.

| # | Task | Needed by | Status |
|---|---|---|---|
| H4 | Provide LLM provider API keys (OPEN_QUESTIONS #5) as CI and runtime secrets. | Live LLM runs | deferred (owner, 2026-10-13: not needed yet) |
| H5 | Answer the `needs-owner` entries in the open owner items in `project.md`. | As they come up | none open (#252) |
| H7 | Optional: configure a proxy pool (OPEN_QUESTIONS #10). | Proxy use in production | todo |
| H8 | Create the GitHub release `data-geonames-2026-10-15` holding the three GeoNames files the manifest pins, with the CC BY 4.0 attribution in its notes (D-0311, D-0914; command in #204). Until then `crawlerai data fetch` gets a 404 for them. | `crawlerai data fetch`, SPEC-05's first real run | obsolete: GeoNames dropped (D-0953, #210) |

## Follow-ups

Open items left by merged PRs, one line each (source PR in brackets). Measure before redesigning where noted.

- ATS adapters (#248): the SmartRecruiters API host's robots.txt disallows every agent but one, so by default its adapter
  is refused and the page rungs serve (D-1306); it was verified on recorded answers. A branded list page with no rows at
  HTTP is rendered once (owner #54) before the own-host referral serves its Workday site; referring first would save the
  render: measure how often. Descriptions are the main section only (D-1308). `fetch.max_rows` is not in the playground.
- ATS adapters (#251): Workable's per-job endpoint is not built; Teamtailor and Personio serve lists only (a job page
  takes the page rungs: a shape cannot pick one item of a feed). UKG's list is refused by the host's robots.txt, so it
  serves only on an operator override (D-1334). Not read: UKG `FullTime`, BambooHR pay as text (`baseSalary` is mapped
  as written; the range normalizer decides), ADP pay type (annual or hourly), Teamtailor's `jobs.rss` locations. UKG and ADP
  were measured on one tenant each (their endpoints are the platform's own); add tenants as found. A re-scrape of a
  listing keeps an earlier record of the same URL: check that a field newly mapped by an adapter reaches it.
- Network data layer (#250): the paging driver (`crawl.paging`) counts linked DOM item blocks only, so a scroll listing whose items hold no item link stops `no_items` although its calls would load more rows.
- Network data layer (#250): a render sometimes ends before the page's data call arrives (one of five renders of one listing kept no call); the settle wait does not wait for fetches in flight.
- Network data layer (#250): structured rows that lack a field the page's call carries per item (microdata rows without a price) keep it unpublished; joining a call's rows to structured rows needs an item identity rule.
- Network data layer (#250): the release executor reads `xhr` bodies with `json.loads`, not `network_json` (no guard prefix), since it shares no code with the engine (INV-20); decide whether it follows.
- Listing browser actions (#241): a load-more or scroll listing whose rows come from a JSON-LD ItemList keeps the
  first batch only (the script is not updated as items load); rows of the grown DOM need role C or a config. Not
  validated on a real virtualised list or a real in-DOM show-more listing; an integer inside a path segment
  (`page-2.html`) is not a +1 integer link, so such pages turn by their pager only. Measure on dev before changing.
- Absent fields (#252): a config-mode page missing an absent required field is still `partial`; listings never get
  `absent` fields (D-1347); a field the previous config covered was not asked of role C on its pages, yet a run reading
  them may list it absent when another field made a call (D-1341). Measure on dev once LLM keys exist.
- Config approval (#252): there is no reject endpoint or MCP tool; a waiting config is replaced by a forced run or an
  operator correction (D-1342).
- Acquisition hardening (#244): pages behind a challenge that does not clear headless stay `blocked` after the 40%
  interstitial wait (5 real 403 challenge pages waited ~20 s each and stayed blocked in the live check); measure the
  share that clears on a dev run before lowering `_INTERSTITIAL_SHARE` (D-1262). A 429 challenge page gets no browser
  attempt by design (D-1263).
- Acquisition hardening (#244): `site.fetch_method` is per site, so one page kind's render (a listing's) sends the
  site's other kinds to the browser too until the weekly re-check; a per-kind memory needs a column (D-1260).
- Acquisition hardening (#244): no rung records `proxy_bytes` usage (the usage resource exists); a learning run's
  recipe replays use the default policy, so no proxy pool (D-1264).
- Anti-bot stack (#253): no real site in the live check cleared a challenge in the headless browser after HTTP was
  refused, so the site session handoff is proven on a local fixture only; measure on a dev run how often a browser
  `ok` opens a session and how many HTTP fetches each session serves before tuning 30 min / 200 fetches (D-1350).
- Anti-bot stack (#249): challenge labels are counted only as log records; per-category counts in the eval report
  need the hidden-cell suppression review (D-1326). The adaptive rate's 20-answer run and 10% recovery are unmeasured
  (D-1327).
- ATS adapters (#226): UKG Pro (UltiPro), ADP, Rippling and Paycom are not built yet; Workday and Oracle Recruiting serve each list's first page only (20 and 25 rows), and Workday sites on a tenant's own domain are not detected.
- Crawl: only the start page's redirect target is kept out of the frontier (D-1285); another page whose URL redirects is still fetched again as its target's task. Deduplicating by final URL needs each task's final URL stored (jobs-crawl-perf #246).
- Role S cap: `project.draft_call_cap` counts a key's calls in all, with no window, and the Settings screen has no field for it (it sends the loaded value back); add a window or a field if the cap is used (D-1282) [#246].
- Recurring: a listing page whose text has no words has no content fingerprint, so it is always extracted; `url_state.record_fingerprint` is unused and could go (D-1283) [#246].
- Optional: report non-LLM recipe errors as a refused recipe [#151].
- Labeling pre-fill: return its diagnostics, a change to the prefill response shape (D-0847) [#111].
- Role C: confirm the `fast` Anthropic model accepts `output_config.effort` (D-0766); sparse 200-row listings spend ~14 output tokens per absent field; Gemini thinking is not lowered for role C [#159]. `max_output_tokens` may not hold 200 wide rows [#111].
- Playground: the toolbar's Format shows its error line under it in the flow, so a refused send without a format moves the action and the output down; hang it as the toolbar's Schema now does (D-1214) [#238].
- Field tables: every field of an uncalibrated engine shows an `uncalibrated` badge; one badge per record would need a DESIGN.md and INV-22 change [#214].
- Shopify product pages take the page path; joining the adapter's answer to the page's collectors needs a capture holding both and a measure of cross-source conflicts (D-1118) [#224].
- Round-1 eval: class 13 is §22 evidence (repeated-structure DOM collectors; class 10 is addressed by #208); classes 11 and 12 answered by the owner (D-1057, D-1058) [#207, #216].
- Acquisition thresholds to confirm on dev: the 1024-byte terminal bound (D-0932) and the listing shell rule's effect on empty listings (D-0933) [#206].
- Array rows (#243, #252): a state variant row, or a lone object, naming the page only with a variant query is
  `not_owned`, and a row with no URL is too (D-1250, D-1253, D-1345). `dom` label-value pairs inside repeated page
  structures (a comparison table) stay page values (D-1255).
- Workflow tooling: if parallel tracker commits keep conflicting on ACTIVE.md, move their writes elsewhere (D-0823) [#192].
- For the owner: once labels exist, the gate compares precision only (§4.8), so a type the engine stops publishing shows only as lower coverage [#32].
- Collect: a `dom` label value that contradicts structured data turns an agreement-ranked field (money, identifier, enum, count, number) into `conflict`; measure the `dom` bucket's effect on required-field `conflict` at milestone M (D-0956) [#208].
- Precedence: `dom` ranks above `config` for text, long_text, url and image_url, so a config or operator field cannot override a DOM label value; re-check when `fit-precedence` first runs on dev (D-0956) [#208].
- Schemas: role S's drafted schemas are stored without the vocabulary check (their paths come from the LLM, so a reply
  check against the pinned file would let the LLM correct a wrong path); the engine executor does not compare a config's
  schema digest per page (D-1374, D-1375) [#255].
- Schemas: an edit's `relearn_schema` scans `progressive_state` by `schema_id`, which no index leads; add one if edits become frequent [#210].
- LLM: role A and role C each fixed the provider's grammar cap their own way (D-1008); a new role with a repeated subschema should hoist it to `$defs` or use a named list, and a client-level check of schema size could catch it before a 400 [#215].
- LLM eval: role C's and role A's `request_hash` changed with their output schemas (D-1008), so recorded dev-eval replies are re-recorded on the next run [#215].
- LLM eval: role C's `request_hash` changed with its message order (D-1021); recorded dev-eval replies are re-recorded on the next run [#217].
- Collect: a banner whose block links to several documents (a promotion with category links) still passes the link-card rule and can be the main image (round 3: one page, its field already `conflict`); measure before widening it (D-1096) [#220].
- LLM eval: role C's `request_hash` changed with its claim form (D-1097); recorded dev-eval replies are re-recorded on the next run. Round 3's all-empty role C page did not reproduce from its capture; re-check in round 4 [#220].
- Collect: the main image is still the first shown image of the main region; on pages whose structured data names an image, measure whether a `dom` image that disagrees costs precision (D-1023) [#217].
- Workflow tooling: `cleanup_worktree.sh` still removes per-worktree `crawlerai-<wt>-*` Postgres containers; drop that loop once none are left, since DB tests use `test_db.sh` (D-0971) [#212].
- Shopify adapter: a collection over 250 products stops at 250 (one of four measured collections reached it); measure on dev before adding cursor paging (SPEC-15 §9) [#219].
- Shopify adapter: on detail pages the generic path publishes page-only fields the API does not state (rating, review count, condition); compare both paths on dev labels before turning the adapter on for detail pages (D-1088) [#219].
- Shopify adapter: locale-prefixed URLs are open (SPEC-15 §9) [#219].
- Shopify adapter: a product page of a shop with several presentment currencies sends one API request, then falls back, every time; remember it per host if such shops are common (D-1114) [#221].
- Adapters: a host's decline (D-1078) lives in each process for 24 hours; store it on the site row if the probe traffic shows in logs. An adapter request on the page's host re-reads that host's robots rules, already checked by the caller [#219].
- API recipes: the paged executor (`RecipeRung.pages`) has no caller; recipe pagination comes only from an operator correction [#223].
- Role C: one site-test listing whose HTTP body holds 20 item blocks gave one role C row; not reproducible without the LLM recording, re-check on the next run [#240].
- Resolve: adapter entities (`collect/adapter.py`) carry no identity, so an adapter item and the page's JSON-LD
  statement of it stay two entities (D-1290) [#247].
