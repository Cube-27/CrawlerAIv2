# CrawlerAI v2

Clean, normalized, typed records from any website, for any schema, plus an executable per-site extraction config
that a deterministic crawler can run.

> **Status: architecture v3 built; handed over 2026-10-21.** Accuracy is measured only by the e2e run over an eval
> set kept outside the repo. How it works: [docs/architecture.md](docs/architecture.md).

**Agents: read CLAUDE.md before changing anything.**

## What it does

- **Scrape, map, crawl, extract.** A REST API and an MCP server provide page content as
  markdown, HTML, links and metadata; URL discovery; site crawls; and structured extraction with a JSON schema or
  a plain-language prompt. The API shapes are our own.
- **Search and best-first crawls.** `POST /v1/search` returns web results from a provider the operator configures (a
  SearXNG instance or any JSON or HTML endpoint) and can scrape them in one batch job; a crawl with
  `strategy: "best_first"` and a `query` fetches the pages that match it first. Typed [Python](sdk/python/README.md) and
  [TypeScript](sdk/typescript/README.md) SDKs wrap the API with job polling, event streaming and webhook verification.
- **Schemas are data.** Commerce and jobs are presets, and any schema can be defined. Each field has a type such as
  money, enum, identifier, date, location or range, and each type has exactly one normalizer. A normalizer declines
  rather than guesses.
- **Precision first.** Every published value carries its evidence, its confidence and a locator pointing to where
  it came from. A wrong value is worse than a missing one, so the system abstains when it isn't sure.
- **Progressive.** An unknown site works on the first call, using structured data plus grounded LLM extraction.
  After a few pages, the system learns a per-site config (XPath, JSONPath or an API recipe) and validates it on
  held-out pages. Repeat crawls then run deterministically, with no per-page LLM calls.
- **Exportable configs.** Learned configs export as portable JSON or as XPath 1.0 + regex drafts for other crawler
  platforms (PHP 8.4 or later, on its HTML5 parser `Dom\HTMLDocument`). Each export is re-executed before release.
- **Replayable.** Every record can be regenerated from its stored capture.

## Why v2 is built this way

Two earlier versions did well on the sites they were tuned against and produced garbage on new ones. v2 is built
around a [generalization contract](docs/rules.md):
- accuracy is measured by one e2e run over an eval set that grows in fresh batches, each scored once before anyone
  fixes anything on it;
- generic code may encode only standards, types and HTML structure;
- site knowledge lives in data;
- new mechanisms are admitted only when evaluation evidence calls for them.

## Documentation

| Document | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for coding agents working in this repo, and every command |
| [docs/architecture.md](docs/architecture.md) | The pipeline as built and where each part lives |
| [docs/rules.md](docs/rules.md) | The product and repo rules CI and agents enforce |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute: checks, pull requests, the e2e report |
| [docs/agents/](docs/agents/) | The agent workflow: orchestrator guide and builder protocol |
| [docs/decisions.md](docs/decisions.md) | The important decisions in force, with the why |

## Stack

| Part | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, PostgreSQL (also the job queue), curl_cffi, Patchright (headless by default, or headful), lxml, Babel/CLDR |
| Frontend | Vite, React, TypeScript, HeroUI |
| Deployment | One Docker image (linux/amd64 only: Google Chrome has no arm64 build, use `--platform=linux/amd64` emulation) running three roles (api, worker, scheduler), with S3-compatible object storage |

## Getting started

You need Docker, [uv](https://github.com/astral-sh/uv), [pnpm](https://github.com/pnpm/pnpm) and GNU make.

```sh
make dev
```

This copies `.env.example` to `.env` if there is none, starts Postgres in Docker, applies the migrations and runs
the API on port 8000 (`GET /healthz`). The frontend runs separately: `cd frontend && pnpm install && pnpm dev`.
The UI never asks for an API key: `pnpm dev` attaches `CRAWLERAI_UI_API_KEY` from `.env` to its API requests, so set
it to a key from `cd backend && uv run crawlerai apikey create --label ui` first.
To run everything at once (API, worker, scheduler and the frontend on http://localhost:5173, in one terminal; Ctrl+C
stops all of them), use `make up` instead. It also creates the UI key and writes it to `.env` when that key is unset
or no longer in the database (after the database is recreated).
Every other command, including the checks CI runs, is in [CLAUDE.md](CLAUDE.md).

## Repository layout

```
backend/                Python package `crawlerai` (src/crawlerai/), tests, alembic migrations
  src/crawlerai/adapters/   the only source directory allowed to contain hostnames (C3)
  data/manifest.json        pinned external data; every file under data/ is listed here (C4)
  .importlinter             one-module-per-field-type and layering contracts (C8)
sdk/                    Python (pure httpx, pydantic) and TypeScript clients, generated from frontend/openapi.json
frontend/               Vite + React + TypeScript + HeroUI v3; generated API client in src/api/
infra/                  docker-compose.yml (Postgres), Dockerfile (the backend image), postgres/init.sql
tools/                  repo checks: site-literal scan, data manifest, license scan, no-size-gates, file length
docs/                   architecture, rules, decisions, agent guides
.github/                CI workflows and the pull request template
.claude/skills/         agent procedures
```

The backend packages follow the pipeline: `acquire`, `collect`, `normalize`, `resolve`, `llm`, `config_ir`,
`content`, `crawl`, `recurring`, `search`, `api`, `mcp_server`, `worker`, `scheduler`, on top of `core`, `db`,
`services`, `storage` and `schemas`; `adapters` holds the platform source adapters.

## License

[GNU Affero General Public License v3.0](LICENSE).
