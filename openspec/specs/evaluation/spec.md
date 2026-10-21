# Evaluation Specification

## Purpose

How extraction quality is measured: one end-to-end (e2e) run of the product over one eval set kept outside the
repository, scored by one scorer, its disagreements adjudicated against what the run captured. The repository holds
no eval set, labels, scorer, captures or per-page results (C3). The engine's fitted data files are frozen inputs, not
outputs of this procedure.

## Requirements

### Requirement: One eval set, outside the repository
There SHALL be one eval set: a list of pages, each naming its schema, its URL and the values the page states (fields
for a detail page, rows for a listing, and a listing's next-page URL when it has one). It lives outside the repository
with the scorer and is never committed, nor are its URLs, values or captures (C3). Pages are referred to by their
number in the set, never by site.
#### Scenario: A page enters the repository
- **WHEN** a change, test or document would carry an eval page's URL, host or stated value
- **THEN** it is refused in review (C3)

### Requirement: Fresh batches and the first score
The set SHALL grow in fresh batches of pages on hosts not in it before. A batch is scored once, in the first e2e run
that reads it and before any change is made for it; that first score is the only number a generalization claim may
cite (C1). The batch then joins the set.

### Requirement: One run per round
A round SHALL be one e2e run on the round's final code: a fresh database, the product's own API (the requests a user
sends, the LLM enabled under a stated call budget), every page of the set, its captures and results kept with the set.
A round has one run, and its score is the round's; nothing is tuned between runs to move it.

### Requirement: One scorer
One scorer SHALL compare a run with the set: per field (per row field for a listing) a verdict of `agree`,
`disagree`, the engine's value only, or the set's value only; per page an outcome (`ok`, `partial`, no match, blocked,
error). It compares values by the field type's equality (normalization spec). The report gives aggregates per field
type and per outcome; the page-by-page comparison with the previous round stays with the set.

### Requirement: Adjudication against the capture
Every `disagree` and every value only one side has SHALL be adjudicated against the run's capture of the page: which
value the page states. A wrong expected value is corrected in the set, not counted against the engine. A value the
engine published that the page does not state is counted on its own (for an LLM value, a grounding failure, llm spec).
A regression is a page whose outcome or adjudicated value is worse than in the previous round.
#### Scenario: The set was wrong
- **WHEN** a disagreement's capture states the engine's value and not the set's
- **THEN** the set's value is corrected and the field counts as `agree` from that round on

### Requirement: The report in a PR
A PR that changes extraction SHALL report, from one run on its final code, the aggregates per field type before and
after (precision, coverage and n, plus wrong-product), with no per-page or per-site numbers, hosts or URLs; a
precision drop needs a stated reason and a gain from fewer than 3 hosts is flagged (C10). Enforced by: the PR
template; review.

### Requirement: Frozen fitted data
`backend/data/calibration.json`, `source_precedence.yaml` and `drift_margins.json` SHALL be read as engine data
(extraction spec, resolution spec) and stay as fitted on 2026-10-18; no code in the repository refits them, and a
refit needs the owner. Confidence is `calibrated=true` only for the buckets `calibration.json` holds, and no doc, PR
or UI claims accuracy beyond the e2e results. Refs: owner (2026-10-21).
