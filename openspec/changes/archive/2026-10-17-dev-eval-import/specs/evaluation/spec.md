## ADDED Requirements

### Requirement: Draft label import and the draft dev report
`crawlerai eval import-labels <file> --split dev --status draft` SHALL capture each page of a label file (JSON
`{"pages": [{url, schema, category, page_kind?, fields?, rows?, notes?}]}`, values as the type's normalizer reads
them; details in `crawlerai.eval.label_file`) into dev through the worker's acquisition path, one page at a time, after the
one-split host check, and store its values normalized as a `draft` label naming no labeler; values the normalizer
declines stay unlabeled and are reported by path, never by value. `crawlerai eval run --split dev --labels all`
SHALL score drafts too, their unlabeled fields unscored, and never store such a run. Refs: D-1460, D-1461.
#### Scenario: Drafts on a private split
- **WHEN** `build_report` or `replay_split` is asked for drafts on `hidden` or `fresh`
- **THEN** it raises `ValueError`

## MODIFIED Requirements

### Requirement: Replay harness and metrics
`replay_page` SHALL be the function the worker calls; `RecordedLLM` keys responses by a hash of the canonical prompt
and replays hits; a page with a missing recording or bundle is dropped, unless a dev run answers misses with no
provider or a capped live one (D-1464). Metrics are the TP/FP/FN/WP counts and rates computed in `crawlerai.eval`,
with `wrong_product` a published labeled distractor, values compared by type equality and long_text by word overlap
of at least 0.9 (D-1462); the dev report adds per page kind cells and per-field disagreement counts (D-1463).
Refs: §16.3, §16.4, D-0180, D-0215.
(Previously: no exception for dev misses; long_text compared by equality; no page kind or disagreement cells.)
