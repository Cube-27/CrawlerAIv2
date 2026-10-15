# Implementation tracker

The live state of implementation. Implementors write their rows and the follow-ups they leave in their PR's tracker
commit; a solo agent updates it in its PR (`CLAUDE.md` §3). One row is one entry of a spec's PR plan; one PR covers a
batch of rows. Spec dependencies are in `specs/README.md`. A row is ready when everything it needs is available: the
code it builds on is merged, or what it needs from unmerged work is fully specified. Readiness is per row (owner,
2026-10-13). Read by section, never in full (`CLAUDE.md` §1).

**Statuses:** `todo`; `done (#n)`: merged; `blocked (D-NNNN)`; `human`: waits on a human-only task (below).

Updated: 2026-10-15.

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

## Current focus

- SPEC-14 playground workspace (owner, 2026-10-15; ARCHITECTURE rev 17, D-0809): PRs 1–5 and 9 merged (3–5 in #194);
  next PR 6, then 7, 8 and 10, as batches. PR 11 (additional fields) is blocked on D-0810.
- Data accuracy: SPEC-13 is complete. Next: re-run the Shopify baseline and decide the adapter; then option (b),
  structural ownership of array rows, for checkable types inside related-item arrays.
- Open owner items: D-0311 (GeoNames pin), D-0355 (derived `url` provenance), D-0576 (`drift_margins.json`), D-0656
  (sites list), D-0665 (SimHash threshold), D-0782–D-0784 (investigate: variants and stock, learned-config approval,
  an "absent" field status), D-0810 (additional fields).

## Done specs

Full rows are in git history.

- [SPEC-00 — Project setup and engineering foundations](../specs/SPEC-00-project-setup.md): PRs 1–10 (#1, #3, #4, #9, #5, #6, #7, #8, #12, #10)
- [SPEC-01 — Persistence, job queue and capture storage](../specs/SPEC-01-persistence-queue-storage.md): PRs 1–8 (#11, #14, #17, #19, #13, #20, #23, #25)
- [SPEC-02 — Acquisition](../specs/SPEC-02-acquisition.md): PRs 1–10 (#16, #18, #22, #26, #31, #46, #53, #52, #62, #64)
- [SPEC-04 — Schemas and normalization](../specs/SPEC-04-schemas-and-normalization.md): PRs 1–9 (#43, #47, #58, #54, #57, #59, #60, #56, #66)
- [SPEC-05 — Extraction and resolution](../specs/SPEC-05-extraction-and-resolution.md): PRs 1–13 (#67, #72, #78, #83, #79, #85, #90, #94, #100, #86, #91, #106, #109)
- [SPEC-06 — LLM layer](../specs/SPEC-06-llm-layer.md): PRs 1–7 (#69, #74, #76, #107, #111, #92, #148)
- [SPEC-07 — API foundation and `scrape`](../specs/SPEC-07-api-foundation-and-scrape.md): PRs 1–8 (#70, #77, #80, #88, #105, #96, #81, #108)
- [SPEC-08 — Config IR, learning, progressive mode](../specs/SPEC-08-config-ir-learning-progressive.md): PRs 1–12 (#95, #98, #110, #114, #116, #118, #122, #127, #119, #123, #124, #115)
- [SPEC-09 — API-backed pages](../specs/SPEC-09-api-backed-pages.md): PRs 1–7 (#102, #113, #117, #121, #125, #126, #129)
- [SPEC-10 — Jobs, crawl, extract, MCP](../specs/SPEC-10-jobs-crawl-extract-mcp.md): PRs 1–10 (#120, #128, #130, #137, #140, #132, #144, #145, #146, #148)
- [SPEC-11 — Recurring crawls](../specs/SPEC-11-recurring-crawls.md): PRs 1–5 (#131, #135, #136, #142, #139)
- [SPEC-12 — Frontend application](../specs/SPEC-12-frontend-application.md): PRs 1–11 (#68, #73, #82, #87, #97, #134, #143, #141, #93, #147, #148)
- [SPEC-13 — Variant matrix](../specs/SPEC-13-variant-matrix.md): PRs 1–4 (#170, #172, #171, #174)

## Follow-ups

Open items left by merged PRs, one line each (source PR in brackets). Measure before redesigning where noted.

- Packaging: an installed wheel has no `backend/data`, `VERSION` or `calibration.json` (`ENGINE_VERSION = unknown+cal.none`, empty pricing); one PR decides where `EngineData.load` gets its directory and makes the build write `VERSION` (D-0492) [#100, #148].
- Playground: the batch JSON drawer shows a snapshot of its row and does not follow table refreshes; `screens/jobs/form.ts` imports from `playground/pageRequest` until rows 6–7 remove it [#194].
- Clarifying spec edits: SPEC-11 §4.2 names `task_record`, not `url_task.record_id` (D-0762), §5's INV-10/INV-11 citations, §4.4's `url_state.record_fingerprint` wording [#136, #158]; SPEC-05 §4.3 "expanded graph" (locators address each JSON-LD block as written) [#78]; SPEC-08 §4.11 `platform_draft` shape (D-0606) [#124].
- Job results paging builds the job's whole `task_record` set per page; measure on a ~100k-task job (paging by task id is the likely fix) [#158].
- MCP passes any `ValidationError` raised inside a tool to the client, a service's parse of a stored row included; validate the client's cursor in the tool and drop `ValidationError` from `_REFUSALS` [#195].
- Learning: SPEC-09 discovery, role D and recipe validation are not yet called from learning (needed with R7) [#149]. A cancel during a run's final transaction leaves the job `running` until `expire_learn_runs` [#195].
- The captures replay reads an old `api` capture with page steps when the active config has no recipe [#150]. Optional: report non-LLM recipe errors as a refused recipe [#151].
- `/v1/schemas`: retiring the latest version freezes the name; decide un-retire, reuse or PUT on a retired latest (D-0395) [#81].
- Page fetching: pass `fetch_politely` the HTTP rung for robots.txt; the browser retry through `HostLimiter`; check every attempt for `SLOW_DOWN` (D-0634) [#31, #128]. Robots snapshots are per site, but robots.txt is per scheme, host and port (RFC 9309 §2.3) [#26].
- Indexes, measure first: `url_task (job_id, status, outcome)` if large-crawl listing is slow [#19, #146]; `job (started_at) WHERE status = 'running'` for `fail_stalled_jobs` and `expire_learn_runs`, which share one shape and could share one reaper [#195].
- `release_expired_leases` runs in one transaction; add a per-run batch limit if many workers die at once [#19].
- Labeling pre-fill: return its diagnostics, a change to the prefill response shape (D-0847) [#111].
- Role C: confirm the `fast` Anthropic model accepts `output_config.effort` (D-0766); sparse 200-row listings spend ~14 output tokens per absent field; Gemini thinking is not lowered for role C [#159]. `max_output_tokens` may not hold 200 wide rows [#111].
- Recurring crawls: an equal fingerprint with a moved SimHash re-extracts every run (fix in `standing_record`); unchanged re-scrapes emit no `task.abstained`; `changed_since` can miss a late-committing row; `extract` jobs are not runs yet; a timed-out sitemap read is not a partial run [#136, #142].
- `TruncatedText` makes every event data and Reason cell a tab stop [#157].
- Resolve: `_linked` in `resolve/rows.py` compares every row pair; `holders()` could reuse `_single_offer`; zero-touch ignores a required row-mapped field (no preset has one) [#174, #176]. Optional: scan only url-typed key sub-fields for group URLs [#173]; `Final` on `_SET_NULL` [#177].
- Markdown: `_tidy` strips a list item's continuation indent; `markdown` deep-copies the tree twice [#162]. A replay pinning R1b with an Offer-rooted availability field [#161].
- Collectors: js_state reads only a script's first assignment [#86]; mixed-syntax microdata drops an `itemprop` under a `typeof`-only element [#83].
- Acquisition: CDP streaming for the browser's memory bound; public-suffix data for `Domain=` cookies; proxy support and `proxy_bytes` usage in `fetch_json` [#52, #53, #64].
- Smaller items from done-spec tables (unverified; check before building): theme tracks live OS changes and SPEC-00 §4.3's HeroUI licence/version [#4]; `commerce_detail` availability reads `type:availability` for DOM text [#54]; period words only in the page's languages, range's `to` separator into `vocab/` [#66]; key store to `db/`, one CLI transaction helper, `Forwarded`/XFF precedence [#77].
- More of the same, SPEC-05/08/09/10/11: a nested-wildcard list map gives one candidate per item [#91]; one record per row when JSON-LD and microdata repeat items [#106]; `Chosen.kept` required [#109]; css→xpath pinned across cssselect upgrades [#95]; release JSON-LD typing ignores `@context` [#110]; CSV formula injection if CSV is served as a download [#115]; the test `ScriptedClient` ignores `ReplyCheck` [#126]; the INV-27 markdown leg parses table cells back [#120]; each later markdown page rebuilds the capture's markdown [#144]; the `site` fixture into `tests/db/conftest.py` [#139]; two concurrent first uses of a new inline schema name give a 409 [#105].
- Workflow tooling: ruff/Oxlint rules for more of ENGINEERING's analyser patterns; if parallel tracker commits keep conflicting on ACTIVE.md, move their writes elsewhere (D-0823) [#192]. One shared fake-bin helper for the orchestrator script tests (`test_wait_ci`, `test_merge_pr`, `test_start_agent`, `test_cleanup_worktree`) [#193].
- `eval.labels.from_pydantic` moves below `eval` (services now import it) and formats every 422, `api/problems.py` included; it changes every 422's reason wording [#193].
- For the owner: once labels exist, the gate compares precision only (§4.8), so a type the engine stops publishing shows only as lower coverage [#32]. The project license (`AGPL-3.0-only` in `backend/pyproject.toml`) is the owner's call [#175].

## [SPEC-03 — Evaluation and measurement](../specs/SPEC-03-evaluation-and-measurement.md)

Rows 1–6 and 8–12 done (#28, #27, #30, #33, #29, #32, #35, #42, #34, #39, #44).

| PR | Scope | Status | Notes |
|---|---|---|---|
| 7 | Protected job wired (replace placeholder) + dev report in `backend` job | human (H1, H2) | Changes the protected job (CLAUDE.md §4). From #32: run the gate before `put_run` on a push to `main` (or the candidate becomes its own baseline); store the unsuppressed report as `metrics`; check out with `fetch-depth: 0`. From #34: a rotation lowers hidden `n_pages`, so the next gate fails `n_pages_dropped` until a new baseline is recorded. |

## [SPEC-14 — Playground workspace](../specs/SPEC-14-playground-workspace.md)

| PR | Scope | Status | Notes |
|---|---|---|---|
| 1 | Server-side key; drop Connect | done (#189) | D-0811, D-0812. |
| 2 | Playground shell + Scrape mode + options panel | done (#191) | D-0817–D-0819. |
| 3 | Single-page output with JSON default | done (#194) | D-0825–D-0827. |
| 4 | Batch mode + running results table + JSON drawer + CSV upload + export buttons | done (#194) | D-0828–D-0831, D-0833, D-0834. |
| 5 | Live activity feed | done (#194) | D-0832. |
| 6 | Crawl and Map modes inline | todo | Needs 5. |
| 7 | Extract mode; Jobs as history; `/jobs/:id` redirect; edit and re-run; recent runs | todo | Needs 6. |
| 8 | Batch from results | todo | Needs 6. |
| 9 | `json_values` results format (backend) | done (#190) | D-0813–D-0816. |
| 10 | Get code drawer | todo | Needs 7. Owner's reference shared 2026-10-15. |
| 11 | Additional fields (chips) | blocked (D-0810) | |
