# CLAUDE.md — rules for agents working in this repo

CrawlerAI v2 is a schema-driven web extraction engine; see `README.md`. Coding agents implement it, mostly
autonomously, from OpenSpec changes. The owner is involved only for the escalations listed below. Read this file
fully before doing anything.

## 1. Read order

1. `openspec/project.md`: the layout of `openspec/`, the **generalization contract C1–C13 (binding on every
   change)**, the repo checks, and the open owner items. Read it once per session.
2. The capability specs your change touches: `openspec/specs/<capability>/spec.md` (current behaviour).
3. Your change folder `openspec/changes/<change-id>/` (proposal, tasks, deltas, `design.md` if any); for a backlog
   item, its line in `openspec/backlog.md`.
4. `openspec/conventions/ENGINEERING.md`: how to write code here (verification, tests, structure, the patterns the
   analysers flag). Read it once per session; for frontend work also `openspec/conventions/DESIGN.md`.

**Read only what your change needs, never in full**, and don't update a document unless your change makes it wrong.
Everything else is read on demand, by section (`grep -n "^#"`, then line ranges), when a spec or the code points
to it: `openspec/design/` (goals, contract evidence, candidates register, owner decisions), decision entries
(`grep -rn "### D-NNNN" openspec`), and the archive (`openspec/changes/archive/`): the done specs (`SPEC-NN §x`) and
the frozen ARCHITECTURE.md rev 26 (`ARCHITECTURE §N`). Archived files are history: open one section only when you
need the design of code you are changing, and never edit them. Reviewers read the same subset.

The capability specs are the source of truth for behaviour. Where a spec, a change, `openspec/design/` or the
contract disagree, stop and escalate (§5).

You may read every project document under `openspec/`. You may never read or request hidden or fresh evaluation
cases, the `HIDDEN_HOSTS` list, the values of `CRAWLERAI_EVAL_PRIVATE_*`, or the `Invoro` and CrawlerAI v1
repositories (C1, C12).

## 2. Hard rules

The contract C1–C13 in `openspec/project.md` is binding: breaking a rule is a defect, even when it fixes a site.
How it applies day to day:

- **C1.** Don't request or use custodian credentials (`CRAWLERAI_EVAL_PRIVATE_*`), and don't try to read the private
  eval database or object root. Work only with the aggregate pass/fail the protected CI job reports, and never try
  to infer individual hidden cases from it.
- **C2.** Every generic rule names its standard (schema.org, ISO, CLDR, RFC, HTML) or the structural property it
  uses, in a comment next to it. "Site X does Y" is never a justification.
- **C3.** Hostnames, site, retailer and brand names, and strings copied from real pages are allowed only under
  `backend/src/crawlerai/adapters/` and in database rows. Test fixtures are synthetic and use RFC 2606 names
  (`example.com`, `.test`).
- **C4.** Vocabularies come from versioned external data listed in `backend/data/manifest.json`. Never add a word,
  phrase, token, class name, selector or regex because one page failed.
- **C5.** If one site fails, the fix is a config, a learning re-run or an operator correction through the API.
  Change generic code only for a *class* of failures, and show the class with dev results.
- **C7.** No defaults, no fallback currency, no host tables, no values taken from URL codes.
- **C8.** If you need the same logic twice, you are in the wrong module.
- **C9.** No test is named after a site or asserts one site's output. Write property tests and replay tests.
- **C10 (gate).** A change must improve dev and must not regress hidden. Claim improvements only from fresh
  results. How to read the results:
  - The dev report is full. The hidden report is pass/fail plus aggregates per field type and evidence bucket,
    with cells under 10 labeled fields suppressed; PR comments carry only the pass/fail per field type.
  - Hidden regresses on a precision drop of more than 0.5 pt on any required field type, or on any wrong-product
    value (that count stays 0). A dev improvement with a hidden drop is a regression, not a win.
  - A PR that changes extraction behaviour includes the aggregate report in its description (the PR template's
    evaluation section). Until milestone M the gate reports `no_baseline`, and acceptance rests on tests, replays
    and review.
