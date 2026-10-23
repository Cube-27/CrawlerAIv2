# CLAUDE.md

CrawlerAI v2 is a schema-driven web extraction engine; see `README.md`.

## Layout

- `backend/` (Python, `src/crawlerai/`, `tests/`, `migrations/`), `frontend/` (Vite+, React), `sdk/`, `infra/`,
  `tools/` (repo checks and `tools/orchestrator/` worktree/CI scripts).
- `docs/architecture.md`: what the code does and where. `docs/rules.md`: the rules CI and agents enforce. `docs/archive/`:
  frozen history (old specs, design, decisions, handover), not maintained; the code wins over it.
- Read only what your change needs. Where the docs and the contract disagree, stop and ask the owner.
- Work on a branch `change/<id>` in a worktree made by `tools/orchestrator/new_worktree.sh <id> change/<id>`, never
  in the main checkout. `main` takes PRs only. Never merge your own PR.

## Agent workflow

One orchestrator and at most two builders, each a Claude session in its own herdr tab:
`docs/agents/orchestrator.md` (the orchestrator, `/crawlerai-orchestrator`), `docs/agents/builder-protocol.md` (every
builder; its HARD RULES override the rest). Test output is cut to failures and the summary by `.claude/hooks/test_output_hook.py` (`TEST_FILTER=0` shows it all).

## Commands

Needs Docker, `uv`, `pnpm`, GNU make. From the repo root:

```sh
make dev            # Postgres, migrations, API on :8000
make db             # Postgres only (`make db-down` stops it)
make migrate        # alembic upgrade head, then `crawlerai schemas sync`
make api-client     # regenerate frontend/openapi.json and src/api/schema.d.ts; commit both (CI fails on a diff)
make check          # every CI check locally (`make check-backend`, ... per job)
```

- `uv run mypy src tests migrations` (in `backend/`) must pass.
- `browser` tests need Google Chrome stable: `uv run patchright install chrome` once.
- DB tests need `make db` and `CRAWLERAI_DATABASE_URL` (`.env.example`); `tests/db` also need
  `CRAWLERAI_TEST_DATABASE_URL`, a database they own, never the dev one. `tools/orchestrator/test_db.sh up|drop`
  manages one per worktree.
- Run only the test files you touched, one at a time; never the full suite or `pytest -n` locally.

## Contract (binding; `docs/rules.md`)

A bug fix repairs the layer whose rule failed, for the whole class of pages. Data the page does not state stays
unpublished. No site-specific steps, no speculative layers, no second path for existing logic (C8).

- **C1.** Claims rest on pages nobody fitted on. The measure is the e2e run: one run of the product per round over
  the one eval set, kept outside the repo, scored by one scorer, each disagreement adjudicated against the capture.
  The set grows in fresh batches (20–30 pages, one per host not in it before, stratified by schema, language,
  platform and render mode); a batch is scored once, before any change is made on it, and that first score is the
  only generalization number; then it joins the set. Never look at a fresh batch's pages before that score.
  Calibration, precedence and drift margins are frozen as fitted on 2026-10-18; a refit needs the owner. The set, its
  URLs, values and captures stay out of the repo (C3).
- **C2.** Every generic rule names its standard (schema.org, ISO, CLDR, RFC, HTML) or structural property in a
  comment. "Site X does Y" is never a justification.
- **C3.** Hostnames, site, retailer and brand names, and strings copied from pages live only in
  `backend/src/crawlerai/adapters/` and database rows. Fixtures are synthetic, with RFC 2606 names (`example.com`,
  `.test`).
- **C4.** Vocabularies come from versioned external data in `backend/data/manifest.json`. No word, selector or regex
  added because one page failed.
- **C5.** A failing site is fixed by config, a learning re-run or an operator correction; change generic code only for
  a class of failures, shown with e2e results.
- **C7.** No defaults; an unclear currency never drops a price, but a price whose amount is contested by an
  unexplained rival is a conflict (INV-14); currency from page evidence, else the URL locale/subdomain/ccTLD
  (flagged), else null; no host tables, and no other value from URL codes (owner #68, D-1782).
- **C9.** No test is named after a site or asserts one site's output; write property and replay tests.
- **C10.** A change that alters extraction is accepted when it improves the e2e run and drops no field type's
  precision without a stated reason (a scoring fix, an adjudicated correction of the set). The PR reports the e2e
  aggregate per field type before and after, never per-page or per-site numbers, and a gain from fewer than 3 hosts
  is flagged. Claims that the engine generalizes come only from a fresh batch's first score.
- **C11.** Cognitive complexity at most 15 per function (hard check); files over 800 lines only warn. Add no other
  LOC, complexity, coverage or ratchet gate.
- **C12.** Never read, copy or port from the `Invoro` or CrawlerAI v1 repositories.
- **C13.** Nothing in the candidates register (owner's candidates list) is built until the owner admits it.

## Other rules

- Never `exec` or `eval` LLM output; generated selectors, recipes and schemas are data for our interpreters.
- Public repo: no customer or company names (except adapter platform names), secrets, captures, eval data, URLs or
  site names. Commit only synthetic fixtures.
- No AGPL, GPL, SSPL or non-commercial dependencies (CI enforces).
- Greenfield: no versioning, migration chains or compatibility shims; a model change edits the one baseline
  migration. Record versions, draft and active configs and `engine_version` stay.
- An architecture change deletes what it supersedes in the same PR. Code comments cite the standard, not `D-NNNN`, `ARCHITECTURE §N` or `SPEC-NN`.
- Verification is runtime grounding on real pages plus the `.claude/skills/verify-*` checks (formal or property) for
  the paths a change touches, not new example tests. A test is added only for a behaviour nothing else covers; tests a
  change makes redundant are deleted. No eval loops: one timeboxed regression run per PR, on the final code, gives the
  C10 before/after report; generalization claims come only from a fresh batch's first score (C1). A `pytest.raises`
  block holds one call.
- Decisions within one change's scope are yours: write them in the PR body only. Escalate to the owner anything that
  alters the contract, a public API or schema other capabilities rely on, the evaluation procedure
  or labels, or needs credentials: say so in your report and move on. The orchestrator asks the owner.
- Merge needs green CI and every review thread (any bot) fixed or answered and resolved.
