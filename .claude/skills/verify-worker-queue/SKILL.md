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
  `tools/ci_changes.py` (`verify_worker_queue`), as three parallel shards (`--shard 1/3` .. `3/3`) that together run
  every check, finding and mutant.

## Does my change touch it?

```sh
{ git diff --name-only origin/main...; git diff --name-only HEAD; } | sort -u | grep -E 'worker/loop\.py|worker/handlers/|db/queue\.py|db/jobs\.py|db/usage\.py|crawl/frontier\.py|scheduler/loop\.py|services/polite\.py|acquire/politeness\.py|acquire/shared_browser\.py|tools/verify/'
```

(The first diff is your commits, the second what is not committed yet.) Any output: run the check. Also run it when a change elsewhere alters what these rely on: a new await or transaction
between a task's claim and its result, a new lock on `url_task` or `job` rows, a new caller of `claim_tasks`,
`fail_task` or `HostLimiter` (`admit`, `wait`, `holding`), a request sent outside `polite_fetch`'s hold, or a change
to `TASK_SLOTS`, `TASK_DEADLINE`, `CANCEL_GRACE`, `_LOCK_WAIT`, `_END_SESSION`, `LEASE`, `MAX_ATTEMPTS`,
`QUEUED.bound` or `BROWSER_CONTEXTS`.

## Run

