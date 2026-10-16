# CrawlerAI v2 — project context

Read this file first, after `CLAUDE.md`. It holds what every change needs: what the system is, how `openspec/` is
laid out, the binding generalization contract, and the open owner items. Everything else is read on demand.

## Purpose

CrawlerAI v2 takes any URL or site and returns clean, normalized, typed records for a schema the caller chooses,
plus an executable per-site config. It is used through a REST API, an MCP server and a web UI; the API shapes are
our own. Commerce and jobs are the first schema presets, not the limit. Users: *config users* (consume configs for
an existing crawler platform), *data users* (consume records) and agents (through MCP). One deployment serves one
organization, with API keys; there is no billing. Open source under AGPL-3.0, in a public repo.
Goals G1–G7 and non-goals: [design/overview.md](design/overview.md) (§1).

## Stack

Python 3.12 (FastAPI, pydantic v2, SQLAlchemy async + asyncpg, Alembic, curl_cffi, httpx, Patchright headless,
selectolax, lxml, Babel/CLDR, trafilatura), PostgreSQL 16 (also the queue), S3-compatible object storage;
TypeScript (Vite+, React, HeroUI v3). One Docker image with three roles: `api`, `worker`, `scheduler`.
Full table and rejected alternatives: [design/operations.md](design/operations.md) (§19). Commands: `CLAUDE.md` §7.

## Layout of `openspec/`

