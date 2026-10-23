# Rules still enforced

CI checks and the contract agents rely on. `CLAUDE.md` holds the full agent text; this is the quick list.

## Project charter

1. **Objective.** Improve crawl and extraction coverage and accuracy in general. Keep one coherent browser/HTTP
   fingerprint. Keep the code machine-agnostic (Windows and Linux).
2. **Bug.** An extracted value differs from the live page AND it is a pattern, not a site-specific issue. Site-only
   problems are fixed by config or data (C5).
3. **Decisions** are kept until proven wrong; then they are flagged to the owner instead of followed. No technology or
   decision is frozen.

## Extraction contract (C1–C13)

- **C1** Accuracy claims come only from the e2e run over the eval set (kept outside the repo); a fresh batch's first score is
  the only generalization number. Never look at a fresh batch before it is scored.
- **C2** Every generic rule names its standard (schema.org, ISO, CLDR, RFC, HTML) or structural property in a comment.
- **C3** Hostnames, brand names and page strings only in `backend/src/crawlerai/adapters/` and DB rows. Fixtures are synthetic
  (`example.com`, `.test`). CI: `tools/site_literal_scan.py --public`.
- **C4** Vocabularies come from versioned external data in `backend/data/manifest.json`; no word, selector or regex for one page.
- **C5** A failing site is fixed by config, a learning re-run or an operator correction; generic code changes only for a class.
- **C6** Adapters only for multi-tenant platforms, evaluated on ≥3 tenants; measured in the e2e run, no CI check.
- **C7** No defaults except the currency symbol's; never rewrite page data's meaning; an unclear currency never drops a price (page evidence, else URL
  locale/subdomain/ccTLD, flagged, else the symbol's primary currency in CLDR's English locale (`$` USD), flagged, else null; no host tables); a price contested by an unexplained rival is a conflict. Prices/ratings are numbers.
- **C8** One module per field type; no second path for existing logic. CI: `lint-imports`.
- **C9** No test is named after or asserts one site; write property and replay tests.
- **C10** An extraction change must improve the e2e run without dropping a field type's precision; the PR reports aggregates per
  field type, never per page or site; a gain from <3 hosts is flagged.
- **C11** Cognitive complexity ≤ 15 per function (`complexipy`, Oxlint); files over 800 lines only warn; no other size/coverage
  gate (`tools/no_size_gates.py`).
- **C12** Nothing from the Invoro or CrawlerAI v1 repos. **C13** Candidates are built only when the owner admits them.

## Product rules

- HTTP first; the browser only when blocked, a JS shell, or `render.mode` asks. A missing field never triggers a render.
- robots.txt off by default (`respect_robots: true` opts in). No proxies or CAPTCHA solving by default.
- The LLM never invents a value; values are grounded verbatim; its output is never `exec`/`eval`ed (ruff `S102`/`S307`).
- Every crawl extracts fresh; learning keeps selectors and cookies, never values.
- A stated brand outranks the platform vendor; a job page holding its application form is its own `apply_url`; a canonical link
  wins for the page URL.
- Hide internals from users; unpublished beats wrong.

## Repo rules

- Public repo: no customer or company names, secrets, captures, eval data or site URLs. No AGPL/GPL/SSPL/non-commercial
  dependencies (`tools/license_scan.sh`).
- Greenfield: a model change edits the one baseline migration; no compatibility shims. An architecture change deletes what it
  supersedes in the same PR.
- Frontend: visual values only in `frontend/src/app/theme.css`, UI only from `@heroui/react` (`tools/theme_only_check.py`).
- `uv run tools/dev.py api-client` output (`frontend/openapi.json`, `frontend/src/api/schema.d.ts`) is committed; CI fails on a diff.
- Branch `change/<id>` in a worktree (`tools/orchestrator/new_worktree.sh`); `main` takes PRs only; merge needs green CI and
  every review thread resolved; never merge your own PR.
- Tests: only files you touched locally; `pytest.raises` blocks hold one call; verification is runtime grounding plus `.claude/skills/verify-*`.
- Code is the source of truth. Delete a plan or spec once it's implemented; record only important decisions in `docs/decisions.md`.
- Update `docs/` when a change makes them wrong. Reasoning goes in the PR body.
