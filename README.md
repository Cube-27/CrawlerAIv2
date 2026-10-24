<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/snowcrawl-logo-dark.svg">
    <img src="docs/assets/snowcrawl-logo.svg" alt="Snowcrawl" width="380">
  </picture>
</p>

<p align="center">
  <b>Point it at any website. Get clean, typed, evidence-backed records, and a config that keeps getting them.</b>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/architecture.md">Architecture</a> ·
  <a href="docs/rules.md">Rules</a> ·
  <a href="sdk/python/README.md">Python SDK</a> ·
  <a href="sdk/typescript/README.md">TypeScript SDK</a>
</p>

---

Every snowflake is different; so is every website. **Snowcrawl** is a schema-driven web extraction engine that
reads the page in front of it (its structured data, its DOM, the API calls it makes) and turns it into normalized
records for *your* schema. Every value comes with its evidence and a locator, and when Snowcrawl isn't sure, it says
nothing rather than guess. Then it learns the site, so the next crawl runs on a deterministic config with no LLM in
the loop.

## ❄️ What it does

- **Scrape, map, crawl, extract, search.** A REST API and an MCP server serve page content as markdown, HTML, links
  and metadata; discover a site's URLs; crawl it (best-first on a query, if you like); search the web through a
  provider you configure; and extract structured records with a JSON schema or a plain-language prompt.
- **Schemas are data.** Commerce and jobs ship as presets; define any schema you need. Each field has a type (money,
  enum, identifier, date, location, range, ...) and each type has exactly one normalizer, which declines rather than
  guesses.
- **Precision first.** Every published value carries its evidence, its confidence and a locator pointing to where it
  came from. A wrong value is worse than a missing one.
- **Progressive.** An unknown site works on the first call, from structured data plus grounded LLM extraction. After a
  few pages Snowcrawl learns a per-site config (XPath, JSONPath or an API recipe), validates it on held-out pages,
  and repeat crawls run deterministically.
- **Custom recipes.** When you know a site's API better than any heuristic, write the recipe yourself: a main call,
  extra calls, an optional warm-up and page fields. A URL its pattern matches is served by your recipe first.
- **Adapters.** Built-in adapters speak the public APIs of popular job-board and storefront platforms, so those pages
  come back structured without any learning at all.
- **Exportable and replayable.** Learned configs export as portable JSON or as XPath 1.0 + regex drafts for other
  crawler platforms, each re-executed before release. Every record can be regenerated from its stored capture.

### 🧪 The Recipes screen

The web UI covers jobs, records, schemas, sites, schedules and settings, plus a playground for one-off calls. Its
**Recipes** screen is a workbench for custom recipes: pick sample pages, see the calls they made, let Snowcrawl
propose a recipe from one endpoint, bind its parameters, test it against the samples, and save it, all before it
ever serves a real crawl.

## 🚀 Quick start

You need Docker (Compose included). It runs on Windows, macOS and Linux.

```sh
cp .env.example .env     # optional: every setting has a default
docker compose up
```

That builds the images, starts Postgres, applies the migrations, and runs the API, a worker, the scheduler and the
web UI.

- **Web UI:** http://localhost:8080 (it makes and uses its own API key)
- **API:** http://localhost:8000 (`GET /healthz`)
- **Your own API key:** `docker compose exec api snowcrawl apikey create --label me`

`docker compose down` stops everything and keeps the data (database, captures and browser profiles live in Docker
volumes); `docker compose down -v` deletes it too. After pulling, `docker compose up --build`.

Good to know:

- **Headful browser.** The browser rung runs headless. `SNOWCRAWL_BROWSER_HEADLESS=false` in `.env` runs it headful
  under Xvfb inside the container: no window appears on the host.
- **amd64 only.** Google Chrome has no Linux arm64 build, so the images are `linux/amd64`; Apple Silicon runs them
  under emulation, slowly.
- **Engine version.** `SNOWCRAWL_GIT_SHA=$(git rev-parse HEAD) docker compose up --build` stamps the commit into the
  engine version; without it the build uses `0000000`.

## 🛠️ Commands

The `snowcrawl` CLI runs inside the image (`docker compose exec api snowcrawl --help`):

