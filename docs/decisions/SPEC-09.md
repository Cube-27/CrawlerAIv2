# SPEC-09 decisions

Decisions for [SPEC-09 — API-backed pages: discovery, recipe binding (role D), validation, execution](../specs/SPEC-09-api-backed-pages.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0493 — Recipe splits into `RequestSpec` and `ApiRecipe`
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `RequestSpec` holds method, url, `params_from_url`, headers, body, pagination and `requires_page_fetch`; `ApiRecipe(RequestSpec)` adds `map` (at least one field) and a required `proof`.
- Alternatives: One model with optional `map`/`proof`.
- Why: Binding and role D (§4.5, "the `ApiRecipe` without `map`/`proof`") produce the request half; a stored recipe always carries its proof.
- Reversible: yes

### D-0494 — `bind` returns `RequestSpec | Ambiguous` over samples
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `bind(samples)`, where a `Sample` is the page URL, the captured request (method, URL, body) and the page's JSON documents by kind (`jsonld`, `js_state`) as the caller builds them.
- Alternatives: `bind(candidates) -> ApiRecipe` as the spec's module list sketches.
- Why: The map comes from discovery and the headers from replay (PRs 2–3), so binding can only produce the request half.
- Reversible: yes

### D-0495 — Binder grammar
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `path:<i>` counts page path segments after the leading `/` from 0; `query:<name>` takes the first non-empty value; `regex:<pattern>` is portable with exactly one group, searched over the raw path; `jsonld:`/`js_state:` take a `json_doc.select` query selecting exactly one scalar. Values compare percent-decoded and are re-encoded per place (RFC 3986 pchar in the path; `&`, `=`, `+` encoded in a query value); numbers compare as their JSON text.
- Alternatives: 1-based indexes; comparing raw strings.
- Why: One spelling per value lets URL and JSON sources meet; exact reproduction of every sample is still required.
- Reversible: yes, until recipes are stored

### D-0496 — Recipe JSONPaths use the engine's subset
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `map`, `pagination.rows` and data binders must be queries `json_doc.select` reads (`$['a'][0][*]`); dot notation (`$.data.name`, the spec's illustration) is refused.
- Alternatives: Accept dot notation and translate it.
- Why: What is stored is what the engine runs (§12.1); the config executor (#98) uses the same `select`.
- Reversible: yes

### D-0497 — Which values become parameters
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: Binding needs two sample pages. A value equal to a page-URL path segment or query value on every sample is bound, even when constant; a varying value with no URL source binds to a page-data path only when the same path holds it on every sample (`requires_page_fetch`); a constant without a URL source stays literal; a varying value without a source is `Ambiguous`. Parameters are `p1`, `p2`, … in order of first use.
- Alternatives: Bind only varying values; allow one sample.
- Why: One page cannot tell constants from parameters; binding constant page data would add a fetch for nothing; held-out validation (PR 4) checks the choice.
- Reversible: yes

### D-0498 — Credential headers are refused in the recipe model
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `Authorization`, `Proxy-Authorization` and `Cookie`, in any case (RFC 9110 §11.6.2, §11.7.2; RFC 6265 §5.4), never appear in a recipe; the token-value rule stays with header minimization (PR 3).
- Alternatives: Refuse only in PR 3's minimizer.
- Why: §4.6 says they are never kept; the model also guards role D output and operator corrections.
- Reversible: yes

### D-0540 — Captured network entries record their request method and body
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 2 (#113) · Status: decided
- Decision: `NetworkBody` gains optional `method` and `request_body` (UTF-8 text, else `None`); a request body over the 2 MB per-body cap skips the entry, as an oversized response does. Bundles written before decode with `None`; discovery skips their entries.
- Alternatives: Assume GET for unrecorded requests; bump `bundle_version`.
- Why: SPEC-09 §4.3 groups by request method and body, and `bind` needs both; assuming a method would be a default (C7).
- Reversible: yes

### D-0541 — Discovery groups endpoints by URL shape (spec clarification)
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 2 (#113) · Status: decided
- Decision: SPEC-09 §4.3's "URL without query values" reads as (method, `binding.url_shape`, request body shape): origin, path segment count and query names, plus the index-free paths of a JSON request body.
- Alternatives: The literal URL without query values.
- Why: An endpoint keyed by a path parameter has a different path on every page and would never group; binding then decides which segments are literal.
- Reversible: yes

### D-0542 — Discovery scoring and map paths (spec clarification)
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 2 (#113) · Status: decided
- Decision: Score = required fields (`required_fields`, groups included) with an `equal` reading, plus each other field with a visible leaf of its type that no required hit used. Money also reads ordered pairs of one object's scalar members joined with `+` (`joined_raw`, a space between), pairing only a member with a digit and one without (one amount run, `_AMOUNT_RUN`). A field's map path is the first path on page 1 that reads it on every page, indices kept; a candidate needs a required field in the map; the best body per endpoint stands for the page; ties keep capture order.
- Alternatives: §4.3's "first-match path identical after index stripping"; pairs across objects; all member pairs (quadratic, review of #113).
- Why: The most conservative reading of §4.3 that still finds paths when an earlier match differs by page.
- Reversible: yes

### D-0543 — Listing rows discovery goes to SPEC-09 PR 5
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 2 (#113) · Status: superseded by D-0604
- Decision: Discovery covers detail pages; `pagination.rows` discovery for listings comes with pagination in PR 5.
- Alternatives: Do it in PR 2.
- Why: Rows matter only to the pagination executor, and listing samples have many records per page.
- Reversible: yes

### D-0559 — Header minimization adds one captured header at a time (spec reading)
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 3 (#117) · Status: decided
- Decision: If no single captured header added to `Accept: application/json` makes the replay pass, the recipe is `not_learnable`; headers are not combined.
- Alternatives: Add all, then remove one at a time (delta debugging).
- Why: SPEC-09 §4.6's wording and its most conservative reading; every kept header is individually proven.
- Reversible: yes

### D-0560 — Captured headers never tried in a replay
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 3 (#117) · Status: decided
- Decision: Never tried: the client's own fields (`model.CLIENT_FIELDS`: Host, Content-Length, Transfer-Encoding, connection options, Accept-Encoding; RFC 9110/9112), which `RequestSpec` also refuses as it refuses credentials; HTTP/2 pseudo-headers; credentials; values that differ between sample pages; token-like values. A value is token-like when one of its items (split at whitespace, `,`, `;` and `.`, RFC 9110 §5.6, RFC 7515 §7.1) is 20 or more characters of one RFC 4648 base64 alphabet. `NotLearnable` names the withheld headers.
- Alternatives: A 20-character run anywhere in the value (flags `application/x-www-form-urlencoded`).
- Why: §4.6's structural token rule without catching media types; JWTs are caught by their parts (review of #117).
- Reversible: yes

### D-0561 — Replay compares map values with the published values
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 3 (#117) · Status: decided
- Decision: `replay.reproduces` compares `normalize(read_map(...))` with `equal` against `record.data` for every map field the page has a value for (at least one).
- Alternatives: Compare with the captured network body's leaves.
- Why: The same bar discovery used to pick the map; §4.7 compares against browser-captured values.
- Reversible: yes

### D-0562 — Captured network requests record their headers; `JsonRequest` sends method, headers and body
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 3 (#117) · Status: decided
- Decision: `NetworkBody.request_headers` is optional, recorded through `acquire.headers.recorded` (no cookies), `None` in older bundles. `JsonRequest` gains `method`, `headers` and `body`; the fetch's own Host and cookies win, and a redirected POST follows WHATWG Fetch §4.4.
- Alternatives: Bump `bundle_version`.
- Why: §4.6 replays "headers from the captured request"; consistent with D-0540.
- Reversible: yes

### D-0581 — An API recipe validates whole
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 4 (#121) · Status: decided
- Decision: A recipe is accepted only when every map field reproduces on every held-out page where the engine published it; one failing field refuses the recipe, and fields are not dropped from the map.
- Alternatives: Drop failing fields, as SPEC-08 §4.7 does for config fields.
- Why: SPEC-09 §4.7 accepts "when every field reproduces on every held-out page"; the conservative reading.
- Reversible: yes

### D-0582 — A map field published on no held-out page refuses the recipe
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 4 (#121) · Status: decided
- Decision: `never_published: <fields>`, which also covers a map field outside the schema.
- Alternatives: Accept it unchecked.
- Why: Nothing activates without validation (SPEC-08 §4.13); consistent with #118's `never_published`.
- Reversible: yes

### D-0583 — The recipe's report is part of `validation_report`
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 4 (#121) · Status: decided
- Decision: `ValidationReport.api_recipe = {held_out, fields: {<name>: {published, reproduced}}, refused}`, set by `api_recipe.validate.attach` whether or not the recipe was accepted; the recipe enters `Validated.ir.api_recipe` only when both the config and the recipe validated.
- Alternatives: A separate report column; drop the report of a refused recipe.
- Why: SPEC-09 §2 integrates the recipe into SPEC-08's validation report; an operator sees why a recipe did not enter (SPEC-08 §4.10).
- Reversible: yes

### D-0584 — A null published value is no value in replay
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 4 (#121) · Status: decided
- Decision: `replay.compare` compares only fields whose published value is not `null`.
- Alternatives: Compare against `null` (always fails).
- Why: D-0561 compares "every map field the page has a value for".
- Reversible: yes

### D-0599 — Recipe execution is a bound rung in `config_ir`
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 (#125) · Status: decided
- Decision: `config_ir/api_recipe/execute.RecipeRung` binds the recipe to `fetch_json` and the HTTP rung; `acquire(..., recipe=)` takes it as a rung, after adapters and before http/browser.
- Alternatives: `acquire/api_rung.py` taking an `ApiRecipe` (SPEC-09 §4.1 module list).
- Why: `.importlinter` layers `acquire` and `collect` below `config_ir`; the same injection as `collect.config.ConfigExecutor` (SPEC-08 PR 2).
- Reversible: yes

### D-0600 — The `api` collector returns `Executed`; the caller names the recipe
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 (#125) · Status: decided
- Decision: `collect/api.ApiCollector` gives page-owned values on a detail page; on a listing, `rows` items are `ListItem` rows with row-scoped map paths relative to the row. The recipe id in `api:<id>:<path>` is the id of the config holding it (D-0035).
- Alternatives: `CollectResult` with schema.org-typed entities; absolute `[*]` map paths.
- Why: a recipe knows no schema.org type; `Executed` is how config rows reach the pipeline (SPEC-08 PR 8 wires both).
- Reversible: yes, until recipes with rows are stored

### D-0601 — Recipe fallback rules (SPEC-09 §4.10)
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 (#125) · Status: decided
- Decision: an `ok` recipe result is kept; a 429/503 (from the endpoint or the HTML page fetch) is kept with no fallback; anything else, including an unbindable parameter, falls back to the configured method with the recipe's attempts recorded first.
- Alternatives: fall back on 429/503 too.
- Why: RFC 6585 §4, RFC 9110 §15.6.4: another request inside the backoff is one more, as for the browser retry (review of #125).
- Reversible: yes

### D-0602 — Binders read page data as lists of documents
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 (#125) · Status: decided
- Decision: `binding.page_data(page)` = `{"jsonld": [...], "js_state": [...]}` in page order, from `executor.documents`; learning builds `Sample.page_data` with it.
- Alternatives: one document per kind.
- Why: a page can hold several blocks; PR 1 tests already use the list form (`jsonld:$[0]['sku']`).
- Reversible: yes, until recipes with data binders are stored

### D-0603 — Pagination execution
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 (#125) · Status: decided
- Decision: every request, the first included, sets the query parameter to `start + n·step` (same-name items replaced, others kept as written); a response whose `rows` select nothing ends the listing and is not yielded; a non-`ok` one is yielded last; the HTML page is fetched once.
- Alternatives: leave the first request as captured.
- Why: SPEC-09 §4.8 "incrementing the parameter until `rows` is empty"; one rule for every page.
- Reversible: yes

### D-0604 — Pagination and `rows` discovery are not in SPEC-09 PR 5 (supersedes D-0543)
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 (#125) · Status: decided
- Decision: a recipe's `pagination` comes from role D (PR 6, whose output includes it) or an operator correction (SPEC-08 PR 10); discovery from listing samples is a follow-up.
- Alternatives: discover rows from listing samples in PR 5.
- Why: it needs listing records and successive captured requests, which nothing produces yet; §6 tests pagination on execution only.
- Reversible: yes

### D-0611 — Role D's repair round uses prompt kind `d_bind`
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 6 (#126) · Status: decided
- Decision: Both role D calls are `prompt_kind="d_bind"`; the repair is told apart by its system prompt (`d_bind.txt` + `d_repair.txt`).
- Alternatives: Add `d_repair` to `PromptKind`.
- Why: SPEC-06 §4.2 fixes the prompt kinds, and role D has one.
- Reversible: yes

### D-0612 — Role D writes the request without headers or pagination
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 6 (#126) · Status: decided
- Decision: The output schema is `{method, url, params: [{name, binder}], body}`. Headers come only from header minimization by replay (§4.6), `requires_page_fetch` is derived from the binders (`binding.request_spec`), and pagination is left out, as deterministic binding leaves it out.
- Alternatives: The full `RequestSpec` shape §4.5 names ("the `ApiRecipe` without `map`/`proof`").
- Why: The model sees header names only (§4.5), so it cannot propose values, and §4.6 keeps only headers "proven necessary by replay". Params are an array of closed objects, which providers' structured output handles.
- Reversible: yes

### D-0613 — Role D acceptance: reproduce the requests first, then minimize headers
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 6 (#126) · Status: decided
- Decision: A spec is replayed only after it reproduces every captured sample request exactly (`binding.mismatch`); only that failure gets the one repair round. A replay failure ends `NotLearnable` without a repair, since the spec's request is then the browser's own.
- Alternatives: Repair on replay failure too.
- Why: §4.5 "must reproduce the captured endpoint URL on every sample page and the replayed response must contain the mapped values"; no fetch happens for a URL the model wrote that the browser did not request.
- Reversible: yes

### D-0625 — The PHP hint takes its parameters from the caller
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 7 (#129) · Status: decided
- Decision: `api_recipe_request($page_url, $params)` takes each parameter's value from the caller; a comment per parameter names its binder and says how binders read the page; PHP does not evaluate binders.
- Alternatives: Port the path, query and regex binders to PHP.
- Why: Path-segment and percent-decoding details would be a second implementation to keep in step, and `jsonld`/`js_state` binders need the page's JSON documents anyway; the hint is a draft for review (§12.2).
- Reversible: yes

### D-0626 — The hint is `platform_draft.api_recipe_php`
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 7 (#129) · Status: decided
- Decision: `PlatformDraft` gains `api_recipe_php: str | None` beside `api_recipe`, set exactly when the IR has a recipe.
- Alternatives: A separate export format; a field inside the recipe object.
- Why: SPEC-09 §4.9 puts both in `platform_draft`, and the recipe stays the IR's model unchanged (D-0606).
- Reversible: yes

### D-0627 — Jinja2 renders the hint, with escaping enforced
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 7 (#129) · Status: decided
- Decision: Jinja2 (BSD-3-Clause) renders `api_recipe.php.j2` with `StrictUndefined`, autoescape on and a `finalize` that accepts only `php_literal`, `php_comment` or `php_int` values (a `Markup` subclass).
- Alternatives: `string.Template`; Python f-strings.
- Why: §4.9 names a `.j2` template, and `finalize` turns a missing escape into an error rather than an injection into the PHP.
- Reversible: yes

### D-0728 — A recipe serves a page only when its record is all the caller reads
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 follow-up, integration review R7 (#150) · Status: decided
- Decision: `scrape` with formats `["records"]` only; `batch_scrape` and `extract` records tasks; `crawl` records pages at `max_depth` only. Other pages are fetched themselves, and `max_age` reuses an `api` capture only for a record-only scrape.
- Alternatives: Always serve through the recipe.
- Why: A JSON body has no markdown, links or metadata of the page (SPEC-07 formats, SPEC-10 §4.5 link discovery); the most conservative reading of SPEC-09 §4.8.
- Reversible: yes

### D-0729 — A page the recipe served joins no drift window
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 follow-up, integration review R7 (#150) · Status: decided
- Decision: `ActiveConfig.drifts` is false for the recipe's executor; a page that fell back to HTML (§4.10) is recorded as usual.
- Alternatives: Record the `api` candidates as the fields' observations.
- Why: The window measures the config's page steps (SPEC-08 §4.9), which did not run; recording the page would show every field unmatched and suspend it.
- Reversible: yes

### D-0730 — The page fetched to bind is the fallback (refines D-0601)
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 follow-up, integration review R7 (#150) · Status: decided
- Decision: When the recipe fails (not 429/503) after its HTML page fetch reached the page, the rung's result is that page, with every attempt recorded; not for `method_hint=browser`.
- Alternatives: Fetch the page again (the #125 behaviour).
- Why: The second fetch is one more request for the same page: §4.10 falls back to the configured method, and that page is its HTTP form.
- Reversible: yes

### D-0731 — Endpoint politeness
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 follow-up, integration review R7 (#150) · Status: decided
- Decision: The endpoint's host gets a `site` row on first use; its robots.txt is checked when the policy respects robots, and a disallowed or unreachable one gives a `blocked` `api` attempt (`robots` / `robots_unreachable`) and the page is fetched instead. The request is admitted at the host's rate; the caller's admitted turn on the page's host goes to the first request there, and another waits in place (worker included, at most the host interval).
- Alternatives: No robots.txt or rate for endpoints; postpone the task.
- Why: SPEC-02 §4.6, RFC 9309 §2.3.1.4. A rung cannot postpone a task; waiting in place matches `PoliteHttp`.
- Reversible: yes

### D-0732 — The recipe executor's field status
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 follow-up, integration review R7 (#150) · Status: decided
- Decision: The config's field status, restricted to the fields the recipe maps.
- Alternatives: Every mapped field `corroborated`.
- Why: Role C is not asked for fields the executor covers (SPEC-08 §4.8); a mapped field the config does not run stays open to role C. `api` values are in the `adapter` bucket either way.
- Reversible: yes

### D-0733 — Recipe learning is a second PR
- Date: 2026-10-14 · Spec/PR: SPEC-09 PR 5 follow-up, integration review R7 (#150) · Status: decided
- Decision: Discovery, binding, role D, header minimization and held-out validation are wired into `run_learn_job` in `fix/recipe-learning`.
- Alternatives: Wire them in #150.
- Why: It needs a replay fetcher in the learner and network-body samples: design beyond R7's serving seam. The review report's Fix allows a second PR.
- Reversible: yes

### D-0734 — Recipe learning runs only after the config validates
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: `run_learn_job` learns an API recipe only when the HTML config validated.
- Alternatives: Learn a recipe for a refused config too.
- Why: `attach` lets a recipe into a validated config only (D-0583); replays for a refused config would be requests with no use.
- Reversible: yes

### D-0735 — Recipe learning is for detail schemas only
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: A listing run learns no recipe.
- Alternatives: Learn a listing recipe without `pagination`.
- Why: A listing recipe needs `pagination`/`rows`, which nothing discovers (D-0604); without them a listing would be served one page with no rows.
- Reversible: yes

### D-0736 — A recipe validates on held-out captures of its endpoint
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: A recipe's held-out pages are the held-out captures that hold an answer of the same endpoint (`discovery.endpoint_request`); fewer than `MIN_HELD_OUT` refuses it (`too_few_held_out`).
- Alternatives: Replay every held-out page.
- Why: SPEC-09 §4.7 validates "on the held-out captures (browser captures with network bodies)"; the conservative reading.
- Reversible: yes

### D-0737 — A recipe refused before validation is reported
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: `validation_report.api_recipe = {held_out: [], fields: {}, refused: "not_learnable: …" | "role_d_rejected: …"}`; no endpoint, or a listing, leaves `api_recipe` null.
- Alternatives: Report nothing.
- Why: An operator sees why a site with an endpoint has no recipe (D-0583, SPEC-08 §4.10).
- Reversible: yes

### D-0738 — A role D LLM failure fails the learning run
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: An LLM failure of role D ends the run as role A's does.
- Alternatives: Activate the config without a recipe.
- Why: Same handling as role A (D-0588); `role_d.bind_by_role_d` documents that its failures propagate.
- Reversible: yes

### D-0739 — Learning replays go with the default policy and the served path's politeness
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: `services.fetching.learning_replay`: the JSON rung with the default `FetchPolicy`, after the endpoint host's robots.txt (disallowed or unreachable → `blocked`, nothing sent) and at that host's rate, waiting in place.
- Alternatives: No robots.txt or rate for replays.
- Why: A `learn` job carries no fetch policy, and the default respects robots.txt; consistent with D-0731.
- Reversible: yes

### D-0740 — A replay's page URL is the capture's requested URL
- Date: 2026-10-14 · Spec/PR: SPEC-09 §2, §7 follow-up to D-0733 (#151) · Status: decided
- Decision: Binding and replay read the page URL from `manifest.url`.
- Alternatives: `final_url`.
- Why: Serving binds from the URL being acquired (SPEC-09 §4.8).
- Reversible: yes

### D-0777 — `learn_recipe` always says why a run has no recipe
- Date: 2026-10-15 · Spec/PR: SPEC-09 §4.7, UAT re-run 5c (#163) · Status: decided
- Decision: A listing, a sample without network bodies and a sample with no endpoint come back as `refused("<kind>: <reason>")` (`listing`, `no_network_bodies`, `no_endpoint`) instead of `None`.
- Alternatives: Keep `None` and leave `api_recipe` out of the report.
- Why: D-0583: the report says why; a forced learn on an API-backed site said nothing.
- Reversible: yes

### D-0877 — A config without a recipe does not run on an `api` capture
- Date: 2026-10-16 · Spec/PR: SPEC-09 follow-ups (#199) · Status: decided
- Decision: `ActiveConfig.for_capture` returns None for an `api` capture no adapter detects when the config has no `api` executor; a replay then extracts it cold.
- Alternatives: Refuse to replay it; run the page steps on the JSON (before).
- Why: Page steps read a page, not the JSON an earlier config's recipe fetched (review of #150). Live paths only see `api` captures of the current config's recipe (#195).
- Reversible: yes
