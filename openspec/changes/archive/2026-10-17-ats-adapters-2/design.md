# Design: five more adapters, adapter entities with identity

## Shape

- **Raw requests.** `JsonRequest.raw` makes `fetch_json` accept any 2xx body. An adapter that sends one reads the body
  into JSON and records that with `adapters.answer.recorded` (the request's attempts and timing kept), so the capture
  the collector reads is JSON and `serves`, the shapes and the stored capture are as for every adapter. `answer.serving`
  is the shared "no row is not served" check (SmartRecruiters now uses it); `answer.with_body` is what paging merges
  with.
- **XML.** `adapters/xml_reader.read_xml` (lxml, already a dependency): every element with child elements is an object
  of arrays by child name, a leaf is its trimmed text; a shape therefore walks `(name, ALL)` for every member.
- **Identity.** `collect/adapter.AdapterCollector` builds each entity with `schema_org_map.entity`, the function the
  JSON-LD and microdata collectors use: the identifier values and the `url` its shape maps are `identity` and
  `item_urls`; `resolve.identity` does the rest.

## Decisions

### D-1330 — BambooHR, Teamtailor, UKG Pro, Personio and ADP Workforce Now are admitted
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: the five platforms are admitted from §22 "More platform adapters" (owner decision #57, extended), reading
  the public data each platform's own pages load, verified live end to end through the scrape API: BambooHR on 5
  boards (listing and detail), Teamtailor on 2, Personio on 3 (one with descriptions), ADP on 1 center (list and job)
  and UKG on 1 board (search and opportunity). Paycom, iCIMS and JazzHR stay on the page rungs (no verified public
  data). Workable's per-job endpoint stays a follow-up. All run by default.
- Alternatives: wait for three tenants per platform found by search (the public tenants found were few: UKG and ADP
  show one each, both answer from the platform's shared endpoints, so the code paths are the platform's, not a
  tenant's).
- Why: the data is the platform's own public API, one request shape for every tenant (C6 asks for ≥ 3 tenants where
  they exist).
- Reversible: yes (`CRAWLERAI_DISABLED_ADAPTERS`)

### D-1331 — A request may be raw; the adapter records the JSON it reads from the answer
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: `JsonRequest.raw` (default false) skips the JSON check of a 2xx body; every other status, the SSRF guard, the
  caps and the proxy rules are unchanged. Personio's XML feed and UKG's opportunity page use it; their adapters answer
  `not_served` when the body is not what the platform serves, and record JSON otherwise.
- Alternatives: a second fetch function for text (duplicates the guarded client); a non-JSON capture body with a reader
  in the collector (the collector, `serves` and the replay all assume JSON, INV-39).
- Why: one guarded client, one capture shape.
- Reversible: yes

### D-1332 — XML is read by lxml with entities and DTDs off, and a DOCTYPE is refused
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: `read_xml` builds `etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
  huge_tree=False)` and refuses a document with any DOCTYPE (a feed has none), so entity expansion and external
  entities cannot occur; the body is already capped by the fetch and libxml2's depth limit applies. No new dependency
  (defusedxml would add one for the same guarantees).
- Alternatives: defusedxml; the standard library's `xml.etree` (expat expands internal entities).
- Why: lxml is a dependency already, and the guarantees are testable (entity bomb, external entity, depth).
- Reversible: yes

### D-1333 — Personio and Teamtailor serve lists only; a Personio ad is one description
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: both feeds hold every job and neither has an endpoint for one, and a shape cannot pick one item of a list, so
  their job pages are not detected and fall to the page rungs. A Personio position's ad is its `jobDescription`
  sections in order (a heading and an HTML body each); the adapter records them as one HTML `description` (each name in
  an `h2`) so the field has one candidate, not one per section (a section is not the description, and a custom section
  such as a slug would win a pick by position).
- Alternatives: serve a detail page from the whole list and filter by id (a shape language change); one candidate per
  section.
- Why: the smallest correct reading of the feed's structure; no value is inferred.
- Reversible: yes

### D-1334 — UKG's search endpoint is disallowed by the host's robots.txt, so the list serves only on an operator override
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: as for D-1306, the adapter is built and verified, and by default the host's robots.txt (`*/JobBoardView`
  disallowed) makes the list request `blocked` (`robots`), so the page rungs serve (a script-built list yields a shell);
  the opportunity page is allowed and is served. An operator override of robots.txt for the job serves the list
  (verified live with `respect_robots=false` and a reason). The tenant of a match is `{host}/{company}/{board}`: the
  platform has two hosts and the API and page URLs follow from it.
- Alternatives: skip the list; override robots.txt for APIs (never by default, ARCHITECTURE §7.1).
- Why: politeness is the contract (SPEC-15 §4.6).
- Reversible: yes

### D-1335 — An ADP job page is found by its external id in the list, and recorded with it
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: a career center page names a job by `jobId`, the `ExternalJobID` the list's `customFieldGroup` states, while
  the endpoint for one requisition takes its `itemID`; the adapter fetches the list, finds the requisition (by
  external id, or `itemID`), and fetches it, both through `send`. Both answers are recorded with an `externalJobID`
  member so a requisition's URL (the center's page with `jobId`) is mapped like any other value. A requisition that
  states no external id has no URL.
- Alternatives: a requisition URL from `itemID` (not a page of the platform); no URL.
- Why: a row without its URL cannot be told from another by the record keyset and merges with nothing.
- Reversible: yes

### D-1336 — Adapter entities carry identity through the same function as the structured collectors
- Date: 2026-10-17 · Change/PR: ats-adapters-2 (#251) · Status: decided (owner-delegated 2026-10-17)
- Decision: `AdapterCollector` builds its entities with `schema_org_map.entity`, so a shape's `identifier` values and
  `url` are the entity's identity and item URLs (D-1290, D-1291) and an adapter's posting merges with the page's
  JSON-LD posting of the same item. A shape that maps neither has an entity with none, as before.
- Alternatives: merge in the adapter collector (a second path for identity, C8).
- Why: this closes the #247 follow-up with no new rule.
- Reversible: yes
