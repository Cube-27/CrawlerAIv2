# Rules still enforced

CI checks and the contract agents rely on. `CLAUDE.md` holds the full agent text; this is the quick list.

## Extraction contract (C1–C13)

- **C1** Accuracy claims come only from the e2e run over the eval set (kept outside the repo); a fresh batch's first score is
  the only generalization number. Never look at a fresh batch before it is scored.
- **C2** Every generic rule names its standard (schema.org, ISO, CLDR, RFC, HTML) or structural property in a comment.
- **C3** Hostnames, brand names and page strings only in `backend/src/crawlerai/adapters/` and DB rows. Fixtures are synthetic
  (`example.com`, `.test`). CI: `tools/site_literal_scan.py --public`.
- **C4** Vocabularies come from versioned external data in `backend/data/manifest.json`; no word, selector or regex for one page.
- **C5** A failing site is fixed by config, a learning re-run or an operator correction; generic code changes only for a class.
- **C7** No defaults; never rewrite page data's meaning; an unclear currency never drops a price (`$`=USD with no other hint,
  else URL locale, flagged, else null); a price contested by an unexplained rival is a conflict. Prices/ratings are numbers.
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
- `make api-client` output (`frontend/openapi.json`, `src/api/schema.d.ts`) is committed; CI fails on a diff.
- Branch `change/<id>` in a worktree (`tools/orchestrator/new_worktree.sh`); `main` takes PRs only; merge needs green CI and
  every review thread resolved; never merge your own PR.
- Tests: only files you touched locally; `pytest.raises` blocks hold one call; verification is runtime grounding plus `.claude/skills/verify-*`.
- Update `docs/` when a change makes them wrong. Reasoning goes in the PR body.
