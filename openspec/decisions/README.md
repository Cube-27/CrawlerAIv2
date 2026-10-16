# Decisions: how they are logged

Agents log the decisions they make while implementing. Owner decisions belong in
[../design/owner-decisions.md](../design/owner-decisions.md) (ARCHITECTURE Appendix A); open owner questions belong in
[../OPEN_QUESTIONS.md](../OPEN_QUESTIONS.md). What to decide yourself and when to escalate: `CLAUDE.md` §4–§5.
The implementor writes its decisions in its tracker commit, the last commit before it opens the PR, under the
decision-ID range the orchestrator gave at assignment (`CLAUDE.md` §3). Don't log trivial choices.

**Where an entry goes** (OpenSpec keeps decisions with the change they belong to):
- A decision about a change goes in that change's `design.md`, under `## Decisions` (create the file if the change has
  none). When the change is archived, its decisions move with it.
- Cross-cutting and process decisions (tooling, CI, orchestration, UAT and review fixes, rules for every capability),
  decisions of a PR that implements no change (a fix that restores specified behaviour), and every `needs-owner` or
  `pending-owner` entry go at the end of [log.md](log.md). Open ones are also listed in
  [../project.md](../project.md#open-owner-items) "Open owner items".
- Closed history: each archived spec's log is `../changes/archive/<date>-spec-NN-*/decisions.md`. Entries are never
  moved between files after they are written, except with their whole change on archive.
- D-IDs are one sequence across all files. The highest in use:
  `grep -rhoE "^### D-[0-9]+" openspec | sort | tail -1`. Find any entry with `grep -rn "### D-NNNN" openspec`.
  `tools/decision_ids.py` (CI `site-literals` job) fails when one ID heads two entries anywhere under `openspec/`.
  Older text that says "DECISIONS.md D-NNNN" or "docs/decisions/SPEC-NN.md" means this log as a whole.

**Statuses:**
- `decided`: made by an agent within its authority. Stands unless the owner overrides it.
- `pending-owner`: a default an agent chose that the owner should confirm. Work proceeds on it.
- `needs-owner`: blocking. Work that depends on it stops until the owner answers.
- `confirmed` / `overridden`: the owner's answer, with the date.
- `superseded`: replaced by a later entry. Link it.

**Rules:**
- Entries are append-only. To change a decision, add a new entry and mark the old one `superseded`.
- Keep each entry under about ten lines.
- A decision that changes behaviour also changes the requirement it touches, through the change's spec delta.
- No customer names and no secrets; the repo is public.

**Template:**

```
### D-NNNN — <title>
- Date: YYYY-MM-DD · Change/PR: <change-id> (#PR) · Status: decided | pending-owner | needs-owner
- Decision: <one or two sentences>
- Alternatives: <what else was considered>
- Why: <reason; cite requirements, design sections (§N) or eval results>
- Reversible: yes | costly | no — <what reversing would take>
- Owner answer: <filled when confirmed or overridden>
```
