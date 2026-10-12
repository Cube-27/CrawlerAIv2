# CLAUDE.md — rules for agents working in this repo

CrawlerAI v2 is a schema-driven web extraction engine; see `README.md`. Coding agents implement it, mostly
autonomously, from the specs. The owner is involved only for the escalations listed below. Read this file fully
before doing anything.

## 1. Read order

1. `docs/plans/ACTIVE.md`: what is in progress, what is next, what is blocked.
2. The spec for your work in `docs/specs/`: its design, invariants, acceptance criteria, and your PR's row in the
   PR plan.
3. The `docs/ARCHITECTURE.md` sections that spec cites. **§2 (generalization contract C1–C13) is binding on every
   change.** Read it once per session.
4. `docs/DECISIONS.md`: earlier decisions you must stay consistent with.

`ARCHITECTURE.md` is the single source of truth. Where a spec and the architecture disagree, stop and escalate
(§5).

## 2. Hard rules

These come from the generalization contract. Breaking one is a defect, even when it fixes a site.

- **Never touch hidden or fresh evaluation data (C1).** Don't request or use custodian credentials
  (`CRAWLERAI_EVAL_PRIVATE_*`), and don't try to read the private eval database or object root. Work only with
  the aggregate pass/fail the protected CI job reports, and never try to infer individual hidden cases from it.
- **No site literals in generic code (C3).** Hostnames, retailer and brand names, and strings copied from real
  pages are allowed only under `backend/src/crawlerai/adapters/` and in database rows. Test fixtures are
  synthetic and use RFC 2606 names (`example.com`, `.test`).
- **No lists that grow one incident at a time (C4).** Vocabularies come from versioned external data listed in
  `backend/data/manifest.json`.
- **Fix sites with data, not code (C5).** If one site fails, the fix is a config, a learning re-run or an operator
  correction. Change generic code only for a *class* of failures, and show the class with dev results.
- **Normalizers decline rather than guess (C7).** No defaults, no host tables, no values taken from URL codes.
- **One module per field type (C8).**
- **Tests check type properties and replays (C9).** No test is named after a site or asserts one site's output.
- **Gate (C10).** A change must improve dev and must not regress hidden. Claim improvements only from fresh
  results.
- **No size gates (C11).** Don't split files to satisfy line counts, and don't add LOC or complexity ratchets.
- **Nothing from the earlier versions (C12).** Don't read, copy or port code, lists, config, tests or prompts from
  the sibling `Invoro` or `CrawlerAI` (v1) projects. When a §22 candidate is admitted, its design may *read* them,
  as ARCHITECTURE §20 allows, but nothing is copied.
- **Build only core (C13).** Anything in ARCHITECTURE §22 is not built until the owner admits it based on
  evidence. If you think a candidate is needed, log the evidence in `DECISIONS.md` as `needs-owner`.
- **Never `exec` or `eval` LLM output.** Generated selectors, recipes and schemas are data run by our
  interpreters.
- **Public repo.** No customer, prospect or company names (except as adapter platform names), no business terms,
  no secrets, no captures, no evaluation data. Commit only synthetic fixtures.
- **Dependency licenses.** Don't add dependencies under AGPL, GPL, SSPL or non-commercial licenses. LGPL is
  allowed but avoided. CI enforces this.

## 3. How to do one unit of work

One unit is **one row of a spec's PR plan**: one branch, one PR.

1. In `docs/plans/ACTIVE.md`, set the row to `in-progress` and add your branch name. Branch:
   `spec-NN/pr-M-short-name`.
2. Implement exactly that row's scope. If you find work outside it, add a row or a note to ACTIVE.md instead of
   doing it.
3. Write tests first where the spec's testing section defines them: property tests for normalizers, replay tests
   for extraction.
4. Run the local checks (`make check` once SPEC-00 has created it) until they pass. Don't skip hooks or weaken
   checks.
5. Log any decision the spec didn't make in `docs/DECISIONS.md` (§4).
6. Open a PR using the template. Link the spec row, list the acceptance criteria you met, and paste the dev eval
   delta when extraction behaviour changed.
7. After review and green CI, merge, then mark the row `done` in ACTIVE.md with the PR number.

Before merging, a reviewer agent (or `/code-review`) checks the diff against the spec and §2 of this file.

## 4. Decisions: decide and log, or escalate

**Decide yourself and log it** (`DECISIONS.md`, status `decided`): implementation choices within one spec's
scope that don't change ARCHITECTURE, a public API shape, a DB schema other specs rely on, or a §2 rule. Examples:
- internal module structure;
- library choice among licence-clean equivalents;
- naming;
- error messages;
- a spec detail that is genuinely ambiguous, where you take the most conservative reading.

Don't log trivial choices.

**Escalate** (§5) when:
- the change would alter `ARCHITECTURE.md` or `OPEN_QUESTIONS.md`, or contradict them;
- it would build anything listed in ARCHITECTURE §22;
- it touches evaluation split access, the protected CI job, or labels;
- it needs credentials, secrets, paid accounts, labeling, or anything only a human can do;
- it changes a public API or MCP shape, or a table other specs depend on, beyond what the spec defines;
- two specs contradict each other;
- the same failure persists after three honest attempts.

## 5. Escalation procedure

1. Add a `DECISIONS.md` entry with status `needs-owner`. Give the question, the options, your recommendation and
   what is blocked.
2. Mark the row `blocked` in ACTIVE.md and link the entry.
3. Move on to the next unblocked row whose dependencies are done. Don't wait idle.

## 6. Editing documents

- `ARCHITECTURE.md` and `OPEN_QUESTIONS.md` change only with owner approval. When approved, update the revision
  log, and keep the specs consistent in the same change.
- Specs may get clarifying edits that don't change the architecture. Log those in DECISIONS.md.
- `ACTIVE.md` and `DECISIONS.md` are working documents. Keep them current, short and factual.
- Write plainly. No marketing language, and no claims that aren't backed by a test or eval result.

## 7. Commands

SPEC-00 adds the real commands here. Until then, there is nothing to run.
