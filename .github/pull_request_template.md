<!-- One-minute briefing. Rules: CLAUDE.md §2 and CONTRIBUTING.md. -->

## Why

<!-- 1–3 sentences. Link the change and its tasks: openspec/changes/<change-id>/proposal.md, tasks A-B. -->

## What changed

-

## Scope

<!-- What this PR covers, and what it deliberately leaves out. -->

## Verification

<!-- Real commands and their outcomes. Map each task and each scenario of the spec deltas to the test or command that proves it. -->

## Evaluation report

<!--
Required if this PR changes anything under backend/src/crawlerai/ collect/, normalize/, resolve/, llm/, config_ir/
or acquire/ (C10). Otherwise write "Not applicable".
- Golden-set aggregate per field type, before and after (`crawlerai eval run --split dev --labels all`): precision,
  coverage and n. No per-page or per-site numbers, hosts or URLs.
- A precision drop on any field type needs a stated reason (a scoring fix, a label correction).
- A claim that the engine generalizes cites a fresh batch's first score only.
-->

## Decisions

<!-- The ID of each decision the tracker commit logs, with its status (`decided` or `needs-owner`); or "None". -->

## Checklist

- [ ] I did not add a site literal: no hostname, site, brand or retailer name, or string copied from a page outside `backend/src/crawlerai/adapters/` (C3). Adding a commercial site, retailer or job board to `tools/site_literal_allowlist.txt` is a C3 violation.
- [ ] I did not add a list entry, word, selector or regex for a single page (C4, C5).
- [ ] No §22 candidate implemented (C13).
- [ ] Aggregate report attached, if `collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/` or `acquire/` changed: golden-set delta per field type shown, no unexplained precision drop (C10).
- [ ] Property or replay tests added; no test is named after a site or asserts one site's output (C9).
- [ ] Behaviour changes have a spec delta in the change folder; if this PR completes the change, the deltas are applied to `openspec/specs/` and the change is archived.
- [ ] Decisions listed above, and logged in the tracker commit (`openspec/decisions/README.md`, "Where an entry goes").
