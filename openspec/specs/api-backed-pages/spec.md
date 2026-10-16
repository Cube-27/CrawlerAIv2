# API-backed Pages Specification

## Purpose

Pages whose values arrive by XHR/JSON are a first-class path. From browser captures with network bodies the system
finds the endpoint that carries the page's values, binds a typed `api_recipe` from the page URL (deterministically,
LLM role D only when that is ambiguous), proves its headers by replay, validates it on held-out pages, then serves
the site's pages over `httpx` with no browser, and exports the recipe as data plus a PHP hint. The browser capture is
[acquisition](../acquisition/spec.md); the config IR, learning loop and validation report are
[learning-configs](../learning-configs/spec.md); role D's prompt and client are [llm](../llm/spec.md); platform API
knowledge is [adapters](../adapters/spec.md).
Design rationale: [ARCHITECTURE §7.2](../../design/acquisition.md), [§11](../../design/llm.md),
[§12](../../design/config-ir.md). History:
[SPEC-09](../../changes/archive/2026-10-13-spec-09-api-backed-pages/SPEC-09-api-backed-pages.md) and its
[decisions](../../changes/archive/2026-10-13-spec-09-api-backed-pages/decisions.md).

## Requirements

### Requirement: Recipe model
An `api_recipe` SHALL be a `RequestSpec` (`method` GET or POST, `url` template, `params_from_url`, `headers`,
`body` template, `pagination`, `requires_page_fetch`) plus a `map` of at least one field and a required `proof`
(`validated_on`, `headers_tried`, `bound_by` `deterministic` or `role_d`). `map`, `pagination.rows` and data binders
MUST be queries in the engine's JSONPath subset (bracket notation, `$['a'][0][*]`); a money entry may join two queries
with `+`. The model MUST refuse `Authorization`, `Proxy-Authorization` and `Cookie` in any case, and the client's own
fields (Host, Content-Length, Transfer-Encoding, connection options, Accept-Encoding). A recipe is data run by the
engine, never code.
Refs: §7.2 step 2, §12.1, §18, SPEC-09 §4.2, D-0493, D-0496, D-0498, D-0560.

#### Scenario: Dot-notation map
- **WHEN** a recipe's map holds `$.data.name`
- **THEN** the recipe is refused

### Requirement: Endpoint discovery
Discovery SHALL read the network JSON bodies of a site's sample browser captures, grouping requests by (method, URL
shape: origin, path segment count and query names, request body shape). A body's score is the required fields whose
published value `equal`s one of its scalar leaves under the field's normalizer, plus other fields with a visible leaf
of their type; a money field may also read an ordered pair of one object's members joined with `+`. An endpoint is a
candidate only when it scores a required field on every sample page; a field's map path is the first path on page 1
that reads it on every page, indices kept. The highest-scoring endpoint wins (one endpoint per config). Network
entries without a recorded method are skipped.
Refs: §7.2 step 1, SPEC-09 §4.3, D-0035, D-0540, D-0541, D-0542.

#### Scenario: Endpoint keyed by a path parameter
- **WHEN** samples requested `https://example.test/api/items/12` and `.../items/34`, each holding the page's title
- **THEN** both group as one endpoint with a map path for `title`

### Requirement: Deterministic binding
Binding SHALL need at least two sample pages. A page-URL path segment or query value that appears verbatim
(percent-decoded) in the endpoint request on every sample becomes a parameter (`p1`, `p2`, ... in order of first
use) with binder `path:<i>` (0-based after the leading `/`), `query:<name>` (first non-empty value) or
`regex:<pattern>` (exactly one group, over the raw path). A varying value with no URL source binds to `jsonld:<query>`
or `js_state:<query>` only when the same query selects it on every sample, which sets `requires_page_fetch`; a
constant without a URL source stays literal. The template is accepted only if it reproduces every sample request
exactly; otherwise binding is ambiguous and goes to role D.
Refs: §7.2 step 2, SPEC-09 §4.4, D-0494, D-0495, D-0497, D-0602.

#### Scenario: Round trip
- **WHEN** a recipe is bound from samples and applied to a sample page URL
- **THEN** it reproduces that page's captured endpoint request

