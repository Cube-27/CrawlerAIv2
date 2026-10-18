# Evaluation Specification

## Purpose

Measuring extraction quality on the golden set, the one eval split (`dev`), grown in fresh batches scored once before
any change is made on them: two-pass labels and draft label import, a replay harness, metrics, and fitting on the
golden set. Rationale: owner decision #67 (master improvement plan, 2026-10-18), ARCHITECTURE §16
([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-03. Storage is in
[persistence-storage](../persistence-storage/spec.md); the labeling screen in [frontend](../frontend/spec.md).

## Requirements

### Requirement: One split, grown in fresh batches
The system SHALL keep one eval split, `dev` (the golden set; eval tables carry `CHECK split = 'dev'`). A new batch
(20–30 pages, one page per host not yet in dev) SHALL be imported into a database of its own and scored once with
`eval run` before any change is made on it; that first score is the only number a generalization claim may cite,
and the batch then joins dev. Refs: owner (2026-10-18, master plan decision 2).

### Requirement: Labels and two-pass labeling
Labels SHALL follow the label document validated in `crawlerai.eval` (every field labeled on a `labeled` or `checked`
page, absence explicit, distractors optional); only `checked` pages count, and a checker MUST differ from the labeler
(DB CHECK). An LLM may pre-fill a draft but is never ground truth. Refs: §16.2, D-0168, D-0175, D-0209.
#### Scenario: Self-check refused
- **WHEN** the labeler submits the checker pass under their own name
- **THEN** the write is refused and the page stays `labeled`

### Requirement: Labeling API and eval capture
With `CRAWLERAI_EVAL_UI=true` the API SHALL mount `/v1/eval/*` for the `dev` split, API key and ETag guarded,
serving sanitized HTML. `crawlerai eval capture`/`import-sites` fetch through acquisition, obey robots.txt and store
every page whatever its outcome. (Previously: site moves copy then delete.) Refs: §16.1, §16.2, D-0207, D-0222.

### Requirement: Replay harness and metrics
`replay_page` SHALL be the function the worker calls; `RecordedLLM` keys responses by a hash of the canonical prompt
and replays hits; a page with a missing recording or bundle is dropped, unless a dev run answers misses with no
provider or a capped live one (D-1464). Metrics are the TP/FP/FN/WP counts and rates computed in `crawlerai.eval`,
with `wrong_product` a published labeled distractor, values compared by type equality, long_text by word overlap
of at least 0.9 (D-1462), image_url by the file it names (D-1484) and a place labeled by its text only by that text
(D-1487), in `crawlerai.eval.scoring`; the dev report adds per page kind cells and per-field disagreement counts
(D-1463). Refs: §16.3, §16.4, D-0180, D-0215.
#### Scenario: Renditions of one image
- **WHEN** an image_url output and its label differ only in scheme and query
- **THEN** the output is TP; another path or host is FP

### Requirement: Draft label import and the draft dev report
`crawlerai eval import-labels <file> --split dev --status draft` SHALL capture each page of a label file (JSON
`{"pages": [{url, schema, category, page_kind?, fields?, rows?, notes?}]}`, values as the type's normalizer reads
them; details in `crawlerai.eval.label_file`) into dev through the worker's acquisition path, one page at a time, and
store its values normalized as a `draft` label naming no labeler; values the normalizer declines stay unlabeled and
are reported by path, never by value. `crawlerai eval run --split dev --labels all` SHALL score drafts too, their
unlabeled fields unscored, and never store such a run. `eval run` SHALL report listing rows bounded to the labeled
page (an unmatched engine row counts as FP only among the first as many engine rows as the label has rows) and write
the report over every row beside it; a stored run keeps every row. (Previously: after the one-split host check.)
Refs: D-1460, D-1461, D-1480.
#### Scenario: Rows of further pages
- **WHEN** a listing's label holds n rows and the engine published them first, then rows of further pages
- **THEN** the bounded report has precision 1.0 and the all-rows report counts the further rows as FP

### Requirement: Golden-set report in the PR
A PR that changes extraction behaviour SHALL put the golden-set aggregate per field type, before and after, in its
description's evaluation section, with no per-page or per-site numbers; precision drops on a field type only with a
stated reason. Enforced by: the PR template; review.

### Requirement: Fitting on the golden set
`eval calibrate` and `eval fit-precedence` SHALL fit on a stored dev run and stamp what they write `source_split: dev`.
Refs: owner (2026-10-18, master plan decision 10).

### Requirement: Claims before and after milestone M
Until calibration is fitted confidence SHALL be `calibrated=false` and precedence and drift margins their defaults;
improvement claims come only from golden-set results (a change's dev delta, a fresh batch's first score), and no
doc, PR or UI claims accuracy beyond them. (Previously: improvement claims from fresh results, a hidden drop a
regression.) Refs: owner (2026-10-18, master plan decision 2).

### Requirement: Retired evaluation invariants (INV-01, INV-02, INV-04, INV-19, INV-21, INV-25)
INV-01 (private store), INV-02 (fitting on dev only), INV-04 (hidden-host scan), INV-19 (protected CI job), INV-21
(merge gate) and INV-25 (complementary suppression) SHALL NOT apply: retired with the hidden and fresh splits (owner,
2026-10-18, master plan decision 2). Enforced by: nothing; retired.
