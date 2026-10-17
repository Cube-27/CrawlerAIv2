# Evaluation Specification

## Purpose

Measuring extraction quality without overfitting: three splits with separate storage, two-pass labels, a replay
harness, suppressed aggregates, the merge gate, dev-only fitting and the protected CI job. Until milestone M the gate
reports `no_baseline`. Rationale: ARCHITECTURE §16, §21, Appendix A #29, #30
([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-03. Storage is in
[persistence-storage](../persistence-storage/spec.md); the labeling screen in [frontend](../frontend/spec.md).

## Requirements

### Requirement: Three splits
The system SHALL keep `dev` (visible, used for tuning and all fitting), `hidden` (custodian only, gate only, a third
rotated into dev each quarter) and `fresh` (custodian only, measured once for improvement claims, then promoted to
dev); a host's pages stay in one split, and hidden/fresh hosts are drawn from hosts development never touched.
Refs: §16.1, §21, D-0221, D-0225, D-0253.
#### Scenario: Host already in dev
- **WHEN** a fresh `import-sites` file lists a host that has dev pages
- **THEN** nothing is fetched and only per-split counts of conflicting hosts are reported

### Requirement: Hidden and fresh never leave the private store (INV-01)
No hidden or fresh URL, host, label or capture SHALL exist in the main DB, repo, logs or CI artifacts; main eval
tables carry `CHECK split = 'dev'`, and `get_store` refuses a private split without separate private settings.
Enforced by: separate DB and roles, split CHECKs, the protected job uploading no artifacts, the aggregate test; active
(log redaction test not built yet). Refs: C1, §15, D-0170, D-0177, D-0199, D-0202.
#### Scenario: Developer machine
- **WHEN** `get_store("hidden", settings)` runs with empty `CRAWLERAI_EVAL_PRIVATE_*` settings
- **THEN** it raises `PrivateCredentialsMissing`

### Requirement: Hidden-host scan (INV-04)
No hidden or fresh host SHALL appear anywhere in the repo: `site_literal_scan.py --hidden-hosts-from-env HIDDEN_HOSTS`
scans every tracked file with no exemption, prints only `path:line`, never a host, and passes when no list is set.
Enforced by: the scan in `eval-protected.yml`; active, host list from milestone M. Refs: C1, C3, D-0081, D-0109.
#### Scenario: Seeded hidden host
- **WHEN** `HIDDEN_HOSTS` holds `seeded.test` and a scratch file names `a.seeded.test`
- **THEN** the job log shows that file's `path:line` and never the host

### Requirement: Labels and two-pass labeling
Labels SHALL follow the label document validated in `crawlerai.eval` (every field labeled on a `labeled` or `checked`
page, absence explicit, distractors optional); only `checked` pages count, and a checker MUST differ from the labeler
(DB CHECK). An LLM may pre-fill a draft but is never ground truth. Refs: §16.2, D-0168, D-0175, D-0209.
#### Scenario: Self-check refused
- **WHEN** the labeler submits the checker pass under their own name
- **THEN** the write is refused and the page stays `labeled`

### Requirement: Labeling API and eval capture
With `CRAWLERAI_EVAL_UI=true` the API SHALL mount `/v1/eval/*` for the `dev` split only (422 otherwise), API key and
ETag guarded, serving sanitized HTML. `crawlerai eval capture`/`import-sites` fetch through acquisition, obey
robots.txt and store every page whatever its outcome; site moves copy then delete. Refs: §16.1, §16.2, D-0207, D-0222.

### Requirement: Replay harness and metrics
`replay_page` SHALL be the function the worker calls; `RecordedLLM` keys responses by a hash of the canonical prompt
and replays hits; a page with a missing recording or bundle is dropped, unless a dev run answers misses with no
provider or a capped live one (D-1464). Metrics are the TP/FP/FN/WP counts and rates computed in `crawlerai.eval`,
with `wrong_product` a published labeled distractor, values compared by type equality and long_text by word overlap
of at least 0.9 (D-1462); the dev report adds per page kind cells and per-field disagreement counts (D-1463).
Refs: §16.3, §16.4, D-0180, D-0215.

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

### Requirement: Aggregate report and minimum cells
A hidden or fresh aggregate SHALL contain no URL, host, label, value or per-page row; a cell below 10 shows only
`{"n": <n>}`. The dev report is the same schema plus per-page rows, unsuppressed. Refs: §16.3, D-0181, D-0184.

### Requirement: Complementary suppression (INV-25)
In a hidden or fresh aggregate no suppressed cell SHALL be recoverable by subtraction: when exactly one cell of a
summing group is suppressed, the next-smallest is suppressed too. Enforced by: property test
`test_no_suppressed_cell_is_derivable_from_its_group`; active. Refs: §16.3, D-0187, D-0246.
#### Scenario: One small cell in a group
- **WHEN** exactly one bucket cell of a field type is below 10
- **THEN** the next-smallest bucket cell of that type is suppressed as well

### Requirement: Merge gate (INV-21)
`gate(candidate, baseline)` SHALL fail on a precision drop over 0.5 pt on a required field type, any
`wrong_product > 0` (even without a baseline), or fewer pages than the baseline; without a baseline on `main` it
passes with `no_baseline`, and never reports a hidden improvement. Enforced by: the protected job gate; reports
`no_baseline` until milestone M. Refs: G2, §16.4, D-0188, D-0193, D-0333.
#### Scenario: First run with a wrong product
- **WHEN** the gate runs with no baseline and one wrong product on money
- **THEN** it fails with reasons `["no_baseline", "wrong_product:money"]`

### Requirement: Protected CI job and PR evaluation section (INV-19)
`eval-protected.yml` SHALL run on PRs and `main` in the `eval-protected` environment, upload no artifacts and print
only pass/fail; today it runs the hidden-host scan and prints `eval-protected: pass, no_baseline` (hidden run, gate,
PR comment not built yet: human tasks H1/H2). A PR touching extraction code SHALL fill the "Evaluation report"
section. Enforced by: PR template; active (protected job comment not built yet). Refs: C10, §16.4, D-0234.
#### Scenario: Extraction PR before M
- **WHEN** a PR changes `backend/src/crawlerai/resolve/`
- **THEN** its description fills the Evaluation report section and the protected job passes as `no_baseline`

### Requirement: Fitting on dev only (INV-02)
Calibration, source precedence, drift margins and vocabularies SHALL be fitted on dev only: `eval calibrate` and
`fit-precedence` exit 2 on any other split before opening a store and stamp output `source_split: dev`. Enforced by:
both commands' split check and stamp; active. Refs: C1, §10, §16, D-0229, D-0231, D-0758.
#### Scenario: Hidden fit refused
- **WHEN** `crawlerai eval calibrate --split hidden --run <id>` runs
- **THEN** it exits 2 and writes nothing

### Requirement: Claims before and after milestone M
Until milestone M confidence SHALL be `calibrated=false`, precedence and drift margins their defaults, and no doc, PR
or UI claims accuracy; improvement claims come only from fresh results, and a dev gain with a hidden drop is a
regression. Refs: C10, §21, Appendix A #29.
