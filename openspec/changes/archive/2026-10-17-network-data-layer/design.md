# Design: network-data-layer

The network data-source layer (Appendix A #59): a browser capture's fetch/XMLHttpRequest calls read as a data source,
generically, beside structured data and the DOM. Batch A1 (tasks 1-2) captures the calls and reads them at run time;
batch A2 (tasks 3) learns listing recipes with pagination from call series, in a second PR of this change.

## Data shape

- `NetworkBody` (one captured call): request (method, URL, body, headers), response (status, content type, headers),
  `resource_type`, `action`; the body as received.
- `network_match.Call` (a readable call: 2xx, `network_json`), `EndpointKey` (method, URL shape, body shape),
  `DataCall` (visible leaves, row query, row hits); `row_series` groups calls by endpoint and row query.
- `xhr` collector: a series and its per-field map (paths relative to a row) give `array_row` rows through
  `collect.api.read_rows`, the API recipe row reader.
- A2: `Pagination` (`param` | `cursor` | `next_url` | `link`, discriminated by `kind`); `pagination.infer(calls, rows)`
  and `first_request`/`next_request`, shared by serving and replay; `listing.ListingPage` (a stored page's published
  rows and the document states whose calls it reads), `ListingEndpoint` (series key, row map, score);
  `ReplayPage.listing` (the captured responses of pages 1 and 2); `network_match.LearnedCalls` (a listing recipe as
  its calls show it).

## Decisions

### D-1310 Network data-source layer admitted
Status: decided (owner-delegated 2026-10-17). The owner's rule #53 names "identifying a page's network/API calls the way
crawl engineers do" as the next generic layer; under the delegation of 2026-10-17 it is admitted from §22 as one
layer: capture, a shared reader, run-time listing rows, an evidence bucket, and (A2) listing recipes with pagination.
Recorded as Appendix A #59 and a §22 row. CAPTCHA, logins, typing and real Chrome stay out (owner #50, #52).

### D-1311 What the browser keeps
Status: decided (owner-delegated 2026-10-17). Responses whose request destination is fetch/XMLHttpRequest or a
document (Fetch Standard §2.2.5), not the main frame's navigation; a body labelled with a JSON MIME type (WHATWG MIME
Sniffing §4.6: `application/json`, `text/json`, `+json`) is kept as before, one labelled `text/plain` or not labelled
only when its bytes are an RFC 8259 object or array. A guard prefix (a cross-site script inclusion guard such as
`)]}'`) is at most 16 characters holding no `{` or `[`: the JSON text starts at the first opener. Bodies are stored as
received and every reader parses them with `network_json`, so the browser and the readers agree. Empty bodies are not
kept. 10 MB of network bodies per page in all (INV-30), beside 2 MB and 50 bodies. Response headers are recorded as
request headers are (no cookies, SPEC-02 §4.7): `Link` (RFC 8288) and paging headers are what A2 reads.

### D-1312 Action index
Status: decided (owner-delegated 2026-10-17). `NetworkBody.action` counts the browser actions (click, scroll, goto,
back) the page had performed when the response arrived: 0 for the page's own load, None in older bundles. Counting, not
naming, actions keeps the tab's protocol unchanged; a kept state's calls are those since the last kept state.

### D-1313 One reader of captured calls (refines the orchestrator's design note)
Status: decided (owner-delegated 2026-10-17). `collect/network_match.py` is the only reader of network bodies for the
collectors and API discovery (C8); discovery keeps only its published-value scoring, and the URL shape moved there from
`binding`. A call carries data when one of its values is visible. Its rows are the array whose object items each hold a
visible string of their own (not one every item repeats), at least `MIN_ITEMS`. The note's separate "structured" score
and alignment with `acquire.items` blocks are left out: visibility of an item's own values already says the page shows
the items, also in a table without links, and one rule is easier to measure. JSON numbers are not counted: a page shows
a number formatted, and short numbers match any counter.

