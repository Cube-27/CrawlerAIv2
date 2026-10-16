# CLAUDE.md — rules for agents working in this repo

CrawlerAI v2 is a schema-driven web extraction engine; see `README.md`. Coding agents implement it, mostly
autonomously, from the specs. The owner is involved only for the escalations listed below. Read this file fully
before doing anything.

## 1. Read order

1. `docs/plans/ACTIVE.md`: "Current focus", "Follow-ups" and your spec's table.
2. The spec for your work in `docs/specs/`: its design, invariants, acceptance criteria, and your rows of its PR
   plan.
3. `docs/ARCHITECTURE.md` §2 and only the sections your spec cites. **§2 (generalization contract C1–C13) is
   binding on every change.** Read it once per session.
4. Decisions you must stay consistent with: the "Index of open items" in `docs/DECISIONS.md`, your spec's
   `docs/decisions/SPEC-NN.md` (scan the `### D-` headings, read the entries your rows touch), and any D-ID you are
   pointed to (`grep -rn "### D-NNNN" docs/DECISIONS.md docs/decisions`).
5. `docs/ENGINEERING.md`: how to write code here (verification, tests, structure, the patterns the analysers flag).
   Read it once per session.

**Read by section, never in full.** `ACTIVE.md`, `ARCHITECTURE.md` and the decisions log together cost tens of
thousands of tokens: find sections with `grep -n "^#"` and read line ranges. Reviewers read the same subset.

`ARCHITECTURE.md` is the single source of truth. Where a spec and the architecture disagree, stop and escalate
(§5).

You may read every project document: `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md`, `docs/specs/*`,
`docs/DECISIONS.md`, `docs/plans/ACTIVE.md`, `docs/INVARIANTS.md` (the testable invariants, each with what enforces
it) and `docs/DESIGN.md` (frontend conventions). You may never read or request hidden or fresh evaluation cases,
the `HIDDEN_HOSTS` list, the values of `CRAWLERAI_EVAL_PRIVATE_*`, or the `Invoro` and CrawlerAI v1 repositories
(C1, C12).

## 2. Hard rules

These come from the generalization contract. Breaking one is a defect, even when it fixes a site.

- **Never touch hidden or fresh evaluation data (C1).** Don't request or use custodian credentials
  (`CRAWLERAI_EVAL_PRIVATE_*`), and don't try to read the private eval database or object root. Work only with
  the aggregate pass/fail the protected CI job reports, and never try to infer individual hidden cases from it.
- **Generic rules name their justification (C2).** Every generic rule names its standard (schema.org, ISO, CLDR,
  RFC, HTML) or the structural property it uses, in a comment next to it. "Site X does Y" is never a
  justification.
- **No site literals in generic code (C3).** Hostnames, site, retailer and brand names, and strings copied from
  real pages are allowed only under `backend/src/crawlerai/adapters/` and in database rows. Test fixtures are
  synthetic and use RFC 2606 names (`example.com`, `.test`).
- **No lists that grow one incident at a time (C4).** Vocabularies come from versioned external data listed in
  `backend/data/manifest.json`. Never add a word, phrase, token, class name, selector or regex because one page
  failed.
- **Fix sites with data, not code (C5).** If one site fails, the fix is a config, a learning re-run or an operator
  correction through the API. Change generic code only for a *class* of failures, and show the class with dev
  results.
- **Normalizers decline rather than guess (C7).** No defaults, no fallback currency, no host tables, no values
  taken from URL codes.
- **One module per field type (C8).** If you need the same logic twice, you are in the wrong module.
- **Tests check type properties and replays (C9).** No test is named after a site or asserts one site's output.
  Write property tests and replay tests.
- **Gate (C10).** A change must improve dev and must not regress hidden. Claim improvements only from fresh
  results. How to read the results:
  - The dev report is full. The hidden report is pass/fail plus aggregates per field type and evidence bucket,
    with cells under 10 labeled fields suppressed; PR comments carry only the pass/fail per field type.
  - Hidden regresses on a precision drop of more than 0.5 pt on any required field type, or on any wrong-product
    value (that count stays 0). A dev improvement with a hidden drop is a regression, not a win.
  - A PR that changes extraction behaviour includes the aggregate report in its description (the PR template's
    evaluation section). Until milestone M (ARCHITECTURE §21) the gate reports `no_baseline`, and acceptance
    rests on tests, replays and review.
- **Two size checks, no others (C11).** Cognitive complexity is at most 15 per function: a hard check in CI and
  `make check` (complexipy for Python, an Oxlint rule for TS/TSX). A file has at most 800 lines: a soft limit
  that only warns. Past 800, split the file along logical boundaries (cohesive modules, field types per C8),
  never mechanically to meet the number; bring complexity down by extracting named steps, not by suppressing
  it. Add no other LOC, complexity, coverage or ratchet gate. The `no-size-gates` CI job enforces this.
