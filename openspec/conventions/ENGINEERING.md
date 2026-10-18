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

**Run little locally; CI runs everything (owner, 2026-10-15 and 2026-10-16).** Locally, run only the test files for
the files you changed, one file at a time, and fmt, lint and type-check only those files. Never the full suite, a
whole test directory, `make check`, a repo-wide type check or the full e2e: CI runs them on every push, so read CI.
Never `pytest -n` locally (CI's backend job runs xdist workers, each with its own test databases); vitest runs with
`--maxWorkers=1`. DB tests use the one shared local test Postgres (`eval "$(tools/orchestrator/test_db.sh up)"`), a
database pair per worktree, never a container of your own.

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
every caller in the same PR and delete the old path. Leave no compatibility shims. An architecture change deletes
what it supersedes in the same PR, and the specs and design documents it touches describe one architecture after it
(owner, 2026-10-18).

**Cite the requirement, not the history (owner, 2026-10-18).** New code, comments and docstrings cite the capability
spec requirement (`extraction spec, "Listing rows"`) or the standard a rule rests on, never a decision ID (`D-NNNN`)
or a frozen `ARCHITECTURE §N`/`SPEC-NN §x` section; existing citations are replaced when the code around them changes.
Decision entries keep their IDs; only code stops pointing at them.

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

**Never block on the human for reversible work.** Decide, proceed, and log the decision (`openspec/decisions/README.md`); the
owner corrects after the fact. The exceptions are in `CLAUDE.md` §4. Architecture changes, §22 candidates,
evaluation access, secrets and irreversible actions are escalated, never decided.

**Own the exit condition.** Before starting, state "done" as a checkable predicate, for example "acceptance
criteria 1–4 pass; `make check` green; dev delta posted". Drive to it. A plateau is not a stop: change approach.
Never relax the predicate to declare victory. A real dead end, after three honest attempts, is escalated.

**Encode lessons in structure.** When the same mistake recurs, fix it with the strongest tool that works, in this
order: types, a lint or import contract, a CI check, a test. A sentence in a doc comes last. A rule nothing
enforces is a symptom.

## Patterns the analysers flag

SonarCloud checks every PR. These rules fired more than once here (SonarCloud issue history to 2026-10-15); write
the right pattern first. A finding that misreads the code (a protocol method that must be `async` or keep an unused
parameter) is explained in the PR body, never suppressed.

Python:
- **S5778 one call in `pytest.raises` (ruff `PT012` sees statements, not nested calls):** build arguments before the `with`; the block holds only the raising call.
- **S9073 one fact per `assert` (ruff `PT018`):** `assert a == 1` and `assert b == 2`, not `assert a == 1 and b == 2`.
- **S3776 cognitive complexity ≤ 15:** extract named steps (complexipy enforces it, C11).
- **S6353 concise regex classes:** `\d`, `\w`, not `[0-9]`, `[A-Za-z0-9_]`.
- **S1192 repeated literal:** a literal used three or more times becomes a named constant that cites its standard.
- **S7503 needless `async`:** a function that awaits nothing is sync, unless a protocol or framework requires a
  coroutine.
- **S1172 unused parameter:** remove it, unless a protocol defines the signature.
- **S7519 same value for every key (ruff `C420`):** `dict.fromkeys(keys, value)`, not a comprehension.
- **S8409 FastAPI `response_model` (ruff `FAST001`):** omit it when the return annotation already says the type.
- **S9100 fixture without teardown (ruff `PT022`):** `return`, not `yield`.
- **S5713 redundant `except`:** don't catch a subclass beside its base class in one `except`.

TS/TSX:
- **S6759 read-only props:** `({ title }: Readonly<CardProps>)`, inline prop types too.
- **S6479 list keys (Oxlint `react/no-array-index-key`):** key rows by a stable id, never the array index; give editor-only rows an id at creation.
- **S3358 nested ternary (Oxlint `no-nested-ternary`):** an `if` chain, a lookup table or a named helper.
- **S1186 empty method (Oxlint `no-empty-function`):** a stub says why in a comment (`// no-op: jsdom has no layout`).
- **S7718 catch parameter (Oxlint `unicorn/catch-error-name`):** name it `error` (`error_` when `error` is taken).
- **S9382 `await` in a loop:** `Promise.all` when iterations are independent; a sequential loop (backoff, cursor
  pagination) is explained in the PR body.

Shell (`tools/orchestrator/*.sh`) and CI:
- **S7688 `[[ ]]`, not `[ ]`; S7677 errors to stderr (`>&2`); S7679 positional parameters into named variables
  (`name=$1`); S7682 a function ends with an explicit `return` or `exit`.**
- **GitHub Actions S8541/S8544:** install from the lockfile and build nothing third-party: `uv sync --frozen
  --no-build`, `uv run --no-sync --no-build`, `pnpm install --frozen-lockfile`.
