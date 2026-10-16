# Data model

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 6. Data model

There are two Postgres databases:
- **main:** everything below except hidden and fresh evaluation data;
- **private eval:** hidden and fresh pages, their captures and runs, readable only by the custodian role (C1).

Money is `numeric`, and times are UTC. Full DDL, plus implementation plumbing such as run events, record versions,
the queue, and the private eval tables: SPEC-01 and SPEC-03.

| Table | Key columns | Notes |
|---|---|---|
| `project` | id, name | Groups sites. |
| `api_key` | id, hashed_key, label, last_used_at | API and MCP access. |
| `site` | id, project_id, host (exact, lowercased, unique), platform?, fetch_method (`http`, `browser`), proxy_pool?, robots_snapshot, crawl_delay_ms | `fetch_method` is remembered from evidence (§7.1). |
| `schema_def` | id, name (unique), page_kind, fields, required_groups, origin (`preset`, `user`, `prompt_draft`), status | Edited in place (§5.2). |
| `extraction_config` | id, site_id, schema_id, page_kind, version, status (`draft`, `active`, `suspended`), ir (§12), origin (`adapter`, `induced`, `llm_synth`, `operator`), field_status (per field → `corroborated` / `uncorroborated` / `operator` / `suspended`, plus validation yield), validation_report | One `active` per (site, schema, page_kind). |
| `progressive_state` | site_id, schema_id, page_kind, mode (`cold`, `learning`, `active`), pages_extracted | §8.4. A schema edit sends it back to `cold`. |
| `job` | id, project_id, kind (`scrape`, `batch_scrape`, `map`, `crawl`, `extract`, `learn`), request (frozen), schema_id?, status, webhook_url?, engine_version, usage | — |
| `url_task` | id, job_id, url, canonical_url, page_kind?, status, attempts, capture_id, outcome (`extracted`, `partial`, `unchanged`, `links_only`, `blocked`, `shell`, `not_found`, `no_match`, `failed`), last_error | Claimed with `FOR UPDATE SKIP LOCKED`. |
| `url_state` | site_id, canonical_url, etag, last_modified, content_fingerprint, record_fingerprint, last_seen_at, last_changed_at, missing_runs, gone_at? | §14. |
| `capture` | id, site_id, url, fetched_at, method (`http`, `browser`, `api`), status_code, final_url, block_class, object_key, html_sha256, expires_at | Production and dev captures only (§15). |
| `extraction` | id, url_task_id, capture_id, engine_version, config_version?, mode (`adhoc`, `config`), llm_calls | One resolver run. |
| `candidate` | id, extraction_id, entity_ref, field, raw_value, normalized_value, normalize_status (`ok`, `ambiguous`, `invalid`), source_kind (`adapter`, `api`, `jsonld`, `microdata`, `og`, `js_state`, `xhr`, `config`, `llm`, `derived`, `dom`; `derived` marks a page-URL derivation, §10, and no candidate row holds it), independent (bool), locator (§8.1), chosen, reject_reason | Kept 30 days. |
| `record` | id, extraction_id, job_id, site_id, schema_id, entity_key, version, data, field_meta (per field → status, reason, evidence, confidence, calibrated, source_kind, locator, derived_by?), complete (bool), changed_fields, mode, fingerprint, schema_digest, created_at | `data` holds published fields only. `schema_digest`: the document it was extracted with (§5.2). |
| `eval_page` (dev in main; hidden and fresh in private) | id, capture_id, split, schema_id, page_kind, category, labels (value + locator, explicit `absent`), labeler, checker | — |
| `eval_run` | id, engine_version, split, metrics | Hidden and fresh runs export aggregates only. |
| `usage_event` | id, job_id, resource, provider, model_or_pool, quantity, metadata | Visibility and budgets; not billing. |
