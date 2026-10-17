# Design: output formats

One design question each decision answers; the requirements are in the deltas under `specs/`.

## Decisions

### D-1420 — Screenshot and PDF force the browser rung
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- A request for `screenshot` or `pdf` is fetched in the browser with no adapter or recipe (a JSON endpoint is not the page); over HTTP only it is refused 422 before any job. INV-45 states it. A capture reused through `max_age` must hold the file asked for.

### D-1421 — Artifacts are objects beside the bundle, not rows
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- Files are keyed `captures/Y/M/<id>.<name>`, written before the capture row, found by `exists` per fixed name, deleted by retention with the bundle, and served only through the keyed API (`nosniff`, private cache). A file over 25 MB or one the browser failed to make is left out. No table change, so the baseline migration is untouched.

### D-1422 — Fit markdown is block scoring, not an LLM
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- Blocks are scored by link density, text density and how many pages' blocks repeat (boilerplate); a block below the cut is dropped, `fit.max_blocks` caps the rest. With `fit.query`, BM25 over blocks ranks them. All parameters are named by the standards they come from (BM25 k1, b), not tuned to a site.

### D-1423 — Chunks split the chosen markdown by heading, sentence or token
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- Sizes and overlap are in words (a tokenizer-free proxy for tokens, stated in the API), every chunk carries its heading path, and `chunking.source` picks `markdown` or `markdown_fit`.

### D-1424 — `fit`, `chunking` and `fetch.screenshot` are valid only with their format
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- An option without its format is a 422, as the other format-bound options are; a job stores them in its request so page outputs rebuild the formats.

### D-1425 — Answers name artifacts by URL; the UI uses the same URL
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- `{url, content_type}` is a path on the API's own origin. The playground UI loads it through its server, which attaches the key (SPEC-12 §4.1), so no key reaches the browser. JSON values with `include=fetch` also name the files so a schema job's drawer can show them.

### D-1426 — Exports reuse the CSV columns; xlsx and parquet are one file
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- `jsonl`, `xlsx` and `parquet` use the columns and statuses of `csv_records`; `csv_safe` quoting applies to spreadsheet cells. `xlsx` and `parquet` take no cursor (a file is whole) and answer bytes with a download name. A job without a schema is 409.

### D-1427 — llms.txt follows llmstxt.org; sections by shared directory
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- H1 title and blockquote from the first page's metadata, `## Pages` for root pages and one section per first path segment shared by pages; `llms-full.txt` appends each page's markdown. Capped at 5000 links and 1000 pages. `map` takes `llms_txt` for the file of its URLs.

### D-1428 — Parquet is an optional extra, xlsx a base dependency
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- `openpyxl` (MIT) is a base dependency; `pyarrow` (Apache-2.0) is the `parquet` extra, and its absence is a 503 `format_unavailable` problem, never a crash. Both pass the license check.

### D-1429 — MCP and UI expose every format
- Date: 2026-10-17 · Change/PR: output-formats (#259) · Status: decided (owner-delegated 2026-10-17)
- `scrape` takes the formats and returns a screenshot as an MCP image block; `llms_txt` is the twelfth tool. The playground offers each format and its options; the scrape output has Markdown (fit), Chunks and Screenshot tabs, the page drawer shows the screenshot, and a More exports menu saves JSON Lines, Excel, Parquet and the llms.txt pair.

