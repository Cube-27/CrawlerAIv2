# Tasks

## 1. Owner decisions and documents

- [x] 1.1 Append the master-plan decisions to `design/owner-decisions.md`; rewrite `design/overview.md` §1, §21 and §22
      to the post-plan state. (#271)
- [x] 1.2 Rewrite contract C1 and C10 (and C6's enforcement) in `project.md` and `CLAUDE.md` for fresh-batch rotation
      on the golden set; retire INV-01, INV-02, INV-04, INV-19, INV-21, INV-25 (IDs kept). (#271)
- [x] 1.3 Update `OPEN_QUESTIONS.md` and the backlog's current focus to the plan's phases; delete the change
      `wire-protected-eval-job` and its human tasks. (#271)

## 2. Hidden/fresh/custodian machinery

- [x] 2.1 Delete the private store, private models and migration, private settings, `promote`, `rotate-hidden`, the
      one-split host check and the private object keys; one `dev` store remains. (#271)
- [x] 2.2 Delete the merge gate, suppression, `export_aggregate` and `generalization_gap`; the report is the dev report. (#271)
- [x] 2.3 Delete the private database and custodian role from `infra/postgres/init.sql`, `test_db.sh`, `Makefile`,
      `.env.example` and the docs; document fresh-batch scoring in the evaluation spec. (#271)

## 3. Dead code and docs policy

- [x] 3.1 Delete `find_codes`, `next_mode`, `read_subsets` and the adapter registry's active/registered split. (#271)
- [x] 3.2 Docs policy in `CLAUDE.md` and `ENGINEERING.md` (cite spec requirements, not `D-NNNN`); fix the stale
      docstrings of `acquire/classify.py` and `resolve/preference.py`. (#271)

## 4. Robustness

- [x] 4.1 One guarded JSON reader (`core/json_text.py`) at the twelve `json.loads` bypass sites. (#271)
- [x] 4.2 Scrub NUL and lone surrogates from a candidate's `raw_value` before it is stored. (#271)
