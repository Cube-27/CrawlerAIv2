# Change: plan phase 0 — the golden set as the only measure, the master-plan decisions, guarded JSON

## Why

The master improvement plan (owner, 2026-10-18) found that the hidden/fresh/custodian evaluation machinery protects
data that does not exist (the gate reports `no_baseline`; ~900 source and ~1,500 test lines), while the golden set
the owner declared the only measure has none of the tools it needs. It also found JSON parsed at twelve places that
bypass the guarded reader (a deeply nested document raises `RecursionError` and fails the page) and NUL characters in
`raw_value` that make Postgres reject a page's candidates. The owner approved all thirteen recommendations of the
plan's section 7 except decision 7, which is deferred: vendor-blocked pages stay a `blocked` outcome.

## What Changes

- The owner's decisions are recorded (`design/owner-decisions.md` #67); `design/overview.md` §1, §21 and §22 describe
  the post-plan architecture; contract C1 and C10 are rewritten for fresh-batch rotation on the golden set; INV-01,
  INV-02, INV-04, INV-19, INV-21 and INV-25 are retired (IDs kept); OPEN_QUESTIONS and the backlog's current focus
  follow the plan's phases.
- **Deleted:** the private eval database and its models and migration, `EvalPrivateDatabaseSettings`, the private
  store, `promote`/`rotate-hidden`, the merge gate, aggregate suppression, `export_aggregate`, `generalization_gap`,
  the one-split host check, the private object keys, the custodian role, the in-flight change
  `wire-protected-eval-job`, and their tests and spec requirements. One eval split remains, `dev`.
- **Dead code deleted:** `find_codes`, `next_mode`, `read_subsets`, the adapter registry's registered/active split.
- **Docs policy:** new code cites the spec requirement, not `D-NNNN` or `ARCHITECTURE §N`; the stale docstrings the
  plan names are fixed.
- **One guarded JSON reader** in `core/json_text.py` (text or bytes with RFC 8259 §8.1 encoding detection, depth
  guard), used at every site that parsed page or answer JSON with `json.loads`; the release executor keeps its own
  copy (INV-20). A candidate's `raw_value` is scrubbed of NUL and lone surrogates before it is stored.

## Impact

- Capabilities: [evaluation](../../../specs/evaluation/spec.md), [persistence-storage](../../../specs/persistence-storage/spec.md),
  [learning-configs](../../../specs/learning-configs/spec.md) (deltas in `specs/`); contract and design documents by owner
  approval (master plan, 2026-10-18).
- Files: `backend/src/crawlerai/eval/`, `db/`, `core/settings.py`, `core/json_text.py` (new), `cli.py`,
  `backend/migrations/`, `infra/postgres/init.sql`, the JSON call sites in `acquire/`, `adapters/`, `content/`,
  `search/`, `collect/`, `config_ir/`, `resolve/task.py`, `tools/orchestrator/test_db.sh`, docs.
- Not here: `.github/workflows/` (the worker token cannot push workflow files): `eval-protected.yml` and the private
  test databases in `ci.yml` stay until the owner removes them (backlog H9).
