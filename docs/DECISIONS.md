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
| D-0044 | `.gitignore`, CLAUDE.md | Agent worktrees live under `.worktrees/` or `.claude/worktrees/`, ignored by git. | Elsewhere. | yes |
