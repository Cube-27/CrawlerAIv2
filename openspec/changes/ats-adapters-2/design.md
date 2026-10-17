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
