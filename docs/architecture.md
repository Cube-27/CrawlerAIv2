# Architecture

What the code does today. One Docker image, three roles (`crawlerai api|worker|scheduler`, `crawlerai/cli.py`);
PostgreSQL is the store and the queue, an object store (`storage/`, fs or S3) holds captures.
Layering is enforced by `backend/.importlinter` (`make check-backend`): `api > mcp_server > services > crawl/recurring/search
> config_ir > resolve/llm > collect > content > normalize > schemas > acquire/adapters > db/storage > core`.

## Request path

`api/routers/*` (mounted in `api/app.py`) and the MCP server (`mcp_server/server.py`, mounted at `/mcp`) both call
`services/*`. Synchronous `POST /v1/scrape` and queued jobs (batch, crawl, extract, map, search, schedules) run the same
page task: `services/page_run.py`. Workers claim tasks from Postgres (`db/queue.py`, `worker/loop.py`) and run the
handler of the job kind (`worker/handlers/`); `scheduler/loop.py` enqueues schedules, rechecks and retention.

## Pipeline

1. **Acquire** (`acquire/`). `rungs.py` picks the rung: HTTP first (`http.py`, `curl_client.py`, TLS profile in
   `impersonate.py`), the Patchright Chrome browser (`browser.py`, `shared_browser.py`, `browser_profiles.py`) when blocked,
   a JS shell, or `render.mode` asks. `classify.py`/`challenge.py` set the block class (`ok|blocked|shell|not_found|error`).
   Politeness, robots (off by default), SSRF guard and redirects: `politeness.py`, `robots.py`, `ssrf.py`, `redirects.py`.
   Site memory (the rung a site's pages start with): `memory.py`. The result is a capture bundle (`core/capture.py`,
   `storage/capture_bundle.py`); every record can be replayed from it (`POST /v1/captures/{id}/replay`).
   URLs an adapter detects go to the adapter first (`adapters/`: Greenhouse, Lever, Shopify, Workday, … `registry.py`).
2. **Content** (`content/`). Parse once (`content/page.py`), then markdown/html/links/metadata/chunks for the content formats.
3. **Collect** (`collect/`). `collect/run.py` runs every collector over the one parse: `jsonld`, `microdata`, `og`, `dom`,
   `js_state`, `xhr`, `platform_json`, `adapter`, `config`; listing rows via `collect/items/`. Each yields candidates with
   evidence and a locator.
4. **Resolve** (`resolve/`). `resolve/pipeline.py:extract_page` is the one function the worker and replay run:
   ownership/intent (`ownership.py`, `intent.py`, `identity.py`), preference (`preference.py`, data in
   `backend/data/source_precedence.yaml`), derivations (`derive.py`), offers (`offers.py`), evidence and confidence
   (`evidence.py`, `score.py`), listing rows (`listing.py`, `rows.py`), pagination (`pagination.py`). A field the page does
   not state stays unpublished; contested values are conflicts. If resolution raises, the outcome is `error` and nothing is set.
5. **Normalize** (`normalize/`). `dispatch.py` sends each field type (`schemas/types.py`: text, money, enum, url, identifier,
   date, location, range, count, number, list, object, …) to its one module; a normalizer declines rather than guesses.
6. **LLM** (`llm/`). Role C fills only what the structured sources lack (`llm/roles/c_extract.py`), roles S draft schemas and
   labels; every value must be grounded verbatim in the page (`grounding.py`, `claim_checks.py`). Output is data, never code.
7. **Outputs**. Records with per-field evidence, confidence, locator (`services/records.py`, `services/page_store.py`);
   `llms.txt` views; configs export (`config_ir/exporters`).

## Proxies

`CRAWLERAI_PROXY_POOLS` (`core/proxy.py`) maps a pool name to a proxy URL or to
`{"endpoints": [url, ...], "mode": "rotate"|"sticky", "country"?, "timezone"?, "locale"?}`; a request's
`fetch.proxy_pool` names one, else the fetch is direct, from the place `CRAWLERAI_EGRESS_COUNTRY`, `_TIMEZONE` and
`_LOCALE` declare. `rotate` takes endpoints in turn, `sticky` keeps a site on one endpoint. An endpoint whose username or
password holds `{session}` is a provider gateway with sticky exits: each site (registrable domain) gets a session id
there, so its HTTP, JSON and browser fetches leave from one address; the exit ends after `SESSION_TTL` or
`SESSION_FETCHES` (as cookie sessions do, `acquire/session.py`) or at a failure through it (block, no answer), and the
next fetch mints another. The exit is part of the browser profile key (`context_key`, profiles of an exit live only
in this process), and a cookie session earned through it ends with it. Timezone rule (`acquire/locality.py`): the
exit's declared IANA zone, else the one zone of its declared country, else the request locale's region's; a country of
several zones and no declared zone sets none (the machine's), which startup logs once (`check_places`). The locale is
the request's, else the exit's declared one, and the HTTP and JSON rungs send it as `Accept-Language` too.

## Learned configs

`config_ir/` holds the IR (`model.py`), learning (`learning.py`, `induction.py`, `listing_induction.py`, `synthesis.py`),
validation on held-out pages (`validation.py`, `held_out.py`), activation and drift (`activation.py`, `drift.py`), operator
corrections (`corrections.py`), API recipes (`api_recipe/`) and executors (`executor.py`, `release_executor.py`, which
shares no code with the engine). Configs keep selectors and cookies, never values. Learn jobs: `worker/learn.py`.

## Jobs and data

`db/models.py` is the schema (one baseline migration in `backend/migrations/`). Crawl frontier: `crawl/frontier.py`;
recurring diffing: `recurring/`; webhooks: `db/webhook_outbox.py`, `services/webhook_deliveries.py`; usage and LLM cost:
`db/usage.py`, `services/llm_costs.py`.

## Surfaces

REST under `/v1` (`scrape`, `batch/scrape`, `map`, `search`, `crawl`, `extract`, `schemas`, `records`, `captures`, `jobs`,
`schedules`, `configs`/`sites`, `usage/llm`, `project/settings`; `GET /healthz`): the contract is `frontend/openapi.json`
(`make api-client`). Bearer API keys (`crawlerai apikey create`). Schemas (presets in `schemas/presets/*.json`) are data.
SDKs in `sdk/python`, `sdk/typescript` (`make sdk`); web UI in `frontend/`.

## Pinned data

Vocabularies live in `backend/data/` and are pinned with sha256 in `backend/data/manifest.json` (`tools/data_manifest_check.py`).
`calibration.json`, `source_precedence.yaml`, `drift_margins.json` are as fitted on 2026-10-18; no code refits them, a refit is flagged to the owner.
