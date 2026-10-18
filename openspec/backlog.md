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

- QA sweep (#263): a 200 anti-bot interstitial (an HTTP and a browser render both `ok`, no links, no structured data,
  a title that is not the page's) is kept as the product page, publishing only `url`, and role C finds nothing in it:
  telling it from a page needs a structural rule (a detail page with no link, no structured data and no offer evidence)
  that is an acquisition rule for the owner (#53), or a vendor signature in `adapters/challenges.py` that only labels.
- QA sweep (#263): `markdown` and `html` of an `api` capture still read the JSON answer as HTML (a description's links
  render as `<api>/\"https:/...` targets); decide what those formats are for a JSON body (empty, or the answer's text
  values) alongside D-1450.
- QA sweep (#263): a listing with no rows answers `records: []` with nothing saying why (no role C, or role C read
  none); a page field it did resolve (`next_page_url`) is dropped with it. Consider a page-level reason.
- QA sweep (#263): an HTTP `error` attempt (`network_error: curl 92`, an HTTP/2 stream a bot filter resets) ends the
  scrape `failed` with no browser attempt; check whether the ladder should try the browser after a network error.
- QA sweep (#263): a single-valued `location` publishes `conflict`/`disagree` for every posting that states several
  locations (96 of 167 on one Ashby board) although the adapter's `also` marks the primary one; owner question whether
  the primary location publishes or the field becomes a list.
- QA sweep (#263): with role C on, a client-rendered collection page gave 3 rows (of dozens shown) and a hosted career
  page whose API host's robots.txt disallows the adapter gave 0; measure role C's row recall on dev listings.
- Draft dev baseline (#264, #267): money's locale set reads every alternate link's `hreflang`, so `$` on a page tagged
  with one territory is ambiguous when its alternates name others; reading only the alternates that link to the page
  itself (D-1482) is right but publishes prices on role C rows that carry no URL, lowering listing money precision:
  land it once role C rows carry their URL. Shops with several presentment currencies keep listing rows unpriced until
  the owner admits reading the currency the page shows (D-1481). A separately stated apply link needs a ranked
  `schema_org` path for `apply_url` (D-1485). Generic listing rows whose URL carries a query the labels drop, or a
  trailing slash, still match no label row.
- Request context and actions (#262): a scrape's `browser_actions` (listing paging) takes no `fetch.actions` yet (D-1439):
  let the paging driver run the caller's steps first (a cookie banner, a filter). An asynchronous job's secret values
  stay in `job.request` after it ends (D-1432): scrub them when the job ends, once recurring crawls show whether a re-run
  reads them. Steps are per request; per-URL steps in a batch are a later member if callers ask.
- Crawl strategies (#261): the best-first weights (0.5 match, 0.3 inherited, 0.2 prior, 0.8 per depth) and the candidate
  factor 5 are untuned; they were checked live on one public documentation site only (a query-matching page before its
  siblings, an eventloop page found one level down). Measure on dev once a crawl evaluation exists. A best-first crawl's
  unfetched candidates list as `cancelled` in `GET /v1/jobs/{id}/results`; consider hiding them there.
- Web search (#261): an HTML provider's results carry no snippet, results are not cached, and SearXNG is read up to 5
  pages. No public SearXNG instance accepted the JSON API in the live check (challenge pages), so the SearXNG path was
  verified against a local stub of its JSON API and the template path against a public JSON API.
- SDKs (#261): the CI `sdk` job (`make check-sdk`: regenerate, diff, each SDK's checks and tests) could not be added: the
  worker's token cannot push workflow files. Add it to `ci.yml`; until then only the digest test runs in CI. The SDKs
  are not published to PyPI or npm and carry the repository's AGPL-3.0 license, which the owner may want to relax for
  libraries. Add an `AsyncCrawlerAI` webhook receiver example if callers ask.
- Schedules and webhooks (#259): delivered `webhook_event` and `webhook_delivery` rows are never expired (add them to
  retention); a job's deliveries have no read endpoint (status, attempts, last error) for a caller debugging a receiver;
  the UI cannot edit a schedule (`PATCH /v1/schedules/{id}` exists) or create one from a stored run's request.
- ATS adapters (#248): the SmartRecruiters API host's robots.txt disallows every agent but one, so by default its adapter
  is refused and the page rungs serve (D-1306); it was verified on recorded answers. A branded list page with no rows at
  HTTP is rendered once (owner #54) before the own-host referral serves its Workday site; referring first would save the
  render: measure how often. Descriptions are the main section only (D-1308).
- ATS adapters (#251): Workable's per-job endpoint is not built; Teamtailor and Personio serve lists only (a job page
  takes the page rungs: a shape cannot pick one item of a feed). UKG's list is refused by the host's robots.txt, so it
  serves only on an operator override (D-1334). Not read: UKG `FullTime`, BambooHR pay as text (`baseSalary` is mapped
  as written; the range normalizer decides), ADP pay type (annual or hourly), Teamtailor's `jobs.rss` locations. UKG and ADP
  were measured on one tenant each (their endpoints are the platform's own); add tenants as found. A re-scrape of a
  listing keeps an earlier record of the same URL: check that a field newly mapped by an adapter reaches it.
- Network data layer (#250): the release executor reads `xhr` bodies with `json.loads`, not `network_json` (no guard prefix), since it shares no code with the engine (INV-20); decide whether it follows.
- Network data layer (#254): cold listing rows publish text fields only through role C (call rows admit text by equality), so without LLM keys a learned listing recipe maps checkable fields only (the live check's public search listing: `url`); verify a full `learn` job through the API once role A has keys (H4).
- Listing paging (#258): call rows that extend a listing beyond its script (D-1402) carry the fields their call proves
  by the listing's links or by visibility; a field the script states for other items admits by equality only, so those
  rows are partial until role C reads them (verify once role A/C have keys). Grown items stated by neither structured
  data nor a call stay for role C or a config.
- Listing paging (#258): a load-more control written as an `a` without `href` (a placeholder, HTML Standard §4.6.1) is
  no control, so such a listing stops `no_mechanism` (one public test listing, live check of #258); measure on dev how
  often before admitting script-click placeholders.
- Listing paging (#258): a JSON-LD `ItemList` beside a load-more, a call filling structured rows (D-1400, D-1401) and an
  in-DOM show-more listing were verified on synthetic pages only; validate on dev listings.
- Absent fields (#252): a config-mode page missing an absent required field is still `partial`; listings never get
  `absent` fields (D-1347); a field the previous config covered was not asked of role C on its pages, yet a run reading
  them may list it absent when another field made a call (D-1341). Measure on dev once LLM keys exist.
- Acquisition hardening (#244): pages behind a challenge that does not clear headless stay `blocked` after the 40%
  interstitial wait (5 real 403 challenge pages waited ~20 s each and stayed blocked in the live check); measure the
  share that clears on a dev run before lowering `_INTERSTITIAL_SHARE` (D-1262). A 429 challenge page gets no browser
  attempt by design (D-1263).
- Anti-bot stack (#253): no real site in the live check cleared a challenge in the headless browser after HTTP was
  refused, so the site session handoff is proven on a local fixture only; measure on a dev run how often a browser
  `ok` opens a session and how many HTTP fetches each session serves before tuning 30 min / 200 fetches (D-1350).
- Anti-bot stack (#249): challenge labels are counted only as log records; per-category counts in the eval report
  need the hidden-cell suppression review (D-1326). The adaptive rate's 20-answer run and 10% recovery are unmeasured
  (D-1327).
- ATS adapters (#226): UKG Pro (UltiPro), ADP, Rippling and Paycom are not built yet; Workday and Oracle Recruiting serve each list's first page only (20 and 25 rows), and Workday sites on a tenant's own domain are not detected.
- Playground (#257): at phone width a toolbar select's error line, in a `w-64` column, can sit over the tool wrapped under it (Format's over Schema); a reserved line would move the layout whenever none shows, so measure on a phone before changing it (D-1397).
- Fetch trail (#257): a task robots.txt kept from its page has no capture, so its drawer has no attempts and `last_error` (`robots`) is shown nowhere; the `network` evidence label was checked in component tests only, since no public page of the live check published a value of a captured call.
- Config approval (#257): a rejected config's cold state learns again after 8 more pages (D-1391); a way to stop learning one site (pause) is not built.
- Crawl (#256): a page enqueued before the task redirected to it is fetched is still fetched as its own task; only URLs
  found after the redirect are left out (D-1382).
- Adapters (#256): a decline of a host other than the page's (a canonical or referred platform URL) is not stored on any
  site row, so it lasts one fetch (D-1384).
- Shopify adapter (#256): a collection stops at the adapter row cap (1000); a locale subfolder's region is not used, so a
  multi-currency shop's rows stay unpriced (D-1385, D-1386).
- Role S cap: `project.draft_call_cap` counts a key's calls in all, with no window, and the Settings screen has no field for it (it sends the loaded value back); add a window or a field if the cap is used (D-1282) [#246].
- Labeling pre-fill: return its diagnostics, a change to the prefill response shape (D-0847) [#111].
- Role C: confirm the `fast` Anthropic model accepts `output_config.effort` (D-0766); sparse 200-row listings spend ~14 output tokens per absent field; Gemini thinking is not lowered for role C [#159]. `max_output_tokens` may not hold 200 wide rows [#111].
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
- Shopify adapter: on detail pages the generic path publishes page-only fields the API does not state (rating, review count, condition); compare both paths on dev labels before turning the adapter on for detail pages (D-1088) [#219].
- API recipes: the paged executor (`RecipeRung.pages`) has no caller; recipe pagination comes only from an operator correction [#223].
- Role C: one site-test listing whose HTTP body holds 20 item blocks gave one role C row; not reproducible without the LLM recording, re-check on the next run [#240].
- Resolve: adapter entities (`collect/adapter.py`) carry no identity, so an adapter item and the page's JSON-LD
  statement of it stay two entities (D-1290) [#247].
- Output formats: `markdown_fit` and `chunks` count words, not model tokens; a tokenizer-backed size needs a licensed tokenizer, which no LLM-free path has [#260].
- Output formats: no OCR or visual diff of a screenshot, and no scheduled screenshot history per URL [#260].
