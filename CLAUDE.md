# CLAUDE.md — rules for agents working in this repo

CrawlerAI v2 is a schema-driven web extraction engine; see `README.md`. Coding agents implement it, mostly
autonomously, from the specs. The owner is involved only for the escalations listed below. Read this file fully
before doing anything.

## 1. Read order

1. `docs/plans/ACTIVE.md`: what is in progress, what is next, what is blocked.
2. The spec for your work in `docs/specs/`: its design, invariants, acceptance criteria, and your PR's row in the
   PR plan.
3. The `docs/ARCHITECTURE.md` sections that spec cites. **§2 (generalization contract C1–C13) is binding on every
   change.** Read it once per session.
4. `docs/DECISIONS.md`: earlier decisions you must stay consistent with.
5. `docs/ENGINEERING.md`: how to write code here (verification, tests, structure). Read it once per session.

`ARCHITECTURE.md` is the single source of truth. Where a spec and the architecture disagree, stop and escalate
(§5).

## 2. Hard rules

These come from the generalization contract. Breaking one is a defect, even when it fixes a site.

- **Never touch hidden or fresh evaluation data (C1).** Don't request or use custodian credentials
  (`CRAWLERAI_EVAL_PRIVATE_*`), and don't try to read the private eval database or object root. Work only with
  the aggregate pass/fail the protected CI job reports, and never try to infer individual hidden cases from it.
- **No site literals in generic code (C3).** Hostnames, retailer and brand names, and strings copied from real
  pages are allowed only under `backend/src/crawlerai/adapters/` and in database rows. Test fixtures are
  synthetic and use RFC 2606 names (`example.com`, `.test`).
- **No lists that grow one incident at a time (C4).** Vocabularies come from versioned external data listed in
  `backend/data/manifest.json`.
- **Fix sites with data, not code (C5).** If one site fails, the fix is a config, a learning re-run or an operator
  correction. Change generic code only for a *class* of failures, and show the class with dev results.
- **Normalizers decline rather than guess (C7).** No defaults, no host tables, no values taken from URL codes.
- **One module per field type (C8).**
- **Tests check type properties and replays (C9).** No test is named after a site or asserts one site's output.
- **Gate (C10).** A change must improve dev and must not regress hidden. Claim improvements only from fresh
  results.
- **No size gates (C11).** Don't split files to satisfy line counts, and don't add LOC or complexity ratchets.
- **Nothing from the earlier versions (C12).** Don't read, copy or port code, lists, config, tests or prompts from
  the sibling `Invoro` or `CrawlerAI` (v1) projects. When a §22 candidate is admitted, its design may *read* them,
  as ARCHITECTURE §20 allows, but nothing is copied.
- **Build only core (C13).** Anything in ARCHITECTURE §22 is not built until the owner admits it based on
  evidence. If you think a candidate is needed, log the evidence in `DECISIONS.md` as `needs-owner`.
- **Never `exec` or `eval` LLM output.** Generated selectors, recipes and schemas are data run by our
  interpreters.
- **Public repo.** No customer, prospect or company names (except as adapter platform names), no business terms,
  no secrets, no captures, no evaluation data. Commit only synthetic fixtures.
- **Dependency licenses.** Don't add dependencies under AGPL, GPL, SSPL or non-commercial licenses. LGPL is
  allowed but avoided. CI enforces this.

## 3. How work runs

One unit is **one row of a spec's PR plan**: one branch, one worktree, one PR. Project skills in `.claude/skills/`
hold the procedures:

| Skill | Who runs it | Does |
|---|---|---|
| `/run-plan` | The orchestrator | Assigns ready rows to workers (max 3 worktrees, 8 agents), merges one at a time, reviews, merges on green CI, keeps the tracker and log current, escalates. |
| `/implement-pr` | A worker | Takes one row from `todo` to an open, verified PR: tests first, then code, self-review, PR body. |
| `/review-pr` | A fresh reviewer agent | Verdict against the spec row, §2 and `docs/ENGINEERING.md`: `MERGE`, `FIX` or `ESCALATE`. |
| `/pickup` | Anyone starting a session | Resumes in-flight rows from the trail, or pauses cleanly. |

**Shared files have one writer.** With an orchestrator running, only the orchestrator edits `ACTIVE.md` and
`DECISIONS.md`. Workers put their decisions in the PR body (`## Decisions`), and the orchestrator copies them
across on merge. A solo agent with no orchestrator updates both files itself, in its PR.

`main` requires a PR for every change, including tracker updates. Work in flight is read from open PRs and
`spec-*` branches, not from ACTIVE.md. Never use an admin bypass of the branch rules. Never merge without a `MERGE`
verdict from someone other than the author and green CI. Never skip hooks or weaken checks.

## 4. Decisions: decide and log, or escalate

**Decide yourself and record it** (status `decided`, through the PR body or `DECISIONS.md` per §3): implementation choices within one spec's
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

1. Record a `needs-owner` decision: the question, the options, your recommendation, and what is blocked.
2. The row becomes `blocked`, linked to the `DECISIONS.md` entry. The orchestrator writes both; working solo, you
   do.
3. Move on to the next ready row. Don't wait idle; the owner answers asynchronously.

## 6. Editing documents

- `ARCHITECTURE.md` and `OPEN_QUESTIONS.md` change only with owner approval. When approved, update the revision
  log, and keep the specs consistent in the same change.
- Specs may get clarifying edits that don't change the architecture. Log those in DECISIONS.md.
- `ACTIVE.md` and `DECISIONS.md` are working documents. Keep them current, short and factual.
- Write plainly. No marketing language, and no claims that aren't backed by a test or eval result.

## 7. Commands

SPEC-00 adds the real commands here. Until then, there is nothing to run.
