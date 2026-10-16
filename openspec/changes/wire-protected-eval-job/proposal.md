# Change: wire the protected evaluation job

## Why

C10 accepts a change only when it improves dev and does not regress hidden. The `eval-protected` workflow is still
the SPEC-00 placeholder that reports `no_baseline`, and the `backend` job does not produce the dev report, so the
gate exists in code (`crawlerai eval gate`) but runs on nothing. This is the one open row of SPEC-03 (row 7),
carried over by the OpenSpec conversion (D-1136). It waits on human tasks: custodian credentials (H1) and the
protected environment (H2); measuring anything also needs labels (H3, milestone M, ARCHITECTURE §21).

## What Changes

- Replace the placeholder in `.github/workflows/eval-protected.yml` with SPEC-03 §4.9: hidden-host scan, hidden
  replay, gate against the latest `main` run, aggregate written to the private store, PR comment with pass/fail per
  field type only; no artifacts, nothing printed beyond pass/fail lines.
- The `backend` job runs `crawlerai eval run --split dev` on every PR and uploads the full dev report.
- Carry-overs from earlier PRs: from #32, run the gate before `put_run` on a push to `main` (or the candidate
  becomes its own baseline), store the unsuppressed report as `metrics`, and check out with `fetch-depth: 0`; from
  #34, a rotation lowers hidden `n_pages`, so the next gate fails `n_pages_dropped` until a new baseline is recorded.
- Touches the protected job, so it is escalated by rule (`CLAUDE.md` §4): the owner (or custodian) reviews it.

## Impact

- Capability: [evaluation](../../specs/evaluation/spec.md) (delta in `specs/evaluation/spec.md`).
- Design: SPEC-03 §4.8–§4.9 in the [archive](../archive/2026-10-16-spec-03-evaluation-and-measurement/SPEC-03-evaluation-and-measurement.md);
  ARCHITECTURE §16.4 and §21 ([archived](../archive/2026-10-16-architecture-rev25/ARCHITECTURE.md), §21 also in
  [design/overview.md](../../design/overview.md)).
- Files: `.github/workflows/eval-protected.yml`, `.github/workflows/ci.yml`, `backend/src/crawlerai/eval/` (`export-aggregate`).
- Status: `human` until H1 and H2 are done.
