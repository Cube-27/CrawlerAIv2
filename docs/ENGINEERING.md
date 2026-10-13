# Engineering principles

How agents write code in this repo. `CLAUDE.md` §2 (the generalization contract) outranks this file: where they
seem to conflict, the contract wins. Agents read this once per session.

Adapted from [pstack](https://github.com/cursor/plugins/tree/main/pstack) by Lauren Tan (MIT; see `NOTICE`).
Selected and rewritten for this project.

## Verification

**Prove it works.** Check the real thing, not a proxy. "It compiles", an agent's self-report and a cached result
are not evidence. The strongest proof is a check anyone can re-run: a test, a replay, or an eval delta. For
extraction changes, the proof is the dev eval delta (C10). When a check fails, suspect the check before the system.

**Sequence verifiable units.** Work in small units, each ending in a state you can check. Don't start the next unit
until the current one is green. In git history, the failing test comes first and the fix sits on top. A break
caught at its own unit is cheap to find; one caught after a batch is buried.

**Test behaviour, not implementation (C9).** A test calls the code the way its users do, and asserts the exact
result. Delete or rewrite any test that would still pass if the function returned a wrong value:
- loose assertions (`is not None`, `> 0`, "doesn't raise");
- call-only mocks;
- expected values computed by the code under test;
- restated constants.

For normalizers, prefer Hypothesis properties: round trips, declining on ambiguity, idempotence. For extraction,
prefer replays of stored captures.

**Explain the number.** Every reported metric says what bounds it and what else it could be measuring: skipped
pages, cached work, abstentions that look like precision, or cells too small to mean anything. Keep the run count
and n with the number. An eval result reported without its n is not a result.

## Changing code

**Fix root causes (C5).** Reproduce first. Ask "why" until you reach the cause, and fix it there.
- Never add a guard that silences a symptom.
- If a workaround needs a paragraph of comment to justify it, the code is wrong.
- Check for the *class* of failure, not just the instance. A failure that only one site shows is fixed with
  data, not code.

**Attack the premise.** When two fixes resting on the same assumption fail the same check, stop fixing. Write the
assumption down and test it.

**Subtract before you add (C13).** Default to removing complexity. Design for observed failures, not speculative
ones. Add no validators, parsers, guards or options beyond what the spec asks for. Build no §22 candidate without
evidence.

**Minimize reader load (C11).** What matters is how much a reader must trace and hold in their head, not line
counts. C11's two checks measure that only roughly: cognitive complexity of at most 15 per function (a hard
check), and 800 lines per file (a warning).
- Bring a complex function down by meaning: extract named steps, replace branch chains with dispatch tables, and
  split a module by responsibility. Never by moving lines into a helper with no name of its own.
- A file past 800 lines is split along logical boundaries (cohesive modules, field types per C8), never
  mechanically.
- Inline wrappers that have one caller, and adapters that have no second implementation.
- Prefer pure functions and local state.
- A new reader should be able to answer "where does X come from, and what can change it?" in 30 seconds.

**Migrate callers, then delete.** Nothing external depends on internals yet. When an internal API changes, move
every caller in the same PR and delete the old path. Leave no compatibility shims.

## Structure

**Boundary discipline.** Validate and parse at system boundaries: HTTP requests, CLI args, settings, DB rows, page
content, LLM output. Pydantic models and typed results are the boundary. Inside, trust the types; don't
re-validate. Business logic lives in pure functions, and FastAPI routes, workers and CLI commands are thin shells
around them.

**Model the domain.** Put the domain in data structures instead of conditionals. Examples from this design:
- the `Ok | Ambiguous | Invalid` normalizer result;
- the `url_task` state machine;
- the field-type registry;
- the IR step union.

A new feature that adds one more branch to an existing if/elif chain, or a second flag that must stay in sync with
the first, is the sign the model is missing.

**Type-system discipline.** Make impossible states unrepresentable.
- Use discriminated unions over bags of optional fields.
- Use `NewType` for IDs that must not mix (`SiteId`, `CaptureId`).
- Match exhaustively (`assert_never`; `never` in TypeScript).
- Derive types from their authority: the OpenAPI schema generates the TS client, and the SQLAlchemy models plus
  Alembic own the DB shape.
- No `Any`, `cast` or `# type: ignore` without a boundary check that justifies it.

**Make operations idempotent.** Queue tasks, migrations, learning jobs and eval commands must converge to the same
state if they run twice or crash halfway. Ask: what happens if this runs twice? What if the previous run died at
each step?

**Separate before serializing shared state.** Before two actors write one thing, ask whether they need to. Give
each its own row, key or file, and merge at read time. Where one shared target is a real invariant, serialize in
structure (`SKIP LOCKED`, unique constraints, a single writer), not by convention.

## Working autonomously

**Never block on the human for reversible work.** Decide, proceed, and log the decision in `DECISIONS.md`; the
owner corrects after the fact. The exceptions are in `CLAUDE.md` §4. Architecture changes, §22 candidates,
evaluation access, secrets and irreversible actions are escalated, never decided.

**Own the exit condition.** Before starting, state "done" as a checkable predicate, for example "acceptance
criteria 1–4 pass; `make check` green; dev delta posted". Drive to it. A plateau is not a stop: change approach.
Never relax the predicate to declare victory. A real dead end, after three honest attempts, is escalated.

**Encode lessons in structure.** When the same mistake recurs, fix it with the strongest tool that works, in this
order: types, a lint or import contract, a CI check, a test. A sentence in a doc comes last. A rule nothing
enforces is a symptom.
