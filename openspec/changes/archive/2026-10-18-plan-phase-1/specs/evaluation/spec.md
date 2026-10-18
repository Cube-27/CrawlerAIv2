## MODIFIED Requirements

### Requirement: Draft label import and the draft dev report
`crawlerai eval import-labels <file> --split dev --status draft` SHALL capture each page of a label file (JSON
`{"pages": [{url, schema, category, page_kind?, fields?, rows?, notes?}]}`, values as the type's normalizer reads
them; details in `crawlerai.eval.label_file`) into dev through the worker's acquisition path, one page at a time, a
page not reached fetched again up to 3 times in all after the back-off (`politeness.backoff`) with the best capture
kept (`ok`, then `shell`, `blocked`, `not_found`, `error`), and store its values normalized as a `draft` label naming
no labeler; values the normalizer declines stay unlabeled and are reported by path, never by value. `crawlerai eval
run --split dev --labels all` SHALL score drafts too, their unlabeled fields unscored, and never store such a run.
`eval run` SHALL report listing rows bounded to the labeled page (an unmatched engine row counts as FP only among the
first as many engine rows as the label has rows) and write the report over every row beside it; a stored run keeps
every row. (Previously: one fetch per page.) Refs: D-1460, D-1461, D-1480.
#### Scenario: Rows of further pages
- **WHEN** a listing's label holds n rows and the engine published them first, then rows of further pages
- **THEN** the bounded report has precision 1.0 and the all-rows report counts the further rows as FP
#### Scenario: Flaky page at import
- **WHEN** a page answers `blocked` at its first fetch and `ok` at its second
- **THEN** the `ok` capture is stored and the page is fetched no third time
