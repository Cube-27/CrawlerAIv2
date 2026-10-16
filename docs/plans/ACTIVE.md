# Implementation tracker

The live state of implementation. Implementors write their rows and the follow-ups they leave in their PR's tracker
commit; a solo agent updates it in its PR (`CLAUDE.md` §3). One row is one entry of a spec's PR plan; one PR covers a
batch of rows. Spec dependencies are in `specs/README.md`. A row is ready when everything it needs is available: the
code it builds on is merged, or what it needs from unmerged work is fully specified. Readiness is per row (owner,
2026-10-13). Read by section, never in full (`CLAUDE.md` §1).

**Statuses:** `todo`; `done (#n)`: merged; `blocked (D-NNNN)`; `human`: waits on a human-only task (below).

Updated: 2026-10-16.

## Human-only tasks

Agents can't do these. Rows that depend on them are `human` until they're finished. **M** tasks belong to milestone
M (ARCHITECTURE §21). Labeling is deferred until the crawler works, so they block no row: the protected eval job stays
a `no_baseline` placeholder, and tests run against local throwaway databases.

| # | Task | Needed by | Status |
|---|---|---|---|
| H1 (M) | Choose the custodian(s) of the hidden and fresh sets (OPEN_QUESTIONS #6). Create the private eval database role and credentials, and store them only in the protected GitHub environment. | Milestone M | deferred |
| H2 (M) | Protect the `eval-protected` GitHub environment (GitHub auto-created it with no rules): add the custodians as required reviewers and set the secrets, including the hidden-host list. | Milestone M | deferred |
| H3 (M) | Label dev from a review of crawler output, then draw and label hidden from sites development never touched (§21 rule). | Milestone M | deferred |
| H4 | Provide LLM provider API keys (OPEN_QUESTIONS #5) as CI and runtime secrets. | Live LLM runs | deferred (owner, 2026-10-13: not needed yet) |
| H5 | Answer the `needs-owner` entries in the decisions log's index of open items. | As they come up | open: see Current focus |
| H6 (M) | Monthly: sample and label 20–30 fresh sites (OPEN_QUESTIONS #7). | After M | deferred |
| H7 | Optional: configure a proxy pool (OPEN_QUESTIONS #10). | Proxy use in production | todo |
| H8 | Create the GitHub release `data-geonames-2026-10-15` holding the three GeoNames files the manifest pins, with the CC BY 4.0 attribution in its notes (D-0311, D-0914; command in #204). Until then `crawlerai data fetch` gets a 404 for them. | `crawlerai data fetch`, SPEC-05's first real run | obsolete: GeoNames dropped (D-0953, #210) |

## Current focus

- Data accuracy: SPEC-13 is complete. Next: re-run the Shopify baseline and decide the adapter; then option (b),
  structural ownership of array rows, for checkable types inside related-item arrays.
- Open owner items: D-0783–D-0784 (investigate, owner 2026-10-16: not now: learned-config approval, an "absent"
  field status), D-0915 (SimHash at Hamming 0 misses some edits).

## Done specs

Full rows are in git history.

- [SPEC-00 — Project setup and engineering foundations](../specs/SPEC-00-project-setup.md): PRs 1–10 (#1, #3, #4, #9, #5, #6, #7, #8, #12, #10)
- [SPEC-01 — Persistence, job queue and capture storage](../specs/SPEC-01-persistence-queue-storage.md): PRs 1–8 (#11, #14, #17, #19, #13, #20, #23, #25)
- [SPEC-02 — Acquisition](../specs/SPEC-02-acquisition.md): PRs 1–10 (#16, #18, #22, #26, #31, #46, #53, #52, #62, #64)
- [SPEC-04 — Schemas and normalization](../specs/SPEC-04-schemas-and-normalization.md): PRs 1–12 (#43, #47, #58, #54, #57, #59, #60, #56, #66, #203, #203, #208)
- [SPEC-05 — Extraction and resolution](../specs/SPEC-05-extraction-and-resolution.md): PRs 1–14 (#67, #72, #78, #83, #79, #85, #90, #94, #100, #86, #91, #106, #109, #208)
- [SPEC-06 — LLM layer](../specs/SPEC-06-llm-layer.md): PRs 1–7 (#69, #74, #76, #107, #111, #92, #148)
- [SPEC-07 — API foundation and `scrape`](../specs/SPEC-07-api-foundation-and-scrape.md): PRs 1–8 (#70, #77, #80, #88, #105, #96, #81, #108)
- [SPEC-08 — Config IR, learning, progressive mode](../specs/SPEC-08-config-ir-learning-progressive.md): PRs 1–12 (#95, #98, #110, #114, #116, #118, #122, #127, #119, #123, #124, #115)
- [SPEC-09 — API-backed pages](../specs/SPEC-09-api-backed-pages.md): PRs 1–7 (#102, #113, #117, #121, #125, #126, #129)
- [SPEC-10 — Jobs, crawl, extract, MCP](../specs/SPEC-10-jobs-crawl-extract-mcp.md): PRs 1–10 (#120, #128, #130, #137, #140, #132, #144, #145, #146, #148)
- [SPEC-11 — Recurring crawls](../specs/SPEC-11-recurring-crawls.md): PRs 1–5 (#131, #135, #136, #142, #139)
- [SPEC-12 — Frontend application](../specs/SPEC-12-frontend-application.md): PRs 1–11 (#68, #73, #82, #87, #97, #134, #143, #141, #93, #147, #148)
- [SPEC-13 — Variant matrix](../specs/SPEC-13-variant-matrix.md): PRs 1–4 (#170, #172, #171, #174)
- [SPEC-14 — Playground workspace](../specs/SPEC-14-playground-workspace.md): PRs 1–11 (#189, #191, #194, #194, #194, #198, #198, #198, #190, #201, #205)

## Follow-ups

Open items left by merged PRs, one line each (source PR in brackets). Measure before redesigning where noted.

- Job results paging builds the job's whole `task_record` set per page; measure on a ~100k-task job (paging by task id is the likely fix) [#158].
- Learning: SPEC-09 discovery, role D and recipe validation are not yet called from learning (needed with R7) [#149].
- Optional: report non-LLM recipe errors as a refused recipe [#151].
- Indexes, measure first: `url_task (job_id, status, outcome)` if large-crawl listing is slow [#19, #146]; `job (started_at) WHERE status = 'running'` for `fail_stalled_jobs` and `expire_learn_runs`, which share one shape and could share one reaper [#195].
- Labeling pre-fill: return its diagnostics, a change to the prefill response shape (D-0847) [#111].
- Role C: confirm the `fast` Anthropic model accepts `output_config.effort` (D-0766); sparse 200-row listings spend ~14 output tokens per absent field; Gemini thinking is not lowered for role C [#159]. `max_output_tokens` may not hold 200 wide rows [#111].
- Resolve: a listing item stated in two syntaxes keeps only the first syntax's row; merging both entities into one row would add the other's values and their agreement [#196].
- Acquisition: CDP streaming for the browser's memory bound; proxy support and `proxy_bytes` usage in `fetch_json` [#52, #64].
- Normalize: a minus counts anywhere before the number (`numbers.negative`), so "In stock - 5 left" declines as negative; count it only when it touches the number, for money and count (D-0922) [#203].
- Normalize: `count` accepts `unitCode` `C62` with a contradicting `unitText` ("kg"); decide whether to decline any `unitText` beside C62 (D-0921) [#203].
- Normalize: `type:remote` (location) still matches its phrase anywhere, so "not remote" reads as remote; the first-clause rule (`vocab.stated_codes`) may apply there too, gated (D-0920) [#203].
- Role S: field-name drafts (`schema.fields`, `POST /v1/schemas/draft`) are charged to no job budget; only the per-key rate limit bounds them, and usage records them. Add a per-key cap on uncharged role S calls if it matters (D-0926) [#205].
- Playground: Extract's toolbar Schema and its "Schema source" option overlap, and a missing schema opens Options to show its message (UAT 2026-10-16) [#214].
- Playground: a map's URLs are not kept, so a map result is not in the address and is lost on back navigation [#214].
- Field tables: every field of an uncalibrated engine shows an `uncalibrated` badge; one badge per record would need a DESIGN.md and INV-22 change [#214].
- Playground: the options panel stays open while a run is shown; closing it on send would hide an options error [#214].
- Resolve: identity merge across collectors (microdata `itemid`/`sku` duplicates, one item in JSON-LD and microdata) belongs in `EntityGraph` with one shared union-find; `_same_nodes` anchors URL agreement to an identity's first node, so two later agreeing nodes can stay apart (D-0942) [#207].
- Resolve: renditions of one image across merged blocks (or an `http` og:image) still decline; publishing one needs a rendition rule (D-0944) [#207].
- Collect: `site_names._runs` is quadratic in `og:site_name`'s separator parts; cap the parts if long site names appear (D-0940) [#207].
- Round-1 eval: class 13 is §22 evidence (repeated-structure DOM collectors; class 10 is addressed by #208); classes 11 and 12 answered by the owner (D-1057, D-1058) [#207, #216].
- Playground: Records with Listing is still disabled ("not available yet"); the API serves listing records since #206 [#206].
- Recurring: SPEC-11 §4.5's listing diff tracks a listing crawl's page URLs, not its row URLs ("No job stores listing records" no longer holds), and a listing page gets no standing record (rows are keyed by row URL), so it is always re-extracted [#206].
- Listing items (`acquire.items`): the largest same-shape linked group wins, so a bare tag cloud or pager outside `nav` can outrank a small grid in markdown. Measure on dev first (D-0934, D-0993) [#206, #213].
- Markdown: trafilatura drops the space after an inline element whose parent is a `div`, `td` or `li` (`**Warning!**This`); fix upstream, or rewrap such runs before extraction with dev evidence (D-0994) [#213].
- Markdown: a listing page with no repeated items keeps only what trafilatura's `favor_precision` keeps (a UAT listing kept only its FAQ); compare recall mode on dev listings before changing it [#213].
- Crawl: each task that adds URLs looks up the start task's capture for the site's host (D-0991); store the host on the job if the query shows in profiles. A redirected start page is usually linked from itself, so its target is fetched again as a task [#213].
- Acquisition thresholds to confirm on dev: the 1024-byte terminal bound (D-0932) and the listing shell rule's effect on empty listings (D-0933) [#206].
- Collect: identifier widening (D-0965) also applies to a field mapped to `T.identifier` itself, pooling every scheme; stop at `identifier` or keep sub-properties of the field's `scheme` [#209].
- Resolve: a standalone variant Product beside its ProductGroup (no `isVariantOf`) gets none of the group's variants as rows; one eval page shows it, see SPEC-13 §9 (D-0966) [#209].
- Workflow tooling: if parallel tracker commits keep conflicting on ACTIVE.md, move their writes elsewhere (D-0823) [#192].
- For the owner: once labels exist, the gate compares precision only (§4.8), so a type the engine stops publishing shows only as lower coverage [#32].
- Collect: a `dom` label value that contradicts structured data turns an agreement-ranked field (money, identifier, enum, count, number) into `conflict`; measure the `dom` bucket's effect on required-field `conflict` at milestone M (D-0956) [#208].
- Precedence: `dom` ranks above `config` for text, long_text, url and image_url, so a config or operator field cannot override a DOM label value; re-check when `fit-precedence` first runs on dev (D-0956) [#208].
- Normalize: money still reads its amount with its own copy of the surrogate/NFKC/one-run steps that `numbers.stated` now holds for count and number; move it there, mapping its reason codes (D-0960) [#208].
- Config IR: `SchemaRef` names the schema only, so an operator can still activate a draft learned before a schema edit; a document digest in the IR would refuse it (D-0950) [#210].
- Normalize: `iso_3166_alpha2` keeps CLDR's EU, EZ and UN, which ISO 3166-1 reserves exceptionally rather than assigning to countries; exclude the exceptionally reserved codes [#210].
- Schemas: an edit's `relearn_schema` scans `progressive_state` by `schema_id`, which no index leads; add one if edits become frequent [#210].
- Worker: no production path passes `llm=None` to the page handlers any more (`task_handlers`); tests still use it to bind no role C. Make `llm` required and pass `NO_LLM` in tests [#215].
- LLM: role A and role C each fixed the provider's grammar cap their own way (D-1008); a new role with a repeated subschema should hoist it to `$defs` or use a named list, and a client-level check of schema size could catch it before a 400 [#215].
- LLM eval: role C's and role A's `request_hash` changed with their output schemas (D-1008), so recorded dev-eval replies are re-recorded on the next run [#215].
- Workflow tooling: `cleanup_worktree.sh` still removes per-worktree `crawlerai-<wt>-*` Postgres containers; drop that loop once none are left, since DB tests use `test_db.sh` (D-0971) [#212].

## [SPEC-03 — Evaluation and measurement](../specs/SPEC-03-evaluation-and-measurement.md)

Rows 1–6 and 8–12 done (#28, #27, #30, #33, #29, #32, #35, #42, #34, #39, #44).

| PR | Scope | Status | Notes |
|---|---|---|---|
| 7 | Protected job wired (replace placeholder) + dev report in `backend` job | human (H1, H2) | Changes the protected job (CLAUDE.md §4). From #32: run the gate before `put_run` on a push to `main` (or the candidate becomes its own baseline); store the unsuppressed report as `metrics`; check out with `fetch-depth: 0`. From #34: a rotation lowers hidden `n_pages`, so the next gate fails `n_pages_dropped` until a new baseline is recorded. |
