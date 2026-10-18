# CLAUDE.md

CrawlerAI v2 is a schema-driven web extraction engine; see `README.md`.

## Layout

- `backend/` (Python, `src/crawlerai/`, `tests/`, `migrations/`), `frontend/` (Vite+, React), `sdk/`, `infra/`,
  `tools/` (repo checks and `tools/orchestrator/` worktree/CI scripts).
- `openspec/project.md`: the contract C1–C13 and repo checks. `openspec/specs/<capability>/spec.md`: current
  behaviour, the source of truth; a behaviour change edits the spec it touches. `openspec/design/`: goals, owner
  decisions, candidates register. `openspec/conventions/ENGINEERING.md` (code), `DESIGN.md` (frontend).
- Read only what your change needs. Where a spec, the design and the contract disagree, stop and ask the owner.
- Work on a branch `change/<id>` in a worktree made by `tools/orchestrator/new_worktree.sh <id> change/<id>`, never
  in the main checkout. `main` takes PRs only. Never merge your own PR.

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
- `browser` tests need `uv run patchright install --no-shell chromium` once.
- DB tests need `make db` and `CRAWLERAI_DATABASE_URL` (`.env.example`); `tests/db` also need
  `CRAWLERAI_TEST_DATABASE_URL`, a database they own, never the dev one. `tools/orchestrator/test_db.sh up|drop`
  manages one per worktree.
- Run only the test files you touched, one at a time; never the full suite or `pytest -n` locally.

## Contract (binding; `openspec/project.md`)

A bug fix repairs the layer whose rule failed, for the whole class of pages. Data the page does not state stays
unpublished. No site-specific steps, no speculative layers, no second path for existing logic (C8).

- **C1.** The golden set (`dev`) is the only measure. It grows in fresh batches of 20-30 pages on new hosts; a batch
  is scored once before any change is made on it, and only that first score supports a generalization claim. Then it
  joins the golden set. Never look at a fresh batch's pages before that score. Fit thresholds, precedence and
  calibration on the golden set.
- **C2.** Every generic rule names its standard (schema.org, ISO, CLDR, RFC, HTML) or structural property in a
  comment. "Site X does Y" is never a justification.
- **C3.** Hostnames, site, retailer and brand names, and strings copied from pages live only in
  `backend/src/crawlerai/adapters/` and database rows. Fixtures are synthetic, with RFC 2606 names (`example.com`,
  `.test`).
- **C4.** Vocabularies come from versioned external data in `backend/data/manifest.json`. No word, selector or regex
  added because one page failed.
- **C5.** A failing site is fixed by config, a learning re-run or an operator correction; change generic code only for
  a class of failures, shown with golden-set results.
- **C7.** No defaults, fallback currency, host tables or values from URL codes.
- **C9.** No test is named after a site or asserts one site's output; write property and replay tests.
- **C10.** A change that alters extraction must improve the golden set and not drop any field type's precision
  without a stated reason. The PR's evaluation section gives the golden-set aggregate per field type, before and
  after, with no per-page or per-site numbers; a gain from fewer than 3 hosts is flagged.
- **C11.** Cognitive complexity at most 15 per function (hard check); files over 800 lines only warn. Add no other
  LOC, complexity, coverage or ratchet gate.
- **C12.** Never read, copy or port from the `Invoro` or CrawlerAI v1 repositories.
- **C13.** Nothing in the candidates register (`openspec/design/overview.md` §22) is built until the owner admits it.

## Other rules

- Never `exec` or `eval` LLM output; generated selectors, recipes and schemas are data for our interpreters.
- Public repo: no customer or company names (except adapter platform names), secrets, captures, eval data, URLs or
  site names. Commit only synthetic fixtures.
- No AGPL, GPL, SSPL or non-commercial dependencies (CI enforces).
- Greenfield: no versioning, migration chains or compatibility shims; a model change edits the one baseline
  migration. Record versions, draft and active configs and `engine_version` stay.
- An architecture change deletes what it supersedes in the same PR. Code comments cite the spec requirement or the
  standard, not `D-NNNN`, `ARCHITECTURE §N` or `SPEC-NN`.
- Tests: few, behaviour-level; no eval loops — one timeboxed regression run per PR; accuracy claims only from a fresh
  batch's first score. Behaviour and Hypothesis property tests over generated inputs; replay tests of stored synthetic captures
  for extraction; a `pytest.raises` block holds one call.
- Decisions within one change's scope are yours: log them in the PR body. Escalate to the owner anything that alters
  the contract, `openspec/design/`, a public API or schema other capabilities rely on, the evaluation procedure or
  labels, or needs credentials. To escalate, record a `needs-owner` entry in `openspec/decisions/log.md`, list it
  under "Open owner items" in `openspec/project.md`, and move to the next task.
- Merge needs green CI and every review thread (any bot) fixed or answered and resolved.
