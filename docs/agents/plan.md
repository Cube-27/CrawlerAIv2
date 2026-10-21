# Handover plan

The last plan before handover (owner-approved 2026-10-21): close open items, fix major bugs as classes, reduce test
debt, finish the one-home-per-concept refactors, update the docs. One builder per PR; `orchestrator.md` runs it. The
specs and `openspec/design/architecture-v3.md` govern; this file only orders the work. The orchestrator updates the
status table when it opens or merges a PR. Item ids in brackets (A6, B9, C1) name findings of the 2026-10-21 audit,
kept outside the repo with the eval reports.

Rules for every PR: one slice, 1–3k changed lines (deletes may exceed), deletes what it supersedes, spec delta in the
same PR, tests for removed code deleted, green CI, bot threads resolved. Sizes: S < 300, M 300–1k, L 1–3k lines.

## Status

| Plan PR | What | GitHub PR | State |
|---|---|---|---|
| D1 | Delete the in-repo golden-set machinery | #397 | merged |
| D2 | Delete dead runtime paths | #396 | merged |
| D3 | Repo hygiene deletions | #398 | merged |
| A1 | One cookie rule; the profile is the browser's cookie store | #403 | merged |
| A2 | Listing renders through the shared browser | #405 | merged |
| A3 | Site memory in its own short transactions | #400 | merged |
| A4 | One page run for scrape and the worker | | next |
| A5 | Decode and fingerprint a body once | | next |
| B1 | One document key, one item key | #399 | merged |
| B2 | One page-locale derivation | #401 | merged |
| B3 | Variant rows keep their stated amount | #402 | merged |
| B4 | One text module | #404 | merged |
| B5 | Image policy in one module; cached canonical | | next |
| E1 | Mid-point e2e (orchestrator) | | after A4, A5, B5 |
| T1 | DB tests: one engine per worker, shared fixtures | | after E1 |
| T2 | Slow tests trimmed, pairs merged | | after E1 |
| T3 | Path-gated sdk job; aligned pins | | after T1, T2 |
| F1–F6 | Bug and accuracy classes | | after E1 |
| X1 | architecture-v3 rewritten in place | | after F1–F6 |
| X2 | README, CONTRIBUTING, CLAUDE.md, HANDOVER.md | | after X1 |
| E2 | Final e2e (orchestrator) | | beside X1 |

## Owner decisions for this plan (binding)

- Page URL: when `<link rel=canonical>` and og:url or JSON-LD `url` disagree, the canonical wins (F2).
- Lever `createdAt` is not mapped (documented members only).
- `ng-cloak`/`v-cloak`/`x-cloak` content over HTTP: no change; the page stays `partial` with the render hint.
- Review widgets loaded client-side count as "render needed"; no engine change; HANDOVER states it.
- Not reopened: one cookie rule with clearance cookies kept; a visible page price applies only to a single-offer page;
  the structured name is published; class fixes only; no value reuse; HTTP-first; no proxies, no paid CAPTCHA.

## Remaining PRs

### Wave 1 (rest)

**A4 refactor(services): one page run for scrape and the worker; split scrape_steps** — L, risk medium. Deps: A3.
Scope (A7, A13): `services/page_run.py` core `page_run(fetched, records, *, retryable)` (cache read, failure mapping,
further-page storage); `services/scrape.py` and `worker/handlers/{steps,scrape,crawl}.py` become adapters; delete the
`_stored`/`_read_stored` vs `_stored_page` and `_finish` vs `unreached`+`extract_records` duplicates; collapse
`PagePlan`/`FetchPlan` where one suffices; split `scrape_steps.py` into `scrape_request.py`, `page_store.py`,
`page_formats.py`. Spec: jobs spec states that the worker's `cache` semantics equal scrape's. Verify: one scrape, one
batch of 3, one crawl of 5 against a local fixture server; verify-worker-queue. Parallel: B5.

**A5 perf(acquire): decode and fingerprint a body once; bounded network-body reads** — S/M, risk low. Deps: A2.
Scope (A6, A10): decode once in the rung and carry the text (`FetchResult` cached property); compute `platform` once
in `acquire` and stamp it for `memory`; remaining parses in `asyncio.to_thread`; `json_bodies` checks `post_data`
size first and gathers bodies bounded, order kept. Delete the repeated decodes in `rungs.py`, `memory.py`,
`page_refs.py`. Verify: one HTTP detail fetch timed before/after on a stored capture replay. Parallel: B5 (not A4:
shared files, A5 after A4 if they collide).

