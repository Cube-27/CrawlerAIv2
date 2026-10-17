# Contributing

CrawlerAI v2 is built mostly by coding agents working from OpenSpec changes, and the same rules apply to every
contributor. Read `CLAUDE.md` before changing anything: the generalization contract C1–C13
(`openspec/project.md`, applied in `CLAUDE.md` §2) is binding on every change, and breaking it is a defect even when
it fixes a site.

## Before you start

- What is in progress and what is next: the change folders in `openspec/changes/` and `openspec/backlog.md`.
- The current behaviour, as requirements: `openspec/specs/<capability>/spec.md`, invariants (`INV-NN`) included.
- One PR covers a batch of related tasks of one change (`openspec/changes/<change-id>/tasks.md`): one branch, one PR
  (`CLAUDE.md` §3). New work starts as a change folder (proposal, tasks, spec deltas); a PR that completes a change
  applies its deltas to `openspec/specs/` and archives it.
- How to write code here: `openspec/conventions/ENGINEERING.md`. Frontend conventions:
  `openspec/conventions/DESIGN.md`.

## Setup and checks

Setup is in `README.md`, and every command, including the checks CI runs, is in `CLAUDE.md` §7. Run the checks
for the parts you changed before you open a PR. CI runs all of them on every PR, and every job must pass before
merge.

C11 allows two size checks and no others. Cognitive complexity is at most 15 per function, and CI fails above
it. A source file over 800 lines gets a warning, never a failure: split it by meaning, not to meet the number.
No other line-count, complexity, coverage-percentage or ratchet gate may be added. The `no-size-gates` CI job
fails if one appears in a workflow, a hook or a tool config.

## Pull requests

- Title in Conventional Commits form: `type(scope): subject`, for example
  `feat(normalize): decline ambiguous dollar symbols`.
- Fill in `.github/pull_request_template.md`: why, what changed, scope, verification, the evaluation report and
  decisions. Behaviour changes come with a spec delta in the change folder.
- Tests come first: behaviour tests, Hypothesis properties for normalizers, replays of stored captures for
  extraction. No test is named after a site or asserts one site's output (C9). Fixtures are synthetic and use
  reserved names (`example.com`, `.test`).
- Merge needs green CI, and for a PR over 10 files the `claude-review` workflow's review (comment `/claude-review`)
  with every finding fixed or answered. Hooks and checks are never skipped or weakened.

### Checklist

Every PR answers these (the template carries them):
- I did not add a site literal (C3). Adding a commercial site, retailer or job board to
  `tools/site_literal_allowlist.txt` is a C3 violation.
- I did not add a list entry for a single page (C4, C5).
- No §22 candidate implemented (C13).
- Aggregate report attached, required if `collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/` or `acquire/`
  changed: dev delta shown, hidden gate passed, no improvement claimed from hidden (C10).
- Property or replay tests added, no site-named tests (C9).
- Decisions recorded in the change's `design.md` or `openspec/decisions/log.md` (`openspec/decisions/README.md`).

### Where the evaluation report comes from

- **Dev:** the full dev report from the `backend` CI job's replay of dev captures. Paste the delta per field type.
- **Hidden:** the `eval-protected` job's comment: pass or fail per field type, never numbers. Numeric hidden
  aggregates go only to the custodian.
- **Improvement claims** come only from fresh results, never from hidden (C10).

Until milestone M (ARCHITECTURE §21) there are no labels: the protected job reports `no_baseline`, and acceptance
rests on tests, replays and review. The `evaluation` capability (`openspec/specs/evaluation/spec.md`) defines the
replay and the reports.

## Decisions and escalation

Implementation choices within a change's scope are decided and logged (the change's `design.md` or
`openspec/decisions/log.md`; listed in the PR body under `## Decisions`). Changes to `openspec/design/` (the
former ARCHITECTURE.md), the contract or `openspec/OPEN_QUESTIONS.md`, §22 candidates, evaluation access and secrets
are escalated to the owner. `CLAUDE.md` §4–§5 has the procedure.

## Licensing and the public repo

The project is AGPL-3.0 (`LICENSE`). The dependency-license deny-list, the ban on anything from the earlier projects
(C12) and what may never be committed to this public repo are in `CLAUDE.md` §2.
