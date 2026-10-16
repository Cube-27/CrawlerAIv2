# Tasks

Status: blocked on human tasks H1 and H2. Agents can't do section 1; section 2 starts when it is done.

## 1. Human-only (owner or custodian)

- [ ] 1.1 H1 (M): choose the custodian(s) of the hidden and fresh sets (OPEN_QUESTIONS #6). Create the private eval
      database role and credentials, and store them only in the protected GitHub environment. Deferred.
- [ ] 1.2 H2 (M): protect the `eval-protected` GitHub environment (GitHub auto-created it with no rules): add the
      custodians as required reviewers and set the secrets, including the hidden-host list. Deferred.
- [ ] 1.3 H3 (M): label dev from a review of crawler output, then draw and label hidden from sites development never
      touched (§21 rule). Deferred; labeling waits until the crawler works.
- [ ] 1.4 H6 (M): monthly, after M: sample and label 20–30 fresh sites (OPEN_QUESTIONS #7). Deferred.

## 2. Implementation (SPEC-03 row 7)

- [ ] 2.1 Protected job per SPEC-03 §4.9 replaces the placeholder in `eval-protected.yml`; done when the pass/fail
      comment appears on a PR.
- [ ] 2.2 On a push to `main`, run the gate before `put_run` (#32); store the unsuppressed report as `metrics`;
      check out with `fetch-depth: 0`.
- [ ] 2.3 Handle `n_pages_dropped` after a rotation: record a new baseline (#34).
- [ ] 2.4 Dev report in the `backend` job (`crawlerai eval run --split dev`, full report uploaded).
- [ ] 2.5 Apply the delta to `openspec/specs/evaluation/spec.md` and archive this change (`/implement-pr` §5).
