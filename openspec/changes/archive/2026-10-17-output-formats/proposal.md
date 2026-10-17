# Change: output formats

## Why

A scrape returns text formats only. Users of a crawler also want a picture or a PDF of the page, main content with the
page's boilerplate pruned and split into chunks for retrieval, results as JSONL, Excel or Parquet files, and an
`llms.txt` of a crawled site. Owner delegation 2026-10-17: build them as part of one robust product.

## What Changes

- `screenshot` (viewport or full page, PNG) and `pdf` formats on scrape, batch and crawl. Requesting either forces the
  browser rung. The file is stored beside the capture's bundle, and the answer carries a URL the API serves
  (`GET /v1/captures/{id}/artifacts/{name}`). The UI shows the screenshot in the page drawer.
- `markdown_fit` (deterministic main-content pruning by link density, text density and cross-page repetition, with an
  optional BM25 `query`) and `chunks` (split the markdown by heading, sentence or token count with size and overlap,
  each chunk carrying its heading path). No LLM.
- `GET /v1/jobs/{id}/results` formats `jsonl`, `xlsx` and `parquet` beside the existing three, from the same columns;
  `csv_safe` also applies to `xlsx`. The UI's export menu offers them.
- `GET /v1/jobs/{id}/llms.txt` and `llms-full.txt` for a crawl (or batch) job, and an `llms_txt` member of `map`.
- MCP: the new formats are in `scrape`'s request schema; a screenshot also comes back as an image block; a new
  `llms_txt` tool.

## Impact

- Capabilities: [acquisition](../../specs/acquisition/spec.md), [extraction](../../specs/extraction/spec.md),
  [rest-api](../../specs/rest-api/spec.md), [jobs](../../specs/jobs/spec.md),
  [persistence-storage](../../specs/persistence-storage/spec.md), [frontend](../../specs/frontend/spec.md).
- Files: `backend/src/crawlerai/{acquire,content,services,api,mcp_server,config_ir/exporters,scheduler}/`,
  `frontend/src/`, `frontend/openapi.json`. No table changes: artifacts are objects keyed from the capture's key.
- Dependencies: `openpyxl` (MIT); `pyarrow` (Apache-2.0) as the optional extra `parquet`.
