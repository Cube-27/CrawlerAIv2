# SPEC-03 — Evaluation and measurement

Layer: L0. Architecture refs: §16 (all), §15 (replay), §6 (`eval_page`, `eval_run`), §2.2 C1, C9, C10, C13,
§21 L0, G1, G2, G7.

## 1. Summary

The defence against §2.1. Three splits with physically separated storage and credentials, a minimal labeling tool,
a replay harness that is the only path from captures to metrics, a metric report whose hidden/fresh parts are
aggregates computed in the protected CI job, and the merge gate (§16.4). A change is accepted when it improves
dev and does not regress hidden; improvement claims are made only from fresh (C10). It is built before any
extraction; labels arrive at milestone M (§21), and until then the gate reports `no_baseline`.

**Where the labeling tool lives.** In this spec, not in SPEC-12. L0 must finish before L1 starts, the tool is
inseparable from the eval store's access model, and the custodian runs it against the private database on their
own machine. It is implemented as the first screen of the frontend app from SPEC-00 (so it uses the shared
shell, theme and generated client), mounted only when the backend runs with `CRAWLERAI_EVAL_UI=true`.

## 2. Scope

Core:
- Eval stores: dev (main DB + main object store, `eval/dev/` prefix) and private (separate database + separate
  object store root) behind one `EvalStore` protocol.
