# Change: the network data-source layer

## Why

Many pages load their data through their own fetch/XMLHttpRequest calls; crawl engineers read those calls instead of
the DOM. The owner's rule #53 says further data sources arrive as whole generic layers, one at a time; under the owner
delegation of 2026-10-17 the network data-source layer is admitted from §22 (Appendix A #57). Today the browser keeps
only bodies labelled JSON (not JSON served as `text/plain` or behind an anti-script-inclusion prefix), records no
response headers or the browser action a call followed, has no per-page byte bound, gives no listing rows from the
calls, and API discovery scores calls with logic of its own.

## What Changes

- Admission: owner-decisions row #57 and a §22 row admitting the network data-source layer.
- Capture: the browser keeps fetch, XMLHttpRequest and document responses whose body is JSON by media type or by
  sniffing (RFC 8259, an anti-script-inclusion prefix stripped), within a per-page total cap; `NetworkBody` gains the
  cookie-free response headers, the Fetch resource type and the index of the browser action the call followed (None
  for bundles written before).
- `collect/network_match.py`: the one reader of captured calls (readable bodies, endpoint keys, visible leaves, the
  row array of a call); `XhrCollector` reads a listing's rows from the call series of its best endpoint through the
  API recipe row reader (`collect/api.py`), and API discovery uses the same module.
- Listing resolution takes those rows where structured data and the config give none, below role C when they leave a
  required field unpublished.
- Later batch (A2, tasks section 3): listing recipes with pagination kinds and their inference from call series.

## Impact

- Capabilities: [acquisition](../../specs/acquisition/spec.md), [extraction](../../specs/extraction/spec.md),
  [persistence-storage](../../specs/persistence-storage/spec.md), [adapters](../../specs/adapters/spec.md).
- Design: `openspec/design/overview.md` §22, `openspec/design/owner-decisions.md` #57.
- Files: `storage/capture_bundle.py`, `acquire/browser.py`, `acquire/browser_tab.py`, `content/page.py`,
  `collect/network_match.py`, `collect/xhr.py`, `collect/api.py`, `collect/admission.py`, `collect/run.py`,
  `resolve/pipeline.py` (listing rows source), `config_ir/api_recipe/discovery.py`, `config_ir/api_recipe/binding.py`.
