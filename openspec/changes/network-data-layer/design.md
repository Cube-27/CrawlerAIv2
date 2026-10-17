# Design: network-data-layer

The network data-source layer (Appendix A #57): a browser capture's fetch/XMLHttpRequest calls read as a data source,
generically, beside structured data and the DOM. Batch A1 (tasks 1-2) captures the calls and reads them at run time;
batch A2 (tasks 3) learns listing recipes with pagination from call series, in a second PR of this change.

## Data shape

- `NetworkBody` (one captured call): request (method, URL, body, headers), response (status, content type, headers),
  `resource_type`, `action`; the body as received.
- `network_match.Call` (a readable call: 2xx, `network_json`), `EndpointKey` (method, URL shape, body shape),
  `DataCall` (visible leaves, row query, row hits); `row_series` groups calls by endpoint and row query.
- `xhr` collector: a series and its per-field map (paths relative to a row) give `array_row` rows through
  `collect.api.read_rows`, the API recipe row reader.

## Decisions

### D-1310 Network data-source layer admitted
Status: decided (owner-delegated 2026-10-17). The owner's rule #53 names "identifying a page's network/API calls the way
crawl engineers do" as the next generic layer; under the delegation of 2026-10-17 it is admitted from §22 as one
layer: capture, a shared reader, run-time listing rows, an evidence bucket, and (A2) listing recipes with pagination.
Recorded as Appendix A #57 and a §22 row. CAPTCHA, logins, typing and real Chrome stay out (owner #50, #52).

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
read as rows only, and the other calls are admitted value by value as before. A request sent again counts once. Rows
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
