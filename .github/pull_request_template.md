<!-- One-minute briefing. Rules: CLAUDE.md. -->

## Why

<!-- 1–3 sentences. -->

## What changed

-

## Verification

<!-- Runtime grounding (what ran on which kind of page, and what came out), the verify-* skills run, and any test
added or deleted. -->

## Evaluation report

<!-- Required if this PR changes backend/src/snowcrawl/ collect/, normalize/, resolve/, llm/, config_ir/ or acquire/
(C10); otherwise "Not applicable". One regression run on the final code: precision, coverage and n per field type,
before and after, plus wrong_product. No per-page or per-site numbers, hosts or URLs. A precision drop needs a stated
reason; a gain from fewer than 3 hosts is flagged. -->

## Decisions

<!-- Decisions made within this change's scope, one line each; or "None". Owner items go in the report, not here. -->

## Checklist

- [ ] No site literal (hostname, site, brand or retailer name, or page string) outside `backend/src/snowcrawl/adapters/` (C3).
- [ ] No list entry, word, selector or regex for a single page (C4, C5); no unadmitted candidate (C13).
- [ ] No test named after a site or asserting one site's output (C9); redundant tests deleted.
- [ ] `docs/` updated if the change makes them wrong.
