# Evaluation

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 16. Evaluation

This is the defence against repeating §2.1. The machinery is built first (L0); labels arrive at milestone M (§21).

### 16.1 Splits

| Split | Who sees cases | Used for | Source |
|---|---|---|---|
| **dev** | Everyone, including agents | Tuning, debugging, and fitting precedence, confidence buckets and drift margins | New pages labeled for v2. Nothing from v1 (C12). |
| **hidden** | Custodian only (OPEN_QUESTIONS #6); others see aggregates | The non-regression gate only (C10), never fitting | Sites absent from dev, stratified by category. A third rotates into dev each quarter and is replaced. |
| **fresh** | Custodian | Improvement claims and the headline number (G1) | Each month, 20–30 sites nobody has seen are sampled (OPEN_QUESTIONS #7), labeled, measured once, then moved into dev. |

**Categories for stratification:**
- `platform_store` (hosted e-commerce platforms such as Shopify);
- `custom_store`;
- `api_backed` (data loaded from XHR/JSON);
- `job_board` (including ATS-hosted);
- `mixed` (one-off sites of any kind).

About 70% detail and 30% listing. DOM-only sites are included on purpose: all 10 accurate v1 results in the 50-site
audit came from JSON-LD pages, so the hard cases were never measured. Custom schemas get their own labels before any
accuracy claim.

### 16.2 Labels

- Two passes: a labeler and a checker. An LLM may pre-fill labels; a human confirms each one. An LLM audit is never
  ground truth.
- Labels are value plus locator, with explicit `absent`.
- Effort: an initial ~300 pages for dev + hidden, ≈ 2–3 engineer-weeks; then ~25 fresh sites × 3 pages per month,
  ≈ 8–12 hours. Labeling is the one part of the process that can't be delegated to agents.

### 16.3 Metrics

- **Per field type, per split:** precision, coverage, abstain rate, false-publish on `absent`, wrong-product rate
  (must be 0).
- **Per evidence bucket and config field status:** precision. This is what admits or rejects candidates in §22.
- **Per category:** zero-touch rate, meaning all required fields published and correct.
- **Generalization gap:** dev minus fresh, per field type.
- **Acquisition:** outcome mix per category.
- **Usage:** LLM calls per 1k pages, by mode.

Hidden and fresh aggregates suppress cells with fewer than 10 labeled fields, so aggregates can't identify individual
cases. Suppression is also complementary: when exactly one cell in a group that sums to a reported total is
suppressed, the next-smallest cell in that group is suppressed too, so no suppressed cell can be recovered by
subtraction.

### 16.4 Harness and gate

- Every merge replays dev and hidden captures offline. Dev results are shown in full. Hidden results are computed in
  the protected job. PR comments show only pass/fail per field type; numeric aggregates go only to the custodian.
- **A merge fails** on a hidden precision drop of more than 0.5 pt on any required field type, or on any
  wrong-product value. At ~150 hidden pages, 0.5 pt is less than one field label, so in practice any new wrong
  publish on hidden fails the gate.
- Exported configs go through the release check (§12.3).
- Pages from redesigned sites are re-captured and re-labeled, never silently dropped.