- **C11.** Cognitive complexity is at most 15 per function: a hard check in CI and `make check` (complexipy for
  Python, an Oxlint rule for TS/TSX). A file has at most 800 lines: a soft limit that only warns. Past 800, split
  the file along logical boundaries (cohesive modules, field types per C8), never mechanically to meet the number;
  bring complexity down by extracting named steps, not by suppressing it. Add no other LOC, complexity, coverage or
  ratchet gate. The `no-size-gates` CI job enforces this.
- **C12.** Don't read, copy or port code, lists, config, tests or prompts from the sibling `Invoro` or `CrawlerAI`
  (v1) projects. When a §22 candidate is admitted, its design may *read* them (ARCHITECTURE §20), but nothing is
  copied.
- **C13.** Anything in the candidates register (§22, `openspec/design/overview.md`) is not built until the owner
  admits it based on evidence. If a task asks for one, stop and point at C13. If you think a candidate is needed,
  log the evidence as a `needs-owner` decision.
- **Never `exec` or `eval` LLM output.** Generated selectors, recipes and schemas are data run by our
  interpreters.
- **Public repo.** No customer, prospect or company names (except as adapter platform names), no business terms,
  no secrets, no captures, no evaluation data. Commit only synthetic fixtures.
- **Dependency licenses.** Don't add dependencies under AGPL, GPL, SSPL or non-commercial licenses. LGPL is
  allowed but avoided. CI enforces this.
