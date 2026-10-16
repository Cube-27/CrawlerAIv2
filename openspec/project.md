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
Full table and rejected alternatives: ARCHITECTURE §19 ([archived](changes/archive/2026-10-16-architecture-rev25/ARCHITECTURE.md)). Commands: `CLAUDE.md` §7.

## Layout of `openspec/`

| Path | Holds | Read |
|---|---|---|
| `project.md` | This file: purpose, layout, the contract C1–C13, repo checks, invariant rules, open owner items | Always |
| `specs/<capability>/spec.md` | The **current behaviour**, as requirements with scenarios; one folder per capability (list below). The source of truth for what the system does. | The capabilities your change touches |
| `changes/<change-id>/` | In-flight work: `proposal.md` (why, what), `tasks.md` (the checklist; one PR implements a batch of tasks), `design.md` (only when needed; holds the change's decisions), `specs/<capability>/spec.md` deltas (`## ADDED`, `## MODIFIED`, `## REMOVED Requirements`) | Your change |
| `changes/archive/<date>-<name>/` | Done changes, frozen: the 16 original SPEC-NN specs with their decision logs. Index: [changes/archive/README.md](changes/archive/README.md) | When a ref (`SPEC-NN §x`, `D-NNNN`) points there |
| `backlog.md` | Follow-ups left by merged PRs, current focus, human-only tasks not tied to a change | When choosing work |
| `design/` | [overview.md](design/overview.md): goals, the evidence behind the contract, milestone M, the candidates register (§22); [owner-decisions.md](design/owner-decisions.md): ARCHITECTURE Appendix A, appended as the owner decides. The full ARCHITECTURE rev 25 (cited in code as `ARCHITECTURE §N`) and the old INVARIANTS table are frozen in [the archive](changes/archive/2026-10-16-architecture-rev25/) | When a spec or a ref points there |
| `decisions/` | How decisions are logged ([README](decisions/README.md)) and the cross-cutting log ([log.md](decisions/log.md)) | When logging a decision |
| `OPEN_QUESTIONS.md` | Questions only the owner or a user can answer, with recommended defaults | When escalating |
| `conventions/` | `ENGINEERING.md` (how to write code here), `DESIGN.md` (frontend conventions), `RECURRING.md` (repeated agent mistakes and their checks) | Implementors and reviewers, once per session |

## Capabilities

| Capability | Covers |
|---|---|
| [acquisition](specs/acquisition/spec.md) | Fetch rungs (HTTP, browser, proxy), outcome classification, politeness, robots, SSRF, body limits, cookies, captures |
| [adapters](specs/adapters/spec.md) | Platform adapters (Greenhouse, Lever, Shopify; C6) and API-backed pages: discovery, recipes, validation |
| [schemas](specs/schemas/spec.md) | Field types, schema documents, presets, custom schemas, prompt and field-name drafts, page kind |
| [normalization](specs/normalization/spec.md) | One normalizer per field type; decline rather than guess |
| [extraction](specs/extraction/spec.md) | Parse once, collectors, locators, ownership, listings and pagination, content formats |
| [resolution](specs/resolution/spec.md) | Validity, ownership, intent, preference, atomic offers, evidence buckets, confidence, incomplete pages |
| [variants](specs/variants/spec.md) | The variant matrix: row-mapped lists, per-variant rows, common variant fields |
| [llm](specs/llm/spec.md) | The LLM client, budgets, usage and cost, roles C, A, D and S, grounding |
| [learning-configs](specs/learning-configs/spec.md) | Config IR, learning, validation, corroboration, progressive mode, drift, exporters, release check |
| [rest-api](specs/rest-api/spec.md) | Auth, `scrape`, schemas, configs, records, replay and usage endpoints, response shapes; the MCP server |
| [jobs](specs/jobs/spec.md) | Async jobs and the queue, batch, map, crawl frontier, extract, results, events, webhooks, pinning; recurring crawls |
| [persistence-storage](specs/persistence-storage/spec.md) | Databases, data model, captures, retention, replay |
| [evaluation](specs/evaluation/spec.md) | Splits, custodian access, labels, metrics, suppression, the gate, the protected job |
| [frontend](specs/frontend/spec.md) | The web UI: shell, screens and the playground at `/` |

## Generalization contract (C1–C13)

ARCHITECTURE §2.2, verbatim. Both earlier versions worked on the sites they were tuned on and produced garbage on new
ones. These rules are binding. A change that conflicts with them is wrong, even if it fixes a site. Why:
[design/overview.md](design/overview.md) (§2.1, §2.3, §20).

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

## Repo checks

Every job in `.github/workflows/ci.yml` must pass before merge; `make check` runs them locally in CI order (without
the protected hidden-host scan), and `.pre-commit-config.yaml` runs the fast ones on staged files.

- **Path gating** — the `changes` job (`tools/ci_changes.py`) skips `backend`, `frontend` and `licenses` when a PR
  touches none of their inputs (a skipped job counts as passed); a push to `main` runs every job (D-0970).
- **Backend** — CI `backend`: `uv sync --frozen` from wheels, `ruff check` (incl. `S102`/`S307` against
  `exec`/`eval`), `ruff format --check`, strict `mypy`, `lint-imports`, `complexipy`, the Alembic
  upgrade/downgrade/upgrade round trip, and `pytest`.
- **Import contracts (C8)** — `lint-imports` with `backend/.importlinter` (one module per field type, only
  `crawlerai.normalize` imports the parsing libraries, adapters isolated); INV-08 is in
  [normalization](specs/normalization/spec.md).
- **Frontend** — CI `frontend`: `tools/theme_only_check.py`, `pnpm check` (Vite+: format, Oxlint incl. complexity,
  type-check), `pnpm test`, `pnpm build`, and `make api-client` + `git diff --exit-code` ("API client out of date").
- **Theme-only** — `tools/theme_only_check.py` fails on color literals, arbitrary Tailwind values, palette utilities,
  `style=` props, extra CSS files or non-allow-listed UI imports under `frontend/src/` (D-0356, D-0358).
- **No site literals (INV-03, INV-09)** — `tools/site_literal_scan.py --public` (CI `site-literals`, pre-commit
  `--staged`) flags hostnames and URL hosts (pinned IANA TLD list); it exempts `backend/src/crawlerai/adapters/`,
  `docs/`, `openspec/`, `.github/`, lockfiles and manifests (D-0004, D-1139); tests are not exempt, so the INV-03
  scan covers `tests/`. `tools/site_literal_allowlist.txt` holds only standards, tooling and RFC 2606/6761 names,
  each justified. Enforced by: the scan in CI and pre-commit; active.
- **Hidden-host scan (INV-04)** — runs only in `eval-protected.yml`; see
  [evaluation](specs/evaluation/spec.md).
- **Pinned external data (INV-05)** — `tools/data_manifest_check.py` (CI `data-manifest`): every file under
  `backend/data/` is listed in `backend/data/manifest.json` with its source, version, license and matching sha256;
  the dev-fitted files (`source_precedence.yaml`, `calibration.json`, `drift_margins.json`) are not pinned and carry
  `source_split: dev` instead. Enforced by: CI `data-manifest`; active.
- **Licenses** — `tools/license_scan.sh` + `tools/license_policy.py` (CI `licenses`) fail on AGPL, GPL, SSPL or
  non-commercial licenses by SPDX expression (LGPL passes) and upload CycloneDX SBOMs as `license-report`.
- **C11 size checks and no others (INV-18)** — complexity ≤ 15 per function fails (`complexipy --no-ignore`; Oxlint
  `crawlerai/cognitive-complexity`); `tools/file_length.py` only warns over 800 lines. `tools/no_size_gates.py` (CI
  `no-size-gates`) fails on any other line-count, complexity, coverage or ratchet gate. Enforced by: CI
  `no-size-gates`; active.
- **Decision IDs** — `tools/decision_ids.py` (CI `site-literals`, beside ruff, `mypy --strict` and pytest over
  `tools/`) fails when a `### D-NNNN` heading repeats across every Markdown file under `openspec/` (D-0823, D-1138).

## Invariants

The testable invariants keep their IDs `INV-01`…`INV-40` and live as requirements in their capability's `spec.md`
(INV-03, INV-05, INV-09 and INV-18 in "Repo checks" above), each with what enforces it and whether that enforcement
runs today. An invariant whose enforcement is not built yet is still binding: review applies it until the check
exists. Invariants are never removed or renumbered; a superseded one keeps a requirement that says so. A change that
adds one takes the next free ID (INV-41; check with `grep -rhoE "INV-[0-9]+" openspec/specs openspec/project.md |
sort -u | tail -1`) in its spec delta.

## Open owner items

Decisions with status `needs-owner` or `pending-owner` (`CLAUDE.md` §5). Keep this list current; the entries are in
[decisions/log.md](decisions/log.md).

| ID | Title | Status |
|---|---|---|
| D-0783 | Investigate: approving a learned config before it becomes a reusable recipe | needs-owner (owner 2026-10-16: not now) |
| D-0784 | Investigate: an "absent" field status so role C stops asking | needs-owner (owner 2026-10-16: not now) |
| D-0915 | SimHash at Hamming 0 still misses some one-word edits | needs-owner |
| D-1024 | Listing rows without structured data take no item URL | needs-owner |
