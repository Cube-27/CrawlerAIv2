# Design: accuracy-r1

## Decisions

### D-1480 — `eval run` bounds listing rows to the label's row count, and reports every row too
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: `build_report(rows="labeled")` counts an unmatched engine row as FP only among the first as many engine
  rows as the label has rows; matched rows count wherever they are. `eval run` writes that report to `--out` and the
  report over every row to `<name>.all-rows.json`, and prints both per field type. A stored run (checked labels) keeps
  every row, as the gate's runs do; only a dev report may bound rows.
- Alternatives: the capture's first-page row set (an adapter's merged answer keeps no page boundary, and a generic page
  has one page anyway); bound by the last matched engine row (a scattered match would admit a further page's rows);
  drop unmatched rows altogether (hides rows the engine invents on the labeled page).
- Why: a label holds the page as it was labeled, its first page, and adapters and paging list the first page's rows
  first; the bound needs nothing but the label.
- Reversible: yes.

### D-1481 — Platform listing rows without a price stay so
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: no change. The matched platform rows missing `price` come from shops with several presentment currencies,
  whose tokenless answer prices in the primary market while the page shows its visitor's (D-1114), and from rows
  whose price range has two bounds (INV-14). Publishing them needs the currency the page shows: the page's own
  localization markup, a second request and a new source, which is the owner's to admit.
- Alternatives: publish the primary-market price (the round-3 failure D-1114 records); `@inContext(country:)` from the
  URL (C7).
- Why: C7; §2 (new sources arrive as whole layers when the owner admits them).
- Reversible: yes.

### D-1482 — Listing money declines: kept, and the hreflang rule waits for row URLs
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: of the listing prices declined as `invalid` or `ambiguous`, the `invalid` ones are structured prices with no
  `priceCurrency` on pages that state no currency in structured data (D-0301), and most `ambiguous` ones are `$` on
  pages whose language tag names no territory (D-0302): both stay declined. The rest are `$` on pages tagged with a
  territory whose alternate links name other territories: money's locale set reads every alternate's `hreflang`,
  though an alternate names another page's language (HTML §4.6.7.1). Reading only the alternates that link to the
  page itself fixes them, but on the dev set it also publishes prices on role C rows that carry no URL, which match
  no label row, so listing money precision fell (77.4 to 53.9, bounded). It is not landed here; it lands once role C
  rows carry their URL (backlog).
- Alternatives: land it and accept the drop (a precision regression on a required type, C10).
- Why: no field type may lose precision; the rule itself is right and recorded for the follow-up.
- Reversible: yes.

### D-1483 — A hosted Greenhouse board names its jobs by the board's route on its host
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: `AdapterMatch.host` holds the page's host for an adapter whose shapes build URLs on it. Greenhouse sets it
  for a hosted board page (`/{token}`, `/{token}/jobs/{id}`), and its shapes map a job's `url` to the job object's
  `id` after `https://{host}/{token}/jobs/`: the hosted board's documented job route, the URL the board's own pages
  link. An embedded board (`/embed/...`) keeps `absolute_url`, the page the embedding site states. A prefixed property
  now takes an integer member (an API's numeric id) in its decimal digits; a boolean or a fraction stays as it is.
- Alternatives: strip `gh_jid` (a query-word rule, C4); keep `absolute_url` (the owner's career page or the board's
  route with its routing query, neither of which a hosted board page links); a fixed board host (the page's host is
  the one the page shows).
- Why: the platform's route on the page's host is what the platform states for that board.
- Reversible: yes.

### D-1484 — image_url scores by the file it names
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: an image_url output (or list of images) that is not type-equal to its label scores TP when both name the
  same stored files by `resource_key` (authority and path, scheme and query aside), the rendition rule the resolver
  already uses (SPEC-05 §4.7). Collect is unchanged: it does not prefer a rendition size.
- Alternatives: collect prefers the largest rendition (sizes are written in paths and queries no standard defines).
- Why: a scheme or a sizing query does not make another image; renditions written in the path still differ.
- Reversible: yes.

### D-1485 — `apply_url` keeps `JobPosting.url`
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: the hosted Greenhouse apply URLs are fixed by D-1483 (the job page holds its application). A separately
  stated apply link (an answer's apply member, a schema.org `potentialAction` ApplyAction `target`) is not mapped:
  path alternatives pool with no ranking, so mapping it beside `url` would make the field a conflict, and mapping it in
  place of `url` would give the posting's entity a URL that is not its page.
- Alternatives: change the preset path to the ApplyAction alone (loses the pages whose posting URL is the apply page).
- Why: a ranked path is a schemas capability change; backlog.
- Reversible: yes.

### D-1486 — Structured text with escaped markup reads as the fragment's text
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: a text-type structured value with no element markup whose character references, decoded once, give
  element markup is read as that fragment's rendered text (`schema_org_map._fragment_read`), for every structured
  collector and the adapter collector; `1 &lt; 2` decodes to no element and stays text.
- Alternatives: a per-adapter flag for APIs that document escaped HTML (the same class appears in JSON-LD).
- Why: HTML Standard character references; the value is a serialized fragment.
- Reversible: yes.

### D-1487 — A place labeled by its text only scores by that text
- Date: 2026-10-18 · Change/PR: accuracy-r1 (#267) · Status: decided (owner-delegated 2026-10-17)
- Decision: when a location label states its text and no locality, region or country, an output scores TP when it is
  location-equal to the label with its own parts cleared (text by tokens, remote flag equal). Lists of places pair
  each label place with one output place by a maximum bipartite matching.
- Alternatives: change location equality (SPEC-04 §4.5 is the resolver's too).
- Why: a label silent on the parts claims nothing about them.
- Reversible: yes.
