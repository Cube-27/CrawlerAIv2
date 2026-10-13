# Invariants

The testable invariants of CrawlerAI v2. Each one has an ID, a statement, the `ARCHITECTURE.md` rule or section it
comes from, and what enforces it. Specs add invariants; none is ever removed or renumbered. A spec that adds one
appends its row here in the same PR.

**Status** says whether the enforcement runs today (`active`) or which spec adds it. An invariant whose enforcement
is not built yet is still binding: review applies it until the check exists.

| ID | Invariant | Ref | Enforced by | Status |
|---|---|---|---|---|
| INV-01 | No hidden or fresh case (URL, host, label, capture) exists in the main DB, the repo, logs or CI artifacts. | C1, §6, §15 | Separate DB and object prefixes with custodian-only credentials; the protected job uploads no artifacts and writes aggregates only to the private store; log redaction test. | Separate DB and roles: active (`infra/postgres/init.sql`; `app` refused: `tests/db/test_eval_private_database.py`). Main DB holds dev cases only: active (CHECK on `eval_page.split`, `eval_run.split`). No artifacts: active (`eval-protected.yml`). Aggregate names no host and suppresses small cells: active (`test_aggregate_suppresses_small_cells_and_names_no_host`). Redaction test: SPEC-03. |
| INV-02 | Calibration tables, `source_precedence.yaml`, drift margins and type vocabularies are derived from dev only. | C1, §10, §16 | Calibration and precedence commands refuse any split but `dev`, and stamp the artifact with its source split. | SPEC-03, SPEC-05 |
| INV-03 | No hostname or URL literal outside `adapters/`, docs, lockfiles and the justified allowlist. | C3 | `tools/site_literal_scan.py --public` in CI and pre-commit. | Active (CI `site-literals`, pre-commit `site-literals`). |
| INV-04 | No hidden or fresh host appears anywhere in the repo. | C1, C3 | Protected scan (`--hidden-hosts-from-env`), reporting file:line only. | Active (`eval-protected.yml`); the host list exists from milestone M. |
| INV-05 | Every data file under `backend/data/` comes from a pinned external source listed in the manifest. | C4 | `tools/data_manifest_check.py`. | Active (CI `data-manifest`). |
| INV-06 | A normalizer never returns `Ok` for empty input, never maps an ambiguous symbol without context, never reads a host table. | C7, §9 | Hypothesis property tests per type. | SPEC-04 |
| INV-07 | Derived values fill only empty fields and carry `derived_by`. | C7 | Resolver tests. | SPEC-05 |
| INV-08 | Exactly one module handles each field type; only `normalize.*` imports Babel, price-parser, dateparser and GeoNames data. | C8 | import-linter contracts (`backend/.importlinter`). | Active (CI `backend`, `lint-imports`). |
| INV-09 | No test file, test name or fixture contains a hostname or retailer name. | C9 | The INV-03 scan covers `tests/`. | Active (CI `site-literals`). |
| INV-10 | Replay is deterministic: the same (bundle, schema, config, calibration) yields byte-identical records, with LLM calls replayed from recorded responses. | G7, §15 | Replay tests run twice and diff. | SPEC-03 |
| INV-11 | Blocked and shell captures yield zero candidates and zero records. | §7.1, §8.2 | Unit tests on the pipeline entry. | SPEC-05 |
| INV-12 | Every `llm` candidate value is a verbatim substring of the cleaned text at its stated offsets. | §11 | Grounding check test. | SPEC-06 |
| INV-13 | URL query-parameter values are never published unless the same value is visible on the page. | §8.2 r4 | Resolver test. | SPEC-05 |
| INV-14 | For exact-match types, two valid owned candidates that disagree produce `conflict` and no value. | §10 | Property test. | SPEC-05 |
| INV-15 | Price, currency and availability of a published offer come from one source object. | §10 | Resolver test. | SPEC-05 |
| INV-16 | Every outbound connection target is a public IP; each redirect hop is re-checked; proxies do not bypass the check. | §7.1, §18 | SSRF tests with a stub resolver. | SPEC-02 |
| INV-17 | LLM output is never executed. | §11, §18 | ruff S102/S307, plus a grep for `exec(`, `eval(` and `subprocess` outside an allowlisted module. | ruff: active (`S` rules in `backend/pyproject.toml`). Grep: added with the first LLM code (SPEC-06). |
| INV-18 | CI and hooks contain no LOC, complexity or coverage-threshold gates. | C11 | `tools/no_size_gates.py` (CI `no-size-gates`). | Active. |
| INV-19 | Every PR that touches extraction behaviour carries the dev delta report and the hidden pass/fail per field type. | C10 | PR template; protected job comment. | PR template: active. Protected job comment: SPEC-03. |
| INV-20 | An exported config field reproduces the engine's value on every held-out page while there are fewer than 10, and on ≥ 95% from 10 on, or is marked `manual`. | §12.3 | Release check test. | SPEC-08 |
| INV-21 | Wrong-product count on hidden is 0, or the merge fails. | G2, §16.4 | Protected job gate. | SPEC-03; reports `no_baseline` until milestone M. |
| INV-22 | Every candidate carries a locator; every published field carries `evidence`, `confidence`, `calibrated`, `source_kind` and `locator`. | §6, §13.1 | Pydantic models and tests. | SPEC-05 |
| INV-23 | Every LLM call writes a `usage_event` with `prompt_kind` and is charged to a job budget. | §11, §17 | LLM client tests. | SPEC-06 |
| INV-24 | `site.fetch_method` and block classification are decided from HTTP status and structural body properties only; no vendor or challenge-page strings exist in code. | C2, C3, §7.1 | INV-03 scan; review. | Scan: active. Classification: SPEC-02. |
| INV-25 | In a hidden or fresh aggregate, no suppressed cell can be recovered by subtraction: in every group of cells that sums to a reported total (bucket and config-status cells per field type; category, acquisition and usage cells over `n_pages`), never exactly one cell of several is suppressed. | §16.3, D-0234 | Property test `test_no_suppressed_cell_is_derivable_from_its_group`. | Active. |
| INV-26 | Within one pipeline run (or one `scrape` request), each capture body is parsed at most once per parser (selectolax, lxml); collectors, cleaned text, content formats, pagination and the engine executor read one shared `ParsedPage`. The release executor (INV-20) is the only exception. | §8, Appendix A #31 | A test that counts parser constructions in `extract_page` and `scrape`. | SPEC-05 (`content.page`), SPEC-07, SPEC-08 |
