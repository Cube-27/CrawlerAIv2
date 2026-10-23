# CrawlerAIv2 architecture v3: every delivery technology, HTTP by default, browser on block or by selection

**FROZEN 2026-10-19; rewritten in place 2026-10-21.** The owner's answers to the four open questions are in section
(g). Every PR in (f) has landed, and the text describes the system on `main`: where an owner decision changed a point
after the freeze, the point states the current rule and names its row in `owner-decisions.md`.
Inputs: the owner's research notes, kept outside the repo (the technology inventory; the verification of every
inventory claim, where every former [U] claim this design rests on is CONFIRMED unless marked **[UNCONFIRMED]**
below; the mapping notes 1–3), and the former acquisition plan, which this document supersedes.

Binding owner principles (2026-10-19) are restated only where a design point applies them. Nothing here relitigates
them. No site names, hostnames or URLs appear in this document.

Terms used throughout:
- **surface**: one (site, schema) pair, the unit at which anything is learned or set; a schema is a detail, listing,
  job or user schema (`schemas/types.py`).
- **source document**: one parsed unit a reader yields from a capture: a JSON value (JSON-LD block, state blob,
  captured call body, documented platform answer) or an HTML tree (the page, a fetched fragment, a frame). Every
  candidate carries a locator into exactly one source document (`collect/locator.py`).
- **field source**: the learned, per-surface answer to "where does field F live and what fetch does reading it
  need": `http` (in the HTML or its embedded documents), `call` (an HTTP request the page itself makes, replayed
  without the browser), or `browser` (exists only in the rendered DOM). Stored in the config IR (`config_ir/model.py`),
  the one recipe store; no new table.

---

## (a) Extraction model end to end

### a.1 Request

`POST /v1/scrape`, `/v1/batch/scrape`, `/v1/crawl`, `/v1/extract` (`services/scrape.py`, `batch.py`, `crawl.py`,
`extract.py`) take, as today: URLs, a schema (preset id, inline document, prompt draft or field list), `fetch`
(`method_hint auto|http|browser`, `proxy_pool`, caller `headers`/`cookies`, page `actions`, `wait_for`), `locale`,
`budget`, `min_confidence`, formats.

Changed member: `render_fields` (list of names) is **replaced** by `render`:

```
render: { mode: "off" | "locate" | "always", fields: [name, ...] }   # default {mode: "off"}
```

- `off`: HTTP; the browser is used only when HTTP is refused (a.3). Fields the HTTP page does not carry are
  `missing` with reason `no_candidates`; the job summary counts them per field and names `render.mode: locate` as
  the next step (never an XHR, selector or blob name: the user sees fields and outcomes, not internals).
- `locate`: the surface's **locate run** (a.6) is started (or refreshed) for the fields the HTTP extraction left
  missing on the submitted pages, or for `fields` when given. After it, every page is fetched by the plan the field
  sources dictate (a.3). This is the owner's "user selects an additional field": the user names fields, the system
  finds where they live.
