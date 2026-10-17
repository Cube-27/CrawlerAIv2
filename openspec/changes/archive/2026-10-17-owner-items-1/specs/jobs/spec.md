## MODIFIED Requirements

### Requirement: Conditional GET and content fingerprint
Only records tasks of `batch_scrape` and `extract` SHALL use `url_state`, and only with a standing record: the HTTP rung
sends stored validators, and a 304 or an equal content digest (BLAKE2b of the visible words, nonce-like tokens left out,
`recurring/simhash.py`; the SimHash stored beside it only reports how far a change moved) ends the task `unchanged`,
linking the standing records, with no extraction or LLM call. A detail page's standing record is the newest of its
entity; a listing page's are the latest versions of the entities the task named by `url_state.standing_task_id` stood
for, valid while that task extracted the page the way it would be now. Replay never reads `url_state` (INV-10).
(Previously: an equal SimHash, which let about 1 in 10 one-word edits pass, D-0915.) Refs: §14, D-0637, D-0662,
D-0663, D-0952, D-1283, D-1340.
#### Scenario: Unchanged listing
- **WHEN** a listing page whose text is unchanged is scraped again in a records batch
- **THEN** its task ends `unchanged` with no extraction, and the job lists the rows' records the first run stored
#### Scenario: One-word edit
- **WHEN** a page's visible text changes by one word and its SimHash stays equal
- **THEN** its content digest differs and the page is extracted again
