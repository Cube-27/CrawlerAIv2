# Design: dev-eval-import

## Decisions

### D-1460 — Draft label import: generic file, dev only, drafts only, the worker's fetch
- Date: 2026-10-17 · Change/PR: dev-eval-import (#264) · Status: decided (owner-delegated 2026-10-17)
- Decision: `crawlerai eval import-labels <file> --split dev --status draft` reads `{"pages": [...]}` (shape in
  `crawlerai.eval.label_file`), checks every page against its schema before any fetch, refuses hosts of other splits
  by counts, fetches each page with `polite_fetch` (robots, site rate, adapters, render check) one at a time, and
  stores a `draft` with no labeler. Values are normalized by the field's normalizer in the captured page's context;
  declines, lists with dropped items and row-mapped fields stay unlabeled and are reported by path. Re-runs skip URLs
  already in dev.
- Alternatives: `labeled`/`checked` imports (would bypass §16.2's two passes); `eval capture`'s HTTP-only fetch
  (misses the adapters and renders the worker uses); storing values as given (unnormalized labels never compare).
- Why: owner request; a draft is never ground truth, so the two-pass rule is untouched.
- Reversible: yes.

### D-1461 — Drafts scored only in a dev report that asks, never stored as a run
- Date: 2026-10-17 · Change/PR: dev-eval-import (#264) · Status: decided (owner-delegated 2026-10-17)
- Decision: `replay_split` and `build_report` take `statuses` (checked by default); any other set is refused off dev.
  A draft's unlabeled fields are not scored. `eval run --labels all` prints and writes its report but never stores an
  eval run, so drafts never become a baseline or a calibration input; `--labels checked` stores the run.
- Alternatives: count drafts as checked (pollutes the gate and calibration).
- Why: §16.2 (only checked pages count), INV-02.
- Reversible: yes.

### D-1462 — long_text scores by word overlap of at least 0.9
- Date: 2026-10-17 · Change/PR: dev-eval-import (#264) · Status: decided (owner-delegated 2026-10-17)
- Decision: metrics score a long_text output TP when it is type-equal to the label or the Sørensen-Dice coefficient of
  their word multisets (`vocab.tokens`) is at least 0.9 (`normalize.dispatch.similarity`). All other types keep
  SPEC-04 type equality (money amount and currency, enum member, location's rule, URL canonical form).
- Alternatives: exact equality (scores nearly every description wrong over line breaks and boilerplate); character
  edit distance (quadratic on 100k-character texts).
- Why: a description is one value whose edges and line breaks differ between sources.
- Reversible: yes — a constant.

### D-1463 — Dev-only triage cells: per page kind and per-field disagreements
- Date: 2026-10-17 · Change/PR: dev-eval-import (#264) · Status: decided (owner-delegated 2026-10-17)
- Decision: the report adds `by_page_kind` ("page_kind|field_type") and `disagreements` ("schema|field" → counts of
  `FP|wrong_value`, `FP|on_absent`, `FP|extra_row`, `FN|<engine reason>`, `FN|not_output`), each judgment its engine
  reason and each page its label status. Both are empty in hidden and fresh aggregates.
- Alternatives: suppressed page kind cells in aggregates (two page kinds split a type's cell, so one suppressed part
  would be derivable, §16.3).
- Why: triage needs where a field fails and why; aggregates stay per type and bucket only (§4.7).
- Reversible: yes.

### D-1464 — Recording misses in a dev run: drop, answer nothing, or a capped live call
- Date: 2026-10-17 · Change/PR: dev-eval-import (#264) · Status: decided (owner-delegated 2026-10-17)
- Decision: `eval run --llm recorded` (default, as CI) drops a page whose recording is missing; `unanswered` answers
  with a client without providers, so role C's fields stay missing with `llm_unavailable`; `live` calls the configured
  providers and records their replies, at most `--llm-max-calls` requests (`CappedLLM`, then `llm_budget`). Each page
  counts its LLM calls without a reply, which tells the misses that depend on role C.
- Alternatives: only `recorded` (no baseline without recordings or keys).
- Why: a local baseline needs to run with and without keys at a bounded cost.
- Reversible: yes.