| Command | What it does |
|---|---|
| `snowcrawl worker` | Claim queued tasks and run them |
| `snowcrawl scheduler` | Release expired leases, expire old data, re-check fetch methods |
| `snowcrawl fetch` | Fetch one URL over HTTP or in the browser into a capture bundle file |
| `snowcrawl schemas` | Schema definitions |
| `snowcrawl apikey` | API keys (the API never creates one) |
| `snowcrawl schedules` | Recurring schedules: list, pause, resume |
| `snowcrawl jobs` | A job's outcomes, and its stored captures extracted again |
| `snowcrawl data` | The pinned data files of `backend/data/manifest.json` |
| `snowcrawl openapi` | Print the API's OpenAPI document |

Development runs on the host with `uv` and `pnpm`:

```sh
docker compose up -d postgres     # the database the tests need
uv run tools/dev.py               # lists every command
uv run tools/dev.py check         # every CI check, locally
uv run tools/dev.py api-client    # regenerate frontend/openapi.json and the frontend's API types
uv run tools/dev.py sdk           # regenerate both SDKs from it
cd frontend && pnpm install && pnpm dev   # the UI on its dev server, against the API on :8000
```

The rest is in [CLAUDE.md](CLAUDE.md).

## 🧭 How it stays honest

Snowcrawl is built around a [generalization contract](docs/rules.md):

- accuracy is measured by one end-to-end run over an eval set kept outside the repo, which grows in fresh batches,
  each scored once before anyone fixes anything on it;
- generic code encodes only standards, types and HTML structure;
- site knowledge lives in data;
- new mechanisms are admitted only when evaluation evidence calls for them.

## 📚 Documentation

| Document | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | The pipeline as built and where each part lives |
| [docs/rules.md](docs/rules.md) | The product and repo rules CI and agents enforce |
| [docs/decisions.md](docs/decisions.md) | The important decisions in force, with the why |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute: checks, pull requests, the e2e report |
| [CLAUDE.md](CLAUDE.md) | Rules for coding agents working in this repo, and every command |
| [docs/agents/](docs/agents/) | The agent workflow: orchestrator guide and builder protocol |
| [Python SDK](sdk/python/README.md) · [TypeScript SDK](sdk/typescript/README.md) | Typed clients with job polling, event streaming and webhook verification |

**Agents: read [CLAUDE.md](CLAUDE.md) before changing anything.**

## 🧱 Stack

| Part | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, PostgreSQL (also the job queue), curl_cffi, Patchright, lxml, Babel/CLDR |
| Frontend | Vite, React, TypeScript, HeroUI |
| Deployment | One Docker image (linux/amd64) running three roles (api, worker, scheduler), with S3-compatible object storage |

## 🗂️ Repository layout

```
backend/                Python package `snowcrawl` (src/snowcrawl/), tests, alembic migrations
  src/snowcrawl/adapters/   the only source directory allowed to contain hostnames (C3)
  data/manifest.json        pinned external data; every file under data/ is listed here (C4)
  .importlinter             one-module-per-field-type and layering contracts (C8)
sdk/                    Python (pure httpx, pydantic) and TypeScript clients, generated from frontend/openapi.json
frontend/               Vite + React + TypeScript + HeroUI; generated API client in src/api/
docker-compose.yml      the one way to run the app: Postgres, migrations, API, worker, scheduler, web UI
infra/                  Dockerfile (the backend image), web/ (the web UI image: Dockerfile, nginx), postgres/init.sql
tools/                  dev.py (generators and every CI check), repo checks: site-literal scan, data manifest, license scan, no-size-gates, file length
docs/                   architecture, rules, decisions, agent guides, assets
.github/                CI workflows and the pull request template
.claude/skills/         agent procedures
```

The backend packages follow the pipeline: `acquire`, `collect`, `normalize`, `resolve`, `llm`, `config_ir`,
`content`, `crawl`, `recurring`, `search`, `api`, `mcp_server`, `worker`, `scheduler`, on top of `core`, `db`,
`services`, `storage` and `schemas`; `adapters` holds the platform source adapters.

## License

[GNU Affero General Public License v3.0](LICENSE).