### Requirement: Role D binding
When binding is ambiguous, role D SHALL receive the sample page URLs, each captured request (method, URL, header
names only, body) and the JSON keys of the page's structured data, never page text, and return
`{method, url, params: [{name, binder}], body}`, with no headers or pagination. Its spec is replayed only after it
reproduces every captured request; only a reproduction failure gets one repair round (`prompt_kind="d_bind"`). A
replay failure or a second miss leaves the site with no recipe; an LLM failure fails the learning run. Prompt and
client are [llm](../llm/spec.md).
Refs: §7.2 step 2, §11, SPEC-09 §4.5, D-0611, D-0612, D-0613, D-0738.

#### Scenario: Spec that does not reproduce
- **WHEN** role D's spec yields a URL the browser never requested, twice
- **THEN** no fetch is made for it and the recipe is refused `role_d_rejected`

### Requirement: Headers proven by replay
Replay SHALL start with only `Accept: application/json` through the JSON rung (SSRF guard included). If it fails
(non-2xx, or a mapped value differs), the system adds one captured header at a time in captured order, keeping one
that alone makes the replay pass; headers are not combined. Credentials, client fields, HTTP/2 pseudo-headers, values
that differ between samples, and token-like values (an item of 20 or more characters of one RFC 4648 base64
alphabet) are never tried; when none passes the recipe is `not_learnable`, naming the withheld headers. `{page_url}`
is the only templated header value.
Refs: §7.2 step 2, SPEC-09 §4.6, D-0559, D-0560.

#### Scenario: Required header
- **WHEN** an endpoint answers only with `X-Requested-With`
- **THEN** the recipe keeps exactly that header

#### Scenario: Cookie needed
- **WHEN** an endpoint answers only with the captured cookie
- **THEN** the recipe is `not_learnable` and the site stays on its page rungs

### Requirement: Replay comparison
A replay SHALL reproduce a page when `normalize(read_map(answer))` `equal`s the page's published `record.data` for
every map field the page has a non-null value for, and at least one.
Refs: SPEC-09 §4.6, D-0561, D-0584, D-0740.

#### Scenario: Null published value
- **WHEN** the page published `brand: null`
- **THEN** `brand` is not compared

### Requirement: Held-out validation
A recipe SHALL be accepted only when every map field reproduces on every held-out page where it was published; one
failing field refuses the whole recipe, and a map field published on no held-out page refuses it
(`never_published`). Held-out pages are the held-out captures holding an answer from the same endpoint; fewer than
3 refuses it (`too_few_held_out`). `validation_report.api_recipe = {held_out, fields: {<name>: {published,
reproduced}}, refused}` is set whether or not it was accepted; the recipe enters the IR only when both the config and
the recipe validated, and `fetch.method` stays `http`.
Refs: §7.2 step 3, SPEC-09 §4.7, D-0581, D-0582, D-0583, D-0736.

#### Scenario: One field fails
- **WHEN** `price` does not reproduce on one held-out page
- **THEN** the recipe is refused and not stored in the IR

### Requirement: When a recipe is learned
The system SHALL learn a recipe only for a detail schema and only after the HTML config validated. A run with no
recipe SHALL say why in `validation_report.api_recipe.refused`: `listing`, `no_network_bodies`, `no_endpoint`,
`not_learnable: ...`, `role_d_rejected: ...`. Recipes needing cookies, session or auth tokens or signed requests are
not learnable in core (§22 cookie handoff).
Refs: §7.2, SPEC-09 §2, §9, D-0734, D-0735, D-0737, D-0777.

#### Scenario: Listing run
- **WHEN** a listing schema's learning run finishes
- **THEN** `api_recipe.refused` is `listing: ...`

### Requirement: Recipe execution
When the active config has an `api_recipe`, `acquire` SHALL try it after adapters and before the page rungs: bind the
parameters from the page URL (fetching the HTML page first only when `requires_page_fetch`), send the request with
the recipe's headers through the JSON rung, and return `FetchResult(method='api')` with the JSON body. The `api`
collector reads the map into candidates `source_kind='api'`, locator `api:<config id>:<path>`; on a listing, `rows`
items are rows with row-relative paths. Values resolve in the `adapter` evidence bucket.
Refs: §7.2, §10, SPEC-09 §4.8, D-0599, D-0600.

