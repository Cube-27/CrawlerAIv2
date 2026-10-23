# Custom recipes plan

Owner-approved 2026-10-23. An engineer turns a hard-to-crawl domain into replayable HTTP calls once, by choosing
from the calls the site's own pages make; every later URL of that domain and page kind that a recipe's patterns match
is served in the selected schema without rendering. The system proposes, the engineer decides. A custom recipe is a
config (`extraction_config` row, origin `operator`), never code. The owner's spec is kept outside the repo; this file
holds every requirement a builder needs. `docs/agents/orchestrator.md` runs it; the orchestrator updates the status
table when it opens or merges a PR. The last PR deletes this file.

Rules for every PR: one slice, deletes what it supersedes, docs it makes wrong updated in the same PR, no second path
for existing logic (C8: the learned-recipe code in `config_ir/api_recipe/` is extended, never copied), site strings
only in fixtures with RFC 2606 names (C3), every generic rule cites its standard (C2), complexity ≤ 15 (C11),
green CI, bot threads resolved. Sizes: S < 300, M 300–1k, L 1–3k changed lines.

## What exists (build on it, never beside it)

- `config_ir/api_recipe/model.py`: `RequestSpec` (GET/POST, `{name}` placeholders, binders `path|query|regex|jsonld|js_state`,
  `HeaderValue`/`ContextHeader`, JSON `RequestBody`, four paginations), `ApiRecipe` (`map` field→JSONPath, `proof`).
  Credential values are refused; `token_like` literals never stored.
- `discovery.py` (endpoints scored by matching published values, `collect/network_match.endpoint_key` groups by
  method, URL shape, body shape), `binding.py` (`bind`, `resolve_params`, `render_url/body`), `headers.py` (`minimize`, proven by
  replay), `pagination.py` (`infer`, `first_request`, `next_request`), `replay.py` (`request_for`, `compare`),
  `validate.py`, `execute.py` (`RecipeRung`, `RecipeExecutor`), `listing.py`.
- `ExtractionConfigIR` (`config_ir/model.py`): `api_recipe` (whole-page recipe), `recipes` (per-field `call`
  companions), `fields: FieldSteps` (XPath/CSS/JSONPath/regex steps, `needs: http|call|browser`, `call`).
- Saving an operator config: `config_ir/corrections.py` + `activation.store_correction`; approval:
  `activation.approve/reject`, `services/configs.approve_config/reject_config`, `POST /v1/configs/{id}/approve|reject`.
- Active config: `config_ir/active.py:active_config` (one per site, schema, page kind; `ProgressiveState.active_config_id`),
  pinned per host at job submit (`services/batch.JobPins.configs`), read in `worker/handlers/steps.py`.
- Ladder: `acquire/rungs.acquire` (~l.175): adapter → learned recipe → page rungs. The recipe reaches it as
  `PagePlan.recipe` (`services/fetching.py` ~368) → `page_fetch` builds `recipe_rung` → `acquire(recipe=rung)`;
  `fetching.py` ~426 `by_adapter = rungs.adapters.would_serve(url)` disables the recipe on adapter sites. Attempts of a
  served rung come first in `FetchResult.attempts` (`with_attempts`); trail stored as `StoredFetch.attempts`
  (`AttemptRecord`, `acquire/types.py` ~182, has no recipe id).
- Browser capture: `acquire/browser_capture.DataCalls` keeps JSON/Flight/same-site HTML-fragment bodies of fetch/xhr/
  document requests (2 MB per body, 50 bodies, 10 MB per page) as `NetworkBody` (`storage/capture_bundle.py` ~68:
  method, URL, status, content type, resource type, request body, cookie-free headers via `acquire/headers.recorded`,
  `action`). Main-frame navigation responses are skipped first (~l.128). `action` counts `calls.actions`, which only
  listing actions bump (`browser_tab.py` ~199): page steps never do today.
- Page steps: `PageStep` (`acquire/types.py`), `acquire/page_steps.run_steps`, main-frame navigations tracked by
  `browser_wait.MainFrame`. Request context: `RequestContext` (secret headers/cookies, redacted on serialize).
  `PolicyFields` (`types.py` ~135) round-trips into `StoredFetch` by itself; `stored_fetch.made_as` (~75) decides cache
  reuse from steps/context/screenshot/content_only only.
