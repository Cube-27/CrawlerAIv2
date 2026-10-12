# CrawlerAI v2

Clean, normalized, typed records from any website, for any schema, plus an executable per-site extraction config
that a deterministic crawler can run.

> **Status: design.** No code exists yet. The architecture and the implementation specs are complete, and
> implementation starts with [SPEC-00](docs/specs/SPEC-00-project-setup.md).

## What it does

- **Scrape, map, crawl, extract.** A REST API and an MCP server cover the same ground as Firecrawl: page content as
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
around a [generalization contract](docs/ARCHITECTURE.md#2-generalization-contract):
- accuracy is measured on hidden and fresh sites that developers and agents never see;
- generic code may encode only standards, types and HTML structure;
- site knowledge lives in data;
- new mechanisms are admitted only when evaluation evidence calls for them.

## Documentation

| Document | Purpose |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The single design reference |
| [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) | Decisions still open, each with a recommended default |
| [docs/specs/](docs/specs/README.md) | Implementation specs in build order, each with a PR plan |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Log of decisions made during implementation |
| [docs/plans/ACTIVE.md](docs/plans/ACTIVE.md) | Current implementation state |
| [CLAUDE.md](CLAUDE.md) | Rules for coding agents working in this repo |

## Planned stack

| Part | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, PostgreSQL (also the job queue), curl_cffi, Patchright (headless), lxml, Babel/CLDR |
| Frontend | Vite, React, TypeScript, HeroUI |
| Deployment | One Docker image running three roles (api, worker, scheduler), with S3-compatible object storage |

Setup and development commands will be added here by SPEC-00.

## License

[GNU Affero General Public License v3.0](LICENSE).
