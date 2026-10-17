# Change: import draft labels into dev and report on them

## Why

The owner provided a draft labeled set (kept outside the repo, C3) to measure the engine before milestone M. There is
no way to load labels from a file, no `crawlerai eval run` command, and the report scores checked pages only, so the
set cannot be measured. A dev baseline also needs the triage the report lacks: per page kind, per-field disagreements,
and which misses depend on role C.

## What Changes

- `crawlerai eval import-labels <file> --split dev --status draft`: a generic label file (shape in
  `crawlerai.eval.label_file`), each page fetched through the worker's acquisition path (polite, serial), stored as a
  dev eval page with its values normalized into a `draft` label; declined values are reported by path.
- `crawlerai eval run --split dev [--labels all] [--llm recorded|unanswered|live] [--llm-max-calls N] [--out F]`:
  replays dev through `replay_split` and `build_report`; a checked-only run is stored as an eval run, a draft run
  never is.
- Metrics: drafts scored only on dev when asked (unlabeled fields unscored); long_text matches by word overlap ≥ 0.9;
  dev-only `by_page_kind` and `disagreements`; each judgment carries the engine's reason, each page its LLM calls
  without a reply.

## Impact

- Capability: [evaluation](../../../specs/evaluation/spec.md).
- Code: `backend/src/crawlerai/eval/` (`label_file.py`, `metrics.py`, `replay.py`, `cli.py`, `store.py`,
  `prefill.py`), `backend/src/crawlerai/cli.py`, `backend/src/crawlerai/normalize/` (`text.word_overlap`,
  `dispatch.similarity`).
- Labels and captures live only in the local database and object store; nothing of the set enters the repo.