- Shared browser: `acquire/shared_browser.SharedBrowser.render(work)` holds one of `BROWSER_CONTEXTS` slots; profiles
  (`acquire/browser_session._Profiles`, ~201) per (site, pool, exit), exclusive while taken, kept idle 60 s, at most
  `_OPEN_PROFILES`; every fetch opens and closes its own tab (`browser.py` ~298); temporary profiles are released on
  `keep`. No warm page yet.
- Drift: `config_ir/drift.record_run` (~179) suspends a drifted field and `_relearn` → `progressive.request_learning
  (force=True, locate=)` (~188; refuses while a run of the scope is in flight; `_LearnRequest` ~115 holds site, schema,
  page_kind, locate); learning: `config_ir/learn_job.run_learn_job` → `held_out.load_pages` (8 latest captures of the
  site, `_latest` selects from `Capture`, so `Capture.url` is there) → `learning.learned` → `_finish` (`activate`, or
  `store_pending` when `Project.require_config_approval`; `store_pending` needs `learning_started_at` and moves the
  scope's one `ProgressiveState`).
- URL globs: `crawl/rules.py` (fnmatch). No `{name}` path-template matcher, no HAR export, no capture-calls route, no
  fetch without a `ClaimedTask` (`page_task.fetch_task` needs the job and url_task rows `scrape._start` makes).

## Owner decisions for this plan (binding)

- Engineer-driven, not automated; output is always the selected schema; no publish step, approval or audit trail for
  saving; data verification is the user's; test pass criteria out of scope; robots.txt stays off by default.
- The recipe is per (site, schema, page kind) and serves any URL its patterns match. Several active recipes per scope,
  one per pattern set; identical pattern shape in the same scope → 409.
- **Learned config stays active.** Saving a recipe changes no other row's status: the recipe takes precedence for the
  URLs its patterns match; the learned config serves the rest. Learning never activates a config over a recipe's
  patterns and never samples URLs they match.
- **Ladder: custom recipe → adapter → learned recipe → page rungs.** Only operator recipes with patterns move ahead of
  adapters; learned recipes keep their place.
- **Engineer capture runs synchronously in the API process** (like `POST /v1/scrape`), no new job kind.
- Internals (calls, paths, headers) are shown on the Recipes screen only: a stated exception to "hide internals"
  (`docs/rules.md`).
- Endpoints follow the repo's resource convention (a recipe is a config): `POST /v1/sites/{host}/configs` creates,
  `PUT /v1/configs/{id}/recipe` edits (the existing `PUT /v1/configs/{id}` stays the correction); captures under
  `/v1/captures`; builder helpers that persist nothing under `/v1/recipes/{calls,propose,test}`.
- Out of scope (v1): detail pages without their own URL; WebSocket, event-stream and binary answers; logins, captcha,
  OTP; publish/review/audit workflow; daily health checks; test pass criteria.

## Status

| Plan PR | What | Deps | GitHub PR | State |
|---|---|---|---|---|
| cr1 | Recipe IR, URL patterns, selection by URL, save API | — | | next |
| cr2 | Engineer capture mode, call list, HAR | — | | next |
| cr3 | Serving: warm-up, extra calls, HTML answers, ladder order, rate | cr1 | | |
| cr4 | Propose and test endpoints | cr1, cr2, cr3 | | |
| cr5 | Learning leaves patterns alone; drift repair proposals | cr1 | | |
| cr6 | Browser-sent calls from a warm page | cr3 | | |
| cr7 | Recipes screen: list, samples, call list, main call | cr1, cr2 | | |
| cr8 | Builder: review, extra calls, test, save, repairs | cr4, cr5, cr6, cr7 | | |
| E1 | Final e2e (orchestrator) | cr8 | | |
| cr9 | E1 fixes, final docs, delete this plan | E1 | | |

Two builders at a time; the browser goes to one builder only (cr2 and cr6 need it). Ready order: cr1 ‖ cr2 → cr3 ‖ cr5 →
cr4 ‖ cr7 → cr6 → cr8 → E1 → cr9.

## PRs

**cr1 feat(config_ir): custom recipe IR, URL patterns, config selection by URL, save API** — L, risk medium. Deps: none.

Model (`config_ir/model.py`, `config_ir/api_recipe/model.py`):
- New `config_ir/url_pattern.py`: `UrlPattern` = host + path template of segments (RFC 3986 §3.3) where a segment is a
  literal, `{name}` (one segment, feeds a parameter; RFC 6570 level 1 syntax as `PLACEHOLDER` already uses), `*` (one
  segment), or a trailing `**` (the rest), plus optional `?key={name}` (other query keys ignored). Functions:
  `parse`, `match(pattern, url) -> dict[str, str] | None`, `shape(pattern)` (every `{name}` → `{}`; the identity for the
  409 rule), `most_specific(patterns, url)` (more literal segments, then longer path; deterministic tie-break on shape),
  `generalize(urls) -> list[UrlPattern]` (segments equal on every sample stay literal, the rest become `{p<i>}`; used by
  cr4). Property tests: match/shape/specificity in `tests/property/test_url_pattern.py`.
- `ExtractionConfigIR` gains `patterns: list[UrlPattern]` (empty for every learned config), `warm_up: WarmUp | None`
  (`url`: the page itself or a fixed template; its answer may bind parameters), `sent_by: Literal["http","browser"]`
  (`http` default). Validators: patterns only with origin `operator`; a config with patterns holds `api_recipe` (the
  main call); `warm_up`/`sent_by` only with patterns.
- `RequestSpec`: `answer: Literal["json","html"] = "json"`; `RequestBody.encoding: Literal["json","form"]` (form =
  `application/x-www-form-urlencoded`, HTML §4.10.21.7, placeholders percent-encoded); binder kinds `pattern:<name>`
  (a parameter from the matched URL pattern), `warm_up:<jsonpath>`/`warm_up_xpath:<xpath>`/`warm_up_regex:<one group>`
  (from the warm-up answer) and `main:<jsonpath>` (an extra call bound from the main answer; extra calls only). An HTML
  answer's `map` holds XPath 1.0 (`config_ir/xpath1.check_xpath1`) instead of JSONPath; `proof` optional for operator
  recipes (`validated_on` may be empty: proven by the engineer's test, not held-out). `requires_page_fetch` stays true
  exactly when a binder reads the page's documents; page-HTML fields stay ordinary `FieldSteps` (`needs: http`); a
  field only a render fills (`needs: browser`) is allowed and reported as `renders` on the summary.
- Extra calls are `recipes` entries named by `FieldSteps.call` (existing). Field map = `api_recipe.map` ∪ each extra
  call's `map` ∪ page-HTML `fields`; `ListingSpec.row`/recipe `pagination.rows` is the row path.
- The pydantic model `CustomRecipe` (`config_ir/custom_recipe.py`): the API body for create/edit — schema id, page
  kind, patterns, main call, extra calls, warm-up, field map, sent_by, `rate_ms` (per-recipe minimum interval, cr3
  applies it) — and `to_ir(schema, *, at, engine_version)` / `from_ir`. Credential values are refused as today.

DB (`db/models.py` ~364, `migrations/versions/0001_baseline.py` ~302, greenfield edit, plain column names as the repo
writes indexes): `extraction_config.patterns JSONB NOT NULL DEFAULT '[]'`, `pattern_shape TEXT NOT NULL DEFAULT ''`
(`''` = the learned config); `uq_extraction_config_active` becomes the partial unique on `(site_id, schema_id,
page_kind, pattern_shape) WHERE status = 'active'`. `ProgressiveState` keeps pointing at the learned config only.

Activation (`config_ir/activation.py`): `store_recipe(conn, key, ir, *, replaces: ExtractionConfigId | None)` → next
version of the scope (`_store`'s scope-wide `max+1` stays), `active` at once, suspends the previous active row of the
same pattern shape; `ConfigConflict` when another active row (not the one replaced) of the scope has that shape.
Every place that assumes one active row or one latest version per scope takes the pattern shape instead:
`_suspend_active` (~158; called by `activate`, `approve`, `store_correction` — without this a learned activation
suspends every recipe), `_lock_pending` (~90, "latest version of its scope"), `services/configs._latest_version`
(~223, the correction's 409), `config_ir/active.py` ~42 `.one_or_none()` (raises with two active rows),
`services/batch.py` ~274 `dict(rows)` (keeps one row per host silently). `learn_job._operator_since` is safe (joins
`ProgressiveState.active_config_id`).

Selection (`config_ir/active.py`): `active_config(conn, site_id, schema, vocabulary, url)` → the active recipe whose
pattern matches (most specific), else the learned config; `active_configs(conn, site_id, schema)` → all active rows of
the scope for pins. Callers that change: `services/scrape.py` ~505 `_config`, `services/captures.py` ~66 (replay),
`services/batch.py` ~270 (pins: `JobPins.configs: dict[str, list[ExtractionConfigId]]`, host → learned + recipes
active at submit), `worker/handlers/steps.py` ~70 (pick per URL, then `config_by_id`). `services/page_task.py` ~119
already takes the URL's config through `Records`. `ActiveConfig` gains `patterns` and `custom: bool`. A markdown-only
request returns `None` at `scrape.py` ~503 (`work.schema is None`): unchanged.

API (`services/configs.py`, `api/routers/configs.py`): `POST /v1/sites/{host}/configs` (`CustomRecipe` → 201
`ConfigDetail`, 409 `conflict`, 404 site/schema, 422 `invalid`), `PUT /v1/configs/{id}/recipe` (new version replacing
that recipe; 409 when `id` is not its shape's latest or the new shape collides). `ConfigSummary` gains `patterns`,
`custom`, `renders` (fields needing a render), `sent_by`. `GET /v1/sites/{host}/configs` lists recipes with the rest.
`uv run tools/dev.py api-client`; commit `frontend/openapi.json`, `schema.d.ts`, the SDK model files.

Verify: property tests above; `tests/db/test_configs_api.py` (create, edit, 409 on shape, list), `tests/db/
test_config_activation.py` (several active rows per scope, learned untouched), selection by URL in
`tests/db/test_recipe_serving.py` (two shapes, `/about` → learned); mypy, ruff, lint-imports. Runtime grounding: a
fixture server (`tests/db/support.Web`) with two URL shapes. Docs: `docs/architecture.md` "Learned configs" → describes
custom recipes and selection; `docs/decisions.md` adds the Custom recipes bullets (engineer-driven, learned stays
active, custom before adapters).

**cr2 feat(acquire): engineer capture mode, capture calls API, HAR export** — L, risk medium. Deps: none. Browser: yes.

- `acquire/types.py` `PolicyFields`/`FetchPolicy`: `calls: Literal["data","all"] = "data"`, added to
  `stored_fetch.made_as` so a cache read never hands a data-mode capture to an engineer capture. In `all`,
  `browser_capture.DataCalls` keeps every finished `fetch`/`xhr` response and every main-frame `document` response that
  follows a page step (form-submit navigations: move the main-frame skip at ~l.128 behind the `calls == "all"` check;
  `page_steps.run_steps` bumps `calls.actions` per step, as listing actions do, so `action` is the step index with 0 =
  page load), on any domain, whose answer is JSON (labelled, unlabelled,
  or behind a guard prefix such as `)]}'` — strip and note it), GraphQL, Flight, HTML, JSONP or text; WebSocket,
  event streams (`text/event-stream`) and binary media types (RFC 2046 top-level `image|audio|video|font`,
  `application/octet-stream`, `*zip*`, `*pdf*`) are not kept. Caps in `all`: 2 MB per body as today, 500 calls,
  50 MB per page; own-domain calls are listed first. `NetworkBody` gains `same_site: bool` (registrable domain via
  `acquire/public_suffix`), `guard_prefix: str | None`, and keeps form-encoded request bodies as text. Headers stay
  cookie-free (`headers.recorded`); context header values are masked with `core/redaction.REDACTED` in the manifest.
- `services/captures.py`: `capture(runtime, caller, CaptureRequest)` runs the page task synchronously as
  `POST /v1/scrape` does with `render.mode = browser`, the request's page steps, request context and proxy pool,
  `calls = all`, persisting the capture and its record (it is a sample), returning `CaptureResult{capture_id, url,
  records, attempts}`. Route `POST /v1/captures` (`api/routers/captures.py`, 200; `Caller` for LLM accounting).
- Call list: `services/recipe_calls.py` over `config_ir/api_recipe/discovery.py` (extend `_bodies`, `member_pairs`,
  `normalized`; grouping by `network_match.endpoint_key`): per endpoint group → method, URL shape, body shape,
  samples it appears on, calls (index, status, content type, resource type, step, same_site, size), and per schema
  field: matched path(s) with "n of m samples" (value equal to the published value by the field type's normalizer,
  `normalize/dispatch.equal`), or for fields with no published value, candidate paths whose value is of the field's type
  (`dispatch.normalize` accepts). For HTML answers: whether each published value's text occurs in the answer (no
  path; the engineer writes the XPath). Row path proposal for rows (`network_match.row_series` / `_rows`). Deterministic,
  no LLM. Routes: `GET /v1/captures/{id}/calls` (one capture), `POST /v1/recipes/calls` `{capture_ids: 2..5}` (merged
  across samples, same shape), `GET /v1/captures/{id}/calls/{n}` (one call: request/response headers, request body,
  answer text capped at 2 MB), `GET /v1/captures/{id}/calls.har` (HAR 1.2, cookie-free, context values masked;
  `services/har.py`, `application/json`).
- Verify: unit tests for `DataCalls` in `all` mode on a synthetic page (own + other domain, guarded JSON, form submit
  after a step, caps), unit for HAR shape, property for grouping/matching counts; `tests/db` for the routes. Runtime
  grounding: one capture of a public JS-rendered page via the CLI/API, read the call list. Docs: architecture "Acquire"
  (capture modes) and "Surfaces".

**cr3 feat(acquire): serving a custom recipe: warm-up, extra calls, HTML answers, custom before adapters, rate** — L,
risk medium. Deps: cr1.

- `config_ir/api_recipe/execute.py` `RecipeRung`: (1) warm-up request first, same fetch, its cookies kept in that
  fetch's jar (`acquire/session.py` site session, or the JSON client's jar for the one fetch), its answer parsed as
  JSON or HTML (`content/page.py`) for `warm_up*` binders; (2) the main call (GET/POST, JSON or form body, JSON or HTML
  answer); (3) extra calls bound from the page URL, the warm-up answer or the main answer (`main:` binders), each
  filling its `map`; a detail answer is kept only when it identifies the item (`acquire/identity.identified`, as today).
  HTML answers: the capture is stored as an `api` capture with `text/html`; `collect/api.ApiCollector` (or a sibling
  reading the same `map`) evaluates XPath over `content/page.py`'s parse. No second rung: one `RecipeRung`, branches
  on `answer`/`encoding`/`warm_up`.
- Ladder: `acquire(…, custom: Rung | None = None)` tries the custom recipe before `rungs.adapters.serve` (~l.175),
  keeping the `served`/`by_recipe` bookkeeping so `with_attempts` (~197) lists its attempts first; learned recipes stay
  after adapters. `services/fetching.page_fetch` passes the recipe as `custom` when the config has patterns
  (`PagePlan.recipe` + `ActiveConfig.custom`); `by_adapter` (~426, `would_serve`) and `uses_recipe` (~385) must not
  disable a custom recipe on an adapter site, and `polite_fetch(by_adapter=)` paces its endpoint host as a recipe's.
  On any failure the URL continues as if no pattern matched. `AttemptRecord` gains `recipe: str | None` (the config
  id; `exclude_if` None, in the `data_call` style) so the trail names the recipe; it reaches `StoredFetch.attempts`
  by itself. Fields mapped to page HTML need the HTTP page (`requires_page_fetch` path).
- Per-recipe rate: `rate_ms` applied in `services/fetching._polite_send` beside the host limiter (never below it).
- Verify: `tests/db/test_recipe_serving.py` (warm-up cookie → main call; extra call bound from main answer; HTML answer
  by XPath; form body; failure → page rungs with recipe attempts first; adapter site served by the recipe first);
  property test for form encoding round-trip. Runtime grounding: fixture server. Docs: architecture "Pipeline 1".

**cr4 feat(services): propose and test a recipe** — M, risk low. Deps: cr1, cr2, cr3.

- `POST /v1/recipes/propose` `{capture_ids, main: {endpoint key or capture call index}, schema_id}` → `CustomRecipe`
  draft, persisting nothing: parameter binding via `binding.bind` (deterministic only; `Ambiguous` → the parameter is
  left as a literal and reported), pagination via `pagination.infer` over the call series, headers via
  `headers.minimize` (constants only; a credential header → `ContextHeader`), field map from the confirmed matches
  (cr2's matcher), patterns via `url_pattern.generalize`. The response also carries the `unfilled` fields and the
  parameters it could not bind. Every engineer edit is theirs: propose is a pure function of its inputs.
- `POST /v1/recipes/test` `{recipe: CustomRecipe | config_id, urls, fetch options}` → per URL the recipe's records,
  the normal extraction's records (the ladder as if no pattern matched) and both fetch trails. "Persisting nothing"
  means no capture, record, config or site memory/decline row: the test calls `page_task.fetch_task` +
  `page_run.extract_run` (~228) and never `page_run`/`settle_task` (which always `store_capture` + `store_kept`);
  `page_task._kept` and `fetching.store_declines` are skipped for a test fetch (one flag on the task, no second path).
  Plan decision: a test run does create a `scrape` job row with its url_tasks (`scrape._start`) so fetch usage is
  counted against the key (`record_fetch_usage`); the job ends `done` with no results. A `browser`-sent recipe whose
  calls fail reports `cannot_replay` (cr6 fills it in).
- Verify: `tests/db/test_recipes_api.py` (propose round-trips on samples: rendering the proposal reproduces each
  sample's request; test returns both record sets and no new rows). Docs: architecture "Surfaces".

**cr5 feat(config_ir): learning leaves custom patterns alone; drift repair proposals** — M, risk medium. Deps: cr1.

- `held_out.load_pages`/`_extractions` (~229): over-fetch the scope's latest captures and drop in Python those whose
  `Capture.url` a recipe of the scope matches (`url_pattern.match`; patterns are not SQL), until the limit is filled;
  `learn_job._finish`/`activation.activate` only ever replace the `pattern_shape = ''` row (cr1's index and
  `_suspend_active(shape)` guarantee it; assert it). `progressive.trigger_learning` unchanged.
- Drift on a recipe (`drift.record_run` ~179, `_relearn` ~213): the drifted field is suspended as today (cold
  extraction for that field), and the relearn request carries `repair=config_id`: `progressive.request_learning`
  signature and `request` dict, `_LearnRequest.repair` (~115), `StateKey.repair_of` beside `locate_of` (~134), read in
  `learn_job._start` (~154) into `_Run`. A repair run is one learn job of the scope (the one-in-flight rule holds),
  samples = captures matching the recipe's patterns; it runs `api_recipe.learn.learn_recipe`'s discovery/binding/
  minimize over them with the recipe's endpoint preferred, keeps every engineer-given part that still replays, and
  produces the recipe's next version with the repaired path, call or parameter, stored `pending_approval` against that
  pattern shape by `store_pending(shape=)`, which for a shape ≠ `''` inserts the row without moving the scope's
  `ProgressiveState` (that state is the learned config's); nothing applies without approval. `approve` → active
  (suspends the current version of that shape); `reject` keeps it. `ConfigSummary` gains `drifting: list[Name]`,
  `pending_repair: ExtractionConfigId | None`; `ConfigDetail` of a repair carries the diff vs the current version
  (changed paths/calls/parameters).
- Verify: `tests/db/test_config_drift.py` (drift on a recipe → pending repair, learned row untouched), `tests/db/
  test_learning_run.py` (samples exclude pattern URLs; a forced learn never suspends a recipe). Docs: architecture
  "Learned configs".

**cr6 feat(acquire): recipes sent by the browser from a warm page** — M, risk medium. Deps: cr3. Browser: yes.

- `acquire/browser_session.py` `_Context`/`_Profiles` (~168, ~201): a warm page on the site's own (non-temporary)
  profile — one tab opened on first use at the warm-up URL or the recipe's page, kept while the profile is open
  (`keep`'s 60 s idle timer), closed with the context's stack; `SharedBrowser.send(site, request)` takes the profile
  like a render (`take`/`keep`, exclusive while taken, within `BROWSER_CONTEXTS`) and runs the request through the
  page's own `fetch` (`page.evaluate`, `credentials: "include"`, method, headers, body), returning status, headers,
  body; nothing is rendered per URL. `RecipeRung` uses it for `sent_by = browser` (same identity, proxy and per-host
  rate). A site that signs requests in application code makes the test answers fail: `POST /v1/recipes/test` reports
  `cannot_replay` with the status seen.
- Run `verify-worker-queue` (shared_browser is in its path). Verify: a `tests/browser` test on a fixture page whose
  fetch hook adds a header the server requires. Docs: architecture "Acquire".

**cr7 feat(frontend): Recipes screen: list, samples, call list, main call** — L, risk low. Deps: cr1, cr2.

- Routes `sites/:host/recipes`, `sites/:host/recipes/new`, `recipes/:id` (`app/router.tsx`); `api/captures.ts`,
  `api/recipes.ts`, hooks in `api/hooks/` (TanStack Query, keys under `["recipes", …]`), types from the generated
  `schema.d.ts` only.
- `screens/recipes/RecipesScreen.tsx`: per-site list (patterns, page kind, schema, version, drifting fields, pending
  repairs) with a link from `SiteScreen`. `RecipeBuilder.tsx` steps 1–4: pick schema → sample URLs (2–5) with page
  steps (`components/StepsEditor.tsx`) and request context/proxy pool, each capture run on add with its records →
  call list grouped by endpoint, own-domain first, each group with its field matches ("price at $.data… on 3 of 3"),
  a call drawer (HeroUI `Drawer`) with headers/body/answer and a HAR download → pick main call. Internals are shown
  here only.
- Skills to apply: `atomic-design`, `ui-layout-stability`, `typescript-best-practices`, `crawlerai-owner-preferences`
  (HeroUI as is, no design review). `tools/theme_only_check.py` and complexity lint apply. Tests: vitest per screen
  with the stubbed API (`test/api.ts`), `--maxWorkers=1`.

**cr8 feat(frontend): builder: review, extra calls, warm-up, HTML fields, test, save, repairs** — L, risk low.
Deps: cr4, cr5, cr6, cr7.

- Steps 5–8: review the proposal (binding, pagination, headers, field map, patterns; every value editable; an edit is
  never overwritten by a later propose) → add extra calls (pick from the call list, bind from page URL / warm-up /
  main answer), a warm-up request, or page-HTML XPath fields for unfilled fields; fields needing a render are flagged
  → test on any URLs (recipe records beside normal records, both trails; `cannot_replay` shown for browser-sent
  failures) → save (409 shown with the conflicting recipe; `sent_by` toggle). Every field shows its source and its
  value on each sample. Editing an existing recipe loads its config into the same builder. Pending repair: diff vs
  current with approve/reject (existing hooks).
- Tests as cr7. Docs: `docs/rules.md` "Hide internals from users" gains the Recipes-screen exception;
  architecture "Surfaces" names the screen.

**E1 final e2e (orchestrator)** — Deps: cr8. One run over the eval set (no recipes exist for it, so the ladder change
and selection by URL must leave every field type's aggregate unchanged); regressions classified per
`orchestrator.md`; an engine regression becomes a cr9 item.

**cr9 fix/docs: E1 fixes, final docs, delete this plan** — S, risk low. Deps: E1. Engine regressions from E1 (as
classes), a last pass over `docs/architecture.md`, `docs/decisions.md`, `docs/rules.md`, and `git rm docs/agents/plan.md`.

## Verification (whole plan)

- Each PR: mypy, ruff, lint-imports, complexipy on its files; the test files it touches, one at a time; `uv run
  tools/dev.py api-client` and the SDK model files when a route or model changes; `verify-worker-queue` for cr6.
- Runtime grounding per PR as listed; cr4+cr8 end-to-end: capture two sample URLs of a fixture site (`Web`), list calls,
  propose, test, save, then `POST /v1/scrape` a third URL of the pattern and read the trail: `api` attempt first, no
  browser.
- E1 is the only e2e run (no per-PR eval). Claims about generalization are not made: recipes are per site by design.
