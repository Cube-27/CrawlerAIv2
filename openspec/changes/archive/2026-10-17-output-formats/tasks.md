# Tasks

## 1. Capture artifacts

- [x] 1.1 The browser rung takes a screenshot (viewport or full page) and a PDF of the rendered page when the fetch
      policy asks; the fetch result carries them; the capture step stores them beside the bundle. (259)
- [x] 1.2 `screenshot` and `pdf` formats on scrape, batch and crawl force the browser rung; page outputs and answers
      carry the artifact URLs; `GET /v1/captures/{id}/artifacts/{name}`; retention deletes artifacts with the capture. (259)

## 2. Content formats

- [x] 2.1 `markdown_fit`: deterministic pruning, optional BM25 `query`. (259)
- [x] 2.2 `chunks`: heading, sentence and token strategies with size, overlap and heading path. (259)

## 3. Exports

- [x] 3.1 `jsonl`, `xlsx` and `parquet` on `GET /v1/jobs/{id}/results`. (259)
- [x] 3.2 `llms.txt` and `llms-full.txt` for crawl and batch jobs; `llms_txt` on `map`. (259)

## 4. Surfaces

- [x] 4.1 MCP: new formats, image block, `llms_txt` tool. (259)
- [x] 4.2 UI: formats and options in the playground, screenshot in the page drawer, export menu, llms.txt download. (259)
- [x] 4.3 Specs, API client, live verification. (259)