**B5 perf(resolve): image policy in one module; cached canonical; linear supersede; one JSON-LD parse** — M, risk medium. Deps: B4.
Scope (B9–B12, B16): `normalize/images.py` (resource key, rendition, secure-first, at-largest) replaces
`preference._secure_first|_largest_renditions|_at_largest|_secure` and `supersede._representative|_part_of`;
`lru_cache` on `normalize.url.canonical`; `supersede._by_length` precomputes `solid`/lines; `metadata._json_ld_types`
reads `ParsedPage.derived`'s parsed blocks; `js_state.attribute_documents` cached. Move the offers/variants part of
`preference.py` to `resolve/offers.py` and precedence loading to `score.py` (preference under 800 lines). Verify:
replay of one 50-image capture timed before/after (at least 5× fewer `canonical` calls). Parallel: A4 or A5.

**E1 mid-point e2e (orchestrator)** — Deps: A4, A5, B5. One run over the eval set to catch refactor regressions;
regressions classified per `orchestrator.md`; an engine regression becomes a fix PR before Wave 2.

### Wave 2: test debt and CI

**T1 test(db): one engine per worker, TRUNCATE teardown, shared fixtures** — M (−1.2k lines), risk low–medium. Deps: E1.
Scope (C1, C2, D6): `tests/db/conftest.py` session-scoped engine per xdist worker, rollback-per-test `conn` kept, one
`TRUNCATE … CASCADE` instead of the per-table DELETEs; `tests/db/support.py` with `kettle_schema`, `fetching_from(web)`,
the `Web` stand-in, `client`, `server`; delete the per-file copies. Verify: CI `--durations=0` before/after in the PR
body (backend pytest 2m18s → ≤ 90 s). Parallel: T2.

**T2 test: slow tests trimmed, unit/property pairs merged, redundant examples deleted** — M (−0.8k lines), risk low. Deps: E1.
Scope (C6, C9): `test_js_state_collector` chain 40 → 20 levels; `property/test_rows` "never merge" at
`max_examples=50`; `test_mcp_server` one stdio smoke, the rest in-process; merge the 8 same-name unit/property pairs
(rows, preference, grounding, evidence, release_executor, record_exporters, content_formats, api_recipe_binding) into
one file each, deleting example tests a property covers; deduplicate the `unit/db` overlaps (config_drift,
llm_client, role_s). Verify: CI durations. Parallel: T1.

**T3 ci: path-gated sdk job; local parallel pytest; aligned pins** — S, risk low. Deps: T1, T2.
Scope (C8, C11): one `sdk` job gated on `sdk/**` and `frontend/openapi.json` (tsc, the SDKs' own tests, ruff/mypy on
handwritten files); `sdk/typescript/src/schema.d.ts` generated from the one frontend file (delete the copy if the
generator can reference it, else keep the digest check); pnpm/TypeScript pins aligned with the frontend; Makefile
`check-backend` runs `pytest -n auto` with per-worker databases, no `patchright install` each run. Verify: CI green
with the new job skipped on a backend-only change.

### Wave 3: bug and accuracy classes (each one class, each with a synthetic fixture; two at a time)

**F1 fix(resolve): an extraction miss is `partial`, never `no_match`** — S/M, risk low. Deps: E1.
Rule: `no_match` only when no needed field has any candidate from the page; a page with candidates resolution
rejected, or with a `closed_shadow_root`/unreadable-content signal, is `partial` with the reasons and the render hint.
`records.states_entity` takes the candidate set, not only published fields. Spec: resolution "Incomplete pages", jobs
"Page outcomes". Verify: fixture (custom element without light DOM plus a stated title).

