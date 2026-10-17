# Delta: rest-api

## ADDED Requirements

### Requirement: Output format members and artifacts endpoint
Scrape, batch and crawl SHALL accept the formats `markdown_fit`, `chunks`, `screenshot` and `pdf`, with `fit`,
`chunking` and `fetch.screenshot` options valid only with their format; an answer names a screenshot or PDF as
`{url, content_type}`. `GET /v1/captures/{id}/artifacts/{name}` SHALL serve `screenshot.png` or `page.pdf` with
`nosniff`, behind the API key, and 404 once the capture is gone. `GET /v1/jobs/{id}/results` SHALL take the formats
`jsonl`, `xlsx` and `parquet` in the schema's columns (`xlsx` and `parquet` as one file, `parquet` 503
`format_unavailable` without pyarrow), and `GET /v1/jobs/{id}/llms.txt` and `llms-full.txt` SHALL answer the llmstxt.org
text of a job's pages (409 for none). The MCP `scrape` tool takes the new formats and returns a screenshot as an image
block; a twelfth tool, `llms_txt`, answers the file. Refs: D-1424, D-1425, D-1428.
#### Scenario: Artifact served
- **WHEN** a scrape asked for `screenshot` and its URL is fetched with the key
- **THEN** it answers `image/png` bytes