#### Scenario: Served page
- **WHEN** a site's config has a validated recipe and a records-only scrape requests a page
- **THEN** the page is fetched over `httpx` with zero browser seconds

### Requirement: Recipe fallback
An `ok` recipe result SHALL be kept, and a 429 or 503 from the endpoint or the HTML page fetch SHALL be kept with no
fallback. Anything else, an unbindable parameter included, falls back to the configured method with the recipe's
attempts listed first; when the recipe's HTML page fetch already reached the page, that page is the result (not for
`method_hint=browser`). A page served through the fallback counts against the config's yield as usual.
Refs: SPEC-09 §4.10, D-0601, D-0730, D-1082.

#### Scenario: Endpoint 404
- **WHEN** the bound endpoint answers 404
- **THEN** the page is fetched the configured way and the result lists the `api` attempt first

### Requirement: Where a recipe serves
A recipe SHALL serve a page only when its record is all the caller reads: a `scrape` with formats `["records"]`,
`batch_scrape` and `extract` records tasks, and `crawl` pages at `max_depth`. Other pages are fetched themselves, and
`max_age` reuses an `api` capture only for a record-only scrape. A page the recipe served joins no drift window; the
recipe executor's field status is the config's, restricted to mapped fields. A config without a recipe MUST NOT run
on an `api` capture no adapter reads; that capture is extracted cold.
Refs: SPEC-09 §4.8, D-0728, D-0729, D-0732, D-0877.

#### Scenario: Markdown requested
- **WHEN** a scrape asks for `["records", "markdown"]`
- **THEN** the page itself is fetched, not the endpoint

### Requirement: Endpoint politeness
The endpoint host SHALL get a `site` row on first use. When the policy respects robots.txt, a disallowed or
unreachable robots.txt gives a `blocked` `api` attempt (`robots` / `robots_unreachable`) that sent nothing, and the
page is fetched instead. Requests go at the host's rate; the caller's admitted turn on the page's host goes to the
first request there, and another waits in place. Learning replays use the default `FetchPolicy` under the same rules.
Refs: SPEC-02 §4.6, SPEC-09 §4.8, D-0731, D-0739.

#### Scenario: Endpoint disallowed
- **WHEN** the endpoint host's robots.txt disallows the API path
- **THEN** no endpoint request is sent and the page is fetched the configured way

### Requirement: Pagination
For a listing recipe with `pagination` (`kind: param`, `name`, `start`, `step`, `rows`), every request, the first
included, SHALL set the parameter to `start + n·step` (same-name items replaced), fetch the HTML page at most once,
stop at a response whose `rows` select nothing (not yielded) or at the job limit, and yield a non-`ok` response last.
A recipe gets `pagination` only from an operator correction: discovery and role D produce none, and listings learn no
recipe (not built yet: rows and pagination discovery from listing samples; no service calls the paged executor).
Refs: §8.6, SPEC-09 §4.8, D-0603, D-0604, D-0612, D-0735.

#### Scenario: Offset pagination
- **WHEN** an offset endpoint returns rows for offsets 0 and 20 and none for 40
- **THEN** two responses are yielded and the third ends the listing

### Requirement: Export with a PHP hint
`platform_draft` SHALL carry the recipe as data and, exactly when the IR has a recipe, `api_recipe_php`: a PHP hint
rendered from `api_recipe.php.j2` by Jinja2 with `StrictUndefined`, autoescape and a `finalize` accepting only escaped
PHP literal, comment or integer values. `api_recipe_request($page_url, $params)` takes parameter values from the
caller, with a comment naming each binder. The hint is a rendering; nothing generated is executed.
Refs: §7.2 step 4, §12.2, §18, SPEC-09 §4.9, D-0625, D-0626, D-0627.

#### Scenario: Exported config
- **WHEN** a config with a recipe is exported as `platform_draft`
- **THEN** `api_recipe` and `api_recipe_php` are both present, and absent for a config without one
