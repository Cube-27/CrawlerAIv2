# Decisions log

Agents log the decisions they make while writing specs and implementing them. Owner decisions belong in
ARCHITECTURE Appendix A; open owner questions belong in OPEN_QUESTIONS.md. What goes here and when to escalate:
`CLAUDE.md` §4–§5.
While an orchestrator runs, workers put decisions in their PR body and only the orchestrator writes this file
(`CLAUDE.md` §3).

**Statuses:**
- `decided`: made by an agent within its authority. Stands unless the owner overrides it.
- `pending-owner`: a default an agent chose that the owner should confirm. Work proceeds on it.
- `needs-owner`: blocking. Work that depends on it stops until the owner answers.
- `confirmed` / `overridden`: the owner's answer, with the date.
- `superseded`: replaced by a later entry. Link it.

**Rules:**
- Entries are append-only. To change a decision, add a new entry and mark the old one `superseded`.
- Keep each entry under about ten lines.
- No customer names and no secrets; the repo is public.

**Template:**

```
### D-NNNN — <title>
- Date: YYYY-MM-DD · Spec/PR: SPEC-NN PR M (#PR) · Status: decided | pending-owner | needs-owner
- Decision: <one or two sentences>
- Alternatives: <what else was considered>
- Why: <reason; cite ARCHITECTURE/spec sections or eval results>
- Reversible: yes | costly | no — <what reversing would take>
- Owner answer: <filled when confirmed or overridden>
```

---

## Index of open items

Items with status `needs-owner` or `pending-owner`. Keep this list current.

| ID | Title | Status |
|---|---|---|
| — | None open (answered in D-0234) | — |

---

## Entries

### D-0001 – D-0044: Decisions made while writing the specs

