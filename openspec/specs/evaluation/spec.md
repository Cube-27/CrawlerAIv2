# Evaluation Specification

## Purpose

Measurement of extraction quality without overfitting: three splits (dev, hidden, fresh) with physically separate
storage and custodian-only access, two-pass labels, a replay harness over stored captures, the metric report and its
suppressed aggregates, the merge gate, dev-only fitting of calibration, precedence and drift margins, the protected
CI job, and the PR-template evaluation section. Labels arrive at milestone M; until then the gate reports
`no_baseline`. Storage primitives are in [persistence-storage](../persistence-storage/spec.md); the labeling screen
is in [frontend-app](../frontend-app/spec.md); the CI scans are in [repo-checks](../repo-checks/spec.md).
Design rationale: [ARCHITECTURE §16](../../design/evaluation.md), [§21](../../design/build-order.md),
[Appendix A #29, #30](../../design/owner-decisions.md). History:
[SPEC-03](../../changes/archive/2026-10-16-spec-03-evaluation-and-measurement/SPEC-03-evaluation-and-measurement.md)
and its [decisions](../../changes/archive/2026-10-16-spec-03-evaluation-and-measurement/decisions.md).

## Requirements

### Requirement: Three splits
The system SHALL keep three splits: `dev` (visible to everyone, used for tuning and all fitting), `hidden`
(custodian only; used only for the non-regression gate, never fitting; a third rotates into dev each quarter) and
`fresh` (custodian only; 20–30 unseen sites sampled monthly, measured once for improvement claims, then promoted to
dev). Every eval page SHALL carry a category: `platform_store`, `custom_store`, `api_backed`, `job_board` or `mixed`.
Refs: §16.1, SPEC-03 §4.3.

#### Scenario: Fresh measured once
- **WHEN** a fresh batch has been measured and every page of a site is `checked`
- **THEN** `crawlerai eval promote --from fresh --to dev` moves that whole site into dev, keeping its labels

### Requirement: Hidden and fresh never leave the private store (INV-01)
No hidden or fresh case (URL, host, label, capture) SHALL exist in the main DB, the repo, logs or CI artifacts. Main
`eval_page`/`eval_run` carry `CHECK split = 'dev'`; private tables carry `CHECK split IN ('hidden','fresh')`.
`get_store` SHALL raise `PrivateCredentialsMissing` for hidden/fresh when the private settings are empty, and
`PrivateStoreNotSeparate` when the private DB URL names the main database or one object root contains the other.
On a private split an unexpected CLI failure prints only its exception type; CLI output names pages by input
position, never by URL. Enforced by: separate DB and roles (`infra/postgres/init.sql`; `app` refused:
`tests/db/test_eval_private_database.py`), the split CHECKs, `eval-protected.yml` uploading no artifacts, and
`test_aggregate_suppresses_small_cells_and_names_no_host`; status: active, except the log redaction test (SPEC-03,
not built yet).
Refs: C1, §6, §15, SPEC-03 §4.2, §4.11, D-0170, D-0177, D-0199, D-0202.

#### Scenario: Developer machine
- **WHEN** `get_store("hidden", settings)` runs with empty `CRAWLERAI_EVAL_PRIVATE_*` settings
- **THEN** it raises `PrivateCredentialsMissing` with a message that this is expected for non-custodians

### Requirement: Hosts stay in one split
`crawlerai eval capture` and `import-sites` SHALL refuse the whole input before any fetch when one of its hosts
already has pages in another split, reporting counts per split, never a host or line. `promote` SHALL leave a fresh
site whose host also has hidden pages, and `rotate-hidden` SHALL skip hidden hosts that also have fresh pages. At
milestone M, hidden and fresh sites SHALL be drawn only from hosts development never touched (not in the main `site`
table, dev captures or debugging); sites reviewed while building dev labels are dev.
Refs: §21, D-0221, D-0225, D-0253.

#### Scenario: Host already in dev
- **WHEN** a fresh `import-sites` file lists a host that has dev pages and custodian settings are present
- **THEN** nothing is fetched and the command reports the count of conflicting hosts per split

### Requirement: Label format
Labels SHALL be stored in `eval_page.labels` as `{label_version, status: draft|labeled|checked, labeler, checker,
prefill_source, fields, rows, lists, notes}`: each field has a normalized `value`, an explicit `absent` flag, a
`locator`, and optional `distractors` (same-field values of other entities on the page). Listing rows go in `rows`;
row-mapped `list<object>` fields go in `lists` (`label_version` 2) with `rows` and `distractor_keys`. A `labeled` or
`checked` page SHALL label every schema field (missing means error; absence is explicit); a `draft` may be partial.
Only `checked` pages count for metrics.
Refs: §16.2, SPEC-03 §4.3, D-0168, SPEC-13 §4.10.

#### Scenario: Missing field on a labeled page
- **WHEN** a `labeled` label document omits a schema field
- **THEN** validation refuses it with the field and reason, and nothing is saved

### Requirement: Two-pass labeling
A page SHALL become `checked` only when a checker different from its labeler confirms it (DB `CHECK (checker IS NULL
OR (labeler IS NOT NULL AND checker <> labeler))`; a labeler pass clears `checker`). An LLM MAY pre-fill a `draft`
(`prefill_source`), but an LLM audit is never ground truth; a human confirms each label.
Refs: §16.2, SPEC-03 §4.10, D-0175, D-0209.

#### Scenario: Self-check refused
- **WHEN** the labeler submits the checker pass under their own name
- **THEN** the write is refused and the page stays `labeled`

### Requirement: Labeling API
With `CRAWLERAI_EVAL_UI=true` the API SHALL mount `/v1/eval/pages` (list), `/v1/eval/pages/{id}` (row, sanitized
`bundle_html`, cleaned text, schema field shapes), `PUT /v1/eval/pages/{id}/labels`, `POST .../normalize`,
`POST .../prefill` and `POST /v1/eval/capture` (at most 20 URLs). It SHALL require the API key, serve the `dev`
split only (422 otherwise), and guard label writes with an ETag (`If-Match` mismatch 412, concurrent change 409).
Sanitizing removes `script`, `iframe`, `frame`, `frameset`, `object`, `embed`, `meta[http-equiv]`, `on*` attributes
and `javascript:` URLs and inserts one `<base href>`. Hidden and fresh pages are labeled only by an instance of the
app on the custodian machine with a private backend, never deployed.
Refs: §16.2, Appendix A #30, SPEC-03 §4.10, D-0207, D-0212, D-0213, D-0214, D-0235, D-0716.

#### Scenario: Private split requested
- **WHEN** `GET /v1/eval/pages?split=hidden` is called
- **THEN** the response is 422, even when private settings are set

### Requirement: Eval capture and site moves
`crawlerai eval capture` and `import-sites` SHALL fetch through the acquisition fetchers, obey robots.txt (a page on
an origin whose robots.txt is unreachable is skipped) and space requests per host, and store every fetched page as an
eval capture and unlabeled page whatever its outcome. The site list format is `<category> <schema> <url>` per line
with `--pages-per-site N`; any malformed line rejects the whole file. `promote` moves whole sites (only fully checked
ones without `--all`); `rotate-hidden --fraction F` picks `floor(F·n + 0.5)` hosts per category at random. Moves copy
then delete, so a rerun finishes an interrupted move.
Refs: §16.1, SPEC-03 §4.4, D-0195, D-0196, D-0197, D-0220, D-0222, D-0223.

#### Scenario: Blocked page captured
- **WHEN** an eval capture's fetch is classified `blocked`
- **THEN** the bundle and page are stored, the command exits 0 and reports the outcome

### Requirement: Replay harness
`replay_page(bundle, schema, config, llm, mode)` SHALL be the same function the worker calls, with calibration named
by `engine_version`. `RecordedLLM` SHALL key responses by sha256 of the canonical JSON `[prompt_kind, model_class,
system, user, output_schema]`; a hit returns the stored response, a miss calls the provider (dev from any machine,
hidden/fresh only inside the protected job) and stores it. `replay_split` runs every `checked` page with its
`config_snapshot` or `None` (cold). A missing recording or invalid snapshot drops the page; setup errors stop the
run. Determinism is [INV-10](../persistence-storage/spec.md).
Refs: §15, §16.4, SPEC-03 §4.5, D-0215, D-0216, D-0217, D-0219.

#### Scenario: Dropped page
- **WHEN** a page's bundle is missing during replay
- **THEN** the page counts as dropped, which lowers `n_pages` and trips the gate

### Requirement: Metrics
For each checked page and field the harness SHALL count TP (published and equal by type), FP (published and absent
or unequal), FN, TN, FP_absent and WP (published value in the distractors), and report per (split, field type) and
(split, schema, field): `precision = TP/(TP+FP)`, `coverage = TP/(TP+FN)`, `abstain_rate`,
`false_publish_on_absent`, `wrong_product` (count, must be 0) and `n`; plus precision per evidence bucket and per
config field status, `zero_touch` per category, `generalization_gap = precision_dev − precision_fresh`, acquisition
outcome mix per category, and LLM calls per 1k pages by mode. Listing rows match label rows by canonical `url`;
row-mapped rows match by their key; unmatched engine rows are FP, unmatched label rows FN.
Refs: §16.3, SPEC-03 §4.6, D-0180, D-0185, D-0186.

#### Scenario: Wrong product
- **WHEN** the engine publishes a price equal to a labeled distractor
- **THEN** the cell's `wrong_product` is 1 and the publish is also an FP

### Requirement: Aggregate report and minimum cells
A hidden or fresh aggregate (`eval-aggregate.json`) SHALL contain no URL, host, label, value or per-page row, and
an empty `by_field`. A cell below 10 is reported as `{"n": <n>}` only: field cells count scored fields, bucket and
config-status cells count published fields, category, acquisition and usage cells count pages. The dev report SHALL
be the same schema plus a `pages` array and `by_field`, unsuppressed.
Refs: §16.3, SPEC-03 §4.7, D-0181, D-0182, D-0183, D-0184.

#### Scenario: Small cell
- **WHEN** a hidden `by_bucket` cell has 7 published fields
- **THEN** the aggregate shows `{"n": 7}` for it and no precision

### Requirement: Complementary suppression (INV-25)
In a hidden or fresh aggregate, no suppressed cell SHALL be recoverable by subtraction: in every group of cells that
sums to a reported total (bucket and config-status cells per field type; category, acquisition and usage cells over
`n_pages`), never exactly one cell of several is suppressed; when one is, the next-smallest is suppressed too (ties by
first key). A one-cell group gets no complement. Enforced by: property test
`test_no_suppressed_cell_is_derivable_from_its_group`; status: active.
Refs: §16.3, Appendix A #30, D-0187, D-0234, D-0246, D-0247.

#### Scenario: One small cell in a group
- **WHEN** exactly one bucket cell of a field type is below 10
- **THEN** the next-smallest bucket cell of that type is suppressed as well

### Requirement: Merge gate (INV-21)
`gate(candidate, baseline)` SHALL fail on a precision drop of more than 0.005 on a required field type (money, text,
long_text, enum, url, image_url, identifier, date, location; exactly 0.5 pt passes), on any `wrong_product > 0`, or
on `candidate.n_pages < baseline.n_pages`. It reads the unsuppressed in-job report and raises `GateInputInvalid` on a
suppressed cell or split mismatch. The baseline is the newest run of the split whose `git_sha` is on `main` (walking
`git rev-list --end-of-options <ref> --`); without one it passes with `no_baseline`. A wrong product fails even
without a baseline. Output is pass/fail per field type plus reasons; it never reports a hidden improvement.
Wrong-product count on hidden is 0 or the merge fails. Enforced by: the protected job gate; status: SPEC-03, reports
`no_baseline` until milestone M.
Refs: G2, §16.4, SPEC-03 §4.8, D-0188, D-0189, D-0190, D-0191, D-0192, D-0193, D-0333.

#### Scenario: First run with a wrong product
- **WHEN** the gate runs with no baseline and one wrong product on money
- **THEN** it fails with reasons `["no_baseline", "wrong_product:money"]`

### Requirement: Protected CI job and PR evaluation section (INV-19)
`.github/workflows/eval-protected.yml` SHALL run on `pull_request` and `push` to `main` in the GitHub environment
`eval-protected` (custodians as required reviewers), with `CRAWLERAI_LOG_REDACT_URLS=true`, uploading no artifacts and
printing only pass/fail lines. Today it runs the hidden-host scan and prints `eval-protected: pass, no_baseline`.
(Not built yet, waiting on human tasks H1/H2, the environment secrets: `crawlerai eval run --split hidden`, the gate,
`export-aggregate` to the private store at `reports/{run_id}.json`, recording the baseline on `main` after gating,
the pass/fail PR comment, manual fresh runs, and the dev report in the `backend` job.) Every PR that touches
extraction behaviour (`collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/`, `acquire/`) SHALL carry the dev
delta report and the hidden pass/fail per field type in its "Evaluation report" section. Enforced by: PR template;
protected job comment; status: PR template active, protected job comment SPEC-03 (not built yet).
Refs: C10, §16.4, SPEC-00 §4.6, SPEC-03 §4.9, D-0234.

#### Scenario: Extraction PR before M
- **WHEN** a PR changes `backend/src/crawlerai/resolve/`
- **THEN** its description fills the Evaluation report section, and the protected job passes as `no_baseline`

### Requirement: Fitting on dev only (INV-02)
Calibration tables, `source_precedence.yaml`, drift margins and type vocabularies SHALL be derived from dev only.
`crawlerai eval calibrate --split dev --run <id>` and `fit-precedence` SHALL exit 2 with an INV-02 message on any
other split before opening a store, and stamp what they write with `source_split: dev`. `fit-precedence` exits 2
without a current `source_precedence.yaml`. No `calibration.json` exists until the first dev fit. Enforced by:
calibration and precedence commands refuse any split but `dev` and stamp their artifact; status: SPEC-03, SPEC-05
(active for both commands).
Refs: C1, §10, §16, SPEC-03 §4.4, D-0229, D-0230, D-0231, D-0758.

#### Scenario: Hidden fit refused
- **WHEN** `crawlerai eval calibrate --split hidden --run <id>` runs
- **THEN** it exits 2 and writes nothing

### Requirement: Claims before and after milestone M
Until milestone M, confidence SHALL be `calibrated=false`, precedence the spec's initial order, drift margins their
defaults, and the gate `no_baseline`; no doc, PR or UI claims accuracy. A change is accepted when it improves dev
(shown, not gated) and does not regress hidden; improvement claims SHALL come only from fresh results.
Refs: C10, §21, Appendix A #29.

#### Scenario: Dev up, hidden down
- **WHEN** a change raises dev precision but the hidden gate fails
- **THEN** it is a regression and does not merge
