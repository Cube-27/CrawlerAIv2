# Tasks

## 1. Capture artifacts

- [ ] 1.1 The browser rung takes a screenshot (viewport or full page) and a PDF of the rendered page when the fetch
      policy asks; the fetch result carries them; the capture step stores them beside the bundle.
- [ ] 1.2 `screenshot` and `pdf` formats on scrape, batch and crawl force the browser rung; page outputs and answers
      carry the artifact URLs; `GET /v1/captures/{id}/artifacts/{name}`; retention deletes artifacts with the capture.

## 2. Content formats

- [ ] 2.1 `markdown_fit`: deterministic pruning, optional BM25 `query`.
- [ ] 2.2 `chunks`: heading, sentence and token strategies with size, overlap and heading path.

## 3. Exports

- [ ] 3.1 `jsonl`, `xlsx` and `parquet` on `GET /v1/jobs/{id}/results`.
- [ ] 3.2 `llms.txt` and `llms-full.txt` for crawl and batch jobs; `llms_txt` on `map`.

## 4. Surfaces

- [ ] 4.1 MCP: new formats, image block, `llms_txt` tool.
- [ ] 4.2 UI: formats and options in the playground, screenshot in the page drawer, export menu, llms.txt download.
- [ ] 4.3 Specs, API client, live verification.
