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
| D-0001 | LGPL dependencies allowed but avoided | pending-owner |
| D-0012 | Labeling iframe loads images from live sites | pending-owner |
| D-0015 | `apply_url` maps to `JobPosting.url` | pending-owner |
| D-0019 | Only derivations: canonical/final URL → `url`, absolutize | pending-owner |
| D-0024 | Role C offsets corrected by exact-match search, never fuzzy | pending-owner |
| D-0037 | `map`/`crawl` scope is the exact host | pending-owner |

---

## Entries

### D-0001 – D-0044: Decisions made while writing the specs

- Date: 2026-10-12 · Source: spec authoring (SPEC-00 … SPEC-12) and the rev 5 consistency pass.
- Status: `pending-owner` where the Index above lists it; `decided` otherwise. Every entry is reversible unless the
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
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 3 (#4) · Status: decided
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
- Date: 2026-10-12 · Spec/PR: SPEC-00 PR 2 (#3) · Status: decided
- Decision: `uv sync --frozen --no-build --no-install-project`, then `uv build --wheel` + `uv pip install --no-build --no-deps` for the project. Later steps use `uv run --no-sync --no-build`. Local dev keeps the editable sync. SonarCloud S8544 on the wheel install is a false positive (it resolves nothing).
- Alternatives: `uv sync --frozen` (builds sdist dependencies; S8541).
- Why: No third-party build script runs in CI or the image.
- Reversible: yes
