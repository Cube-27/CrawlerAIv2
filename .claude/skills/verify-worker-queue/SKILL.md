---
name: verify-worker-queue
description: Model-check the worker/queue concurrency (claim, lease, deadline, retry, lease release, job settling, per-host pacing, the shared browser's context cap) with TLA+/TLC. Use for any change to backend/src/crawlerai/worker/loop.py, worker/handlers/steps.py (fetch_queued), db/queue.py, db/jobs.py, db/usage.py, crawl/frontier.py, worker/handlers/ (count_fetch and the frontier lock the job row), scheduler/loop.py, services/polite.py, acquire/politeness.py, acquire/shared_browser.py, or tools/verify/; and when asked whether tasks can get stuck, run twice, or overload a host.
---

# Verify the worker and queue

A TLA+ model of how worker processes claim url_task rows, run them under a deadline, record results, and how the
scheduler releases expired leases, checked by TLC over every interleaving within small bounds. Tests show some
orders; this checks all of them, including a page that hangs, a worker that dies holding leases, and work left behind
after its cancellation.

- Model: `tools/verify/worker_queue/WorkerQueue.tla` (every action cites its code), instances in `MC.tla`, shared
  constants in `base.cfg`.
- Runner: `tools/verify/worker_queue.py` (standard library; pinned `tla2tools.jar` v1.7.4, sha256 `936a2620...`; a
  pinned Temurin 21 JRE is fetched when no `java` 11+ is on PATH; cache and TLC logs in `~/.cache/crawlerai-tla/`).
- CI: the `verify-worker-queue` job in `.github/workflows/ci.yml`, run when a changed path is one of its inputs in
  `tools/ci_changes.py` (`verify_worker_queue`).

## Does my change touch it?

```sh
{ git diff --name-only origin/main...; git diff --name-only HEAD; } | sort -u | grep -E 'worker/loop\.py|worker/handlers/|db/queue\.py|db/jobs\.py|db/usage\.py|crawl/frontier\.py|scheduler/loop\.py|services/polite\.py|acquire/politeness\.py|acquire/shared_browser\.py|tools/verify/'
```

(The first diff is your commits, the second what is not committed yet.) Any output: run the check. Also run it when a change elsewhere alters what these rely on: a new await or transaction
between a task's claim and its result, a new lock on `url_task` or `job` rows, a new caller of `claim_tasks`,
`fail_task` or `HostLimiter`, or a change to `TASK_SLOTS`, `TASK_DEADLINE`, `CANCEL_GRACE`, `_LOCK_WAIT`, `LEASE`,
`MAX_ATTEMPTS`, `QUEUED.bound` or `BROWSER_CONTEXTS`.

## Run

```sh
make verify-worker-queue        # = python3 tools/verify/worker_queue.py: checks, findings, mutants (about 1 minute)
python3 tools/verify/worker_queue.py left-behind mutant-no-deadline   # only the named checks
```

Exit 0 and one `ok` line per check means the code still keeps every property within the bounds. `TLC_HEAP` sets the
JVM heap (default `1500m`).

## What it checks

| Property | In one sentence | What breaks for users if it fails |
| --- | --- | --- |
| `TaskTerminates` | every claimed task reaches `done` or `failed`, even if its page hangs, its worker dies, or its work is left behind | a page never gets a result |
| `JobFinishes` | every job ends `completed` or `failed` | a crawl stays `running` forever; no webhook, no listing diff |
| `NoDoubleProcessing` | at most one run of a task that has not been cancelled exists at a time | a page is fetched and extracted twice at once |
| `SlotCap` | a worker never runs more than `TASK_SLOTS` tasks | memory and connection pool exhausted |
| `BrowserCap` | a worker's shared browser never renders more than `BROWSER_CONTEXTS` pages at once | renderer processes exhaust memory |
| `HostSpacing` | a request goes to a host only when the worker's `HostLimiter` has its turn due | a site gets more than one request per interval from a worker |
| `HostOneInFlight` | never two requests in flight to one host | a slow site gets parallel load (known finding, below) |
| `NoDoubleProcessingStrict` | not even work left behind runs beside a new claim of its task | duplicate requests from left-behind work (known finding) |

Checks (instances in `worker_queue.py` `INSTANCES`; each checks every property in the first six rows):

- `two-workers`: 2 workers x 1 slot, 2 tasks of one job on one host, 2 attempts, one worker death, one hang.
- `left-behind`: 2 workers x 1 slot, 2 tasks, 1 attempt, one hang, one cancellation left behind.
- `slots`: 1 worker x 2 slots, 3 tasks on one host, 1 attempt: a postponed task comes due while a slot is busy, so a
  claim runs with fewer free slots than due tasks.
- `browser`: 1 worker x 3 slots, 3 tasks on 3 hosts, 1 attempt, one hang.

Time is ticks with the code's order: host interval <= `QUEUED.bound` < a 429's pause; `TASK_DEADLINE` < `LEASE`;
`CANCEL_GRACE` + `_LOCK_WAIT` fit inside one tick.

## Known findings (the code breaks a requested property; they stay listed until the code changes)

`FINDINGS` in `worker_queue.py` must keep failing with exactly that property; a finding that starts passing fails the
run, so whoever fixed it moves it to `CHECKS`.

1. `finding-host-in-flight` (HostOneInFlight): one worker claims t1 and t2 on one host; t1's first turn is admitted
   and its request is still in flight when the host's interval passes; t2's `HostLimiter.admit` is then due and its
   request goes too. The limiter spaces request starts; it never waits for an answer, so any page slower than the
   site's interval (1 s by default; the HTTP timeout is 10 s, renders longer) overlaps the next. Each worker process
   also paces on its own (`politeness.py` docstring accepts that).
2. `finding-left-behind-beside-reclaim` (NoDoubleProcessingStrict): w1's run of t1 stalls holding job j1's row lock
   (taken by `count_fetch`'s usage UPDATE at the handler's end, or by `settle_job`, until the commit); t2 (same job, on w2) reaches its deadline and its cancellation is ignored (left behind); the
   deadline `fail_task` hits `lock_timeout` on the job row and gives up; t2's lease expires;
   `release_expired_leases` requeues it and w1 claims it again while w2's left-behind work of t2 still runs. The fence
   keeps the stale result out, but both runs send requests.
3. `finding-left-behind-hangs-on-its-row` (TaskTerminates): left-behind work that never ends while holding its
   url_task row lock (between the fenced UPDATE and the commit) blocks the deadline failure (`lock_timeout`), and
   `release_expired_leases` skips the row (`SKIP LOCKED`) every minute: the task stays `claimed` and its job
   `running` until the process exits. Nothing (e.g. `idle_in_transaction_session_timeout`) bounds that transaction.

## Reading a failure

A `FAIL` line names the check, what TLC found and the log path, then the counterexample as numbered steps: the action
taken and the variables it changed (`run[w1,1]` is worker w1's first slot record: `pc` where its work is, `dl` its
`_run_within_deadline` coroutine, `cancelled` left behind, `stuck` hung). Map each action to the code:

| Action | Code |
| --- | --- |
| `Claim(w)` | `run_worker`: `free`, `claim_tasks` transaction (FOR UPDATE SKIP LOCKED, lease, `attempts + 1`, `start_jobs`), `create_task(run(task))` |
| `Turn` | `polite_fetch` -> `_first_turn` -> `HostLimiter.admit`; not due -> `Later` -> `Postpone`; or the task ends with no request (robots.txt disallow, stored capture reread) |
| `HttpDone` | the HTTP rung answers: ok, 429/503 (`pause_host`, `Failed(transient)`), or escalate to the browser; an answer the handler ends with is extracted and counted (`count_fetch` updates `job.usage`: job row locked until commit) |
| `AdmitNext` | the browser retry's `admit_next` = `HostLimiter.wait(host, gap, QUEUED.bound)` |
| `AcquireContext`, `RenderDone` | `SharedBrowser.fetch`: `async with self._contexts`, the render |
| `UpdateRow` | `_move`'s fenced UPDATE (row lock); no row -> `LeaseLost`, rollback |
| `LockJob`, `Commit` | `settle_job`'s FOR NO KEY UPDATE on the job (already held after `count_fetch`), `settled_status`, commit |
| `DeadlineFires` | `asyncio.wait(timeout=TASK_DEADLINE)` expires, `work.cancel()`, `CANCEL_GRACE`; ends or `_LEFT_BEHIND` |
| `DeadlineFail` | `fail_task(DEADLINE, transient=False)` under `lock_timeout`; gives up (DBAPIError) on a lock held by hung or left-behind work |
| `LateCancel` | left-behind work takes its cancellation later and rolls back |
| `ReleaseExpired(t)` | scheduler `release_expired_leases` (SKIP LOCKED, `fail_task("lease expired", transient=True)`) |
| `Hang`, `Die(w)` | faults: an await that never returns; a worker process dies (PostgreSQL rolls back its transactions) |
| `Tick` | time passes; never past a due deadline or a pending deadline failure |

### Real bug or modeling error?

Replay the steps against the code. It is a **real bug** when every step is something the code can do in that order:
each await the model splits at is an await in the code, each step the model makes atomic is one transaction or one
stretch without an await, and every guard matches the code's condition. Report it in the code's words (as the
findings above are) before changing anything; never weaken the property, add fairness to a fault (`Hang`, `Die`,
`LateCancel`, a left-behind cancellation), or shrink the bounds to make it pass.

It is a **modeling error** when a step cannot happen in the code: two steps the code does in one transaction, a guard
the code has that the action lacks, a lock the code takes that the model does not (or the reverse), or a timing the
code rules out (a deadline later than a lease). Fix the action and cite the code line that justifies it in its
comment. Then run the checks: every mutant must still be caught, or the fix hid a property.

A TLC `Error: ... Attempted to ...` or parse error is a broken model, not a finding: fix the spec.

A change that makes the code do what a mutant does (`MUTANTS` in `worker_queue.py`, each with the code edit it
mirrors) is a real bug once the model is updated to match: the default checks must then fail. If they pass, the
instances cannot reach the case: add or grow an instance until the mutant's property fails there, and never delete the
mutant to get a pass.

## Updating the model for an intended change

1. Find the actions whose comments cite the code you changed (`grep -n 'claim_tasks' tools/verify/worker_queue/WorkerQueue.tla`).
2. Change them to do what the code now does, keeping one action per transaction or await-free stretch, and the
   comment's citation current. A new constant gets a line in `base.cfg` or the instance in `worker_queue.py`, with the
   code's order between values kept (deadline < lease, interval <= bound < pause).
3. A new guard or mechanism that a property depends on gets a mutant: a `Bug` value in the spec that removes it, and a
   `Check` in `MUTANTS` that expects the property it protects to fail. Run the checks and see it caught.
4. A change that should fix a finding: move its `Check` from `FINDINGS` to `CHECKS` (`expect=None`).
5. Run the checks; keep the run near one minute. If bounds must grow, say so in the PR.

## What this does not cover

- The SQL itself: that `claim_tasks` takes at most `n` due rows each claimed once under concurrency, the fence's
  UPDATE, READ COMMITTED. The model assumes them; `tests/db/test_queue.py` and
  `test_2_claimers_take_20_tasks_each_exactly_once_and_at_most_7_a_claim` in `tests/db/test_worker.py` ground them.
- Claim order (priority, round robin between jobs, score): any due tasks may be claimed.
- Job cancellation (`cancel_requested`, `Skipped`, `cancel_task`), `insert_claimed` (synchronous scrape), tasks a crawl
  adds while it runs, `fail_stalled_jobs`, worker stop.
- `SharedBrowser`'s restart after a crash; the listing scrape's own browser (outside the cap, acquisition spec);
  adapters, recipes and robots.txt reads; `HostLimiter`'s adaptive spacing arithmetic.
- Timing beyond order: a blocked event loop that delays the deadline timer past `LEASE - TASK_DEADLINE` breaks
  `NoDoubleProcessing`; the model assumes timers fire on time and that a running transaction holds a row lock for
  less than `_LOCK_WAIT` (the job row from `count_fetch` to the commit: the frontier's writes and `_move`).
- Sizes beyond the bounds above (at most 2 workers, 3 slots, 3 tasks, 1 job, 2 attempts, one fault of each kind).
