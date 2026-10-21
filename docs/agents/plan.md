# Handover plan

The last plan before handover (owner-approved 2026-10-21): close open items, fix major bugs as classes, reduce test
debt, finish the one-home-per-concept refactors, update the docs. One builder per PR; `orchestrator.md` runs it. The
specs and `openspec/design/architecture-v3.md` govern; this file only orders the work. The orchestrator updates the
status table when it opens or merges a PR. Item ids in brackets (A6, B9, C1) name findings of the 2026-10-21 audit,
kept outside the repo with the eval reports.

Rules for every PR: one slice (sizes are estimates, not gates; C11), deletes what it supersedes, spec delta in the
same PR, tests for removed code deleted, green CI, bot threads resolved. Sizes: S < 300, M 300–1k, L 1–3k lines.

## Status

| Plan PR | What | GitHub PR | State |
|---|---|---|---|
| D1 | Delete the in-repo golden-set machinery | #397 | merged |
| D2 | Delete dead runtime paths | #396 | merged |
| D3 | Repo hygiene deletions | #398 | merged |
| A1 | One cookie rule; the profile is the browser's cookie store | #403 | merged |
| A2 | Listing renders through the shared browser | #405 | merged |
| A3 | Site memory in its own short transactions | #400 | merged |
| A4 | One page run for scrape and the worker | #409 | merged |
| A5 | Decode and fingerprint a body once | #410 | merged |
| B1 | One document key, one item key | #399 | merged |
| B2 | One page-locale derivation | #401 | merged |
| B3 | Variant rows keep their stated amount | #402 | merged |
| B4 | One text module | #404 | merged |
| B5 | Image policy in one module; cached canonical | #408 | merged |
| E1 | Mid-point e2e (orchestrator) | | done: one engine regression (#404) |
| E1-fix | A text equal but for white space is no cut | #411 | merged |
| T1 | DB tests: one engine per worker, shared fixtures | #413 | merged |
| T2 | Slow tests trimmed, pairs merged | #412 | merged |
| T3 | Path-gated sdk job; aligned pins | #419 | merged |
| F1 | An extraction miss is `partial`, never `no_match` | #415 | merged |
| F2 | The canonical link is the page-URL field's stated value | #416 | merged |
| F3 | A site summary is not the description; a legend is not prose | #417 | merged |
| F4 | A single stated image never fills an image list; gallery slides | #420 | merged |
| F5 | Inline-state rating and count the page text shows | | closed: no bug class (values only client-side) |
| F6 | Unknown `?variant=` selects the default variant; struck amount | #421 | merged |
| X1 | architecture-v3 rewritten in place | #422 | merged |
| X1-fu | Spec text: timeout fallback, rejected-reason storage | #423 | merged |
| X2 | README, CONTRIBUTING, CLAUDE.md, HANDOVER.md | #425 | merged |
| E2 | Final e2e (orchestrator) | | done: two engine regressions, fixed below |
| E2-fix 1 | The selected variant's ids don't override the page's | #424 | merged |
| E2-fix 2 | A platform image list holds only the shown variant's images | #426 | merged |

## Owner decisions for this plan (binding)

- Page URL: when `<link rel=canonical>` and og:url or JSON-LD `url` disagree, the canonical wins (F2).
- Lever `createdAt` is not mapped (documented members only).
- `ng-cloak`/`v-cloak`/`x-cloak` content over HTTP: no change; the page stays `partial` with the render hint.
- Review widgets loaded client-side count as "render needed"; no engine change; HANDOVER states it.
- Not reopened: one cookie rule with clearance cookies kept; a visible page price applies only to a single-offer page;
  the structured name is published; class fixes only; no value reuse; HTTP-first; no proxies, no paid CAPTCHA.

## Remaining PRs

None: every plan PR is merged. Open items and owner decisions are in `HANDOVER.md`.

## Not done, and why

Moved to `HANDOVER.md` ("Not done, and why" and "Open items").
