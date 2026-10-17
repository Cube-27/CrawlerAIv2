# CrawlerAI v2

Clean, normalized, typed records from any website, for any schema, plus an executable per-site extraction config
that a deterministic crawler can run.

> **Status: implemented, not yet measured.** The core pipeline, API, MCP server and UI are built (16 specs done,
> [openspec/changes/archive/](openspec/changes/archive/README.md)). Accuracy is unknown until labels exist (milestone
> M). Work in progress: [openspec/changes/](openspec/changes/) and [openspec/backlog.md](openspec/backlog.md).

**Agents: read CLAUDE.md before changing anything.**

## What it does

- **Scrape, map, crawl, extract.** A REST API and an MCP server provide page content as
  markdown, HTML, links and metadata; URL discovery; site crawls; and structured extraction with a JSON schema or
  a plain-language prompt. The API shapes are our own.
- **Schemas are data.** Commerce and jobs are presets, and any schema can be defined. Each field has a type such as
  money, enum, identifier, date, location or range, and each type has exactly one normalizer. A normalizer declines
  rather than guesses.
- **Precision first.** Every published value carries its evidence, its confidence and a locator pointing to where
  it came from. A wrong value is worse than a missing one, so the system abstains when it isn't sure.
- **Progressive.** An unknown site works on the first call, using structured data plus grounded LLM extraction.
  After a few pages, the system learns a per-site config (XPath, JSONPath or an API recipe) and validates it on
  held-out pages. Repeat crawls then run deterministically, with no per-page LLM calls.
- **Exportable configs.** Learned configs export as portable JSON or as XPath 1.0 + regex drafts for other crawler
  platforms. Each export is re-executed before release.
- **Replayable.** Every record can be regenerated from its stored capture.

## Why v2 is built this way

Two earlier versions did well on the sites they were tuned against and produced garbage on new ones. v2 is built
around a [generalization contract](openspec/project.md#generalization-contract-c1c13):
- accuracy is measured on hidden and fresh sites that developers and agents never see;
- generic code may encode only standards, types and HTML structure;
- site knowledge lives in data;
- new mechanisms are admitted only when evaluation evidence calls for them.

## Documentation

The docs follow the [OpenSpec](https://github.com/Fission-AI/OpenSpec) layout: current behaviour as requirements per
capability, in-flight work as change folders, done work archived.

| Document | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for coding agents working in this repo, what to read, and every command |
| [openspec/project.md](openspec/project.md) | Project context, the generalization contract C1–C13, open owner items |
| [openspec/specs/](openspec/specs/) | The current behaviour, one `spec.md` of requirements per capability (invariants `INV-NN` included) |
| [openspec/changes/](openspec/changes/) | In-flight changes (proposal, tasks, spec deltas); [archive/](openspec/changes/archive/README.md) holds the done specs SPEC-00 … SPEC-15 |
| [openspec/backlog.md](openspec/backlog.md) | Current focus, follow-ups and human-only tasks |
| [openspec/design/](openspec/design/overview.md) | Design rationale (goals, contract evidence, candidates register) and the owner decisions; the full former ARCHITECTURE.md is archived |
| [openspec/decisions/](openspec/decisions/README.md) | How decisions are logged, and the cross-cutting log |
| [openspec/OPEN_QUESTIONS.md](openspec/OPEN_QUESTIONS.md) | Decisions still open, each with a recommended default |
| [openspec/conventions/](openspec/conventions/) | `ENGINEERING.md` (engineering principles), `DESIGN.md` (frontend conventions), `RECURRING.md` (recurring agent mistakes) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute: checks, pull requests, the evaluation report |
| [.claude/skills/](.claude/skills/) | Agent procedures: `run-plan`, `implement-pr`, `pickup` |

## Stack

| Part | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, PostgreSQL (also the job queue), curl_cffi, Patchright (headless), lxml, Babel/CLDR |
| Frontend | Vite, React, TypeScript, HeroUI |
| Deployment | One Docker image running three roles (api, worker, scheduler), with S3-compatible object storage |

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
Every other command, including the checks CI runs, is in [CLAUDE.md §7](CLAUDE.md#7-commands).

## Repository layout

```
backend/                Python package `crawlerai` (src/crawlerai/), tests, alembic migrations
  src/crawlerai/adapters/   the only source directory allowed to contain hostnames (C3)
  data/manifest.json        pinned external data; every file under data/ is listed here (C4)
  .importlinter             one-module-per-field-type and layering contracts (C8)
frontend/               Vite + React + TypeScript + HeroUI v3; generated API client in src/api/
infra/                  docker-compose.yml (Postgres), Dockerfile (the backend image), postgres/init.sql
tools/                  repo checks: site-literal scan, data manifest, license scan, no-size-gates, file length
openspec/               project context, capability specs, changes and archive, design, decisions, conventions
.github/                CI workflows (ci.yml, eval-protected.yml) and the pull request template
.claude/skills/         agent procedures
```

The backend packages follow the pipeline: `acquire`, `collect`, `normalize`, `resolve`, `llm`, `config_ir`,
`content`, `crawl`, `recurring`, `eval`, `api`, `mcp_server`, `worker`, `scheduler`, on top of `core`, `db`,
`storage` and `schemas`. [SPEC-00 §4.1](openspec/changes/archive/2026-10-12-spec-00-project-setup/SPEC-00-project-setup.md#41-repo-layout)
describes each.

## License

[GNU Affero General Public License v3.0](LICENSE).