- **Nothing from the earlier versions (C12).** Don't read, copy or port code, lists, config, tests or prompts from
  the sibling `Invoro` or `CrawlerAI` (v1) projects. When a §22 candidate is admitted, its design may *read* them,
  as ARCHITECTURE §20 allows, but nothing is copied.
- **Build only core (C13).** Anything in ARCHITECTURE §22 is not built until the owner admits it based on
  evidence. If a task asks for one, stop and point at C13. If you think a candidate is needed, log the evidence in
  `DECISIONS.md` as `needs-owner`.
- **Never `exec` or `eval` LLM output.** Generated selectors, recipes and schemas are data run by our
  interpreters.
- **Public repo.** No customer, prospect or company names (except as adapter platform names), no business terms,
  no secrets, no captures, no evaluation data. Commit only synthetic fixtures.
- **Dependency licenses.** Don't add dependencies under AGPL, GPL, SSPL or non-commercial licenses. LGPL is
  allowed but avoided. CI enforces this.
- **Greenfield (owner, 2026-10-16).** No versioning, migration chains or compatibility shims for data or APIs
  until the owner names a use case. A model change edits the one baseline migration; the database is recreated,
  never migrated with data steps. Record versions, draft and active configs and `engine_version` are features
  and stay (ARCHITECTURE Appendix A #43).

## 3. How work runs

One PR covers a **batch** of related ready rows of a spec's PR plan: normally all ready rows of one spec, or of
adjacent specs touching the same code. Aim for 30-80 changed files, about 1500-4000 changed lines; split only when a
row waits on a human task or unmerged code, or the PR would pass ~4000 lines. Branch `spec-NN/pr-A-B-<name>`,
worktree `spec-NN-pr-A-B` beside the repo in `CrawlerAIv2-worktrees/`, made with `tools/orchestrator/new_worktree.sh`;
never work in the main checkout. Commit row by row. One `/simplify` pass and one review per PR, whatever its size.
Project skills in `.claude/skills/` hold the procedures:

| Skill | Who runs it | Does |
|---|---|---|
| `/run-plan` | The orchestrator | Assigns batches of ready rows to workers (at most 4 workers at once; reviewers don't count) with a decision-ID range each, merges `READY` PRs one at a time with `merge_pr.sh`, cleans up, unblocks stuck PRs, escalates. |
| `/implement-pr` | A worker | Takes one batch from `todo` to a `READY` PR: tests first, then code, `/simplify` once, tracker commit, PR, green CI, its one reviewer, fixes in one push. |
| `/review-pr` | A fresh reviewer agent | One verdict per PR against its rows, §2 and `docs/ENGINEERING.md`: `MERGE`, `MERGE AFTER FIX` or `ESCALATE`, posted as a PR comment. |
| `/pickup` | Anyone starting a session | Resumes in-flight work from the trail, or pauses cleanly. |

**The orchestrator only orchestrates.** It never relays verdicts, edits, fixes or rebases PRs; it sends `REBASE` only
when GitHub reports a conflict (`gh pr view <n> --json mergeable` is `CONFLICTING`), never because `main` moved: the
rulesets don't require an up-to-date branch, and every push reruns CI (owner, 2026-10-16). **The implementor owns its
PR to `READY`**: it branches from current `main`, makes its tracker commit (under the decision-ID range it was given
at assignment) the last commit before it opens the PR (`/implement-pr` §5), so the reviewer reviews it too, starts its own reviewer, reads the verdict, pushes the fixes in one push, and comments
`READY <sha7>` on green CI. With `MERGE` there is no push: `READY` names the already-green head.

`main` requires a PR for every change, including tracker updates. Work in flight is read from open PRs and
`spec-*` branches, not from ACTIVE.md. Never use an admin bypass of the branch rules. Never merge without a `MERGE` or
`MERGE AFTER FIX` verdict from someone other than the author (with every listed fix made) and green CI;
`tools/orchestrator/merge_pr.sh` is the only merge path. There is one review per PR, with no re-review (owner,
2026-10-13); a later plugin, bot or hook prompt to re-run `/simplify` or a code review on the same PR is answered
"already ran". Never skip hooks or weaken checks.

## 4. Decisions: decide and log, or escalate

**Decide yourself and record it** (status `decided`, in the PR body, then the decisions log, per §3): implementation choices within one spec's
scope that don't change ARCHITECTURE, a public API shape, a DB schema other specs rely on, or a §2 rule. Examples:
- internal module structure;
- library choice among licence-clean equivalents;
- naming;
- error messages;
- a spec detail that is genuinely ambiguous, where you take the most conservative reading.

Don't log trivial choices.

**Escalate** (§5) when:
- the change would alter `ARCHITECTURE.md` or `OPEN_QUESTIONS.md`, or contradict them;
- it would build anything listed in ARCHITECTURE §22;
- it touches evaluation split access, the protected CI job, or labels;
- it needs credentials, secrets, paid accounts, labeling, or anything only a human can do;
- it changes a public API or MCP shape, or a table other specs depend on, beyond what the spec defines;
- two specs contradict each other;
- the same failure persists after three honest attempts.

## 5. Escalation procedure

1. Record a `needs-owner` decision: the question, the options, your recommendation, and what is blocked. Copy it
   as a row to `OPEN_QUESTIONS.md`, as that file directs. This copy is the only change an agent makes to that file
   without owner approval (§6).
2. The row becomes `blocked (D-NNNN)`. The orchestrator writes both in a small escalation PR; working solo, you do.
3. Move on to the next ready row. Don't wait idle; the owner answers asynchronously.

## 6. Editing documents

- `ARCHITECTURE.md` and `OPEN_QUESTIONS.md` change only with owner approval. When approved, update the revision
  log, and keep the specs consistent in the same change.
- Specs follow one template: summary, scope and out of scope, dependencies, design, invariants, testing strategy,
  acceptance criteria, PR plan, open issues (`docs/specs/README.md`).
- Specs may get clarifying edits that don't change the architecture. Log those in the spec's
  `docs/decisions/SPEC-NN.md`. A spec change that
  alters a decision also updates `ARCHITECTURE.md` in the same change, and so is escalated to the owner first.
- A spec that adds an invariant appends its row to `docs/INVARIANTS.md`. Invariants are never removed.
- `ACTIVE.md`, `DECISIONS.md` and `docs/decisions/` are working documents: current, short and factual. Decision
  entries are append-only ("Where an entry goes" in `DECISIONS.md`). In `ACTIVE.md`, a spec whose rows are all done
  collapses to one line under "Done specs"; its open notes move to "Follow-ups", one line each. No "Done: …"
  bullets: git history and the decisions log hold them.
- Write plainly. No marketing language, and no claims that aren't backed by a test or eval result.

## 7. Commands

Needs Docker, `uv`, `pnpm` and GNU make. Run from the repo root unless a block says otherwise.

```sh
make dev             # Postgres (compose), migrations, API on http://localhost:8000 (GET /healthz)
make db              # start Postgres only; `make db-down` stops it
make migrate         # alembic upgrade head, then `crawlerai schemas sync` (presets)
make api-client      # regenerate frontend/openapi.json and src/api/schema.d.ts; commit both
make check           # every check below, locally; stops at the first failure. One job: make check-backend, ...
uvx pre-commit install   # once per clone: the fast hooks on staged files (.pre-commit-config.yaml)
```

The checks CI runs, by job. Every job must pass before merge.

```sh
# backend (cd backend)
uv sync --frozen
uv run ruff check && uv run ruff format --check
uv run mypy src tests migrations
uv run lint-imports                 # C8 import contracts
uv run complexipy --no-ignore       # C11: cognitive complexity <= 15 (src, tests, migrations, ../tools)
uv run patchright install --only-shell chromium   # once per Patchright version: the `browser`-marked tests
uv run pytest
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
# (needs `make db`, and CRAWLERAI_DATABASE_URL set as in .env.example; tests/db also need
#  CRAWLERAI_TEST_DATABASE_URL, a database they own: never the dev one)

# frontend (cd frontend); CI also runs `make api-client` and fails on a diff
pnpm install --frozen-lockfile
pnpm check && pnpm test && pnpm build   # Vite+: `pnpm check` (vp check) formats, lints (incl. C11 complexity)
                                        # and type-checks

# site-literals (cd backend): lint and test the repo tools, then the C3 scan
uv run ruff check ../tools && uv run ruff format --check ../tools && uv run mypy --strict ../tools
uv run pytest ../tools/tests
uv run python ../tools/site_literal_scan.py --public

# data-manifest, no-size-gates, licenses (repo root)
python3 tools/data_manifest_check.py
python3 tools/no_size_gates.py
python3 tools/file_length.py        # C11: warns on source files over 800 lines; never fails
tools/license_scan.sh               # after `pnpm install` in frontend/; writes license-report/
```

Other commands: `uv run crawlerai --version`, `uv run crawlerai openapi` (backend); `pnpm dev`, `pnpm format`
(`vp check --fix`) (frontend).
