# Decisions log: cross-cutting entries

Cross-cutting and process decisions (tooling, CI, orchestration, UAT and review fixes, rules for every capability),
and every `needs-owner` or `pending-owner` entry. Statuses, template and where an entry goes:
[README.md](README.md). Open owner items are indexed in [../project.md](../project.md#open-owner-items).
Entries written before the OpenSpec conversion (#223), when this file was `docs/DECISIONS.md`, keep their paths
(`docs/...`) and `ARCHITECTURE §N` refs as history; §N resolves in the
archived ARCHITECTURE.md.

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

### D-0224 — Recurring agent mistakes become checks or skill rules; orchestrator processes are managed
- Date: 2026-10-13 · Spec/PR: workflow (owner request) · Status: decided
- Decision: A finding that recurs is recorded in `docs/plans/RECURRING.md` and gets a check (preferred) or a skill rule in the same change (`/run-plan` §2a); ruff `PT012` is the first such check. Reviews end with a `Categories:` line. Workers report DONE only with the PR's SonarCloud gate `OK`. The orchestrator runs one watcher for all agents, refuses new agents below 1.5 GB free, closes finished panes, and removes a worktree's `crawlerai-*` containers on merge, through `tools/orchestrator/` scripts (`/run-plan` §1a).
- Alternatives: keep lessons in session memory only; one `herdr agent wait` per agent.
- Why: The owner asked that repeated mistakes, visible in SonarCloud, become checks or skills that survive new sessions, and that the orchestrator manage processes so the machine never hangs. S8707, S5778 and red-gate DONE reports each recurred; the low-memory reaper killed per-agent watchers twice.
- Reversible: yes

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

### D-0270 — Cleanup removes all Docker build cache after each merge
- Date: 2026-10-13 · Spec/PR: workflow (#51, owner request) · Status: decided (owner)
- Decision: `cleanup_worktree.sh` removes `crawlerai-*` containers with `-v`, all build cache (`docker builder prune -af`) and dangling images after each merge; a failed prune warns on stderr.
- Alternatives: Cap the cache at 5 GB (`--max-used-space`).
- Why: Owner, 2026-10-13: "i dont need any cache in docker". The cache is host-wide, so other projects' builds get slower too.
- Reversible: yes

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

### D-0311 — GeoNames has no versioned download URL
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: superseded by D-0953
- Decision: Needed: a stable source for the four pinned GeoNames files (SPEC-04 §4.6). `download.geonames.org/export/dump/*` is rewritten daily, so the pinned sha256 (the 2026-10-13 snapshot) stops matching and `crawlerai data fetch` refuses ("the entry needs re-pinning").
- Alternatives: (a) re-pin in a PR whenever a fetch is needed; (b) mirror the pinned snapshot as a release asset of this repo (CC BY 4.0 allows it with attribution) and point `url` at it; (c) an owner-run object-store mirror.
- Why: Recommendation (b), a one-time owner action. Blocked: SPEC-05's first real run; tests use a synthetic gazetteer and CI never fetches.
- Reversible: yes — change the manifest `url`.
- Owner answer: confirmed 2026-10-16, option (b): mirror the pinned snapshot as a release asset of this repo (CC BY 4.0, attribution in the release notes and NOTICE). Re-pinned to the 2026-10-15 snapshot in #204 (D-0914); the owner creates the release (ACTIVE H8).

### D-0319 — One review per PR; `MERGE AFTER FIX` is not re-reviewed
- Date: 2026-10-13 · Spec/PR: workflow (#63) · Status: decided (owner)
- Decision: Each PR gets one review once complete and green. With `MERGE AFTER FIX` the implementor makes the fixes, gets CI green and comments `READY`; no second review.
- Alternatives: The same reviewer ticks off the fixes.
- Why: Owner choice, 2026-10-13.
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

### D-0355 — Derived `url` values and INV-22
- Date: 2026-10-13 · Spec/PR: SPEC-05 PR 2 (#72) · Status: confirmed
- Decision: Question: INV-22 requires `evidence`, `source_kind` and `locator` on every published field, but the `canonical_link` and `final_url` derivations (SPEC-05 §4.8, D-0019) have no candidate, no §6 `SourceKind` and no §10 bucket. Options: (a) a `derived` source kind and evidence bucket, with locators for the link and the final URL (ARCHITECTURE §6/§10 and a migration); (b) exempt `derived_by` fields from those INV-22 attributes; (c) keep a derived `url` in `field_meta` only. Recommendation: (a). Blocked: SPEC-05 PR 7 and PR 8. The models enforce INV-22 as written.
- Alternatives: See options.
- Why: Every published value keeps its provenance and is calibrated like any other bucket.
- Reversible: yes
- Owner answer: confirmed 2026-10-16, option (a): a `derived` source kind and evidence bucket with locators for the canonical link and the final URL (ARCHITECTURE Appendix A #40). Implemented in #204 (D-0910, D-0911).

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

### D-0378 — Row-level readiness
- Date: 2026-10-13 · Spec/PR: none, workflow chore (#75) · Status: confirmed
- Decision: A row is ready when the code it touches is merged, or what it needs from unmerged work is fully specified, even if its spec's other dependencies or earlier rows aren't `done`. `/run-plan` §1.1, `/implement-pr` §0 and ACTIVE.md say so.
- Alternatives: A row waits until its spec's dependencies and earlier rows are `done` (the old rule).
- Why: The old rule left worker slots idle on rows whose inputs already existed.
- Reversible: yes — restore the old rule in the three places.
- Owner answer: owner direction, 2026-10-13.

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

### D-0539 — `wait_ci.sh` treats a missing `backend` check after a grace period as "CI never started"
- Date: 2026-10-14 · Spec/PR: tooling chore (#112) · Status: decided
- Decision: CI counts as started when the ci workflow's `backend` check (no `needs:`) appears on the head, the same check the success condition already requires. Grace is 5 minutes from the start of the wait (`WAIT_CI_NO_RUN_S`); a `CONFLICTING`/`DIRTY` PR fails at once.
- Alternatives: count check runs with a `workflowName`; `gh run list --commit` (needs the full SHA and a second call).
- Why: one definition of "CI started"; a `workflowName` count could be met by another workflow while `backend` never comes, which is the hang this fixes (#109).
- Reversible: yes — edit `tools/orchestrator/wait_ci.sh`.

### D-0576 — `drift_margins.json` is a dev-fitted file under `backend/data/` (with D-0444)
- Date: 2026-10-14 · Spec/PR: SPEC-08 PR 9 (#119) · Status: confirmed
- Decision: Question: `drift_margins.json` (§4.9) is a third dev-fitted file under `backend/data/`, like `calibration.json` and `source_precedence.yaml`, so INV-05's pinned-sha256 rule blocks it the same way. Options: (a) as D-0444 (a): the manifest check exempts stamped dev-fitted files, and the spec's `{"yield": 0.2, "validity": 0.1, "source_split": "dev"}` is committed; (b)/(c) as D-0444. Recommendation: answer with OPEN_QUESTIONS #19, option (a). Blocked: drift suspension in production; until then windows are recorded and nothing is suspended (C7: no default margin). Copied to OPEN_QUESTIONS #20.
- Alternatives: See options.
- Why: The same contradiction as D-0444 (CLAUDE.md §4).
- Reversible: yes
- Owner answer: confirmed 2026-10-16, option (a): the manifest check exempts stamped dev-fitted files; the spec's margins are committed with the stamp "spec default, unfitted". Implemented in #204 (D-0913).

### D-0647 — Worktree cleanup checks the merge itself
- Date: 2026-10-14 · Spec/PR: chore, run-plan §2a (#133) · Status: decided
- Decision: `cleanup_worktree.sh` removes nothing while a PR of the branch is open, or while a branch tip (local or remote) is neither the head of a merged PR nor in origin/main; a failed PR query also refuses. `/run-plan` §1.3 gives the gated `if merge_pr.sh ...; then ...; fi` form. No `merge_and_cleanup.sh` wrapper.
- Alternatives: A merge-and-cleanup wrapper script; the skill rule alone.
- Why: The check guards the destructive step for every caller and call order, including a `;` chain after a failed merge (#128).
- Reversible: yes

### D-0648 — Prompt suggestions off per agent pane
- Date: 2026-10-14 · Spec/PR: chore, run-plan §2a (#133) · Status: decided
- Decision: `start_agent.sh` opens each agent tab with `herdr tab create --env CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION=false`; the agent inherits it from the pane's shell (checked: a started agent printed `false`).
- Alternatives: `promptSuggestionEnabled: false` in `.claude/settings.json` or `~/.claude`.
- Why: It is scoped to orchestrated agents, and the owner's own sessions keep suggestions.
- Reversible: yes

### D-0656 — The `/sites` screen opens a site by host; a sites table needs a `GET /v1/sites` endpoint
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 6 (#134) · Status: confirmed
- Decision: `/sites` is a host lookup that opens `/sites/{host}` (config versions from `GET /v1/sites/{host}/configs`). SPEC-12 §4.3's sites table (host, fetch method, mode per schema, pages extracted) is not built: ARCHITECTURE §13.1 has no endpoint that lists sites.
- Alternatives: (a) add `GET /v1/sites` to §13.1 and SPEC-08 (a public API change); (b) amend SPEC-12 §4.3 to the host lookup.
- Why: Adding an endpoint changes the public API, which is the owner's call (CLAUDE.md §4). Recommendation: (b) now, (a) when operators need the table. Blocks nothing.
- Reversible: yes
- Owner answer: confirmed 2026-10-16, option (b): SPEC-12 §4.3 amended to the host lookup as built; a sites table later, when needed (#204).

### D-0665 — Hamming ≤ 3 lets a one-word change, such as a new price, pass as `unchanged`
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 2 (#135) · Status: confirmed
- Question: ARCHITECTURE §14 row 2 treats Hamming ≤ 3 as unchanged and skips extraction. On 100 fixed-seed 500-word texts, a one-word edit stays within 3 bits on 87 seeds and moves 4 to 6 bits on the other 13 (the test asserts at least 80, and that some exceed 3). So on a long page, a change to a single visible token (a price, a stock count, a date) usually skips extraction, and row 3's record version and change feed never see it. The threshold is meant to skip boilerplate-only changes. Nonces and whitespace are already ignored structurally, at Hamming 0.
- Options:
  - (a) Keep ≤ 3 as built here, and confirm on dev (D-0039).
  - (b) Treat only Hamming 0 as unchanged, so SimHash serves only for its nonce and whitespace invariance. This changes ARCHITECTURE §14.
  - (c) Make the threshold depend on text length.
- Recommendation: (b), until dev results show which boilerplate changes ≤ 3 would absorb. It is a one-constant change (`UNCHANGED_BITS`).
- Blocked: nothing in this PR. It affects whether PR 3's "a changed price yields a new record version" holds on real long pages.
- Owner answer: confirmed 2026-10-16, option (b): only Hamming 0 counts as unchanged (`UNCHANGED_BITS = 0`); ARCHITECTURE §14 row 2 amended (#204). SimHash still misses some one-word edits: D-0915.

### D-0680 — Recurring Sonar test-style rules become ruff checks
- Date: 2026-10-14 · Spec/PR: owner chore, Sonar settings and debt (#138) · Status: decided
- Decision: ruff `PT018` (one condition per assert) and `PT022` (no `yield` in a fixture without teardown) are enabled for `backend/` and `tools/`. Neither is a size gate (C11).
- Alternatives: Leave them to SonarCloud; scope a Sonar ignore to test paths.
- Why: SonarCloud `python:S9073` (composite assert) fired 28 + 31 times in tests and `S9100` 4 times; a recurring finding gets a check (`docs/plans/RECURRING.md`). Both are real style findings, not false positives, so an ignore would be wrong.
- Reversible: yes

### D-0711 — Learn jobs run in the worker process
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: `crawlerai worker` runs `run_learner` beside `run_worker`; it polls `next_learn_job` every 30 s and runs `run_learn_job` with an LLM client from settings.
- Alternatives: A scheduler entry (it would hold the scheduler's turn for a whole run); a separate command.
- Why: D-0624 named the worker; `run_learn_job` manages its own transactions; the scheduler starts runs once a minute.
- Reversible: yes

### D-0712 — A learn run still running after an hour ends as a failed run
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: The scheduler's `expire_learn_runs` ends runs `running` past `LEARN_RUN_TIMEOUT` (1 h) as `failed` with reason `expired`, and a run that finishes after expiry writes nothing; a job that cannot start ends `failed`. Answers D-0624's open items.
- Alternatives: A job lease or heartbeat (a SPEC-01 queue change).
- Why: A run makes a few role A calls of at most 120 s each per provider, so one hour means its process died.
- Reversible: yes

### D-0713 — Cancelling a learn job ends its run
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: Cancelling a queued learn job calls `learning_failed` in the cancel transaction; a running one is left to its run, which ends `cancelled` on `cancel_requested` (before, `settle_job` ended a task-less running job at once and left the state `learning`).
- Alternatives: Settle a running learn job at once and end its state there.
- Why: D-0622: every non-activating end calls `learning_failed`, and only the run knows when it has stopped.
- Reversible: yes

### D-0714 — Role C is bound in scrape, extract and crawl, not in batch or the captures replay
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: `scrape` records and the worker's `extract` and `crawl` handlers bind `role_c` charged to the job; batch (D-0631, D-0635) and the captures replay (D-0523, D-0524) bind none. The eval replay binds role C on every page, so batch records can differ from it by D-0631's choice.
- Alternatives: Bind role C in batch too; make the replay skip role C per job kind.
- Why: SPEC-07 §4.4 step 3, SPEC-10 §4.6, ARCHITECTURE §8.4; D-0507 deferred it only until SPEC-06 PR 4.
- Reversible: yes

### D-0715 — A worker task counts its fetch usage after the extraction
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: `fetch_page` returns the attempts of a reached page and the handler counts them (`count_fetch`) after extracting; crawl reads sitemaps after the page.
- Alternatives: Commit the fetch usage in a transaction of its own (breaks INV-31's one transaction per task).
- Why: D-0346: role C's client updates the job's usage on its own connection and would wait on the task's uncommitted job-row write.
- Reversible: yes

### D-0716 — The eval API takes the API key and is rate-limited; /labeling sits behind RequireKey
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: `/v1/eval` requires `require_api_key`; the labeling screens read through TanStack queries on `useApiClient`. Supersedes D-0344 and D-0380 for the eval API; `/healthz` stays public.
- Alternatives: Keep the eval API unauthenticated in dev.
- Why: SPEC-03 §4.10: "same API-key auth as everything else"; D-0344 misread it.
- Reversible: yes

### D-0717 — Every job kind keys `url_task.canonical_url` by `crawl.canonical.canonicalize`
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided
- Decision: Scrape and batch use the sorted-query form, as extract and crawl do.
- Alternatives: The url type's form (query order kept) for every kind.
- Why: SPEC-10 §4.1; SPEC-05 §4.10 needs one entity key per page.
- Reversible: yes

### D-0718 — Rows keyed by the unsorted query form before #149
- Date: 2026-10-14 · Spec/PR: Integration review (#149) · Status: decided (owner, 2026-10-14): (a)
- Decision: Question: `record.entity_key`, `url_state.canonical_url` and `url_task.canonical_url` written by scrape or batch for URLs with two or more query pairs out of order no longer match new writes, so those pages start a new version chain once. Options: (a) leave them; (b) a backfill migration that recomputes keys and merges chains. Recommendation: (a) (no production data yet). Blocked: nothing.
- Alternatives: (b) a backfill migration.
- Why: Rewriting stored data needs the owner (CLAUDE.md §4).
- Reversible: yes
- Owner answer: owner, 2026-10-14: option (a), leave the rows keyed by the unsorted query form; no backfill.

### D-0741 — The worker, scheduler and API keep the Proactor event loop on Windows
- Date: 2026-10-14 · Spec/PR: UAT fix F06 (#153) · Status: decided
- Decision: No `WindowsSelectorEventLoopPolicy`; asyncio's default loop stays.
- Alternatives: The selector loop policy for every process.
- Why: The UAT crash was a use-after-free in curl_cffi's handle release (D-0742), not the loop. On Windows only the Proactor loop runs subprocesses, which the browser rung (Patchright) needs; curl_cffi's selector thread on Proactor is supported upstream.
- Reversible: yes

### D-0742 — `acquire/http.py` removes a request's curl handle before curl_cffi frees its callbacks
- Date: 2026-10-14 · Spec/PR: UAT fix F06 (#153) · Status: decided
- Decision: `_Session.release_curl` removes the handle from the multi handle first; `curl-cffi` is pinned `>=0.16,<0.17` because the workaround uses the session's internals.
- Alternatives: Drop `DEBUGFUNCTION` (loses the sent request headers, SPEC-02 §4.7); never cancel a fetch (outer time caps would not hold).
- Why: curl_cffi 0.16.3 (the latest release) frees the debug callback's data before removing an in-flight handle, whose connection close then calls it: a native crash on any cancelled fetch, such as the crawl's sitemap time cap.
- Reversible: yes

### D-0743 — Every lock of a job's row is FOR NO KEY UPDATE
- Date: 2026-10-14 · Spec/PR: UAT fix F16 (#153) · Status: decided
- Decision: `cancel_job`, `settle_job`, `Frontier.enqueue` and a learn run's `_abandon` lock the job row FOR NO KEY UPDATE; a crawl reads sitemaps before it writes its job's row.
- Alternatives: Commit each task in several transactions; keep FOR UPDATE.
- Why: FOR UPDATE waits on the FOR KEY SHARE that a running task's inserts referring to the job hold until it commits, so a cancel waited for a whole sitemap read; FOR NO KEY UPDATE still serializes every writer of the row (PostgreSQL row-level locks).
- Reversible: yes

### D-0744 — `crawlerai data fetch` tries every entry and reports the refused ones together
- Date: 2026-10-14 · Spec/PR: UAT fix F11 (#153) · Status: decided
- Decision: `fetch_data` returns `DataReport(written, refused)`; a refused entry (path outside the data directory, non-https URL, failed or cut-short download, hash mismatch, failed write) never stops the others, and the CLI exits 2 if any was refused.
- Alternatives: Stop at the first refusal (before).
- Why: One re-pinned source (D-0311) kept unrelated data, such as the schema.org vocabulary, from being fetched.
- Reversible: yes

### D-0745 — Exposing task failure and block reasons in the jobs API
- Date: 2026-10-14 · Spec/PR: UAT fix F17, F16 (#153) · Status: answered 2026-10-14
- Decision: Not built. Question: should the API expose `url_task.last_error` and a task-failure event? SPEC-10 defines neither (`PageOutput` has no reason; §4.2's event kinds have no task failure), and the job summary has no `cancel_requested`.
- Alternatives: (a) `PageOutput.last_error: str | null` on `/results` plus a `task_failed` event `{task_id, url, attempts, last_error}`; (b) a per-task listing endpoint, which also covers records jobs; (c) leave it. Also: `cancel_requested: bool` on the job summary, so the job page can show "cancel requested" while a dead worker's lease runs out.
- Why: A public API change beyond the spec (CLAUDE.md §4). Recommendation: (a) plus `cancel_requested`; additive fields, and the worker already writes `last_error` redacted (SPEC-01 §4). Blocks the F17 UI (fix/uat-frontend).
- Reversible: yes
- Owner answer: option (a) with `cancel_requested` (owner 2026-10-14). Implemented in #157 (D-0760, D-0761); SPEC-10, SPEC-12 and ARCHITECTURE rev 12 updated.

### D-0746 — Role replies use wire forms inside every provider's structured-output subset
- Date: 2026-10-14 · Spec/PR: UAT fix F01–F04, F09 (#154) · Status: decided
- Decision: Role C replies with a list of `{field, value, start, end}` claims (a field claimed twice is dropped, C7); role S with `llm/roles/s_wire` (fields as a list, `""`/`[]` for an absent parameter, nesting unrolled to `MAX_DEPTH`); role A with `config_ir/step_wire` (`{selector, expression, when_type, source, post}`), a listing's extra `next` steps being `invalid_step` instead of the schema's `maxItems: 1`. Each reply is read back into the role's model; SPEC-06 §4.2, §4.4, §4.5 and SPEC-08 §4.6 clarified.
- Alternatives: Strip unsupported keywords per provider (can't fix recursion or the union cap); instruct JSON without native structured output.
- Why: Constrained decoding on both providers for any field count; ARCHITECTURE §11's grounding and selector rules are unchanged.
- Reversible: yes

### D-0747 — Provider structured-output subsets are versioned data
- Date: 2026-10-14 · Spec/PR: UAT fix F01–F04, F09 (#154) · Status: decided
- Decision: `backend/data/llm/{anthropic,gemini}-structured-output.json`, pinned in the manifest with the provider's documentation page, read by `llm.schema_subset`; a property test checks every role's schema against each.
- Alternatives: Constants in code citing the documentation URLs, which the C3 scan refuses.
- Why: C4, following the pricing files (SPEC-06 §4.8).
- Reversible: yes

### D-0748 — A provider's refusal is `ProviderRefused`
- Date: 2026-10-14 · Spec/PR: UAT fix F01–F04, F09 (#154) · Status: decided
- Decision: An HTTP error status that `is_transient` does not cover raises `ProviderRefused`, a subclass of `ProviderUnavailable` (code and field reason `llm_unavailable`, problem 503) carrying the provider's status and message; it is neither retried nor failed over.
- Alternatives: A new code or problem type (a public API shape); failing over on a refusal.
- Why: SPEC-06 §4.7 names `llm_unavailable` for a call without a reply; `is_transient` already says other statuses are not failed over.
- Reversible: yes

### D-0749 — A scrape that fails for an undeclared reason records `internal_error`
- Date: 2026-10-14 · Spec/PR: UAT fix F01–F04, F09 (#154) · Status: decided
- Decision: `services.scrape` fails the task and job with `last_error = internal_error` on any exception it does not declare, then re-raises.
- Alternatives: The exception's class name.
- Why: A stable code like scrape's other `last_error` codes; the job ends at once instead of after the lease (UAT F09).
- Reversible: yes

### D-0750 — The job event stream reconnects after 35 s without a byte
- Date: 2026-10-14 · Spec/PR: UAT fix F08 (#152) · Status: decided
- Decision: A stream silent for 35 s counts as dropped and reconnects with `Last-Event-ID`; any byte, a heartbeat too, resets the backoff. A reconnect rereads the job summary.
- Alternatives: 30 s (exactly two heartbeats, no margin); refetch the summary on a timer.
- Why: The server's keep-alive is 15 s of idle (SPEC-10 §4.2). `progress` isn't stored, so after a resume only the summary has the counts (UAT F08).
- Reversible: yes

### D-0751 — Paged tables hold 20 rows in a fixed-height box
- Date: 2026-10-14 · Spec/PR: UAT fix F19 (#152) · Status: decided
- Decision: `PagedTable` (components/) pages jobs, records and job results by 20 (`limit=20`) in a 66rem box (`--height-table-page`), with fixed column widths and the pager under it. Loading and error states fill the same box; taller rows scroll inside it.
- Alternatives: Pad short pages with empty rows (React Aria rows are focusable, so blank rows reach keyboard and screen-reader users); the server's default of 50.
- Why: The owner's rule: no layout shift on interaction (DESIGN.md, Data tables).
- Reversible: yes

### D-0752 — Scrape and batch forms don't offer listing pages for records
- Date: 2026-10-14 · Spec/PR: UAT fix F21 (#152) · Status: decided
- Decision: `PageKindChoices` disables Listing while Records is chosen, always showing "Records of listing pages are not available yet."; choosing Records clears a Listing choice.
- Alternatives: Keep it enabled and let the 422 explain.
- Why: The server always refuses the combination (D-0502, `check_records`).
- Reversible: yes — drop the rule when scrape takes listing records.

### D-0753 — A site page offers learning for any stored schema
- Date: 2026-10-14 · Spec/PR: UAT fix F13 (#152) · Status: decided
- Decision: Once its configs load, `/sites/{host}` shows a "Learn a config" form (schema picker, Learn now / Learn anyway), with or without configs.
- Alternatives: Only in the empty state.
- Why: A site without a config had no way to learn one from the UI (UAT F13); a site may need a config for another schema too.
- Reversible: yes

### D-0754 — Labeling prefill asks for confirmation
- Date: 2026-10-14 · Spec/PR: UAT fix F15 (#152) · Status: decided
- Decision: "Prefill from the LLM" asks first and is offered only for a page with no status or a draft; the stored draft and unsaved edits are replaced.
- Alternatives: No confirmation.
- Why: DESIGN.md: confirm before what can't be undone; D-0538: a prefill never replaces a labeled or checked page.
- Reversible: yes

### D-0755 — `start_agent.sh` accepts agent names matching `^[a-z0-9][a-z0-9-]*$`
- Date: 2026-10-14 · Spec/PR: run-plan §2a chore (#155) · Status: decided
- Decision: `tools/orchestrator/start_agent.sh` refuses any other NAME before it reads memory or opens a tab (`ERROR agent name must be lowercase ...`).
- Alternatives: Reject only uppercase letters; leave it to herdr.
- Why: herdr agent names are lowercase, and its help documents no other rule; every name the skills use fits this form, and a leading `-` would be read as an option.
- Reversible: yes

### D-0756 — Dev-fitted files are checked by their `source_split: dev` stamp, not pinned
- Date: 2026-10-14 · Spec/PR: OQ #19 fix (#156) · Status: decided (owner answer 2026-10-14)
- Decision: `data_manifest_check` exempts exactly `source_precedence.yaml` and `calibration.json` at the top of `backend/data/` from the pinned-sha256 rule and checks their `source_split: dev` stamp (top-level YAML key, JSON object key); a missing or non-dev stamp, or a manifest entry pinning either file, fails. INV-05 reworded to external data.
- Alternatives: (b) a manifest entry per fitted file whose sha256 the fit commands rewrite; (c) fitted files outside `backend/data/`.
- Why: D-0444 option (a), owner answer 2026-10-14.
- Reversible: yes

### D-0757 — The initial `source_precedence.yaml` is SPEC-05 §4.7's default for all four precedence types
- Date: 2026-10-14 · Spec/PR: OQ #19 fix (#156) · Status: decided
- Decision: `[adapter, api, jsonld, microdata, og, config, llm]` for text, long_text, url and image_url, stamped `source_split: dev` only (no `eval_run_id`/`git_sha`: no run fitted it). `fit-precedence` rewrites the whole file.
- Alternatives: Other orders for long_text, url and image_url.
- Why: The spec gives one default (`[...]` for url and image_url); `load_precedence` needs an order for all four types.
- Reversible: yes

### D-0758 — No `calibration.json` until the first dev fit
- Date: 2026-10-14 · Spec/PR: OQ #19 fix (#156) · Status: decided
- Decision: SPEC-05 PR 8's empty calibration is not committed.
- Alternatives: `{"buckets": {}}` with a placeholder eval run id and commit.
- Why: `Calibration` requires a dev run's `eval_run_id` and `git_sha`; a placeholder would be invented provenance (C7). A missing file already means every bucket is uncalibrated, and the engine version reports `cal.none`.
- Reversible: yes

### D-0759 — `drift_margins.json` is not covered by the OQ #19 answer
- Date: 2026-10-14 · Spec/PR: OQ #19 fix (#156) · Status: decided
- Decision: The drift margins are not committed; OPEN_QUESTIONS #20 / D-0576 stays open.
- Alternatives: Exempt and commit `drift_margins.json` in #156.
- Why: The owner's answer names exactly the two files.
- Reversible: yes

### D-0760 — `task_failed` is recorded only when a task ends `failed`
- Date: 2026-10-14 · Spec/PR: D-0745 (#157) · Status: decided
- Decision: `record_task_events` records `task_failed {task_id, url, attempts, last_error}` when the task's status becomes `failed` (its last attempt, a permanent failure, or an expired lease on its last attempt), after its other task events and before the job's end event. A task that ends `done` with a reason (`blocked`, `robots`) records none; its reason is on its page output's `last_error`.
- Alternatives: Also record an event for `done` tasks that have a reason.
- Why: The owner's wording ("fails terminally"); a `done` task's reason is already on its page output.
- Reversible: yes

### D-0761 — A requested cancel replaces the Cancel button with a label
- Date: 2026-10-14 · Spec/PR: D-0745 (#157) · Status: decided
- Decision: While a queued or running job's `cancel_requested` is true, the job page shows a warning-toned "cancel requested" label beside its status, in place of the Cancel button.
- Alternatives: Keep the button, which cancels again idempotently.
- Why: UAT F16 expected a visible pending state, and a second cancel has no effect.
- Reversible: yes

### D-0762 — A job's records are the ones its tasks stand for, through `task_record`
- Date: 2026-10-14 · Spec/PR: UAT re-run F28 (#158) · Status: decided
- Decision: `task_record (url_task_id, record_id)` (migration 0017; both FKs `ON DELETE CASCADE`, PK on both, index on `record_id`). `store_records` links each record it answers with, stored or found unchanged; an `unchanged` task (304 or SimHash) links its standing record. `RecordFilter.job_id` (job results, exports, MCP status results, `/v1/records?job_id`) selects through it. The migration backfills from `record.extraction_id → extraction.url_task_id`.
- Alternatives: `url_task.record_id` as SPEC-11 §4.2 names it, which cannot hold a listing page's one record per row; `Record.job_id` OR links for unchanged entities only, which gives two definitions of a job's records.
- Why: SPEC-11 §4.2/§4.4 say the task references the existing latest record, and job results carry `changed_fields` per record. This is plumbing for the column §4.2 names, generalized to listings (D-0664 deferred it).
- Reversible: yes

### D-0763 — A re-extraction that changes only `field_meta` stores nothing
- Date: 2026-10-14 · Spec/PR: UAT re-run F31 (#158) · Status: decided
- Decision: SPEC-11 §4.4 as written: an equal record fingerprint inserts nothing and leaves the stored row, its reasons and provenance included, unchanged. The stored `field_meta` describes the extraction that stored the record.
- Alternatives: Rewrite the stored row's `field_meta` in place, which mixes two extractions in one row and breaks that record's replay (INV-10); store a new version on a reason-only change, which contradicts §4.4, adds versions on every LLM outage and recovery, and has empty `changed_fields`.
- Why: The spec is explicit, and both alternatives are less conservative. Fresh reasons belong with the task's extraction, not the record.
- Reversible: yes

### D-0764 — Job end times and event times use `clock_timestamp()`
- Date: 2026-10-14 · Spec/PR: UAT re-run F34 (#158) · Status: decided
- Decision: `transition_job` stamps `finished_at` and the end event's `ts` with one `clock_timestamp()` value; `record_event` stamps every event with `clock_timestamp()`.
- Alternatives: Settle the job in its own transaction after the task's.
- Why: A job settles at the end of its last task's transaction, where `now()` is when that transaction began (PostgreSQL §9.9.5). The queue's leases already use `clock_timestamp()` for the same reason.
- Reversible: yes

### D-0765 — Role C replies with one required claim per asked field
- Date: 2026-10-14 · Spec/PR: UAT re-run F29 (#159) · Status: decided
- Decision: Role C's wire form is `{fields: {<name>: {value, start, end}}}`, a closed object with one required claim per asked field; an empty value means the page does not show it. Listing rows and page fields use the same shape. This supersedes D-0746 for role C (its list of claims, and the dropped "claimed twice" case); SPEC-06 §4.4 updated.
- Alternatives: Keep the list with `maxItems` (Anthropic's subset has none); a per-provider schema.
- Why: Bounds a reply's claims by the fields asked within both providers' structured-output subsets; neither has `maxLength`, so a value is bounded by the token cap (D-0767).
- Reversible: yes

### D-0766 — A fast Anthropic call asks for low effort
- Date: 2026-10-14 · Spec/PR: UAT re-run F29 (#159) · Status: decided
- Decision: The Anthropic provider sends `output_config.effort = "low"` for `model_class="fast"`; a `strong` call keeps the model's default.
- Alternatives: `thinking: disabled` (refused by some current models); a setting per model class.
- Why: Current Claude models think by default, and thinking tokens count against `max_tokens`; role C copies spans. A configured model without `effort` support would be refused, and the refusal is logged (D-0769).
- Reversible: yes

### D-0767 — A reply cut at its output cap is not retried
- Date: 2026-10-14 · Spec/PR: UAT re-run F29 (#159) · Status: decided
- Decision: A provider stop reason `max_tokens` / `MAX_TOKENS` marks the reply `cut`; an invalid cut reply, first or retry, raises `OutputCut` (reason `llm_output_invalid`), and a cut first reply is not retried. A complete, schema-invalid reply keeps the one retry (SPEC-06 §4.2).
- Alternatives: Retry with a larger cap.
- Why: The same request with the same cap is cut again, and both calls are paid (UAT: 6 of 6).
- Reversible: yes

### D-0768 — Failed calls count on the extraction
- Date: 2026-10-14 · Spec/PR: UAT re-run F30 (#159) · Status: decided
- Decision: `LLMFailure.answered` and `LLMResponse.answered` carry every call that answered, a retried one included; role C records them in `extraction.llm_calls`, so the extraction and the `task_extracted` event match usage.
- Alternatives: Count successful calls only (the old behaviour, which disagreed with usage); derive the count from usage events by `request_hash`.
- Why: Each answered call is charged (INV-23).
- Reversible: yes

### D-0769 — Provider refusals are logged once, and their cause is in the diagnostic
- Date: 2026-10-14 · Spec/PR: UAT re-run F33 (#159) · Status: decided
- Decision: `ProviderRefused` carries provider, model, status and the provider's message with the API key redacted; the client logs it at WARNING once per (provider, model, status). A page diagnostic appends the cause for `ProviderUnavailable`, `ProviderRefused` and `OutputCut`; a schema error's message, which can quote page text, is left out.
- Alternatives: Log every failure; dedupe per process at module level.
- Why: A refusal repeats on every call until the settings change, and its message is what the operator needs.
- Reversible: yes

### D-0770 — Tests never see the process's `CRAWLERAI_*` variables
- Date: 2026-10-14 · Spec/PR: UAT re-run F27 (#159) · Status: decided
- Decision: An autouse fixture in `backend/tests/conftest.py` removes every `CRAWLERAI_*` variable except `CRAWLERAI_TEST_*` (the test databases) for each test; per-test key removals are dropped.
- Alternatives: `monkeypatch.delenv` in each settings test; stop exporting `.env` in the Makefile.
- Why: `make check` exports the developer's `.env`, and settings a test builds read the environment.
- Reversible: yes

### D-0771 — Adopting a prompt draft starts with an empty name
- Date: 2026-10-14 · Spec/PR: UAT re-run F32 (#160) · Status: decided
- Decision: `/schemas/new?from=<id>` prefills the source schema's document without its name, and the Name field says a name must be one no other schema has.
- Alternatives: Suffix the draft's name (a guess the user didn't make); save as a new version of the draft (SPEC-12 §4.3 says adoption creates a `user` schema via `POST`).
- Why: The draft's own name is taken by its versions, so prefilling it made every Save answer 409.
- Reversible: yes

### D-0772 — One vitest timeout for every frontend test file
- Date: 2026-10-14 · Spec/PR: UAT re-run F35 (#160) · Status: decided
- Decision: `test.testTimeout: 20_000` in `frontend/vite.config.ts` replaces six per-file `vi.setConfig` calls; screen tests connect through `src/test/connect.ts`, which pastes the key.
- Alternatives: Add the override to the one file without it (the next new file forgets it again).
- Why: Every screen test renders the whole app through its router; the one file without the override was the one that timed out under load.
- Reversible: yes

### D-0778 — Typefaces are bundled with the app, not loaded from a font service
- Date: 2026-10-15 · Spec/PR: DESIGN.md, UI refresh (#164) · Status: decided
- Decision: Inter and JetBrains Mono come from the Fontsource packages (`@fontsource-variable/*`, OFL-1.1), imported only by `src/app/theme.css`; no page loads a font, script or style from a third-party service.
- Alternatives: A Google Fonts `@import`.
- Why: A self-hosted tool should make no third-party request on each load and should work offline.
- Reversible: yes

### D-0779 — Timestamps show in the viewer's time zone on a 24-hour clock
- Date: 2026-10-15 · Spec/PR: DESIGN.md, UI refresh (#164) · Status: decided
- Decision: `Timestamp` renders an API time as a short local date and 24-hour time in a `<time>` element, the exact instant in `dateTime` and its tooltip; tests pin `TZ=UTC`.
- Alternatives: Raw RFC 3339 text; a 12-hour clock.
- Why: Readable dates; a column of times lines up without AM/PM markers.
- Reversible: yes

### D-0782 — Investigate: variants, availability and stock
- Date: 2026-10-15 · Spec/PR: accuracy Q3 (#167) · Status: confirmed (2026-10-16)
- Decision: Question: how should availability and stock stated in words ("In stock (N available)") be read, given they belong to the selected variant? Options from the classification: (a) `schema:` enums also match their members' de-camel-cased names as a token run, derived from the pinned schema.org file; (b) as (a), but only as the leading token run of the text; (c) keep exact matching. Owner direction: availability and stock belong with **variants**, which are not built (ARCHITECTURE §22, D-0440); variants change the architecture and are hard to get right, so enum matching does not change now.
- Alternatives: See options.
- Why: Evidence: the UAT re-run declined availability as `invalid` on every page without structured availability (13/13 on one site, 13/19 on another); a repro showed the `type:availability` vocabulary maps "Not in stock" to `InStock`, a wrong value. A Shopify baseline (10 stores, 49 variant pages) found 44/49 pages carrying several offers or `hasVariant`. Blocked: nothing; availability from text stays declined.
- Reversible: yes
- Owner answer: 2026-10-16, "build it": availability and stock quantity are separate fields; availability in words or codes ("in stock", "instock", "available", "In stock (5 available)") normalizes to schema.org `ItemAvailability`, one convention in the repo; stock quantity is its own field (5); variants carry them when the page states them per variant, otherwise publish what the page shows. Built in #203 (D-0920–D-0924, ARCHITECTURE Appendix A #39).

### D-0783 — Investigate: approving a learned config before it becomes a reusable recipe
- Date: 2026-10-15 · Spec/PR: accuracy Q4 (#167) · Status: answered (owner delegation 2026-10-17, D-1342)
- Decision: Question: should a learned config need human approval before it becomes a reusable recipe, at least where sources conflict or several sources compete, or can another mechanism make approval unnecessary? Ideas from the classification: corroboration only by a reference from a different source than the step reads (a `jsonld` step not corroborated by `jsonld`, §10's independence applied to §8.3 step 4); learning reports per-entity fields that are constant across the sample entities, or share an affix, as `suspect`. Owner direction: approval is probably needed; this changes the architecture, so corroboration does not change now.
- Alternatives: See ideas; keep corroboration as is.
- Why: Evidence: on one site the config's JSON-LD steps were "corroborated" by the same JSON-LD values (circular); a title kept the site-name suffix on every page; an image URL was one placeholder shared by every product on two sites. Blocked: nothing; values are unchanged meanwhile.
- Reversible: yes
- Owner answer: owner 2026-10-16: not now. Answered 2026-10-17 under owner delegation: optional approval by the project setting `require_config_approval` (D-1342, owner decision #60, #252).

### D-0784 — Investigate: an "absent" field status so role C stops asking
- Date: 2026-10-15 · Spec/PR: accuracy Q1 option C (#167) · Status: answered (owner delegation 2026-10-17, D-1341)
- Decision: Question: should learning record a required field as `absent` for a (site, schema, page kind) when role C returned no grounded value on every held-out page, so the §4.13 gap rule skips it until drift, a re-learn or a page showing a value re-tests it? It changes ARCHITECTURE §8.3 and §8.4 (a field status), SPEC-05 §4.13 and SPEC-08 §4.7–§4.9. Owner direction: part of the learned-config investigation (D-0783); not built.
- Alternatives: Keep asking role C on every page for a required field the site never shows; make more fields optional per preset (as `brand`, D-0781).
- Why: Evidence: with `brand` and `url` absent on several UAT sites, role C ran once per page on every page, in config mode too. Blocked: nothing; the gap rule is unchanged.
- Reversible: yes
- Owner answer: owner 2026-10-16: not now. Answered 2026-10-17 under owner delegation: an `absent` field status learned from the run's pages (D-1341, owner decision #60, #252).

### D-0810 — Additional fields: how typed field names become an extraction
- Date: 2026-10-15 · Spec/PR: SPEC-14 PR 11 · Status: confirmed
- Context: v1 let a user type field names as chips for an ad-hoc extraction. v2 extracts by a schema (stored, inline or drafted from a prompt; prompts only on scrape and extract).
- Options: (a) a `fields` request member; the server drafts a typed schema from the names (role S); (b) the UI sends the names as a prompt where prompts are allowed; (c) chips pick fields from presets and stored schemas.
- Recommendation: (a), one path for every run type, with the draft shown for editing; it changes the public API.
- Blocked: SPEC-14 PR 11 only. The owner discusses it before it is built.
- Owner answer: confirmed 2026-10-16, option (a): a `fields` request member; the server drafts a typed schema from the names with role S, shown for editing before the run; one path for every run type; public API change approved (ARCHITECTURE Appendix A #41, rev 20). Implemented in #205 (D-0925–D-0929).

### D-0820 — Decisions log split by spec
- Date: 2026-10-15 · Spec/PR: workflow (owner request) · Status: decided
- Decision: An entry moves verbatim to `docs/decisions/SPEC-NN.md` when its Spec/PR field names a spec; a field naming several specs puts it under the first named (D-0719–D-0727 → SPEC-06). Entries with no spec in that field (workflow, UAT, review fixes, owner), the D-0001–D-0044 spec-authoring block, and every entry whose status says `needs-owner` or `pending-owner` stay in `DECISIONS.md`. Moved files keep ID order; entries are separated by one blank line.
- Alternatives: split by D-ID range; split by the PR's main spec, decided per entry by hand.
- Why: Agents read only their spec's file and the index of open items (`CLAUDE.md` §1), so `DECISIONS.md` dropped from 5,582 lines to under 750. The field rule is mechanical and checkable; a one-off script checked that no entry text changed.
- Reversible: yes — concatenate the files in ID order.

### D-0821 — Lean ACTIVE.md
- Date: 2026-10-15 · Spec/PR: workflow (owner request) · Status: decided
- Decision: "Current focus" is 3-6 lines; "Done: …" bullets are deleted; fully done specs collapse to one "Done specs" line; open follow-ups from those tables and bullets move to "Follow-ups", one line each with the source PR. SPEC-03 keeps only its `human` row 7 (with the #32 and #34 notes); SPEC-14 keeps its table. Follow-ups found done were dropped (`url_task.record_id`, built as `task_record`; table notes addressed to a later row of the same spec that is now done); the rest are kept, the smaller unverified ones on two grouped lines.
- Alternatives: keep the tables and only trim notes.
- Why: Agents read ACTIVE.md every session; 295 lines became about 110. Git history and the decisions log keep the rest.
- Reversible: yes — git history.

### D-0822 — Batch PRs and `new_worktree.sh`
- Date: 2026-10-15 · Spec/PR: workflow (owner request) · Status: decided
- Decision: One PR covers a batch of related ready rows (30-80 files, about 1500-4000 lines), branch `spec-NN/pr-A-B-<name>`, worktree `spec-NN-pr-A-B`. `tools/orchestrator/new_worktree.sh NAME BRANCH` fetches origin and adds the worktree beside the main checkout (first entry of `git worktree list`, as `start_agent.sh` and `cleanup_worktree.sh` find it), refusing an existing path, an existing local or remote branch, or a NAME that is a path; the local checks run before any network call.
- Alternatives: a `config.sh` with `WORKTREE_ROOT` as in the owner's other project; keep raw `git worktree add` in the skills.
- Why: Fewer, larger PRs cut per-PR review and CI overhead; the script removes the `C:/c/` path mistake and branch reuse. No new config file: the other scripts already derive the root.
- Reversible: yes.

### D-0823 — The orchestrator only orchestrates; the implementor hands back a READY PR
- Date: 2026-10-15 · Spec/PR: workflow (owner request) · Status: decided · Supersedes the `YOUR TURN` handshake
- Decision: The orchestrator gives each implementor five free decision IDs at assignment, merges on `READY <sha7>` with `merge_pr.sh`, closes panes, cleans up, sends `REBASE` only when a branch is behind `main` or conflicts, and unblocks stuck PRs. The implementor starts its one reviewer, reads the verdict comment itself, fixes, adds the tracker commit (rows, follow-ups, decisions; "Current focus" only when asked) and comments `READY`. Reviewers post verdicts with `gh pr comment`. An escalation PR still needs its one review.
- Alternatives: keep `YOUR TURN` (the orchestrator sequences each tracker commit).
- Why: Owner request; the handshake cost a round trip per PR, and non-overlapping ID ranges remove the clash it prevented.
- Reversible: yes — skills and `CLAUDE.md` §3.

### D-0824 — `/simplify` once per PR; analyser patterns in ENGINEERING
- Date: 2026-10-15 · Spec/PR: workflow (owner request) · Status: decided
- Decision: `/implement-pr` §2a runs `/simplify` once, after the behaviour and tests, before the PR opens (restoring what #181 removed); later prompts to re-run it or a review get "already ran". ENGINEERING "Patterns the analysers flag" lists the SonarCloud rules that fired more than once in the project's issue history (218 issues), except S5655 (mypy disagrees) and S101 on the generated `schema.d.ts` (excluded since).
- Alternatives: a SonarCloud quality profile change (needs the owner's account).
- Why: Owner request; S5778, S9073 and the shell rules recurred across PRs.
- Reversible: yes.

### D-0845 — `merge_pr.sh` tells the reviewer's verdict by its form
- Date: 2026-10-15 · Spec/PR: workflow (#193) · Status: decided
- Context: `merge_pr.sh` refuses a PR without `READY <sha7>` and a reviewer's verdict from a non-author, but every agent posts as the owner's one GitHub account, so a login check would refuse every PR.
- Decision: The verdict is a comment that starts with `## Review` and has a line `**Verdict: MERGE**` or `**Verdict: MERGE AFTER FIX**` (`/review-pr` §4 fixes the form); `READY <sha7>` starts a comment's first line, for the head being merged. Like `merge_guard.py`, it guards against mistakes, not a forged review. Duplicate `### D-NNNN` IDs fail `tools/decision_ids.py` in CI's `site-literals` job.
- Alternatives: a login check; a verdict anywhere in any comment (an implementor's READY note "Verdict MERGE" would pass).
- Why: The only signal that separates the reviewer's comment from the implementor's on one account.
- Reversible: yes

### D-0879 — CSV formula injection in `csv_records` downloads
- Date: 2026-10-16 · Spec/PR: SPEC-08 §4.11, SPEC-10 follow-ups (#199) · Status: confirmed
- Decision: Open. Should `csv_records` neutralise cells starting with `=`, `+`, `-`, `@`, tab or CR (OWASP CSV Injection), now that the UI's Export CSV saves them as a file? Recommendation: (a). Blocks only the #115 follow-up.
- Alternatives: (a) an opt-in `csv_safe=true` results parameter that prefixes `'`, sent by the UI download (an API change); (b) always prefix (amends INV-27); (c) leave values unchanged and warn in the export UI.
- Why: INV-27: exporters serialize the published value unchanged, so either fix changes the API or the invariant (review of #115).
- Reversible: yes
- Owner answer: confirmed 2026-10-16, option (a): an opt-in `csv_safe=true` results parameter, sent by the UI's Export CSV; default output unchanged (INV-27). Implemented in #204 (D-0912).

### D-0906 — Stock analyser rules for ENGINEERING's patterns
- Date: 2026-10-16 · Spec/PR: follow-up (#202) · Status: decided
- Decision: Ruff `C420` (S7519) and `FAST` (S8409); Oxlint `no-nested-ternary` (S3358), `unicorn/catch-error-name` (S7718), `no-empty-function` (S1186), `react/no-array-index-key` (S6479). Not adopted: ruff `ARG` (S1172) and `RUF029` (S7503), Oxlint `no-await-in-loop` (S9382).
- Alternatives: Adopt those too, with suppressions.
- Why: The adopted rules flag only real cases; the others flag framework and protocol signatures and sequential loops, which ENGINEERING exempts (#192).
- Reversible: yes

### D-0914 — GeoNames re-pinned to the 2026-10-15 snapshot at this repo's release assets
- Date: 2026-10-16 · Spec/PR: owner answers (#204) · Status: superseded by D-0953
- Decision: The three GeoNames entries point at the release `data-geonames-2026-10-15` of this repo and pin the export dump of 2026-10-15; `retrieved` is 2026-10-16.
- Alternatives: Pin the 2026-10-13 snapshot named in D-0311.
- Why: Upstream rewrote two of the 2026-10-13 files (`cities15000.zip`, `countryInfo.txt`), so no copy of that snapshot was available to mirror.
- Reversible: yes — change the manifest entries.

### D-0915 — SimHash at Hamming 0 still misses some one-word edits
- Date: 2026-10-16 · Spec/PR: owner answers, D-0665 (#204) · Status: answered (owner delegation 2026-10-17, D-1340)
- Decision: Question: with `UNCHANGED_BITS = 0`, a one-word edit of a 500-word text leaves the SimHash unchanged on 10 of 100 fixed seeds (`test_simhash.py`), so on those pages a new price is skipped as `unchanged`, although ARCHITECTURE §14 now says a one-token change runs extraction. Options: (a) keep SimHash at Hamming 0 and amend §14's wording; (b) an exact hash (e.g. blake2b) of the visible text after nonce and whitespace stripping, which sees every edit; (c) both, SimHash kept for near-duplicate reporting only. Recommendation: (b). Blocked: nothing; recurring crawls run as built.
- Alternatives: See options.
- Why: SimHash flips a bit only where a vote total was near zero, so it is not a bound (D-0665's evidence); changing §14 is the owner's call. Copied to OPEN_QUESTIONS #30.
- Reversible: yes — one function and the stored fingerprint format.
- Owner answer: answered 2026-10-17 under owner delegation: option (c), the exact digest decides and SimHash reports (D-1340, owner decision #60, #252).

### D-0968 — `REBASE` only on a conflict
- Date: 2026-10-16 · Spec/PR: workflow (owner request, #212) · Status: decided · Supersedes D-0823's "behind `main`" trigger
- Decision: The orchestrator sends `REBASE`, and an implementor rebases, only when GitHub reports the PR `CONFLICTING` (`gh pr view <n> --json mergeable`; `UNKNOWN` is asked again). A branch only behind `main` merges as it is. Implementors branch from current `main` and check for a conflict with `git merge-tree --write-tree origin/main HEAD` before opening.
- Alternatives: keep rebasing when behind (the rulesets would then have to require up-to-date branches to make it mean anything).
- Why: The rulesets don't require an up-to-date branch (`strict` off), and every rebase reran the ~8.5-minute backend job; #197–#210 had 2–6 CI runs each.
- Reversible: yes — skills and `CLAUDE.md` §3.

### D-0969 — The tracker commit is in the PR from its opening
- Date: 2026-10-16 · Spec/PR: workflow (owner request, #212) · Status: decided
- Decision: The implementor's tracker commit (`ACTIVE.md` rows `done (#n)`, follow-ups, decisions-log entries) is the last commit before `gh pr create`; `#n` is the next issue number (`gh api .../issues?state=all&per_page=1`), amended at once if GitHub hands out another. The reviewer reviews the tracker lines. After the verdict the implementor pushes only the Act-on fixes, in one push, adjusting tracker lines in that push; with `MERGE` nothing is pushed and `READY` names the green head. The PR body's `## Decisions` lists the logged IDs instead of repeating the entries.
- Alternatives: open the PR, then push the tracker commit with the real number (one more CI run); a tracker commit after review (the old flow: one docs-only push, yet the `changes` filter diffs the whole PR, so backend reran).
- Why: Removes one full CI run per PR and puts the tracker lines under review.
- Reversible: yes.

### D-0970 — CI runs pytest on 4 xdist workers, each with its own databases
- Date: 2026-10-16 · Spec/PR: workflow (owner request, #212) · Status: decided
- Decision: `pytest-xdist` (MIT) in the dev group; the backend job runs `pytest -n 4 --durations=20` (`PYTEST_WORKERS`, one per vCPU of the 4-vCPU runner). `tests/db/conftest.py` suffixes both test database names with `PYTEST_XDIST_WORKER` (`crawlerai_gw0`, ...); CI creates them owned by `app` after its migration round trip, the main ones as copies of the migrated `crawlerai` (`TEMPLATE`), so the workers' upgrade to head is a no-op. A serial `uv run pytest` uses the names as given; `-n` is not in `addopts`.
- Alternatives: `-n auto` (same count on this runner, less explicit for the DB step); let the fixture create the databases (`app` has no `CREATEDB`, and an admin URL would be a new variable); empty worker databases each migrated by its worker (8 upgrades per run).
- Why: pytest was 411 s of the ~8.5-minute job (3,838 tests, serial) on every push.
- Reversible: yes — drop `-n`.

### D-0971 — One shared local test Postgres
- Date: 2026-10-16 · Spec/PR: workflow (owner request, #212) · Status: decided · Replaces the per-worktree throwaway container
- Decision: `tools/orchestrator/test_db.sh up|drop [NAME]` keeps one container, `crawlerai-test-pg` (postgres:16, `127.0.0.1:55432`, the roles of `infra/postgres/init.sql`), and gives each worktree `crawlerai_test_<name>` and `..._private`, recreated empty on `up`; `cleanup_worktree.sh` drops them. Local runs are one changed test file at a time, never `pytest -n`, vitest with one worker.
- Alternatives: keep a container per worktree (one Postgres start and ~100 MB per agent); share the dev compose database (its data must survive).
- Why: Owner request: agents started a container each, and local runs competed for memory with up to four workers.
- Reversible: yes.

### D-1006 — A batch binds role C, bounded by an optional `budget`
- Date: 2026-10-16 · Spec/PR: UAT fixes, SPEC-10 §4.3 (#215) · Status: decided · Supersedes the batch parts of D-0631, D-0635 and D-0714
- Decision: The worker's `batch_scrape` handler binds role C on the worker's client, as `extract` and `crawl` do (`worker.handlers.table.task_handlers`). `BatchScrapeRequest` takes the optional `budget` SPEC-10 §4.3 lists; without one the job's `llm_calls` are not bounded, as a crawl's are not.
- Alternatives: keep batch without role C (UAT: a batch's records lacked the title, price and description a scrape of the same URLs filled); default the budget to a scrape's 10 calls (a 1,000-URL batch would fill 10 pages).
- Why: SPEC-10 §4.3 says the handler is SPEC-07's scrape function, and ARCHITECTURE §8.4 makes role C the cold-mode path for every caller-supplied page.
- Reversible: yes

### D-1007 — A later extraction that misses a field is a new record version
- Date: 2026-10-16 · Spec/PR: UAT fixes (#215) · Status: decided
- Decision: No change. A record version is what one extraction published; a field the new extraction did not publish is absent from it and listed in `changed_fields`, and no value is carried over from an earlier version.
- Alternatives: carry the prior version's value forward (publishes a value this capture does not show, against §8.4 grounding and INV-27's "no layer after resolution changes a published value"); skip a version that only loses fields (hides a real removal).
- Why: SPEC-11 §4.4 lists "fields that became published or abstained" in `changed_fields`. The UAT case (price lost in version 3) was a batch extracted without role C, fixed by D-1006.
- Reversible: yes

### D-1008 — LLM output schemas stay within a provider's compiled-grammar cap
- Date: 2026-10-16 · Spec/PR: UAT fixes, SPEC-06 §4.2, SPEC-08 §4.6 (#215) · Status: decided
- Decision: Role A replies `{fields: [{field, steps}]}`, `field` an enum of the asked names, so the step form appears once in the schema; a field without an entry has `no_steps`, one named twice gets both entries' steps. Role C keeps its closed object of one required claim per field, each a `$ref` to one claim form in `$defs`. SPEC-08 §4.6 is edited to match.
- Alternatives: split the fields across several calls (more calls and budget per page or round); `$ref` for role A's steps too (refused as "Schema is too complex" at 50 fields).
- Why: Anthropic refused role A on the 20-field `commerce_detail` preset, and role C from 18 fields on, with HTTP 400 "The compiled grammar is too large" (probe against the API, 2026-10-16); both new forms were accepted with 50 fields, and stay inside both providers' subsets (`llm.schema_subset`).
- Reversible: yes

### D-1009 — A provider's refusal of a request is labelled `llm_unavailable`
- Date: 2026-10-16 · Spec/PR: UAT fixes (#215) · Status: confirmed 2026-10-16, option (a) (D-1056)
- Question: SPEC-06 §4.2 and §4.7 (D-0748) give `ProviderRefused` (any non-transient HTTP error, such as a 400 for a schema the provider will not compile) the reason and problem type `llm_unavailable`, the same as "no provider answered". UAT read a learn job's `llm_unavailable` as an outage when the request itself was refused. Relabelling changes a field reason and a public problem type.
- Options: (a) a new code `llm_refused` (field reason, task `last_error`, problem 502) for `ProviderRefused`; (b) keep `llm_unavailable` and add the refusal's cause to the learn job's end event (the role C diagnostic already carries it); (c) leave as is.
- Recommendation: (a): a refusal is the request's fault, and operators act on it differently from an outage.
- Blocked: nothing; the grammar refusal itself is fixed by D-1008.
- Reversible: yes

### D-1010 — A run without a schema shows and exports its page outputs
- Date: 2026-10-16 · Spec/PR: UAT fixes, SPEC-14 §4.3 (#215) · Status: decided
- Decision: The playground reads whether a job has records from its stored request (`formats` without `records`). For a job without, the results table stays on `json_values` (URL, outcome), its drawer shows the page's outputs from `format=json` at the same cursor, Export JSON saves every page output, and Export CSV is disabled. The API is unchanged: `format=json` already returns page outputs and `csv_records` answers 409 for such a job, as its docs say.
- Alternatives: add page formats to `json_values` items (`include=markdown`; an API shape beyond SPEC-14 §4.4).
- Why: UAT found a markdown batch's and crawl's results unviewable in the UI (`records: []`).
- Reversible: yes

### D-1011 — UAT findings that are by design
- Date: 2026-10-16 · Spec/PR: UAT fixes (#215) · Status: decided
- Decision: No code change for: a markdown-only crawl making no LLM calls (no schema, nothing to extract); brand published from the page's JSON-LD `brand.name`, which states the site's name (extract, never enrich: Appendix A #43); price not taken from an `AggregateOffer`'s `lowPrice` (§10) and left to role C, which that run could not call (no provider key then); `rating` a decimal string as written (SPEC-04 §4.4 number, like money amounts); a `shell` page escalated to the browser in auto mode but kept from HTTP because the browser's result was a shell too (SPEC-02 §4.4, ARCHITECTURE §7.1).
- Why: Each follows the cited rule; the captures and their manifests show it.
- Reversible: yes

### D-1056 — Owner answer to D-1009: a provider refusal is `llm_refused`
- Date: 2026-10-16 · Spec/PR: SPEC-06 §4.2, §4.7; SPEC-07 §4.3 (#216) · Status: confirmed
- Decision: `ProviderRefused` has its own code `llm_refused`: the field reason, the task's `last_error` and the problem type (502 "LLM refused the request"). It subclasses `LLMFailure` directly, no longer `ProviderUnavailable`; nothing caught it as the latter. The OpenAPI document is unchanged (502 was already declared, problem types are strings); the UI shows the problem's title and raw reasons, so it needs no label map.
- Alternatives: (b) keep `llm_unavailable` and add the cause to the learn job's end event; (c) leave as is.
- Why: owner, 2026-10-16, deferring to the recommendation: a refusal is the request's fault (Appendix A #44; OPEN_QUESTIONS #31).
- Reversible: yes

### D-1021 — Role C gives the page text first and the fields asked after it
- Date: 2026-10-16 · Spec/PR: reference eval round 2, SPEC-06 §4.4 (#217) · Status: decided
- Decision: Role C's user message is the URL line, the page text, then the fields asked (a listing: row fields, then page fields). The wire form (D-0765, D-1008) is unchanged. SPEC-06 §4.4 states the order. Roles A, D and S keep theirs.
- Alternatives: a list of claims naming only the fields found (also answered with the old order in most probes, but reopens D-0765's bound); fewer fields per call (more calls per page); default effort (did not help: 1 of 3 probes answered).
- Why: Round 2 found role C answering every field empty on pages that show some (15 fields asked since #208 grew the preset). Live probes with `claude-haiku-5-5` on the same captured page, 15 fields: old order 1 of 7 replies with a value (`$defs` form) and 0 of 2 (claim written under each field); new order 6 of 6 and 5 of 5, and the branch's code 8 of 8. Another page's brand: 0 of 3 before, 3 of 3 after. So the `$defs` form of #215 was not the cause. Anthropic's long-context guidance puts long documents first and the query last.
- Reversible: yes

### D-1022 — An http(s) URL with an empty authority is declined
- Date: 2026-10-16 · Spec/PR: reference eval round 2, SPEC-04 §4.4 (#217) · Status: decided
- Decision: `https:////host/path` stays `Invalid("no_host")`; the rule and its standard are stated in `normalize/url.py` and SPEC-04 §4.4, and tested.
- Alternatives: the WHATWG parser's slash skipping (`https://host/path`), which also turns `https:///path` into host `path`.
- Why: RFC 3986 §3.2 reads the authority as empty and RFC 9110 §4.2.1 has a recipient reject an http(s) URI with an empty host; the next segment is the host only when the slashes were a mistake, which the URL does not say (C7). Precision first.
- Reversible: yes

### D-1023 — The main image is not taken from a dialog or from what the page does not show
- Date: 2026-10-16 · Spec/PR: reference eval round 2, SPEC-05 §4.5 (#217) · Status: decided
- Decision: The DOM collector's main image skips images inside a dialog (`dialog`, roles `dialog` and `alertdialog`) as it skips tangential content, and images the cleaned text's rules do not show (hidden subtrees, `aria-hidden`, `display: none`, inherited `visibility`), through one `content.text.shown`.
- Alternatives: rank `dom` images below `og` only (keeps the badge whenever `og:image` declines); a size or file-name test (a list, C4).
- Why: Round 2 published a certification badge from an off-canvas drawer (`role="dialog"`, `aria-hidden="true"`) inside `main` while `og:image` declined; the text already treated that drawer as not shown. HTML Standard §4.11.4 and WAI-ARIA 1.2 §5.4 define a dialog as a window apart from the page.
- Reversible: yes

### D-1024 — Listing rows without structured data take no item URL
- Date: 2026-10-16 · Spec/PR: reference eval round 2 (#217) · Status: confirmed (owner 2026-10-16: option (a); D-1122)
- Question: Role C reads the cleaned text, which holds no link targets, so its listing rows carry no `url`: in round 2, 13 of the 15 listing pages with rows had no row URL (the 2 with URLs came from JSON-LD `ItemList`). The repeated item blocks `acquire.items` finds (#213, D-0993) hold each item's own link. Taking a row's URL from them is extraction from repeated structure, which ARCHITECTURE §22 lists as not admitted (C13), and §8.6 names only structured data and role C as row sources.
- Options: (a) admit repeated structure for row URLs only: a role C row whose grounded title is the visible text of exactly one repeated item block takes that block's link (its own target, HTML Standard §4.6) as a `dom` candidate; (b) give role C the link targets (anchors marked in its input text) and ground a URL claim against the page's links (changes SPEC-05 §4.4's cleaned text); (c) leave rows without URLs until labels measure it.
- Recommendation: (a): it uses the structure the engine already finds for map and crawl, publishes only a link the page attaches to that item, and declines when the title matches no block or several.
- Blocked: listing row URLs on pages without structured data; nothing else.
- Reversible: yes

### D-1096 — The main image is not a decorative, fallback or link-card image
- Date: 2026-10-16 · Spec/PR: reference eval round 3, SPEC-05 §4.5 (#220) · Status: decided
- Decision: The DOM collector's main image also skips decorative images (empty `alt`, HTML Standard §4.8.4.4; roles `none`/`presentation`, WAI-ARIA 1.2), a media element's fallback content (`video`, `audio`, `object`, `canvas`, §4.8), and link-card images: the nearest block around the image holding a hyperlink holds no other image, and its hyperlinks lead to exactly one other web document (`canonical_url`, not this page, not an `image/*` resource by the stdlib's built-in extension map).
- Alternatives: skip images inside form controls and option pickers (`label`, `fieldset`, ARIA `radio`/`option`/`listbox`): the round-3 image was not in one (it was a comparison card linking to another collection), and two eval pages' correct images sit in gallery `button`s; skip any image near any link (drops single-image pages whose region holds breadcrumbs).
- Why: Round 3 published a comparison card's image; with these rules that page gets no DOM image (its og:image is malformed, D-1022), one page's DOM candidate moves from an `alt=""` banner to the image its JSON-LD names, a job page's logo (in a link to the employer) is dropped from a schema without an image field, and 20 of 25 captured detail pages are unchanged.
- Reversible: yes

### D-1097 — Role C claims say whether the page shows each field
- Date: 2026-10-16 · Spec/PR: reference eval round 3, SPEC-06 §4.4 (#220) · Status: decided
- Decision: The claim form is `{shown: bool, value, start, end}`, `shown` first; the prompt has the model decide `shown` field by field. A claim gives a candidate only when `shown` is true and the value is not empty. Effort stays `low`.
- Alternatives: `medium` effort (same 68 values, 3x output tokens, max 3545 of the 4096 cap); a nullable value (a union, outside both providers' subsets); unchanged.
- Why: The empty span was every field's easiest valid claim. Live probes, `claude-haiku-5-5`, six eval pages' recorded gap requests (5 to 17 fields), 3 runs each: grounded values 55 (old) vs 68 (flag); pages whose count varied across runs 5 vs 1; mean output tokens 687 vs 718. The shipped prompt measured 67, 2 pages varying, 645 tokens. A 55-field request is accepted (D-1008). No all-empty reply in 72 calls, so the round-3 all-empty page is not reproduced from its captures.
- Reversible: yes

### D-1121 — No LLM call cap by default; a project-level cap for requests without a budget
- Date: 2026-10-16 · Spec/PR: owner answers (#224) · Status: decided
- Context: Owner: "there is no cap, but we can put a setting in settings to allow the user to put a cap". Scrape and extract defaulted `budget.llm_calls` to 10; batch and crawl had none (D-1006, D-1044).
- Decision: No request kind has a default budget (`budget` is optional; `budget.llm_calls` is required inside it). `project.llm_call_cap` (nullable, baseline migration) bounds every job whose request sets no `budget.llm_calls`, crawl included; `db.usage.budget_remaining` reads it when the job checks, so a change applies to running jobs. `GET/PATCH /v1/project/settings`; Settings shows "LLM call limit per run"; the playground's empty limit means the project setting.
- Alternatives: copy the cap into `job.request` at submission (a snapshot per job; four call sites and the recurring and learning jobs).
- Why: One place covers every job kind; the job's own budget still wins.
- Reversible: yes

### D-1122 — A role C listing row takes the item URL of its one repeated item block
- Date: 2026-10-16 · Spec/PR: ARCHITECTURE §8.6, D-1024 option (a) (#224) · Status: decided
- Decision: `collect.item_links.row_links`: a role C row whose grounded text values (its `text` fields' spans, white space dropped) all lie in exactly one block of `acquire.items.item_blocks`, a block no other row is in, takes that block's link as a `dom` candidate for each row field of type `url` whose `schema_org` path is `<Type>.url`, when the block's hyperlinks lead to exactly one document other than the page (`canonical_url`). Otherwise no candidate.
- Alternatives: the title field only (needs a list of title properties, `name`/`title`); the block's first link (a brand or review link in a card would win).
- Why: The owner's option (a), read conservatively: every value role C grounded must sit in the block, and a card linking to two documents says nothing about which is the item's.
- Reversible: yes

### D-1136 — Documentation in the OpenSpec layout
- Date: 2026-10-16 · Change/PR: OpenSpec conversion (#223) · Status: decided (owner asked for the layout, 2026-10-16)
- Decision: `openspec/` holds `project.md` (context, contract C1–C13 verbatim), `specs/<capability>/spec.md` (14 capabilities, ≤ 100 lines each, current behaviour as requirements; INV-NN kept in their requirements), `changes/` (in-flight work; `archive/` holds SPEC-00…SPEC-15 as-is with their logs), `design/` (`overview.md`: goals, contract evidence, milestone M, candidates register; `owner-decisions.md`: Appendix A, live); ARCHITECTURE.md and INVARIANTS.md frozen verbatim in `changes/archive/2026-10-16-architecture-rev26/`, `decisions/`, `conventions/` (ENGINEERING, DESIGN, RECURRING), `backlog.md` (was ACTIVE.md) and `OPEN_QUESTIONS.md`. `CLAUDE.md` stays the agent entry point.
- Alternatives: keep ARCHITECTURE.md live (over 1000 lines, duplicating the specs); split it into design files (first draft of #223: grew the docs to ~5,000 lines, owner pushback); move project.md's role into CLAUDE.md; rewrite code comments that cite `ARCHITECTURE §N`, `SPEC-NN §x` (about 800 files).
- Why: an agent reads by default only CLAUDE.md, project.md, the capability specs it touches and its change folder; code citations (`ARCHITECTURE §N`, `SPEC-NN §x`, `INV-NN`) keep resolving in the archive, so no code changes; nothing is held twice as live text.
- Reversible: yes — a docs move.

### D-1137 — SPEC-03 and SPEC-15 archived; row 7 becomes a change
- Date: 2026-10-16 · Change/PR: OpenSpec conversion (#223) · Status: decided
- Decision: SPEC-15 (all rows done) and SPEC-03 (rows 1–6, 8–12 done) are archived; SPEC-03 row 7 and human tasks H1, H2, H3, H6 become `openspec/changes/wire-protected-eval-job/` with a MODIFIED delta of the evaluation requirement INV-19; H4, H5, H7, H8 and the follow-ups go to `backlog.md`.
- Alternatives: keep SPEC-03 active until row 7 lands (it waits on milestone M tasks).
- Why: the archive is history; the one open row is the only in-flight work, and OpenSpec models it as a change.
- Reversible: yes

### D-1138 — Where decisions live after the conversion
- Date: 2026-10-16 · Change/PR: OpenSpec conversion (#223) · Status: decided
- Decision: a change's decisions go in its `design.md` under `## Decisions` and move with it on archive; cross-cutting ones, those of PRs without a change and every `needs-owner` entry go in `openspec/decisions/log.md`; the open owner items index moves to `project.md`. `tools/decision_ids.py` checks every `### D-NNNN` heading under `openspec/`.
- Alternatives: one central log for everything (the old model); per-capability logs.
- Why: OpenSpec keeps a change's rationale with the change; one ID sequence and one duplicate check stay.
- Reversible: yes

### D-1139 — The site-literal scan exempts openspec/
- Date: 2026-10-16 · Change/PR: OpenSpec conversion (#223) · Status: decided
- Decision: `openspec/` joins `docs/` in `EXEMPT_DIRS` of `tools/site_literal_scan.py`; the protected hidden-host scan still covers it.
- Alternatives: scan the docs (archived logs and the adapter capability name platforms and real hosts).
- Why: same reason as D-0004; the documentation moved.
- Reversible: yes

### D-1140 — Branches, tracker commit and archiving under OpenSpec
- Date: 2026-10-16 · Change/PR: OpenSpec conversion (#223) · Status: decided
- Decision: a PR implements a batch of tasks of one change on branch `change/<change-id>` (worktree `<change-id>`); new work starts by writing the change folder as the PR's first commit; the tracker commit checks the tasks `(#n)`, updates `backlog.md`, logs decisions and, when the change's last task is done, applies the deltas to `openspec/specs/` and moves the folder to `changes/archive/<date>-<change-id>/`. A fix that restores stated behaviour needs no change folder.
- Alternatives: archive in a separate follow-up PR (an extra docs-only CI run per change).
- Why: one PR per batch stays the rule (CLAUDE.md §3); the reviewer checks the delta application with the code.
- Reversible: yes

### D-1141 — One normalization capability, not one per field type
- Date: 2026-10-16 · Change/PR: OpenSpec conversion (#223) · Status: decided
- Decision: `openspec/specs/normalization/spec.md` holds one requirement group per field type; C8's one module per type stays a code rule (INV-08).
- Alternatives: `normalization-money/`, `normalization-enum/` … (11 folders of 20–40 lines).
- Why: the shared contract (Ok/Ambiguous/Invalid, context, no defaults) is stated once, and the file stays within the 100-line cap per capability spec (owner, 2026-10-16); per-type detail is in `normalize/<type>.py` and its property tests.
- Reversible: yes

### D-1151 — A detail page's related items and its product's group do not make its intent ambiguous
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-05 §4.6 (#225) · Status: decided
- Decision: `resolve.intent`: when the page URLs settle no single candidate, the page's own candidates are those that are not another page's item: not one whose every URL names another document (scheme, host and path, RFC 3986 §3; the query is left out, as it may select a variant of the same page), and not one of three or more microdata items whose element paths differ only in positions (sibling elements of one shape: a carousel, a comparison table). One own candidate is the target; of several, the one naming a page URL; of several of those, the one product group with variants (`hasVariant`). The group a product `isVariantOf` is not a candidate. Otherwise the page stays ambiguous.
- Alternatives: count any entity nested in a primary entity out (breaks the tested rule that only lists and relation properties exclude); compare full URLs for "another document" (a variant URL with another query order would count as elsewhere).
- Why: 7 of 41 tough-run detail pages published nothing (every field `intent_ambiguous`); replayed, all 7 now have a target, 32 of their 35 core fields publish, and no other page's target changes.
- Reversible: yes

### D-1152 — Bodies are decoded by HTML encoding sniffing; a browser body is UTF-8
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-05 §4.1 (#225) · Status: decided
- Decision: `decode_body` takes a byte order mark, else the Content-Type charset, else a `meta` declaration in the first 1024 bytes, else UTF-8 (HTML Standard §13.2.3.2), with labels resolved by the Encoding Standard (`iso-8859-1` is windows-1252) through `webencodings` (BSD-3-Clause). A browser capture's body is the rendered DOM the fetcher serializes as UTF-8, so it is decoded as UTF-8 whatever the server declared.
- Alternatives: keep the header-only decode (a browser capture of a page declared windows-1252 turns every non-ASCII character into mojibake); a hand-written label table (a list to keep, C4).
- Why: the reported mojibake class. It is not reproduced in the stored captures: all 336 bodies of the reference runs are UTF-8 and declared so.
- Reversible: yes

### D-1153 — A URL a source gives as a property value is not text
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-05 §4.5 (#225) · Status: decided
- Decision: A microdata value read from a URL attribute (`a`, `area`, `link` href, `img` src, ..., HTML Standard microdata "Values") or an RDFa IRI attribute is marked `url`; a `text` or `long_text` field takes no candidate from it. Enum and URL fields still do (`<link itemprop="availability" href=...>`).
- Alternatives: the element's text in place of its URL (not the property's value by the standard); a text normalizer that declines URL-looking strings (a guess).
- Why: one tough-run listing published a relative path as the title of all 117 rows (`itemprop="name"` on a hyperlink).
- Reversible: yes

### D-1154 — Elided text shows the full title its element's `title` attribute gives
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-05 §4.4 (#225) · Status: decided
- Decision: In the cleaned text, an element whose text ends in an ellipsis (U+2026 or three full stops, its NFKC form) and whose `title` starts with that text without the ellipsis and goes on, shows its `title` (HTML Standard §3.2.6.1: advisory information for the element). Role C then reads and grounds the full name.
- Alternatives: replace the value after grounding (the value would not be a span of the text, INV-12).
- Why: two tough-run listings published half their row titles cut short with an ellipsis; their captures now read the full names.
- Reversible: yes

### D-1155 — A robots.txt answered with 429 is unreachable
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-02 §4.6 (#225) · Status: decided
- Decision: `robots.snapshot_of` treats 429 like a 5xx (unreachable: allows nothing, retried); other 4xx stay unavailable (allows everything, RFC 9309 §2.3.1.3).
- Why: 429 asks for fewer requests (RFC 6585 §4); it does not say the file is unavailable. A 403 robots.txt already allowed everything; the tough-run pages "blocked by robots" were real disallows (re-checked: 6 of 7 hosts answer 200 with a disallow).
- Reversible: yes

### D-1156 — A page an adapter serves is not held back by its own robots.txt
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-15 §4.6 (#225) · Status: decided
- Decision: When `Registry.would_serve(url)`, a page robots.txt disallows is still handed to `acquire`: the adapter requests its API under that host's robots.txt (`adapter_send`), and the page rungs are not admitted (`politeness.refuse`); an adapter answer that is not `ok` ends as `robots`. Same in `services.scrape.polite_fetch` and `worker.polite.fetch_politely`.
- Why: robots.txt governs the URLs a crawler requests (RFC 9309 §2.2); an adapter never requests the page. 4 tough-run job board embed URLs are disallowed by their host's robots.txt and served by the Greenhouse adapter's API, which its host allows.
- Reversible: yes

### D-1157 — A served page that links nowhere is blocked
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-02 §4.3 (#225) · Status: decided · Supersedes the terminal-document rule (small, no page parts)
- Decision: A 2xx HTML page that is not a shell and has no hyperlink (`a`/`area` with `href`, HTML Standard §4.6) is `blocked`, whatever scripts, images or forms it holds.
- Alternatives: compare with a 403 body of the same host (no such body is stored; the bot pages came with 200); text phrases (C4).
- Why: two tough-run browser captures were a bot page (18 KB, scripts, a form, no link) classed `ok` and extracted empty. Of the 336 stored 2xx captures classed `ok`, those two are the only ones without a hyperlink.
- Reversible: yes

### D-1158 — A listing whose structured data lists no items is a shell
- Date: 2026-10-16 · Spec/PR: tough-site run, SPEC-02 §4.3, D-0933 (#225) · Status: decided
- Decision: The HTTP listing-shell rule's "structured data" is now data that lists items: a JSON-LD node typed ItemList (any depth), or at least `MIN_ITEMS` microdata items. Other JSON-LD (WebSite, Organization, BreadcrumbList) and JSON script state no longer exempt a listing without repeated items from the browser.
- Alternatives: keep JSON script state as rows (it exempted 4 tough-run listings that had none; the browser renders the grid from it when it has them).
- Why: 8 tough-run listings with no rows at HTTP were `ok` because of such data; replayed, all 8 are now `shell` (browser retry). One of them had 58 role C rows at HTTP: if its browser retry fails, the HTTP shell is kept and those rows are lost (follow-up).
- Reversible: yes

### D-1176 — Adapter shapes see the page's match; a property may read several members and a root prefix
- Date: 2026-10-16 · Change/PR: ats-adapters (#226) · Status: decided
- Decision: `Adapter.shapes` takes the `AdapterMatch` (not only the page kind). `Shape.also` names further members a property reads after its own, in order; `Shape.prefixes` puts a text before each string value of a property. The adapter collector applies both; locators stay the JSON paths.
- Alternatives: rewrite the answer body in `fetch` (the capture would no longer be the platform's answer, breaking replay); resolve `externalPath` against the endpoint URL (RFC 3986 drops the site segment for an absolute path).
- Why: Workday states a listed job's path relative to its career site and Oracle a requisition's id only; both keep a primary location apart from the others.
- Reversible: yes

### D-1177 — Workday through its career sites' CXS endpoints
- Date: 2026-10-16 · Change/PR: ats-adapters (#226) · Status: decided
- Decision: Workday has no public documentation for these endpoints; the adapter calls exactly what the career site's page calls, unauthenticated: `POST /wday/cxs/{tenant}/{site}/jobs` with the page's own first-page body (20 rows) and `GET .../job/{location}/{slug}`. The match's tenant is the site's root without the locale (what `externalUrl` starts with); the locale goes in `Accept-Language`. `startDate` maps to `datePosted` (the job page's JSON-LD states the same value). A list row's `locationsText` is kept as written, including "N Locations" (owner: location text as written; telling a count from a place would need a phrase list, C4).
- Why: the list page is rendered in the browser; its HTTP fetch is a shell with no rows.
- Reversible: yes

### D-1178 — Oracle Recruiting Cloud through the Candidate Experience REST resources
- Date: 2026-10-16 · Change/PR: ats-adapters (#226) · Status: decided
- Decision: The site segment goes into the finder as written (site numbers and site codes both answer); first page of 25 with `expand=requisitionList`; the job's URL is the site URL + `/job/{Id}`. `ExternalDescriptionStr` is the description (responsibilities and qualifications stay out); `LegalEmployer`, when stated, is the hiring organization. An `ok` answer with no items is `not_served`, so the page falls back.
- Why: the resources are documented (REST API for Oracle Fusion Cloud HCM) and are what the site's page calls.
- Reversible: yes

### D-1179 — No iCIMS adapter
- Date: 2026-10-16 · Change/PR: ats-adapters (#226) · Status: decided
- Decision: iCIMS gets no adapter. Its career portals are server-rendered HTML and call no public JSON; the vendor's REST API needs customer OAuth credentials, which adapters never use.
- Why: an adapter reads a platform's public, unauthenticated JSON; the page path already reads the portals' HTML.
- Reversible: yes

### D-1208 — The `claude-review` CI workflow is the review, only for PRs over 10 files
- Date: 2026-10-17 · Change/PR: owner request (#236) · Status: decided
- Decision: The `/review-pr` reviewer agent is removed. A PR that changes more than 10 files gets one review, the `claude-review` workflow (Anthropic's code-review plugin, Sonnet 5.5 at high effort), started by the implementor commenting `/claude-review`; the implementor fixes or answers each inline finding in one push, then `READY`. A PR of 10 files or fewer merges on green CI and `READY`. `merge_pr.sh` checks it: over 10 files it needs the plugin's `## Code review` comment or an inline comment by `claude[bot]`; the managed Code Review's notices from the same app don't count. No `/simplify`, no re-review.
- Alternatives: keep `/review-pr` for every PR (an agent and about 50k tokens even for one-line PRs); review every PR in CI (the same cost on PRs the plugin's own pre-check calls trivial).
- Why: owner, 2026-10-17. The plugin found the planted bug in a test PR (#231) and reviews a 54-file diff for about $0.30-0.65.
- Reversible: yes

### D-1245 — A listing without rows at HTTP whose body holds other repeated blocks is not rendered
- Date: 2026-10-17 · Spec/PR: site-test-40-fixes (#240) · Status: needs-owner
- Question: the HTTP listing-shell rule (D-0933, D-1158) sends a listing to the browser only when its HTTP body shows
  no repeated items and no structured data that lists items. In the 40-page site test, two client-rendered listings
  hold other repeated linked blocks in their HTTP body (related posts, search filters). They stay `ok` at HTTP, role
  C reads 0 rows, and no browser render follows: the grid is only a client template there. The tough-site run saw
  about 7 such pages (#225 follow-up). Rendering on the extraction result is an acquisition rule like owner #49
  (detail pages only), so it needs the owner (#53).
- Options: (a) in `auto`, a listing whose HTTP capture gives no rows after extraction gets one browser render, and the
  capture with more rows is kept, as owner #49 does for detail pages without offer data; (b) a structural test of
  the item blocks at classification (unexpanded template placeholders, items inside forms), each needing its own
  standard; (c) leave it.
- Recommendation: (a). The evidence is the extraction result, not a page string, and it costs one render and one more
  role C call, only on listings that gave nothing.
- Blocked: rows on client-rendered listings whose HTTP body holds other repeated blocks; nothing else.
- Reversible: yes
- Owner answer: confirmed 2026-10-17, option (a) (owner decision #54). Implemented in #242 (D-1246–D-1249).

### D-1580 — A page's language subtags that CLDR does not know are dropped before the count unit-label lookup
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `normalize.count._names_a_measure` intersects `vocab.context_languages(ctx)` with the primary language
  subtags CLDR has locale data for (`_cldr_languages`, from `babel.localedata.locale_identifiers`) before calling the
  cached `_measure_labels`. So the cache keys only on languages CLDR knows. A page whose only stated subtags are
  unknown now reads like a page that states no language, which means every locale's unit labels. Before, it meant no
  labels, so a `unitText` such as "kg" beside `C62` was accepted.
- Alternatives: an `lru_cache(maxsize=...)` bound (it still stores a full label set per garbage combination, up to
  the bound); keep the empty label set for unknown-only tags through a sentinel key (two meanings for "no usable
  language").
- Why: review finding on #245. Garbage subtags beside a real one each stored a fresh copy of the whole CLDR label set,
  so the cache grew without bound over a long crawl. An unknown subtag gives no CLDR data either way, so the
  conservative reading is "no language stated", the rule that already applies (D-1271).
- Reversible: yes

### D-1581 — The SearXNG provider reads results by SearXNG's documented JSON members
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `SearxngProvider` passes `SEARXNG_FIELDS = {"url": "url", "title": "title", "snippet": "content"}` to
  `search.results.parse`, the members of SearXNG's documented Search API JSON response (`format=json`). The template
  provider is still read by the answer's shape (D-1443), with the operator's `CRAWLERAI_SEARCH_FIELDS` when given.
- Alternatives: keep reading SearXNG by shape (an empty `content` takes `template`, "default.html", or `engine` as
  the snippet; a member order with `engine` before `title` gives every title wrong).
- Why: review finding on #261. The provider is named in configuration and its response schema is documented, so this
  is no site rule (C3): it is the same field mapping the operator can already state for a template provider.
- Reversible: yes — a constant.

### D-1582 — Role S drafts get the schema.org reference check user schemas get, in the reply check
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `collect.schema_org_map.pinned_reference_errors(fields)` runs `reference_errors` against
  `default_vocabulary()`. It returns `[]` on `VocabularyMissing`, so a process without the file checks syntax only.
  `services.schemas._check_references` (user create and inline schemas) and role S's reply check
  (`llm.roles.s_schema._parsed`) both call it. A draft that names an unknown schema.org type, property or enumeration
  therefore takes the client's one retry, then `OutputInvalid`, and is never stored.
- Alternatives: check after the reply in `_drafted` and raise (no retry for the model to correct it); a second copy of
  the try/except in role S (C8).
- Why: review finding on #255. Role S stored drafts through `registry.create` directly, past the check SPEC-04 §4.2
  states for every schema document.
- Reversible: yes

### D-1583 — long_text word overlap drops numbers, so texts that differ only in a figure match
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277), owner-items · Status: decided (owner 2026-10-18)
- Decision: option (a), implemented in `normalize.text._words`; `word_overlap` counts runs of letters, marks and numbers; `vocab.tokens` is unchanged.
- Question: `normalize.text.word_overlap`, which scores long_text in the evaluation (D-1462, threshold 0.9), builds
  its words with `vocab.tokens`, which keeps letters and marks only. Two descriptions that differ only in a number
  ("lasts 10 hours" / "lasts 20 hours") score 1.0, so a wrong value counts as TP (review finding on #264).
- Options: (a) count runs of letters, marks and numbers as words (UAX #29 WB9/WB10) in `word_overlap` only, keeping
  `vocab.tokens` for vocabulary matching; (b) leave it.
- Recommendation: (a). It can only lower long_text TP counts where output and label state other figures.
- Blocked: nothing; it changes what counts as a long_text match, a scoring rule (`CLAUDE.md` §4), so it waited for the
  owner, who approved (a) on 2026-10-18.
- Reversible: yes

### D-1584 — A database error during recipe learning fails the learn run
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `config_ir.learning._learned` re-raises `sqlalchemy.exc.SQLAlchemyError` from `learn_recipe` (beside `LLMFailure`), so the run ends failed (`error`) and no config activates; every other exception is still a refused recipe (`recipe_error: <type>`, D-1389). The adapters spec's held-out validation requirement says so.
- Alternatives: a dedicated `UsageNotRecorded` exception raised by `services.fetching.learning_replay` around its usage write (needs an edit in a file PR #273 rewrites, and catches only that one write, not the replay's other database reads).
- Why: a database error is never the recipe's own; letting it through keeps a replay whose usage was not stored from leaving the request unaccounted (D-1381) while the job reports completion.
- Reversible: yes

### D-1585 — A job's records page places a record at the task whose link came first
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `services.records._job_page` places each record at the job's task whose `task_record` link has the smallest (`created_at`, `url_task_id`), not the smallest task id. The cursor stays a record id (no API change).
- Alternatives: encode the position (task id, record id) in the cursor (an API shape change); stamp `task_record.created_at` at commit with a trigger as `record` is (a baseline-migration edit in a file PR #273 rewrites).
- Why: links only accrue, so an older task that comes to stand for a record later no longer moves it under a cursor already given and skips the records between. Residual: `created_at` is the transaction's start (`now()`), so two task transactions that overlap and link the same record can still order by start rather than commit; the window is one task transaction.
- Reversible: yes

### D-1586 — The listing diff reads row URLs with the schema the job pinned
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `recurring.listing_diff` reads the row URL fields from `job.pinned["schema"]` (INV-28, `JobPins`), not the live schema by id, and filters records that publish none of them (SQL NULL) before canonicalizing. A job without pins (no records) lists no row URLs. It reads only the `schema` member, as `recurring` sits below `services` and cannot import `JobPins`.
- Alternatives: keep the live schema and only filter NULLs (an edit mid-crawl still changes which fields are read: false misses and `url_gone`).
- Why: the records were extracted with the pinned schema; reading them with another is a different listing.
- Reversible: yes

### D-1587 — Request members stored in an `integer` column are bounded by its range
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `core.validation.PG_INTEGER_MAX` (2^31 − 1, PostgreSQL §8.1.1) bounds `ProjectSettings.llm_call_cap`/`draft_call_cap` and the schedules' `interval_s` (create and update) with `le=`; the settings form's cap fields take `maxValue` 2147483647. The jobs spec's schedule line states the interval range.
- Alternatives: widen the columns to `bigint` (a baseline-migration edit, and no use case for caps or intervals that large).
- Why: a larger value passed validation and failed at the write with a 500; it is now a 422 naming the bound. OpenAPI gains `maximum` on those members (the lead regenerates the clients).
- Reversible: yes

### D-1588 — Only extractions outside config mode count as "role C was asked" for absent fields
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `config_ir/held_out.py` sets `StoredPage.asked_llm` only for extractions whose `mode` is not `config`. In config mode role C is asked only for the fields the active config does not cover, so its LLM call says nothing about a covered field. A forced re-learn whose pages are all config-mode extractions therefore lists no field absent.
- Why: a covered field whose steps missed on drifted pages could otherwise be listed absent although the site states it (review finding on #252). Losing an absent entry costs one role C ask per page; a wrong absent entry hides a stated field.
- Alternatives: persist the field names role C was asked per extraction and test membership in `absent._unstated` (exact, but a new column for a rare case).
- Reversible: yes

### D-1589 — A row-mapped field's path refuses the `>` ranking
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `schemas/types.py:_check_row_mapping` refuses `>` in a row path, as it refuses `+`. Row discovery (`resolve/rows.py:_reached`) pools every alternative's rows, so a ranked row path was accepted but not honoured. No preset uses `>` in a row path (the one `>` in the presets is a scalar field's). The schemas spec line on row-mapped lists says so.
- Why: the smallest fix of review finding T161 on #270 that keeps resolve/ (phase 2a) untouched; a document that asks for a ranking it would not get is refused rather than silently pooled.
- Alternatives: make `_reached` return the first rank that reaches rows (a resolve/ change, left to phase 2a).
- Reversible: yes (lifting the refusal once `_reached` honours ranks)

### D-1590 — A page with more links than `MAX_LINKS` states no links for referral
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `acquire/page_refs.page_refs` returns `links=()` when a page has more than `MAX_LINKS` (5000) distinct http(s) link targets, instead of the first 5000. Its own URLs (final URL, canonical, `og:url`) still count.
- Why: a prefix of a large page's links can name one career site where the whole names two, so `Referring.referred` would refer it wrongly (review finding on #248); the cap's comment already said such a page is not judged by its links.
- Reversible: yes

### D-1591 — The request context serializes its names canonically
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `RequestContext` serializes `headers` as its names lowercased and sorted, and `cookies` as its names sorted (case kept), each with the redacted value; values stay out of every serialization (D-1432). Stored captures' `fetch_policy.context` therefore compares equal for the same names in any order or header case, and `recent_capture` reuses them. `recent_capture` also requires the same `screenshot` area when the request asks for a screenshot.
- Why: header field names are case-insensitive (RFC 9110 §5.1), cookie names are not (RFC 6265 §4.1.1); a context is a set of names. Review findings on #262 (T131) and #260 (T99). Captures stored before the change keep their old order and may miss once (greenfield, no migration).
- Reversible: yes

### D-1592 — Token-like query values are withheld by (name, value), from any samples
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `binding.withhold_tokens` withholds each percent-decoded `(name, value)` query item that every sample's endpoint URL holds and that is token-like, unless a page value binds it; it strips items by name and value together. It no longer gives up when the samples' query names differ or when no binding can be built (one sample, mixed methods): the page-value check runs without the binding's own two-sample and one-method checks, so a single sample's token-like values are withheld before role D.
- Why: review findings T80/T81/T82 on #258: an ordinary item sharing a token's name was dropped, and a constant token could reach role D and the stored recipe, against model.py's "never stored unless the page states it". With one sample a constant cannot be told from a parameter, so the stricter reading (withhold) is taken; the replay shows whether the endpoint needs it.
- Reversible: yes

### D-1593 — Task leasing order across jobs: a scored crawl's tasks lease before other jobs' tasks
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277), owner-items · Status: decided (owner 2026-10-18)
- Decision: option (a): `claim_tasks` leases by priority, then round robin between jobs (rank within the job by score, then id), then the job with fewer leased tasks, then job id, then task id. Score orders only within a job. The jobs spec's requirement says so.
- Question: `db/queue.claim_tasks` leases by priority, then score, then id across all jobs, as the jobs spec
  ("Crawl strategy and best-first scoring") requires. A best-first crawl's scored tasks therefore lease before every
  other job's unscored tasks at the same priority (review finding on #261).
- Options: (a) order by score only within a job (score as a tie-break after job fairness, e.g. per-job round robin
  or oldest job first); (b) leave it, since priority already separates job kinds.
- Recommendation: (a), as a jobs-spec change; it changes a requirement, so it waited for the owner, who approved (a) on 2026-10-18.
- Blocked: fairness between a large scored crawl and other jobs at the same priority; nothing else.
- Reversible: yes

### D-1594 — The public CrawlRequest schema does not advertise the `max_pages` alias
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `max_pages` stays accepted by the server as an alias of `limit` (jobs spec, D-1440/D-1446), but the `limit` field description and the CrawlRequest docstring no longer name it; the validator's own docstring records the alias. The SDKs expose `limit` only.
- Why: the alias is a before-validator the OpenAPI schema cannot carry, so a client generated from the schema with extra members forbidden (the Python SDK) refused `max_pages` although the description offered it. Advertising only what the schema can express removes the contract mismatch without a compat shim or a second request member.
- Reversible: yes

### D-1595 — The playground names fetch combinations the server always refuses, on their field, before sending
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `withFetchErrors` (frontend `screens/playground/advanced.ts`) mirrors the two server rules that refuse a fetch combination outright — a screenshot/PDF, `wait_for` or actions with `method_hint: http` (`check_formats`, `FetchOptions._coherent`) and headers with the browser, `wait_for` or actions (INV-44) — as errors on `fetch.method_hint` / `fetch.headers` in Scrape, Batch, Crawl and Extract, so the send is held, like the existing webhook checks. Fields are not disabled.
- Why: the forms let a request reach the API that always 422s. Form-coherence checks of request members are what the forms already do (webhook, page kind); the frontend spec's "MUST NOT validate selectors or schema rules" is about extraction rules, not this. An inline error keeps every field editable and tells the user which change resolves it.
- Reversible: yes

### D-1596 — Crawl's options carry best-first keywords
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: the Crawl options hold `keywords` (a tag list under Query), restored from a stored crawl and sent with `strategy: best_first` only, as `query` is.
- Why: editing a stored crawl that used `keywords` (from the API or an SDK) silently dropped them, so the re-run ranked pages differently. Showing the member is the smallest change that round-trips a stored request; hiding it while preserving it would be a second, invisible path.
- Reversible: yes

### D-1597 — A JSON body decodes as UTF-8: JSON-labelled, or an API capture's not labelled HTML
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `storage/capture_bundle.decode_html` decodes a body as JSON text (UTF-8, with the UTF-16/32 forms told from the first bytes by `json.detect_encoding`, as `core.json_text` reads it) when its last Content-Type essence is a JSON MIME type (`application/json`, `text/json`, `+json`; WHATWG MIME Sniffing §4.6), or when it is an `api` capture (`body.json`, SPEC-01 §4.5) not labelled `text/html` or `application/xhtml+xml`. The label's charset parameter is ignored for such a body. Every other body keeps HTML encoding sniffing (D-1152).
- Why: RFC 8259 §8.1 makes JSON exchanged between systems UTF-8 and §11 gives its media type no charset parameter, so a charset label (or an adapter's re-encoded body keeping the first answer's charset) must not decode it. A refused API answer can be an HTML document, which its own charset decodes; the `api` method alone would misread it.
- Reversible: yes

### D-1598 — The browser's JSON body reads stay bounded by Chromium's DevTools buffer, not a pre-read decoded-size check
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `acquire/browser._json_body` keeps its pre-read check on `Content-Length`/wire size and its post-read 2 MB cap; no check on the decoded size is added before `response.body()`. A compressed JSON body that decodes past the cap is read once and dropped.
- Why: no decoded size is available before the read: Playwright exposes neither the decoded length nor its own CDP session, and a second CDP session's `Network.enable` `maxResourceBufferSize` does not apply to Playwright's `getResponseBody` (measured with the pinned Patchright Chromium: a 5 MB body still read under a 2 MB limit set on another session). Chromium's default per-resource DevTools buffer bounds one read (measured: a gzip JSON decoding to 19.9 MB is returned, one of 20.1 MB is evicted and `body()` fails), and bodies are read one at a time and dropped past the cap, so the worker holds at most about 20 MB transiently per read. Skipping compressed bodies by an assumed ratio would drop legitimate JSON.
- Reversible: yes (a decoded-size cap can be added if Playwright exposes one, or via request interception that streams the body)

### D-1599 — A listing's content fingerprint reads its links as well as its words
- Date: 2026-10-18 · Change/PR: bot-review-fixes (#277) · Status: decided (owner-delegated 2026-10-17)
- Decision: `page_fingerprint` fingerprints a listing by its visible words followed by the canonical URLs it links to, in document order (`content.links`), instead of by its words alone (links only when it had no words, D-1383). A detail page is still fingerprinted by its words. The jobs spec's "Conditional GET and content fingerprint" requirement says so.
- Why: a listing whose rows keep their titles but link to other items (reposted items with new IDs) read as unchanged, so the task linked standing records with stale row URLs and the listing diff never saw the change. The spec already holds standing records valid only "while that task extracted the page the way it would be now"; reading the links restores that. The cost is more re-extraction on listings whose hrefs churn (session or tracking parameters): never a stale record, only a skipped optimisation.
- Reversible: yes

### D-1665 — Scoring follows the wider resource key
- Date: 2026-10-18 · Change/PR: plan-phase-3c (#284), owner-items · Status: decided (owner 2026-10-18: accepted as implemented)
- Decision: `eval.scoring._same_file` already reads `resource_key` (D-1484), so the wider key also makes two images
  that differ only in a path-stated size, conversion or options score as one image. Its test case "another path"
  (`a_1200x.jpg` vs `a_1024x.jpg`) is now a rendition; the other-path case is `a.jpg` vs `b.jpg`. This is a scoring
  change by effect, so the image_url gain above is partly a scoring fix (C10); the owner may keep the key narrow for
  scoring only.
- Reversible: yes

### D-1743 — The first calibration table is held back: τ would abstain most page-level fields
- Date: 2026-10-18 · Change/PR: plan-phase-3d (#288) · Status: decided (owner-delegated 2026-10-17; superseded by D-1770, D-1772)
- Decision: `fit-calibration` is shipped, `backend/data/calibration.json` is not. Fitted on the golden set, the 9 buckets
  with n >= 20 (money, text, url; dev precision 0.57-0.97) all sit below τ (0.97 required, 0.95 optional), so with
  the table live money, text and url coverage falls to about 0 (text 0.569 to 0.005, url 0.564 to 0.003, money 0.315
  to 0). Owner to choose: raise precision first, lower τ, or apply τ only to buckets above it.
- Why: C10 forbids a golden-set precision or coverage drop without a scoring or label reason.
- Reversible: yes (`crawlerai eval fit-calibration --report <eval run --out file>`)

### D-1775 — Rows from page state, grounded by the page's text and links (supersedes D-1774)
- Date: 2026-10-18 · Change/PR: listing-state-sections (#293) · Status: decided (owner-delegated 2026-10-17)
- Decision: A listing no other source gives rows reads them from a state array of `MIN_ITEMS`+ objects. A field's key
  is the row member named by the field's name or schema.org property (the schema's own words), its value normalized
  and shown in the page text; the item URL may instead be a rendered link's target. A row stands only when its URL is
  such a link or its name is shown; else it abstains.
- Why: grounding every value in what the page renders keeps key names from guessing (INV-12's rule applied to state);
  running only where nothing else gives rows leaves every current listing unchanged.
- Reversible: yes

### D-1776 — A listing's sections of one row shape and URL kind are read together
- Date: 2026-10-18 · Change/PR: listing-state-sections (#293) · Status: decided (owner-delegated 2026-10-17)
- Decision: Beside the chosen group, bind reads every aligned group of its field set (or holding its required fields
  and a field beyond the item URL) whose blocks lead, a quorum of them, to URLs of its blocks' kind (host, path depth, first segment),
  apart from blocks already read; blocks in document order, one per item (session parameters aside).
- Why: on the dev set, without the URL kind check footer and category lists of the same shape became rows (FP);
  with it, listing rows TP 935 to 999, FN 926 to 862, FP 181 to 180 (`--llm unanswered`).
- Reversible: yes

### D-1777 — Price over currency certainty: what still declines
- Date: 2026-10-18 · Change/PR: price-currency · Status: decided (applies owner #68)
- Decision: A contradiction still declines: two signs sharing no currency (`USD 12 EUR`) and a sign that cannot
  denote the structured `priceCurrency` stay `Invalid`. A monetary range keeps declining on a `null` currency
  (`currency_unknown`), and a label import declines a money label whose currency is unknown (ground truth states it).
- Why: owner #68 covers a price whose currency could not be determined, not one the page states two ways.
- Reversible: yes

### D-1778 — Currency evidence: buckets, region signals, checked syntax
- Date: 2026-10-18 · Change/PR: price-currency · Status: decided (applies owner #68)
- Decision: Only `locale` and `unknown` money values are measured apart (`money|<evidence>|<basis>`, uncalibrated until
  n >= 20); `page` is noted in `field_meta.basis` and keeps its bucket. The ccTLD and Content-Language narrow a shared
  currency sign only; number and date readings ignore them. A signless amount is `Ok.checked=false`: never spotted and
  never admitted from state or XHR without an anchor.
- Why: owner #68 asks lower confidence for steps 4-5 only; a bare number is no evidence that a text is a price.
- Reversible: yes

### D-1779 — A multi-currency shop's stored answer stays unpriced
- Date: 2026-10-18 · Change/PR: price-currency · Status: decided (applies owner #68)
- Decision: The Shopify guard stays: such a shop is not served live, so the page path publishes the price the page
  shows (its currency or unknown); a stored answer's rows stay unpriced, since its amounts are the primary market's.
- Why: publishing another market's amount with an unknown currency would be a wrong price, not a missing currency.
- Reversible: yes