- `always`: every page is rendered (the owner's "forces browser rendering"), and the locate run still happens, so the
  surface can fall back to HTTP later when `always` is turned off.

`render` is pinned at submit (INV-28) and also stored per surface (`site_surface.render_mode`, new column on
`extraction_config`'s key scope, see PR 5), so a batch submitted without it inherits the surface's mode.

### a.2 Fetch plan

Per page, before any request, from memory alone (no extraction, no collector pass):

1. **Adapter / API recipe** (unchanged): a measured platform adapter (`adapters/registry.py`) or the surface's learned
   API recipe serves the page as `api` (`acquire/rungs.py` adapter and recipe rungs; `config_ir/api_recipe`).
2. **Method**: `method_hint` if not `auto`; else `browser` if the block history says browser-first (`site_block`,
   `BROWSER_FIRST_BLOCKS=2`, `BLOCK_TTL` 15 min) or the surface's active config has any field source `browser`, or the
   surface's `render_mode` is `always`; else `http`.
3. **Companion calls** (HTTP, same rung, after the page, rate-limited by `politeness`): (i) the platform's documented
   product JSON when the HTTP page fingerprints a platform that has one (`adapters/platforms.product_json`; Shopify
   Ajax product, WooCommerce Store API; CONFIRMED), identity-checked (`acquire/identity.py`), joined as a network body
   marked `data_call` — **always**, not as a render fallback (decision 3 in (g)); (ii) every `call` field source of the active
   config (its `ApiRecipe`, bound from the page URL and page documents); (iii) eager HTML fragments the page declares
   (a.4, item 4).

`FetchPolicy.settle_on` (learned `content|data_call`) is deleted. The browser's ready condition (a.3) is fixed.

### a.3 Fetch: HTTP default, browser on block or by field source

HTTP rung (`acquire/http.py`, curl_cffi impersonating the browser rung's Chrome: its naming headers, read at startup, over the nearest curl_cffi Chrome profile) classifies the answer
structurally (`acquire/classify.py`, INV-24). In `auto`, the browser retry happens for exactly these outcomes, all of
which are "blocked" in the owner's sense (the server did not give the page to this client):

| HTTP outcome | Browser retry | Kept |
|---|---|---|
| `blocked` (403/407/429-after-pause/451 see below/503 interstitial) | yes, after `politeness.backoff` | browser `ok` only |
| `shell` that a challenge names (`acquire/challenge.py`, vendor signature or structural) | yes | browser `ok` only |
| `error` `network_error` / `timeout` | yes (never the same transport again) | browser `ok` only |
| `shell` with no challenge (a script-only app document) | yes, once per page (decision 2 in (g)) | browser `ok` only; else HTTP outcome `shell` |
| `ok` lacking the offer / rows / a requested field | **no** (deleted: `content/render_need.py`) | HTTP |
| `auth_wall`, `not_found`, redirect classes, `unsupported_media` | no | HTTP |

The `BROWSER_MIN_S=20` budget guard, the site-session handoff (browser cookies to HTTP, one way, challenge and
clearance cookies included: owner #76), block history and the 7-day re-check of `browser` contracts stay as specified.

Browser rung (`acquire/browser.py`, Patchright headless Google Chrome stable, INV-42..44, owner 2026-10-23): a persistent profile per site (owner
#50), one navigation, no request interception (owner #67 (12), removed: request routing sends `no-cache` headers no
user's browser sends), network capture, caller steps. The ready condition is fixed and source-driven
(`acquire/browser_wait.py`):

- ready when `DOMContentLoaded` has fired and (a) every `call` endpoint the surface's field sources name has answered,
  else (b) no data call has been in flight for `STEP_QUIET_S` (0.5 s); capped at `READY_MAX_S` (3.5 s) after
  `load`, whatever is still in flight; listings keep the item-area read. `_ready`'s "DOM states the offer"
  (`usable_content`) test is deleted; `usable_content` stays for classification.
- the rendered document is serialized **with open shadow roots**: `Element.getHTML({serializableShadowRoots: true,
  shadowRoots: <all open roots found by walking `shadowRoot`>})` run in Patchright's isolated world (allowed by
  INV-44: `evaluate`, no init script), producing declarative `<template shadowrootmode="open">` markup that the HTML
  reader flattens (a.4). Closed roots are not reachable without an init script (CONFIRMED) and stay out (b).
- captured bodies: today's JSON (any origin, sniffed, guard prefix stripped) **plus** `text/x-component` (RSC Flight)
  and same-site `text/html` fragment answers of `fetch`/`xhr` requests (Turbo Frames, htmx-style partials), each a
  `NetworkBody` with `resource_type` and `content_type`; caps unchanged (`JSON_BODIES_MAX`, `JSON_PAGE_MAX_BYTES`
  apply to all captured bodies together).
- locale: the job's locality (`#333`) sets the context's `locale` and `timezone_id` (Playwright context options the
  owner's P8 asks for; INV-44 is amended to name them as allowed, see (h)). No client hints or extra headers are set
  (owner #50 and INV-44); the user agent is the browser's own with `HeadlessChrome/` renamed `Chrome/` (owner #71,
  decision 1 in (g)).

### a.4 Sources: readers over the capture

`content/page.py::ParsedPage` is built once per capture and exposes **source documents** to the collectors. Readers
are pure functions of the capture (INV-26). Every reader names its standard or documented format (C2) and holds no
site string (C3). The full list with scope is in (b); the readers in scope now:

1. **HTML tree** of the page after three structural pre-passes, applied in this order to the raw document before any
   text or DOM collector runs:
   - **Declarative shadow DOM**: each `<template shadowrootmode="open"|"closed">` is replaced by its children under
     its host (HTML Standard: the template represents the host's shadow root; its content is the host's rendered
     content). Slotted light-DOM children stay where they are (also rendered). This also serves the rendered
     document of a.3, so one path reads shadow content over HTTP and browser alike (C8).
   - **Completed streaming boundaries** (React Fizz instruction set, CONFIRMED): for every inline script that calls
     `$RC("<boundary id>", "<content id>")`, the children of the element with the content id (a `hidden` element)
     replace the `<template id="<boundary id>">` marker; a `$RX` call leaves the fallback. Without this pass, HTTP-only
     reading drops every late Suspense segment as `hidden` text (`content/text.py::hidden`).
   - **Eager fragment inclusion**: a `<turbo-frame id src>` without `loading="lazy"` (Hotwire Turbo handbook: loads
     "as soon as the tag appears"; CONFIRMED) is a companion HTTP GET of `src` on the page's own site, whose answer's
     element with the same `id` replaces the frame's children. Lazy frames and htmx partials: (b).
   The `NOT_RENDERED` set and `hidden()` rules of `content/text.py` then apply unchanged.
2. **JSON-LD**, **microdata**, **RDFa Lite**, **Open Graph** (`collect/jsonld.py`, `microdata.py`, `og.py`): unchanged
   readers; the OG table gains the documented commerce product tags (d.6).
3. **Embedded state** (`content/state.py`, extended; collector `collect/js_state.py`), in script order:
   - `<script type="application/json">` (covers `__NEXT_DATA__`, Angular `ng-state`/`*-state`, Nuxt 3
     `__NUXT_DATA__`, SvelteKit `data-sveltekit-fetched`, Inertia `data-page` scripts; all CONFIRMED);
   - the value after `window.X =`, `var|let|const X =`, and, new, a bare statement-level `X =` (ECMAScript
     AssignmentExpression as an ExpressionStatement; SvelteKit's `__sveltekit_<hash> = {...}`, Remix's and React
     Router's `window.__remixContext`/`__reactRouterContext` are already `window.` forms); the value is read by the
     **JS literal reader** (next item), so JSON and JS object literals both parse;
   - object-literal arguments of statement-level `X.push({...})` calls (ECMAScript CallExpression with an
     ObjectLiteral argument; GA4 `dataLayer.push({event, ecommerce:{currency, value, items:[{item_id, price}]}})`
     and Meta Pixel `fbq('track','ViewContent',{value, currency, content_ids})` style calls read the same way: the
     object literal arguments of `X(...)`/`X.y(...)` calls whose arguments include an object literal). These are
     price **cross-check** documents: they carry a currency code and are admitted by the usual equality/visibility
     rule (`collect/admission.py`), never published alone;
   - `<script type="text/x-magento-init">` JSON (Adobe Commerce docs; CONFIRMED: `spConfig`/`optionPrices` live here);
   - the **RSC Flight** document (3b, CONFIRMED from React source): all `self.__next_f.push([1, "<chunk>"])` string
     chunks (tag 1) concatenated, tag 3 chunks base64-decoded, then the row grammar `<hex id>:<tag?><payload>` with
     length-prefixed `T` rows (`id:Tlen,text`) honoured; each JSON row is one document (`rsc:<row id>`); `$`-prefixed
     reference strings are kept as strings (no resolution needed for scalar extraction). A `text/x-component` network
     body is read by the same parser.
   **JS literal reader** (`content/js_literal.py`, new): a recursive-descent parser for the ECMAScript literal
   subset: object and array literals (quoted or identifier keys, trailing commas), string literals with escapes,
   numbers (incl. `-`, exponents, `0x`), `true|false|null|undefined|void 0`, nested parentheses, and the **devalue
   IIFE form** `(function(a,b,...){return <literal>}(<args>))` with parameter substitution (Nuxt 2's `window.__NUXT__=`
   and `devalue.uneval` output, CONFIRMED). Anything else (a function body, a call) ends the value: not state.
   **Decoders applied to parsed state**, by documented shape, not by name: (i) **devalue flat array** (Nuxt 3
   payload: an array whose values reference other indices; `["Reactive", i]`, `["Ref", i]`, `["ShallowRef", i]`,
   `["ShallowReactive", i]`, `["EmptyRef", json]`, `["EmptyShallowRef", json]`, `["Date", iso]`, `["Map", ...]`,
   `["Set", ...]`, `["NuxtError", ...]` revivers; applied when a top-level array's element 0 is an object whose every
   value is an in-range integer index) → dereferenced tree, cycle-guarded; (ii) **normalized-cache dereference**: an
   object whose values are objects and that contains `{"__ref": "<key>"}` members (Apollo InMemoryCache, CONFIRMED)
   is read with every `__ref` replaced by the referenced entry (depth-limited, cycle-guarded), roots `ROOT_QUERY`
   first. Both decoders are structural and run on any document with that shape.
4. **Attribute JSON** (`content/attr_json.py`, new): an attribute value that, HTML-unescaped, starts with `{` or `[`
   and parses as RFC 8259 JSON is a source document (`attr:<xpath>@<name>`). Covers Inertia's older `data-page`
   attribute, Livewire `wire:snapshot`, WooCommerce `data-product_variations` (inline variation prices when ≤ 30
   variations, CONFIRMED), Magento `data-mage-init`, Shopware's and others' data attributes. **Astro island props**
   (`<astro-island props>`; CONFIRMED serializer) are revived from their `[type, value]` tuples by shape (every
   value an array whose first element is an integer 0..11).
5. **Captured calls** (`collect/xhr.py`, `network_match.py`): unchanged admission for unknown bodies; `text/html`
   fragments are HTML trees (item 1 rules) and `text/x-component` bodies are RSC documents.
6. **Documented platform JSON** (`collect/platform_json.py`): unchanged; read as the platform documents it (Shopify
   integers are minor units ×100 for every currency, including zero-decimal ones, CONFIRMED [P60]; WooCommerce
   `currency_minor_unit`).
7. **DOM** (`collect/dom.py`, `dom_text.py`, item layer `collect/items/*`): unchanged passes, scoped by
   `product_apart`, over the pre-passed tree (so shadow and streamed content is now visible to them); price-role
   exclusions added in (d).
8. **Config steps** (`collect/config.py`): the active config's `FieldSteps` (xpath/css/jsonld/jsonpath/regex/attr)
   read directly, as today; a `jsonpath` step's `source` gains `attr`, `rsc` and `fragment:<n>` addresses (PR 5).
9. **Role C** (`llm/roles/c_extract.py`): after resolution, once per page, for the missing fields the llm spec's "When
   role C is asked" names (on a detail page optional ones included, owner #67 (3); in `active` mode only fields the
   config neither runs nor lists as absent; never an object or a list of objects, whose sub-fields one span cannot
   hold), and for a listing as the listings spec states; grounded (INV-12); never the default extractor;
   product-scoped (PR 2c). Unchanged place in the pipeline.

### a.5 Field resolution and output

Unchanged stages (`resolve/pipeline.py`, `preference.py`, `score.py`, `ownership.py`, `evidence.py`): screening
(invalid / ambiguous / not_owned / url_param), scoring (source weight × scope × agreement), Offer anchoring (INV-15),
derived values, calibration, provenance on every field (INV-22). Changes:

- **Price** resolution adopts #334's `_price_winner`: differing amounts publish only when a role explains them (the
  one visible DOM amount beats stale structured/meta/call amounts, flagged `disagree`; the shown variant's Offer beats
  other Offers); otherwise `conflict`. Amounts differing only in currency publish with currency unknown (C7). The
  always-publish tie rule of `main` is deleted.
- **Field status for unrendered pages**: `interaction_required` / `script_rendered` from `holds_state` is deleted with
  `render_need.py`. New: a field whose source is `browser` in the surface's config and whose fetch did not render
  (budget, `method_hint http`) is `interaction_required` with reason `render_bound`. Every other unfilled field keeps
  `missing` with its furthest-stage reason. The job summary (`services/job_outcomes.py`) reports per field the count
  of `missing/no_candidates` on HTTP-only pages and, when the surface's `render_mode` is `off`, the hint
  `render.mode: locate`.
- Output shape unchanged (owner #51 clean JSON): values, `currency` beside `price`, unpublished fields omitted;
  provenance, reasons and flags in the detailed record only.

### a.6 Locate run: user-selected fields become specific fetches

Triggered by `render.mode` `locate` or `always` on a surface, or by a user adding a field to a surface whose pages
have already been extracted (`services/schemas.update_schema` → relearn, already the behaviour for schema edits).
Runs as a `learn` job (`worker/handlers/learn.py`, existing job kind), one per surface, never on the request path:

1. **Sample**: up to `LOCATE_SAMPLES=3` of the surface's stored pages (most recent first, `config_ir/held_out.py`
   loaders), each fetched again **in the browser** with network capture, caller steps and the job locality; their
   HTTP captures are kept beside them. Each render is one browser use per surface, not per page.
2. **Values**: the normal collector pass and resolution run on each rendered capture (all sources of a.4, DOM and
   admitted call/state values included); role C fills what is still missing, grounded (learning may use the LLM; the
   runtime path never does by default). Fields the user named but nothing finds are reported `not_found_in_render`
   and the user is told in field terms.
3. **Induction over sources** (`config_ir/induction.py`, extended): for every published value, candidate steps are
   induced in each source document that contains it: a `jsonpath` step for a state/attribute/RSC/call document
   (`source: js_state|attr|rsc|xhr`), an `xpath` step for the DOM, an `ApiRecipe` for a call (endpoint shape from
   `network_match.endpoint_key`, binders from the page URL/path/query and page documents; GraphQL persisted queries
   replay with the captured `extensions.persistedQuery.sha256Hash` and bound `variables`, CONFIRMED; a call that needs
   a credential header is a recipe only when the header name is one the caller's request context supplies, by
   reference, PR 5).
4. **Validation** (`config_ir/validation.py`, both executors): each step must reproduce the published value on at
   least `MIN_LOCATE_HELD_OUT=2` other sample pages (the rule of #332's `finds.py`, generalized to every source), and
   a `call` recipe must reproduce it when replayed over HTTP without the browser.
5. **Cheapest validated source wins**, per field: `http` (HTML or embedded document of the HTTP capture) < `call`
   (HTTP + replayed request) < `browser` (DOM of the render only). The chosen step is written with
   `FieldSteps.needs: http|call|browser` into the surface's config (new version, `config_ir/activation.py`), origin
   `located`. Fields that validate nowhere stay out (they still go through the generic collectors at runtime).
6. **Runtime**: a.2 derives the fetch plan from the config's field needs. A surface whose every located field is
   `http` or `call` never opens the browser again unless blocked; one with a `browser` field renders every page, and
   the ready condition waits for its named endpoints. Drift (`config_ir/drift.py`) suspends a located field whose
   yield falls, which re-queues a locate run when `render_mode` is still `locate`/`always`.

Listings follow the same run: rows located in a call series become a listing recipe with pagination
(`network_match.row_series`, `api_recipe` pagination kinds), rows in state become `state_rows` paths, rows only in the
rendered DOM make the listing `browser`-bound (with the existing paging actions).

---

## (b) Source-adapter layer: every inventory technology

Scope marks: **now** = PRs in (f); **later** = designed here, built when a fresh batch shows the gap (C1), with the
reason; **report** = detected and named in page diagnostics and the job summary only, with the reason it is not read.

| # | Technology | Reader / mechanism | Scope | Reason / note |
|---|---|---|---|---|
| 1a | Server HTML | HTTP rung + HTML tree | now (exists) | — |
| 1b | Streamed HTML (Fizz boundaries, out-of-order fill) | full body read (exists) + `$RC` boundary completion pre-pass | now (PR 4) | CONFIRMED instruction set; without it late segments are `hidden` text |
| 1c | ESI | nothing to do | now (n/a) | assembled before the client (CONFIRMED); stale fragments are a price-disagreement case, (d) |
| 2a | JSON-LD (sent) | `collect/jsonld.py` | now (exists) | JS-injected JSON-LD appears only in a render: read there as the same source |
| 2b | Microdata | `collect/microdata.py` | now (exists) | `content=` vs visible disagreement handled by (d) visible-wins |
| 2c | RDFa Lite (schema.org) | `collect/microdata.py` | now (exists) | full RDFa 1.1 **later**: W3Techs' 40% is `property=` meta noise; no measured product use |
| 2d | Open Graph + commerce product tags | `collect/og.py` extended (d.6) | now (PR 6) | OGP basics; `product:*` are Pinterest/Meta-documented |
| 2e | Twitter cards | — | report | rarely carry a price; `twitter:data1/label1` have no fixed semantics |
| 2f | Microformats h-product | — | later | 0.4% of sites; class-based vocabulary, cheap to add if a batch shows it |
| 2g | Identifier fill | schema_org_map + DOM identifier spotting (exist); Shopify `sku`/`barcode` via documented JSON shape | now (PR 7) | adds `sku`, `barcode`→`gtin` members to the Shopify answer shape (documented) |
| 3a | Next.js Pages Router | `application/json` script (exists) | now (exists) | `/_next/data/...json` holds the same `pageProps` as `__NEXT_DATA__` (CONFIRMED): never fetched |
| 3b | Next.js App Router (RSC Flight) | RSC reader (a.4 item 3) + `text/x-component` capture | now (PR 3b) | CONFIRMED wire format from React source; version drift → parse failure is a diagnostic, never a wrong value |
| 3c | Nuxt 3 (`__NUXT_DATA__` devalue flat array) | devalue decoder | now (PR 3a) | CONFIRMED; external `_payload.json` (payload > ~10 KB) **later** via `call` field source (it is a page fetch the locate run captures) |
| 3c | Nuxt 2 (`window.__NUXT__=` devalue IIFE) | JS literal reader | now (PR 3a) | CONFIRMED |
| 3d | Remix / React Router 7 (`__remixContext`, `__reactRouterContext` JSON) | window assignment (exists) | now (exists) | single-fetch **turbo-stream** chunks (`streamController.enqueue`) **later**: library-documented format, no measured use yet; detected and reported now |
| 3d | SvelteKit (`kit.start(..., {data: <uneval>})`, fetched-response JSON scripts) | JSON scripts (exist) + bare assignment + JS literal reader for the `data:` literal inside the `start(` argument object | now (PR 3a) | CONFIRMED; the start call is an object-literal call argument, read by the same rule as `push(` |
| 3d | Angular TransferState (`<script id="ng-state" type="application/json">`) | JSON script (exists) | now (exists) | CONFIRMED |
| 3d | Gatsby `page-data.json` | — | later | external fetch of a documented path; locate run's `call` source covers it when a batch needs it; reported now |
| 3d | Astro islands (`props` tuples) | attribute JSON + tuple revival | now (PR 3c) | CONFIRMED serializer |
| 3d | Qwik (`qwik/json`, v2 `qwik/state`+`qwik/vnode`) | — | report | blob format undocumented; <0.1% |
| 3e | Apollo (`__APOLLO_STATE__` + `__ref`), Redux (`__PRELOADED_STATE__`), Pinia (`window.__pinia` devalue), urql (`__URQL_DATA__`) | window assignment (exists) + `__ref` dereference + JS literal reader | now (PR 3a) | all conventions, read by structure not name; Relay has no SSR global (CORRECTED) |
| 3f | Magento `text/x-magento-init` + `data-mage-init` | script JSON + attribute JSON | now (PR 3c) | CONFIRMED (Adobe docs) |
| 3f | Shopify `{{ product \| json }}` inline, `Shopify.currency.active` | JSON scripts/assignments (exist); currency via platform adapter (d.7) | now (PR 7) | minor units ×100 for every currency (CONFIRMED) applies only to documented endpoint bodies, never to generic state |
| 3f | WooCommerce `data-product_variations` | attribute JSON | now (PR 3c) | CONFIRMED (≤30 variations inline; above, admin-ajax → `call` source) |
| 3f | SFCC, VTEX, Shopware, Wix, Squarespace inline data | generic readers above | now (generic) | no documented inline product blob; Shopware's `window.currencyIsoCode` is read as a declared currency member (d.7) |
| new | Inertia (`data-page` script or attribute) | JSON script / attribute JSON | now (PR 3c) | CONFIRMED |
| new | Livewire (`wire:snapshot`) | attribute JSON | now (PR 3c) | CONFIRMED |
| new | Turbo Frames (`<turbo-frame src>`) | eager fragment inclusion; lazy frames via `call` source in locate | now (PR 4) / later | CONFIRMED |
| new | htmx partials (`hx-get` + `hx-trigger load/revealed`) | — | later | **[UNCONFIRMED]** in the verification pass; same mechanism as Turbo once confirmed |
| new | Phoenix LiveView / Blazor Server | dead render read as HTML (exists) | now (HTML) / report (socket) | initial HTML holds the price (CONFIRMED); live diffs need a socket client: never |
| new | Analytics payloads (GA4 `dataLayer.push`, Meta Pixel `ViewContent`) | push/call-argument literal reader | now (PR 3a) | cross-check only (admission by equality/visibility); carry ISO currency codes |
| 4a | XHR/fetch JSON, GraphQL incl. persisted queries | capture (exists) + locate `call` recipes | now (PR 5) | auth/CSRF headers: recipe only with a caller-supplied header by reference; otherwise `browser`-bound |
| 4a | gRPC-web | — | report | binary framing, protobuf schema unknown; `application/grpc-web*` content type reported |
| 4b | WebSocket / SSE | — | report | browser notes an opened socket/EventSource; fields are `browser`-bound; no protocol client |
| 4c | Service-worker cache | a persistent profile per site (owner #50), whose HTTP cache and service workers are deleted before each launch | now (exists) | first-visit fetch bypasses an existing cache (CONFIRMED); within one launch (idle up to 60 s) a later page may be served by the site's service worker |
| 5 | Declarative shadow DOM | DSD flatten pre-pass | now (PR 4) | CONFIRMED |
| 5 | Open imperative shadow roots | `getHTML` serialization in the render | now (PR 5) | CONFIRMED; 0.186% of page loads |
| 5 | Closed shadow roots | — | report | needs an `attachShadow` hook before page scripts (init script, INV-44); 0.059% of loads |
| 6 | iframes / third-party widgets | same-origin frame documents captured as fragments when a located field names one | later | no measured product-field use; frames' JSON calls are already captured |
| 7 | Interaction-gated content | listing paging actions (exist); caller `actions` steps (exist); variant selection via steps | now (exists) | no automatic clicking on detail pages (not in the principles) |
| 7 | Virtualized lists | listing actions (exist) | now (exists) | rows come from the call series when the DOM drops them |
| 8 | CSS generated content (`::before/::after`) | — | later | `getComputedStyle` read in the isolated world is allowed; no measured price use |
| 8 | Canvas/image/sprite text, font-glyph obfuscation | — | report | OCR and glyph mapping are not visible/extractable data; PUA code points in a price node → diagnostic `obfuscated_text` |
| 8 | SVG `<text>` | — | later | `svg` is in `NOT_RENDERED`; read `<text>` when a batch shows it |
| 9 | Wasm / Flutter CanvasKit / Blazor Wasm / Unity | data via located `call` sources (works now); UI | now (call) / report (DOM) | `application/wasm` resources and `flt-*`/`flutter-view` elements reported |
| 10 | AMP / m-dot / print alternates | — | report | alternates may carry other prices; the requested URL is the record |
| 10 | PDF and other non-HTML 200 | outcome `unsupported_media` | now (PR 4) | today a non-HTML 200 is `ok` |
| 11 | Geo / locale / A-B / personalization | egress country recorded, per-job locality drives Accept-Language and browser locale/timezone (#333 + PR 2a) | now | one URL ≠ one price: the record states its egress and locale |
| 12 | Consent walls | nothing over HTTP (content is in the HTML); overlays affect only browser steps (`click_intercepted`) | now (exists) | no CMP cookie setting, no clicking (principles) |
| 12 | Paywall / age gate / login | `auth_wall` (401) exists | report | structural gate detection is a heuristic; the caller's own cookies (exist) are the way through |
| 12 | 451 region block | `blocked` with challenge label `legal`, outcome `geo_blocked` | now (PR 4) | RFC 7725 |
| 12 | Anti-bot vendors | impersonated TLS/HTTP (exists), structural + signature labels (exist), block history (exists), residential pools as configured proxy pools (exist, untestable now), customer keys/cookies/proxies (exist) | now | the user agent is the browser's own with its headless token renamed (owner #71); no other header is set |
| 13 | Customer-supplied access | request context (exists); recipe credential **references** (PR 5); the request's `fetch.proxy_pool`, pinned per job (exists; no per-site pool) | now | product feeds / Merchant feeds **later** (a feed is another surface) |
| 13 | Sitemaps | `crawl/sitemaps.py` (exists) | now | — |

Platform data endpoints (verification §1b): only Shopify Ajax product and WooCommerce Store API are public and
documented, and stay the only platform companion calls. Magento GraphQL `products` (anonymous, cacheable; CONFIRMED by
implication) is **later** as a third documented companion call when a fresh batch has Magento pages lacking data.
Every other platform's API needs a key or token (Wix, Shopware, PrestaShop, Tiendanube, Shoptet, Salla, Shopline,
Square, SFCC, Cafe24 client id, BigCommerce origin-scoped tokens) → customer-supplied credentials by reference, or the
generic path. Undocumented endpoints (Shopify `/products.json`, Squarespace commerce `?format=json` shapes, Shoplazza
currency) are never relied on.

---

## (c) User-added fields and forced render: locating and fetching specifically

(c) is a.6 in operational terms; this section fixes the contracts.

**What the user does**: adds a field to the surface's schema (name, type, description, optional `schema_org` path;
`PUT /v1/schemas/{id}`), or sets `render.mode`. Nothing else. No XHR, selector, blob or source name is ever shown or
asked for; outcomes speak in field names and the statuses of a.5.

**What the system stores** (config IR, `config_ir/model.py`):

```
FieldSteps:
  steps: [...]                      # unchanged step grammar
  needs: "http" | "call" | "browser"   # new; "http" when absent (older documents)
  call: <recipe id>                  # new, for needs=call: the ApiRecipe in ExtractionConfigIR.recipes
ExtractionConfigIR.recipes: {id: ApiRecipe}   # new; today one recipe per config, now one per endpoint
ApiRecipe.headers: [{name, value} | {name, from_context: true}]   # new: a caller-context header by reference
Provenance.origin: + "located"
```

`JsonPathStep.source`: `jsonld | js_state | attr | rsc | xhr | api` (was four). Locators follow (`attr:<xpath>@<name>`,
`rsc:<row>:<path>`, `fragment:<n>:<xpath>`, `xhr:<n>:<path>` as today).

**How a field is identified in the render**: by its published value (resolution on the rendered capture, role C
grounded for the rest), then induction of a step in every source document containing that value, then validation on
≥2 other pages (a.6 steps 2–4). The DOM step for a `browser` field is the induced XPath on the pre-passed rendered
tree (shadow roots flattened), so web-component storefronts work.

**How it is fetched afterwards**: `needs` of all fields → page fetch plan (a.2). `call` recipes run on the HTTP rung
with the impersonated client, Fetch-Metadata headers as a page's own `fetch()` would send (`acquire/api.py`,
exists), bound from the page URL and the HTTP page's documents; a recipe whose binding fails on a page falls back to
the generic path for that field on that page (no browser).

**Forced render (`always`)**: every page renders; the locate run still runs so the surface can later drop to HTTP.

**Deleted**: `render_fields` request member (API, OpenAPI, Python and TypeScript SDK models, frontend field picker),
`RenderNeed`, `render_need()`, `_lacks`, `_render_lacks`, `forced`, `interaction_required/script_rendered`.

---

## (d) Price and currency

Principles applied: a price is a field; roles are fields when the schema defines them; visible wins over structured
when they disagree with no explanation, flagged; an unclear currency never drops a price; nothing is guessed when
prices disagree.

### d.1 Price roles as schema fields

`schema_org` path grammar (`collect/schema_org_map.py::parse_paths`) gains a **filter predicate** on a step:
`Type.prop{name=Value}.prop`, matching a node whose `name` property (as IRI or term) equals `Value`; `{name}` alone
requires presence, `{!name}` absence. The `commerce_detail` preset changes only its `price` path (the predicates
below); every other row is a **user-added field** (decision 4 in (g)): the user adds it to the surface's schema, the
schemas spec documents the row's `schema_org` path as the recommended mapping, and the DOM evidence column is the
structural cue the collectors give that field once the schema holds it.

| Field | Type | `schema_org` | DOM / text evidence | In preset |
|---|---|---|---|---|
| `price` (active) | money | `Offer.price{!priceType}{!validForMemberTier}+priceCurrency \| Offer.priceSpecification{!priceType}{!validForMemberTier}.price+priceCurrency` | the emphasized current amount: not struck, not per-unit, not per-period, not a range bound (d.3) | yes, required (as today) |
| `list_price` | money | `Offer.priceSpecification{priceType=StrikethroughPrice}.price+priceCurrency \| Offer.priceSpecification{priceType=ListPrice}.price+priceCurrency` | struck text (`<s>`, `<del>`, `<strike>`, inline `text-decoration` containing `line-through`) | no (user-added) |
| `unit_price` | money | `Offer.priceSpecification{referenceQuantity}.price+priceCurrency` (UnitPriceSpecification) | an amount followed by a CLDR per-unit pattern and a CLDR unit (`€25/kg`, `$0.50 per 100 ml`) | no (user-added) |
| `unit_price_reference` | text | `Offer.priceSpecification{referenceQuantity}.referenceQuantity` | the unit text beside `unit_price` | no (user-added) |
| `member_price` | money | `Offer.priceSpecification{validForMemberTier}.price+priceCurrency` | none generic (label-based via the field's labels) | no (user-added) |
| `price_range` | range | `AggregateOffer.lowPrice+highPrice+priceCurrency` | two amounts joined by a range mark (exists in `normalize/range.py`) | no (user-added) |
| `seller` | text | `Offer.seller.name \| Offer.offeredBy.name` | none | no (user-added) |

No preset record changes shape (decision 4). Everything else in Table B and the
verification's missed roles is a **user-added field** read by labels, role C grounding and the locate run, with no
preset entry and no generic rule: instalment/BNPL monthly, subscription cost, tax-inclusive/exclusive variants,
shipping, coupon price, bundle/multipack, MOQ-tier prices (`UnitPriceSpecification.eligibleQuantity` is readable by the
path grammar when a user maps it), EU 30-day prior price (no schema.org property; label-based), RRP/UVP vs own prior
price, deposits and eco-fees, core charges, auction bids. The platform must extract any user-defined field; it does.

### d.2 Active price: what is excluded from `price` candidates

Structural rules only (C2/C4), applied in the DOM collectors and in admission for the `price` field:

1. **Struck**: text inside `s`, `del`, `strike` (HTML Standard), or an element whose inline `style` has
   `text-decoration` / `text-decoration-line` containing `line-through` (CSS Text Decoration 3). Already the rule
   for tags; the inline style is new. Class-based strikethrough (stylesheet) is read in forced renders as a computed
   style only **later** (b, 8).
2. **Per-unit**: an amount immediately followed (whitespace aside) by the locale's CLDR `perUnitPattern` separator
   (`/`, "per", "pro", locale-sourced from CLDR unit patterns, not a word list) and a CLDR unit name/symbol
   (mass, volume, length, area, count units) → `unit_price` evidence, excluded from `price`.
3. **Per-period**: amount followed by the same separator and a CLDR duration unit (`month`, `mo`, `yr`, `week`,
   locale forms) or preceded by a CLDR count-times pattern (`4 × $25`, `4x`) → excluded from `price` (instalment or
   subscription; a user field may claim it).
4. **Range bound**: a DOM amount equal to a stated `AggregateOffer.lowPrice` or `highPrice` whose other bound differs
   is the range's bound, excluded from `price`; `price_range` publishes. "From X" text without AggregateOffer stays a
   `price` candidate: no phrase list is allowed, and a lone visible amount is what the page states (the record is
   flagged `offers_disagree`/`conflict` only when another amount disagrees, per #334).
5. **Ratio**: a number with a CLDR percent sign is never an amount (exists).
6. **Other products**: `product_apart` cards, Review/related items (exists).
7. **Minor-unit sanity**: a text reading whose decimal digits exceed the resolved currency's ISO 4217 minor unit is
   dropped (`$10.999` is not USD 10.999; `¥1,234` is JPY 1234, not 1.234) — in `normalize/money.py` via Babel
   `get_currency_precision` (d.7).

### d.3 When sources disagree

Implemented by #334 (`resolve/preference.py::_price_winner`), kept as the rule:
- contenders = groups with different amounts (same amount, different currency: not rivals; currency unknown, C7);
- exactly one contender is an independent visible DOM amount → it publishes, flagged `disagree` (stale structured
  data, `content=` attributes, OG and call values lose; this is the owner's "visible wins, flagged");
- else the shown variant's Offer (INV-38) when every other amount is another Offer's (other variant or seller) →
  publishes, flagged `offers_disagree`;
- else `conflict` (`disagree` or `offers_disagree`), nothing guessed; `offer_split` when only a non-anchor Offer
  states the field.
Mapping-3's objection ("$25/mo" as the lone DOM amount) is closed by d.2 rules 2–3: such text is never a `price`
candidate. Multi-seller buy box: Offers with different `seller` are "other Offers" in the rule above; `seller` as a
field (d.1) lets a user keep the shown seller.

### d.4 Mapping-3 bugs and their fixes

| Bug | Fix | Where |
|---|---|---|
| `Offer.price` only; `priceSpecification`, `priceType`, `validForMemberTier` never read | path predicates (d.1); preset paths; UnitPriceSpecification read as a node of the Offer | `schema_org_map.py`, presets |
| strikethrough tag-only; no CSS line-through | inline `style` line-through; `strike` tag | `collect/dom.py` `_STRUCK` → `struck(node)` |
| `€25/kg` reads as price; `$25/mo` → 25 | d.2 rules 2–3 with CLDR per-unit/duration data (Babel `units`) | `collect/dom.py`, `collect/items/spot`, `normalize/money.py::_text` returns `Invalid("per_unit")`/`Invalid("per_period")` for the `price` role when the suffix is present, `Ok` for `unit_price` |
| `lowPrice/highPrice` never read; "From $80" → 80 | `price_range` field + rule 4 | preset, `preference.py` |
| stale SD outvotes DOM | #334 | `preference.py` |
| OG `og:price:amount`, `product:sale_price:amount` not read | d.6 | `collect/og.py` |
| ar-SA `ر.س` → PKR | CLDR symbol table built with and without trailing full stop **and** without bidi controls (U+200E/U+200F/U+061C); longest-match then finds the 3-letter form as SAR; a sign that still maps to several currencies narrows by page/locale/URL as today | `normalize/money.py::_symbol_currencies`, `_sign_forms` |
| Shopify `.js` assumes cents | correct as documented (×100 for every currency, [P60]); currency from `Shopify.currency.active` (d.7) | `adapters/platforms.py` |
| de-CH ASCII `'` fails | group symbol set per locale = CLDR symbol ∪ its ASCII/compatibility fallbacks (U+2019↔U+0027, U+202F/U+00A0↔U+0020) | `normalize/numbers.py::_convention` |
| Arabic/Persian separators and digits missing | digits mapped through `unicodedata.decimal`; CLDR `arab`/`arabext` numbering-system symbols (U+066B decimal, U+066C group) included in the conventions | `normalize/numbers.py` |
| minor units unused | d.2 rule 7 | `normalize/money.py` |
| no page-level separator consistency | #333: readings narrowed by the page's declared locales when ambiguous; plus: a page whose unambiguous amounts all use one convention (JSON-LD `price` decimals, other text amounts) narrows the remaining ambiguous ones to it | `normalize/numbers.py::readings` (+ `Context.page_convention` from `collect/currencies.py`'s sibling pass) |

### d.5 Currency order (unchanged, #333 merged)

(1) code or unambiguous sign with the amount, or the value's own `priceCurrency`; (2) page structured `priceCurrency`;
(3) page-level declaration (OG currency tags, state members `currency|currencyCode|activeCurrency`, plus
`Shopify.currency.active` and `window.currencyIsoCode` as documented platform members read by the platform signature,
d.7); (4) CLDR locales the page declares (language-only tags settle nothing shared, #333); (5) URL territory (D-1782);
(6) null, basis `unknown`, flagged. A grounded amount always publishes.

### d.6 Open Graph commerce tags

`collect/og.py` table gains: `product:price:amount`+`product:price:currency` (exists) and `og:price:amount`+
`og:price:currency` (the historic OGP product type) → `price`; `product:sale_price:amount`+`:currency` → `price` when
present (the sale price is the price paid; the `product:price:amount` then is `list_price` evidence);
`product:original_price:amount` → `list_price`; `product:retailer_item_id` → `sku`; `product:brand` → `brand`;
`product:condition` → `condition`; `product:availability` / `og:availability` → `availability` (enum via the existing
first-clause rule). Site-default blocks are skipped as today.

### d.7 Platform members for currency

`adapters/platforms.py` signatures gain `currency_members`: Shopify `Shopify.currency.active` (Liquid docs:
presentment currency), Shopware `window.currencyIsoCode` (meta template, CONFIRMED). Read only when the signature
matched; declared at level (3). Shopify answer shape gains `variants[].sku`, `variants[].barcode` (→ `gtin`),
`variants[].price` (minor units ×100), `variants[].available`, `variants[].title`, so the `variants` row-mapped field
is filled from the documented body when the page's own variants are not stated.

---

## (e) What is deleted

Each item is removed in the PR that supersedes it (same change, per CLAUDE.md). Tests that only exercised the deleted
code are deleted with it; no shim, alias or compatibility branch remains.

| Deleted | Superseded by | PR |
|---|---|---|
| `content/render_need.py` (whole file: `offer_shown`, `holds_state`, `STATE_MIN_VALUES`, `_heading_and_price`, `listing_needs_render`, `lost_items`, `listed`) and `tests/unit/test_listing_render.py` | block-only escalation (a.3), locate run (a.6) | 2a |
| `services/scrape_steps.RenderNeed`, `render_need()`, `_lacks`, `_render_lacks`, `_stated`, `forced`; `services/scrape._render_need`; `worker/handlers/steps.py` check binding; `Records.render_fields` | fetch plan from field sources | 2a |
| `acquire/rungs._instead_of_render`, `_data_called` as render fallback, `_browser_may_help`'s `needs_render` branch, `_Retry` paths for lacking pages | `_joined` companion call always; retry on block classes only | 2a |
| `acquire/memory`: `needs_render`, `needs_xhr`, `needs_traversal`, `settle_on`, `Coverage` learning from lacking renders, `lesson` for `forced`; `db/models.SettleOn`; `site_contract` columns `settle_on`, `needs_render`, `needs_xhr`, `needs_traversal` (edit `0001_baseline`) | contract = method + handoff + platform; block history unchanged | 2a |
| `acquire/browser._ready`'s `usable_content` branch and `FetchPolicy.settle_on` | fixed ready condition with located endpoints | 2a / 5 |
| `resolve/page_state.render_could_show`, `SCRIPT_RENDERED`; `resolve/types.FieldStatus` reason `script_rendered` | `interaction_required/render_bound` from field sources | 2b |
| `render_fields` in `services/scrape.py`, `batch.py`, `crawl.py`, `schedules._BATCH_MEMBERS`, `worker/handlers/steps._RENDER_FIELDS`, `RENDER_FIELDS_DESCRIPTION`, OpenAPI, `sdk/python`, `sdk/typescript`, `frontend/src/api/field.ts` picker | `render` member | 2b |
| `resolve/preference._price` always-publish-best tie rule (main) | #334 `_price_winner` | merge #334 |
| `config_ir/finds.py` as a role-C-only write-back (#332 closed unmerged, `pull/332/head`) | `config_ir/locate.py` for every source | 2c / 5 |
| `config_ir/api_recipe/model.CREDENTIAL_FIELDS` refusal as absolute | credential **references** to caller-context headers | 5 |
| `acquire/classify` treating a non-HTML 200 as `ok` | `unsupported_media` | 4 |
| Owner-decision rows #49 (render on no offer data) and #54 (render on no rows) as operative rules | the 2026-10-19 framework; rows marked superseded in `owner-decisions.md` | 1 |
| the former acquisition plan's P3 "absent signals → browser", P2 "target wait condition", P4 "needs" (owner's notes) | this document | 1 (notes archived) |
| `openspec/backlog.md` phases 1–5 text; `OPEN_QUESTIONS.md` row 10 (proxy pools) as open | (h) | 1 |

Deleted by the handover plan (2026-10-21), each in the PR named:

| Deleted | Superseded by | PR |
|---|---|---|
| conditional GET (`recurring/conditional.py`, `Validators`, the HTTP rung's conditional form), standing-record reuse (`standing_record`, `standing_listing`, `stand_for_listing`, `stored_validators`, `record_fetch`), the `unchanged` task outcome, `url_state` columns `etag`, `last_modified`, `standing_task_id` | every records task fetches and extracts its page whole (jobs "Fresh extraction"; owner #40, #60 as superseded) | #376 |
| the browser rung's request routing and blocking, its lists and the per-site opt-out `load_all_resources`; the browser's user agent and client hints on a site session's HTTP and JSON requests | no request interception (owner #67 (12) removed); the HTTP rungs keep their own identity | #393 |
| the `url_state` content fingerprint (`recurring/state.py`, `recurring/simhash.py`, its columns), `FetchPolicy.capture_network_json`, the `CRAWLERAI_ROLE` setting, the site row's `proxy_pool` and `crawl_delay_ms`, classify helpers without a caller | nothing read them; a job's pool is the request's `fetch.proxy_pool` | D2 #396 |
| the in-repo golden-set machinery: the eval package, router, CLI commands and labeling screens, `eval_page` and `eval_run`, `resolve/calibrate.py`, the eval UI setting, the `c_prefill` prompt kind | the e2e run over the eval set kept outside the repo (owner #79); fitted files stay frozen | D1 #397 |
| test-only code under `src/` (the fake LLM provider, the schema subset checker, `extract_task`), the agent-tooling script tests | `tests/support/`; the scripts stay | D3 #398 |
| each module's own document and item URL comparisons, `row_url_fields` | `normalize/url_key.py` (`document_key`, `item_key`), the one item-URL predicate `is_item_url` | B1 #399 |
| a worker task's one transaction from fetch to commit | site memory in short transactions of its own; the fetch before the task transaction | A3 #400 |
| each normalizer's own page-locale reads (`context_languages`, money's page languages and territories, location's country table) | `normalize/locales.py` | B2 #401 |
| a variant row's visible amount (`RowField.shown`, `shown_values`), four copies of the visible-amount test, two repeat helpers | a row keeps its stated amount (owner #78); `is_visible_amount`; `content/repeats.py` | B3 #402 |
| the challenge-cookie filter (`challenge_cookie`, `cookie_value_markers`), the per-fetch decrypt of the stored state, the seeding of kept profiles | one cookie rule (owner #76) | A1 #403 |
| the text helpers' copies (cut, summary, whitespace, word folding) | `normalize/strings.py` | B4 #404 |
| the listing rung's own browser per call, the session-wide context recycle, each rung's own render finish | listing renders through the shared browser; one render finish | A2 #405 |
| the image policy's copies across URL, preference and supersede code | `normalize/images.py` | B5 #408 |
| the scrape's and the worker's duplicate cache reads, failure mappings and record steps; `services/scrape_steps.py` | `services/page_run.py`; `scrape_request.py`, `page_store.py`, `page_formats.py` | A4 #409 |
| repeated body decodes (`decode_body`) | the capture bundle's decoded text, one platform fingerprint per fetch | A5 #410 |
| the per-file DB test stand-ins and cleanups | `tests/db/support.py`, one engine per worker | T1 #413 |
| the SDK digest check (`tools/sdk_digest.py`, `sdk/openapi.sha256`) | the `sdk` job regenerates both SDKs and compares | T3 #419 |

Kept deliberately: block history and browser-first-after-2-blocks (it is "browser when blocked" with memory),
`BROWSER_MIN_S`, site-session handoff, platform fingerprints, identity check, admission rule, item layer, calibration,
`source_precedence.yaml`, verify-money and verify-worker-queue skills.

---

## (f) Ordered PR list

Rules for every PR: small, one concern; spec delta in the same PR; superseded code deleted in the same PR; unit tests
only where the acceptance check below says so, from fixtures written from the documented format (no page copied from
any site, C3/C9); CI only; no live fetches, no browser in tests except where an existing browser test file is
extended; property tests via Hypothesis where the check is an invariant. Sizes are net lines of code excluding specs
and generated SDK files.

Every PR below has landed on `main`; the files each names are those it changed, and later refactors moved some of them
((e), second table). Before PR 1: #334 price accuracy (d.3) and #333 locale normalize (declared-locale readings,
`in_language`, egress country, per-job locality). Browser `locale`/`timezone_id` from the job locality is not in #333
and lands in PR 2a. #332 is closed unmerged; PR 2c re-lands its kept parts from `git fetch origin pull/332/head`.

**PR 1 — docs freeze (docs only, ~0 LOC)**
Scope: add this document as `openspec/design/architecture-v3.md`; move the whole documents (h) marks *archived*
(`openspec/backlog.md`, `openspec/OPEN_QUESTIONS.md`) to `openspec/archive/` with a README saying they are
superseded by this document on 2026-10-19; update the pointers in `README.md`, `CONTRIBUTING.md`, `CLAUDE.md` and
`openspec/project.md`; append owner-decision rows #70–#74 (the 2026-10-19 framework and decisions 1–4) and mark #49
and #54 superseded; note decision 1 in `overview.md` §22's anti-bot row. Spec sections stay as they are and are
rewritten by the PR that implements each change (spec delta in the same PR, the repo's rule); until then this
document governs where a spec differs. Acceptance: CI docs checks (`tools/decision_ids.py`, site-literal scan) pass;
no tracked file links to the archived documents' old paths.

**PR 2a — acquisition: browser on block only; fixed ready; companion call always (~−450 / +160 LOC)**
Files: delete `content/render_need.py`, `tests/unit/test_listing_render.py`; `acquire/rungs.py` (retry table a.3,
`_joined` always for fingerprinted platforms, drop `_instead_of_render`/`_data_called`), `acquire/memory.py` (drop
`needs_*`, `settle_on`, `lesson(forced)`), `acquire/browser.py` (`_ready` fixed; context `locale`/`timezone_id` from
`FetchPolicy.locale_hint`), `acquire/types.py` (drop `settle_on`), `db/models.py` + `0001_baseline` (`site_contract`
columns), `services/scrape_steps.py` (drop `RenderNeed` et al.), `services/scrape.py`, `worker/handlers/steps.py`,
`tests/unit/test_rungs.py`, `test_domain_memory.py`, `test_browser_setup.py` (locale option allowed).
Acceptance (unit, fixtures): (i) rungs: for each HTTP block class in the a.3 table, the stubbed browser is called iff
the table says so (table-driven test over `BlockClass`); an `ok` HTTP page with no JSON-LD/OG/price never calls the
browser; (ii) memory: a browser `ok` after `blocked` with handoff teaches `http`+`handoff`; no contract column but
method/engine/handoff/coverage exists (model test); (iii) browser setup source scan: no `user_agent`, no
`extra_http_headers`, no `add_init_script`; `locale`/`timezone_id` allowed.

**PR 2b — API: `render` member, `render_bound` status, summary hints (~+120 / −140 LOC)**
Files: `services/scrape.py`, `batch.py`, `crawl.py`, `schedules.py`, `services/scrape_steps.py` (`RENDER_DESCRIPTION`),
`resolve/page_state.py` (drop `render_could_show`; add `render_bound(fields, config, rendered)`), `resolve/types.py`,
`services/job_outcomes.py` (per-field `missing/no_candidates` counts + hint), OpenAPI regen, `sdk/python`,
`sdk/typescript`, `frontend/src/api/field.ts` (+ the one picker component), rest-api/jobs/resolution spec deltas.
Acceptance: schema test that `render_fields` is rejected (422) and `render` validates `{mode, fields}`; unit: a
config with a `browser` field and an unrendered capture gives `interaction_required/render_bound`; an HTTP page
without a config leaves `missing/no_candidates`; SDK/OpenAPI diff check in CI.

**PR 2c — role C product scope and the `unverified` reason (~+180 / −40 LOC; from `pull/332/head`, #332 closed)**
Files: `llm/marked.py` (`scoped`: evidence text limited to the product's own blocks, `other_item_paths` excluded),
`llm/roles/c_extract.py` (per-page batching of all missing fields in one call; `unverified` for a claim whose value
is not found in the evidence), `resolve/pipeline.py` (`UNVERIFIED` reason; `GapRequest.elsewhere` dropped), llm and
resolution spec deltas, `tests/unit/test_c_extract.py` (the branch's tests for scope and `unverified`). **Not**
re-landed from the branch: `config_ir/finds.py`, `activation.store_find`, the `role_c` provenance origin and the
write-back call in `progressive.py` (PR 5 lands the generalized locate run instead).
Acceptance: fixture page with a product block and two "other item" cards: the role C evidence text holds the product
block's text only; a claim quoting text absent from the evidence is `unverified`, never published; one role C call
per page for N missing fields (stub client call count = 1); `grep -r "finds" backend/src/crawlerai/config_ir` empty.

**PR 3a — embedded state readers: JS literal, bare assignment, call arguments, devalue, `__ref` (~+420 LOC)**
Files: new `content/js_literal.py` (parser), new `content/state_decoders.py` (devalue flat array, Astro tuples hook,
`__ref` dereference), `content/state.py` (bare assignment, `push`/call-argument literals, use the JS literal reader),
`collect/js_state.py` (documents from decoders), `collect/currencies.py` (currency members found in decoded documents),
extraction spec delta, `tests/unit/test_js_state_collector.py` extended, new `tests/property/test_js_literal.py`.
Acceptance: fixtures written from the documented formats in the verification file: (i) Nuxt 2 `window.__NUXT__=`
devalue IIFE with parameter substitution → the expected tree; (ii) Nuxt 3 flat array with `Reactive`/`Ref`/`Date`
revivers → dereferenced tree; (iii) Apollo state with `ROOT_QUERY` and `__ref` → dereferenced; (iv) Redux/Pinia
`JSON.stringify` output with `<` escapes; (v) GA4 `dataLayer.push({...ecommerce...})` and `fbq(...)` object
arguments become documents; (vi) SvelteKit `kit.start(app, el, {data: [...uneval...]})`; (vii) property: for random
JSON values `v`, `read(json.dumps(v)) == v` and `read(js_uneval_like(v)) == v` for a generator emitting unquoted keys,
single quotes, trailing commas, `undefined` leaves; (viii) function bodies and calls inside a value end the read with
no document and no exception.

**PR 3b — RSC Flight reader and `text/x-component` capture (~+220 LOC)**
Files: new `content/rsc.py`, `content/state.py` (collect `self.__next_f.push` chunks per document), `acquire/browser.py`
(capture `text/x-component` bodies; `_json_essence` → `_data_essence`), `storage/capture_bundle.py` (no model change;
`content_type` already stored), `collect/xhr.py` (route x-component bodies to the RSC reader), acquisition and
extraction spec deltas, `tests/unit/test_rsc.py`.
Acceptance: fixture built from the documented grammar: tag-1 UTF-8 chunks split mid-row, one tag-3 base64 chunk, a
`T` length-prefixed text row containing newlines, JSON rows with `$L`/`$@` references → the expected list of
`(row id, value)`; a malformed row yields a diagnostic and the other rows; property: random JSON rows encoded with the
grammar round-trip.

**PR 3c — attribute JSON, Magento init scripts, Astro props, Inertia/Livewire/Woo variations (~+140 LOC)**
Files: new `content/attr_json.py`, `content/state.py` (`text/x-magento-init` type), `content/page.py` (expose attribute
documents), `collect/js_state.py` (read them), `collect/locator.py` (`attr:` scheme), `config_ir/model.py`
(`JsonSource` + `attr`), extraction spec delta, `tests/unit/test_attr_json.py`.
Acceptance: fixtures from the docs: Inertia `data-page` attribute (HTML-escaped JSON), Livewire `wire:snapshot`,
WooCommerce `data-product_variations` with two variations (`display_price`, `display_regular_price`, `attributes`),
Magento `data-mage-init` and `x-magento-init` with `spConfig.optionPrices`, Astro `props` tuples → the expected
documents; an attribute starting with `{` that is not JSON yields nothing and no exception; locators read back.

**PR 4 — HTML structure pre-passes and outcomes (~+260 LOC)**
Files: `content/page.py` (DSD flatten, Fizz boundary completion, fragment inclusion hook), new `content/fragments.py`
(turbo-frame eager fetch planning: returns the `src` list; the fetch happens in `acquire/rungs.py` as a companion
call, same-site only, SSRF-guarded, rate-limited), `acquire/classify.py` (`unsupported_media` for non-HTML 2xx;
451 → `blocked` + label `legal`), `acquire/challenge.py` (`legal`), `services/scrape_steps.py` (`geo_blocked`,
`unsupported_media` outcomes), `db/models.py` outcome literals, `collect/dom_text.py` and `config_ir/listing_induction.py`
(remove `template` from the dropped set now that DSD is flattened before them), specs (acquisition, extraction, jobs).
Acceptance: fixtures: (i) a host with `<template shadowrootmode="open">` → text and DOM collectors see the shadow
text and a candidate's XPath addresses the flattened node; (ii) a Fizz document with `<div hidden id="S:1">`, a
`<template id="B:1">` and `$RC("B:1","S:1")` → the late segment is visible text; `$RX` leaves the fallback;
(iii) `<turbo-frame id="x" src="/f">` planned for fetch, `loading="lazy"` not; the fetched fragment's `#x` children
replace the frame's; (iv) `application/pdf` 200 → `unsupported_media`; 451 → `blocked`, label `legal`, outcome
`geo_blocked`.

**PR 5 — locate run and field sources (~+520 / −160 LOC)**
Files: `config_ir/model.py` (`FieldSteps.needs`, `.call`, `recipes`, `Provenance.origin located`, `ApiRecipe.headers`
`from_context`), `config_ir/api_recipe/model.py` (credential by reference), `config_ir/api_recipe/execute.py` (header
from `RequestContext`), new `config_ir/locate.py` (a.6 steps 2–5; absorbs #332's finds logic), `config_ir/induction.py`
(induce in every source document; `attr`/`rsc`/`xhr` jsonpath steps), `config_ir/validation.py` (replay a `call`
over HTTP in validation), `worker/handlers/learn.py` (render samples when `render_mode` is `locate|always`),
`services/schemas.py` (field add → locate when the surface's mode allows), `db/models.py` + baseline
(`site_surface.render_mode` on the config scope), `acquire/rungs.py` (fetch plan from `needs`; `call` recipes as
companion calls), `acquire/browser.py` (`getHTML` open-shadow serialization; ready waits for named endpoints),
learning-configs/adapters/acquisition spec deltas, `tests/unit/test_locate.py`, `tests/unit/test_api_recipe_model.py`.
Acceptance (fixtures, both executors): (i) three synthetic rendered captures (HTML + state + one captured call body
carrying a field value) → induction yields steps in state, call and DOM; validation on the other two keeps all
three; the chosen `needs` is `http` (state wins); remove the value from the state fixtures → `call` wins and the
recipe replays against a stub; remove it from the call → `browser`; (ii) a recipe needing `authorization` is
produced only when the request context names that header, and the stored recipe holds no value; (iii) fetch plan
test: a config with all `http`/`call` fields plans `http` + N companion calls; one `browser` field plans `browser`;
(iv) `getHTML` call appears in the browser source scan as an `evaluate` in the isolated world and nothing else.

**PR 6 — price roles, path predicates, active-price exclusions, OG commerce tags (~+330 LOC)**
Files: `collect/schema_org_map.py` (`{name=Value}`, `{name}`, `{!name}` predicates in `parse_paths`/`select`),
`schemas/presets/commerce_detail.json` (`price` path with the d.1 predicates only; no new fields, decision 4),
`schemas/registry.sync_presets` (digest change, in place), schemas spec (the recommended `schema_org` paths of the
d.1 user-added price-role fields), `collect/dom.py` (`struck()` with inline style; per-unit/per-period suffix exclusion using
Babel unit data via a new `normalize/units.py`; range-bound exclusion), `collect/items/align.py`/`spot` (same
exclusion for row prices), `normalize/money.py` (`Invalid("per_unit"|"per_period")` for role `price`; `Ok` for
`unit_price`), `collect/og.py` (d.6 table), `resolve/preference.py` (range-bound rule), schemas/extraction/
normalization/resolution spec deltas, `backend/data/manifest.json` (CLDR units version pin), tests:
`test_schema_org_map.py` predicates, `test_dom_collector.py` exclusions, `test_og_collector.py`, property test in
`tests/property/test_normalize_money.py` (an amount followed by any CLDR unit of the page locale is never `Ok` for
`price`).
Acceptance: fixtures: JSON-LD with `priceSpecification[{priceType: StrikethroughPrice}, {referenceQuantity}]` and a
plain `price` → `price`, `list_price`, `unit_price` publish from the right nodes; DOM with `<s>€40</s> €25` and
`<span style="text-decoration: line-through">` → `list_price` 40, `price` 25; `€25/kg` → `unit_price` only; `$25/mo`
→ no `price` candidate; `AggregateOffer{lowPrice 80, highPrice 120}` + DOM `80` → `price_range`, no `price`;
OG `product:sale_price:amount` present → `price` from it, `product:price:amount` → `list_price`; preset sync test
shows the digest change and no required-field change.

**PR 7 — currency and number fixes (~+170 LOC)**
Files: `normalize/money.py` (symbol forms without bidi controls and trailing stop; minor-unit reading filter via
`get_currency_precision`), `normalize/numbers.py` (ASCII/compat fallbacks per CLDR group symbol; `arab`/`arabext`
symbols and digit mapping; `page_convention` narrowing), `collect/currencies.py` (page convention from unambiguous
amounts; platform currency members), `adapters/platforms.py` (`currency_members`; Shopify shape `variants[]`
members), `collect/platform_json.py` (variants rows), normalization/adapters spec deltas, `.claude/skills/verify-money`
model update (new property: a reading with more decimals than the currency's minor unit never publishes), property
tests extended.
Acceptance: `ر.س 120` with `html_lang=ar-SA` → SAR; `ر.س.‏120` → SAR; `1'234.50` with `de-CH` → 1234.50;
`١٬٢٣٤٫٥٠` with `ar-EG` → 1234.50; `$10.999` → `Ambiguous` unless the page convention settles it; `¥1,234` → 1234
JPY; a page whose JSON-LD prices use `.` decimals reads `1.234` text as 1.234; Shopify fixture with
`Shopify.currency = {active: "CAD"}` and a `.js` body `price: 12900` → `price` 129.00 CAD; variants rows with
`sku`/`barcode`. verify-money skill run passes.

**PR 8 — detect-and-report diagnostics (~+120 LOC)**
Files: new `content/signals.py` (structural signals: WebSocket/EventSource opened — from the browser's request log
`resource_type websocket`/`eventsource`; `application/wasm` resources; `flt-*`/`flutter-view` elements; `phx-*`
attributes / `blazor.server.js`; `_framework/blazor.webassembly.js`; `application/grpc-web*` bodies; PUA code points
in a money candidate's text; closed-root suspicion = custom element with no light text and no DSD; turbo-stream
`streamController.enqueue` chunks; Gatsby `/page-data/` links; `rel=amphtml`), `acquire/browser.py` (record the
resource types seen, counts only), `services/job_outcomes.py` (per-signal counts in the job summary; no URLs), jobs
spec delta, `tests/unit/test_signals.py` over fixtures (one per signal).
Acceptance: each fixture raises exactly its signal; a plain page raises none; the summary shape is in the OpenAPI.

No browser-identity PR: the user agent is the browser's own with `HeadlessChrome/` renamed `Chrome/` in the context
(owner #71); INV-44 sets no other header.

Order: 1 → 2a → 2b → 2c → 3a → 3b → 3c → 4 → 5 → 6 → 7 → 8. PRs 2c/3a/3b/3c/4 are independent of each other and
may run in parallel after 2b; 5 depends on 2a/2b/2c/3c; 6 and 7 depend on nothing after 1 and may run in parallel
with 2–5.
Verification: the e2e run over the eval set (C1); a claim that a change generalizes rests only on a fresh batch's
first score.

---

## (g) Decisions (frozen 2026-10-19)

The four questions the principles and the code did not settle, answered by the owner on 2026-10-19 and recorded as
owner decisions #71–#74 (the framework itself is #70). No question is open.

**Decision 1 — browser identity: the browser's own user agent, headless token renamed** (owner #71). The context's
`user_agent` is the browser's own with only `HeadlessChrome/` replaced by `Chrome/`, never the `--user-agent` launch
switch; client hints and every other header stay the browser's own (owner #50, INV-44). A page blocked by a
header-checking vendor stays `blocked` with its label; the owner's residential proxies and customer-supplied access
are the way through.

**Decision 2 — a challenge-free JavaScript shell renders once automatically** (owner #72). An HTTP 200 document with
no text and no links and no vendor or structural challenge is retried in the browser once per page (a.3 table); the
browser's `ok` is kept, otherwise the page's outcome is `shell`. The locate run still applies to the surface so later
fetches can drop to `call`/`http` sources. PR 2a's retry table carries it.

**Decision 3 — documented platform product JSON is joined always** (owner #73). On a page whose HTTP HTML
fingerprints Shopify or WooCommerce, the documented product JSON (Shopify Ajax product, WooCommerce Store API) is one
companion HTTP request per detail page, paced by the site's pacing (`politeness`), identity-checked and joined as a
`data_call` body, whether or not any field is missing. PR 2a.

**Decision 4 — price-role fields are user-added** (owner #74). `list_price`, `unit_price`, `unit_price_reference`,
`member_price`, `price_range` and `seller` are not added to the `commerce_detail` preset. The path-predicate grammar,
the `priceSpecification` reading and the active-price exclusions (d.1–d.2) are built so that a user-added field with
the documented `schema_org` path works; the schemas spec lists those paths as the recommended mappings. The preset's
`price` path gains the predicates that keep struck, member and per-unit prices out of it. PR 6.

---

## (h) Repo documents this architecture makes stale, and what to keep

PR 1 (docs freeze) adds this document to `openspec/design/`, moves the whole documents marked *archived* below to
`openspec/archive/`, records the owner's decisions and updates pointers. Every spec section below is rewritten by the
PR named in (f) that implements it (spec delta in the same PR; the specs state only current behaviour, and what
they used to state is kept in a dated section of `openspec/decisions/log.md`).

| Document | Section | Change |
|---|---|---|
| `openspec/specs/acquisition/spec.md` | "Browser on evidence" | rename "Browser on block or by field source"; the a.3 table; delete the offer/rows/render_fields clauses; a challenge-free `shell` retried once in the browser (decision 2) |
| | "Acquisition contract and block history" | contract = method, engine, handoff, coverage, platform; delete `settle_on`, `needs_render/xhr/traversal`, `forced` lesson, the "listing render" scenario |
| | "Data calls" | companion call always for fingerprinted documented platforms (decision 3); `call` field sources; eager fragment calls; credential references |
| | "HTTP and browser rungs" | fixed ready condition; open-shadow serialization; captured body types |
| | "Network JSON capture" | → "Network body capture": JSON, `text/x-component`, same-site `text/html` fragments |
| | "Patchright's documented browser setup (INV-42..44)" | allow context `locale`/`timezone_id` (owner P8); the user-agent rule of owner #71 (decision 1) |
| | "Structural outcome classification" | `unsupported_media`; 451 label `legal` |
| | "Acquisition candidates stay unbuilt" | unchanged list (residential proxies remain unbuilt beyond pool config) |
| `openspec/specs/extraction/spec.md` | "Structured-data collectors" | OG commerce tags; platform answer members; preset predicates |
| | new "Source documents" | a.4 reader list and pre-passes, each with its standard |
| | "Embedded JSON state and XHR admission" | documents from JS literals, decoders, attributes, RSC; admission rule unchanged |
| | "No generic DOM heuristics" | add: price-role exclusions are CLDR/HTML-standard rules (d.2) |
| `openspec/specs/resolution/spec.md` | "Fields a render would show" | → "Render-bound fields" (`render_bound`); delete `holds_state` |
| | "Candidate score" / price | #334 rule as written; range-bound rule |
| `openspec/specs/rest-api/spec.md` | "Render fields" | → "Render mode" (`render {mode, fields}`) |
| `openspec/specs/jobs/spec.md` | "Page outcomes", "Job outcome summary" | `geo_blocked`, `unsupported_media`; per-field missing counts and the locate hint; signal counts (PR 8) |
| `openspec/specs/learning-configs/spec.md` | "Config IR", "Learning trigger, sample and job", "Induction", "Held-out validation", "Activation" | `needs`, `recipes`, `located` origin; render samples; induction over sources; call replay in validation |
| `openspec/specs/adapters/spec.md` | "Recipe model", "Headers proven by replay", "Shopify values" | credential references; `currency_members`; variants members |
| `openspec/specs/normalization/spec.md` | "money", "range, count and number" | minor-unit filter; symbol forms; ASCII/Arabic conventions; page convention; per-unit/per-period invalid reasons |
| `openspec/specs/schemas/spec.md` | "schema.org paths", "Presets" | predicate grammar; `price` path predicates; recommended `schema_org` paths for the user-added price-role fields (decision 4); no new preset fields |
| `openspec/specs/listings/spec.md` | "Rows from captured calls", "Rows from page state" | located listing sources; fragments as row documents |
| `openspec/specs/persistence-storage/spec.md` | "Main data model tables", "Capture bundle format" | `site_contract` columns removed; `site_surface.render_mode`; body kinds |
| `openspec/design/owner-decisions.md` | rows #49, #54; new rows #70–#74 | PR 1: #49 and #54 marked superseded by #70 (the 2026-10-19 framework); #71–#74 record decisions 1–4 |
| `openspec/design/overview.md` | §22 | PR 1: anti-bot row notes decision 1 and points to (b) for the technology scope. Later PRs: add deferred rows: closed shadow roots, WebSocket client, iframes as sources, CSS generated content, OCR (never), Magento GraphQL companion call, htmx partials; §21 build order: append this plan's PRs |
| `openspec/backlog.md` | whole | *archived* in PR 1 (`openspec/archive/backlog.md`): the PR list in (f) is the current focus; its render-need follow-ups (STATE_MIN_VALUES, interaction_required narrowing) are closed by PR 2a; its other follow-ups are read from the archive when a PR touches their area |
| `openspec/OPEN_QUESTIONS.md` | whole | *archived* in PR 1 (`openspec/archive/OPEN_QUESTIONS.md`): row 10 is answered (configured pools only; residential pools untestable until a vendor exists), decisions 1–4 are owner decisions #71–#74; owner items are raised in reports and recorded in `owner-decisions.md` |
| `openspec/project.md` | "Capabilities", "Invariants" | INV-44 amendment text; no new invariant |
| `CLAUDE.md` | contract line on fetching | one sentence: HTTP by default; browser on block or by a located `browser` field source; LLM never the default extractor |
| `.claude/skills/verify-money` | model | minor-unit property; per-unit/per-period never `price` |
| the former acquisition plan (owner's notes, outside the repo) | whole | superseded; archived beside the other notes |

Kept as is: `openspec/decisions/log.md` (archive, closed to new entries since 2026-10-19; it holds the specs'
superseded text in dated sections), `openspec/decisions/README.md`,
`openspec/conventions/ENGINEERING.md` and `DESIGN.md`, `openspec/specs/variants`, `evaluation`, `identity-and-intent`,
`llm` (role C's place is unchanged; the locate run uses it as learning does), `frontend` (except the render picker
copy), `.claude/skills/verify-worker-queue`. The PR procedure is `docs/agents/builder-protocol.md`.

---

## Appendix: traceability of [U] dependencies

Every former [U] claim this design uses is CONFIRMED or REFINED in the owner's verification note: 3a `/_next/data`
(not fetched, same data), 3b Flight grammar, 3c Nuxt 2 devalue and Nuxt 3 flat array, 3d Remix/React Router/
SvelteKit/Angular/Gatsby/Astro, 3e Apollo/Redux (Relay CORRECTED: no global), 3f Magento init, 1b Fizz, 1c ESI, 4a
persisted queries, 4c service worker first visit, 5 shadow DOM (all three), 7 virtualization, 8 computed style, Table B
multipack/eligibleQuantity/tax/member/sale, §3 Shopify minor units and every platform endpoint, §4 block-rate figures,
missed items 1–16. Still unconfirmed and therefore not built: htmx partials (later), Flutter semantics tree
(report-only), Qwik blob format (report-only), Wix warmup data and Squarespace commerce JSON shapes (never relied on),
SFCC client-id use from a server (never relied on). Population data remains NPD for most price roles; nothing here
depends on a prevalence figure except the scope marks in (b), which are revisable from fresh-batch evidence (C1).