- Date: 2026-10-12 · Source: spec authoring (SPEC-00 … SPEC-12) and the rev 5 consistency pass.
- Status: `decided`, except D-0001, D-0012, D-0015, D-0019, D-0024 and D-0037: `confirmed 2026-10-13`
  (Owner answer: confirmed as written, D-0234). Every entry is reversible unless the
  table says otherwise. Implementation proceeds on all of them (OPEN_QUESTIONS #14).
- Decisions settled by ARCHITECTURE rev 5 are not repeated here: corroboration floor, `operator` bucket, schema
  version restarting learning, glob-expanded `extract` URLs, `error` class, robots outcome, PR-comment contents.

| ID | Spec § | Decision | Alternative | Reversible |
|---|---|---|---|---|
| D-0001 | SPEC-00 §3, §9 | LGPL dependencies are allowed but avoided (asyncpg instead of psycopg). | Add LGPL to the deny-list. | yes |
| D-0002 | SPEC-00 §4.9 | Create `docs/INVARIANTS.md` (enforced invariants) and `docs/DESIGN.md` (UI design guide); both derived from ARCHITECTURE. | Keep that content in the specs and CLAUDE.md. | yes |
| D-0003 | SPEC-00 §4.2–4.3 | Toolchain: uv, ruff, mypy --strict, SQLAlchemy 2 async + asyncpg, Alembic, pnpm, ESLint 9 + Prettier, react-router, openapi-typescript/openapi-fetch + TanStack Query, HeroUI v3.2.x, Vitest, `make`. | poetry, pyright, psycopg, npm, other clients. | yes, with churn |
| D-0004 | SPEC-00 §4.7 | The public site-literal scan exempts `docs/**` and lockfiles. | Scan docs too. | yes |
| D-0005 | SPEC-01 §4.2 | IDs are UUIDv7; money is `numeric(18,6)`; enums are text + CHECK. | Native enums, bigint IDs. | costly once data exists |
| D-0006 | SPEC-01 §4.3 | 10-minute lease; 3 retries, backoff from 30 s; a job fails only if every task fails. | Other values. | yes |
| D-0007 | SPEC-01 §4.7 | `ENGINE_VERSION` = git sha + calibration hash. | Semver. | yes |
| D-0008 | SPEC-02 §4.3 | Shell = < 200 visible chars and < 5 links; to be confirmed on dev. | Other thresholds. | yes |
| D-0009 | SPEC-02 §4.4 | Browser fallback only on `shell`/`blocked`; HTTP re-checked every 7 days. | Other cadence. | yes |
| D-0010 | SPEC-02 §4.6, §4.8 | Rate limiter is per process. The browser stores rendered and raw bodies; JSON capture capped at 2 MB × 50 bodies. | Shared limiter; rendered body only. | yes |
| D-0011 | SPEC-02 §4.9 | Adapters ship inactive until measured on ≥ 3 tenants (C6). | Ship active. | yes |
| D-0012 | SPEC-03 §4.10 | The labeling iframe loads images from live sites. | Strip `src`, show captured images only. | yes |
| D-0013 | SPEC-03 §1, §4.5 | Labeling tool lives in SPEC-03 (L0) as a frontend screen behind `CRAWLERAI_EVAL_UI`; `eval_page.config_snapshot` measures config fields. | Separate tool; separate table. | yes |
| D-0014 | SPEC-03 §4.8 | The gate also fails if the hidden `n_pages` drops; the first run passes as `no_baseline`. | No page-count rule. | yes |
| D-0015 | SPEC-04 §4.2 | `apply_url` maps to `JobPosting.url`. | A custom mapping (e.g. `potentialAction`). | yes |
| D-0016 | SPEC-04 §4.1 | `long_text` lives in the `text` module, `image_url` in `url`, `datetime` in `date`. | Separate modules. | yes |
| D-0017 | SPEC-04 §4.4 | Text max 512, long_text max 100k; years 1970–2100; first vocabularies are schema.org-derived, `en` only. | Other bounds. | yes |
| D-0018 | SPEC-04 §4.6 | The schema.org vocabulary file (CC BY-SA) is used as pinned data. | Hand-typed members. | yes |
| D-0019 | SPEC-05 §4.8 | The only derivations are canonical/final URL → `url` and absolutize. | None at all. | yes |
| D-0020 | SPEC-05 §4.6–4.7 | Intent rules as specified; cold listings need ≥ 3 top-level entities; initial `source_precedence` order (refit on dev). | Other rules. | yes |
| D-0021 | SPEC-05 §4.9 | Bucket priority adapter > agreed > structured. | Other order. | yes |
| D-0022 | SPEC-05 §4.10 | `partial` records are stored as well as returned. | Return only. | yes |
| D-0023 | SPEC-06 §2 | Providers: Anthropic + Gemini; temperature 0; one retry, failover once (OPEN_QUESTIONS #5 default). | Other providers. | yes |
| D-0024 | SPEC-06 §4.3 | Model-reported offsets are corrected by exact-match search, never fuzzy matching. | Drop on any offset mismatch. | yes |
| D-0025 | SPEC-06 §4.4 | Role C input truncated at 40k (detail) / 80k (listing) chars, ≤ 200 rows; missing optional fields ride along in the same call. | Required fields only. | yes |
| D-0026 | SPEC-06 §4.5 | Role S drafts are named `draft_<hash12>`; editing one creates a `user` schema. | Other naming. | yes |
| D-0027 | SPEC-07 §4.2 | API keys: `ck_` + base62, sha256-hashed; rate limit 20 req/s, burst 40. | argon2; other limits. | yes |
| D-0028 | SPEC-07 §4.4 | Sync `scrape` runs inline in the API process; timeout 60 s default, 120 s max. | Through the queue. | yes |
| D-0029 | SPEC-07 §4.6 | Replay never calls an LLM unless `allow_llm`; schema DELETE means retire. | Other behaviour. | yes |
| D-0030 | SPEC-08 §4.4 | Learning sample = the 5 pages with the most required fields; a failed learn retries after 8 more pages. | Random sample. | yes |
| D-0031 | SPEC-08 §4.5 | Stable class token = no digit run of 3 or more. | Other rule. | yes |
| D-0032 | SPEC-08 §4.9 | Drift window 50 pages; margins yield 0.2 and validity 0.1 until fitted on dev. | Other values. | yes |
| D-0033 | SPEC-08 §4.10–4.11 | An operator PUT creates a new validated config version; `platform_draft` exports carry `draft: true`. | Edit in place. | yes |
| D-0034 | SPEC-08 §4.2 | XPath 1.0 enforced by a function-name allowlist; regex limited to a PCRE-compatible subset. | Other checks. | yes |
| D-0035 | SPEC-09 §4.3–4.6 | One endpoint per config; recipes needing tokens, Cookie or Authorization are not learnable; two-request path when a binder needs the page. | Multi-endpoint recipes. | yes |
| D-0036 | SPEC-10 §4.1 | Canonicalization drops no query parameters (no `utm_*` list, C4). | Strip by list. | yes |
| D-0037 | SPEC-10 §9 | `map`/`crawl` scope is the exact host; subdomains need explicit `include` globs. | Registrable domain. | yes |
| D-0038 | SPEC-10 §4.2–4.7 | HMAC webhook secret per API key; batch ≤ 1000 URLs; map limit 5000; MCP markdown pages of 20k chars. | Other values. | yes |
| D-0039 | SPEC-11 §4.3 | Nonce = opaque token of ≥ 16 chars; SimHash over word 3-grams with blake2b; to be confirmed on dev. | Other values. | yes |
| D-0040 | SPEC-11 §4.2–4.4 | A 304 stores no capture; an equal record fingerprint inserts no record. | Always insert. | yes |
| D-0041 | SPEC-12 §4.1 | SSE read via `fetch` streaming; downloads via authenticated fetch; the API key is lost on reload (§18). | Key in sessionStorage (contradicts §18). | yes |
| D-0042 | SPEC-12 §2 | Screen set derived from §13.1 + C5; `/healthz.eval_ui` flag. | Other screens. | yes |
| D-0043 | SPEC-03 §4.9, SPEC-00 §4.6 | The protected eval job uploads no artifacts and prints only pass/fail; the numeric aggregate is written to the private store (public repo). | Upload the aggregate as an artifact (public in a public repo). | yes |
| D-0044 | `.gitignore`, CLAUDE.md | Agent worktrees live under `.worktrees/` or `.claude/worktrees/`, ignored by git. Superseded by D-0045. | Elsewhere. | yes |

### D-0045 — Agent worktrees live outside the repo
- Date: 2026-10-12 · Spec/PR: tooling (skills `implement-pr`, `pickup`) · Status: decided (owner direction)
- Decision: Worktrees go in `CrawlerAIv2-worktrees/<name>`, a directory beside the main checkout (the first entry of `git worktree list`), never inside the repo. Supersedes D-0044.
- Alternatives: `.worktrees/` inside the repo, ignored by git (D-0044).
- Why: The owner ruled that worktrees cannot be inside the repo.
- Reversible: yes. Change the path in the two skills.

### D-0046 — CLI uses stdlib `argparse`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: `crawlerai` is built on `argparse`, not Typer or Click.
- Alternatives: Typer (MIT), Click (BSD).
- Why: There is one flag today. No dependency until subcommands need one.
- Reversible: yes

### D-0047 — Settings shape
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: `database_url` and `object_store` are required. The two database URLs are `SecretStr`. Object stores must match `fs:///<abs>` or `s3://<bucket>[/<prefix>]`. `eval_private_*` are unset by default, `log_redact_urls` defaults to false, and `role` is optional. An empty value counts as unset (`env_ignore_empty`). No `.env` loading yet.
- Alternatives: a required `role`; plain `str` URLs; empty string as a value.
- Why: The most conservative reading of SPEC-00 §4.4. Unset CI secrets arrive as `""`.
- Reversible: yes

### D-0048 — Build backend hatchling, Python `>=3.12,<3.13`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: hatchling builds the package, and Python is pinned to `>=3.12,<3.13`.
- Alternatives: `uv_build` or setuptools; `>=3.12`.
- Why: ARCHITECTURE §19 fixes Python 3.12, and hatchling is MIT-licensed.
- Reversible: yes

### D-0049 — `NOTICE` unchanged
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
- Decision: No attributions are added. Nothing third-party is vendored, and dependency attribution comes from the SBOM in SPEC-00 PR 7.
- Alternatives: list the dependencies in `NOTICE` now.
- Why: Installed dependencies are not bundled.
- Reversible: yes

### D-0050 — CI backend job lands in SPEC-00 PR 1
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided (owner direction)
- Decision: `ci.yml` runs `uv sync --frozen`, ruff (lint and format check), `mypy src tests` and `pytest`. Actions are pinned to commit SHAs and uv to 0.11.28. Later SPEC-00 rows add `lint-imports`, the replay split, alembic and the other jobs.
- Alternatives: wait for later SPEC-00 rows to add CI.
- Why: The owner asked for the first PR to carry the setup, so CI gates every later row.
- Reversible: yes

### D-0051 — HeroUI is MIT-licensed, not Apache-2.0
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
- Decision: `@heroui/react` and `@heroui/styles` 3.2.6 declare MIT. SPEC-00 §4.3 says Apache-2.0; both are permissive, so nothing changes. The spec table is corrected in SPEC-00 PR 10.
- Alternatives: none.
- Why: Verified from the published packages.
- Reversible: yes

### D-0052 — Frontend versions pinned exactly
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: superseded by D-0226
- Decision: Exact pins: HeroUI 3.2.6, React 19.3.0, Vite 8.3.4, Tailwind 4.3.3, react-router 8.4.0, Vitest 5.0.3, TypeScript 5.9.3, ESLint 9.39.5. TypeScript stays on 5.x and ESLint on 9 for the spec's toolchain (typescript-eslint, jsx-a11y peers). Bump ESLint once jsx-a11y supports 10.
- Alternatives: `^` ranges; ESLint 10 without jsx-a11y.
- Why: Reproducible installs and the SPEC-00 §4.3 tool list.
- Reversible: yes

### D-0053 — Node 24 in CI; pnpm pinned by `packageManager`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
- Decision: CI uses Node 24 LTS; `packageManager: pnpm@11.22.0`; `engines.node >= 22`.
- Alternatives: Node 26.
- Why: The LTS line, and pnpm pinned in one place.
- Reversible: yes

### D-0054 — Theme: only an explicit choice is persisted
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
- Decision: `localStorage["crawlerai.theme"]` is written only when the viewer toggles, so a viewer who never chose follows `prefers-color-scheme`. Applied before paint. The control is a HeroUI `Switch`, "Dark theme".
- Alternatives: persist the resolved theme on first load.
- Why: The most conservative reading of SPEC-00 §4.9.
- Reversible: yes

### D-0055 — Normalize independence contract uses `crawlerai.normalize.*`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: The independence contract matches every module under `crawlerai.normalize` with a wildcard, not SPEC-00 §5's concrete list.
- Alternatives: the concrete list, extended as modules land.
- Why: import-linter errors on modules that don't exist yet. The wildcard covers new type modules automatically. A shared dispatcher inside `normalize` would need the contract narrowed in its PR.
- Reversible: yes

### D-0056 — Layers: `acquire : adapters`, all other siblings independent
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: SPEC-00 §5's `|` siblings stay independent, except acquire and adapters (`:`), because the adapters-isolated contract lets acquire import adapters. `normalize | schemas` forbids normalize→schemas; SPEC-04 relaxes it with a logged decision if needed.
- Alternatives: `|` everywhere; `:` everywhere.
- Why: The strictest reading that is consistent with the adapters contract.
- Reversible: yes

### D-0057 — Forbidden-import contracts check direct imports only
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: The normalize-libs and adapters-isolated contracts set `allow_indirect_imports = True`.
- Alternatives: check indirect chains.
- Why: With indirect checking, collect couldn't call a normalizer that uses Babel. The layers contract still covers the chains.
- Reversible: yes

### D-0058 — CI tool steps run with `uv run --no-sync --no-build`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 6 (#6) · Status: decided
- Decision: `lint-imports` runs without syncing or building, because `uv sync --frozen` earlier in the job already installed the environment.
- Alternatives: `uv run --frozen` (SonarCloud S8541); `--frozen --no-build` (fails on the editable package).
- Why: Nothing needs to be resolved or built at that step.
- Reversible: yes

### D-0059 — Site-literal scan excludes non-host dotted tokens by class
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: In Python (via `tokenize`, including `*.py.*` templates) and JS/TS files, only string literals and comments are scanned. A two-label token whose last label is a tracked file's extension is a file name. A token equal to a tracked Python module path is a module name. URL hosts are always checked.
- Alternatives: exclude TLDs that are also file extensions (drops `.ai`, `.me`, `.br`); an inline ignore pragma.
- Why: The spec's bare regex gave 95 false findings (file names, attribute access). Each rule handles a class using repo data, with no lists (C4).
- Reversible: yes

### D-0060 — Allowlist matching and justification
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: Entries starting with `.` cover the name and its subdomains; plain entries match exactly. Every entry needs a `# justification`, or the scan exits 2. RFC 2606 `.example` is included.
- Alternatives: suffix-match every entry.
- Why: The most conservative reading that still lets fixtures use any RFC 2606 subdomain.
- Reversible: yes

### D-0061 — `ghcr.io` allowlisted as a tooling host
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: GitHub's container registry is on the allowlist, like `pypi.org` and `registry.npmjs.org`.
- Alternatives: leave it for SPEC-00 PR 2 to add.
- Why: PR 2 pins a tool image from it.
- Reversible: yes

### D-0062 — Single-label URL hosts and non-global IPs are not findings
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: `localhost`, compose service names and non-global IP literals in URLs are not flagged.
- Alternatives: flag every URL host not on the allowlist.
- Why: They can't name a public site, and compose and `.env` files need them.
- Reversible: yes

### D-0063 — Data manifest schema
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: `{"entries": [{path, url, version, sha256, license, justification, …}]}`, `path` relative to `backend/data/`. A listed file that is missing fails the check. The IANA TLD list is committed (about 10 KB).
- Alternatives: fetch the TLD list in CI (needs the network, non-deterministic).
- Why: The most conservative reading of SPEC-00 §4.1. SPEC-04 PR 7 can extend it for fetched snapshots.
- Reversible: yes

### D-0064 — Tool tests live in `tools/tests/`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 5 (#5) · Status: decided
- Decision: They run through the backend uv environment; `tools/ruff.toml` extends the backend config.
- Alternatives: put them under `backend/tests/`.
- Why: The tools run as CI runs them (subprocess) and need no package of their own.
- Reversible: yes

### D-0065 — Minimal `/healthz` lands with `make dev`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `crawlerai/api/app.py` has `create_app()` with `GET /healthz` → 200 `{"status":"ok"}`. SPEC-07 PR 1 extends the factory and adds the DB ping.
- Alternatives: wait for SPEC-07; add the DB ping now.
- Why: SPEC-00 PR 2's done-when needs an API answering `/healthz`; this is the smallest shape that does.
- Reversible: yes

### D-0066 — `make dev` starts only what exists
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: compose up `--wait` → `uv sync` → `alembic upgrade head` → `uvicorn --reload`. The rows that add the worker, scheduler and `pnpm dev` also add a process runner.
- Alternatives: honcho now, with placeholders.
- Why: There's nothing else to run yet.
- Reversible: yes

### D-0067 — Local credentials and the `custodian` role
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: Compose uses throwaway passwords bound to `127.0.0.1`. `custodian` is `NOLOGIN` locally, and `.env.example` leaves `EVAL_PRIVATE_*` empty. `make dev` copies `.env.example` to `.env` if missing and exports it (Settings doesn't read `.env`, D-0047).
- Alternatives: a custodian password in the repo; `.env` loading in Settings.
- Why: No custodian credential ever exists in the repo (C1).
- Reversible: yes

### D-0068 — Alembic layout
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `backend/alembic.ini` + `backend/migrations/`. The URL comes from `DatabaseSettings` (the `database_url`-only base of `Settings`). Offline mode is refused. Revision IDs are sequential (`0001`). `target_metadata` stays `None` until SPEC-01.
- Alternatives: read the env var in `env.py`; full Settings; hex revision IDs.
- Why: One settings boundary; sequential IDs make review order obvious.
- Reversible: yes

### D-0069 — Backend Dockerfile in `infra/`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `infra/Dockerfile`, built from `backend/`: `python:3.12-slim` + uv 0.11.28, runs as non-root `crawlerai`, copies only what it runs, and its default command runs the API.
- Alternatives: leave it to a later row.
- Why: SPEC-00 §2 asks for one backend image, and the row's scope is `infra/*`.
- Reversible: yes

### D-0070 — CI and the image install dependencies from wheels only
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: superseded by D-0141
- Decision: `uv sync --frozen --no-build --no-install-project`, then `uv build --wheel` + `uv pip install --no-build --no-deps` for the project. Later steps use `uv run --no-sync --no-build`. Local dev keeps the editable sync. SonarCloud S8544 on the wheel install is a false positive (it resolves nothing).
- Alternatives: `uv sync --frozen` (builds sdist dependencies; S8541).
- Why: No third-party build script runs in CI or the image.
- Reversible: yes

### D-0071 — `crawlerai openapi` output is byte-stable JSON
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 4 (#9) · Status: decided
- Decision: `indent=2`, `sort_keys=True`, a trailing newline, written as UTF-8 bytes to stdout (no CRLF on Windows).
- Alternatives: FastAPI insertion order; an `--output` flag.
- Why: The freshness check (SPEC-00 §4.5) compares bytes; stdout keeps the spec's `> frontend/openapi.json` form.
- Reversible: yes

### D-0072 — Generated API files are excluded from Prettier
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 4 (#9) · Status: superseded by D-0226
- Decision: `openapi.json` and `src/api/schema.d.ts` are in `.prettierignore`.
- Alternatives: run Prettier inside `gen:api`.
- Why: One source of formatting keeps the freshness diff simple.
- Reversible: yes

### D-0073 — API key is optional in `createApiClient`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 4 (#9) · Status: decided
- Decision: `createApiClient({ baseUrl, apiKey? })` sends `Authorization: Bearer` only when a key is given; there is no default base URL.
- Alternatives: require a key; a base URL from the Vite env.
- Why: `/healthz` is unauthenticated; the UI holds the key in memory (ARCHITECTURE §18, SPEC-07 §4.2).
- Reversible: yes

### D-0074 — License policy script instead of `--fail-on`
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `pip-licenses` and `pnpm licenses` only collect data. `tools/license_policy.py` decides with SPDX expression semantics (OR: any clean branch; AND: all; WITH checks the exception; `+` maps to the base ID), using the same matcher for both ecosystems.
- Alternatives: `pip-licenses --fail-on` and `license-checker-rseidelsohn --failOn` as SPEC-00 §4.6 names them.
- Why: `--fail-on` matches whole strings: `MIT AND GPL-3.0-only` passes it, and trove names never match SPDX IDs.
- Reversible: yes

### D-0075 — Denied licenses also matched as trove classifiers
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: The seven PyPI trove classifiers for AGPL/GPL v2/v3, matched as whole names. LGPL is not included.
- Alternatives: SPDX IDs only (misses packages from before PEP 639); substring matching (forbidden).
- Why: The same deny-list in the standard classifier vocabulary, so not a list that grows per incident (C4).
- Reversible: yes

### D-0076 — Python license declaration precedence
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: Use `License-Expression` (PEP 639) if present. Otherwise fail if any classifier is denied. Otherwise use the `License` field.
- Alternatives: check all three; require every classifier to be denied.
- Why: PEP 639 is authoritative, and failing on any denied classifier is conservative.
- Reversible: yes

### D-0077 — Undeclared or unknown licenses don't fail the scan
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `UNKNOWN` declarations are reported in the JSON artifacts but pass.
- Alternatives: fail on unknown.
- Why: SPEC-00 defines a deny-list, not an allow-list.
- Reversible: yes

### D-0078 — Frontend licenses and SBOM come from pnpm's built-ins
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `pnpm licenses list` and `pnpm sbom --sbom-format cyclonedx`, with no new frontend dependency.
- Alternatives: `license-checker-rseidelsohn` plus `@cyclonedx/cyclonedx-npm` or `cdxgen`.
- Why: Fewer dependencies, and pnpm reads its own lockfile.
- Reversible: yes

### D-0079 — `licenses` uv dependency group
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: `pip-licenses>=5,<6` (MIT) and `cyclonedx-bom>=7,<8` (Apache-2.0, verified) live in their own group. The scan syncs `--all-groups` and runs `pip-licenses --with-system`, so the scan tools are checked too.
- Alternatives: put them in `dev`.
- Why: The backend job doesn't install about 30 extra packages.
- Reversible: yes

### D-0080 — The project itself is excluded from the license scan
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 7 (#7) · Status: decided
- Decision: The scan syncs with `--no-install-project`.
- Alternatives: scan the project too.
- Why: The project is AGPL-3.0 (LICENSE); the deny-list applies to dependencies.
- Reversible: yes

### D-0081 — A missing hidden-host list passes visibly
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 8 (#8) · Status: decided
- Decision: An unset or empty list prints `hidden-hosts: pass, no host list configured`. SPEC-03 can make a missing list fail once H2 is done.
- Alternatives: fail when the secret is missing.
- Why: SPEC-00 §4.6: the job must pass until milestone M; the line makes the skip visible.
- Reversible: yes

### D-0082 — Hidden-host scan tokenizes on `[a-z0-9.-]` and redacts by substring
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 8 (#8) · Status: decided
- Decision: Each `[a-z0-9.-]` run in a file or path is looked up case-insensitively against the host set, by every run of its labels, so `_` and every other character separate tokens. A path naming a host is reported as `path:0`. Printed paths have every case-insensitive occurrence of every host replaced with `[hidden]`, independent of tokenizing.
- Alternatives: a regex alternation over all hosts for content (7.2 s/MB at 3,000 hosts vs 0.25 s/MB); `DOTTED`'s `\w` boundaries (leaked a host through `_` in review round 1).
- Why: The most conservative reading of C1/C3: redaction by substring can't leak through a tokenizing gap.
- Reversible: yes

### D-0083 — The hidden-host list is split leniently
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 8 (#8) · Status: decided
- Decision: The secret is split on whitespace and commas, lowercased, with leading and trailing dots stripped.
- Alternatives: one host per line only.
- Why: Tolerant of how the custodian pastes it; it doesn't change what is printed.
- Reversible: yes

### D-0084 — No-size-gates is a tested script covering tool configs
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: decided
- Decision: `tools/no_size_gates.py` (stdlib) scans workflows, `.pre-commit-config.yaml`, `Makefile` and the configs of the tools they run (pyproject, ruff, package.json, ESLint/Vite/Vitest) for line-count tools, size or complexity limits (mccabe/`C901`, pylint `PLR09`, ESLint `max-*`/`complexity`) and coverage thresholds.
- Alternatives: the spec's one-line grep over workflows and hooks.
- Why: An inline grep matches its own patterns, and a gate can be switched on in a tool config just as easily (C11).
- Reversible: yes

### D-0085 — INVARIANTS.md has a Status column
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: decided
- Decision: Each invariant says whether its enforcement runs today (`active`) or which spec adds it.
- Alternatives: the four spec columns only.
- Why: Docs make no claim a check doesn't back (CLAUDE.md §6).
- Reversible: yes

### D-0086 — Escalations copy `needs-owner` entries to OPEN_QUESTIONS.md
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: confirmed 2026-10-13
- Decision: CLAUDE.md §5 step 1: the escalation writer copies the `needs-owner` entry as a row in `OPEN_QUESTIONS.md`. This is the only agent edit to that file without owner approval.
- Alternatives: the owner copies them.
- Why: SPEC-00 §4.9 item 13 and OPEN_QUESTIONS.md's own text require the copy; CLAUDE.md §6 otherwise reserves the file to the owner.
- Reversible: yes
- Owner answer: confirmed as written (D-0234).

### D-0087 — SPEC-00 §4.3 HeroUI row corrected (clarifying edit)
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 10 (#10) · Status: decided
- Decision: `@heroui/react` and `@heroui/styles` 3.2.6, MIT, per D-0051.
- Alternatives: none.
- Why: Matches the published packages; no architecture change.
- Reversible: yes

### D-0088 — UUIDv7 generated in-repo
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `crawlerai.core.ids.uuid7()` implements RFC 9562 §5.7, because Python 3.12 has no `uuid.uuid7`.
- Alternatives: a third-party UUIDv7 package.
- Why: About ten tested lines and no dependency. Switch to the stdlib on Python 3.14.
- Reversible: yes

### D-0089 — `project.name` is UNIQUE
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: The `default` project is found by name; its ID is a v7 generated in the migration.
- Alternatives: a fixed well-known UUID.
- Why: Keeps SPEC-01 §4.2's v7 IDs.
- Reversible: yes

### D-0090 — `site.fetch_method` defaults to `http`
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: A new site starts at the `http` rung (server default).
- Alternatives: no default.
- Why: ARCHITECTURE §7.1: HTTP is the default rung, and `fetch_method` is then recorded from evidence.
- Reversible: yes

### D-0091 — Column shapes left open by ARCHITECTURE §6
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `site.robots_snapshot` is nullable text; `site.crawl_delay_ms` is a nullable int ≥ 0; `api_key.hashed_key` is unique text; `api_key.webhook_secret` is NOT NULL; `schema_def` has UNIQUE (`name`, `version`), `version >= 1`, and `required_groups` defaults to `[]`.
- Alternatives: a jsonb robots snapshot; a nullable webhook secret.
- Why: The most conservative reading. SPEC-02 can add parsed robots columns.
- Reversible: yes

### D-0092 — DB tests skip without a database URL; CI always runs them
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `tests/db` skips when `CRAWLERAI_DATABASE_URL` is unset. CI sets it and runs pytest after the migration round trip, using the `anyio` plugin.
- Alternatives: pytest-asyncio; fail without a DB.
- Why: No new dependency, and the tests always run in CI.
- Reversible: yes

### D-0093 — Foreign keys reference columns, not `"table.column"` strings
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `ForeignKey(Project.id)` and `project.c.id`.
- Alternatives: allowlist `project.id` in the C3 scanner.
- Why: The scan reads `"project.id"` as a host (`.id` is a TLD). See the follow-up in ACTIVE.md.
- Reversible: yes

### D-0094 — `ObjectStore` methods are synchronous
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: `ObjectStore` methods are plain sync calls; async callers run them in a thread (`asyncio.to_thread`).
- Alternatives: An async protocol over aioboto3/aiofiles.
- Why: boto3 is sync; an async S3 client adds a dependency for 10k pages/day (§19 sizing).
- Reversible: yes, before SPEC-02 PR 3 has callers

### D-0095 — S3 endpoint and credentials come from boto3's standard configuration
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: No `CRAWLERAI_*` S3 settings; `AWS_ENDPOINT_URL`, credentials and region come from the AWS environment/config chain, which covers S3-compatible stores (§15).
- Alternatives: `CRAWLERAI_S3_ENDPOINT` and similar settings.
- Why: boto3 already reads them.
- Reversible: yes

### D-0096 — Object key rules
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: Keys are relative `/`-separated paths with non-empty segments that don't start with `.` and contain no `\` or NUL; otherwise `ValueError`. `list(prefix)` is a string-prefix match returning sorted keys; deleting a missing key is a no-op.
- Alternatives: Backend-specific rules; raising on a missing delete.
- Why: One key means one object on both backends (no `..` escape from an `fs` root; dot-files reserved for in-progress `fs` writes); retention stays idempotent.
- Reversible: yes

### D-0097 — Bundle manifest shapes the spec leaves open
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: Headers are ordered `[name, value]` lists (RFC 9110 §5.3 allows repeats); `timings_ms` is `dict[str, int]`; `fetch_policy` is a JSON object; `content_type` may be null; models forbid extra keys. `CaptureBundle.network` is a tuple of bytes aligned by index with `manifest.network_bodies`. The bundle validates `html_sha256`, per-body `sha256`, `network/NNNN.json` naming, and that only browser captures carry network bodies; `decode` turns any mismatch into `CorruptBundle`.
- Alternatives: Header dicts (lose repeats); `NetworkBody` carrying its bytes.
- Why: Most conservative reading of §4.5 "as received" and "round-trip exactly"; inconsistent bundles can't be represented.
- Reversible: before captures exist; after, needs `bundle_version: 2`

### D-0098 — `zstandard` for zstd
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: `zstandard` (BSD-3). Python 3.12 has no stdlib zstd.
- Alternatives: `pyzstd` (BSD-3).
- Why: Widely used, licence-clean, typed.
- Reversible: yes; the format is standard zstd

### D-0099 — Job and task transition tables
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: Job: `queued→{running, cancelled}`, `running→{completed, failed, cancelled}`. Task: `queued→{claimed, cancelled}`, `claimed→{queued, done, failed, cancelled}`. Terminal states have no exits. `claimed→queued` covers retry and expired lease (§4.3); a requeue clears `claimed_by` and `lease_until`, a terminal transition keeps `claimed_by`.
- Alternatives: `queued→completed` for empty jobs; `queued→failed`.
- Why: The smallest graph that covers §4.3 and SPEC-10 §4.2.
- Reversible: yes

### D-0100 — `settled_status` rules
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: A job does not settle while any task is `claimed`. With `cancel_requested` it ends `cancelled` and its queued tasks are not run (SPEC-10 §4.2). Otherwise it ends once nothing is queued: `failed` only if every task failed (D-0006), else `completed`. A job with no tasks completes.
- Alternatives: An empty job fails.
- Why: Nothing failed in an empty job.
- Reversible: yes

### D-0101 — Ending a job records its event in the same transaction
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: `transition_job` to a terminal status inserts `job_event(kind=<status>, payload={})`.
- Alternatives: Callers emit the event themselves.
- Why: One writer; the status and the event cannot diverge (§4.3).
- Reversible: yes

### D-0102 — `job_event.kind` is free text
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: No CHECK constraint.
- Alternatives: A CHECK on SPEC-10 §4.2's kinds.
- Why: SPEC-01 §4.2 doesn't list it among the enumerations, and later specs add kinds.
- Reversible: yes

### D-0103 — Monotonic `uuid7()`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: Within one process, `rand_a` is a 12-bit counter starting at a random value in its lower half; on overflow or clock regression the timestamp advances (RFC 9562 §6.2). Ordering across processes is not guaranteed.
- Alternatives: `job_event.id` as a bigint identity (deviates from §4.2 "ids are uuid"); order by `ts`.
- Why: SPEC-10 orders `job_event` by id for SSE resume.
- Reversible: yes

### D-0104 — Self-referencing FK spelled via `__tablename__`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: `ForeignKey(f"{__tablename__}.id")` for `url_task.parent_task_id`, and `op.create_foreign_key(..., ["id"])` in the migration.
- Alternatives: Fix the C3 scanner in this row.
- Why: The scan reads `"url_task.id"` as a host: the D-0093 class recurring. The scanner fix is a follow-up in ACTIVE.md.
- Reversible: yes

### D-0105 — Hypothesis as a dev dependency
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: `hypothesis` (MPL-2.0, not on the deny-list) for property tests.
- Alternatives: Hand-written generators.
- Why: ENGINEERING and SPEC-01 §6 prescribe property tests.
- Reversible: yes

### D-0106 — Pre-commit tool hooks are `repo: local`
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: The ruff, prettier and eslint hooks run the versions pinned in `backend/uv.lock` and `frontend/pnpm-lock.yaml`.
- Alternatives: `ruff-pre-commit` and `mirrors-prettier` pinned in the config.
- Why: One version source per tool, so hooks can't drift from CI.
- Reversible: yes

### D-0107 — `--staged` scans the index
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: `--staged` is a flag of the scanner's public mode and reads index content (`git show :path`), not a list of file paths.
- Alternatives: Pass filenames and read the working tree.
- Why: §4.8 names `--staged`; reading the index scans exactly what gets committed.
- Reversible: yes

### D-0108 — `make check` round-trips migrations on a scratch database
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: `check-migrations` runs upgrade, downgrade, upgrade on a scratch `crawlerai_check` database recreated each run, and backend tests run against it, not the dev database.
- Alternatives: Use `crawlerai`, as CI does on its throwaway service.
- Why: `downgrade base` would wipe local dev data on every `make check`.
- Reversible: yes

### D-0109 — `make check` leaves out the protected hidden-host scan
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: decided
- Decision: The hidden-host scan runs only in the protected CI job.
- Alternatives: Run it with an empty `HIDDEN_HOSTS`.
- Why: C1: its input exists only in the custodian environment; without it the scan is a pass-through.
- Reversible: yes

### D-0110 — eslint pre-commit hook exceeds the 10 s budget on Windows
- Date: 2026-10-13 · Spec/PR: SPEC-00 PR 9 (#12) · Status: superseded by D-0227
- Question: the eslint hook takes 10.6–17.4 s for a one-file frontend change on the Windows dev host (5–6 s warm on Linux), against SPEC-00 §4.8's < 10 s budget. Which wins?
- Options: (a) keep type-aware eslint in the hook and accept the Windows overage; (b) drop type-aware rules from the hook, keeping the full lint in `make check` and CI; (c) revisit the frontend lint config (`projectService`, HeroUI type depth) in a frontend row.
- Recommendation: (a) now, since hooks are not weakened; consider (c) later.
- Blocked: nothing. Python-file commits take about 2 s.

### D-0111 — The C3 scan reads schema-defined `table.column` strings as columns
- Date: 2026-10-13 · Spec/PR: SPEC-00 §4.7 follow-up (#15) · Status: decided
- Decision: `table.column` is a column reference, not a host, only when the repository's schema (Alembic ops, `Table`, declarative models in tracked Python files) defines both the table and the column.
- Alternatives: allowlist table names (C4); exempt any `identifier.identifier` in Python strings (hides real two-label hosts); treat `_`-adjacent tokens as identifiers.
- Why: structural and derived from the repo, like the file-extension and module-path rules; a host escapes only if a table and column with exactly its two labels exist in the schema.
- Reversible: yes

### D-0112 — Visible text counts non-whitespace characters of `<body>`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Count non-whitespace code points in the body text after stripping the four excluded elements; `<title>` is not counted.
- Alternatives: Collapsed-whitespace length including separators.
- Why: §4.3 says "< 200 characters of visible text" without defining characters; this count doesn't depend on how text nodes are joined.
- Reversible: yes

### D-0113 — The shell rule applies only to HTML responses
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Shell applies when the last `Content-Type` is `text/html` or `application/xhtml+xml`, or absent (browsers sniff).
- Alternatives: Apply to every 2xx body.
- Why: A small JSON body is complete, not an unrendered page.
- Reversible: yes

### D-0114 — A 3xx reaching `classify` is `ok`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Redirects are followed by the fetcher, which sets too many redirects as `error`.
- Alternatives: Classify 3xx as an error.
- Why: The classify table covers final responses only.
- Reversible: yes

### D-0115 — `is_public` follows the IANA special-purpose registries and rejects reserved IPv6
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: `ipaddress.is_global` and not multicast, recursing into IPv4-mapped and NAT64 (RFC 6052) embedded IPv4. Any other IPv6 in an IANA-reserved block (`is_reserved`, e.g. `::/8` holding the deprecated IPv4-compatible `::/96`, RFC 4291 §2.5.5.1) is rejected.
- Alternatives: Unwrap `::/96` like mapped addresses.
- Why: `is_global` (RFC 6890) is a superset of §4.5's ranges, and some stacks route `::/96` to the embedded IPv4. Fails closed.
- Reversible: yes

### D-0116 — A host that can't be IDNA-encoded is rejected as `host`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: `UnicodeError` from resolution maps to `SsrfRejected("host")`.
- Alternatives: Let it surface as a generic exception.
- Why: Keeps the §4.11 error `ssrf_rejected`.
- Reversible: yes

### D-0117 — Non-dotted-quad IPv4 host forms are rejected
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Hosts that WHATWG parses as IPv4 but aren't dotted quads (`2130706433`, `0x7f.1`, `127.1`) are rejected as `host`.
- Alternatives: Normalize them to an address and check it.
- Why: curl and browsers resolve them to loopback but a stub resolver doesn't; rejecting keeps the checked address equal to the connected one.
- Reversible: yes

### D-0118 — HTML parser: selectolax (lexbor)
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: `selectolax` (MIT).
- Alternatives: stdlib `html.parser` (no HTML5 tree building).
- Why: ARCHITECTURE §19 names it for HTML.
- Reversible: yes

### D-0119 — Handlers take a `ClaimedTask` snapshot and an `AsyncConnection`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: `TaskHandler = Callable[[ClaimedTask, AsyncConnection], Awaitable[TaskResult]]`; `ClaimedTask` is a frozen dataclass of the claimed row.
- Alternatives: The ORM `UrlTask` and an `AsyncSession`, as §4.3 sketches.
- Why: `db.jobs` works on `AsyncConnection`; an ORM instance expires on rollback, exactly when the worker needs it to record the failure.
- Reversible: yes, until handlers exist

### D-0120 — Task status follows outcome
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: `Finished(outcome)` with any outcome but `failed` ends the task `done`; `Failed` ends it `failed` or requeues it. `TaskOutcome = Literal[FinishedOutcome, "failed"]`.
- Alternatives: `blocked`/`not_found` as status `failed`.
- Why: D-0006 counts tasks that errored, not pages that were blocked or missing (§4.3).
- Reversible: yes

### D-0121 — Handler exceptions are transient
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: An uncaught exception requeues the task with backoff (at most 3 attempts); a missing handler for a job kind fails the task at once.
- Alternatives: Treat exceptions as permanent.
- Why: DB blips and network errors surface as exceptions; retrying a bug costs at most two attempts.
- Reversible: yes

### D-0122 — Claims are fenced by (`claimed_by`, `attempts`); one transaction per task
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: Finishing updates require the claim's worker and attempt count; a mismatch raises `LeaseLost` and the handler's writes roll back. A release gives back the attempt, so the fence holds only while released snapshots are discarded (follow-up in ACTIVE.md).
- Alternatives: Fence on `claimed_by` only; commit handler writes separately.
- Why: A lost lease must not let two runs both record a result (§4.3).
- Reversible: yes

### D-0123 — The claim starts the job; settling locks the job row
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: `claim_tasks` moves claimed tasks' `queued` jobs to `running`. Finishing a task locks its job row (`FOR UPDATE`), skips settling while an open task remains, then applies `settled_status`; a job no longer `running` is left alone.
- Alternatives: Settle without a lock.
- Why: Exactly one worker ends each job (§4.3).
- Reversible: yes

### D-0124 — Worker constants
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: Claim batch 10; idle poll 1 s; `last_error` cut to 2048 UTF-8 bytes on a character boundary; URLs (RFC 3986 scheme + `://`) become `<url>` when `log_redact_urls` is set. On stop, unstarted claimed tasks are requeued with their attempt given back.
- Alternatives: Batch 1; leave unstarted tasks to lease expiry.
- Why: §19 sizing makes batch size uncritical; a clean stop shouldn't strand tasks.
- Reversible: yes

### D-0125 — `url_task` UNIQUE (`job_id`, `canonical_url`) and a partial index on open tasks
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: Migration 0004 adds both; no separate `job_id` index, since the UNIQUE's index leads with it.
- Alternatives: Leave the UNIQUE to SPEC-10.
- Why: SPEC-10 §4 needs the UNIQUE; the partial index keeps settling O(log n) per task (10k test: 268 s → ~80 s).
- Reversible: yes

### D-0126 — `fetch_http` takes the engine version and browser profile from the caller
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: `fetch_http(url, policy, *, engine_version, impersonate, connector=None)`.
- Alternatives: Read `core.engine_version`; give `impersonate` a default.
- Why: `ENGINE_VERSION` arrives in SPEC-01 PR 7; with no default, `settings.impersonate` stays the only source of the profile.
- Reversible: yes

### D-0127 — Outcomes without a status line, and error bodies
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: No response status line (SSRF rejection of the first URL, connection failure, budget spent) gives manifest `status_code=0` and `AttemptRecord.status=None`. Every `error` outcome stores an empty body but keeps the last response's status and headers.
- Alternatives: Make `status_code` optional in the bundle format; keep partial bodies.
- Why: Leaves the SPEC-01 bundle format unchanged; an error yields no records (INV-11), and a truncated body would mislead replays.
- Reversible: yes

### D-0128 — Fetch error reasons never include the URL
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: Reasons are `timeout`, `body_cap`, `decode_error`, `too_many_redirects`, `ssrf_rejected: <reason>` and `network_error: curl <code>`.
- Alternatives: curl's message text.
- Why: curl messages contain host names; §4.11 redaction.
- Reversible: yes

### D-0129 — Connections are pinned with a wildcard `CURLOPT_RESOLVE`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: `CURLOPT_RESOLVE "*:<port>:<ip>"`.
- Alternatives: A per-host entry; `CURLOPT_CONNECT_TO`.
- Why: A per-host entry silently falls back to DNS when curl's form of the host (IDNA, percent-decoding, trailing dot) differs from the guard's.
- Reversible: yes

### D-0130 — `CRAWLERAI_IMPERSONATE` is typed as curl_cffi's `BrowserTypeLiteral`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: Default `chrome150`.
- Alternatives: A free string.
- Why: An unknown profile fails when settings load, not on the first fetch.
- Reversible: yes

### D-0131 — An expired lease is a transient failure of its attempt
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: `release_expired_leases` runs `fail_task(..., "lease expired", transient=True)` on each expired claim: requeued with backoff while `attempts < MAX_ATTEMPTS`, else failed and the job settled.
- Alternatives: Requeue unconditionally and immediately (the spec's literal "requeues").
- Why: A task that kills or hangs its worker every time would otherwise be requeued forever; §4.3 caps transient retries at 3.
- Reversible: yes

### D-0132 — Claims are fenced by (`claimed_by`, `lease_until`), with `lease_until` from `clock_timestamp()`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: `ClaimedTask` carries `lease_until`; finishing requires both to match. The claim sets `lease_until = clock_timestamp() + LEASE`, so two claims of a task never share it. Supersedes the fence in D-0122. SPEC-01 §4.3's claim SQL is updated to match (clarifying edit).
- Alternatives: A claim-token column (needs a migration); stop `release_task` giving the attempt back (changes D-0124).
- Why: (`claimed_by`, `attempts`) was not unique once `release_task` decrements `attempts`. A future lease heartbeat must update the holder's `ClaimedTask` too.
- Reversible: yes

### D-0133 — DB tests use a dedicated `CRAWLERAI_TEST_DATABASE_URL`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: `tests/db` reads only `CRAWLERAI_TEST_DATABASE_URL` (skipped when unset) and migrates it; CI sets it to its service DB, `make check` to `crawlerai_check`. Updates D-0092.
- Alternatives: Scope the cleanup to the test's own jobs.
- Why: `claim_tasks` and the worker loop take every due task in the database, so tests against a dev DB would run its tasks. Test-only, not a `Settings` field.
- Reversible: yes

### D-0134 — The scheduler logs and survives a failing entry
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: Each entry runs in its own transaction; an exception rolls back, is logged with its traceback, and the entry runs again at its next interval. Next run = end of previous run + interval.
- Alternatives: Let the error end the process (§4.8), relying on a restart policy.
- Why: One entry's failure shouldn't stop the others; a fresh pooled connection per run recovers from a dropped connection.
- Reversible: yes

### D-0135 — A DB error while recording a task failure ends the worker
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: Documented in `worker/loop.py`: `run_worker` raises and the process exits; its claimed tasks return through `release_expired_leases`.
- Alternatives: Catch and continue (the connection is usually gone).
- Why: §4.8; the scheduler recovers the tasks.
- Reversible: yes

### D-0136 — (`schema_id`, `schema_version`) is a composite FK to `schema_def (id, version)`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: `record`, `extraction_config` and `progressive_state` reference `schema_def (id, version)`, which gets `UNIQUE (id, version)`; no separate FK on `schema_id` alone.
- Alternatives: An FK on `schema_id` alone, with `schema_version` unchecked.
- Why: A `schema_def` row is one version, so the pair could otherwise disagree (§5.2).
- Reversible: yes

### D-0137 — Expiring a capture keeps its task and extraction
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: `url_task.capture_id` and `extraction.capture_id` are nullable, `ON DELETE SET NULL`, and indexed.
- Alternatives: NOT NULL with `ON DELETE CASCADE` (deletes extractions that records cite); a plain FK (blocks `expire_captures`).
- Why: Production captures expire after 30 days (§15); extractions and records are kept.
- Reversible: yes

### D-0138 — Column shapes left open by §6
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: Most conservative reading: `capture.status_code`, `final_url`, `html_sha256` NOT NULL as in the bundle manifest; `expires_at` nullable; `object_key` UNIQUE; `candidate.raw_value` jsonb NOT NULL, `normalized_value` nullable; `record.version` ≥ 1 default 1, `changed_fields` jsonb `[]`, `fingerprint` nullable until SPEC-11; `url_state` PK (`site_id`, `canonical_url`), `last_modified` text as received (RFC 9110 §13.1.3); `progressive_state` PK (`site_id`, `schema_id`, `schema_version`, `page_kind`) starting `cold`; `extraction_config` UNIQUE (`site_id`, `schema_id`, `page_kind`, `version`), status default `draft`. Full list in #20.
- Alternatives: A bigint SimHash `content_fingerprint`; a timestamptz `last_modified`.
- Why: SPEC-11 can tighten the fingerprint type when it computes one.
- Reversible: yes, before data exists

### D-0139 — Extra indexes beyond §4.2
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: `ix_capture_expires_at` (partial) and `ix_candidate_created_at` for retention; `ix_url_task_capture_id` and `ix_extraction_capture_id` for `SET NULL` on capture delete; `ix_candidate_extraction_id` for reading an extraction's candidates.
- Alternatives: Add them with the retention PR (8).
- Why: Each serves a query this spec defines (§4.3 scheduler entries, §6 retention).
- Reversible: yes

### D-0140 — `CaptureMethod`/`BlockClass` live in `crawlerai.core.capture`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: Moved from `storage.capture_bundle`; `storage`, `acquire` and `db` import them from `core`.
- Alternatives: Duplicate the Literals in `db.models`.
- Why: The layering contract keeps `db` and `storage` independent; one definition keeps the CHECK and the bundle in sync.
- Reversible: yes

### D-0141 — One locked `uv sync` installs CI and the image
- Date: 2026-10-13 · Spec/PR: SPEC-00 follow-up (#21) · Status: decided
- Decision: `uv sync --frozen --no-build --no-binary-package crawlerai --no-editable` (`--no-dev` in the image) replaces D-0070's `--no-install-project` + `uv build` + `uv pip install`. Only the project is built from source; every dependency stays wheel-only from `uv.lock`. Later steps still use `uv run --no-sync --no-build`.
- Alternatives: keep D-0070's commands and mark SonarCloud S8544 as a false positive.
- Why: Same property as D-0070 (no third-party build script runs), and every install now comes from the lockfile, which clears S8544 in code.
- Reversible: yes

### D-0142 — The site-literal scan's allowlist must lie inside `--root`
- Date: 2026-10-13 · Spec/PR: SPEC-00 follow-up (#21) · Status: decided
- Decision: the default allowlist is `<root>/tools/site_literal_allowlist.txt`; an explicit `--allowlist` must resolve inside `--root`, else `UsageError`.
- Alternatives: read any path given (SonarCloud S8707).
- Why: The scanned repository is the natural base; default CI and hook runs are unchanged.
- Reversible: yes

### D-0143 — `crawlerai fetch` passes the package version as engine version until SPEC-01 PR 7
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: `fetch_http`/`store_capture` take the engine version as a parameter; the CLI passes `version("crawlerai")` until PR 7 replaces it.
- Alternatives: Wait for PR 7.
- Why: PR 7 was in flight. Bundles from the CLI before PR 7 carry `0.1.0`.
- Reversible: yes

### D-0144 — `store_capture` writes the object before the row
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: The object is written first, and the row is inserted after it in the caller's transaction, so a row never names a missing bundle.
- Alternatives: Insert the row first.
- Why: A failed insert leaves only an unreferenced object, which an orphan sweep could remove if one is ever measured to be needed; `expire_captures` deletes by row.
- Reversible: yes

### D-0145 — No `CURLINFO_PRIMARY_IP` check
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: Not added.
- Alternatives: Compare the connected address with the checked one after each response (#18 follow-up).
- Why: `CURLOPT_RESOLVE "*:port:ip"` also overrides literal-IP URLs, so curl can't connect anywhere else; the check could never fire or be tested.
- Reversible: yes

### D-0146 — `crawlerai fetch --out` must lie under the working directory
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: `--out` is resolved and rejected (exit 2) unless it lies under the working directory.
- Alternatives: Write anywhere (SonarCloud S8707).
- Why: Same shape as D-0142.
- Reversible: yes

### D-0147 — `crawlerai fetch` exits 0 whenever a bundle is written
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: Including an `error` outcome; the outcome is reported in the JSON summary's `block_class` and `error`.
- Alternatives: Non-zero exit on an `error` outcome.
- Why: The outcome is data, not a CLI failure.
- Reversible: yes

### D-0148 — `usage_event` column shapes
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: `quantity` bigint ≥ 0 in whole units; `resource` CHECK on the six §4.6 resources; `provider`, `model_or_pool` nullable; `metadata` jsonb NOT NULL default `{}`; FK to `job` without cascade; no timestamp column (the UUIDv7 id carries the time); no `job_id` index until a query reads by job.
- Alternatives: Numeric quantity; free-text resource; a `ts` column.
- Why: All §4.6 budgets are ints; §4.6 lists resources as a closed set, unlike `job_event.kind` (D-0102).
- Reversible: yes

### D-0149 — The `pages` budget counts the job's tasks that ended
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: `budget_remaining(job, "pages")` = budget − tasks in `done` or `failed`; other budgets read `job.usage[resource]`; never below 0; `None` means no budget.
- Alternatives: Count claimed tasks too; record `pages` as a usage resource.
- Why: `pages` is a budget key (§4.6) but not a usage resource; a page is spent once its task ends.
- Reversible: yes

### D-0150 — Budgets are advisory across workers
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: No reservation; concurrent checks may both proceed, so a job can overshoot by the work in flight.
- Alternatives: Lock the job row when checking.
- Why: §4.6: "checked by the caller before expensive work"; a lock would serialize a job's workers.
- Reversible: yes

### D-0151 — Budget exhaustion is a handler result, not an exception
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: Handlers return `Failed(BUDGET_EXHAUSTED, transient=False)`; the worker doesn't change.
- Alternatives: A `BudgetExhausted` exception mapped to a permanent failure.
- Why: An exception rolls back the task's transaction, including usage already recorded, so budgets would undercount.
- Reversible: yes

### D-0152 — `ENGINE_VERSION` details
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: Calibration hash = first 12 hex digits of SHA-256 over the file bytes; missing `VERSION` → `unknown`, missing calibration → `none`; a malformed `VERSION` raises at import. Files are read only from a source tree; an installed wheel reports `unknown+cal.none` (open item in ACTIVE.md).
- Alternatives: The full hash; `git rev-parse` at import.
- Why: An honest marker for unbuilt trees, with no subprocess at import.
- Reversible: yes

### D-0153 — Claims select from a `MATERIALIZED` CTE
- Date: 2026-10-13 · Spec/PR: SPEC-01 follow-up (#24) · Status: decided
- Decision: `claim_tasks` updates rows chosen by a `MATERIALIZED` CTE (`SELECT … LIMIT n FOR UPDATE SKIP LOCKED`), so the subquery runs once and a call never claims more than `n` tasks.
- Alternatives: `id = ANY(ARRAY(subquery))`.
- Why: Both force one evaluation; SQLAlchemy expresses the CTE directly, and `MATERIALIZED` is documented PostgreSQL behaviour (PG ≥ 12). `UPDATE … WHERE id IN (SELECT … LIMIT)` can be planned as a semi-join that re-runs the subquery.
- Reversible: yes

### D-0154 — Only keys under `captures/` expire
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `expire_captures` filters on `expires_at < now()` and `object_key` starting with `captures/`; a row under `eval/` is kept whatever its `expires_at`.
- Alternatives: Filter on `expires_at` alone.
- Why: "Eval prefixes untouched" becomes structural rather than dependent on row data (C1).
- Reversible: yes

### D-0155 — Retention runs one bounded batch per transaction; a full batch runs again at once
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: Each run of `expire_captures`/`expire_candidates` deletes at most `RETENTION_BATCH` (1000) rows chosen by `id IN (SELECT … ORDER BY … LIMIT :batch)`. A run that returns a full batch makes the entry due again immediately (`Periodic.batch`), so a backlog drains as consecutive short transactions; the 1 h interval of §4.3 is kept, and a failed run waits its interval.
- Alternatives: Loop with commit inside the entry; run every minute; size the batch to expected ingest.
- Why: A partial failure strands at most one batch; progress is monotonic; capacity scales with backlog.
- Reversible: yes

### D-0156 — Retention deletes rows, then bundles, then commits
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `DELETE … RETURNING object_key`, delete each object, then the scheduler commits. Until the next run, up to one batch of rows already past `expires_at` may name deleted bundles (stated in the docstring).
- Alternatives: Delete bundles after commit (a crash leaves orphan bundles nothing expires).
- Why: A failed delete or commit leaves the rows and the next run converges (store `delete` is idempotent); no bundle is left without the row that expires it (D-0144).
- Reversible: yes

### D-0157 — "Past" is strict
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `expires_at < now()`, `created_at < now() - 30 days`.
- Alternatives: Inclusive comparisons.
- Why: Most conservative reading of "past `expires_at`" and "kept 30 days".
- Reversible: yes

### D-0158 — The scheduler table is built from the object store
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `periodic(store)` replaces the `PERIODIC` constant; `expire_captures` gets the store through `functools.partial`. Retention lives in `crawlerai.scheduler.retention`.
- Alternatives: Open the store inside `expire_captures` from settings.
- Why: Keeps `Periodic.run` as `(conn) -> …` with the store explicit; retention needs both `db` and `storage`, independent siblings in the layering.
- Reversible: yes

### D-0159 — The robots.txt snapshot is JSON in `site.robots_snapshot`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: `{fetched_at, status_code, body}`, fresh for 24 h.
- Alternatives: A `robots_fetched_at` column (migration); a per-process cache only.
- Why: The 24 h rule needs a fetch time; avoids a schema change.
- Reversible: yes

### D-0160 — Only the `*` robots group applies
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: Rules and `Crawl-delay` are read for user agent `*`.
- Alternatives: A `crawlerai` product token.
- Why: Fetches impersonate Chrome and announce no token of their own (RFC 9309 §2.2.1).
- Reversible: yes

### D-0161 — robots.txt matching follows RFC 9309 (spec clarification)
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: SPEC-02 §4.1's "stdlib `urllib.robotparser` semantics" means rules, `Crawl-delay` and `Sitemap:`; matching follows RFC 9309 §2.2.2–2.2.3 (longest match, `allow` on a tie, `*`/`$`), using Protego 0.7 (BSD-3-Clause). SPEC-02 §4.1 wording updated.
- Alternatives: `urllib.robotparser` (first match in file order, wildcards literal); our own matcher beside robotparser.
- Why: ARCHITECTURE §7.1 says robots.txt is honoured; robotparser fetches pages common files disallow (#26 review).
- Reversible: yes

### D-0162 — robots.txt status handling
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: 2xx is parsed (first 500 KiB, UTF-8); 4xx or more than 5 redirects means allow all; 5xx, network error, timeout or SSRF rejection means unreachable: a transient task failure with nothing stored, and `blocked` once attempts run out.
- Alternatives: Block the task as `robots` at once; end it `failed` after retries.
- Why: RFC 9309 §2.3.1.4 reads unreachable as "disallow all"; a blip shouldn't end tasks or cache "disallow all" for 24 h.
- Reversible: yes

### D-0163 — A 429/503 spends an attempt; once attempts run out the task ends `blocked`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: `Failed(transient=True, after=<Retry-After>, exhausted='blocked')` requeues after Retry-After or the usual backoff while `attempts < MAX_ATTEMPTS`, then ends `done`/`blocked` with `last_error='http 429'`.
- Alternatives: Requeue without counting; end as `failed`.
- Why: §4.3 bounds retries; §7.1 classes 429/503 as `blocked`.
- Reversible: yes

### D-0164 — A Retry-After beyond 15 min ends the task `blocked`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: No retry; the limiter pauses the host for 15 min. A delay too large for `timedelta` or `int()` counts as the longest pause.
- Alternatives: Honour any value; clamp to 15 min.
- Why: Neither retries before the server allows nor holds the job open.
- Reversible: yes

### D-0165 — Request interval and rate waits
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: Interval = the site's `crawl_delay_ms` or 1 s, never below the robots `Crawl-delay`. Any wait > 0 returns `Postpone` (attempt given back), never a sleep. robots.txt fetches skip the limiter.
- Alternatives: Let the site setting override robots; sleep through short waits; count robots fetches.
- Why: The operator may go faster than the default but not faster than robots.txt asks; the worker runs tasks one at a time, so a sleep stalls other sites; at most one robots fetch per site per 24 h per worker.
- Reversible: yes

### D-0166 — Normalizer `equal` stubs are exact JSON equality
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 2 (#27) · Status: decided
- Decision: Each type module's `equal(a, b)` returns `a == b` on normalized values until SPEC-04 PR 9 implements §4.5.
- Alternatives: Raise `NotImplementedError`.
- Why: Metrics (SPEC-03 PR 5) land in L0 before SPEC-04; exact equality only undercounts matches, never invents one.
- Reversible: yes; SPEC-04 PR 9 replaces the bodies

### D-0167 — `FieldShape` stands in for SPEC-04's `FieldSpec`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 2 (#27) · Status: decided
- Decision: `eval.labels` defines `ScalarShape | ListShape | ObjectShape`; list/object recursion lives in `values_equal` for now. SPEC-04 PRs 1/9 migrate callers and delete `FieldShape`.
- Alternatives: Add `schemas.types.FieldSpec` and `normalize.base` now.
- Why: Keeps this row inside `eval/labels` and the hook stubs.
- Reversible: yes

### D-0168 — Labeled and checked pages label every schema field; drafts may be partial
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 2 (#27) · Status: decided
- Decision: Missing fields are an error unless `status == "draft"`; a missing field is labeled `absent: true` explicitly.
- Alternatives: Allow partial labels at any status.
- Why: §4.6 scores every field of a checked page.
- Reversible: yes

### D-0169 — Private DB migrations: one Alembic env, two revision chains
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `alembic.ini` gets a `[private]` section with the same `env.py` and `version_locations = migrations/private_versions`; `env.py` uses `PrivateBase.metadata` and `CRAWLERAI_EVAL_PRIVATE_DATABASE_URL` (`EvalPrivateDatabaseSettings`) for it. Private revisions are `p0001`, ….
- Alternatives: A second `migrations_private/` env; one chain with conditional tables.
- Why: The private DDL evolves on its own, and the custodian runs it on their own machine.
- Reversible: yes

### D-0170 — Main eval tables hold dev only; private ones hold hidden/fresh only
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `CHECK split = 'dev'` on main `eval_page`/`eval_run`; `CHECK split IN ('hidden','fresh')` on the private tables.
- Alternatives: A free `split` column guarded only by the store.
- Why: Makes INV-01 structural for anything writing to the main DB.
- Reversible: yes

### D-0171 — `eval_capture` replaces `site_id` with `host` and `category`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `eval_capture` copies the `capture` columns without `site_id` or `expires_at`, and adds `split`.
- Alternatives: A private `site` table.
- Why: C1: a hidden host must not enter the main `site` table; eval captures never expire.
- Reversible: yes

### D-0172 — `eval_page.schema_name` plumbing
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: Both DBs have `schema_id` and `schema_name`; in the main DB the pair references `schema_def(id, name)` (new `uq_schema_def_id_name`); in the private DB it is unchecked.
- Alternatives: The dev store joins `schema_def` while the private DB stores a name.
- Why: `list_pages(schema_name)` works in both stores; the private DB has no `schema_def`.
- Reversible: yes

### D-0173 — `eval_run.git_sha` and `latest_run(sha)`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `eval_run` gets `git_sha` and `created_at`; `latest_run(None)` returns the newest run of the split, `latest_run(sha)` the newest of that commit.
- Alternatives: Parse the sha out of `engine_version`.
- Why: SPEC-03 §4.8 baseline lookup; deciding which commits are on `main` is the gate's job (PR 6).
- Reversible: yes

### D-0174 — LLM cache layout
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: Values are objects: dev at `eval/dev/llm/{key}.json`, private at `llm/{key}.json` (shared by hidden and fresh). In the private store an `eval_llm_cache` row, written after the object, makes a key a hit; the dev store has no table. Keys are lowercase hex sha256.
- Alternatives: Bytes in a table.
- Why: Follows SPEC-03 §4.2's object layout and keeps the `eval_llm_cache` table the row asks for.
- Reversible: yes

### D-0175 — Two-pass labeling rule in the DB
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `CHECK (checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler))`; a labeler pass clears `checker`.
- Alternatives: Enforce only in the store or the API.
- Why: §16.2 requires two different people, and a new labeler pass invalidates an earlier check.
- Reversible: yes

### D-0176 — Dev pages must reference a dev eval capture
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: The dev store accepts only a `capture` with `object_key = eval/dev/{id}.bundle.zst` and `expires_at IS NULL`; otherwise `EvalNotFound`. `eval_page.capture_id` references `capture` with no cascade.
- Alternatives: A trigger; `expires_at IS NULL` alone (accepts non-expiring production captures).
- Why: SPEC-03 §4.2; an expiring capture would make `expire_captures` fail on the foreign key.
- Reversible: yes

### D-0177 — `get_store` refuses a private config that isn't separate
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `PrivateStoreNotSeparate` when the private DB URL names the main database, or one object root is or contains the other.
- Alternatives: No check.
- Why: INV-01 ("separate DB + object prefixes"); SPEC-01 §5.
- Reversible: yes

### D-0178 — Private store tests use a throwaway `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: Tests use a throwaway database named by this variable (skipped without it); CI creates `crawlerai_private_test`, `make check` creates `crawlerai_private_check`, both owned by `app`.
- Alternatives: Give `custodian` a login in CI.
- Why: C1 and D-0067: no custodian credential exists anywhere agents run.
- Reversible: yes

### D-0179 — `put_capture` reads `duration_ms` from `timings_ms["total"]`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 1 (#28) · Status: decided
- Decision: `put_capture` takes only a bundle; the fetchers record the whole fetch as `total`.
- Alternatives: Take a `FetchResult`.
- Why: Keeps the SPEC-03 §4.2 signature.
- Reversible: yes

### D-0180 — An empty checked listing scores
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: A `checked` listing with `rows: []` counts in `n_pages`; its page-level fields are scored, every published field of every engine row is FP, and it is zero-touch only if the engine published no rows.
- Alternatives: Skip it.
- Why: An empty listing is a legitimate label; skipping it would hide false rows from precision.
- Reversible: yes

### D-0181 — Min cell applies to each cell's own n
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: Field cells (`by_field_type`, `by_field`) are suppressed below 10 scored fields; bucket and config-status cells below 10 published fields; `by_category`, `acquisition` and `usage` below 10 pages. SPEC-03 §4.7 wording updated.
- Alternatives: Count labeled fields for every cell.
- Why: Pages ≤ fields, so counting pages is the stricter reading of §16.3 for page-level cells.
- Reversible: yes

### D-0182 — Pages kept only on dev; the full report stays in the job
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `build_report` includes `pages` only for `split == "dev"`; `export_aggregate` produces what leaves the protected job; the gate (PR 6) reads the unsuppressed report inside the job, so a suppressed `wrong_product` still fails it.
- Alternatives: Suppress at build time.
- Why: The gate needs every wrong-product count; nothing per-page is held for hidden/fresh.
- Reversible: yes

### D-0183 — Per-field cells stay in the job for hidden/fresh
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `export_aggregate` empties `by_field` when `split != "dev"`; the dev report and the in-job report keep it.
- Alternatives: Export it with min-cell suppression.
- Why: §4.7's aggregate schema and C10 expose aggregates per field type and evidence bucket only; `by_field` keys name schemas (possibly custom to a hidden site), and its suppressed cells can be recovered by subtraction.
- Reversible: yes

### D-0184 — Usage cells carry their n (spec clarification)
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `usage` is `{mode: {"llm_calls_per_1k_pages": x, "n": pages}}`, per 1k pages of that mode. SPEC-03 §4.7's example updated.
- Alternatives: A bare number per mode over all pages.
- Why: Keeps n with the number and lets small mode cells be suppressed.
- Reversible: yes

### D-0185 — Zero-touch is literal
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: Every judgment of a required field must be TP (labeled-absent is not TP); a required group needs a TP member and no FP member per entity; any unmatched engine row fails it.
- Alternatives: Count TN as success.
- Why: §4.6: "every required field … is TP".
- Reversible: yes

### D-0186 — `list`/`object` fields report under the shape type
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: decided
- Decision: `by_field_type` keys on `FieldShape.type`, so a list of money is reported under `list`.
- Alternatives: The item type.
- Why: SPEC-04 `FieldSpec` will decide; until then no field mixes into a scalar type's precision.
- Reversible: yes

### D-0187 — Secondary suppression of aggregate cells for hidden/fresh
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 5 (#29) · Status: confirmed 2026-10-13
- Question: `by_bucket` and `by_config_status` cells are subsets of `by_field_type`, so one suppressed cell can be derived by subtracting the visible cells from the type total. §16.3 asks only for primary suppression (cells under 10), while its goal is that aggregates "can't identify individual cases". Add secondary suppression?
- Options: (a) keep primary suppression only, as §16.3 says; (b) add complementary suppression: when exactly one cell in a group is suppressed, suppress the next-smallest too; (c) report bucket and config-status tables only for dev.
- Recommendation: (b). It closes the subtraction path at little cost, and the gate reads unsuppressed numbers inside the job anyway (D-0182).
- Blocked: nothing. Ships with primary suppression; changing it touches ARCHITECTURE §16.3, so it needs the owner.
- Owner answer: option (b), complementary suppression (D-0234; ARCHITECTURE Appendix A #30, §16.3).

### D-0188 — Wrong products fail the gate even without a baseline
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: A first run with a wrong product gives `["no_baseline", "wrong_product:<t>"]` and fails.
- Alternatives: Pass every first run with `no_baseline` only.
- Why: INV-21 (wrong-product count on hidden is 0) needs no baseline; most conservative reading of §4.8.
- Reversible: yes

### D-0189 — Types without precision on both sides aren't compared
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: A field type with no precision on either side, or missing from one report, is not compared for precision.
- Alternatives: Fail it.
- Why: §4.8's rule compares precision; an abstention can't be a wrong publish, and dropped pages are caught by `n_pages_dropped`.
- Reversible: yes

### D-0190 — The 0.5 pt boundary uses `math.isclose`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: A drop of exactly 0.5 pt passes.
- Alternatives: Raw float `<`.
- Why: §16.4 says "more than 0.5 pt"; `0.97 - 0.965 > 0.005` is true in binary floats.
- Reversible: yes

### D-0191 — The gate refuses suppressed or mismatched input
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: `gate` raises `GateInputInvalid` on a suppressed `by_field_type` cell or a split mismatch.
- Alternatives: Skip suppressed cells.
- Why: D-0182: the gate reads the unsuppressed in-job report; a suppressed cell can hide a wrong product.
- Reversible: yes

### D-0192 — `GateResult` adds per-type pass/fail
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: `GateResult` adds `by_field_type: {type: pass}` to §4.7's `{baseline_git_sha, passed, reasons}`.
- Alternatives: Derive per-type results from reasons in PR 7.
- Why: §4.8: "its output is pass/fail per field type and the reasons".
- Reversible: yes

### D-0193 — Baseline lookup walks `git rev-list`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: Walk `git rev-list <ref>` newest first and take the first commit with a run (`latest_run(sha)`); return `None` at once when the store has no runs. The protected job needs full history.
- Alternatives: A store query over a sha set.
- Why: No store or migration change; cheap until milestone M.
- Reversible: yes

### D-0194 — `REQUIRED_FIELD_TYPES` is a constant until presets exist
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 6 (#32) · Status: decided
- Decision: The §4.8 list as a constant.
- Alternatives: Derive from presets now.
- Why: SPEC-04 PR 1 isn't merged.
- Reversible: yes; derive from presets later

### D-0195 — Eval capture obeys robots.txt and spaces requests per host
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: `eval capture` and `import-sites` read robots.txt once per origin per run; a disallowed page, or any page on an origin whose robots.txt is unreachable (RFC 9309 §2.3.1.4), is skipped. Pages of one host are spaced by `politeness.interval(None, Crawl-delay)`, and the CLI sleeps through the wait. Nothing is written to `site.robots_snapshot`.
- Alternatives: Fetch with no robots check (the literal reading of §4.4); an override flag.
- Why: ARCHITECTURE §7.1 / SPEC-02 §4.6 politeness applies to every fetch we make; no hidden host enters the main DB.
- Reversible: yes

### D-0196 — Every fetched page is stored, whatever its outcome
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: Blocked, shell, not_found and error outcomes are stored as eval captures and pages; the command exits 0 and reports each outcome.
- Alternatives: Store only `ok` captures; exit non-zero on a non-`ok` outcome.
- Why: §4.6 reports the acquisition outcome mix per category; dropping failures would hide them.
- Reversible: yes

### D-0197 — Site list format: `<category> <schema> <url>` per line
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: `#` comments and blank lines are ignored; `--pages-per-site N` (required) keeps a host's first N pages; any malformed line, unknown category, non-http(s) URL or duplicate URL rejects the whole file before fetching; errors give line numbers only.
- Alternatives: Site URLs with page discovery (SPEC-10); a CSV with a header.
- Why: §16.1 stratifies by category and page kind; leaving content out of errors keeps hidden hosts out of logs (C1).
- Reversible: yes

### D-0198 — Schemas resolve to their newest active version for every split
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: `--schema NAME` resolves to the highest active `version` in the main `schema_def`; `capture --page-kind` must equal the schema's page kind. Private pages store the resolved id and name (D-0172).
- Alternatives: A `--schema-version` flag; let `--page-kind` override.
- Why: The private DB has no `schema_def`; a mismatched page kind would mislabel pages.
- Reversible: yes

### D-0199 — Eval CLI output names pages by input position, never by URL
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: Each output line is `{n, capture_id, page_id, status_code, block_class, error}` or `{n, skipped}`.
- Alternatives: Print the URL.
- Why: C1: a hidden host must not reach a log or CI transcript.
- Reversible: yes

### D-0200 — `EvalStore.aclose()`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: The protocol gains `aclose()`, which disposes the store's engine; use with `contextlib.aclosing(get_store(...))`.
- Alternatives: Callers reach into the engine; leave engines undisposed.
- Why: `get_store` created an engine nobody could close, leaking connections.
- Reversible: yes

### D-0201 — `import-sites --file` is read only from under the working directory
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: Resolved against the working directory; exit 2 if outside.
- Alternatives: Read any path; mark the Sonar finding safe.
- Why: Same rule as `fetch --out` (D-0146); a real fix for S8707.
- Reversible: yes

### D-0202 — Unexpected failures on private splits report their type only
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 3 (#30) · Status: decided
- Decision: On `hidden`/`fresh`, an unexpected exception exits 1 with `failed with <Type>; details withheld for the <split> split`; on `dev` it propagates with its traceback.
- Alternatives: Print tracebacks for every split.
- Why: C1: a DB error's `DETAIL` or an exception message could carry a hidden URL or row values.
- Reversible: yes

### D-0203 — The browser is not tried after a 429 or 503
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: An HTTP `blocked` with status 429 or 503 is kept, with no browser retry; politeness applies the backoff (D-0163).
- Alternatives: Retry every `blocked` in the browser, as §4.4's sketch does.
- Why: RFC 6585 §4 and RFC 9110 §15.6.4 ask for fewer requests; a second rung would be one more request inside the backoff window.
- Reversible: yes

### D-0204 — `site.fetch_method` turns `browser` only on evidence against HTTP
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: `remember_fetch_method` sets `browser` only when the kept result is a browser `ok` and an HTTP attempt in the same fetch was `shell` or `blocked`; a `method_hint` browser fetch changes nothing.
- Alternatives: §4.4's literal `if r.method == "browser" and ok`.
- Why: §7.1 remembers "the method that worked" after HTTP failed; a forced browser fetch says nothing about HTTP.
- Reversible: yes

### D-0205 — The fetch-method re-check
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: Due means `fetch_method='browser'` and `fetch_method_checked_at` null or older than 7 days, oldest first. It fetches the site's latest `ok` capture after robots.txt, one site per transaction; every re-check sets `fetch_method_checked_at`. No `ok` capture, a robots disallow, or unreachable robots.txt keeps `browser`.
- Alternatives: The latest capture of any class; a queued re-check task.
- Why: A page known to exist makes a miss evidence about the method; no job kind exists for a queued re-check; batch 1 bounds row-lock time.
- Reversible: yes

### D-0206 — `acquire` is pure
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: `acquire(url, policy, remembered: FetchMethod, rungs: Rungs)`; `remember_fetch_method(conn, site_id, result)` writes.
- Alternatives: `acquire(url, site, policy)` reading and writing the DB.
- Why: Rung selection is tested without a database, and the caller owns the transaction (ENGINEERING).
- Reversible: yes

### D-0207 — The labeling API serves the dev split only
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: The router holds a `DevEvalStore` from the main settings and never calls `get_store`; `split` accepts only `dev` (422 otherwise); private settings are ignored even when set.
- Alternatives: Serve whichever split `get_store` can open (§1, §4.10 on a custodian machine).
- Why: C1 / INV-01, most conservative reading; hidden/fresh labeling at M is D-0214.
- Reversible: yes

### D-0208 — Label values are checked for structure only until the normalizers exist
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `PUT labels` validates the document, schema fit and two-pass rule; running values through type normalizers and `POST /normalize` wait for SPEC-04 PRs 2–8 (`/normalize` returns 501).
- Alternatives: Refuse every label until then; hand-check value shapes.
- Why: Hand checks would duplicate a type module's logic (C8).
- Reversible: yes; SPEC-04 adds the check

### D-0209 — Pass rules at the API
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `draft`/`labeled` is the labeler's pass and names its labeler; `checked` is allowed only over a `labeled`/`checked` page and keeps the stored labeler.
- Alternatives: Trust the document's names.
- Why: §16.2 / §4.10: `checked` only on confirmation by a different name.
- Reversible: yes

### D-0210 — Problem responses are local until SPEC-07
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: The router returns SPEC-07 §4.3 problems itself; FastAPI's request validation keeps its default 422; no auth until SPEC-07 PR 2.
- Alternatives: Install app-wide handlers now.
- Why: Those are SPEC-07 PR 1's scope.
- Reversible: yes

### D-0211 — The OpenAPI document always includes the eval routes
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `crawlerai openapi` builds the app with `eval_ui=True`; at runtime they mount only with `CRAWLERAI_EVAL_UI=true`.
- Alternatives: Export only what the default app mounts.
- Why: The labeling screen needs the types, and the export must not depend on the environment.
- Reversible: yes

### D-0212 — Capture through the API is limited to 20 URLs per request
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: `POST /v1/eval/capture` runs `run_capture` into dev within the request.
- Alternatives: A background job (SPEC-10).
- Why: Fetches are polite and sequential, so a request must stay short.
- Reversible: yes

### D-0213 — Sanitized HTML for the labeling view
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: decided
- Decision: Removes `script`, `iframe`, `frame`, `frameset`, `object`, `embed`, `meta[http-equiv]`, `on*` attributes and `javascript:` URLs; inserts one `<base href>` at the final URL or the page's own base resolved against it (D-0012); decodes in the Content-Type charset, else UTF-8.
- Alternatives: Only §4.10's list; strip `src`.
- Why: The extra elements also run script or navigate (HTML standard).
- Reversible: yes

### D-0214 — How hidden/fresh pages get labeled at milestone M
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 8 (#35) · Status: confirmed 2026-10-13
- Question: The labeling API serves dev only (D-0207). SPEC-03 §1/§4.10 suggest the same screen could label hidden/fresh on a custodian machine. How should hidden/fresh labeling work?
- Options: (a) a custodian-only process: the same app run on the custodian machine with a private backend, never deployed; (b) this router gains a private backend behind a custodian-only setting; (c) label hidden/fresh with a separate CLI.
- Recommendation: (a). It keeps the main deployment unable to reach private data, and it reuses the screen.
- Blocked: nothing now. Needed before H3 (milestone M).
- Owner answer: option (a), a custodian-machine instance with a private backend, never deployed (D-0234; Appendix A #30).

### D-0215 — `RecordedLLM` keys on the requested model class
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: sha256 of the canonical JSON array `[prompt_kind, model_class, system, user, output_schema]` (sorted keys, no whitespace); SPEC-06's `request_hash` should use the same function.
- Alternatives: The concrete model name.
- Why: The provider picks the concrete model after the request exists (SPEC-06 failover); an array keeps parts from running together.
- Reversible: yes (re-records the cache)

### D-0216 — `replay_split` builds the `RecordedLLM` itself
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: `replay_split` takes `live: LLMClient | None` and returns `list[EvalCase]` (§4.5's `PageResult`).
- Alternatives: A separate `PageResult` type; the caller builds the `RecordedLLM`.
- Why: Every replay LLM call goes through recording by construction; `EvalCase` is what `build_report` scores.
- Reversible: yes

### D-0217 — `replay_page` takes no `calibration` argument (spec clarification)
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: The engine holds calibration and `engine.version` names it, so SPEC-03 §4.5's `replay_page(..., calibration: Calibration, ...)` drops that parameter. SPEC-05 implements this signature.
- Alternatives: Pass calibration separately.
- Why: Matches ARCHITECTURE §15: `(capture, engine_version, config, schema_version) → record`.
- Reversible: yes

### D-0218 — Interim LLM and engine protocols live in `eval/replay`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: `LLMRequest`/`LLMResponse`/`LLMClient` and the `Engine` protocol stay in `eval/replay` until SPEC-05/06 bring the real types.
- Alternatives: Create `crawlerai.llm.client` now.
- Why: Building SPEC-06's module here would pre-empt its PR (same pattern as `metrics.PageOutput`).
- Reversible: yes

### D-0219 — Replay drops pages on data problems and stops on setup errors
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 4 (#33) · Status: decided
- Decision: A missing recording or an invalid `config_snapshot` drops the page (`ReplayFailed`); an unknown schema, a page-kind mismatch or labels that don't fit the schema stop the run.
- Alternatives: Drop on everything; raise on everything.
- Why: Per-page problems trip the `n_pages` gate as §4.11 intends; setup errors would silently drop every page.
- Reversible: yes

### D-0220 — Promote moves whole sites, by default only fully checked ones
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: Without `--all`, a fresh site moves only when every page is `checked`; `--all` moves every fresh site; pages never move one by one.
- Alternatives: Move checked pages individually; `--all` meaning every split.
- Why: §16.1 splits are sets of sites; splitting one would put a host in dev and a private split at once; `checked` is the only measured status (§4.3).
- Reversible: yes

### D-0221 — A fresh site whose host also has hidden pages is not promoted
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: It stays in fresh even with `--all`.
- Alternatives: Promote it anyway.
- Why: C1 / §16.1: moving it would put a hidden host in dev. Most conservative reading.
- Reversible: yes

### D-0222 — Rotation is stratified by category, rounding half up, at random
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: Per category, `floor(F·n_sites + 0.5)` hosts are chosen by `SystemRandom.sample`; a site's category is its first page's; `--fraction` in (0, 1).
- Alternatives: One draw over all sites; floor rounding.
- Why: §16.1 stratifies hidden by category; with 0.33 and 3 sites, round-half-up moves 1.
- Reversible: yes

### D-0223 — Interrupted moves converge
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 (#34) · Status: decided
- Decision: Copy (`put_capture` converges, `put_page` skipped when the dev page exists), then `remove_page` (no-op when missing); a rerun finishes a partial move.
- Alternatives: A two-phase commit across databases.
- Why: The dev and private stores are separate databases (INV-01); §4.4 fixes the order.
- Reversible: yes

### D-0224 — Recurring agent mistakes become checks or skill rules; orchestrator processes are managed
- Date: 2026-10-13 · Spec/PR: workflow (owner request) · Status: decided
- Decision: A finding that recurs is recorded in `docs/plans/RECURRING.md` and gets a check (preferred) or a skill rule in the same change (`/run-plan` §2a); ruff `PT012` is the first such check. Reviews end with a `Categories:` line. Workers report DONE only with the PR's SonarCloud gate `OK`. The orchestrator runs one watcher for all agents, refuses new agents below 1.5 GB free, closes finished panes, and removes a worktree's `crawlerai-*` containers on merge, through `tools/orchestrator/` scripts (`/run-plan` §1a).
- Alternatives: keep lessons in session memory only; one `herdr agent wait` per agent.
- Why: The owner asked that repeated mistakes, visible in SonarCloud, become checks or skills that survive new sessions, and that the orchestrator manage processes so the machine never hangs. S8707, S5778 and red-gate DONE reports each recurred; the low-memory reaper killed per-agent watchers twice.
- Reversible: yes

### D-0225 — Rotation skips a hidden host that also has fresh pages
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 10 follow-up (#37) · Status: decided
- Decision: `rotate_hidden` leaves out hidden hosts that have fresh pages before choosing, and the per-category fraction is a share of the hosts that can rotate. `import-sites` is unchanged. A host in both hidden and fresh stays in both until one copy is removed by hand, since `promote` skips it too.
- Alternatives: (b) `import-sites` refuses a fresh host already in hidden or dev; (c) both.
- Why: Fresh means sites nobody has seen, and a site moves whole (§16.1). This mirrors `promote`'s guard and changes no input contract; (b) changes the custodian's import and needs a lookup across stores at capture time.
- Reversible: yes

### D-0226 — Frontend toolchain is Vite+
- Date: 2026-10-13 · Spec/PR: SPEC-00 §4.3 follow-up (#38, owner request) · Status: decided
- Decision: `vite-plus` 1.1.0 (MIT), pinned exactly, replaces ESLint, Prettier, `tsc -b` and the separate Vite/Vitest setup; lint (Oxlint), fmt (Oxfmt), type-check (tsgo), test and build are configured in `frontend/vite.config.ts`. pnpm stays. Generated API files are excluded through `fmt.ignorePatterns`. TypeScript 5.9.3 stays only as the `openapi-typescript` peer and for editors. `engines.node` follows vite-plus (`^22.18.0 || ^24.11.0 || >=26.0.0`); CI uses Node 24. Plugins are a plain array (`lazyPlugins` fails `exactOptionalPropertyTypes`). Supersedes the ESLint/Prettier/Vitest parts of D-0003, D-0052 and D-0072.
- Alternatives: keep ESLint + Prettier; Biome.
- Why: The owner asked for one toolchain in one PR. SPEC-00 §4.3 and DESIGN.md were edited in the same PR under that request.
- Reversible: yes, with churn

### D-0227 — The pre-commit hook runs `vp check` on staged frontend files
- Date: 2026-10-13 · Spec/PR: #38 · Status: decided
- Decision: A `sh -c` hook strips the `frontend/` prefix and runs `vp check` from `frontend/`. A one-file frontend commit takes about 4 s on the Windows dev host with type-aware rules on, inside SPEC-00 §4.8's 10 s budget. This resolves D-0110 (OPEN_QUESTIONS #15 is left for the owner to close).
- Alternatives: `vp -C frontend check` (formats but does not lint root-relative paths, and exits 0); `vp staged` (lint-staged keeps its own git stash, which worktrees share); `vp hooks` (would replace the pre-commit framework the backend uses).
- Why: Measured on the probe that fails the hook (an a11y violation).
- Reversible: yes

### D-0228 — The no-size-gates scanner covers Oxlint
- Date: 2026-10-13 · Spec/PR: #38 · Status: decided
- Decision: Oxlint config files and the `pedantic`/`style`/`restriction` categories, set with a severity in config or by `-W`/`-D`/`--deny=` flags, count as size gates, because they enable `max-*`/`complexity` rules (C11).
- Alternatives: read the resolved Oxlint config.
- Why: C11 must hold after the lint tool changes; text matching is enough for the configs we have.
- Reversible: yes

### D-0229 — Interim calibration and precedence fits in `eval/calibrate` until SPEC-05
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: Calibration is the dev run's `by_bucket` cells (`n`, precision; a suppressed cell keeps `n` with no precision). Precedence is the current order, unchanged. Both are default parameters that SPEC-05 PR 13 replaces.
- Alternatives: The commands exit "not available until SPEC-05".
- Why: Both follow SPEC-05 §4.11's rules applied to the data the report has today, so the commands are usable and tested end to end.
- Reversible: yes

### D-0230 — `fit-precedence` refuses without a current `source_precedence.yaml`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: With no current file it exits 2 and does not invent an initial order.
- Alternatives: Write SPEC-05 §4.7's default order.
- Why: The initial order is SPEC-05's to commit (D-0020); a default here would be a guess (C7).
- Reversible: yes

### D-0231 — `calibrate`/`fit-precedence` refuse non-dev splits themselves
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: `--split` accepts dev, hidden or fresh; non-dev exits 2 with an INV-02 message before any store is opened.
- Alternatives: `choices=["dev"]` in argparse.
- Why: The refusal is the command's own, stated and tested, as INV-02 requires.
- Reversible: yes

### D-0232 — `EvalStore.get_run(run_id)`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: A protocol method on both stores that reads one run of the store's split by id, raising `EvalNotFound`.
- Alternatives: A dev-store-only method.
- Why: `--run <id>` needs it, and both stores share the run table code.
- Reversible: yes

### D-0233 — PyYAML is a direct dependency
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 11 (#39) · Status: decided
- Decision: `pyyaml>=6,<7` (MIT), with `types-pyyaml` for mypy; only `safe_load`/`safe_dump`.
- Alternatives: Write YAML by hand.
- Why: SPEC-05 reads the file with a YAML parser; the safe functions never construct objects.
- Reversible: yes

### D-0234 — Owner answers to the open owner questions
- Date: 2026-10-13 · Spec/PR: owner · Status: decided
- Decision: The owner took the recommended option on each open item.
  - D-0187 → (b): hidden/fresh aggregates use complementary suppression (ARCHITECTURE rev 7 §16.3; SPEC-03 PR 12).
  - D-0214 → (a): hidden/fresh pages are labeled by the same app run on the custodian machine with a private backend, never deployed.
  - The `pending-owner` entries D-0001, D-0012, D-0015, D-0019, D-0024, D-0037 and D-0086 are confirmed as written (OPEN_QUESTIONS #14).
  - D-0110 is closed by D-0227 (OPEN_QUESTIONS #15).
  - Secrets (H1, H2, H4) are not needed yet; SPEC-03 PR 7 stays `human` until they are.
- Alternatives: the other options listed in D-0187 and D-0214.
- Why: Owner instruction, 2026-10-13.
- Reversible: yes

### D-0235 — Labels carry an ETag; `PUT labels` takes `If-Match`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: The ETag is sha256 of the stored labels' canonical JSON. `If-Match` is optional (`*` or a list of tags); a mismatch is 412. The store also writes only `WHERE labels = <labels the API read>`, and a miss is 409. `EvalStore.put_labels` gains a required keyword `expected`.
- Alternatives: Only the in-request `WHERE` guard; a version column (a migration on a shared table).
- Why: The #35 review follow-up; standard HTTP conditional requests (RFC 9110 §13.1.1), additive to §4.10's API.
- Reversible: yes

### D-0236 — `GET /v1/eval/pages/{id}` returns the schema's field shapes
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: `PageDetail.fields` holds the page's schema fields (type, scope, nesting), which the form renders.
- Alternatives: Wait for `/v1/schemas` (SPEC-07 PR 7).
- Why: §4.10's form needs one row per schema field, and nothing else serves them before SPEC-07.
- Reversible: yes

### D-0237 — The labeling frame is `sandbox="allow-same-origin"`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: No `allow-scripts`, forms, popups or top navigation; the same origin lets the screen read clicks for click-to-copy, and it prevents link navigation. SPEC-03 §4.10 is clarified to match.
- Alternatives: `sandbox=""`, under which click-to-copy cannot work.
- Why: §4.10 asks for both a sandboxed frame and click-to-copy; this is the narrowest sandbox that allows both, and the API strips script (D-0213).
- Reversible: yes

### D-0238 — Label values are entered as JSON until `/normalize` exists
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: The value field takes a JSON value; `/normalize`'s `{value}` or `{reason}` fills it when it answers.
- Alternatives: Per-type inputs (client-side normalization, out of scope, C8).
- Why: The most conservative reading.
- Reversible: yes

### D-0239 — The labeling screen calls its own origin; `pnpm dev` proxies `/v1`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 9 (#42) · Status: decided
- Decision: `sameOriginClient()` uses `window.location.origin`; the Vite dev server forwards `/v1` to the local API.
- Alternatives: CORS on the API; a configured base URL (SPEC-12 PR 1's connect screen).
- Why: No CORS and no connect screen exist yet.
- Reversible: yes

### D-0240 — `schema_org` and `vocab` are checked for syntax only until the schema.org file is in the manifest
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: Syntax per schema.org naming (`schema:<Type>` / `type:<name>`); checking against the pinned vocabulary waits for SPEC-04 PR 7 (§4.6).
- Alternatives: Commit the schema.org file now; hand-type the members.
- Why: The file isn't fetched yet, and §4.6 says data files aren't committed.
- Reversible: yes

### D-0241 — Schema depth and naming rules
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: A top-level field is depth 1 and each `item`/`fields` level adds 1, max 3. A list item needs no description; object sub-fields do. Schema and field names match `^[a-z][a-z0-9_]{0,63}$`.
- Alternatives: Count only container levels; require item descriptions; free-form names.
- Why: The most conservative reading; names are keys in records, configs and API payloads.
- Reversible: yes

### D-0242 — Presets sync through `crawlerai schemas sync`, run by `make migrate`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: Not an Alembic data migration or a startup hook. It refuses (`PresetConflict`, nothing inserted) when a stored (name, version) differs from the file, belongs to a non-preset row, or is newer than the file.
- Alternatives: A data migration; sync on API startup.
- Why: The preset files stay the single source, and a changed file without a version bump fails loudly.
- Reversible: yes

### D-0243 — `create` inserts version 1; `new_version` inserts latest+1
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: `create` refuses an existing name. `new_version(name, SchemaChanges, origin)` applies the given changes to the latest version, validates the whole document and inserts latest+1; older versions stay `active`. The function is `list_schemas`, not `list`.
- Alternatives: `new_version` retires the previous version; `create` takes any version.
- Why: Records and configs reference older versions; retiring is SPEC-07's decision.
- Reversible: yes

### D-0244 — The C3 scan reads `schema_org` paths from schema documents as non-hosts
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: A dotted token is a schema.org path, not a host, when a tracked JSON schema document maps a field to it (up to any `+`). Extends D-0111.
- Alternatives: A shape test on any `schema_org`-like value; an allowlist of paths (C4).
- Why: Derived from the repo, as D-0111's columns are. A tightening is a follow-up (ACTIVE, SPEC-04 PR 1).
- Reversible: yes

### D-0245 — Preset mappings the spec leaves open
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: `url` → `Product.url`, `image_url` → `Product.image`, `brand` → `Product.brand.name`; listings use the same row paths; `next_page_url` has no schema.org mapping.
- Alternatives: `Offer.url`; `Product.brand`.
- Why: schema.org `brand` is a `Brand`/`Organization`, so the text is its `name`; schema.org has no next-page property.
- Reversible: yes
