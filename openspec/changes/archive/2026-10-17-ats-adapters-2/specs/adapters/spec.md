## ADDED Requirements

### Requirement: BambooHR, Teamtailor, UKG Pro, Personio and ADP adapters
They SHALL detect only the hosted forms their public data names (BambooHR career sites, Teamtailor company hosts' job
lists, UKG Pro job boards and their opportunity pages, Personio company hosts' lists, ADP Workforce Now career centers
by company and center id), fetch the documented JSON, JSON Feed, search API, embedded opportunity or XML feed (UKG in
pages of 50 by `Top` and `Skip`; a list that holds no row, a redirect to the platform's own site, or a page that embeds
nothing is `not_served`) and map `JobPosting` title, locations, date posted, employment type, description, identifier,
URL and the pay where the platform states one, as in `adapters/{bamboohr,teamtailor,ukg,personio,adp}.py`; Teamtailor
and Personio have no endpoint for one job, so a job page falls to the page rungs. Refs: D-1330, D-1333, D-1334, D-1335.
#### Scenario: Board without a careers site
- **WHEN** a company's careers list endpoint answers a redirect to the platform's own site
- **THEN** the adapter's answer is `not_served` and the page is fetched by the page rungs
#### Scenario: Job id from the page
- **WHEN** a career center page names a `jobId` that one requisition of the list states as its external id
- **THEN** that requisition's endpoint is fetched and its capture carries the id for the job's URL

### Requirement: Answers that are not JSON
A request MAY be `raw` (`JsonRequest.raw`): a 2xx answer is then `ok` whatever its body, every other status classifies as
for JSON. An adapter that sends one SHALL record a capture whose body is the JSON its shapes read (the feed read by the
bounded XML reader, the object a page embeds), or answer `not_served`; the collector only ever reads JSON. The XML
reader SHALL resolve no entity, load no DTD, reach no network, refuse a DOCTYPE and bound nesting. Refs: D-1331, D-1332.
#### Scenario: XML with entities
- **WHEN** a feed declares an entity or a DOCTYPE
- **THEN** it is not read and the adapter's answer is `not_served`

## MODIFIED Requirements

### Requirement: Shapes read as schema.org nodes
An adapter SHALL state, for the page it detected (its `AdapterMatch`), the `Shape`s that place schema.org nodes in its
JSON; the adapter collector walks them into entities and candidates with `source_kind='adapter'`, mapped like JSON-LD,
listings as `ItemList` rows. A shape may read a property from further members after its own (`also`) and put a
root before each of a property's string values (`prefixes`); a field that reads a whole node whose shape maps
properties reads an object of those properties' schema.org names. Each entity carries what identifies its item as a
JSON-LD entity does (its identifier values and item URLs), so resolution merges it with the page's own statement of the
item. A body that does not match yields no entities, never an exception. Refs: §8.1, D-0266, D-1087, D-1115, D-1176,
D-1304, D-1336.
(Previously: an adapter's entities carried no identity and could not merge with the page's JSON-LD.)
#### Scenario: One item in the API and in the page
- **WHEN** a detail page's JSON-LD `JobPosting` and the adapter's posting state one identifier or one item URL
- **THEN** they are one entity, with the values of both
