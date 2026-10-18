# Design: plan phase 0

## Decisions

### D-1520 — Phase 0 ships as two changes and two PRs
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: The batch is split: `plan-phase-0` (this change: decisions and documents, the hidden/fresh deletion, dead
  code, docs policy, guarded JSON, raw-value scrub) and `plan-phase-0-2` (URL keys with session-parameter removal and
  the eval report: re-key, list labels, presence ceiling, FN/FP split, cost per correct field), on branches
  `change/plan-phase-0` and `change/plan-phase-0-2`.
- Alternatives: one PR (about 6,000 changed lines); two PRs of one change folder (the first could not archive, so the
  specs would describe the deleted machinery until the second merged).
- Why: each PR stays near 4,000 changed lines, and each merge leaves the specs describing one architecture.
- Reversible: yes

### D-1521 — `dev` stays the name of the one split
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: `Split` is `Literal["dev"]`; the `split` columns with their CHECKs, the labeling API's `split` and the
  commands' `--split dev` stay. A fresh batch is imported into a database of its own, scored once, then imported into
  the golden set (evaluation spec, "One split, grown in fresh batches"); there is no `fresh` split value.
- Alternatives: drop the split column and option everywhere (a schema, API and CLI change for a name with one value,
  and every worker's documented eval command would break).
- Why: smallest change that leaves one mechanism; the name now means "the golden set".
- Reversible: yes

### D-1522 — Workflow files stay until the owner removes them
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: The worker's token has no `workflow` scope, so `.github/workflows/eval-protected.yml` and the private test
  databases `ci.yml` creates stay as they are; `tools/site_literal_scan.py --hidden-hosts-from-env`, which that
  workflow runs, stays so its job keeps passing. The branch ruleset requires no status check (`main-2`:
  `required_status_checks: []`), so deleting the job breaks no merge. Owner task H9 removes all three.
- Alternatives: delete the scan option now (the workflow's job would fail on every PR).
- Why: CI stays green; the leftover is one inert job, listed for removal.
- Reversible: yes

### D-1523 — An eval run is stamped with HEAD
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: With the gate gone, `commits_on` and the store's `latest_run` (the baseline lookup) are deleted;
  `eval/git_head.head_commit` gives the commit a stored run is stamped with (`git rev-parse --verify HEAD`).
- Why: the stamp is the only use left.
- Reversible: yes

### D-1524 — The guarded JSON reader lives in `core`
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: `core/json_text.parse` (text or bytes, RFC 8259 §8.1 / RFC 4627 §3 encoding detection, depth guard) and
  `parse_prefix` move out of `collect/json_doc`, which keeps the RFC 9535 paths; `acquire` and `adapters` sit below
  `collect` in the layers, so only `core` serves all twelve sites. LLM replies, repo data files, label files and CLI
  arguments keep `json.loads`: they are not page or answer input. The release executor keeps its own guarded copy
  (INV-20). A JSON body's markdown also returns `""` when writing it back indented nests too deeply.
- Reversible: yes

### D-1525 — A raw value is made storable, not dropped
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: `resolve.task.storable` replaces U+0000 and lone surrogates in a candidate's `raw_value` (strings and member
  names) with U+FFFD before `jsonb` stores it; normalized values are untouched (normalizers decline such strings).
- Alternatives: store raw values as text (a schema change for a diagnostic column); drop the candidate (loses triage).
- Reversible: yes

### D-1526 — The adapter registry holds only running adapters
- Date: 2026-10-18 · Change/PR: plan-phase-0 (#271) · Status: decided (owner-delegated 2026-10-17)
- Decision: `Registry(adapters)` takes the adapters that run; `acquire.rungs.adapter_registry` leaves out the disabled
  ones and refuses unknown names, so the registered/active split is gone.
- Reversible: yes
