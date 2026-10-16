# SPEC-09 — API-backed pages: discovery, recipe binding (role D), validation, execution

Layer: L2. Architecture refs: §7.2 (all), §8.6 (infinite scroll through §7.2), §11 (role D), §12.1
(`api_recipe`), §12.2 (`platform_draft` code hint), Appendix A #4 (API-backed sites), OPEN_QUESTIONS #12.

## 1. Summary

Pages whose values arrive by XHR/JSON are a first-class path (Appendix A #4). From browser captures with
network bodies, find the endpoints that carry page values, bind a typed `api_recipe` from the page URL
deterministically (role D only when that is ambiguous), prove the headers by replay, validate on held-out
URLs against the browser capture, and then serve the site over `httpx` with the recipe (no browser). The
recipe is part of the IR (SPEC-08) and exports as data plus a PHP code hint.

## 2. Scope

Core:
- Discovery from `bundle.network` (SPEC-02 browser capture) on sample pages.
- `ApiRecipe` model; deterministic URL templating and parameter binding; header minimization by replay.
- Role D prompt and acceptance by replay.
- Held-out validation; integration into SPEC-08 learning and validation report.
- Execution rung in acquisition (`source_kind='api'` candidates via JSONPath map).
- Pagination parameter for infinite-scroll listings.
- Export hint rendering (template).

Out of scope (§22 and non-goals):
- Cookie handoff, session/auth tokens, signed requests, anti-bot (if a recipe needs them it is "not learnable"
  and the site stays on the browser rung — the measured `browser_seconds` is the admission evidence).
- API delta fetches (adaptive recurring).
- Any `exec` of generated code; the PHP hint is a rendered template of the data (§18).
- Platform-specific API knowledge (that is an adapter, C6/§22).

## 3. Dependencies

- SPEC-02 (browser capture with network bodies, `fetch_json`), SPEC-04 (`equal`), SPEC-05 (`xhr` candidates,
  visible index), SPEC-06 (client), SPEC-08 (IR, learning loop, validation report, export).
- OPEN_QUESTIONS #12: PHP snippet from a template.

## 4. Design

### 4.1 Modules

- `crawlerai.config_ir.api_recipe.model` — `ApiRecipe`.
- `crawlerai.config_ir.api_recipe.discovery` — `discover(sample: list[(bundle, extraction)]) -> list[EndpointCandidate]`.
- `crawlerai.config_ir.api_recipe.binding` — deterministic templating; `bind(candidates) -> ApiRecipe | Ambiguous`.
- `crawlerai.config_ir.api_recipe.headers` — header minimization by replay.
- `crawlerai.config_ir.api_recipe.role_d` — role D prompt and output validation.
- `crawlerai.config_ir.api_recipe.validate` — held-out validation.
- `crawlerai.acquire.api_rung` — execution: `fetch_recipe(recipe, page_url, policy) -> FetchResult(method='api')`.
- `crawlerai.collect.api` — JSONPath map → `Candidate(source_kind='api', locator=api:<recipe_id>:<path>)`.

### 4.2 `ApiRecipe`

```jsonc
{ "method": "GET"|"POST",
  "url": "https://example.test/api/products/{slug}",
  "params_from_url": { "slug": "path:3" | "query:id" | "regex:^/p/([^/]+)" },   // how to bind each {param} from the page URL
  "headers": { "Accept": "application/json", "Referer": "{page_url}" },        // only those proven necessary
  "body": null | { "template": "...json with {params}..." },
  "map": { "title": "$.data.name", "price": "$.data.price+$.data.currency" },   // JSONPath per field; '+' joins for atomic money
  "pagination": null | { "kind": "param", "name": "page"|"offset", "start": 1, "step": 1|<page_size>, "rows": "$.data.items[*]" },
  "requires_page_fetch": false,                                                 // true when a binder reads the HTML page (4.4)
  "proof": { "validated_on": [capture_id...], "headers_tried": n, "bound_by": "deterministic"|"role_d" } }
```

`params_from_url` binders are structural (path index, query name, or a regex over the path); the regex, when
used, is per-site data inside the IR (C3 allows it there).

### 4.3 Discovery (§7.2 step 1)

Input: the learning sample (SPEC-08) for a site whose sample captures are browser captures with network bodies
(or whose chosen candidates were `xhr`). For each sample page and each network body (JSON):
- score = number of the page's published required-field values that `equal` some scalar leaf of the body
  (using the field's normalizer on the leaf), plus `visible(leaf)` hits for leaves of the same type;
- an endpoint candidate is a `(request method, URL without query values, body shape)` group that scores ≥ 1
  required field on **every** sample page;
- the JSONPath for each field is the leaf path (array indices kept only for `pagination.rows` discovery;
  otherwise the first-match path must be identical across sample pages after index stripping, like induction).

Pages requiring more than one endpoint per field set are out of core (one recipe per config); the highest-scoring
endpoint wins.

### 4.4 Deterministic binding (§7.2 step 2)

For each sample page, align the page URL with the endpoint URL: a path segment or query value of the page URL
that appears verbatim as a path segment or query value in the endpoint URL becomes a parameter; its binder is
`path:<index>` or `query:<name>` from the page URL. The template is accepted if the same binders reproduce the
endpoint URL on every sample page. Values that appear nowhere in the page URL (ids only present in the HTML) are
looked up in the page's structured data / `js_state` leaves; if found at an identical path on every page the
binder is `jsonld:<path>` / `js_state:<path>` (the recipe then needs the HTML page first — recorded as
`requires_page_fetch: true`, two requests instead of a browser). Otherwise binding is **ambiguous** → role D.

### 4.5 Role D (§11)

- Input: the sample page URLs, the captured endpoint request (method, URL, headers names only, body) per page,
  and the JSON keys of the page's structured data; never page text.
- Output schema: the `ApiRecipe` without `map`/`proof` (a typed request spec, never code).
- Acceptance only by replay: the spec must reproduce the captured endpoint URL on every sample page and the
  replayed response must contain the mapped values (4.6). One repair round with diagnostics; failure → the site
  has no recipe (browser rung remains).

### 4.6 Header minimization and replay (§7.2 step 2, "headers proven necessary by replay")

- Start from no headers but `Accept: application/json`; replay with `httpx` (SSRF guard applies); compare the
  mapped values with the browser capture's values (`equal`).
- If the replay fails (non-2xx, or values differ), add headers from the captured request one at a time in the
  captured order, keeping a header only if its addition makes the replay pass; `Cookie`, `Authorization` and
  any header whose value looks like a token (≥ 20 chars of base64/hex — structural) are never kept: the recipe
  is then `not_learnable` with that reason.
- `{page_url}` is the only templated header value (Referer).

### 4.7 Validation (§7.2 step 3)

On the held-out captures (browser captures with network bodies): bind the URL, replay, map, and compare every
mapped field to the browser-captured value; the recipe is accepted when every field reproduces on every held-out
page where the browser had a value (same bar as SPEC-08 4.7). Accepted recipes enter the IR with their `proof`;
the config's `fetch.method` stays `http`.

### 4.8 Execution

When the active config has an `api_recipe`, `acquire` (SPEC-02 4.4) takes the adapter/API rung: bind params from
the page URL (fetching the HTML page first only when `requires_page_fetch`), `fetch_json` with the recipe's
headers, and produce a `FetchResult(method='api')` whose bundle body is the JSON. The `api` collector maps fields
through `map` into candidates; they are resolved like adapter candidates (`evidence=adapter` bucket, §10). `pagination` yields the next request for listings by incrementing the parameter until `rows` is empty
or the job limit is reached (this is how infinite scroll is served, §8.6).

### 4.9 Export (§7.2 step 4, §12.2)

`platform_draft` includes the recipe as data and a PHP hint rendered from `api_recipe.php.j2` (curl-based GET/POST
with the headers, param substitution, and `json_decode` + the JSONPath map as comments). The hint is a
rendering, not a program we run.

### 4.10 Error handling

Discovery and binding failures are diagnostics in the learning job; nothing is activated. Replay failures during
execution fall back to the configured `fetch.method` for that page and count against the config's yield (drift,
SPEC-08).

## 5. Invariants

INV-16 (replay and execution use the guard), INV-17 (no exec; template rendering only), INV-03 (no hostnames in
`api_recipe/`), INV-20 (recipe fields are part of the release check — the release executor evaluates JSONPath
on a stored replay response, not by fetching), INV-22.

## 6. Testing strategy

- Local test server serving an HTML shell page + a JSON endpoint keyed by a path param; browser-marked test
  captures network bodies; discovery finds the endpoint; binding is deterministic; replay passes with no extra
  headers; held-out validation passes; execution serves the page over `httpx` with `source_kind='api'`.
- Header minimization: server requiring `X-Requested-With`; the recipe keeps exactly that header. Server
  requiring a cookie → `not_learnable`.
- Ambiguous binding → fake role D returns a spec; acceptance by replay; a spec that does not reproduce is
  rejected.
- Pagination: offset-based endpoint; rows exhausted ends the loop.
- Property tests: binder round trip (`bind(apply(template, url)) == params`).
- No site-named tests.

## 7. Acceptance criteria (§21 L2 "API-backed pages with role D")

- On dev captures, `api_backed` sites with learnable endpoints are served with `method=api` and zero browser
  seconds after learning. **Milestone M (§21; not required to mark this spec done):** their field precision is reported per config status.
- Recipes in exported configs pass the release check or are marked `manual`.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | `ApiRecipe` model + binders + property tests | `api_recipe/model,binding` | property | Round trip. |
| 2 | Discovery from network bodies | `api_recipe/discovery` | browser-marked tests | Endpoint found. |
| 3 | Header minimization + replay | `api_recipe/headers` | unit (local server) | Minimal header set. |
| 4 | Held-out validation + IR integration | `api_recipe/validate`, SPEC-08 hooks | unit | Recipe in validated config. |
| 5 | Execution rung + `api` collector + pagination | `acquire/api_rung`, `collect/api` | unit | Pages served over httpx. |
| 6 | Role D | `api_recipe/role_d`, prompt | unit (fake LLM) | Accepted only by replay. |
| 7 | PHP hint template in `platform_draft` | exporter template | unit | Rendered hint contains the recipe. |

## 9. Open issues

- **Evidence bucket for `api` values.** Resolved in ARCHITECTURE rev 5 §10: the `adapter` bucket covers "adapter
  or API recipe" values.
- **Recipes needing cookies/tokens** are not learnable in core; the browser rung continues to serve such sites
  and the cost is measured (admission evidence for the §22 cookie-handoff candidate).
- **One endpoint per config** is a simplification of §7.2; multi-endpoint pages are measured as partial coverage.