- Custodian access control (OPEN_QUESTIONS #6).
- Label format, two-pass labeling, LLM pre-fill hook (filled by SPEC-06), eval page CRUD.
- CLI: capture pages into a split, import a fresh-site list, promote fresh → dev and rotate hidden → dev.
- Replay harness (§15): pure function, recorded LLM responses, deterministic.
- Metrics (§16.3) and the aggregate report format.
- Protected CI job (§16.4) with the gate, baseline comparison and PR comment; the C3 hidden-host scan (SPEC-00).
- Dev report on every PR (full detail).
- `crawlerai eval calibrate` and `fit-precedence` entry points (consumed by SPEC-05; defined here because they
  must refuse non-dev splits — INV-02).

Out of scope:
- Review queue UI beyond labeling (§22).
- Site health dashboards, alerts (§22).
- Any automatic labeling as ground truth (§16.2: an LLM audit is never ground truth).
- The confidence/τ logic itself (SPEC-05); this spec only produces the calibration table.

## 3. Dependencies

- SPEC-00 (CI, protected environment, frontend skeleton), SPEC-01 (tables, bundle, stores), SPEC-02 PRs 1–3
  (HTTP fetch for capturing eval pages).
- OPEN_QUESTIONS #6: custodian = owner + one engineer. #7: fresh = monthly, 20–30 sites, stratified by
  category, 3 pages each. #8: initial ~300 pages. #11: user-supplied ground truth, if any, goes to hidden/fresh only. #13: one US
  region; eval captures retained forever.

## 4. Design

### 4.1 Modules

- `crawlerai.eval.store` — `EvalStore` protocol; `DevEvalStore`, `PrivateEvalStore`.
- `crawlerai.eval.labels` — label models, validation, equality per type (delegates to `normalize.*.equal`).
- `crawlerai.eval.replay` — `replay_page`, `replay_split`, `RecordedLLM`.
- `crawlerai.eval.metrics` — metric computation; `AggregateReport`.
- `crawlerai.eval.gate` — baseline comparison and pass/fail.
- `crawlerai.eval.calibrate` — writes `backend/data/calibration.json` and `source_precedence.yaml` from a dev run.
- `crawlerai.eval.cli` — `crawlerai eval …` commands.
- `crawlerai.api.routers.eval` — labeling endpoints (mounted only when `CRAWLERAI_EVAL_UI=true`).
- `frontend/src/screens/labeling/*` — the labeling screen.

### 4.2 Stores and access control (C1, INV-01)

| | dev | hidden, fresh |
|---|---|---|
| Database | main DB, tables `eval_page`, `eval_run` (SPEC-01 DDL) | database `crawlerai_eval_private`, same DDL plus `eval_capture` (copy of `capture` columns) and `eval_llm_cache` |
| Objects | main store, `eval/dev/{capture_id}.bundle.zst` | private store root, `{split}/{capture_id}.bundle.zst`, `llm/{hash}.json` |
| Credentials | `app` role | `custodian` role; `CRAWLERAI_EVAL_PRIVATE_*` settings, set only on custodian machines and in the `eval-protected` GitHub environment |
| Who sees cases | everyone | custodian; the protected job (machine) |
| What leaves | everything | pass/fail per field type in the PR comment; `eval-aggregate.json` to the private store only |

`infra/postgres/init.sql` creates both databases and roles; `app` has no grant on the private database (test:
connecting as `app` to it fails). Dev `eval_page.capture_id` references `capture` (with `expires_at IS NULL`);
private `eval_page.capture_id` references `eval_capture`.

`EvalStore` protocol:

```python
class EvalStore(Protocol):
    split: Split
    async def list_pages(self, schema_name: str | None = None, status: LabelStatus | None = None) -> list[EvalPageRow]
    async def get_page(self, page_id) -> EvalPageRow
    async def get_bundle(self, capture_id) -> CaptureBundle
    async def put_capture(self, bundle: CaptureBundle, category: str) -> capture_id
    async def put_page(self, page: EvalPageRow) -> page_id
    async def put_labels(self, page_id, labels: Labels, who: str, pass_: Literal["labeler","checker"]) -> None
    async def put_run(self, run: EvalRunRow) -> run_id
    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None
    async def llm_cache_get(self, key: str) -> bytes | None
    async def llm_cache_put(self, key: str, value: bytes) -> None
```

`get_store(split, settings)` returns the dev store for `dev` and raises `PrivateCredentialsMissing` for
hidden/fresh when the private settings are empty — which is the normal state on agent and developer machines.

### 4.3 Eval page and labels

`eval_page` columns per §6; `labels` jsonb:

```jsonc
{
  "label_version": 1,
  "status": "draft" | "labeled" | "checked",
  "labeler": "name", "checker": "name|null", "prefill_source": "none|llm:<model>|null",
  "fields": {                                   // detail pages and page-level listing fields
    "price": { "value": {"amount": "19.90", "currency": "EUR"}, "absent": false, "locator": "xpath:…|jsonld:…|text:123-128", "distractors": [ {"amount":"24.90","currency":"EUR"} ] },
    "brand": { "value": null, "absent": true, "locator": null }
  },
  "rows": [ { "fields": { "title": {...}, "url": {...} } } ],   // listing pages only; order as on page
  "notes": "free text (never a hostname)"
}
```

- `value` is the **normalized** typed value (SPEC-04 types), entered through the labeling UI which runs the
  normalizer on the raw text the labeler selects and shows the result; the labeler can override.
- `absent: true` means the field is genuinely not on the page (G2 false-publish metric).
- `distractors` are values of the same field visible on the page that belong to a different entity
  (recommendations, bundles); they drive the wrong-product metric.
- `category` on the row: `platform_store`, `custom_store`, `api_backed`, `job_board`, `mixed` (ARCHITECTURE
  categories, §16.1). These are category names, not sites.
- A page counts for metrics only when `status == "checked"` (two passes, §16.2).

### 4.4 CLI

```
crawlerai eval capture --split dev|hidden|fresh --schema commerce_detail --page-kind detail --category custom_store URL...
crawlerai eval import-sites --split fresh --file sites.txt --pages-per-site 3      # custodian; file never committed
crawlerai eval promote --from fresh --to dev [--all]                                 # after the fresh run (§16.1)
crawlerai eval rotate-hidden --fraction 0.33                                         # quarterly (§16.1)
crawlerai eval run --split dev|hidden|fresh [--schema …] --out report.json
crawlerai eval gate --candidate report.json --baseline baseline.json
crawlerai eval calibrate --split dev --run <id>            # refuses any other split (INV-02)
crawlerai eval fit-precedence --split dev --run <id>       # refuses any other split (INV-02)
crawlerai eval export-aggregate report.json --out eval-aggregate.json
```

`capture` uses `acquire.fetch_http` / `fetch_browser` (SPEC-02) directly and writes via `EvalStore.put_capture`;
it never writes to the production `capture` table for hidden/fresh. Promotion copies bundles between stores and
deletes the source row, in that order; a promoted page keeps its labels.

### 4.5 Replay harness (§15, G7)

```python
async def replay_page(bundle: CaptureBundle, schema: SchemaDef, config: ExtractionConfigIR | None,
                      llm: LLMClient, mode: Mode) -> ExtractionResult
```
Calibration is part of the engine, named by `engine_version` (ARCHITECTURE §15; D-0217).

- Identical to the live path: `replay_page` *is* the function the worker calls (SPEC-05 implements it; this spec
  defines the signature and the harness around it).
- `RecordedLLM` wraps the real client: key = sha256(role, model, prompt, schema); a hit returns the stored
  response; a miss calls the provider (dev: allowed from any machine; hidden/fresh: only inside the protected
  job) and stores it in the split's cache. Replays of a committed engine version are therefore deterministic
  (INV-10) and cost nothing after the first run.
- `replay_split(store, engine, schema_filter) -> list[PageResult]` runs every `checked` page with the active
  config for the page's site if `eval_page` carries one (`config_snapshot` jsonb, plumbing) else `None`
  (cold mode). Config fields are measured per status (§16.3) using the snapshot.
- Determinism test: run twice, byte-identical JSON.

### 4.6 Metrics (§16.3)

For each checked page, field, and split, with the label `L` and the engine output `O`:

| Count | Definition |
|---|---|
| TP | `O.status == published` and `equal(O.value, L.value)` (type equality from SPEC-04) |
| FP | `O.status == published` and (`L.absent` or not equal) |
| FN | `O.status != published` and not `L.absent` |
| TN | `O.status != published` and `L.absent` |
| FP_absent | FP where `L.absent` |
| WP (wrong product) | `O.status == published` and `O.value ∈ L.distractors` |

Reported, per `(split, field_type)` and per `(split, schema, field)`:
`precision = TP/(TP+FP)`, `coverage = TP/(TP+FN)`, `abstain_rate = (FN+TN)/(TP+FP+FN+TN)`,
`false_publish_on_absent = FP_absent / (FP_absent+TN)`, `wrong_product = WP` (count; must be 0), `n`.

Also:
- per `(split, field_type, evidence_bucket)` and per `(split, field_type, config_field_status)`: precision, n;
- per `(split, category)`: `zero_touch = pages where every required field (and required group) is TP / pages`;
- `generalization_gap[field_type] = precision_dev − precision_fresh`;
- acquisition outcome mix per category (from the bundles' block classes);
- usage: LLM calls per 1k pages by mode (from the harness's call counter).

Listings: rows are matched to label rows by canonicalized `url`; unmatched engine rows are FP for every
published field; unmatched label rows are FN.

### 4.7 Aggregate report (`eval-aggregate.json`)

```jsonc
{ "report_version": 1, "engine_version": "...", "git_sha": "...", "split": "hidden", "n_pages": 150,
  "by_field_type": { "money": {"precision": 0.971, "coverage": 0.88, "abstain_rate": 0.1, "false_publish_on_absent": 0.0, "wrong_product": 0, "n": 140} },
  "by_bucket": { "money|structured": {"precision": 0.98, "n": 90} },
  "by_config_status": { "money|corroborated": {"precision": 0.99, "n": 20} },
  "by_category": { "custom_store": {"zero_touch": 0.62, "n": 30} },
  "acquisition": { "custom_store": {"ok": 28, "blocked": 1, "shell": 1} },
  "usage": { "adhoc": {"llm_calls_per_1k_pages": 420, "n": 120}, "config": {"llm_calls_per_1k_pages": 0, "n": 30} },
  "gate": { "baseline_git_sha": "...", "passed": true, "reasons": [] } }
```

No URLs, hosts, labels, values or per-page rows appear in a hidden/fresh aggregate. Minimum cell size (§16.3): a
cell with fewer than 10 labeled fields is reported as `{"n": <n>}` only, with no metrics, so small cells cannot
identify a case. The dev report is the same schema plus a `pages: [...]` array with per-page, per-field detail
and no suppression, and a `by_field` table per (schema, field); `by_field` is empty in a hidden/fresh aggregate (D-0183).
Each cell is suppressed on its own `n`: field cells count scored fields, bucket and config-status cells count
published fields, page-level cells (`by_category`, `acquisition`, `usage`) count pages (D-0181).

### 4.8 Gate (§16.4)

`gate(candidate, baseline)` implements the hidden half of C10 (non-regression) and fails when any of:
- `candidate.by_field_type[t].precision < baseline.by_field_type[t].precision − 0.005` for any required field
  type (`t` with ≥ 1 required field in a preset: money, text, long_text, enum, url, image_url, identifier, date,
  location);
- `candidate.by_field_type[t].wrong_product > 0` for any `t`;
- `candidate.n_pages < baseline.n_pages` (pages silently dropped — §16.4 "never silently dropped").

Baseline = the latest `eval_run` for the same split whose `git_sha` is on `main`. The first run has no baseline
and passes with `reasons: ["no_baseline"]`.

The dev half of C10 ("improves dev") is shown, not gated: the dev report carries per-field-type deltas against
the dev baseline, and the PR template asks for them (SPEC-00 4.9). The gate never reports a hidden improvement;
its output is pass/fail per field type and the reasons.

### 4.9 Protected CI job (fills the SPEC-00 placeholder)

Steps, on `pull_request` and `push` to `main`, environment `eval-protected`:
1. `uv sync --frozen`; export `CRAWLERAI_EVAL_PRIVATE_*` from environment secrets; `CRAWLERAI_LOG_REDACT_URLS=true`;
   log level `WARNING`.
2. `tools/site_literal_scan.py --hidden-hosts-from-env HIDDEN_HOSTS` (file:line only).
3. `crawlerai eval run --split hidden --out hidden.json`; on `push` to `main` also record the run as the new
   baseline (`put_run`).
4. `crawlerai eval gate --candidate hidden.json --baseline <latest main run>`.
5. `crawlerai eval export-aggregate hidden.json --out eval-aggregate.json` and write it to the private store
   root (`reports/{run_id}.json`) for the custodian. Post only the per-field-type pass/fail and the gate result
   as a PR comment (C10, §16.4). **The repo is public, so workflow logs and artifacts are readable by anyone:**
   the job uploads no artifacts and prints nothing beyond the pass/fail lines.
6. Fresh runs are manual (`workflow_dispatch`), once per fresh batch, then `promote`.

The job fails if any step writes to the artifact area, and the workflow
sets `ACTIONS_STEP_DEBUG` off. The dev report is produced by the normal `backend` job on every PR
(`crawlerai eval run --split dev`) and uploaded in full.

### 4.10 Labeling tool

Backend (`/v1/eval/...`, mounted only with `CRAWLERAI_EVAL_UI=true`; same API-key auth as everything else):
- `GET /v1/eval/pages?split&status&schema` — list.
- `GET /v1/eval/pages/{id}` — row + `bundle_html` (sanitized: `script`, `iframe`, `object`, `embed`, event
  attributes removed; `<base href>` set to the capture URL so images load from the live site — note this makes
  the labeler's browser contact the site; acceptable for a human) + cleaned text with offsets.
- `PUT /v1/eval/pages/{id}/labels` — body = labels; server validates each `value` through the type normalizer
  and refuses invalid values with the reason.
- `POST /v1/eval/pages/{id}/normalize` — `{field, raw_text}` → normalized value or decline reason (so the UI
  shows what the engine would store).
- `POST /v1/eval/pages/{id}/prefill` — calls the pre-fill hook (SPEC-06 role C in a labeling prompt variant) and
  stores a `draft` with `prefill_source`; 501 until SPEC-06 lands.
- `POST /v1/eval/capture` — `{split, schema, page_kind, category, urls[]}`; runs `eval capture`.

Frontend screen `/labeling`:
- Left: the sanitized page in a sandboxed `<iframe sandbox="" srcdoc=…>`; clicking an element copies its text and a
  computed XPath (ids and `data-*` anchors preferred) into the focused field.
- Right: a form with one row per schema field: raw text, normalized value (live via `/normalize`), `absent`
  toggle, locator, distractor list; listing pages show a rows table with add/remove.
- Pass switch: labeler → checker; the checker sees the labeler's values and confirms or edits; `status` becomes
  `checked` only on confirmation by a different name.
- The screen reads the split from the backend; when the backend is pointed at the private store (custodian
  machine) the title bar shows "PRIVATE SPLIT" in a persistent badge.

### 4.11 Error handling

- Replay of a page whose bundle is missing or corrupt → `PageResult(error=...)`; the page counts as dropped and
  trips the `n_pages` gate, which is intended (§16.4).
- Label validation errors are returned with field and reason; nothing partial is saved.
- Private credentials missing → `PrivateCredentialsMissing` with a message that says this is expected for
  non-custodians.

## 5. Invariants

INV-01 (separate stores; the test suite includes "app role cannot connect to private DB" and "aggregate
contains no string matching the host regex"), INV-02 (`calibrate`/`fit-precedence` refuse non-dev), INV-04,
INV-10 (double-run diff), INV-19 (PR comment), INV-21 (gate), INV-09 (no site names in eval tests; fixtures use
`.test` hosts).

## 6. Testing strategy

- Metrics: unit tests from hand-built label/output pairs covering each cell of the table in 4.6, listings
  matching, min-cell suppression.
- Gate: tests for each failure reason; no-baseline case.
- Replay determinism: two runs over a synthetic dev split of 5 bundles with a `RecordedLLM` stub; byte-equal.
- Store: contract tests run against both store implementations with a temp private database in CI (the CI
  Postgres service has both databases; the private one holds synthetic data only).
- Redaction: a log-capture test asserts no URL appears in logs when `CRAWLERAI_LOG_REDACT_URLS=true`.
- Labeling UI: Vitest tests for the form (normalize round trip, absent toggle disables value, checker cannot be
  the labeler).
- CI gates: `backend`, `frontend`, protected job (on a PR that touches extraction packages, it must comment).

## 7. Acceptance criteria (§21 L0 done-when)

- **Milestone M (§21; not required to mark this spec done):** dev and hidden sets labeled: ≥ 300 checked pages across both, stratified per §16.1 (~70% detail, 30% listing;
  all five categories; DOM-only sites included). This is custodian/labeler work enabled by the tool; the spec is
  done when the tool supports it and the custodian confirms.
- Report reproducible: `crawlerai eval run --split dev` twice gives identical `report.json` (on synthetic and
  unlabeled dev captures before M). The protected job passes as `no_baseline` while no hidden labels exist;
  **Milestone M (§21; not required to mark this spec done):** it computes the hidden gate on a PR and posts pass/fail.
- The labeling tool can create, check and export labels for a dev capture (test on a synthetic page).
- `calibrate`/`fit-precedence` exit non-zero on `--split hidden`.
- `app` credentials cannot read any private table or object (test).

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Private database, roles, `EvalStore` protocol + both stores | `infra/postgres/init.sql`, `eval/store`, migrations for `eval_capture`, `eval_llm_cache` | contract tests, access-denied test | Both stores pass the contract. |
| 2 | Label model + validation + equality | `eval/labels`, normalizer `equal` hooks (stubs until SPEC-04) | unit | Round trip + validation errors. |
| 3 | `eval capture` and `import-sites` CLI | `eval/cli`, uses SPEC-02 fetch | unit with local server | Bundles land in the right store. |
| 4 | Replay harness + RecordedLLM + determinism test | `eval/replay` | determinism | Two runs identical. |
| 5 | Metrics + aggregate report + min-cell suppression | `eval/metrics` | unit | All cells covered. |
| 6 | Gate + baseline lookup | `eval/gate` | unit | Each reason tested. |
| 7 | Protected job wired (replace placeholder) + dev report in `backend` job | workflows, `export-aggregate` | protected job | Comment appears on a PR. |
| 8 | Labeling API | `api/routers/eval` | unit | Validation errors surfaced. |
| 9 | Labeling screen | `frontend/src/screens/labeling` | vitest | Labeler/checker flow works on a dev page. |
| 10 | Promote/rotate commands | `eval/cli` | unit (two temp stores) | Bundles move; labels kept. |
| 11 | `calibrate` / `fit-precedence` entry points (write files; logic lands in SPEC-05) | `eval/calibrate` | unit (refuse non-dev) | Files written with `source_split: dev`. |

## 9. Open issues

- **Review finding (adaptive overfitting to hidden).** Resolved in ARCHITECTURE rev 5 C10 and §16.3: acceptance is
  dev improvement plus hidden non-regression, improvement claims come only from fresh, and hidden/fresh cells
  under 10 labeled fields are suppressed. Implemented in 4.7–4.9.
- **Review finding (gate granularity).** Resolved in ARCHITECTURE rev 5 §16.4, which now states that any new
  wrong publish on hidden fails the gate in practice. The spec implements it literally.
- **Review finding (C3 hidden scan oracle).** A flagged file:line tells the author that a host is hidden (one
  bit). Acceptable; noted.
- **`config_snapshot` on `eval_page`** is plumbing needed to measure config-field precision per status
  (§16.3); §6 delegates eval-table plumbing to this spec.
- **Labeler contact with live sites.** The sanitized iframe loads images from the live site; if that is
  unacceptable, the tool can strip `src` attributes (loses visual context). Owner to decide.
