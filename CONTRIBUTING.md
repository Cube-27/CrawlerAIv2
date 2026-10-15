# Contributing

CrawlerAI v2 is built mostly by coding agents working from the specs, and the same rules apply to every
contributor. Read `CLAUDE.md` before changing anything: its §2 (the generalization contract, ARCHITECTURE §2) is
binding on every change, and breaking it is a defect even when it fixes a site.

## Before you start

- What is in progress and what is next: `docs/plans/ACTIVE.md`.
- One PR covers a batch of related rows of a spec's PR plan (`docs/specs/`): one branch, one PR (`CLAUDE.md` §3).
- How to write code here: `docs/ENGINEERING.md`. The invariants your change must keep: `docs/INVARIANTS.md`.
  Frontend conventions: `docs/DESIGN.md`.

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
  decisions.
- Tests come first: behaviour tests, Hypothesis properties for normalizers, replays of stored captures for
  extraction. No test is named after a site or asserts one site's output (C9). Fixtures are synthetic and use
  reserved names (`example.com`, `.test`).
- Merge needs a `MERGE` review verdict from someone other than the author and green CI. Hooks and checks are
  never skipped or weakened.

### Checklist

Every PR answers these (the template carries them):
- I did not add a site literal (C3). Adding a commercial site, retailer or job board to
  `tools/site_literal_allowlist.txt` is a C3 violation.
- I did not add a list entry for a single page (C4, C5).
- No §22 candidate implemented (C13).
- Aggregate report attached, required if `collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/` or `acquire/`
  changed: dev delta shown, hidden gate passed, no improvement claimed from hidden (C10).
- Property or replay tests added, no site-named tests (C9).
- Decisions recorded in `docs/DECISIONS.md`.

### Where the evaluation report comes from

- **Dev:** the full dev report from the `backend` CI job's replay of dev captures. Paste the delta per field type.
- **Hidden:** the `eval-protected` job's comment: pass or fail per field type, never numbers. Numeric hidden
  aggregates go only to the custodian.
- **Improvement claims** come only from fresh results, never from hidden (C10).

Until milestone M (ARCHITECTURE §21) there are no labels: the protected job reports `no_baseline`, and acceptance
rests on tests, replays and review. SPEC-03 builds the replay and the reports.

## Decisions and escalation

Implementation choices within a spec's scope are decided and logged in `docs/DECISIONS.md` (or in the PR body
under `## Decisions` while an orchestrator runs). Changes to `docs/ARCHITECTURE.md` or `docs/OPEN_QUESTIONS.md`,
§22 candidates, evaluation access and secrets are escalated to the owner. `CLAUDE.md` §4–§5 has the procedure.

## Licensing and the public repo

The project is AGPL-3.0 (`LICENSE`). The dependency-license deny-list, the ban on anything from the earlier projects
(C12) and what may never be committed to this public repo are in `CLAUDE.md` §2.
