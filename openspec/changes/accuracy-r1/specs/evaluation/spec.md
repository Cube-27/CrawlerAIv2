## MODIFIED Requirements

### Requirement: Replay harness and metrics
`replay_page` SHALL be the function the worker calls; `RecordedLLM` keys responses by a hash of the canonical prompt
and replays hits; a page with a missing recording or bundle is dropped, unless a dev run answers misses with no
provider or a capped live one (D-1464). Metrics are the TP/FP/FN/WP counts and rates computed in `crawlerai.eval`,
with `wrong_product` a published labeled distractor, values compared by type equality, long_text by word overlap
of at least 0.9 (D-1462), image_url by the file it names (D-1484) and a place labeled by its text only by that text
(D-1487), in `crawlerai.eval.scoring`; the dev report adds per page kind cells and per-field disagreement counts
(D-1463). Refs: §16.3, §16.4, D-0180, D-0215.
(Previously: every type but long_text compared by type equality.)
#### Scenario: Renditions of one image
- **WHEN** an image_url output and its label differ only in scheme and query
- **THEN** the output is TP; another path or host is FP

### Requirement: Draft label import and the draft dev report
`crawlerai eval import-labels <file> --split dev --status draft` SHALL capture each page of a label file (JSON
`{"pages": [{url, schema, category, page_kind?, fields?, rows?, notes?}]}`, values as the type's normalizer reads
them; details in `crawlerai.eval.label_file`) into dev through the worker's acquisition path, one page at a time, after the
one-split host check, and store its values normalized as a `draft` label naming no labeler; values the normalizer
declines stay unlabeled and are reported by path, never by value. `crawlerai eval run --split dev --labels all`
SHALL score drafts too, their unlabeled fields unscored, and never store such a run. `eval run` SHALL report listing
rows bounded to the labeled page (an unmatched engine row counts as FP only among the first as many engine rows as
the label has rows) and write the report over every row beside it; a stored run keeps every row. Refs: D-1460,
D-1461, D-1480.
(Previously: `eval run` reported every engine row only.)
#### Scenario: Drafts on a private split
- **WHEN** `build_report` or `replay_split` is asked for drafts on `hidden` or `fresh`
- **THEN** it raises `ValueError`
#### Scenario: Rows of further pages
- **WHEN** a listing's label holds n rows and the engine published them first, then rows of further pages
- **THEN** the bounded report has precision 1.0 and the all-rows report counts the further rows as FP
