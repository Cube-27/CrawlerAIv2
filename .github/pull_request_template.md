<!-- One-minute briefing. Rules: CLAUDE.md §2 and CONTRIBUTING.md. -->

## Why

<!-- 1–3 sentences. Link the spec rows: docs/specs/SPEC-NN-*.md §8, PRs A-B. -->

## What changed

-

## Scope

<!-- What this PR covers, and what it deliberately leaves out. -->

## Verification

<!-- Real commands and their outcomes. Map each acceptance criterion of the row to the test or command that proves it. -->

## Evaluation report

<!--
Required if this PR changes anything under backend/src/crawlerai/ collect/, normalize/, resolve/, llm/, config_ir/
or acquire/ (C10, INV-19). Otherwise write "Not applicable".
- Dev delta per field type: from the `backend` job's dev report (the full report).
- Hidden: pass/fail per field type only, from the `eval-protected` job comment. Never numbers.
- Improvement claims come from fresh results only, never from hidden. Until milestone M the gate reports
  `no_baseline`, and acceptance rests on tests, replays and review.
-->

## Decisions

<!-- The ID of each decision the tracker commit logs, with its status (`decided` or `needs-owner`); or "None". -->

## Checklist

- [ ] I did not add a site literal: no hostname, site, brand or retailer name, or string copied from a page outside `backend/src/crawlerai/adapters/` (C3). Adding a commercial site, retailer or job board to `tools/site_literal_allowlist.txt` is a C3 violation.
- [ ] I did not add a list entry, word, selector or regex for a single page (C4, C5).
- [ ] No §22 candidate implemented (C13).
- [ ] Aggregate report attached, if `collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/` or `acquire/` changed: dev delta shown, hidden gate passed, no improvement claimed from hidden (C10).
- [ ] Property or replay tests added; no test is named after a site or asserts one site's output (C9).
- [ ] Decisions listed above, and added to the decisions log (`docs/DECISIONS.md`, "Where an entry goes") in the tracker commit.