- **Greenfield (owner, 2026-10-16).** No versioning, migration chains or compatibility shims for data or APIs
  until the owner names a use case. A model change edits the one baseline migration; the database is recreated,
  never migrated with data steps. Record versions, draft and active configs and `engine_version` are features
  and stay (owner decision #43).

## 3. How work runs

Work is an OpenSpec change: `openspec/changes/<change-id>/` with `proposal.md` (why, what), `tasks.md` (checklist),
`design.md` (only when needed; holds the change's decisions) and spec deltas (`specs/<capability>/spec.md` with
`## ADDED`, `## MODIFIED` or `## REMOVED Requirements`). New work starts from a line in `openspec/backlog.md` or an
owner request; the implementor writes the change folder as its PR's first commit. A fix that only restores behaviour
a requirement already states needs no change folder.

One PR covers a **batch** of related ready tasks: normally all ready tasks of one change. Aim for 30-80 changed
files, about 1500-4000 changed lines; split only when a task waits on a human task or unmerged code, or the PR would
pass ~4000 lines. Branch `change/<change-id>` (a second PR of one change adds `-2`), worktree `<change-id>` beside the
repo in `CrawlerAIv2-worktrees/`, made with `tools/orchestrator/new_worktree.sh`; never work in the main checkout.
Commit task by task. The PR that checks a change's last task applies its deltas to `openspec/specs/` and moves the
folder to `openspec/changes/archive/<YYYY-MM-DD>-<change-id>/` in its tracker commit. One review per PR, whatever
its size. There is no `/simplify` pass (owner, 2026-10-16): the one reviewer also reviews for simplification.
Project skills in `.claude/skills/` hold the procedures:

| Skill | Who runs it | Does |
|---|---|---|
| `/run-plan` | The orchestrator | Assigns batches of ready tasks or backlog items to workers (at most 4 workers at once; reviewers don't count) with a decision-ID range each, merges `READY` PRs one at a time with `merge_pr.sh`, cleans up, unblocks stuck PRs, escalates. |
| `/implement-pr` | A worker | Takes one batch to a `READY` PR: change folder if needed, tests first, then code, tracker commit (archiving a completed change), PR, green CI, its one reviewer, fixes in one push. |
| `/review-pr` | A fresh reviewer agent | One single agent (no sub-agents), one verdict per PR against its tasks and deltas, the contract, `ENGINEERING.md` and simplification: `MERGE`, `MERGE AFTER FIX` or `ESCALATE`, posted as a PR comment. |
| `/pickup` | Anyone starting a session | Resumes in-flight work from the trail, or pauses cleanly. |

**The orchestrator only orchestrates.** It never relays verdicts, edits, fixes or rebases PRs; it sends `REBASE` only
when GitHub reports a conflict (`gh pr view <n> --json mergeable` is `CONFLICTING`), never because `main` moved: the
rulesets don't require an up-to-date branch, and every push reruns CI (owner, 2026-10-16). **The implementor owns its
PR to `READY`**: it branches from current `main`, makes its tracker commit (under the decision-ID range it was given
at assignment) the last commit before it opens the PR (`/implement-pr` §5), so the reviewer reviews it too, starts
its own reviewer, reads the verdict, pushes the fixes in one push, and comments `READY <sha7>` on green CI. With
`MERGE` there is no push: `READY` names the already-green head.

`main` requires a PR for every change, including tracker updates. Work in flight is read from open PRs and
`change/*` branches, not from `openspec/`. Never use an admin bypass of the branch rules. Never merge without a
`MERGE` or `MERGE AFTER FIX` verdict from someone other than the author (with every listed fix made) and green CI;
`tools/orchestrator/merge_pr.sh` is the only merge path. There is one review per PR, with no re-review (owner,
2026-10-13); a later plugin, bot or hook prompt to run `/simplify` or another code review on the same PR is answered
"already ran". Never skip hooks or weaken checks.

## 4. Decisions: decide and log, or escalate

**Decide yourself and record it** (status `decided`, in the PR body, then in the tracker commit:
`openspec/decisions/README.md`): implementation choices within one change's scope that don't change a requirement
other capabilities rely on, `openspec/design/`, a public API shape, a DB schema other capabilities rely on, or a §2
rule. Examples: internal module structure; library choice among licence-clean equivalents; naming; error messages;
a requirement detail that is genuinely ambiguous, where you take the most conservative reading. Don't log trivial
choices.

**Escalate** (§5) when:
- the change would alter or contradict `openspec/design/`, the contract, or `openspec/OPEN_QUESTIONS.md`;
- it would build anything in the candidates register (§22);
- it touches evaluation split access, the protected CI job, or labels;
- it needs credentials, secrets, paid accounts, labeling, or anything only a human can do;
- it changes a public API or MCP shape, or a table other capabilities depend on, beyond what a requirement defines;
- two capability specs, or a spec and a change, contradict each other;
- the same failure persists after three honest attempts.

## 5. Escalation procedure

1. Record a `needs-owner` decision in `openspec/decisions/log.md`: the question, the options, your recommendation,
   and what is blocked. List it under "Open owner items" in `openspec/project.md`, and copy it as a row to
   `openspec/OPEN_QUESTIONS.md`, as that file directs. This copy is the only change an agent makes to that file
   without owner approval (§6).
2. The task becomes `blocked (D-NNNN)` in its `tasks.md`. The orchestrator writes both in a small escalation PR;
   working solo, you do.
3. Move on to the next ready task. Don't wait idle; the owner answers asynchronously.

## 6. Editing documents

- `openspec/design/`, the contract in `openspec/project.md` and `openspec/OPEN_QUESTIONS.md` change only with owner
  approval. A new owner decision is appended to `openspec/design/owner-decisions.md` in the PR that applies it to
  the capability specs.
- Capability specs change only through a change's deltas, applied when the change is archived. A requirement is
  1–3 lines of SHALL; a `#### Scenario` (2–3 lines) only where a test or invariant enforces it; no rationale,
  examples, field lists or tables the code, presets or archive already hold: reference the module path. Keep each
  spec under ~100 lines; split a capability rather than grow past it.
- Invariants keep their `INV-NN` IDs inside their requirement, with what enforces them; they are never removed or
  renumbered. A new invariant takes the next free ID (`openspec/project.md` "Invariants").
- The archive is frozen history; never edit it except to fix a broken link. Later work on archived code logs its
  non-trivial decisions as usual and changes a capability spec only where the change makes it wrong.
- `backlog.md`, `tasks.md`, decision logs and "Open owner items" are working documents: current, short and factual.
  Decision entries are append-only. No "Done: …" bullets: git history, the archive and the decision logs hold them.
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