| Path | Holds | Read |
|---|---|---|
| `project.md` | This file: purpose, layout, the contract C1–C13, invariant rules, open owner items | Always |
| `specs/<capability>/spec.md` | The **current behaviour**, as requirements with scenarios; one folder per capability (list below). The source of truth for what the system does. | The capabilities your change touches |
| `changes/<change-id>/` | In-flight work: `proposal.md` (why, what), `tasks.md` (the checklist; one PR implements a batch of tasks), `design.md` (only when needed; holds the change's decisions), `specs/<capability>/spec.md` deltas (`## ADDED`, `## MODIFIED`, `## REMOVED Requirements`) | Your change |
| `changes/archive/<date>-<name>/` | Done changes, frozen: the 16 original SPEC-NN specs with their decision logs. Index: [changes/archive/README.md](changes/archive/README.md) | When a ref (`SPEC-NN §x`, `D-NNNN`) points there |
| `backlog.md` | Follow-ups left by merged PRs, current focus, human-only tasks not tied to a change | When choosing work |
| `design/` | Rationale: the former `ARCHITECTURE.md`, section numbers kept, owner decisions (Appendix A), candidates register (§22). Index: [design/README.md](design/README.md) | When a spec links it |
| `decisions/` | How decisions are logged ([README](decisions/README.md)) and the cross-cutting log ([log.md](decisions/log.md)) | When logging a decision |
| `OPEN_QUESTIONS.md` | Questions only the owner or a user can answer, with recommended defaults | When escalating |
| `conventions/` | `ENGINEERING.md` (how to write code here), `DESIGN.md` (frontend conventions), `RECURRING.md` (repeated agent mistakes and their checks) | Implementors and reviewers, once per session |

## Capabilities

| Capability | Covers |
|---|---|
| [acquisition](specs/acquisition/spec.md) | Fetch rungs (HTTP, browser, proxy), outcome classification, politeness, robots, SSRF, body limits, cookies, captures |
| [adapters](specs/adapters/spec.md) | Multi-tenant platform adapters (Greenhouse, Lever, Shopify), detection, fallback to the page rungs (C6) |
| [api-backed-pages](specs/api-backed-pages/spec.md) | Endpoint discovery from network capture, API recipes, validation, execution |
| [schemas](specs/schemas/spec.md) | Field types, schema documents, presets, custom schemas, prompt and field-name drafts, page kind |
| [normalization](specs/normalization/spec.md) | One normalizer per field type; decline rather than guess |
| [extraction](specs/extraction/spec.md) | Parse once, collectors, locators, ownership, listings and pagination, content formats |
| [resolution](specs/resolution/spec.md) | Validity, ownership, intent, preference, atomic offers, evidence buckets, confidence, incomplete pages |
| [variants](specs/variants/spec.md) | The variant matrix: row-mapped lists, per-variant rows, common variant fields |
| [llm](specs/llm/spec.md) | The LLM client, budgets, usage and cost, roles C, A, D and S, grounding |
| [learning-configs](specs/learning-configs/spec.md) | Config IR, learning, validation, corroboration, progressive mode, drift, exporters, release check |
| [rest-api](specs/rest-api/spec.md) | Auth, `scrape`, schemas, configs, records, replay, usage endpoints, response shapes |
| [jobs](specs/jobs/spec.md) | Async jobs, queue, tasks and outcomes, batch and extract, results, events, webhooks, pinning |
| [crawl-map](specs/crawl-map/spec.md) | URL discovery (`map`) and the crawl frontier |
| [mcp-server](specs/mcp-server/spec.md) | MCP tools and transports |
| [recurring](specs/recurring/spec.md) | Conditional GET, content and record fingerprints, record versions, listing diff |
| [persistence-storage](specs/persistence-storage/spec.md) | Databases, data model, captures, retention, replay |
| [evaluation](specs/evaluation/spec.md) | Splits, custodian access, labels, metrics, suppression, the gate |
| [repo-checks](specs/repo-checks/spec.md) | The CI and local checks that enforce the contract |
| [frontend-app](specs/frontend-app/spec.md) | The web UI shell and its screens |
| [playground](specs/playground/spec.md) | The playground workspace at `/` |

## Generalization contract (C1–C13)

ARCHITECTURE §2.2, verbatim. Both earlier versions worked on the sites they were tuned on and produced garbage on new
ones. These rules are binding. A change that conflicts with them is wrong, even if it fixes a site. Why:
[design/generalization.md](design/generalization.md) (§2.1, §2.3, §20).

| # | Rule | Enforcement |
|---|---|---|
| C1 | **Held-out data is never seen and never fitted.** Splits: dev, hidden, fresh (§16). Hidden and fresh pages, their captures and their site metadata live **only** in a private database and object store (§15), never in the main DB, the repo, logs or CI artifacts (the repo is public, so CI logs and artifacts are too). Agents see only aggregates. Hidden and fresh are never used to fit thresholds, precedence or calibration. Every label is confirmed by a human. | Separate database and store with custodian-only credentials; a protected CI job. |
| C2 | **Generic code encodes standards, types and structure only.** Admissible justifications: a published standard (schema.org, ISO 4217/8601/3166, CLDR, GS1, RFC, HTML, Open Graph), a property of a field type, or a structural regularity of HTML. "Site X does Y" is never admissible. Each generic rule names its justification. | Review. |
| C3 | **No site literals outside site data.** Hostnames, retailer and brand names, and strings copied from pages appear only in the adapter package and in database rows. | CI scan of the whole repo with a domain regex and a reviewed allowlist (standards hosts such as schema.org, package registries, RFC 2606 example names). The scan against hidden and fresh hostnames runs in the protected job, from a secret list, reporting only file and line. |
| C4 | **No lists that grow one incident at a time.** Vocabularies come from versioned external data (CLDR, schema.org). A type vocabulary with no standard (such as availability phrases) lives in its normalizer, is tagged by language, and grows only under the C10 acceptance rule. | Review; PR report. |
| C5 | **A failing site is fixed with data, not code.** Re-run learning (§8.3) or correct the site's config through the API. A PR changes generic behaviour only for a class of failures. | Review. |
| C6 | **Adapters only for multi-tenant platforms**, evaluated on ≥ 3 tenants not used to build them. | Eval report. |
| C7 | **Normalizers decline rather than guess** (§9). No defaults, no host tables, no values from URL codes. Derived values fill only empty fields and carry `derived_by`. | Property tests. |
| C8 | **One module per field type.** | Import-linter independence and forbidden-import contracts, plus review. |
| C9 | **Tests check type properties and replays, not specific sites.** No test is named after a site or asserts one site's output. | C3 scan; review. |
| C10 | **How changes are accepted.** A change is accepted when it **improves dev** and **does not regress hidden** (§16.4). Claims that something *improved* are made only from **fresh** results, never from hidden. Accepting on "hidden improved" would fit hidden slowly through repeated selection. PR comments carry dev deltas and only the hidden pass/fail per field type. Numeric hidden aggregates go only to the custodian. Until labels exist (§21, milestone M), the gate reports `no_baseline` and acceptance rests on tests, replays and review. | CI; PR template. |
| C11 | **Two size checks, no others** (Appendix A #33). Cognitive complexity is at most 15 per function (as SonarSource defines it), a hard check. A file has at most 800 lines, a soft limit: CI warns and never fails. A file past 800 is split along logical boundaries (cohesive modules, field types per C8), never mechanically to meet the number. No other LOC, complexity, coverage or ratchet gates. | Complexity check in CI and `make check`; file-length warning; CI meta-check that refuses any other gate. |
| C12 | **Nothing is copied or ported from Invoro or v1:** code, lists, config, tests, prompts or data (Appendix A #24). | License scan; C3 scan. |
| C13 | **Mechanisms are admitted by evidence.** A mechanism outside core is added only when evaluation results or production outcomes show a class of failures it fixes, and its effect is measured. "It makes sense" and "v1 had it" are not evidence. | §22 register; PR report. |

## Invariants

The testable invariants keep their IDs `INV-01`…`INV-40` and live as requirements in their capability's
`spec.md`, each with what enforces it and whether that enforcement runs today. An invariant whose enforcement is not
built yet is still binding: review applies it until the check exists. Invariants are never removed or renumbered;
a superseded one keeps a requirement that says so. A change that adds one takes the next free ID (INV-41; check with
`grep -rhoE "INV-[0-9]+" openspec/specs | sort -u | tail -1`) in its spec delta.

## Open owner items

Decisions with status `needs-owner` or `pending-owner` (`CLAUDE.md` §5). Keep this list current; the entries are in
[decisions/log.md](decisions/log.md).

| ID | Title | Status |
|---|---|---|
| D-0783 | Investigate: approving a learned config before it becomes a reusable recipe | needs-owner (owner 2026-10-16: not now) |
| D-0784 | Investigate: an "absent" field status so role C stops asking | needs-owner (owner 2026-10-16: not now) |
| D-0915 | SimHash at Hamming 0 still misses some one-word edits | needs-owner |
| D-1024 | Listing rows without structured data take no item URL | needs-owner |