**F2 fix(resolve): the page's canonical link is the page-URL field's stated value** — S, risk medium. Deps: E1.
Rule: for the page-URL field only, a single `<link rel=canonical>` on the page's registrable domain (RFC 6596) is the
page's own URL; og:url and JSON-LD `url` naming another document are held to the page and rejected `other_document`;
without a canonical, behaviour is unchanged (conflicting canonicals → none; final-URL derivation per owner #40). Spec:
resolution "Derived values"; owner-decisions row. Verify: fixture with canonical ≠ og:url.

**F3 fix(collect): a meta summary naming the site is not the entity's description; a legend is not prose** — S, risk low. Deps: E1.
Rules: an `og:description`/`meta description` that contains the page's site name (`og:site_name`, else the title's
site segment) is the site's summary, not the entity's (extends `og.py`'s site-title rule; OGP "one to two sentence
description"); `legend` (HTML §4.10.16) is excluded from description text blocks. Spec: extraction "Structured-data
collectors", "cleaned text". Verify: fixtures.

**F4 fix(collect): a single stated image never fills an image list; gallery slides found by rendition** — M, risk medium. Deps: E1.
Diagnose first on the eval captures the orchestrator names in the brief (gallery blocks present, `_gallery` did not
read them), then ship the class rule found (expected: slides whose `srcset`/`data-src` renditions name the main
image's file family, outside the main image's tag path). Rule 2: `og:image` alone is one image, not a list; it fills
`additional_images` only beside DOM or structured slides. Galleries whose names exist only in inline state are out of
scope. Spec: extraction "images". Verify: fixtures.

**F5 fix(collect): inline-state rating and count that the page text shows are admitted** — S, risk low. Deps: E1.
Diagnose first on the pages named in the brief: did the admission rule refuse a value visible in the page text (bug:
fix the visibility match, e.g. number formatting) or a value not in the HTML text (by design, not done)? Only the bug
class ships. Verify: fixture.

**F6 fix(adapters): a `?variant=` id the product data lacks selects the default variant; a struck amount is a was-price** — S, risk low. Deps: E1.
Rules: Shopify `?variant=` not among `variants[].id` → the product's default (first available) variant, as the page
shows; a structured amount equal to a visible struck amount (`s`/`del`, HTML §4.5.5/§4.7.2) is the list price, so the
visible selling price wins. Spec: adapters "Shopify values", resolution price rule. Verify: fixtures; verify-money.

### Wave 4: documentation

**X1 docs(openspec): architecture-v3 rewritten in place; owner-decisions marked; specs state current behaviour** — M, risk none. Deps: F1–F6.
Scope (C3, C12, D5, A15): superseded paragraphs in §(f) and §(g) replaced by the current rule with a one-line pointer
to the owner row; (b) row 13 corrected (no per-site proxy pool); (e) table extended with this plan's deletions;
owner-decisions rows 40 and 60 "Superseded 2026-10-21 (#376)", row 50 "amended by #71", #67(12) resource blocking
removed (#393); new rows: cookie rule (A1), variant price (B3), canonical (F2), eval machinery deleted (D1);
`overview.md` L4 reworded; every "(Previously …)" clause moved to a dated section of `decisions/log.md`; INV-29 text
amended. Verify: `tools/decision_ids.py`.

**X2 docs: README, CONTRIBUTING, CLAUDE.md, HANDOVER.md** — S/M, risk none. Deps: X1.
Scope: README status line and docs table; CONTRIBUTING "evaluation report" → the e2e procedure; CLAUDE.md contract
lines C1/C10 matching `project.md`; `HANDOVER.md` at the repo root: what the system is and is not, how to run it (make
targets, env, profiles directory), how to run the e2e (eval set and scorer live outside the repo; the matcher caveat
for query-keyed item URLs), what is frozen (fitted data), open owner decisions, "Not done" below, machine constraints.

**E2 final e2e (orchestrator)** — Deps: F1–F6; runs beside X1. One run over the eval set with LLM (bounded LLM
budget, robots off, profiles directory set, fresh DB), compared page by page with the previous rounds: outcome deltas,
per-field agree/disagree, LLM values not on the page, blocked/shell per page. Engine regressions are fixed before
handover or listed in HANDOVER.

## Not done, and why

- JSON-LD `mainEntity` naming another product than the page's title: one-site exception, no class rule.
- `url` derived from the final address when the page states none: owner #40 specifies it.
- Hub/SPA listings, card price ranges, variant-dependent prices, og lead text from entity-escaped JSON-LD, galleries
  whose names exist only in state: no bounded class fix found; listed in HANDOVER.
- Client-rendered product data over HTTP: owner #70, no render for a lacking field; `render.mode: locate` is the
  design.
- LLM run-to-run variance in span choice: accepted; verbatim and grounding checks hold.
- Vendor bot blocks and 429s: out of scope (no proxies, no CAPTCHA).
- curl session pool per host (A12): SSRF pinning makes pooling non-trivial; gain unmeasured.
- Browser profile pruning (A9): the operator deletes the directory; a retention job is deferred.
- Role S label language tags: changes the public labels API; deferred.
- The e2e scorer stays outside the repo with the eval set.