```sh
make verify-worker-queue        # = python3 tools/verify/worker_queue.py: checks, findings, mutants (about 2 minutes)
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
| `HostSpacing` | a request goes to a host only when its turn is due for every worker (`host_turn.next_at`) | a site gets more than one request per interval |
| `HostOneInFlight` | no two requests are in flight to one host from any workers, robots.txt's included (owner plan P1; the hold is shared through `host_turn`) | a slow site gets parallel load |
| `NoDoubleProcessingStrict` | not even work left behind runs beside a new claim of its task | duplicate requests from left-behind work |

Checks (instances in `worker_queue.py` `INSTANCES`; each checks every property):

- `two-workers`: 2 workers x 1 slot, 2 tasks of one job on one host, 2 attempts, one worker death, one hang.
- `left-behind`: 2 workers x 1 slot, 2 tasks, 1 attempt, one hang, one cancellation left behind.
- `slots`: 1 worker x 2 slots, 3 tasks on one host, 1 attempt: a postponed task comes due while a slot is busy, so a
  claim runs with fewer free slots than due tasks.
- `browser`: 1 worker x 3 slots, 3 tasks on 3 hosts, 1 attempt, one hang; robots.txt snapshots fresh (a stale one's
  request spends the tick a render needs within the deadline; the same-host instances request robots.txt).
- `host-in-flight`: `two-workers` with 1 worker x 2 slots: t2's turn comes due while t1's request is in flight.
- `left-behind-reclaim`: `left-behind` with 2 attempts: one run stalls holding the job row while another task's work
  is left behind, so its deadline failure must wait rather than leave the task to its lease.
- `left-behind-hangs`: `left-behind` where the work left behind may never end, holding its url_task row lock.

Time is ticks with the code's order: host interval <= `QUEUED.bound` < a 429's pause; `CANCEL_GRACE` fits inside one
tick; a deadline failure waiting for hung work's lock waits at most that work's own deadline (one more tick, within
`_LOCK_WAIT`), and both end inside `LEASE` (`Lease` = 3 ticks: 6 min 40 s < 10 min).

How the code keeps the last two rows (the findings the model first reported):

- `HostLimiter.holding` (entered by `polite_fetch` before robots.txt's or the page's first turn, held until the fetch
  returns, browser retry and paging included): the first request `admit` admits in it takes the host's turn and hold
  in `host_turn` in one upsert (`acquire/host_turns.py`), so no other task of any process is admitted to the host
  meanwhile; it answers the spacing as the wait (a worker postpones). The hold is a lease (`HOLD_LEASE`) renewed while
  its holder runs and given up as the holder ends or is cancelled, so a dead process or work left behind holds the
  host at most a lease. A holder being cancelled holds nothing, and `admit` raises `CancelledError` in a task being
  cancelled, so work left behind neither blocks its host nor sends a request.
- `_run_within_deadline`: work left behind has its database session ended (`_END_SESSION`: `pg_terminate_backend` of
  the session whose `application_name` names the claim, set LOCAL in `_run`), so it holds no row lock; the deadline
  failure then waits up to `_LOCK_WAIT` (`TASK_DEADLINE + CANCEL_GRACE` + 10 s, the longest another run's
  transaction can hold a lock) and lands before the lease expires: the task ends `failed` and is never claimed again
  while that work runs.

## Known findings (the code breaks a requested property; they stay listed until the code changes)

None open. A finding goes in `FINDINGS` in `worker_queue.py` and must keep failing with exactly that property; a
finding that starts passing fails the run, so whoever fixed it moves it to `CHECKS`.

## Reading a failure

A `FAIL` line names the check, what TLC found and the log path, then the counterexample as numbered steps: the action
taken and the variables it changed (`run[w1,1]` is worker w1's first slot record: `pc` where its work is, `dl` its
`_run_within_deadline` coroutine, `cancelled` left behind, `stuck` hung). Map each action to the code:

| Action | Code |
| --- | --- |
| `Claim(w)` | `run_worker`: `free`, `claim_tasks` transaction (FOR UPDATE SKIP LOCKED, lease, `attempts + 1`, `start_jobs`), `create_task(run(task))` |
| `Turn` | `polite_fetch` -> `holding`, then `rules_of`'s robots.txt request (stale snapshot) or `_first_turn` -> `HostLimiter.admit` -> `HostTurns.take` (turn and hold in one upsert); not due, or the host held by another task of any worker -> `Later` -> `Postpone`; or the task ends with no request (robots.txt disallow, stored capture reread) |
| `RobotsDone`, `PageTurn` | robots.txt answers (snapshot stored, or unreachable -> `Failed`); the page's turn waited for in place (`_first_turn(sent=True)`), postponed past `QUEUED.bound` |
| `HttpDone` | the HTTP rung answers: ok, 429/503 (`pause_host`, `Failed(transient)`), or escalate to the browser; an answer the handler ends with is extracted and counted (`count_fetch` updates `job.usage`: job row locked until commit) |
| `AdmitNext` | the browser retry's `admit_next` = `HostLimiter.wait(host, gap, QUEUED.bound)`; in work being cancelled, `admit` raises and the work ends |
| `AcquireContext`, `RenderDone` | `SharedBrowser.fetch`: `async with self._contexts`, the render |
| `UpdateRow` | `_move`'s fenced UPDATE (row lock); no row -> `LeaseLost`, rollback |
| `LockJob`, `Commit` | `settle_job`'s FOR NO KEY UPDATE on the job (already held after `count_fetch`), `settled_status`, commit |
| `DeadlineFires` | `asyncio.wait(timeout=TASK_DEADLINE)` expires, `work.cancel()`, `CANCEL_GRACE`; ends or `_LEFT_BEHIND`: in cleanup (`behind`, `behindctx` holding a browser context), on to its next admission (`admit`), or still in its transaction |
| `DeadlineFail` | `_END_SESSION` for work left behind (its transaction rolls back), then `fail_task(DEADLINE, transient=False)` under `lock_timeout = _LOCK_WAIT`, waiting for hung work's own deadline |
| `Behind` | left-behind work's cleanup returns and it ends |
| `ReleaseExpired(t)` | scheduler `release_expired_leases` (SKIP LOCKED, `fail_task("lease expired", transient=True)`) |
| `Hang`, `Die(w)` | faults: an await that never returns; a worker process dies (PostgreSQL rolls back its transactions; its holds in `host_turn` stay until `HOLD_LEASE` lapses: `stale`) |
| `Tick` | time passes; never past a due deadline or a pending deadline failure; a stale hold lapses (`held_until`) |

### Real bug or modeling error?

Replay the steps against the code. It is a **real bug** when every step is something the code can do in that order:
each await the model splits at is an await in the code, each step the model makes atomic is one transaction or one
stretch without an await, and every guard matches the code's condition. Report it in the code's words (as the
"How the code keeps" notes above are) before changing anything; never weaken the property, add fairness to a fault
(`Hang`, `Die`, a left-behind cancellation), or shrink the bounds to make it pass.

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
5. Run the checks; keep the run near two minutes. If bounds must grow, say so in the PR.

## What this does not cover

- The SQL itself: that `claim_tasks` takes at most `n` due rows each claimed once under concurrency, the fence's
  UPDATE, READ COMMITTED, and that `HostTurns.take` gives a turn and a hold to one holder. The model assumes them;
  `tests/db/test_queue.py`, `test_2_claimers_take_20_tasks_each_exactly_once_and_at_most_7_a_claim` in
  `tests/db/test_worker.py` and `tests/db/test_host_turns.py` ground them.
- Claim order (priority, round robin between jobs, score): any due tasks may be claimed.
- Job cancellation (`cancel_requested`, `Skipped`, `cancel_task`), `insert_claimed` (synchronous scrape), tasks a crawl
  adds while it runs, `fail_stalled_jobs`, worker stop.
- `SharedBrowser`'s restart after a crash; the listing scrape's own browser (outside the cap, acquisition spec);
  adapters and recipes; `HostLimiter`'s adaptive spacing arithmetic (the model's spacing is shared; the adaptive part
  is per process); the browser's recycling.
- Timing beyond order: a blocked event loop that delays the deadline timer past `LEASE - TASK_DEADLINE` breaks
  `NoDoubleProcessing`; the model assumes timers fire on time, that a running transaction commits at once (the job
  row from `count_fetch` to the commit: the frontier's writes and `_move`), and that PostgreSQL grants a waited-for
  row lock in queue order (the deadline failure is not overtaken by a later run's lock).
- Sizes beyond the bounds above (at most 2 workers, 3 slots, 3 tasks, 1 job, 2 attempts, one fault of each kind).
