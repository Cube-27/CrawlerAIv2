# Tasks

## 1. Admission

- [ ] 1.1 Owner-decisions row #57 and a §22 row admitting the network data-source layer (owner delegation
      2026-10-17).

## 2. Capture and runtime source (batch A1)

- [ ] 2.1 `NetworkBody` keeps `response_headers` (no cookies), `resource_type` and `action`; old bundles decode with
      None.
- [ ] 2.2 The browser keeps fetch, XMLHttpRequest and document responses whose body is JSON by media type or by
      sniffing (RFC 8259, anti-script-inclusion prefix), within 2 MB per body, 50 bodies and 10 MB per page.
- [ ] 2.3 A listing's browser actions tag each call with the index of the action it followed.
- [ ] 2.4 `collect/network_match.py`: readable calls, endpoint keys, visible leaves, row arrays, data calls best
      first; Hypothesis properties.
- [ ] 2.5 `XhrCollector` reads a listing's rows from its best endpoint's call series through the API recipe row
      reader; `collect/run.py` and listing resolution take them where structured data and the config give none.
- [ ] 2.6 API discovery reads calls through `network_match` and keeps only its published-value scoring.

## 3. Listing recipes and pagination (batch A2)

- [ ] 3.1 Pagination kinds `param`, `cursor`, `next_url` and `link` (RFC 8288) in `config_ir/api_recipe/model.py`,
      query or body.
- [ ] 3.2 `config_ir/api_recipe/pagination.py` infers the kind from two or more calls of one endpoint; Hypothesis
      properties.
- [ ] 3.3 `execute.pages()` runs every kind, POST bodies included, and stops on empty rows, an absent cursor or the
      records target.
- [ ] 3.4 Learning accepts listing recipes (supersedes D-0604), validated by replaying pages 1 and 2 against the
      captured rows; samples without network bodies get a browser render with capture.
