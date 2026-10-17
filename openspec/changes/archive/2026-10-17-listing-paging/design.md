# Design: listing-paging

## Data shape

- `crawl.paging._View.ids`: the linked items' identities, else the digests of the rows of the first call series of
  `Tab.calls()` (the page's latest data responses); `_Held` restores the run's kept-state record when a state kept
  ahead of an action is dropped (`Tab.discard`).
- `resolve.call_rows.with_call_rows(graph, schema, rows, call_rows, candidates, page, base_url)`: the listing's rows
  with the call rows that extend them, and the candidates joined call rows give the structured rows. Identity keys:
  `("url", canonical item URL)` and `(identifier field, value)`.
- `config_ir.api_recipe.binding.withhold_tokens(samples) -> (samples, withheld names)`; `model.token_like`.
- `worker.handlers.steps.FetchedPage.further`: a listing recipe's pages after the first; `scrape_steps.Further`,
  `extract_further`, `store_further` shared by the scrape service and the worker.

## Decisions

### D-1400 Rows of a grown document
Status: decided (owner-delegated 2026-10-17). A kept state is the live document serialized, so a script injected after
an action and microdata the grown list carries are read like the first document's: no second read is needed. What
kept the first batch only was the row rule: listed rows excluded every unlisted entity. On a page whose target is
ambiguous (no entity singled out by the page URLs), top-level primary entities no list holds are rows beside the
listed ones; a microdata item merged with its JSON-LD twin stays one row (`resolve.identity`). Grown items that
neither structured data nor a call states (bare DOM blocks) stay for role C or a config.

### D-1401 Call rows join structured rows by item identity
Status: decided (owner-delegated 2026-10-17). A row's identity is its item URLs (`Entity.item_urls` and the values of
the schema's url row fields; schema.org `url`, "URL of the item") and the values of its identifier row fields, per
field. A call row and a structured (or config) row join when they share a key and neither shares one with another row
of the other kind (two candidates decline, C7). The call row's candidates of the row fields the structured row holds no
candidate of become that row's, keeping source kind `xhr` and the `network` bucket; a field the structured data states
is not joined, so the structured value never meets a call value in one row.

### D-1402 Call rows extend the listing within its block group
Status: decided (owner-delegated 2026-10-17). A call row naming no row's item is a row when one of its item URLs is a
link of the repeated item block group whose links hold most rows' item URLs: the listing shows it as one of its items
(a load-more's later batch while the script keeps the first). A call row of items shown in another group (related
items) or not linked at all adds none; a second call row of one item adds none. For the proof, a url row path counts a
row whose value is a link of one of the page's item blocks (HTML Standard §4.6.1: a hyperlink states the document it
leads to), so a call whose items the page links to proves its url path even when the field's other candidates name
other items. Its other fields keep the admission rule: values the structured data states for other items admit by
equality only, so the extended rows are partial without role C (follow-up).

### D-1403 An integer inside a segment numbers pages
Status: decided (owner-delegated 2026-10-17). The +1 link rule compares the one differing path segment or query value
as text split at its ASCII integers: the texts around the integers are equal and exactly one integer is one higher
(`page-2.html` to `page-3.html`, `p2` to `p3`); an integer standing alone is the case with empty texts around it. A
page URL with no integer still gives no structural link (C7): which number its next page would carry is not stated,
and a link holding `2` beside a first page that holds none is as often an item (`widget-2`) as a page.

### D-1404 A state kept ahead of each growing action
Status: decided (owner-delegated 2026-10-17). Before a scroll or a control click the driver keeps the state when it
shows an item no kept state holds, and drops it (`Tab.discard`: its data responses go to the next state) when the state
after the action still shows all its items. A list that only grows keeps one state as before; one that recycles its
items (a virtualised list) keeps each batch before it is replaced, so no item is lost between states (it was lost on
the first replacement, which only set a flag). The cost is one document read per action, within the 40-action cap.

### D-1405 The driver counts call rows when items hold no link
Status: decided (owner-delegated 2026-10-17). The tab hands the driver the JSON bodies of its latest data responses
(`Tab.calls`, at most the 50 a capture keeps, read once each); a page that shows no linked items is counted by the
rows of the first series of those calls (`network_match.data_calls`, `row_series`: rows whose own strings the page
shows), each named by the SHA-256 of its JSON text with members sorted (RFC 8259). Only one of the two counts, so an
item a call loaded and the page links to is not counted twice. A call of fewer than `MIN_ITEMS` rows (a short last
page) is no listing's rows and adds nothing. Mechanisms that need the items' place (a pager, the control after the
items) find none on such a page; scroll and next links work.

### D-1406 Recipe pages in the worker's tasks
Status: decided (owner-delegated 2026-10-17). A batch, extract or crawl task reading a listing's records on a site whose
pinned config's recipe has pagination is served by `RecipeRung.pages` with no row target: up to 50 requests, and for a
crawl up to its `limit` when lower (a crawl's `limit` bounds the pages it fetches; a batch request has no page or
record bound of its own, and adding one is an API change no use case asks for). The first page is the task's capture
and record as before; each further page is stored under the task with its capture, extraction and records
(`scrape_steps.store_further`, shared with the scrape service, C8), keyed by its own URL. The task's outcome is the
first page's. A page the SSRF guard refused a request of ends the further pages (INV-16). A first page not served
falls back to the page rungs, after the turn of the request that follows.

### D-1407 Token-like query values
Status: decided (owner-delegated 2026-10-17). A query value that looks like a token (`model.token_like`, the rule
header minimization applies: an item of 20 or more characters of one base64 alphabet) and is the same on every sample
is never stored: when a page value binds it on every sample (a URL part, or a `jsonld:`/`js_state:` path, now tried for
such constants too) it becomes a parameter read from the page at serving time, so a rotated key follows the page;
otherwise it is left out of the samples' endpoint URLs before binding and role D, and the replay decides: an endpoint
that answers without it gets a recipe without it, one that needs it is `not_learnable` with the names left out in the
reason, as a token header is. Proving the key necessary and storing it was rejected: a stored key goes stale and is a
secret of the site's in our database.
