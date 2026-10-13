# Decisions log

Agents log the decisions they make while writing specs and implementing them. Owner decisions belong in
ARCHITECTURE Appendix A; open owner questions belong in OPEN_QUESTIONS.md. What goes here and when to escalate:
`CLAUDE.md` §4–§5.
While an orchestrator runs, workers put decisions in their PR body and the implementor copies them here in its
tracker commit on `YOUR TURN`, under the IDs the orchestrator sends (`CLAUDE.md` §3).

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
| D-0311 | GeoNames has no versioned download URL | needs-owner |

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
- Date: 2026-10-12 · Spec/PR: tooling (skills `implement-pr`, `pickup`) · Status: decided
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
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 1 (#1) · Status: decided
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
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: superseded by D-0248
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

### D-0246 — Complementary groups include `by_category` (with `acquisition`) and `usage`
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 12 (#44) · Status: decided
- Decision: Besides §4.7's bucket and config-status groups, category and usage cells are complemented, since their `n` sums to the reported `n_pages`.
- Alternatives: Only the two groups §4.7 names.
- Why: The ACTIVE row asks for every group that sums to a reported total; the conservative reading (§16.3).
- Reversible: yes

### D-0247 — A one-cell group gets no complement; ties break by key
- Date: 2026-10-13 · Spec/PR: SPEC-03 PR 12 (#44) · Status: decided
- Decision: A group with one suppressed cell gets no complement; among equal-`n` candidates the first key is suppressed.
- Alternatives: Suppress the group total too.
- Why: A one-cell group equals its total, which §16.3 reports at its own size; key order keeps exports deterministic.
- Reversible: yes

### D-0248 — The C3 scan reads `schema_org` paths only from schema document fields
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 follow-up (#48) · Status: decided
- Decision: Paths come only from the field specs of JSON schema documents (`name`, integer `version`, `page_kind`, `fields`), only when they follow schema.org naming (UpperCamelCase type, lowerCamelCase properties), and match case-sensitively. Supersedes D-0244.
- Alternatives: restrict to `schemas/presets/` (a path rule); reject values ending in an IANA TLD (rejects `Product.name`, since `name` is a TLD); validate against the schema.org vocabulary (new manifest data).
- Why: Structural, derived from the schema document shape, as D-0111's columns are. Residual: a reviewed schema document could map a host spelled `Upper.lower.tld`; vocabulary validation would close it if needed.
- Reversible: yes

### D-0249 — The browser's SSRF guard is a per-fetch SOCKS5 proxy
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: decided
- Decision: Each context gets `proxy=socks5://127.0.0.1:<port>` served by `SocksGuard`, which checks each (host, port) with `SafeConnector.check` once per fetch and connects to the checked IP; loopback and link-local bypass is disabled explicitly (`<-loopback>`, Chromium's implicit bypass rules). The first URL is checked before the context opens; WebRTC non-proxied UDP is disabled. SPEC-02 §4.1 and §4.5 are clarified to match; ARCHITECTURE §7.1 is unchanged.
- Alternatives: §4.5's `route("**/*")` handler (saw only the first URL of a redirect chain in Patchright 1.63, and lets the browser re-resolve DNS); an HTTP forward proxy (needs a request parser).
- Why: Meets §7.1's "resolve once and connect only to that public IP, on every redirect hop" for everything the browser opens (INV-16).
- Reversible: yes

### D-0250 — Browser captures store the raw navigation body
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: decided
- Decision: `CaptureBundle.raw_body` and `CaptureManifest.raw_html_sha256` (optional), stored as `body.raw.html` for browser captures; `bundle_version` stays 1 and older manifests decode with `None`.
- Alternatives: Bump `bundle_version`; store it as a network entry.
- Why: SPEC-02 §4.8 / D-0010 ask for both bodies; the member is additive.
- Reversible: yes

### D-0251 — `browser_timeout_s` is a hard cap on the whole browser fetch
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: decided
- Decision: `goto` gets what remains; the network-idle wait ends at 90% of it; the rest reads the DOM and bodies. A page that never goes idle is read then, not an error; past the cap is `error`/`timeout`.
- Alternatives: A separate idle timeout.
- Why: §4.8's "wait up to `browser_timeout_s` for network idle with a hard cap"; one bound.
- Reversible: yes

### D-0252 — Browser outcome details follow the HTTP fetcher
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: superseded by D-0320 (the size cap only)
- Decision: The size cap is `max_decompressed_bytes` on both bodies; failures report `timeout`, `ssrf_rejected: <reason>` or `network_error: net::ERR_*`, never the URL (D-0128); the navigation response is not captured as a network body; `browser` tests skip without Chromium except under `CI`.
- Alternatives: `max_body_bytes`; capture a JSON document as a network body.
- Why: Consistent with D-0127 and D-0128; the document is already `body.html`.
- Reversible: yes

### D-0253 — Capture and import-sites refuse a host that has pages in another split
- Date: 2026-10-13 · Spec/PR: SPEC-03 follow-up (#49; D-0225 option b) · Status: decided
- Decision: `eval capture` and `eval import-sites` refuse the whole input before any fetch when one of its hosts already has pages in another split, reporting counts only (per split), never a host or line. Re-capturing into the host's own split is allowed. A dev capture is checked against hidden/fresh only when custodian settings are present.
- Alternatives: skip offending lines and report line numbers (a line number points at a hidden host); require private credentials for every dev capture (contradicts C1's custodian-only credentials).
- Why: A site sits in one split (§16.1); counts-only output keeps C1. Remaining gap by design: a non-custodian dev capture of a hidden/fresh host can't be detected; `promote` and `rotate-hidden` still guard moves.
- Reversible: yes

### D-0254 — Normalizer `base` holds the shared types; `dispatch` holds the dispatcher
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: SPEC-04 §4.1 puts both in `base`, but the dispatcher imports the type modules, which import the result types; one module would cycle.
- Alternatives: The dispatcher in `normalize/__init__`; lazy imports in `base`.
- Why: Avoids an import cycle; C8 holds.
- Reversible: yes

### D-0255 — Import contracts: normalize above schemas, an explicit independence list, a `normalize-internals` layers contract
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: D-0056 anticipated the relaxation of D-0055's wildcard, which can't hold because type modules import `base`. Each new type module joins both normalize contracts in its PR.
- Alternatives: normalize defines its own spec protocol (duplicates `FieldType`).
- Why: Keeps C8's one-module-per-type enforced by `lint-imports`.
- Reversible: yes

### D-0256 — `Context` gains `base_url` and `page_url`; every field except `captured_at` is optional
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: §4.4 resolves URLs against the document base and checks images against the page URL, which §4.3's `Context` lacks. `None` means "no evidence", not a default (C7).
- Alternatives: Pass them as separate arguments.
- Why: The spec's own §4.4 needs them.
- Reversible: yes

### D-0257 — text and url accept only JSON strings
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: Other JSON values, including JSON-LD value objects (`@value`, `@id`), are `Invalid("not_a_string")`; unwrapping is the collector's job.
- Alternatives: Unwrap value objects in the normalizer.
- Why: schema.org Text and URL values are JSON strings; C8.
- Reversible: yes

### D-0258 — long_text keeps line breaks, collapsing runs of blank lines to one
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: trafilatura runs in the content layer, before normalization.
- Alternatives: Keep only paragraph breaks.
- Why: Preserves structure without guessing.
- Reversible: yes

### D-0259 — Placeholder syntaxes for text
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: `{{…}}`, `${…}`, and printf `%s`/`%d` with an optional `%1$`/`%(name)` prefix, no flags, ending at a word boundary.
- Alternatives: Allow printf flags (reads "100% sure" as `% s`).
- Why: Template placeholders by their syntax (structural), not a word list (C4).
- Reversible: yes

### D-0260 — url keeps an empty query's `?`; hosts lowercased, not IDNA-converted
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: RFC 3986 §6.2.3 removes an empty component's delimiter only where the scheme allows it.
- Alternatives: Drop the `?`; IDNA-encode hosts.
- Why: RFC 3986; SPEC-04 PR 9 (url `equal`) may revisit IDNA.
- Reversible: yes

### D-0261 — url declines input empty after WHATWG trimming
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: The empty check runs after the WHATWG trim and tab/newline removal; only C0 controls, spaces and Unicode White_Space is `Invalid("empty")`.
- Alternatives: Check before trimming (C0-only input resolved to the base).
- Why: INV-06 (review fix).
- Reversible: yes

### D-0262 — text removes Cc controls that are not White_Space
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: Control-only input is `Invalid("empty")`. Default_Ignorable-only strings (ZWSP, BOM) are still accepted pending a separate decision.
- Alternatives: Keep controls.
- Why: Controls are not text, and Postgres `text`/`jsonb` can't store NUL.
- Reversible: yes

### D-0263 — url and text decline lone surrogates
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: A string holding a Unicode Cs code point is `Invalid("surrogate")`, via `base.has_surrogate` (shared, C8); url checks the base only when it resolves against it.
- Alternatives: Replace with U+FFFD.
- Why: It has no UTF-8 encoding (url's `quote()` raised); JSON-LD may carry one as an escape (RFC 8259 §8.2). C7: decline rather than guess.
- Reversible: yes

### D-0264 — Hypothesis `ci` profile and mypy `explicit_package_bases`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: `tests/conftest.py` registers `ci` (`max_examples=200`, SPEC-04 §6), loaded when `CI` is set; `explicit_package_bases = true` lets mypy tell the two conftest files apart.
- Alternatives: `__init__.py` files in test directories.
- Why: SPEC-04 §6's example count in CI.
- Reversible: yes

### D-0265 — `Adapter.map` takes a field → schema.org projection and the page kind
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: SPEC-02 §4.9 says `map(schema_def)`, but the layers contract puts `schemas` above `acquire : adapters`. The caller (collect, above schemas) passes `{field: schema.org path}` and the page kind; only top-level fields are mapped.
- Alternatives: Relax the layer contract.
- Why: Same information, no contract change (C8).
- Reversible: yes

### D-0266 — Adapter JSONPaths use RFC 9535 bracket notation
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: `$['location']['name']`, `$['jobs'][*]['title']`.
- Alternatives: Dot notation.
- Why: RFC 9535 Normalized Paths; can't be mistaken for a hostname by the C3 scan.
- Reversible: yes

### D-0267 — Greenhouse endpoints verified; no guessed regional host
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: `GET /v1/boards/{token}/jobs?content=true` and `/jobs/{id}`, verified against the platform's public docs on 2026-10-13, closing SPEC-02 §9's "[unverified]" item for Greenhouse. Boards on regional hosts the docs don't name are not detected and fall through to the generic rungs.
- Alternatives: Guess a regional API host.
- Why: C7: decline rather than guess.
- Reversible: yes

### D-0268 — `acquire/api.fetch_json` (GET only) lands with the adapters
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: `JsonRequest(url, page_url)`, GET only; SPEC-09 extends it for recipes; proxy support follows SPEC-02 PR 7.
- Alternatives: Build it in SPEC-09.
- Why: The adapter's fetch needs it now.
- Reversible: yes

### D-0269 — The active adapter set is a `Registry` argument
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: A per-adapter settings flag is a follow-up.
- Alternatives: A settings flag now.
- Why: Settings are SPEC-02 PR 7's scope, and nothing builds the registry in production yet.
- Reversible: yes

### D-0270 — Cleanup removes all Docker build cache after each merge
- Date: 2026-10-13 · Spec/PR: workflow (#51, owner request) · Status: decided (owner)
- Decision: `cleanup_worktree.sh` removes `crawlerai-*` containers with `-v`, all build cache (`docker builder prune -af`) and dangling images after each merge; a failed prune warns on stderr.
- Alternatives: Cap the cache at 5 GB (`--max-used-space`).
- Why: Owner, 2026-10-13: "i dont need any cache in docker". The cache is host-wide, so other projects' builds get slower too.
- Reversible: yes

### D-0271 — schema.org enumeration members ship as typed data until the schema.org file is in the manifest
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: `normalize/vocab/schema/ItemAvailability.json` lists the 12 members, typed from the standard; its JUSTIFICATION.md says to read them from the pinned schema.org file once SPEC-04 PR 7 adds it.
- Alternatives: Wait for PR 7 (no enum `Ok` until then); add the file to the manifest here.
- Why: The spec's open issue names hand-typed members as the fallback; a closed standard enumeration, not an incident list (C4).
- Reversible: yes

### D-0272 — "Longest match wins" applies to overlapping matches only
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: A match inside a longer match's span is dropped; matches at separate places all count, and different codes there are `Ambiguous`.
- Alternatives: The longest match anywhere wins.
- Why: Choosing by length across places would guess between two members (C7).
- Reversible: yes

### D-0273 — Vocabulary language comes from the page
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: Primary subtags of `html_lang`, `og_locale` and `request_locale` (not `hreflang`); with none stated, every language is tried; only languages without a file give `Invalid("no_vocabulary_for_language")`.
- Alternatives: Always try every language; require a stated language.
- Why: Vocabularies are language-tagged (§9); cross-language disagreement still shows as `Ambiguous`.
- Reversible: yes

### D-0274 — `schema:` enum matching is exact and case-sensitive
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: Only surrounding white space is trimmed; `instock` against `schema:ItemAvailability` is `Invalid("not_a_member")`; a JSON-LD node with keys other than `@id` is `Invalid("not_a_string")`.
- Alternatives: Casefold; fall back to `type:availability` phrases.
- Why: schema.org names are case-sensitive; the spec links no `schema:` field to a `type:` vocabulary.
- Reversible: yes

### D-0275 — range resolves currency through the money rules via the dispatcher
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: `range.normalize` takes a keyword-only `money` callable; the dispatcher passes `normalize(·, FieldSpec(type=money), ctx)`.
- Alternatives: Import `money` (breaks the independence contract); copy CLDR symbol resolution (C8 duplication).
- Why: §4.4's "currency through the money rules" with one module per type (C8).
- Reversible: yes

### D-0276 — Range value shape `{min, max, currency, unit, period}`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: Bounds are plain-notation decimal strings; exactly one of `currency`/`unit` is set; `period` is one of the five schema.org unitText values or null.
- Alternatives: One `currency|unit` key.
- Why: Keeps ISO 4217 currency and UN/CEFACT or unitText unit distinguishable for PR 9's `equal`.
- Reversible: yes

### D-0277 — A unit range needs no period; a monetary range does
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: A `QuantitativeValue` with a `unitCode` or non-period `unitText` gives `Ok` with `period: null`; a currency range without a period is `Ambiguous("period_missing")`; a period with neither currency nor unit is `Ambiguous("currency_missing")`.
- Alternatives: Require a period for every range.
- Why: §9's "period unresolved" applies to salary-style amounts; a quantity range has no period.
- Reversible: yes

### D-0278 — A currency written once in range text applies to both bounds
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: If only one bound has text around its amount (`€10-20`, `10-20 EUR`), that text is copied around the other bound before each goes to the money rules; with none, `Ambiguous("currency_missing")`.
- Alternatives: Decline unless both bounds carry it.
- Why: A structural property of written ranges; the money rules still decide the currency.
- Reversible: yes

### D-0279 — Range text needs one separator with an amount on each side
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: A lone text value is `Invalid("not_a_range")`; structured `QuantitativeValue.value` gives min = max.
- Alternatives: Read a lone text amount as min = max.
- Why: §4.4: text is two parses around a separator; `value` is a standard single value.
- Reversible: yes

### D-0280 — `type:period` (en) words live in `range.py` until moved into `vocab/`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: hour/day/week/month/year after "per" or "/", derived from schema.org unitText. Follow-up: move into PR 4's vocab framework with a JUSTIFICATION.md.
- Alternatives: Invent a vocab file format ahead of PR 4.
- Why: Avoided a conflict with PR 4 while both were in flight.
- Reversible: yes

### D-0282 — A proxy pool is an HTTP proxy used through a CONNECT tunnel
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: `http://[user[:password]@]host[:port]`, always tunnelled (http pages too): curl gets `HTTPPROXYTUNNEL`; the browser's `SocksGuard` chains each checked connection to the pool with CONNECT. SPEC-02 §4.5 clarified.
- Alternatives: SOCKS5 or HTTPS proxies; absolute-form forwarding; pointing Chromium straight at the pool (leaves hops unchecked, D-0249).
- Why: OPEN_QUESTIONS #10's datacenter/ISP pools speak CONNECT (RFC 9110 §9.3.6); tunnelling keeps the proxy from rewriting requests; chaining behind the guard keeps INV-16.
- Reversible: yes

### D-0283 — An unknown proxy pool ends the fetch with `error='proxy_pool_unknown'`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: A policy naming a pool not in `CRAWLERAI_PROXY_POOLS` fetches nothing.
- Alternatives: Fetch directly; raise.
- Why: C7: no fallback that silently changes where requests come from; an outcome like other fetch failures (§4.11).
- Reversible: yes

### D-0284 — The configured proxy endpoint is the SSRF allowlist entry
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: The proxy's own address isn't SSRF-checked; being configured in settings is §4.5's explicit allowlist.
- Alternatives: Check it like a target.
- Why: §7.1/§4.5: "public or explicitly allowlisted in settings".
- Reversible: yes

### D-0285 — Settings errors hide input; `ProxyEndpoint` hides credentials in its repr
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: `hide_input_in_errors`; username and password stay out of reprs.
- Alternatives: Default reprs.
- Why: Proxy and database URLs carry credentials.
- Reversible: yes

### D-0286 — A refused proxy tunnel reports as curl does
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: `network_error: curl 7` over HTTP; a SOCKS general failure in the browser; no separate `proxy_error` class.
- Alternatives: A `proxy_error` class.
- Why: curl gives a refused CONNECT the same code as an unreachable server; separating them needs per-handle state.
- Reversible: yes

### D-0287 — A GTIN keeps its digits as given
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: No padding of GTIN-12/13 to 14 digits; PR 9's `equal` may compare zero-padded.
- Alternatives: Pad to the GS1 14-digit comparison form.
- Why: §4.4 doesn't require padding; the stored value stays what the page published.
- Reversible: yes

### D-0288 — No separators inside a GTIN; ISBN separators per ISO 2108 are dropped
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: Spaces and hyphens in a GTIN are `Invalid("not_digits")`; ISBNs drop ISO 2108 hyphens, spaces and a leading `ISBN ` prefix.
- Alternatives: Also strip GS1 human-readable spacing.
- Why: §4.4 "digits only"; conservative, relaxable for a class of failures.
- Reversible: yes

### D-0289 — Identifiers accept non-negative JSON integers
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: A non-negative JSON integer is read as its decimal digits; booleans, floats, negatives, lists and objects are `Invalid("not_a_string")`.
- Alternatives: Strings only.
- Why: JSON-LD publishers write `gtin13` unquoted; a lost leading zero shows as a length or check-digit failure, never a silent change.
- Reversible: yes

### D-0290 — An ISBN-13 needs the 978/979 prefix
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: Any other EAN-13 under scheme `isbn` is `Invalid("prefix")`.
- Alternatives: Accept any EAN-13.
- Why: ISO 2108.

### D-0281 — Parse once: one shared `ParsedPage` per capture
- Date: 2026-10-13 · Spec/PR: owner (ARCHITECTURE rev 8, Appendix A #31) · Status: decided (owner)
- Decision: A capture body is parsed at most once per parser (selectolax, lxml) per pipeline run or `scrape` request. SPEC-05's `content.page.ParsedPage` holds the trees (lxml lazily), the script blocks, cleaned text and the visibility index. Collectors, content formats, pagination and the engine executor take it instead of the body. The release executor is the only exception (INV-20). New invariant INV-26.
- Alternatives: let each consumer parse what it needs.
- Why: Owner, 2026-10-13: "make sure multiple parsing is avoided and parsed html is reused" (seen in earlier products). Before this, the specs had each collector, cleaned text, content formats, pagination and the executor start from the body.
- Reversible: yes

### D-0291 — Operational invariants INV-27–INV-32
- Date: 2026-10-13 · Spec/PR: owner (ARCHITECTURE Appendix A #32) · Status: decided (owner)
- Decision: Adopt six invariants: no layer after resolution changes a published value (INV-27); a job pins its settings at submit (INV-28); cookies stay inside one fetch (INV-29); untrusted bodies are bounded, oversize is an error (INV-30); one task's failure never fails another (INV-31); forwarded headers only from trusted proxies, and no API keys created at startup (INV-32). Each is written for v2; nothing is copied (C12).
- Alternatives: the other candidates reviewed (listing/detail separation, popup suppression, a single redactor, `srcset` grammar), which the owner didn't select.
- Why: The owner allowed a one-off read of the v1 invariants document only (a logged exception to C12, 2026-10-13), after "parse once" (D-0281) turned out to be missing, and chose these six.
- Reversible: yes

### D-0292 — No comparisons with a named hosted crawler in the docs
- Date: 2026-10-13 · Spec/PR: owner · Status: decided (owner)
- Decision: README and ARCHITECTURE no longer name or compare against a specific hosted crawler product.
- Alternatives: keep the comparison.
- Why: Owner instruction.
- Reversible: yes

### D-0293 — Date order comes from the CLDR locales of `html_lang` and `og_locale`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: A tag with a territory uses its CLDR locale's short date pattern; a language-only tag allows the orders of every CLDR locale of that language (and script), so `en` declines `03/04/2026` while `de` is DMY; no locale allows every order.
- Alternatives: CLDR likely subtags (`en` → `en_US`); also using `cctld_territory`/`request_locale`.
- Why: Likely subtags would act as a default (C7), and §4.4 names only these two sources.
- Reversible: yes

### D-0294 — Numeric dates are parsed by our own code, not `dateparser`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: Three-field numeric dates are read in each allowed order by the module; `dateparser` handles text with words.
- Alternatives: `dateparser` with `DATE_ORDER` for every input.
- Why: `dateparser` silently swaps fields when a reading is invalid, so it cannot report ambiguity.
- Reversible: yes

### D-0295 — A two-digit year is read in every century
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: `yy` is read as 19yy, 20yy and 21yy, and the 1970–2100 range settles which (`26` → 2026; `85` → `Ambiguous`); `dateparser` readings are checked for a year written in full.
- Alternatives: POSIX `%y` pivoting.
- Why: A pivot is a default (C7).
- Reversible: yes

### D-0296 — A datetime needs a time and a numeric offset; output is UTC with `Z`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: Date-only input is `Invalid("no_time")`; a naive time or a zone abbreviation is `Invalid("no_offset")`; `2 hours ago` is `Invalid("relative_datetime")`. A `date` field takes the calendar date the input states in its own offset.
- Alternatives: Keep the source offset in the output; assume UTC for naive times.
- Why: Exact equality (§4.5) needs one form per instant, and an assumed zone is a default (C7).
- Reversible: yes

### D-0297 — Relative dates are detected structurally
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: A reading is relative when it moves with the base time (parsed again with the base one day later); only `day`/`time` periods name a day.
- Alternatives: A list of relative phrases.
- Why: No phrase list (C4); `1 month ago` and `March 2026` do not name a day.
- Reversible: yes

### D-0298 — Relative dates are read against fixed bases
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: `dateparser` reads against two fixed bases and the result is shifted onto `ctx.captured_at`; a reading that is not a plain one-day shift is dropped.
- Alternatives: Use the capture time as `RELATIVE_BASE`.
- Why: `dateparser` keeps every settings object for the life of the process, so a per-page base grows memory per page.
- Reversible: yes

### D-0299 — Date and datetime inputs are strings only
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: Any other JSON value is `Invalid("not_a_string")`.
- Alternatives: Accept JSON numbers as timestamps.
- Why: Structured sources (JSON-LD `datePosted`) carry strings; a number's unit and epoch are not stated.
- Reversible: yes

### D-0300 — Money accepts text, schema.org `price` + `priceCurrency`, or `amount` + `currency`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: A structured amount is a JSON number or a schema.org `price` string (ASCII digits, `.` decimal point, no grouping); a structured currency must be an uppercase ISO 4217 code Babel lists.
- Alternatives: Lenient parsing of structured strings; uppercasing codes.
- Why: schema.org `price` syntax and ISO 4217 define these forms; accepting the normalized form makes labels re-normalizable and idempotence direct.
- Reversible: yes

### D-0301 — Money text with no currency sign is `Invalid("no_currency")`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: This holds even when `page_currencies` holds one code.
- Alternatives: Take the single page currency.
- Why: §4.4 lets a page currency settle a sign, not supply a missing one; the most conservative reading (C7).
- Reversible: yes

### D-0302 — Money's locale set comes from the context tags, then the ccTLD
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: Tags come from `html_lang`, `og_locale`, `request_locale` and `hreflang`. A tag with a territory is used as is; a language-only tag becomes `language_ccTLD` when CLDR has that locale, else every CLDR locale of the language. Tags CLDR can't parse (`x-default`) are ignored; with no tag CLDR knows, the ccTLD stands for its territory's locales. With no locales at all, every CLDR locale counts.
- Alternatives: Read `en` as CLDR's default `en` (US).
- Why: A tag without a territory doesn't say which territory's `$` is meant, so `$` with `lang="en"` stays ambiguous (ARCHITECTURE §9).
- Reversible: yes

### D-0303 — Precedence of money currency evidence
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: (1) an ISO 4217 code names itself; (2) the `page_currencies` codes the sign stands for anywhere in CLDR; (3) the currencies the sign stands for in the locale set; (4) if none, every currency the sign stands for in CLDR. One currency is `Ok`, several are `Ambiguous`.
- Alternatives: Intersect locale and page evidence.
- Why: §4.4 makes a stated page currency decisive for a sign valid for it; an ISO code naming itself also covers CLDR `zh` writing ILR as `ILS`.
- Reversible: yes

### D-0304 — Money locates its own amount and sign, with `price-parser` as fallback
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: The amount is the one run of digits joined by CLDR decimal and group separators; two runs are `Invalid("range")`. The sign is the longest CLDR symbol or ISO code next to the amount, not inside a run of letters; failing that, the sign `price-parser` locates if it is a whole token. A minus sign (U+002D, U+2212) before the amount is `Invalid("not_positive")`.
- Alternatives: Use `price-parser`'s amount and sign as given.
- Why: `price-parser` drops minus signs (`-5 €` gives 5), reads only the first of two amounts, and locates `S$` inside `BS$`.
- Reversible: yes

### D-0305 — Money signs on both sides of the amount must agree; an amount may open with its decimal symbol
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: The longest sign before and the longest after the amount are both read and the currency is what both can denote (`$5 USD` gives USD); none shared (`USD 12 EUR`) is `Invalid("currency_conflict")`. An amount may open with `.` or `,` (`.99`) unless a letter or digit precedes it, and CLDR decides whether it is the decimal symbol.
- Alternatives: Keep the first or shorter sign; drop the leading separator.
- Why: `.99 USD` read as 99 and `USD 12 EUR` resolved to one code, both wrong values (C7).
- Reversible: yes

### D-0306 — Money amounts fit `numeric(18,6)` and keep their written digits
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: An amount must be below 10^12 with at most 6 significant fraction digits (trailing zeros don't count), else `Invalid("out_of_range")`; the output keeps its written digits (`19.90`).
- Alternatives: Round.
- Why: Values must be storable without rounding (D-0005), and §4.5 compares amounts as Decimals.
- Reversible: yes

### D-0307 — Lever endpoints verified; both documented instances detected
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: `GET /v0/postings/{site}?mode=json` and `/v0/postings/{site}/{posting_id}`, verified against the platform's public Postings API docs on 2026-10-13, closing SPEC-02 §9's "[unverified]" item for Lever. The global and EU job site hosts are each sent to their own instance's API host.
- Alternatives: The global host only.
- Why: The docs name both instances.
- Reversible: yes

### D-0308 — Filtered Lever job site lists and application forms are not detected
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: A job site URL carrying one of the list endpoint's documented filter or group parameters (`location`, `commitment`, `team`, `department`, `level`, `group`), and the `/{site}/{id}/apply` form, fall through to the generic rungs.
- Alternatives: Forward the filters to the API (the docs don't say the job site uses the same parameters).
- Why: C7: decline rather than guess.
- Reversible: yes

### D-0309 — No `datePosted` or `hiringOrganization.name` mapping for Lever
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: Lever maps `JobPosting.title`, `url`, `description` and `jobLocation` only.
- Alternatives: Map undocumented fields.
- Why: The documented posting fields have no posting date or company name.
- Reversible: yes

### D-0310 — `PATH_SEGMENT` and `json_path` live in `adapters/base`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: The URL path-segment pattern and the RFC 9535 bracket-notation builder are shared by the adapters.
- Alternatives: A copy per adapter.
- Why: C8: the same logic was needed twice.
- Reversible: yes

### D-0311 — GeoNames has no versioned download URL
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: needs-owner
- Decision: Needed: a stable source for the four pinned GeoNames files (SPEC-04 §4.6). `download.geonames.org/export/dump/*` is rewritten daily, so the pinned sha256 (the 2026-10-13 snapshot) stops matching and `crawlerai data fetch` refuses ("the entry needs re-pinning").
- Alternatives: (a) re-pin in a PR whenever a fetch is needed; (b) mirror the pinned snapshot as a release asset of this repo (CC BY 4.0 allows it with attribution) and point `url` at it; (c) an owner-run object-store mirror.
- Why: Recommendation (b), a one-time owner action. Blocked: SPEC-05's first real run; tests use a synthetic gazetteer and CI never fetches.
- Reversible: yes — change the manifest `url`.
- Owner answer:

### D-0312 — Fetched entries in the data manifest
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: A `"fetched": true` entry is absent from git: `data_manifest_check` allows it to be missing and checks its hash when present; `crawlerai data fetch` writes it only after the hash matches.
- Alternatives: Commit the files.
- Why: SPEC-04 §4.6 keeps the GeoNames files out of git.
- Reversible: yes

### D-0313 — The gazetteer is read from the source tree's `backend/data/geonames/`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: Read once per process from `backend/data/geonames/`, the rule calibration follows (`core.engine_version.data_dir`). Without the files, text location input raises `GazetteerMissing` ("run `crawlerai data fetch`"); input that declines on its own never loads it.
- Alternatives: Decline every location silently.
- Why: A missing deployment file should be loud. Follow-up for the image build: run `crawlerai data fetch` and ship `backend/data` (or a settings path) with `VERSION` and calibration.
- Reversible: yes

### D-0314 — Country codes are not read in free text
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: ISO 3166-1 codes are accepted only in structured `addressCountry` (alpha-2 or alpha-3), not in location text.
- Alternatives: Match codes in text too.
- Why: The conservative reading of SPEC-04 §4.4's "country name/code match": alpha-2 codes collide with ISO 3166-2 subdivision abbreviations and short words.
- Reversible: yes

### D-0315 — The country is not implied from the page context
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: `cctld_territory` and the page language never settle a homonym; the languages only choose which CLDR country names and `type:remote` phrases are read.
- Alternatives: Prefer the page's territory.
- Why: C7: no values from URL codes.
- Reversible: yes

### D-0316 — Every place name in location text must fit the value
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: Text naming places no single place fits (a city and a country it is not in, or two countries) is `Invalid("inconsistent")`. A city in several regions of one country, with no region named, gives country and locality with `region: null`.
- Alternatives: Keep the first match.
- Why: SPEC-04 §4.4 ("exists in exactly one country → Ok"); C7.
- Reversible: yes

### D-0317 — A structured address without `addressCountry` is read as text
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: It is read as the text "locality, region" through the text rules.
- Alternatives: Decline it.
- Why: The text rules already resolve or decline homonyms (§4.4).
- Reversible: yes

### D-0318 — `jobLocationType` is read as JSON-LD allows
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: A string, an array of values, or a node object with `@id`; any one TELECOMMUTE value makes the job remote. Any other shape is not remote and never raises.
- Alternatives: Accept strings only.
- Why: JSON-LD 1.1 §4.1 and §4.3; SPEC-04 §4.7 (normalizers never raise on bad input).
- Reversible: yes

### D-0319 — One review per PR; `MERGE AFTER FIX` is not re-reviewed
- Date: 2026-10-13 · Spec/PR: workflow (#63) · Status: decided (owner)
- Decision: Each PR gets one review once complete and green. With `MERGE AFTER FIX` the implementor makes the fixes, gets CI green and comments `READY`; no second review.
- Alternatives: The same reviewer ticks off the fixes.
- Why: Owner choice, 2026-10-13.
- Reversible: yes

### D-0320 — The browser holds both body caps, at storage
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 10 (#64) · Status: decided
- Decision: The browser fetch holds the navigation body to `max_body_bytes` (its size on the wire, `Request.sizes()`) and to `max_decompressed_bytes`; an oversize body is a `body_cap` error with no capture body (INV-30). Both are checked after the response finishes and before anything is kept: Patchright has no streaming read, so Chromium's own limits bound the memory. Supersedes D-0252's size cap.
- Alternatives: Stream the body through CDP `Fetch.takeResponseBodyAsStream` (a larger change; a possible follow-up row).
- Why: INV-30, and the same two caps as the HTTP and JSON fetchers.
- Reversible: yes

### D-0321 — JSON-fetch cookies match on the hop's host name
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 10 (#64) · Status: decided
- Decision: `fetch_json` keeps cookies in a per-fetch jar matched on each hop's host name, with host-only cookies kept to their host (RFC 6265 §5.3 step 6, §5.4); httpx's own jar, which would match on the pinned address, refuses every cookie.
- Alternatives: Drop cookies on every hop (also meets INV-29, but differs from the other fetchers); pin the address at the connection layer so httpx's jar sees host names (a larger change).
- Why: INV-29. `Domain=` uses the stdlib's heuristic rather than public-suffix data; a follow-up row can add it.
- Reversible: yes

### D-0322 — `equal` is reflexive and symmetric for every JSON value
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: Identical values are always equal, whatever their shape; each type's `equal` and `dispatch.equal` start from that.
- Alternatives: Refuse values of the wrong shape, as the old object rule did for unknown keys.
- Why: Eval compares hand-entered labels, and a non-reflexive equality breaks the multiset match.
- Reversible: yes

### D-0323 — Location equality also compares `remote_flag`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: Country, casefolded locality, region only when both have one (§4.5), and `remote_flag`.
- Alternatives: Only §4.5's three parts.
- Why: A remote job and an on-site one in the same country differ; the conservative reading.
- Reversible: yes

### D-0324 — GTINs compare in the GS1 14-digit form
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `identifier.equal` left-pads GTIN-8/12/13 with zeros to 14 digits; other schemes compare exactly.
- Alternatives: Exact (§4.5).
- Why: D-0287 left this to PR 9; GS1 General Specifications §3.3.2.
- Reversible: yes

### D-0325 — List `normalize`: a single value is a list of one; reasons in `Ok.reasons`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: With no item `Ok`, the list is `Ambiguous("no_item")` if any item was ambiguous, else `Invalid("no_item")`; dropped items are reported as `<path>: <reason>`.
- Alternatives: Refuse non-lists; pick an item's options.
- Why: JSON-LD 1.1 §4.3.1 treats a value and a one-element array alike; options for a whole list would be a cross product.
- Reversible: yes

### D-0326 — Object `normalize` ignores unnamed keys and treats `null` as missing
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: The value holds only the sub-fields that normalized; a required one that declines declines the object.
- Alternatives: Refuse extra keys; emit nulls.
- Why: Structured sources carry `@type` and more; JSON-LD drops nulls.
- Reversible: yes

### D-0327 — The labeling API returns `FieldSpec` in `PageDetail.fields`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `FieldShape` goes (D-0167); `eval` uses `FieldSpec` and `dispatch.equal`; the TS client is regenerated.
- Alternatives: Keep a separate shape model.
- Why: One model for schema fields (C8); the response is a superset of the old one.
- Reversible: yes

### D-0328 — `type:period` phrases are "per <unit>" per language
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `vocab/type/period/en.json`; the solidus form `/<unit>` takes the phrase's last word; only the page's languages are read (all when it states none).
- Alternatives: Keep English "per" in code.
- Why: C4 and §9: language-tagged vocabularies; the solidus is SI/ISO 80000-1 notation for "per". Closes D-0280's follow-up.
- Reversible: yes

### D-0329 — url percent-decodes a domain host and refuses forbidden domain code points
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `Invalid("forbidden_host_code_point")`, or `Invalid("unparsable")` when the host decodes to invalid UTF-8.
- Alternatives: Keep the host percent-encoded.
- Why: WHATWG URL Standard, host parsing.
- Reversible: yes

### D-0330 — Python complexity check: complexipy
- Date: 2026-10-13 · Spec/PR: owner-directed, C11 amendment (#65) · Status: decided
- Decision: complexipy 8 (MIT, no dependencies) measures SonarSource cognitive complexity for backend `src`, `tests`, `migrations` and `tools/`. The limit of 15 is set only in `[tool.complexipy]` (backend/pyproject.toml). It runs with `--no-ignore` in the backend CI job, `make check-complexity` and a pre-commit hook that runs from `backend/`.
- Alternatives: flake8-cognitive-complexity (adds flake8 next to ruff); radon/xenon (cyclomatic complexity, not cognitive).
- Why: it implements Sonar's metric, and one binary covers backend and tools. `no_size_gates` refuses its snapshot ratchet, report-only mode and any threshold given as a flag.
- Reversible: yes

### D-0331 — Frontend complexity rule: local Oxlint rule over oxlint-plugin-complexity
- Date: 2026-10-13 · Spec/PR: owner-directed, C11 amendment (#65) · Status: decided
- Decision: `frontend/lint/cognitive-complexity.js` is an Oxlint JS plugin built on oxlint-plugin-complexity 3.0.1's `createCognitiveVisitor` (MIT). It reports cognitive complexity above `max: 15` and nothing else.
- Alternatives: eslint-plugin-sonarjs (LGPL-3.0-only, avoided by CLAUDE.md, and an ESLint stack beside Oxlint); the plugin's own `complexity/complexity` rule (always gates cyclomatic complexity too, a second gate C11 doesn't allow); Oxlint's core `complexity` rule (cyclomatic only).
- Why: licence-clean, and it runs inside `vp check`. It is stricter than Sonar on React components, because it adds +1 per nested function and skips `a || literal` defaults and JSX `cond && <X/>`. `PageEditor` scored 49 here and 23 on Sonar.
- Reversible: yes

### D-0332 — The file-length warning covers source files only
- Date: 2026-10-13 · Spec/PR: owner-directed, C11 amendment (#65) · Status: decided
- Decision: `tools/file_length.py` counts tracked `.py`, `.js/.jsx/.mjs/.cjs`, `.ts/.tsx/.mts/.cts` and `.sh` files, except the generated `frontend/src/api/schema.d.ts`. It checks its own repository and takes no arguments, and runs in the `no-size-gates` job and `make check-size-gates`, not in pre-commit.
- Alternatives: count every tracked file, documents included.
- Why: the owner's rule is about splitting code by meaning (C8); documents and generated files have no logical split.
- Reversible: yes

### D-0333 — Gate refs are passed after `--end-of-options`
- Date: 2026-10-13 · Spec/PR: owner-directed, Sonar fixes (#65) · Status: decided
- Decision: `commits_on` runs `git rev-list --end-of-options <ref> --`, so a ref that starts with `-` fails as an unknown revision instead of acting as an option. Extends D-0193.
- Alternatives: refuse refs that start with `-` in Python.
- Why: git's own end-of-options marker covers every option form.
- Reversible: yes

### D-0334 — Page text is rendered from the tree; `ParsedPage` caches it
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: `content.text.render(root)` returns the cleaned text and the shown attribute values in one walk of the selectolax tree. `ParsedPage.cleaned_text` and `ParsedPage.visible_values` cache the result; SPEC-05 §4.1 writes these as `cleaned_text(page)` and `visible_values(page)`.
- Alternatives: functions that take the page, which need a circular import and let a caller skip the cache.
- Why: one walk, one cache, one import direction.
- Reversible: yes

### D-0335 — Inline text joins as rendered
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: text nodes are concatenated, and whitespace collapses as CSS Text 3 §4.1 collapses it, with Unicode White_Space as the collapsible set (as SPEC-04 collapses). Table cells are separated by a space; line boxes and `br` by `\n`. SPEC-05 §4.4's "inline text joined by space" is read this way.
- Alternatives: a space between every inline node, which turns `$<span>19</span>` into `$ 19`, text that is not on the page.
- Why: grounding (INV-12) needs verbatim page text.
- Reversible: yes

### D-0336 — Visibility index entries are lines, not runs
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: the index holds every cleaned-text line, plus the `alt`, `title`, `value` and `content` attributes of visible elements, in the SPEC-04 text form. `visible(value)` is a substring match that doesn't split a word, with letters and digits as an approximation of UAX #29 word boundaries.
- Alternatives: exact membership of a run, which misses values split across inline elements.
- Why: lines contain every run. Matching whole words keeps `9.99` from matching inside `19.99`.
- Reversible: yes

### D-0337 — The hidden set comes from the HTML Standard
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: content counts as hidden when it is one of:
  - the HTML Standard rendering section's "Hidden elements", which include `head`, `title`, `meta`, `input[type=hidden]` and a closed `dialog`;
  - `noscript` and `svg`, from SPEC-05 §4.4;
  - `iframe`, whose content is raw text.

  `visibility` is inherited, and a descendant with `visible` is shown again (CSS 2 §11.2). As a result, `meta[content]` is never in the index.
- Alternatives: only the elements §4.4 lists.
- Why: a standard decides what is hidden, not a list grown page by page (C2, C4).
- Reversible: yes

### D-0338 — One decode for both parsers
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: `storage.capture_bundle.decode_body` decodes the body once, in the Content-Type charset, else UTF-8 (as D-0213); the labeling view uses it too. lxml gets the decoded text re-encoded as UTF-8 with that encoding named, so an XML encoding declaration doesn't break it. An empty document gives an empty `html` element.
- Alternatives: give each parser the raw bytes.
- Why: lexbor decodes bytes wrongly (non-ASCII came out as U+FFFD), and both parsers must read the same characters.
- Reversible: yes

### D-0339 — Node paths: absolute indexed XPath in the selectolax tree
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 1 (#67) · Status: decided
- Decision: `TextRun.node_path` and `ScriptBlock.xpath` are XPath 1.0 location paths into the selectolax (HTML-standard) tree, with every step indexed (`/html[1]/body[1]/div[3]`). A tag that is not an NCName (`o:p`) gets `*[name()='o:p'][n]`. One formatter, `content.text.xpath_step`, builds every step. A path may not resolve in `lxml_tree`, because libxml2 builds HTML trees differently (no implied `tbody`, different handling of misnested tags).
- Alternatives: paths computed in the lxml tree, which would need lxml for every page.
- Why: a path must name the tree its text came from.
- Reversible: yes

### D-0340 — Row-level readiness
- Date: 2026-10-13 · Spec/PR: run-plan · Status: decided
- Decision: a row is ready when the code it touches is merged, or when what it needs is fully specified (a frontend row may mock spec-defined API shapes), even if its spec's other listed dependencies aren't done. Rows within one spec still run in order.
- Alternatives: spec-level readiness only.
- Why: spec-level dependencies left worker slots idle while the first rows of SPEC-07, SPEC-06 and SPEC-12 needed nothing from SPEC-05 (the owner asked about the frontend).
- Reversible: yes

### D-0341 — No custom design system
- Date: 2026-10-13 · Spec/PR: owner-directed · Status: decided (owner)
- Decision: HeroUI v3 as it is. Every visual value lives in `src/app/theme.css`, so a visual change is a one-file change. No wrapper components, inline styles, raw colors, palette utilities or arbitrary values. A CI check follows.
- Alternatives: a drafted design system; an owner-supplied design.
- Why: owner instruction.
- Reversible: yes

### D-0342 — Connect accepts the key without a probe request
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: The Connect screen stores the key as entered; the first 401 drops it and shows the problem on `/connect`.
- Alternatives: probe `GET /v1/schemas` (not in `openapi.json` yet, so untyped); a key-check endpoint (public API change, escalation).
- Why: The most conservative reading.
- Reversible: yes

### D-0343 — `ProblemSummary` is narrowed by hand until the generated schema has the problem type
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: `api/problem.ts` reads `title` and `detail` from an `application/problem+json` body; replaced by the generated type once SPEC-07's problem schema is in `schema.d.ts`.
- Alternatives: wait for SPEC-07 PR 1.
- Why: SPEC-12 §4.1's "no hand-written DTO" targets endpoint shapes; this reads two RFC 9457 members.
- Reversible: yes

### D-0344 — Labeling routes stay outside `RequireKey`
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: Only screens that call the API with the key sit behind the key gate; the labeling routes do not.
- Alternatives: gate them (their loaders take no key and would still run).
- Why: The eval API is unauthenticated (SPEC-03 §4.10); SPEC-12 PR 9 owns the labeling integration.
- Reversible: yes

### D-0345 — First shared compositions: `PageHeader` and `ProblemAlert`
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: `src/components/PageHeader` (h1 and badges left, primary actions right) and `ProblemAlert` (HeroUI `Alert`) are the one way to show a page title and an API problem; the existing screens' titles use `PageHeader`.
- Alternatives: per-screen headings and error markup.
- Why: Owner rule D-0341 and "one way per recurring job".
- Reversible: yes

### D-0346 — Usage is committed in its own transaction
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `MeteredClient` holds an `AsyncEngine` and records each call's usage with `engine.begin()`, not on the caller's connection; a caller must not hold an uncommitted write to the job row when it calls the client.
- Alternatives: Return usage in a result for the handler to record; catch provider errors in handlers.
- Why: Closes the ACTIVE.md note for SPEC-06 for every caller at once; the typed exceptions (§4.7) can propagate without losing usage (D-0151's concern).
- Reversible: yes

### D-0347 — Only answered LLM calls are charged
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: A provider error records no usage; an invalid reply that is retried is two charged calls.
- Alternatives: Charge every attempt.
- Why: A failed call has no token counts and no cost; the budget is checked before each attempt either way.
- Reversible: yes

### D-0348 — No LLM budget or usage without a job
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `job_id=None` (eval pre-fill only, SPEC-06 §4.2) skips the budget check and usage rows; `usage_event.job_id` is NOT NULL.
- Alternatives: A synthetic job for pre-fill.
- Why: Matches the spec's field comment; SPEC-06 PR 5 revisits if pre-fill needs metering.
- Reversible: yes

### D-0349 — The root output schema is a closed object
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `LLMRequest` refuses an `output_schema` whose root is not `{"type": "object", "additionalProperties": false}`, including an omitted `additionalProperties`.
- Alternatives: Refuse only an explicit `additionalProperties: true` (§4.6's literal wording).
- Why: An omitted keyword allows extra properties too, which is what §4.6 guards against; the most conservative reading.
- Reversible: yes

### D-0350 — `request_hash` keeps SPEC-03's key
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: sha256 of the canonical JSON array (prompt_kind, model_class, system, user, output_schema), excluding `max_output_tokens` and `job_id`; `request_key` renamed `request_hash` and moved to `llm.client`.
- Alternatives: Hash the concrete model (§4.2's wording).
- Why: The provider picks the model after the request exists, and existing recordings keep their keys.
- Reversible: yes

### D-0351 — `jsonschema` for LLM output validation
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 1 (#69) · Status: decided
- Decision: `jsonschema` (MIT) validates replies against draft 2020-12 schemas; `types-jsonschema` (Apache-2.0) is a dev dependency for mypy.
- Alternatives: A hand-written validator.
- Why: The standard implementation; licence-clean.
- Reversible: yes

### D-0352 — Locator grammar
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: decided
- Decision: Locator address parts split on `:` and the last part takes the rest (XPath, JSONPath, CSS and `og:` names hold `:`); `js_state` splits after the first `script[n]` step, which `ParsedPage` ends a script path with. Indices are ASCII digits without a leading zero, a `text:` span is non-empty (`start < end`), JSONPath starts with `$` (RFC 9535) and XPath with `/`.
- Alternatives: Escaping `:` inside parts.
- Why: Every SPEC-05 §4.3 form stays readable as written, and each locator has one spelling.
- Reversible: yes, until collectors persist locators

### D-0353 — `collect` sits above `content` in the layering
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: decided
- Decision: `collect` and `content` were independent siblings in `.importlinter`; `collect` now sits one layer above `content`.
- Alternatives: A page protocol inside `collect`.
- Why: SPEC-05 §4.1 and INV-26: every collector takes the `ParsedPage`.
- Reversible: yes

### D-0354 — Extraction model shapes
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: decided
- Decision: `Candidate.raw` is SPEC-04's `Raw` (any JSON value: JSON-LD prices are numbers), not `str | dict | list`; sequences are tuples; `FieldSet = dict[str, FieldOutcome]`; `LLMCallRecord` has SPEC-06 §4.2's fields; `Evidence` moves to `resolve.types`. An unpublished field holds no value and states a reason; `blocked`/`shell`/`not_found` results have no candidates and no fields (INV-11); an `error` result has no fields but keeps its candidates (§4.14).
- Alternatives: The spec's literal annotations.
- Why: The most conservative reading that the later rows can rely on.
- Reversible: yes

### D-0355 — Derived `url` values and INV-22
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: needs-owner
- Decision: Question: INV-22 requires `evidence`, `source_kind` and `locator` on every published field, but the `canonical_link` and `final_url` derivations (SPEC-05 §4.8, D-0019) have no candidate, no §6 `SourceKind` and no §10 bucket. Options: (a) a `derived` source kind and evidence bucket, with locators for the link and the final URL (ARCHITECTURE §6/§10 and a migration); (b) exempt `derived_by` fields from those INV-22 attributes; (c) keep a derived `url` in `field_meta` only. Recommendation: (a). Blocked: SPEC-05 PR 7 and PR 8. The models enforce INV-22 as written.
- Alternatives: See options.
- Why: Every published value keeps its provenance and is calibrated like any other bucket.
- Reversible: yes

### D-0356 — Theme-only check as a Python tool with an import allow-list
- Date: 2026-10-13 · Spec/PR: owner direction (#71) · Status: decided
- Decision: `tools/theme_only_check.py` scans tracked `frontend/src` files line by line with regexes. The UI-import rule is an allow-list of runtime packages; a new runtime dependency is added to it in the PR that adds it to package.json.
- Alternatives: An Oxlint JS plugin rule (can't see `.css` files or class strings without extra parsing); a deny-list of named UI libraries (grows one library at a time, C4).
- Why: One stdlib script covers the CSS-file rule and the TSX rules, runs in CI, make and pre-commit, and names its structural property next to each pattern (C2).
- Reversible: yes. Delete the tool and its three call sites

### D-0357 — Layout sizes as Tailwind `@theme` variables
- Date: 2026-10-13 · Spec/PR: owner direction (#71) · Status: decided
- Decision: Sizes outside Tailwind's default scale are `@theme` variables in theme.css (`--container-content: 80rem`, `--height-page-view: 70dvh`), used through the utilities Tailwind generates for them.
- Alternatives: `max-w-(--var)` references in class strings; the default `max-w-7xl`.
- Why: The screen names a role and theme.css holds the value, so a resize is a one-file edit.
- Reversible: yes

### D-0358 — One icon set: @gravity-ui/icons 2.22.0 (MIT)
- Date: 2026-10-13 · Spec/PR: owner direction (#71) · Status: decided
- Decision: Status display needs an icon (DESIGN.md: never color alone) and `@heroui/react` exports none, so `@gravity-ui/icons`, the set HeroUI's documentation uses, is added, pinned exact at a release older than two weeks.
- Alternatives: Unicode glyphs (inconsistent rendering); a second icon library.
- Why: Icons only, no components or CSS, so it is not a second UI layer.
- Reversible: yes. Swap the five imports in `StatusLabel`

### D-0359 — Linear as the layout and pattern reference
- Date: 2026-10-13 · Spec/PR: owner direction (#71) · Status: decided
- Decision: DESIGN.md names Linear as the reference for layout, density and pattern choices only (left sidebar, list- and table-first screens, compact page header, subtle borders, neutral palette with one accent, keyboard-first, few modals). No styles or brand assets are copied; visual values stay HeroUI defaults, with any tweak in theme.css.
- Alternatives: Stripe's dashboard; no named reference.
- Why: The owner asked for one reference with consistency as the goal; Linear's table-first application UI matches the operator screens (SPEC-12). Prose only, so C3 is untouched.
- Reversible: yes. Edit the Reference section and the Patterns column

### D-0360 — Save notice is a toast; empty/off/missing states are EmptyView
- Date: 2026-10-13 · Spec/PR: owner direction (#71) · Status: decided
- Decision: The labeling save notice moved from an `<output>` in `LabelingPage` state to `toast.success` inside `useSave`. The off, missing and no-pages states use `EmptyView`; save/conflict errors use `ProblemAlert`/`Alert`.
- Alternatives: Keep the screen-local notice (a second way to notify).
- Why: One way per job (DESIGN.md, Patterns); the toast also outlives the editor's remount.
- Reversible: yes

### D-0361 — `create_app` keeps `eval_ui` and reads settings at startup
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `create_app(eval_ui=None)`; the app lifespan reads `DatabaseSettings()` and creates the one engine the routers share (`app.state.database`).
- Alternatives: `create_app(settings)` as SPEC-07 §4.1 sketches.
- Why: `crawlerai openapi` and uvicorn's `--factory` build the app without a database or object store configured.
- Reversible: yes

### D-0362 — Problem `instance` is the request path; no request-id middleware yet
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `Problem.instance` is the request path (RFC 9457 §3.1.5).
- Alternatives: A per-request id (`urn:uuid:…`) and an `X-Request-ID` header.
- Why: Nothing logs or reads a request id yet. When logging lands, switch `instance` to the request id (#70 review).
- Reversible: yes

### D-0363 — Unreadable capture of a labeling page is 500 `capture_unreadable`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `ObjectNotFound`/`CorruptBundle` from `get_bundle` in `GET /v1/eval/pages/{id}` answer 500 with type `capture_unreadable`.
- Alternatives: 404 `not_found`; the generic 500 problem.
- Why: The page exists; a missing or damaged stored object is the server's fault, and a distinct type tells the labeling screen why.
- Reversible: yes

### D-0364 — Problems for framework errors
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: Unknown path → `not_found`; other HTTP errors and unexpected exceptions → `about:blank` with the status phrase (RFC 9457 §4.2.1), message withheld on 500; `/healthz` without a database → 503 `unavailable`. These extend SPEC-07 §4.3's types for statuses it doesn't name.
- Alternatives: FastAPI's default bodies.
- Why: Every error the API answers is one shape the client reads.
- Reversible: yes

### D-0365 — `/healthz` reports `eval_ui`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: `GET /healthz` answers `{"status":"ok","eval_ui":bool}` after a `SELECT 1` bounded at 5 s; `eval_ui` is the plumbing field SPEC-12 §4.3 (D-0042) reads for its labeling nav.
- Alternatives: A separate endpoint for the flag.
- Why: One unauthenticated call tells the UI the API is up and which screens to show.
- Reversible: yes

### D-0366 — 422 problem declared per router; supersedes D-0210
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 1 (#70) · Status: decided
- Decision: Routers that take input declare `responses={422: PROBLEM_RESPONSE}` (the eval router does), replacing FastAPI's `HTTPValidationError` in OpenAPI; `/healthz`, which takes no input, declares none. The OpenAPI document is served at `/v1/openapi.json` (SPEC-07 §4.6). D-0210 (problems local until SPEC-07) is superseded.
- Alternatives: One app-level `responses={422: …}`, which also documents a 422 on `/healthz`.
- Why: The document should list only errors an operation can return.
- Reversible: yes

### D-0367 — The field shape is narrowed by hand until the generated schema has records
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 2 (#73) · Status: decided
- Decision: `src/api/field.ts` declares `FieldStatus`, `FieldResult` (`status`, `reason`, `value`) and `FieldTypeSpec`; replaced by the generated types once SPEC-07's record and schema DTOs are in `schema.d.ts`.
- Alternatives: Wait for SPEC-07 records.
- Why: Same reasoning as D-0343; it reads only the documented SPEC-07 §4.4 members.
- Reversible: yes

### D-0368 — A published value that formats to nothing renders as "—"
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 2 (#73) · Status: decided
- Decision: An empty string or empty list shows "—" (named "No value"), and `remote_flag=true` shows as the text `remote` in a location.
- Alternatives: Render an empty span.
- Why: DESIGN.md forbids rendering an empty string; the flag is a server value shown as text, not inferred.
- Reversible: yes

### D-0369 — Field status tones
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 2 (#73) · Status: decided
- Decision: published → success, missing → neutral, abstained → warning, conflict → danger, in `FieldStatusBadge` next to the status type.
- Alternatives: Other mappings.
- Why: DESIGN.md "Status display": each domain maps its values to one tone, once.
- Reversible: yes

### D-0370 — Anthropic calls send no `temperature`
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: The Anthropic provider sends no sampling parameters; Gemini sends `temperature: 0`. Narrows D-0023's "temperature 0" to the providers that accept it.
- Alternatives: Send `temperature: 0` everywhere (§4.2).
- Why: Claude Haiku 5.5 and Sonnet 5.5 reject non-default sampling values with a 400; replay determinism comes from the recorded cache (INV-10), not from temperature.
- Reversible: yes

### D-0371 — Failover is per call, from the first provider, at most once
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: Each provider call, including the one validity retry, asks the configured providers in order; a client has one or two providers. A call that does not answer is not charged (D-0347); the budget is checked once before each call.
- Alternatives: Keep using the provider that answered for the retry.
- Why: Simplest reading of "failover to the next provider once" (§4.2); `LLMResponse.provider` names the one that answered.
- Reversible: yes

### D-0372 — Only "no answer" fails over
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: 408, 429, 5xx (RFC 9110, RFC 6585), timeouts and connection errors become `ProviderError`; other statuses (bad key, unknown model, refused schema) propagate as the SDK's exception.
- Alternatives: Fail over on any error.
- Why: Another provider would not fix a misconfiguration; it should fail loudly.
- Reversible: yes

### D-0373 — SDK retries are off
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: Anthropic `max_retries=0`; Gemini without retry options (one attempt).
- Alternatives: Keep the SDKs' backoff retries.
- Why: They would multiply latency up to the 60/120 s timeouts and hide the failover the spec defines.
- Reversible: yes

### D-0374 — Default model ids in settings
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: fast: `claude-haiku-5-5`, `gemini-3.5-flash-lite`; strong: `claude-sonnet-5-5`, `gemini-3.8-flash`; each overridable by `CRAWLERAI_LLM_{FAST,STRONG}_MODEL_<PROVIDER>`.
- Alternatives: No defaults; `gemini-3.1-pro-preview` for strong.
- Why: Appendix C names Haiku/Flash-Lite-class and Sonnet-class models; Gemini Pro is a preview, 3.8 Flash is the current stable mid-tier model.
- Reversible: yes

### D-0375 — Provider settings and keys
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: `CRAWLERAI_LLM_PROVIDERS` is comma-separated, defaults to `anthropic,gemini`, and refuses duplicates and unknown names; keys are `CRAWLERAI_LLM_API_KEY_<PROVIDER>` (SecretStr); `providers_from_settings` refuses a listed provider without a key.
- Alternatives: The vendors' own env vars (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).
- Why: One `CRAWLERAI_*` namespace (SPEC-00 §4.4); no client is built half-configured.
- Reversible: yes

### D-0376 — LLM output token counts include thinking
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: Gemini `tokens_out` = candidates + thinking tokens; Anthropic's `output_tokens` already includes thinking; a Gemini response without usage metadata records 0.
- Alternatives: Candidate tokens only.
- Why: Thinking tokens are billed as output.
- Reversible: yes

### D-0377 — LLM provider SDK dependencies
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 2 (#74) · Status: decided
- Decision: `anthropic` (MIT) and `google-genai` (Apache-2.0), as SPEC-06 §4.1 names; `httpx` moved from dev to runtime and `httpx2` added (the providers catch their transport errors and take test clients).
- Alternatives: Raw HTTP.
- Why: The spec names the official SDKs.
- Reversible: yes

### D-0378 — Row-level readiness
- Date: 2026-10-13 · Spec/PR: none, workflow chore (#75) · Status: confirmed
- Decision: A row is ready when the code it touches is merged, or what it needs from unmerged work is fully specified, even if its spec's other dependencies or earlier rows aren't `done`. `/run-plan` §1.1, `/implement-pr` §0 and ACTIVE.md say so.
- Alternatives: A row waits until its spec's dependencies and earlier rows are `done` (the old rule).
- Why: The old rule left worker slots idle on rows whose inputs already existed.
- Reversible: yes — restore the old rule in the three places.
- Owner answer: owner direction, 2026-10-13.

### D-0379 — Grounding aligns one claim at a time
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 3 (#76) · Status: decided
- Decision: `align` takes one claim (`SpanClaim`) and returns `GroundedSpan | None`; role C maps it over its fields. Two occurrences equally near the claimed `start` resolve to the earlier one. An empty value is dropped. Offsets count code points of the cleaned text (Python `str` indices), as SPEC-05's `CleanedText` does.
- Alternatives: `align(values, text)` over a mapping (spec's sketch); dropping on a tie.
- Why: One value per call keeps the function independent of role C's output shape (detail fields vs listing rows); a fixed tie-break keeps replays deterministic (INV-10); an empty span holds no value and is not a valid `text:` locator.
- Reversible: yes

### D-0380 — Keyless requests are rate limited by client address
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 2 (#77) · Status: decided
- Decision: A request without a bearer key is rate limited by client address (trusted-proxy aware); with one, by `sha256(key)[:16]` as specified. Only authenticated routes are limited; `/healthz` and the eval API are not.
- Alternatives: limit only keyed requests; a per-address bucket on every request in addition to the per-key one.
- Why: keyless requests cannot be sent without limit, and INV-32's client address has a use; the second bucket would add a limit the spec doesn't define.
- Reversible: yes

### D-0381 — Trusted proxies and how forwarded hops are read
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 2 (#77) · Status: decided
- Decision: `CRAWLERAI_TRUSTED_PROXIES` is a JSON list of addresses or networks, empty by default. Hops are read right to left through trusted proxies; the first untrusted hop is the client; an unreadable hop (`unknown`, an obfuscated id, garbage) stops the walk at the last readable address. `Forwarded` is preferred to `X-Forwarded-For`.
- Alternatives: leftmost hop (client-controlled); a header-specific hop count.
- Why: RFC 7239 §8.1; the most conservative reading.
- Reversible: yes

### D-0382 — `apikey` CLI output and repeated revocation
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 2 (#77) · Status: decided
- Decision: `apikey create` prints JSON `{id, label, key}`; `apikey revoke` prints `{id, revoked}` (`false` when already revoked, keeping the first `revoked_at`) and exits 2 for an unknown id. The webhook secret is 32 random bytes in hex, drawn at creation and not printed.
- Alternatives: print the webhook secret too; reset `revoked_at` on a second revoke.
- Why: SPEC-10 owns how webhook secrets reach clients; revocation time is an audit fact.
- Reversible: yes

### D-0383 — OpenGraph field roles
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: A field's OGP role is the single property its `schema_org` path names on the root type (`Product.name` → `name`, `Offer.price+priceCurrency` → `price`); a path through another object (`Product.brand.name`) has none. So `og:title` maps to `Product.name` but not to `Product.brand.name`, though both end in `.name` (SPEC-05 §4.5). The same rule, with the field type, keys `og:image`, `og:url`, `product:availability` and `product:price:*`; a list field matches by its item type.
- Alternatives: The literal "ends in `.name`", which would propose the page title as the brand.
- Why: `og:title` is the title of the object the page describes, not of a related object; the most conservative reading. Review note: the root type is not checked, so `Organization.name` also gets `og:title`; revisit with ownership and intent (SPEC-05 PR 6).
- Reversible: yes

### D-0384 — Repeated OpenGraph properties
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: A repeated property gives a scalar field its first value and a list field every value in document order (`og:image` and `og:image:url` read as one property); the locator names the first value's property.
- Alternatives: One candidate per occurrence.
- Why: Open Graph protocol, "Arrays": the first tag is preferred in a conflict. Several candidates from one source would disagree with themselves at preference.
- Reversible: yes

### D-0385 — OpenGraph values are not translated
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: `product:price:*` becomes the money normalizer's structured form `{amount, currency}` from the first of each; a missing currency is left out, so the candidate declines (`no_currency`). `product:availability` passes through unchanged, so values outside the schema.org member names (`in stock`) are declined by the `schema:ItemAvailability` enum normalizer.
- Alternatives: An OGP-value → schema.org-member table in the collector.
- Why: Value translation belongs to the enum module (C7, C8); whether a vocabulary for OGP availability values is worth adding is measured on dev.
- Reversible: yes

### D-0386 — The Open Graph protocol is cited by name
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 5 (#79) · Status: decided
- Decision: Code cites the Open Graph protocol by name, not by its host, so `tools/site_literal_allowlist.txt` is unchanged.
- Alternatives: Allowlist the OGP host as a standards body.
- Why: The smallest change; no allowlist edit for one module.
- Reversible: yes

### D-0387 — Collector diagnostics
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: `CollectResult` gains `diagnostics: tuple[str, ...] = ()`. A JSON-LD block that is not JSON (including `NaN` and nesting the parser refuses) and a value the `Candidate` model refuses (nested deeper than its validator recurses) are skipped and named there.
- Alternatives: Log only.
- Why: SPEC-05 §4.5: a collector never raises and returns a diagnostic; the PR 2 model had no place for one.
- Reversible: yes

### D-0388 — schema.org scope in JSON-LD
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: A bare term (`Product`, `name`) is read as schema.org only under a schema.org context: the namespace as a string, `@vocab`, or an array of contexts, http or https, with or without the trailing slash. Full `http(s)://schema.org/` IRIs are read anywhere. A block with no context has no entities, and a remote context other than schema.org's is not fetched.
- Alternatives: Assume schema.org when there is no context.
- Why: JSON-LD 1.1 §4.1; the most conservative reading (C7).
- Reversible: yes

### D-0389 — JSON-LD entities and parents
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: Every object typed with a vocabulary type is an entity, at any depth. Its parent is the nearest enclosing entity; a node defined on its own takes the one entity that references it by `@id`, unless that would make a cycle; a node referenced from two or more entities has no parent. For references, the first definition of an `@id` wins. `Entity.kind` is the most specific listed type: the first one that no other listed type is a subtype of.
- Alternatives: Merge duplicate `@id` definitions (JSON-LD flattening).
- Why: The simplest rule that keeps entities a tree (SPEC-05 §4.6).
- Reversible: yes

### D-0390 — Entity URLs from JSON-LD
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: An entity's `urls` are its `url`, its own `@id`, its `mainEntityOfPage` (a string, or that node's `url`/`@id`) and its offers' `url`, canonicalized by the url normalizer. An `@id` with a fragment is left out.
- Alternatives: Include fragment `@id`s.
- Why: RFC 3986 §3.5: a fragment names part of a document, not a page; fragment `@id`s would all canonicalize to the page URL and make intent ambiguous.
- Reversible: yes

### D-0391 — Text standing in for a Thing
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: On a path ending in `.name` (`Product.brand.name`), a text value where the path expects a node (`"brand": "Acme"`) is taken as that thing's name.
- Alternatives: No candidate.
- Why: schema.org data model, "Conformance": text is accepted where a Thing is expected.
- Reversible: yes

### D-0392 — Structured-data candidate shapes and locators
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: Each value of an array property is its own candidate. A `list` field gets one candidate per node, holding all values and located at the first. A `+` path gives one object per value of the first property (`{"price": …, "priceCurrency": …}`), located at the first property; several second values stay an array, so the normalizer declines. JSON-LD locators are RFC 9535 normalized paths into the block as written (SPEC-05 §4.3 says "expanded graph"); a referenced node's values are located where it is defined. `null`, value objects holding a non-scalar, and arrays nested inside an array of values are not values.
- Alternatives: Locators into an expanded form; one candidate per list item.
- Why: Locators that read back the raw value from the capture (tested as a property).
- Reversible: yes

### D-0393 — schema.org vocabulary loading
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 3 (#78) · Status: decided
- Decision: `collect.schema_org_map.default_vocabulary()` reads `backend/data/schemaorg/schemaorg-all-https.jsonld` once and raises `VocabularyMissing` ("run `crawlerai data fetch`") when it is absent, as the gazetteer does. Tests use a synthetic vocabulary file in the same format.
- Alternatives: Derive and commit a type-hierarchy file.
- Why: One source for the vocabulary (the manifest pin, D-0018); CI never fetches.
- Reversible: yes

### D-0394 — `PUT /v1/schemas/{id}` must name the latest version
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: The body is the whole new document without name and version (`SchemaContent`). It becomes version latest+1 with `origin=user`, and the answer is 200 with the new row. If `{id}` is not the latest version, or is retired, the answer is 409 `conflict`, and the detail names the latest version's id. A concurrent insert of the same version is also 409. The registry's `new_version` takes `base_version` and raises `NotLatest`.
- Alternatives: Build silently on whatever is latest; PATCH-style partial changes.
- Why: An edit made to an old version would otherwise drop the versions added since without anyone noticing. PUT replaces the whole document (RFC 9110 §9.3.4).
- Reversible: yes

### D-0395 — `DELETE /v1/schemas/{id}` retires that one version
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: The answer is 204, and a repeated DELETE is also 204. Other versions keep their status. `PUT` doesn't retire the version it builds on. Retiring the latest version freezes the name; that is a follow-up (ACTIVE, from the #81 review).
- Alternatives: Retire every version of the name; retire the previous version on PUT.
- Why: The id names a version, and records and configs reference versions (§5.2, D-0029, D-0243).
- Reversible: yes

### D-0396 — Presets are read-only through the API
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: PUT or DELETE on an `origin=preset` row, and POST with a name from the preset files, answer 409 `conflict`.
- Alternatives: Allow both.
- Why: A `user` version under a preset's name would make the next `crawlerai schemas sync` raise `PresetConflict` (D-0242). Presets change only through their files (§5.3).
- Reversible: yes

### D-0397 — Problem type `conflict` (409)
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: Added to SPEC-07 §4.3's types for a name that is taken, a stale edit, or a change to a preset or retired schema.
- Alternatives: 422 `validation`.
- Why: The request is valid, but the stored state doesn't allow it (RFC 9110 §15.5.10). This extends §4.3 the way D-0364 did.
- Reversible: yes

### D-0398 — `crawlerai.services` is its own layer under `api | mcp_server`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 7 (#81) · Status: decided
- Decision: Added to the layering contract and to the forbidden-import source lists. Input models (`NewSchema`, `SchemaContent`) live in the service, so REST and MCP share them. `GET /v1/schemas` answers `{items: [...]}` sorted by name then version, with optional `name` and `status` filters. POST answers 201 with `Location`.
- Alternatives: Services beside `crawl | eval`; input models in `api.dto`.
- Why: SPEC-07 §4.7 says REST and MCP call the same functions.
- Reversible: yes

### D-0399 — INV-26's count for the content formats counts parses of the capture body
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: trafilatura's readability fallback parses readability's own summary, a new document with only the main content, and that parse is not counted. The test tells the two apart by a `<head>` JSON-LD block that readability's output never contains.
- Alternatives: `fast=True`, which skips the fallback and changes the extraction §4.5 specifies; counting every lxml construction, which this fallback always fails.
- Why: INV-26 is about the capture body. A mutation check shows the test catches a re-parse of the body.
- Reversible: yes

### D-0400 — `normalize.url.canonical` and `canonical_url` are public
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: `canonical(raw, base)` is public, and `canonical_url(raw, base) -> str | None` wraps it for callers outside a field. The content formats (`links`, `content.dom`, `metadata.canonical`) call it directly, not through the dispatcher.
- Alternatives: `dispatch.normalize` with a synthetic `FieldSpec(url)` and a `Context` (it needs a `captured_at` the formats don't have); a copy of the URL rules in `content` (C8).
- Why: A link is not a field value, and one module owns the URL rules (C8).
- Reversible: yes

### D-0401 — The `html` format cleans a clone of the selectolax tree
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: `LexborHTMLParser.clone()` (a copy, no parse), serialized by lexbor. Every attribute whose value parses as a `javascript:` URL is removed, whatever its name; comments stay. The eval sanitizer uses the same `content.html.remove_scripting_attributes`.
- Alternatives: A deep copy of the lxml tree (libxml2's HTML4-era tree building); a fixed list of URL attributes.
- Why: The shared tree stays as parsed (INV-26), lexbor follows the HTML standard, and one function serves both sanitizers.
- Reversible: yes

### D-0402 — `metadata` member rules
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: `og` reads `meta[property]`, else `meta[name]`, and the first value of each key wins. `structured_data_types` lists the JSON-LD `@type` values, then the microdata `itemtype` tokens; an IRI is reduced to its last path segment or fragment, and a JSON-LD term is kept as written. `@type` inside `@context` and on value objects is not a node type. A JSON-LD block that doesn't parse is skipped. `language` is the stripped `<html lang>`, else `og:locale` as written. Absent members are `None` or empty.
- Alternatives: OGP `property` only; full type IRIs; expanding JSON-LD contexts.
- Why: `name` is read the way SPEC-05 §4.2's `meta:` locator reads it; the reduced names match §4.4's example; resolving a context is the JSON-LD collector's job (SPEC-05).
- Reversible: yes

### D-0403 — `markdown` is `""` when there is no main content
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 3 (#80) · Status: decided
- Decision: trafilatura finding nothing gives `""`, not `None`.
- Alternatives: `None`.
- Why: The §4.4 response shape gives `markdown` as a string.
- Reversible: yes

### D-0404 — Microdata and RDFa Lite items
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 4 (#83) · Status: decided
- Decision: An item is an element with `itemscope` or `typeof`; an element with both is one item, with the types of both syntaxes. Both syntaxes' property elements belong to their nearest enclosing item; `itemref` adds microdata properties per the HTML Standard's crawl (each element once; the item's own element excluded). A nested item (a property element that is an item) is its holder's child; an item that is no property is top-level, so DOM nesting alone gives no parent. A parent is the nearest entity up a chain of single holders (untyped items skipped), unless that would make a cycle; an item that two items hold has no parent.
- Alternatives: Parent by DOM nesting; read the two syntaxes as separate item sets.
- Why: The HTML Standard's top-level and nested items; one entity per element keeps the `microdata:<xpath>` ids unique. A property never crosses into another item's scope, so a related item's values are never attributed to the outer item.
- Reversible: yes

### D-0405 — Vocabulary scope of microdata and RDFa names
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 4 (#83) · Status: decided
- Decision: A short `itemprop` name is a schema.org term only in an item with a schema.org `itemtype` (http or https). An untyped item is in no vocabulary, even when nested in a schema.org item. RDFa terms resolve under a schema.org `vocab` in scope (an empty `vocab` clears it), and the `schema:` prefix of the RDFa 1.1 initial context is read. Full schema.org IRIs are read anywhere. `prefix` declarations are not read.
- Alternatives: An untyped nested item inherits its holder's vocabulary.
- Why: The HTML Standard ties names to the item's type; the most conservative reading (C7). RDFa Core 1.1 §7.4.3 and the initial context.
- Reversible: yes

### D-0406 — Microdata values and item JSON
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 4 (#83) · Status: decided
- Decision: Values follow the HTML Standard's "Values" (`meta` content; `src`/`href`/`data` URL attributes as written, the empty string when absent; `data`/`meter` value; `time` datetime; else text content). RDFa values: `content`, then `time` datetime, then `resource`/`href`/`src`, then text content. URLs are kept as written; the url normalizer resolves them against the base URL. An item value's raw is its JSON-LD-shaped object (`@type`, `@id`, then each property, one value bare and several as an array), what the normalizers read. Each item appears once in that object, so `itemref` cycles and shared items keep it as large as the page. The locator of an item value is its element. A blank `itemid` or `resource` names nothing.
- Alternatives: The HTML Standard's microdata-to-JSON form (`{"type", "properties"}`), which the normalizers do not read; resolved URLs as raw.
- Why: The same raw shapes as JSON-LD, so one normalizer reads both; raw values match the capture.
- Reversible: yes

### D-0407 — `POST /v1/scrape` is declared by hand until SPEC-07 generates it
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: `src/api/scrape.ts` declares the SPEC-07 §4.3–4.4 request and response and adds the route to the generated `paths` by module augmentation, so the call uses the authenticated client and its 401 handling; deleted once `make api-client` generates it.
- Alternatives: Wait for SPEC-07 PRs 4–6; raw `fetch` outside the client (loses the 401 middleware).
- Why: Row-level readiness (D-0378); same reasoning as D-0343 and D-0367.
- Reversible: yes

### D-0408 — Empty scrape limits are left to the server
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: Empty `max_age`, `timeout_s` and `budget.llm_calls` are left out of the request; `fetch.method_hint` starts at `auto` (FetchPolicy's default).
- Alternatives: Prefill SPEC-07's example values.
- Why: The UI does not choose server defaults (§3).
- Reversible: yes

### D-0409 — Record field types come from the schema, else the value is shown as sent
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: Field types come from the response's draft schema, the inline schema sent, or `GET /v1/schemas/{schema_id}`; when none is readable, `FieldValue` gets `spec: null` and shows a string as is and anything else as JSON.
- Alternatives: Infer the type from the value (a client heuristic, §3).
- Why: Most conservative; review of #82 found the earlier text fallback hid published lists.
- Reversible: yes

### D-0410 — Scrape picks a schema by id; "Edit as schema" is SPEC-12 PR 4
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: The Scrape form takes a stored schema's id as text; a drafted schema is shown with its fields, and adopting or editing it is left to the Schemas screen.
- Alternatives: A schema list in the form; an "Edit as schema" link to a screen that does not exist yet.
- Why: SPEC-12 PR 4 owns schema editing and draft adoption.
- Reversible: yes

### D-0411 — Outcome tones
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: extracted → success, partial and shell → warning, not_found → neutral, blocked and failed → danger, in `components/OutcomeLabel` next to the outcome type.
- Alternatives: Other mappings.
- Why: DESIGN.md "Status display": each domain maps its values to one tone, once.
- Reversible: yes

### D-0412 — Entity `via`: the parent's schema.org property holding it
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: `Entity.via` is the schema.org property of the parent entity that holds the entity: a full schema.org IRI anywhere, or a bare term under a schema.org context. Through untyped objects it is the property on the entity, not on the object in between. A node referenced by `@id` takes the property of its one reference, and gets none if its one referrer references it under two properties. Microdata: the one name the holder's element gives the item (or the untyped item on the way); an element naming two properties names none.
- Alternatives: Exclude every primary entity nested in another primary entity; parse the property out of the locator.
- Why: §4.6 names relation properties, and an `@id` reference or a microdata item doesn't show its property in its id.
- Reversible: yes

### D-0413 — Primary types are the required fields' roots without Offer
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: The root types of the required fields' `schema_org` paths, without Offer (and its subtypes) unless Offer is the only root. `required_groups` members don't count.
- Alternatives: Include Offer, which would make every Offer of the product a competing candidate.
- Why: An Offer belongs to the item it offers (schema.org `offers`/`itemOffered`; §4.5, §4.7).
- Reversible: yes

### D-0414 — Intent excludes entities in lists and under relation properties
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: An entity is excluded when any ancestor is an `ItemList` or `ListItem` (or a subtype), or when somewhere up its chain it sits under `isRelatedTo`/`isSimilarTo` of a primary entity. A primary entity nested through another property stays a candidate, and the URL decides.
- Alternatives: Exclude every nested primary entity.
- Why: The literal reading of §4.6 step 1.
- Reversible: yes

### D-0415 — All primary entities excluded is `intent_ambiguous`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: When primary-type entities exist but all of them are excluded, the result is `AmbiguousTarget(candidates=())`, not the `page` entity. `page` is the target only when the page has no primary-type entity at all.
- Alternatives: Fall back to `page`.
- Why: §4.6 step 4 says "primary type absent", and a list of products is not a page about one of them. This is the conservative reading.
- Reversible: yes

### D-0416 — Only an Offer child of the target is the target's
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: `owned_by` accepts an Offer (or subtype, so also AggregateOffer) whose parent is the target. An Offer nested inside an AggregateOffer is not owned.
- Alternatives: Any Offer descendant.
- Why: §4.5 and §4.7 say "an Offer child of the target". Atomic offers and `lowPrice` belong to PR 7.
- Reversible: yes

### D-0417 — Page-level candidates belong to the target whatever the field's root
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 6 (#85) · Status: decided
- Decision: Page-level candidates (OG, meta, text) belong to the target whatever the root type of the field's path, so an `Organization.name` field still gets `og:title`.
- Alternatives: Own page-level candidates only for fields rooted at the target's type.
- Why: §4.6 step 4 attributes page values to the target without a type condition; this answers D-0383's review note. Measure on dev before changing it.
- Reversible: yes

### D-0418 — js_state and xhr admit against the other kinds' candidates
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: `js_state` and `xhr` implement `AdmittingCollector.collect(page, schema, ctx, others) -> Admitted`, not `Collector`. `Admitted` holds candidates and diagnostics but no entities: its candidates name entities of `others`, or `page`. PR 9 runs these two after the other collectors, passes their candidates, and adds the admitted candidates to the merged graph.
- Alternatives: Return a `CollectResult` that copies the referenced entities (duplicate ids on merge).
- Why: Admission depends on the other kinds' candidates (§8.1), and a `CollectResult` must hold every entity its candidates name.
- Reversible: yes

### D-0419 — An admitted value is owned by the entity it equals, else by the page
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: A value admitted by equality is owned by the entity of each candidate it equals, one candidate per entity. A value admitted by visibility is owned by `page`.
- Alternatives: Own every admitted value by `page`.
- Why: A state value equal to a related product's price is evidence about that product. Owning it by `page` would put it on the target and cause spurious conflicts.
- Reversible: yes

### D-0420 — A field with any other-kind candidate admits by equality only
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: A field that has any candidate from another source kind, even one that did not normalize, admits state values by equality only. So a value both equal and visible is not independent. A candidate of the same kind is never an anchor.
- Alternatives: Count only valid candidates; let visibility make an equal value independent.
- Why: The conservative reading of §4.5 ("leaves are considered only for fields still lacking a candidate or for agreement checks"): fewer admissions, and no independent vote for a value that only agrees.
- Reversible: yes

### D-0421 — State is a script's first assignment, and only an object or array
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: js_state reads a `<script type="application/json">` whole. In any other non-JSON-LD script it reads only the first `window.<ident> =` or `var|let|const <ident> =` assignment, and only when its JSON value is an object or array. Booleans and `null` are never candidates.
- Alternatives: Every assignment in a script; scalar initializers.
- Why: The locator addresses one document per script. A scalar initializer is a script variable, not state. `true`, `false` and `null` are values of no field type.
- Reversible: yes

### D-0422 — `ParsedPage` carries the captured network bodies
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 10 (#86) · Status: decided
- Decision: `ParsedPage(html, network=())`; `ParsedPage.of` passes `bundle.network`.
- Alternatives: Pass the bundle to the xhr collector.
- Why: Collectors read the `ParsedPage`, never the bundle (§4.1, INV-26).
- Reversible: yes

### D-0423 — Scrape formats only for a reached page
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: Formats are returned only when `block_class` is ok (outcome `extracted`); a blocked, shell, not_found or failed page answers 200 with its outcome and no format members.
- Alternatives: Return the formats of whatever body came back.
- Why: §4.8: no partial formats on failure; a block page's markdown would read as content.
- Reversible: yes

### D-0424 — Without `records` a reached page is `extracted`
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: A scrape without `records` whose page was reached has outcome `extracted`.
- Alternatives: `links_only` (not in §4.4's outcome list).
- Why: §4.4 lists the outcomes a scrape returns; PR 5 adds `partial`.
- Reversible: yes

### D-0425 — A page robots.txt keeps from a scrape is `blocked`, without fetch members
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: A robots.txt disallow, or an unreachable robots.txt (RFC 9309 §2.3.1.4), gives outcome `blocked` (task `last_error` `robots` / `robots_unreachable`), and the answer's `capture_id`, `final_url`, `fetched_at` and `fetch` are `null`. The scrape screen hides them when null.
- Alternatives: A problem response; synthetic fetch members.
- Why: §4.8: a page not fetched is an outcome; these four are the only nullable additions to §4.4's shape.
- Reversible: yes

### D-0426 — Every SSRF rejection is a 422 `ssrf_rejected` problem
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: Any SSRF rejection, DNS failure included, is a 422 problem `ssrf_rejected` with the guard's reason as `detail`. A refused target is checked before the job is created; a refused redirect hop fails the job and stores no capture.
- Alternatives: 400; DNS failure as outcome `failed`.
- Why: INV-16; the guard fails closed, and one rule is simpler.
- Reversible: yes

### D-0427 — `records` refused until SPEC-07 PR 5; `max_age` accepted
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: `records` is refused with 422 until PR 5. `max_age` is accepted and every scrape fetches anew. `budget.llm_calls` defaults to 10 (§4.4's example).
- Alternatives: Accept `records` and ignore it; 501.
- Why: Never answer as though records were extracted; the frontend sends `max_age` when set.
- Reversible: yes

### D-0428 — The scrape service takes the engine and commits in steps
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: `services.scrape.scrape(engine, fetching, request)`, not a session: the job and its claimed task commit first, the fetch runs outside any transaction, and its results commit in one transaction; formats are computed before that write. The site's rate is awaited in place within `timeout_s`. Scrape jobs and new sites belong to the `default` project; `api_key` is not passed (no column records it).
- Alternatives: One transaction (§4.7's sketch); postpone like a worker.
- Why: A timed-out scrape must still fail its job (§4.4 step 4); a slow page holds no connection or row lock; the caller waits anyway.
- Reversible: yes

### D-0429 — The API's browser rung launches Chromium per fetch
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: In the API process the browser rung opens a browser for each browser fetch.
- Alternatives: One browser per API process (SPEC-02 §4.8 says so for workers).
- Why: The browser is used only on evidence (ARCHITECTURE §7.1); an API process should not hold one it rarely uses. Revisit if measured.
- Reversible: yes

### D-0430 — Scrape usage per fetch attempt
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: `http_requests` +1 per `http`/`api` attempt, robots.txt included; `browser_seconds` = ceil(attempt duration) per browser attempt (SPEC-02 §4.7, §4.8). The answer's `usage` is read back from `job.usage`.
- Alternatives: Count the page fetch only.
- Why: Every request made is visible.
- Reversible: yes

### D-0431 — Format members are omitted, never null
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 4 (#88) · Status: decided
- Decision: A format's member is left out when not requested (`exclude_if`) and the OpenAPI document gives it no null branch (`markdown?: string`); `PageMetadata` members are all required in the document. `POST /v1/scrape` is generated into the frontend client; records and the draft schema stay hand-narrowed until PRs 5 and 6, and the form's request is sent as the generated type (openapi-typescript marks defaulted members required).
- Alternatives: `string | null`; keep the module augmentation.
- Why: Matches §4.4 and the shapes #82 was built against.
- Reversible: yes

### D-0432 — Drafts show no prompt hash until the API returns one
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: Draft schemas show origin `prompt_draft` but no prompt hash: `SchemaDef` has no such member until SPEC-06 PR 6 (role S, prompt-hash reuse) adds it.
- Alternatives: Hash the prompt client-side; declare the member by hand.
- Why: The UI shows only server values (§3); no hand-written DTOs (SPEC-12 §4.1).
- Reversible: yes

### D-0433 — Schema routes for create, adopt and edit
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: Routes `/schemas/new` (adoption is `/schemas/new?from=<id>`, a create prefilled from that schema) and `/schemas/:id/edit`, beside `/schemas` and `/schemas/:id`.
- Alternatives: Modal editors on the detail page.
- Why: DESIGN.md "few modals"; one form for create, adopt and edit.
- Reversible: yes

### D-0434 — The query cache belongs to one API key
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: `ApiQueryProvider` starts a new TanStack `QueryClient` when the key changes or is dropped; queries and mutations do not retry; a create, save or retire invalidates every `schemas` query.
- Alternatives: The key in every query key.
- Why: Nothing read with one key is shown under another (§18), with no key material in cache keys.
- Reversible: yes

### D-0435 — The schema form checks only what a request needs
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: The form checks the JSON shape, a chosen page kind and unique field names; every schema rule is the server's 422, shown next to the input it names. Changing a field's type drops the old type's `vocab`, `scheme`, `item` or `fields`; empty optional texts send null.
- Alternatives: Client-side schema validation.
- Why: The UI holds no logic (§3).
- Reversible: yes

### D-0436 — Schema actions follow the server's rules
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: Edit is offered only on the latest active non-preset version and retire on any active non-preset version (SPEC-07 §4.6); refusals still render as problems. Status tones: active → success, retired → neutral (`SchemaStatusLabel`).
- Alternatives: Always show the buttons.
- Why: Fewer dead ends; DESIGN.md "Status display".
- Reversible: yes

### D-0437 — Preference returns `Chosen` or `Unpublished`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: Preference returns `Chosen(chosen, agreeing, rejected)` or `Unpublished(missing|conflict, reason, rejected)`. Evidence, confidence and `FieldOutcome` come in PR 8. For an exact-match type the chosen candidate is the first kept one, in the order the collectors give.
- Alternatives: Return `FieldOutcome` now, with placeholder evidence.
- Why: INV-22 forbids a published outcome without evidence. `agreeing` is what PR 8 needs for the `agreed` bucket.
- Reversible: yes

### D-0438 — A missing field states the furthest screening stage
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: A `missing` field's reason is the furthest screening stage a candidate reached (`invalid` < `ambiguous` < `not_owned` < `url_param`), or `no_candidates` when the field has none. Every rejected candidate keeps its own reason.
- Alternatives: A generic `no_valid_candidates`.
- Why: It names the stage that blocked the field.
- Reversible: yes

### D-0439 — Unranked kinds never win; a split winning kind is a conflict
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: In precedence types, a source kind absent from the type's order never wins: if only such candidates exist, the field is `missing` with reason `unranked`. Equal values still count as agreeing. Two candidates of the winning kind that disagree make the field `conflict`/`disagree`. A `list` field follows its item type's rule; an `object` field publishes on agreement.
- Alternatives: Unranked kinds rank last; the first candidate of the winning kind wins.
- Why: The order is fitted on dev (INV-02), and an unranked kind has no dev measurement. When two values tie, nothing settles which is right (C7).
- Reversible: yes

### D-0440 — Atomic offers anchor on one Offer
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: The anchor Offer is the one holding kept candidates for the most Offer-rooted fields; on a tie, the first one seen. Candidates from two different Offers that disagree make the field `offers_disagree`. An Offer field with no kept candidate from the anchor is `offer_split`, which includes an Open Graph price beside a JSON-LD Offer that states only availability. Page-level values that agree with the anchor's value count as agreeing.
- Alternatives: Per-field agreement only, which can take price and availability from different Offers.
- Why: INV-15 says one source object; this is the conservative reading.
- Reversible: yes

### D-0441 — The URL-parameter rule compares every scalar of the raw value
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: INV-13 compares every string and number inside the raw value (including inside objects and arrays, such as `priceCurrency`), in the SPEC-04 text form, against the request URL's query values decoded as application/x-www-form-urlencoded (WHATWG). Empty values are ignored. A match is kept only when `visible` finds it on the page.
- Alternatives: Compare only top-level strings.
- Why: A currency or code copied from the URL is a value taken from a URL code (C7).
- Reversible: yes

### D-0442 — Derivations fill only missing fields, in a fixed order
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: Derivations fill only `missing` fields, never `conflict`. The order is `absolutize` (the field's own relative candidate, put through preference again), then `canonical_link`, then `final_url`. The page-URL field is the url field of a detail schema whose path is `T.url`, for a primary type T. Derived page URLs pass through the url normalizer.
- Alternatives: Fill conflicts too, or put the canonical link first.
- Why: A conflict is a field whose values disagree; filling it would hide that. A candidate's own value is closer to the field than a page-level URL.
- Reversible: yes

### D-0443 — `source_precedence.yaml` has one reader
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: decided
- Decision: `load_precedence` requires `source_split: dev`, an order for each of text, long_text, url and image_url, known source kinds, and no other types. `parse_orders` is shared with `eval/calibrate`, and a test checks that its stamp keys match the `Precedence` model.
- Alternatives: Let `long_text` fall back to `text`'s order.
- Why: INV-02, and no defaults (C7).
- Reversible: yes

### D-0444 — Dev-fitted files under `backend/data/` and INV-05
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 7 (#90) · Status: needs-owner
- Decision: Question: INV-05 says every file under `backend/data/` comes from a pinned external source listed in `manifest.json`. SPEC-05 puts the dev-fitted `source_precedence.yaml` (§4.7) and `calibration.json` (PR 8) there, and the fit commands rewrite them, which would break a pinned sha256. Options: (a) `data_manifest_check` exempts the two fitted, stamped artifacts and checks their `source_split: dev` stamp instead, with INV-05 reworded to "external data"; (b) a manifest entry per fitted file, whose url names the eval run and whose sha256 the fit commands rewrite; (c) move fitted files out of `backend/data/`. Recommendation: (a). Blocked: committing the initial order (D-0020), which PR 9 needs to run `extract_page`, and PR 8's empty `calibration.json`. Copied to OPEN_QUESTIONS #19.
- Alternatives: See options.
- Why: The specs contradict each other (CLAUDE.md §4).
- Reversible: yes

### D-0445 — The adapter collector is built per capture with the adapter and the detected page kind
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 11 (#91) · Status: decided
- Decision: `AdapterCollector(adapter, page_kind)` implements the `Collector` protocol. The pipeline (PR 9) builds it for `api` captures from `registry.detect(bundle.url)` and that adapter's `detect(bundle.url).page_kind`.
- Alternatives: Detect from `ctx.page_url`, which for an API capture is the endpoint, not the page.
- Why: Only the bundle's `url` holds the page URL.
- Reversible: yes

### D-0446 — The adapter entity is the node at the mapped query's last wildcard
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 11 (#91) · Status: decided
- Decision: Entity id `adapter:<name>:<normalized path>` (`$` for detail, `$['jobs'][0]` per listing row). Kind is the single schema.org root type of the mapped paths; a map spanning several types is skipped with a diagnostic. `urls` come from `adapter.map({"url": "<Type>.url"})`.
- Alternatives: Add `root(page_kind)` to the `Adapter` protocol.
- Why: Structural (RFC 9535); the adapters need no change.
- Reversible: yes

### D-0447 — `json_doc.select` takes name, wildcard and index segments
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 11 (#91) · Status: decided
- Decision: RFC 9535 queries limited to name, wildcard and non-negative index segments, so every normalized path (and so every locator path) is a query; other queries raise `ValueError`.
- Alternatives: A JSONPath library.
- Why: Adapter maps use only this subset (D-0266); no dependency needed.
- Reversible: yes

### D-0448 — Role S output is checked by the client, within its one retry
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 6 (#92) · Status: decided
- Decision: The role S output schema is `SchemaDocument`'s Pydantic JSON Schema without `name` and `version`. `LLMClient.complete_json` takes an optional reply check (`ReplyCheck`: why a schema-valid reply is invalid, or None); role S passes the `SchemaDocument` validation, so a schema mismatch and an invalid document share the client's one retry (at most two calls), then `OutputInvalid`. `RecordedLLM` passes the check to its live client.
- Alternatives: A hand-written JSON Schema encoding every document rule; a second retry in role S on top of the client's (up to four calls).
- Why: One definition of the document (SPEC-04 types); JSON Schema can't express "every field described" or required-group rules; §4.5 says "the client validates it with the SchemaDef model; invalid → one retry", and roles A and D can reuse the check. Whether each provider's structured-output mode accepts the recursive `$ref` is unverified until keys exist (H4).
- Reversible: yes

### D-0449 — Role S keys drafts on the whitespace-normalized prompt
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 6 (#92) · Status: decided
- Decision: The prompt is normalized by collapsing Unicode whitespace runs to one space and stripping the ends; the hash and the request use the normalized text. An empty prompt is refused. The stored draft is returned whatever its status.
- Alternatives: Hash the raw prompt; also hash the sample pages or page kind.
- Why: §4.5 "the same prompt text (after whitespace normalization)" and "keyed by prompt hash"; one prompt, one schema.
- Reversible: yes

### D-0450 — Role S input limits
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 6 (#92) · Status: decided
- Decision: Each sample's cleaned text is cut to its first 40,000 characters (role C's detail limit, D-0025); 1–3 samples are required; `max_output_tokens` is 8,192.
- Alternatives: A new setting for role S's limit; no cut.
- Why: Bounds the request without a new setting; 8,192 tokens holds a schema of several dozen fields.
- Reversible: yes

### D-0451 — The labeling nav entry reads `/healthz` once per query cache
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 9 (#93) · Status: decided
- Decision: The shell reads `/healthz` with the same-origin client and no key, once per query cache (`staleTime: Infinity`); an unknown or failed answer hides the Labeling entry. `/labeling` itself still says when the labeling API is off.
- Alternatives: Poll the flag; show the entry by default.
- Why: The flag is fixed for the backend's lifetime; hiding is the conservative reading of "shown only when" (SPEC-12 §4.3). The cache is per key, so a key change reads it again (review Consider item, left for a follow-up).
- Reversible: yes

### D-0452 — The current nav entry is marked with `aria-current` and styled in theme.css
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 9 (#93) · Status: decided
- Decision: The main nav's entry for the page shown carries WAI-ARIA `aria-current="page"`; one rule in `src/app/theme.css` (`.link[aria-current="page"]`) underlines it, HeroUI's own hover treatment.
- Alternatives: A per-component className (a visual value outside theme.css); HeroUI Tabs as nav (wrong role).
- Why: Owner rule: a visual change is an edit to theme.css only (DESIGN.md, Theming); the underline marks the state without relying on color.
- Reversible: yes

### D-0453 — Test stubs answer the shell's `/healthz` by default
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 9 (#93) · Status: decided
- Decision: `stubApi` (and the test setup through it) answers `GET /healthz` with `healthReply()` (`eval_ui: false`), unrecorded unless a test names it.
- Alternatives: A `/healthz` reply in every screen test.
- Why: Every screen now sends it; screen tests assert only their own calls.
- Reversible: yes

### D-0454 — An uncalibrated published field may have no confidence
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: A published field's `confidence` is its bucket's dev precision, and is `None` only when the field is `calibrated=false` (the bucket has no dev measurement). INV-22's "carries `confidence`" is read as the attribute being present, as §13.1 says of every field.
- Alternatives: Keep `confidence` mandatory (PR 2), so nothing publishes until dev is labeled.
- Why: §10 publishes uncalibrated buckets with the flag set, and §21 L1 is done when every published field carries evidence and `calibrated=false`; with no labels there is no precision.
- Reversible: yes

### D-0455 — Evidence bucket priority; a lone state value has no bucket
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: `adapter` (adapter or api chosen) > `agreed` (at least 2 distinct source kinds among the independent candidates of chosen + agreeing) > the chosen kind's bucket: `structured` for jsonld/microdata/og, `config_corroborated`/`config_uncorroborated` from a caller-given set of corroborated fields, `llm_grounded`. A lone js_state/xhr value fits no §10 bucket and abstains with reason `no_bucket`.
- Alternatives: Count js_state/xhr as `structured`.
- Why: §10 names no bucket for embedded state; publishing without a bucket breaks INV-22.
- Reversible: yes

### D-0456 — τ and record confidence cover required-group members
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: τ 0.97 applies to required fields and to every member of a required group; others use 0.95. Record confidence takes the same set. `calibrated` requires n ≥ 30 and a precision. A `below_tau` field keeps `evidence`, `confidence` and `calibrated` in `field_meta`, and its chosen candidate moves to `rejected` with `below_tau`.
- Alternatives: Group members as optional.
- Why: The stricter reading (C7); the meta says why the field abstained.
- Reversible: yes

### D-0457 — Derived values publish only with a source candidate
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: An `absolutize` value publishes with its source candidate's kind, locator and bucket, and `derived_by`. A page-URL derivation (`canonical_link`, `final_url`) has no candidate and stays `missing` with reason `no_provenance` until D-0355 is answered.
- Alternatives: Publish it without provenance.
- Why: INV-22 as the models enforce it.
- Reversible: yes

### D-0458 — `Calibration` lives in `resolve.evidence`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: `Calibration` and `Bucket` move to `resolve.evidence`, and `eval.calibrate` imports them, so the writer and the engine's reader share one model. `load_calibration` returns `None` for a missing file (every field uncalibrated).
- Alternatives: Two models.
- Why: C8; `resolve` sits below `eval` in the layering.
- Reversible: yes

### D-0459 — Entity key
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 8 (#94) · Status: decided
- Decision: `entity_key` is the hex sha256 of `str(site_id) + canonical_url`; the caller passes the target's canonicalized URL.
- Alternatives: A separator between the parts.
- Why: A UUID string has one length, so the concatenation is unambiguous.
- Reversible: yes, until records are stored

### D-0460 — IR `attr` step is its own selector key
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: `attr` is a selector key of its own (an attribute of the context node, e.g. a listing row), not a modifier on `xpath`/`css`; XPath reads attributes with `@name`. `when_type` goes only with `jsonld`; `source` is required with `jsonpath`.
- Alternatives: `attr` as a modifier on `css`/`xpath` steps.
- Why: SPEC-08 §4.2 lists `attr` among the exactly-one selector keys and §4.3 runs it on the tree beside `xpath`/`css`; the literal reading.
- Reversible: yes

### D-0461 — CSS translation is authoritative
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: `css` is translated with cssselect's `HTMLTranslator` at validation and stored as `xpath`; an IR whose stored `xpath` differs from the translation of its `css` is refused. Pseudo-elements are refused.
- Alternatives: Keep a supplied `xpath` as is; overwrite it silently.
- Why: Executors run the `xpath`; a hand-edited mismatch would export something other than the readable `css` says. A cssselect upgrade that changes translations is handled by the loader rows (review follow-up).
- Reversible: yes

### D-0462 — `api_recipe` waits for SPEC-09
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: The IR model has no `api_recipe` field yet (`extra="forbid"` refuses one); SPEC-09 adds it with `ApiRecipe`.
- Alternatives: An untyped `dict` placeholder.
- Why: SPEC-09 owns the shape; a placeholder would let unvalidated recipes into stored IRs.
- Reversible: yes

### D-0463 — Portable regex subset
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: Patterns allow literals, `\d\D\s\S\w\W\b\B\n\t\r\f\A`, punctuation escapes, `\xhh`, `\1` to `\9`, classes without nesting, POSIX classes or set-operation doubles, counted quantifiers `{n}`/`{n,}`/`{n,m}`, `(?:`, lookarounds, `(?P<name>`/`(?P=name)` (names up to 32 characters) and the `i`/`m`/`s` flags. Replacements allow only `\1` to `\9` naming existing groups. Python compiles with `re.ASCII` (`PCRE_FLAGS`).
- Alternatives: Translating between dialects; a PCRE binding in tests.
- Why: D-0034 asks for a conservative check; refusing is safer than translating. Non-ASCII under PHP `/u` is settled on the PR 11 row (review follow-up).
- Reversible: yes

### D-0464 — XPath 1.0 check refuses variables and namespace prefixes
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: Besides the D-0034 function allowlist, variable references and namespace prefixes are refused.
- Alternatives: Allow them and fail at run time.
- Why: A config carries no bindings for them; libxml2 compiles both and fails only on evaluation.
- Reversible: yes

### D-0465 — IR field and post-op shape
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 1 (#95) · Status: decided
- Decision: A field has at least one step; a field without steps is absent from `fields`. Normalizer post ops exist for every field type except `list`/`object` and take `{}`. `FieldStatus` moves to `db.models` beside the other `extraction_config` enums.
- Alternatives: Empty step lists; a second `FieldStatus` copy in `eval`.
- Why: An empty step list carries a status for nothing; C8, one definition.
- Reversible: yes

### D-0466 — A prompt is drafted only from a reached page
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 6 (#96) · Status: decided
- Decision: `scrape` drafts a `schema.prompt` only when the page was fetched with outcome `extracted`, with its cleaned text as role S's one sample; otherwise the answer has no `schema` member and no call is made.
- Alternatives: Return a stored draft for a page not reached; draft before fetching.
- Why: Role S needs 1–3 sample pages (SPEC-06 §4.5), and §4.8 returns nothing derived from a page that was not reached, as for formats.
- Reversible: yes

### D-0467 — LLM failures on `scrape` are problems and fail the job
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 6 (#96) · Status: decided
- Decision: The client's errors share `LLMFailure`, whose `code` is the task's `last_error` and the problem type: 422 `budget_exhausted`, 503 `llm_unavailable`, 502 `llm_output_invalid`. The last two extend SPEC-07 §4.3's types, as D-0364 did. A blank `schema.prompt` is a 422 `validation` before any job.
- Alternatives: 200 without `schema`; one generic 500.
- Why: The request asked for a schema it cannot get; §4.8 makes that a request-level failure with nothing partial.
- Reversible: yes

### D-0468 — The API starts without LLM provider keys
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 6 (#96) · Status: decided
- Decision: `client_from_settings` returns `Unconfigured(reason)` when a listed provider has no key; its calls raise `ProviderUnavailable(reason)`, and stored drafts are still served.
- Alternatives: Fail startup; build the client per request.
- Why: Scrape without a prompt needs no LLM, and provider keys are deferred (H4).
- Reversible: yes

### D-0469 — Records and replay shapes are declared by hand until SPEC-07 PR 8
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: `frontend/src/api/records.ts` declares SPEC-07 §4.6's records list and replay and adds them to the generated `paths` by module augmentation: a listed record is the §4.4 record plus `capture_id`, `schema_id` and `version`; a page is `{items, next_cursor}` (`next_cursor` null on the last page); a replay answers `{records: [...]}` and is sent an empty body. Deleted once SPEC-07 PR 8 is in `openapi.json`; that PR matches these shapes or updates the module.
- Alternatives: Wait for SPEC-07 PR 8; raw `fetch` outside the client.
- Why: Row-level readiness (D-0378), as D-0407; the fewest members the screen needs, and the page envelope follows `SchemaList.items`.
- Reversible: yes

### D-0470 — Records are listed by schema, with filters in the URL
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: The Records screen requires a schema version; job and site narrow the list. The filters live in the URL query (`/records?schema_id=…&job_id=…&site=…`).
- Alternatives: Columns from the union of the fields on a page; filters in `localStorage`.
- Why: SPEC-12 §4.3 asks for one column per schema field, which needs one schema; URL filters can be reloaded and shared and need no storage.
- Reversible: yes

### D-0471 — The record inspector is a bottom drawer
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: The inspector is a HeroUI `Drawer` placed at the bottom, opened by row action (click or Enter), with no route of its own.
- Alternatives: A right drawer (too narrow for the eight-column field table); a `/records/:id` route (no single-record endpoint in SPEC-07).
- Why: SPEC-12 §4.3 "row click opens the inspector"; few modals (DESIGN.md).
- Reversible: yes

### D-0472 — The replay diff compares status and value, for one replayed record
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: The replay diff compares each field's `status` and `value` (JSON equality, member order ignored per RFC 8259 §4); confidence and locator are shown, not compared. It diffs only when the replay made exactly one record; with several it lists them without a diff. Tones: changed → warning, same → neutral.
- Alternatives: Match records by position; compare every attribute.
- Why: A replayed record has no id of the stored one, and the UI holds no matching logic (§3); the same value can be published from another source.
- Reversible: yes

### D-0473 — The watcher's lock is a pidfile in the git common dir
- Date: 2026-10-13 · Spec/PR: tooling chore (#99) · Status: decided
- Decision: `watch_agents.sh` locks with `watch_agents.lock` in `git rev-parse --git-common-dir`, holding "<pid> <windows pid>" and created exclusively with `ln` from a temp file.
- Alternatives: A `.pid` name; `flock` (not in Git Bash); `noclobber` (a reader can see an empty file and clear it as stale).
- Why: The common dir is shared by every worktree, so there is one lock; the C3 scan reads `.pid` as a TLD.
- Reversible: yes

### D-0474 — Watcher liveness falls back to the Windows pid, bash only
- Date: 2026-10-13 · Spec/PR: tooling chore (#99) · Status: decided
- Decision: A holder is alive if `kill -0` sees it, or if PowerShell `Get-Process` finds its Windows pid as a `bash` process.
- Alternatives: `kill -0` only; any process with that Windows pid.
- Why: `kill -0` sees only its own MSYS runtime's processes, and Windows reuses pids.
- Reversible: yes

### D-0475 — The pipeline takes a config executor bound to its IR
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `crawlerai.collect.config.ConfigExecutor` is `execute(page, schema, ctx) -> Executed` plus `field_status`, implemented by `EngineExecutor(ir, vocabulary)`; SPEC-05 §4.5 and SPEC-08 §4.3 now state this signature (clarifying edit).
- Alternatives: SPEC-05 §4.5's literal `execute(ir, page, schema) -> list[Candidate]`.
- Why: `.importlinter` puts `config_ir` above `collect` and `resolve`, so the pipeline cannot name the IR type; candidates need `ctx` to normalize, listings need row entities, resolution needs field status (§10).
- Reversible: yes — only the PR 8 wiring uses it

### D-0476 — Config candidates carry no `page` entity
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `Executed.rows` holds only listing rows (`config:row:<n>`, kind `ListItem`, roots); page-level candidates name `page`.
- Alternatives: Return a `CollectResult` that includes `page`.
- Why: The OpenGraph collector emits `page` and `EntityGraph.of` adds it when missing; a second one would be a duplicate id (as `Admitted` for js_state/xhr).
- Reversible: yes

### D-0477 — The engine reads JSONPath with `json_doc`'s RFC 9535 subset, not jsonpath-ng
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: Queries outside the name/wildcard/index subset are refused per step with an `unsupported_jsonpath` diagnostic.
- Alternatives: Add jsonpath-ng to the engine as SPEC-08 §4.1 lists.
- Why: C8: one JSONPath reader in the engine; locator paths are in the subset; the release executor (PR 3) uses jsonpath-ng, keeping the two independent (INV-20).
- Reversible: yes — swap the reader in `_select_all`

### D-0478 — Post ops: a normalizer op checks, it does not transform
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `{"<type>": {}}` requires the value to be `Ok` for its type and passes it on unchanged; `trim`, `regex_replace` and `absolutize_url` take text only; `absolutize_url` without a base URL declines `no_base_url` (C7); a failed post op declines the step and the next step runs.
- Alternatives: Let the normalizer op transform the value.
- Why: SPEC-04 owns normalization (C8); normalizing twice is not idempotent for every type.
- Reversible: yes

### D-0479 — Without a valid step, the first match is proposed with its decline
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: If no step gives `Ok`, the first step that matched is proposed with its `Invalid`/`Ambiguous` result (a multi-match carries the matches as `raw`); no match gives no candidate; selector errors are diagnostics.
- Alternatives: Propose only `Ok` values.
- Why: Other collectors propose invalid candidates too; drift (§4.9) and validation (§4.7) need "matched but not valid".
- Reversible: yes

### D-0480 — Scope of config steps
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `regex`, `jsonld` and `jsonpath` read the whole page and are refused in a listing row; a row step is an `xpath`/`css` step selecting elements; `when_type` matches subtypes through the JSON-LD collector's vocabulary; `next` fills the schema's `next_page_url` field (ARCHITECTURE §5.3) when present.
- Alternatives: Run regex on a row's serialized HTML.
- Why: Most conservative reading of SPEC-08 §4.3; a serialization the release executor cannot reproduce exactly.
- Reversible: yes

### D-0481 — A config for another schema version or page kind raises `ConfigMismatch`
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: `EngineExecutor.execute` refuses a schema whose name, version or page kind differs from the IR's.
- Alternatives: Run it anyway.
- Why: Configs are per schema version (ARCHITECTURE §5.2, §6); a mismatch is a wiring bug, not page content.
- Reversible: yes

### D-0482 — Config candidates are never independent
- Date: 2026-10-13 · Spec/PR: SPEC-08 PR 2 (#98) · Status: decided
- Decision: Every `source_kind='config'` candidate has `independent=False`.
- Alternatives: `independent=True`.
- Why: A config is learned from the page's other sources and a `jsonld` step reads the node the JSON-LD collector reads, so an equal value is one piece of evidence, not `agreed` (ARCHITECTURE §8.1, §10) (#98 review).
### D-0483 — The pipeline lives in `resolve.pipeline`; role C is a hook, not an LLM client
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `extract_page` takes `role_c: Callable[[GapRequest], Awaitable[GapReply]] | None` where SPEC-03's signature has `llm`; the caller binds the client. `eval.engine.PipelineEngine.replay_page(bundle, schema, config, llm, mode)` keeps SPEC-03's signature.
- Alternatives: Import `LLMClient` in `resolve` (breaks the `resolve | llm` independence contract); a new top-level package.
- Why: The import contracts stay as they are; SPEC-06 PR 4 binds role C from the client in a layer above both.
- Reversible: yes

### D-0484 — The collectors are assembled in `collect.run`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `collect_page` runs JSON-LD, microdata, OG, and the adapter collector for an `api` capture whose page URL an active adapter detects (D-0445), each isolated: one that raises gives a diagnostic and no candidates. js_state and xhr then admit against the rest (D-0418).
- Alternatives: Build the adapter collector in `resolve` (forbidden: only acquire and collect import adapters).
- Why: §4.14; import contracts.
- Reversible: yes

### D-0485 — The scrape task's handler step is `resolve.task.extract_task`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: This row supplies the step after the fetch: extract, store `extraction`/`candidate`/`record`, return the outcome; the caller settles the task. The fetch and worker registration stay with SPEC-07's scrape function and SPEC-10 PR 2.
- Alternatives: A second fetching handler beside `services.scrape`.
- Why: SPEC-07 §4.4 and SPEC-10 §4.2 make the scrape function the handler; a second fetch path would duplicate it.
- Reversible: yes

### D-0486 — No fitted precedence means every precedence type declines
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `EngineData.load` uses `UNRANKED` (empty orders) when `source_precedence.yaml` is absent: text, long_text, url and image_url fields are `missing`/`unranked`. Exact-match types still publish on agreement.
- Alternatives: Commit SPEC-05's default order (blocked by D-0444).
- Why: C7: decline rather than follow an unmeasured order; consistent with a missing calibration meaning uncalibrated.
- Reversible: yes

### D-0487 — Normalization context from page evidence only
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `content.context.page_context` sets `html_lang`, `og_locale`, `hreflang` (`link rel~=alternate`), `base_url`, `page_url` and `captured_at`. `page_currencies` and `cctld_territory` stay empty for now.
- Alternatives: Fill them from the page's structured data and CLDR territories.
- Why: An empty value makes money decline rather than guess (C7); filling them is a follow-up with its own tests.
- Reversible: yes

### D-0488 — Entity key uses the task's canonical URL
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `record.entity_key = sha256(site_id + url_task.canonical_url)` for detail pages.
- Alternatives: The target entity's own URL.
- Why: Stable across runs of one URL, and the key `url_state` (SPEC-11) uses.
- Reversible: yes

### D-0489 — Role C is asked only for real gaps
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: In schema order: required fields that are `missing`, and `missing` members of required groups no member fills. Conflicts and abstentions are never sent. Role C runs once per page; its exceptions propagate.
- Alternatives: Every member of every required group.
- Why: §4.13; fewer LLM calls; a replay's missing recording reaches the harness.
- Reversible: yes

### D-0490 — Config mode and listings are refused for now
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: `extract_page` raises `ModeNotSupported` for a config or a listing schema until SPEC-08 PR 2 and SPEC-05 PR 12.
- Alternatives: Resolve page-scoped listing fields only, or ignore the config.
- Why: A partial answer would be scored as a real one.
- Reversible: yes

### D-0491 — Unreadable recordings drop the page (follow-up from #33)
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: A recording that doesn't parse as an `LLMResponse`, or whose cache row points at a missing object, raises `RecordingUnreadable`; `replay_split` drops the page as `ReplayFailed("recording unreadable: …")`.
- Alternatives: Stop the run.
- Why: A per-page data problem, like a missing recording (D-0219); the `n_pages` gate catches it.
- Reversible: yes

### D-0492 — Runtime data shipping deferred (follow-up from SPEC-04 PR 7)
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 9 (#100) · Status: decided
- Decision: Shipping `VERSION`, `calibration.json` and GeoNames data goes to its own PR before the first deployment. `EngineData.load(data_dir)` takes the directory explicitly, so that PR only chooses where it comes from (package data or a settings path) and makes the build write `VERSION`.
- Alternatives: Settle it here.
- Why: It changes `infra/Dockerfile` and packaging, outside this row; D-0444 already blocks committing the fitted files.
- Reversible: yes

### D-0493 — Recipe splits into `RequestSpec` and `ApiRecipe`
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `RequestSpec` holds method, url, `params_from_url`, headers, body, pagination and `requires_page_fetch`; `ApiRecipe(RequestSpec)` adds `map` (at least one field) and a required `proof`.
- Alternatives: One model with optional `map`/`proof`.
- Why: Binding and role D (§4.5, "the `ApiRecipe` without `map`/`proof`") produce the request half; a stored recipe always carries its proof.
- Reversible: yes

### D-0494 — `bind` returns `RequestSpec | Ambiguous` over samples
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `bind(samples)`, where a `Sample` is the page URL, the captured request (method, URL, body) and the page's JSON documents by kind (`jsonld`, `js_state`) as the caller builds them.
- Alternatives: `bind(candidates) -> ApiRecipe` as the spec's module list sketches.
- Why: The map comes from discovery and the headers from replay (PRs 2–3), so binding can only produce the request half.
- Reversible: yes

### D-0495 — Binder grammar
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `path:<i>` counts page path segments after the leading `/` from 0; `query:<name>` takes the first non-empty value; `regex:<pattern>` is portable with exactly one group, searched over the raw path; `jsonld:`/`js_state:` take a `json_doc.select` query selecting exactly one scalar. Values compare percent-decoded and are re-encoded per place (RFC 3986 pchar in the path; `&`, `=`, `+` encoded in a query value); numbers compare as their JSON text.
- Alternatives: 1-based indexes; comparing raw strings.
- Why: One spelling per value lets URL and JSON sources meet; exact reproduction of every sample is still required.
- Reversible: yes, until recipes are stored

### D-0496 — Recipe JSONPaths use the engine's subset
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `map`, `pagination.rows` and data binders must be queries `json_doc.select` reads (`$['a'][0][*]`); dot notation (`$.data.name`, the spec's illustration) is refused.
- Alternatives: Accept dot notation and translate it.
- Why: What is stored is what the engine runs (§12.1); the config executor (#98) uses the same `select`.
- Reversible: yes

### D-0497 — Which values become parameters
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: Binding needs two sample pages. A value equal to a page-URL path segment or query value on every sample is bound, even when constant; a varying value with no URL source binds to a page-data path only when the same path holds it on every sample (`requires_page_fetch`); a constant without a URL source stays literal; a varying value without a source is `Ambiguous`. Parameters are `p1`, `p2`, … in order of first use.
- Alternatives: Bind only varying values; allow one sample.
- Why: One page cannot tell constants from parameters; binding constant page data would add a fetch for nothing; held-out validation (PR 4) checks the choice.
- Reversible: yes

### D-0498 — Credential headers are refused in the recipe model
- Date: 2026-10-13 · Spec/PR: SPEC-09 PR 1 (#102) · Status: decided
- Decision: `Authorization`, `Proxy-Authorization` and `Cookie`, in any case (RFC 9110 §11.6.2, §11.7.2; RFC 6265 §5.4), never appear in a recipe; the token-value rule stays with header minimization (PR 3).
- Alternatives: Refuse only in PR 3's minimizer.
- Why: §4.6 says they are never kept; the model also guards role D output and operator corrections.
- Reversible: yes

### D-0499 — The merge guard fails closed
- Date: 2026-10-13 · Spec/PR: chore (#104) · Status: decided
- Decision: `tools/orchestrator/merge_guard.py` denies a Bash or PowerShell call when the hook input is unreadable, and the hook command denies when neither `python3` nor `python` is on PATH.
- Alternatives: Fail open (allow on error).
- Why: A guard that fails open is silently off; a broken Python setup blocks tool calls until fixed, and the stderr message names the cause.
- Reversible: yes

### D-0500 — Literal bodies are data to the merge guard
- Date: 2026-10-13 · Spec/PR: chore (#104) · Status: decided
- Decision: Quoted here-documents and `@'...'@` here-strings are stripped before parsing; a quoted argument is scanned only after `-c`, `-Command`, `/c` or `iex`, or when it contains `$(` or a backtick.
- Alternatives: Scan the whole command text with regexes.
- Why: PR bodies, commit messages and docs that mention the merge command must pass; the guard targets mistakes, not evasion.
- Reversible: yes

### D-0501 — An inline schema is stored once, or matched by name
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: An inline `schema` is stored as a `user` schema at version 1, or matched to its name's latest version when that one has the same document and is active. A name whose latest version differs or is retired is a 409 `conflict`; a document that breaks a schema rule is a 422 `validation` (`schema.inline…`). All before any job.
- Alternatives: Add a new version when it differs; run inline schemas without storing them.
- Why: A record needs a stored `schema_id`; an inline schema never edits a stored one (ARCHITECTURE §5.2); the same body twice reuses one row.
- Reversible: yes

### D-0502 — A schema `records` cannot use is a validation problem
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: A schema id that is unknown, retired, or for another page kind than `page_kind` is a 422 `validation` problem on `schema`, before any job. A prompt draft of another page kind is the same problem and fails the job (`invalid_schema`). `records` needs `schema` and `page_kind`; listing records are refused until SPEC-05 PR 12.
- Alternatives: 404 for an unknown id; extract against the schema's own page kind.
- Why: The id is a request member; D-0490 refuses listings in `extract_page`.
- Reversible: yes

### D-0503 — `max_age` reuses a recent `ok` capture of the canonical URL
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: `max_age` reuses the latest capture of the request's canonical URL (found through the tasks that fetched it) in the same site, fetched within `max_age` seconds, `ok` and not expired; a capture whose bundle is gone is fetched anew. A reused capture skips robots.txt and the rate limit, counts no usage, and `fetch` is the capture's original fetch. Index `capture (site_id, fetched_at)` added (migration 0009).
- Alternatives: Reuse blocked or shell captures too; match `capture.url` exactly.
- Why: A blocked page is worth retrying; §4.4 names the canonical URL; the query needs the index.
- Reversible: yes

### D-0504 — A page whose resolution fails is `failed` with nothing derived
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: When resolution fails (SPEC-05 §4.14), the scrape answers 200 with outcome `failed`, no formats, records or draft; the task fails with `extraction_error`.
- Alternatives: A 500 problem; return the formats anyway.
- Why: SPEC-07 §4.8: a page's failure is an outcome, and nothing partial is returned.
- Reversible: yes

### D-0505 — Without the engine's data files, `records` is a 503
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: The API loads `EngineData` from `backend/data/` of the source tree at startup. Without it, `records` is a 503 problem `records_unavailable` before any job, and the other formats work. This extends SPEC-07 §4.3's problem types, as D-0467 did.
- Alternatives: Fail startup; load per request.
- Why: D-0492 defers shipping the data files; the API should still serve formats.
- Reversible: yes

### D-0506 — `extract_page` takes the caller's parse; storing is its own step
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: `extract_page(..., parsed=)` takes the caller's `ParsedPage`; `resolve.task.store_extraction` stores an `ExtractionResult` (`extract_task` uses it too), and `Stored` carries the `RecordDraft`. The scrape extracts outside its write transaction, as it computes formats (D-0428).
- Alternatives: Call `extract_task` inside the write transaction.
- Why: INV-26: one parse per request; no connection held while the page resolves.
- Reversible: yes

### D-0507 — Scrape records run `adhoc` without role C for now
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: Records run in `adhoc` mode with no role C hook until SPEC-06 PR 4 binds it. `job.schema_id` is set for a schema by id or inline; a draft is known only after the job starts, and its records name it.
- Alternatives: Set `job.schema_id` after drafting.
- Why: Smallest change; records carry `schema_id` either way.
- Reversible: yes

### D-0508 — The INV-26 parser counter is shared by all tests
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 5 (#105) · Status: decided
- Decision: The `parses` fixture moves to `tests/conftest.py` so DB tests can count parses; the records tests are `tests/db/test_scrape_records.py`, with their own small stub web.
- Alternatives: Keep them in `test_scrape_service.py` (over 800 lines).
- Why: C11: split along a logical boundary; test modules cannot import each other (importlib mode).
- Reversible: yes

### D-0509 — Listing rows
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: Rows are the primary-type entities with an `ItemList`/`ListItem` ancestor and no primary-type entity between them and the list. With no such entity, the rows are the top-level primary entities, when there are at least 3 and intent gives `AmbiguousTarget`.
- Alternatives: Count every primary entity under a list, related items included.
- Why: A related or offered item belongs to its holder (§4.6 step 1). Fewer than 3, or one named by the page URL, is what a detail page looks like (§4.7).
- Reversible: yes

### D-0510 — Rows take no page-level value
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `EntityGraph.owned_by(..., page_values=False)` for rows: og/meta values are no row's. Page-scoped fields resolve against the page entity. `primary_types` reads only required row fields.
- Alternatives: Detail ownership for every row.
- Why: A page value describes the listing, not one of its rows (§4.6, §5.2).
- Reversible: yes

### D-0511 — A listing record holds the page fields
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: Each row's record is `{**page_fields, **row_fields}`, so `field_meta` covers every schema field (INV-22). Completeness and record confidence are computed over that merged set; the page's `record_confidence` is its least confident row's, `None` when any row's is.
- Alternatives: A separate page record; rows without the page fields.
- Why: INV-22; §4.10 gives one record per row.
- Reversible: yes

### D-0512 — Row entity key
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `sha256(site_id + url)`, where `url` is the row's published value of its first row-scoped url field with path `T.url`; without one, `<task canonical URL>#<row position>`. A URL listed twice gives one record, the first.
- Alternatives: The entity's `@id`; no record for a row without a URL.
- Why: §4.10 "keyed by row url"; position is stable for unchanged markup; SPEC-11 versions records by `(site_id, entity_key)`.
- Reversible: yes

### D-0513 — Listing outcome
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `extracted` when there is at least one row and every row is complete; `no_match` when no record is kept (no rows, or a crawl where every row is incomplete); otherwise `partial`, including a crawl that drops some incomplete rows.
- Alternatives: `partial` with no record for a listing with no rows.
- Why: §4.10 applied per row; `no_match` means "no record".
- Reversible: yes

### D-0514 — `next_page_url` is not filled from pagination in cold mode
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `next_page_candidates` goes into `ExtractionResult.next_pages`. The schema's `next_page_url` field stays `missing` unless a source states it: a config's `next` step (D-0480).
- Alternatives: A `rel_next` derivation.
- Why: A derived value without a candidate has no source kind or bucket (INV-22, D-0355); §4.8 lists the only derivations in core (C13).
- Reversible: yes

### D-0515 — The structural pagination rule needs the integer in the page URL
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: With no integer segment or parameter in the page URL, no structural candidate is taken; `rel=next` still applies. A repeated query parameter name is skipped.
- Alternatives: Read a missing parameter as page 1.
- Why: §4.12 "differ from the current URL only in one integer…"; guessing the first page's number skips a page on 0-based sequences (C7). The crawl frontier still gets every link.
- Reversible: yes

### D-0516 — Role C is not called for listings
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: The detail gap hook (§4.13) runs for detail pages only; role C for listings is SPEC-06 PR 5.
- Alternatives: Send each row's gaps as a detail request.
- Why: Role C's listing call returns rows, a different shape (ARCHITECTURE §8.6).
- Reversible: yes

### D-0517 — `Stored.records`
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 12 (#106) · Status: decided
- Decision: `store_extraction` returns every record it inserted as `StoredRecord(id, draft)` pairs (0 or 1 for a detail page, one per kept row for a listing), inserted in one statement; `services.scrape` reads the first, since the request refuses listing records.
- Alternatives: Keep `record_id`/`record` and add listing fields beside them.
- Why: One shape for both page kinds.
- Reversible: yes

### D-0518 — Role C is bound in `config_ir.role_c`
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: `role_c(client, *, job_id) -> RoleC` lives in `crawlerai.config_ir.role_c`; `llm.roles.c_extract` returns `Filled` (lower-layer types only). `eval.engine.PipelineEngine` binds it on the harness's `RecordedLLM` with `job_id=None`.
- Alternatives: `eval.engine` (production code would import eval); a new top-level package; changing the layering contract.
- Why: `resolve | llm` are independent (D-0483); `config_ir` is the first layer above both, and both the replay engine and the worker (services) can import it.
- Reversible: yes

### D-0519 — Role C failure reasons
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: Each `LLMFailure` carries a `field_reason`: `BudgetExhausted` → `llm_budget`, `ProviderUnavailable` → `llm_unavailable`, `OutputInvalid` → `llm_output_invalid`. The asked fields stay `missing` with it, plus a diagnostic `role C: <reason>`; a failed call adds no `llm_calls` record.
- Alternatives: Fold `OutputInvalid` into `llm_unavailable`; map the reason inside each role.
- Why: SPEC-06 §4.7 names two reasons for three exceptions; keeping the client's own code is more informative, and one mapping on the failure serves every role.
- Reversible: yes

### D-0520 — Missing optional fields ride along with a required gap
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: When a required field (or a member of an unmet required group) is `missing`, every `missing` optional field joins the same role C call; optional gaps alone never trigger a call. Partly supersedes D-0489.
- Alternatives: Required fields only (D-0489 as written).
- Why: SPEC-06 §4.4 and D-0025; one call either way.
- Reversible: yes

### D-0521 — Type-invalid role C values stay candidates
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: An aligned value its normalizer declines is proposed with its `Invalid`/`Ambiguous` result; preference rejects it and the candidate row keeps the reason. Ungrounded values are dropped with the diagnostic `role C: <field> ungrounded` (no value text, which is page content).
- Alternatives: Drop them before resolution, as SPEC-06 §4.4/§6 words it ("dropped").
- Why: Same as every collector; the reason reaches `candidate.reject_reason`. A clarifying spec edit may follow.
- Reversible: yes

### D-0522 — Role C truncation and limits
- Date: 2026-10-13 · Spec/PR: SPEC-06 PR 4 (#107) · Status: decided
- Decision: `DETAIL_MAX_CHARS = 40_000` is a constant (D-0025; role S's `SAMPLE_MAX_CHARS` reuses it). Spans are aligned to the text the model read, so a value past the cut is ungrounded; truncation is recorded as a diagnostic. `max_output_tokens = 4096`; fields are listed sorted by name.
- Alternatives: A `CRAWLERAI_LLM_C_MAX_CHARS` setting now; record truncation on `LLMCallRecord`.
- Why: Matches role S's precedent; `extraction.llm_calls` stores a count, so a diagnostic is what persists.
- Reversible: yes

### D-0523 — Replay uses the records' schema versions, cold
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: A capture replays against each schema version its stored records follow (the recorded version, not the latest), cold (`adhoc`, no config, no role C), and returns the records a page task would store (`resolve.task.page_records`: one per listing row, deduplicated by row URL). A capture with no record answers 409 `conflict`; an unknown capture or an expired bundle answers 404.
- Alternatives: A `schema_id` in the replay body (an API member SPEC-07 doesn't define); the latest schema version (the diff would compare different schemas).
- Why: A capture carries no schema; schemas are immutable per version (§5.2), so the recorded version keeps the replay comparable with the stored record. SPEC-07 §4.4 runs cold until SPEC-08 exists.
- Reversible: yes

### D-0524 — `allow_llm` accepted, unused until role C binds on replay
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: The replay body takes `allow_llm` (default false), but no replay calls an LLM yet: replay passes no role C to `extract_page`.
- Alternatives: Leave the member out until then.
- Why: SPEC-07 §4.6 defines the body; the default keeps replays cheap and deterministic (D-0029).
- Reversible: yes

### D-0525 — `GET /v1/records` pages by a keyset cursor, newest first
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: `{items, next_cursor}`, newest first by record id (UUIDv7), cursor = the last id; `limit` 50 by default, at most 200; every filter optional; `site` is the host, compared without case (RFC 4343). A listed record is the §4.4 record plus `capture_id` (null once the capture expired), `schema_id` and `version`; its `confidence` is recomputed from `field_meta` and the schema (§10). Migration 0010 indexes `record (job_id, id)`, `(schema_id, id)` and `(extraction_id)`.
- Alternatives: Offset paging; an opaque encoded cursor; requiring a filter.
- Why: D-0469's envelope; a keyset cursor is stable while records are added; extractions keep a NULL `capture_id` after expiry (SPEC-01 §4.2).
- Reversible: yes

### D-0526 — The Records screen follows SPEC-07's shapes
- Date: 2026-10-13 · Spec/PR: SPEC-07 PR 8 (#108) · Status: decided
- Decision: Where #97's hand shapes (D-0469) differed, the frontend follows SPEC-07: replayed records carry no `id`; `capture_id` is nullable (the inspector then offers no replay); the generated client marks `allow_llm` required, so the screen sends `{allow_llm: false}`. `RecordList` keys records by their position title. D-0469's module augmentation is deleted.
- Alternatives: A synthetic id on replayed records.
- Why: An id would name nothing stored (§13.1: replays are not persisted).
- Reversible: yes

### D-0527 — The release executor learns the schema through `FieldRule`s
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: `release_run(ir, ReleasePage, rules)` takes one `FieldRule(many, accepts)` per field: `many` for list fields, `accepts(value, type | None)` for normalizer post-op checks and the field's own validity, built by the release check from the schema and SPEC-04's normalizers. A field without a rule does not run (diagnostic); only valid values are returned (no decline as in D-0479).
- Alternatives: Import `schemas`/`normalize` (breaks the contract); return each step's raw matches for the caller to pick.
- Why: "First valid step wins" (§12.1) needs validity, and §4.1 forbids every `crawlerai` import but the model; the release check compares only reproduced values.
- Reversible: yes

### D-0528 — Release `when_type` matches by type name, without subtypes
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: A JSON-LD node is any object with `@type`; `when_type` matches a declared type's name with or without the `http(s)://schema.org/` prefix. Subtypes are not matched; `@context` is not read.
- Alternatives: Load the schema.org vocabulary into the release executor.
- Why: §12.3 says "no engine logic". An exported config's consumer has no vocabulary either, so a field that holds only through a subtype should be marked `manual`.
- Reversible: yes

### D-0529 — The release executor reads script state with its own reader
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: `js_state` reads `application/json` scripts and the object or array after a `window.x =` / `var|let|const x =` assignment (ECMAScript syntax) with `json.JSONDecoder.raw_decode`; `xhr` reads UTF-8 JSON network bodies; an `api` source is a diagnostic (SPEC-09).
- Alternatives: Take the engine's parsed documents as input.
- Why: Independence (INV-20): the same syntax read by separate code is what makes agreement meaningful.
- Reversible: yes

### D-0530 — jsonpath-ng capped below 1.9
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 3 (#110) · Status: decided
- Decision: `jsonpath-ng>=1.8,<1.9`. It accepts queries outside the engine's RFC 9535 subset (D-0477), such as `$..name`; where the engine refuses such a step the executors may disagree, and the release check marks the field `manual`.
- Alternatives: The latest release.
- Why: 1.9.x and 1.10.x were under two weeks old; SPEC-08 §4.1 names jsonpath-ng.
- Reversible: yes
