# Backlog

Work not yet in a change: the current focus, follow-ups left by merged PRs, and human-only tasks that no change
owns. It replaces `docs/plans/ACTIVE.md` (D-1136). Implementors add the follow-ups they leave in their tracker
commit and delete the lines their PR closes; a follow-up that grows into work becomes a change folder under
`changes/`. In-flight work is read from open PRs and `changes/`, not from here.

## Current focus

The master improvement plan (owner, 2026-10-18, `design/owner-decisions.md` #67), by phase:
- **Phase 0, measure what is real:** done but for decode once at acquire (phase-1 batch): golden set as the only
  measure (#271); row keys without session parameters, label re-keying, list labels, presence ceiling, FN/FP kinds
  and cost per correct field (#272). Golden TP share with recorded role C: 30.0% → 46.9% after re-keying.
- **Phase 1, acquisition robustness:** one polite fetch, structural render-need without role C, resource blocking,
  bounded scroll/next by default for single-URL listing scrapes, `blocked` with the vendor label.
- **Phase 2, the item layer:** segment, align (typed value spotting), bind; role C per block; delete the item-link,
  item-text and call-row joins.
- **Phase 3, detail precision and recall:** role C for every missing field with element and link claims; precedence
  and calibration fitted on the golden set; label–value collector generalized.
- **Phase 4, learning that adds coverage:** induction over block alignment; oracle = engine ∪ role-C-grounded values;
  role A prompt caching.
- **Phase 5, acquisition access:** deferred (decision 7); vendor-blocked pages stay `blocked`.
- **Phase 6:** golden set grows in fresh batches; adapters measured on 3 tenants or deleted.

## Human-only tasks

Agents can't do these.

| # | Task | Needed by | Status |
|---|---|---|---|
| H4 | Provide LLM provider API keys (OPEN_QUESTIONS #5) as CI and runtime secrets. | Live LLM runs | deferred (owner, 2026-10-13: not needed yet) |
| H5 | Answer the `needs-owner` entries in the open owner items in `project.md`. | As they come up | none open (#252) |
| H7 | Optional: configure a proxy pool (OPEN_QUESTIONS #10). | Proxy use in production | todo |
| H9 | Delete `.github/workflows/eval-protected.yml`, the private test databases and `CRAWLERAI_TEST_PRIVATE_DATABASE_URL` in `.github/workflows/ci.yml`, then `tools/site_literal_scan.py --hidden-hosts-from-env` and its test (`tools/tests/test_site_literal_scan_hidden.py`); the worker token cannot push workflow files (D-1522). | Clean-up of the retired hidden machinery (#67) | todo |
| H8 | Create the GitHub release `data-geonames-2026-10-15` holding the three GeoNames files the manifest pins, with the CC BY 4.0 attribution in its notes (D-0311, D-0914; command in #204). Until then `crawlerai data fetch` gets a 404 for them. | `crawlerai data fetch`, SPEC-05's first real run | obsolete: GeoNames dropped (D-0953, #210) |

## Follow-ups

Open items left by merged PRs, one line each (source PR in brackets). Measure before redesigning where noted.

- Bot review findings left for phase 2 (#277): item groups ranked by summed evidence (a large image-only gallery outranks a smaller grid: `content/segment.rank`, whose first group feeds markdown and render need; the align step orders groups by fields aligned); `resolve/pipeline` holders miss row-mapped `field.sub` candidates; `resolve/preference` keeps the winner's http image over a lower source's https twin; `resolve/identity` keeps only the first of two ProductGroups under one isVariantOf; `LearnedCalls.matches` ignores fixed query values and body shape; `resolve/pagination` `int()` on a digit run over 4300 digits; `schema_org_map._selections` never counts a list or joined value as stated. Fix in the layer phase 2 rebuilds, or delete with it.
- Role C on listings (#279): on the golden set's listings role C adds about no TP with either prompt (D-1600): the
  926 FN are mostly rows and fields the item layer does not find, which role C, filling bound rows only, cannot add.
  Call rows bound to no block and listings with no aligned group get no role C values; measure which listings lose
  rows to that before adding a path. `BLOCK_CLAIM_TOKENS` rests on one live run (41 output tokens per claim).
- Role C on detail pages (#283): on the golden set `product_id` coverage stays 0.25 and detail `image_url` precision
  0.63 (role C claims few ids for them; the image is usually published before role C runs); measure image claims where
  a collector's image is wrong before changing precedence. `apply_url` is still missing on 6 of 17 job pages, not yet
  broken down by cause. Recorded detail replays need re-recording (request changed). An
  element that renders no text sits before the next line's break in role C's text. Adapters that stated only a
  posting URL no longer give `apply_url`; map a documented apply link where the platform has one.
- Extract with `fetch.cache: only` (#277): sample URLs read stored captures, but globs are still expanded by a live map.
- Item layer (#278): block prices whose symbol is ambiguous without a stated currency (`$` on a page in `es` or `en`,
  `Rs.`) decline in the money normalizer; on the golden set four listings show prices only so. A currency the page
  states in its state or call JSON as an ISO 4217 code could settle the symbol, as structured data's does; measure
  before admitting it. A WebPage `mainEntityOfPage` given only as an `@id` is not read as a row's item URL (D-1569).
- Item layer (#278): a state value read at a key the page's blocks proved (`collect.induce`) ranks in no text
  precedence and has no evidence bucket, so it never fills a row alone; a bucket for it is a resolution-spec change.
  A listing split into sections of one shape aligns its first section's group only (the other sections' items are
  not rows); merging same-shape groups would read them, with label-subset pages then scoring extra rows.
- Golden report (#272): `eval re-key` marks 206 of 748 golden label rows stale by a written-form search of the
  capture; a row whose title the capture writes only in a script-escaped or transformed form may be marked stale
  wrongly. Spot-check stale rows against the captures before the next fresh batch, and keep the stale count in each PR.
  Presence of amounts, numbers, dates and enums is unknown (no written form to search); executability classes and
  per-failure-class deltas (plan §8) are not built. The no-LLM `list` precision fell (0.36 → 0.20) only because the
  `locations` labels now import (n 12 → 287): the engine's listing locations are scored for the first time.

- Master plan phase 1 (#273): on fresh captures of the golden set, the structural render need lost 41 values on 2
  listings whose HTTP document shows a repeated group that is not their items (links in an unmarked footer, profile
  cards) and whose rows came from the render's data calls; the item layer (phase 2) decides which group lists the
  items. Renders the structural rules keep gained no value on 3 golden listings whose rows come from structured data
  (their sites are then remembered as `browser`): measure again once role C asks for missing row fields.
- Master plan phase 1 (#273): resource blocking cut browser bytes per listing page by 34% (median 21%, 32 golden
  listings `ok` either way), short of the plan's 60%: scripts and data calls carry the rest. The 10 s interstitial
  bound is unmeasured on challenges that clear. The blocked share per vendor (master plan §8.4) is not in the eval
  report.
- Master plan phase 1 (#273): default listing growth ran on 10 of 40 golden listings in a live scrape and is not in the
  eval numbers (the import follows the worker path, D-1549); the items it adds become records only through structured
  data or role C until the item layer reads blocks.
- Learning live (#269): role A reads 180k to 285k input tokens per call (5 sample pages of up to 120,000 characters
  of reduced HTML, sent again in each repair round), USD 0.15 to 2.70 of role A per learned host against about
  USD 0.002 per role C page: measure a smaller `CRAWLERAI_LLM_A_MAX_CHARS` or prompt caching across rounds. Synthesis
  still wants the row selector to select exactly the engine's rows on each sample page (D-1500), so a sample page whose
  rows left items out pushes the repair toward a narrower selector. An XPath element value is its string-value,
  so a long_text only the DOM states (blocks without whitespace between them) cannot be reproduced; rendering the
  element needs the parsed tree's render without a second parse (INV-26). A listing learns only the fields its cold
  rows publish. The dev eval database's `job_listing` predates
  `locations` (it holds `location`): re-import or sync it before measuring listing configs. The learning-configs spec
  is past 100 lines: split it (configs and learning).
- Sweep fixes 2 (#266): a hosted career page whose API host's robots.txt disallows the adapter still gives 0 rows
  (`no_rows: not_asked`). Listing role C requests changed (D-1600), so recorded dev replays of listings need
  re-recording.
- Accuracy round 2 (#270): some labels' row titles add a variant or the company the page shows apart from the title,
  so matched rows score their title wrong; settle the label convention. Shops with several presentment currencies keep
  listing rows unpriced (D-1481, D-1492): a page currency source needs a standard or the platform's documentation, and
  new captures (the dev ones hold the API answer only). Block rows whose link carries a query the labels drop stay as
  they are.
- Request context and actions (#262, #268): steps are per request; per-URL steps in a batch are a later member if callers
  ask. A schedule keeps no secret value (D-1510), so a recurring crawl of a page behind the caller's own cookies or
  headers has no home: add it with a deployment key setting that encrypts the values on the schedule if callers need it.
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
- Anti-bot stack (#253): no real site in the live check cleared a challenge in the headless browser after HTTP was
  refused, so the site session handoff is proven on a local fixture only; measure on a dev run how often a browser
  `ok` opens a session and how many HTTP fetches each session serves before tuning 30 min / 200 fetches (D-1350).
- Anti-bot stack (#249): challenge labels are counted only as log records; per-category counts could join the eval
  report now that no cell is suppressed (D-1326). The adaptive rate's 20-answer run and 10% recovery are unmeasured
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
