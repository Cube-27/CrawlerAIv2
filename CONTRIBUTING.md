# Contributing

CrawlerAI v2 is built mostly by coding agents, and the same rules apply to every
contributor. Read `CLAUDE.md` before changing anything: the generalization contract C1–C13
(`docs/rules.md`, applied in `CLAUDE.md`) is binding on every change, and breaking it is a defect even when
it fixes a site.

## Before you start

- What the code does: `docs/architecture.md`. The rules CI and agents enforce: `docs/rules.md`. Decisions in force: `docs/decisions.md`.
- One PR covers one concern: one branch, one PR (`CLAUDE.md`). The PR description carries the reasoning.

## Setup and checks

Setup is in `README.md`, and every command, including the checks CI runs, is in `CLAUDE.md`. Run the checks
for the parts you changed before you open a PR. CI runs all of them on every PR, and every job must pass before
merge.

C11 allows two size checks and no others. Cognitive complexity is at most 15 per function, and CI fails above
it. A source file over 800 lines gets a warning, never a failure: split it by meaning, not to meet the number.
No other line-count, complexity, coverage-percentage or ratchet gate may be added. The `no-size-gates` CI job
fails if one appears in a workflow, a hook or a tool config.

## Pull requests

- Title in Conventional Commits form: `type(scope): subject`, for example
  `feat(normalize): decline ambiguous dollar symbols`.
- Fill in `.github/pull_request_template.md`: why, what changed, scope, verification, the e2e report and
  decisions. `docs/` is updated if the change makes them wrong.
- Tests come first: behaviour tests, Hypothesis properties for normalizers, replays of stored captures for
  extraction. No test is named after a site or asserts one site's output (C9). Fixtures are synthetic and use
  reserved names (`example.com`, `.test`).
- Merge needs green CI and every review thread fixed or answered and resolved. Hooks and checks are never skipped
  or weakened.

### Checklist

Every PR answers these (the template carries them):
- I did not add a site literal (C3). Adding a commercial site, retailer or job board to
  `tools/site_literal_allowlist.txt` is a C3 violation.
- I did not add a list entry for a single page (C4, C5).
- No unadmitted candidate implemented (C13).
- Aggregate report attached, required if `collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/`, `acquire/` or
  `adapters/` changed: e2e delta per field type shown, no unexplained precision drop (C10).
- Property or replay tests added, no site-named tests (C9).
- Decisions recorded in the PR body.

### The e2e report

A PR that changes extraction reports one e2e run on its final code (C1, C10). Procedure:

1. Start from a fresh database (`docker compose down -v`, then `docker compose up`;
   without `-v` the existing data is kept), the API and one worker, with the LLM enabled under a stated call
   budget.
2. Send every page of the eval set, which lives outside the repo with its scorer, as a user would, through the API.
3. Score the run with the one scorer and adjudicate every disagreement against the run's capture: a wrong expected
   value is corrected in the set, not counted against the engine.
4. Paste the aggregate per field type (precision, coverage, n, wrong-product) before and after into the PR. Never
   per-page or per-site numbers, hosts or URLs; a precision drop needs a stated reason, and a gain from fewer than 3
   hosts is flagged.

Generalization claims come only from a fresh batch's first score, taken before any change is made on it.

## Decisions and escalation

Implementation choices within a change's scope are decided and listed in the PR body under `## Decisions`. Changes to the
contract (`docs/rules.md`), a public API, the evaluation procedure, candidates and secrets are escalated to the owner.
`CLAUDE.md` has the procedure.

## Licensing and the public repo

The project is AGPL-3.0 (`LICENSE`). The dependency-license deny-list, the ban on anything from the earlier projects
(C12) and what may never be committed to this public repo are in `CLAUDE.md`.