### D-1314 Listing rows from a call series
Status: decided (owner-delegated 2026-10-17). A row field's path is proved on the page when the state admission rule
(equality with another kind's candidate, or a checkable type shown on the page) admits its value in `MIN_ITEMS` rows or
more; the proved path is then read in every row of the series, as a recipe's map is read, so a row the page has not
scrolled into view keeps its values. The first series (best rows call first) with a proved field is read; its calls are
read as rows only, and the other calls are admitted value by value as before. A series' calls share their origin and
path as well as their endpoint key: only query or body values vary (a URL shape alone lets two resources meet, review
of #250). A request sent again counts once. Rows
are `array_row` entities, not schema.org `ListItem`s, so structured-row selection never mistakes them for stated
items. Text fields are admitted by equality only (owner accuracy Q2 option a), so cold rows carry checkable fields; a
learned map (A2) reads text fields too.

### D-1315 Where the rows serve
Status: decided (owner-delegated 2026-10-17). Structured rows, then the config's rows, then the rows of captured calls.
Rows of calls that leave a record incomplete still ask role C, whose rows replace them; when role C reads none, they
stand. Complete rows of a call skip role C.

### D-1316 The `network` evidence bucket
Status: decided (owner-delegated 2026-10-17). A value of a captured call takes evidence `network` (§10), measured apart
as `<type>|network` and uncalibrated until dev labels exist; before, a lone `xhr` value had no bucket and abstained, so
the layer could publish nothing. A lone `js_state` value keeps no bucket. `xhr` ranks last in the committed precedence
orders of text, long_text, url and image_url (`backend/data/source_precedence.yaml`), so it never wins over another
kind. On a detail page a lone visible checkable `xhr` value now publishes; array-row ownership (#55) keeps related
items' values from the target.

### D-1317 A2 in a second PR
Status: decided (owner-delegated 2026-10-17). Listing recipes (pagination kinds, inference from call series, the paged
executor for every kind, learning's listing path with two-page replay validation, browser renders for samples without
network bodies) touch learning and the job services; they are tasks section 3, a second PR of this change, which stays
open.

### D-1360 Pagination kinds
Status: decided (owner-delegated 2026-10-17). `pagination` is a union discriminated by `kind`: `param` (where, name,
start, step), `cursor` (where, name, the response path of the cursor), `next_url` (the response path of the URL) and
`link` (RFC 8288 `rel=next`). `where` is `query` (a parameter name) or `body` (a normalized JSONPath into the JSON body,
no wildcards; GraphQL `variables` are such a path); a body value needs a body. Every field is required: no defaults.
A next URL or link target is followed only on the request's own origin (RFC 6454), as a recipe's scheme and host are
fixed. A body value keeps the JSON type the captured body gave it.

### D-1361 Inference from a call series
Status: decided (owner-delegated 2026-10-17). Kinds are tried from the most exact: `link` (each response's next link is
the next call's URL), `next_url` (one response path resolves to it), `param` (one varying request value whose integers
step by a constant), `cursor` (one varying request value equal to a scalar at one path of the previous response). Any
second varying request value (a timestamp, a token) leaves the series without pagination, the conservative reading. The
first call may lack the value (a cursor has no previous answer; a page parameter added from page 2 needs three calls
to show the step). Every sample page with two or more calls must give the same pagination.

### D-1362 A series' query names may differ
Status: decided (owner-delegated 2026-10-17). `row_series` keys calls by method, literal origin and path, body shape and
row query, no longer by the endpoint key's query names: a listing's first call often lacks the page or cursor
parameter its next calls add, and the literal path still keeps two resources apart (refines D-1314).

### D-1363 The paged executor
Status: decided (owner-delegated 2026-10-17). `RecipeRung.pages(url, policy, records=, limit=50, admit_next=)` runs
every kind: it stops at a page with no object rows, when the pagination names no next page or one already requested (a
cursor that comes back), when the rows yielded reach `records`, at `limit` requests, or when `admit_next` refuses the
next request; a non-`ok` page is yielded last. The first request is the caller's admitted turn (D-0603 kept for
`param`).

### D-1364 Listing recipes are learned (supersedes D-0604)
Status: decided (owner-delegated 2026-10-17). A listing's endpoint is the series, on every sample page with calls,
whose row paths read values `equal` to the published row values of a field in `MIN_ITEMS` rows (or every published
row, when fewer), a required field among them; per field the path matching most rows wins. Before binding, each
page's first call gets its pagination value set to where the listing starts, so binding sees a constant; binding needs
two distinct listing URLs (one URL cannot tell a parameter from a constant, and a parameterless recipe would serve every
listing of the site the same rows). Role D, when binding is ambiguous, is told the pagination kind and where it sets
the page, and keeps that value as captured (`d_bind.txt`); the pagination joins its spec.

### D-1365 Two-page replay validation
Status: decided (owner-delegated 2026-10-17). A listing recipe's replay for a page requests its first page and the page
its pagination names next, and compares each with the page's captured calls of the endpoint: the same rows in the same
order with each mapped raw value equal (the same API answers the same JSON; normalizing would hide a drifted row).
The second page is compared where the page captured a second call; a held-out page with fewer is rendered while
renders are left. Held-out acceptance stays SPEC-09 §4.7's (every field reproduced on at least 3 pages).

### D-1366 Renders while learning
Status: decided (owner-delegated 2026-10-17). `learn_recipe(render=)`: a sample page whose capture holds no calls (for
a listing: also one whose endpoint series has fewer than two calls when no pagination showed) is rendered with network
capture, a listing with its browser actions toward 60 rows (`services.scrape_paging.learning_render`: robots.txt, the
site's rate, the default policy); at most 3 sample and 3 held-out pages per run, one browser at a time (the worker
launches one per render: learning renders are rare). Published values stay those of the stored capture. Discovery reads
only the sample pages that have calls when two or more do (a capture without calls says nothing of the endpoint), for
detail recipes too.

### D-1367 Learned maps read a capture's calls
Status: decided (owner-delegated 2026-10-17). `ConfigExecutor.learned_calls` gives the active listing recipe as its
calls show it (method, origin, path segments with placeholders as wildcards, row query, map); the `xhr` collector reads
a series of those calls with the recipe's map before proving paths on the page, so a browser capture's call rows carry
the text fields learning proved by equality with published values (D-1314's equality-only rule is for cold rows).

### D-1368 A listing scrape served by its recipe
Status: decided (owner-delegated 2026-10-17). A records-only listing scrape with browser actions on a site whose active
recipe has pagination is served by `RecipeRung.pages` over HTTP with `browser_actions.records` as the target, each page
a further kept state (capture and records), no actions report; when its first page is not served the browser actions
run (SPEC-09 §4.10). The worker's crawl and batch tasks keep serving a listing's first page only (follow-up).

### D-1369 The settle wait and data calls in flight; the paging driver's items
Status: decided (owner-delegated 2026-10-17). A render whose content is quiet while a fetch or XMLHttpRequest call is in
flight is read up to 3 s later (`_CALL_WAIT_S`), so a late data call is kept and a long poll costs at most 3 s. The
paging driver still counts linked DOM items only: counting a call's rows needs the tab to hand the driver its bodies
while it acts, which is not small; it stays a follow-up.

