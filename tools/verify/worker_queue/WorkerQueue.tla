---------------------------- MODULE WorkerQueue ----------------------------
(***************************************************************************)
(* The worker and queue concurrency of backend/src/crawlerai:               *)
(*   worker/loop.py        run_worker, _run_within_deadline, _run, _execute *)
(*   db/queue.py           claim_tasks, fail_task, release_task,            *)
(*                         release_expired_leases, _move (the fence),       *)
(*                         settle_job, TASK_DEADLINE, LEASE, MAX_ATTEMPTS   *)
(*   services/polite.py    polite_fetch, _first_turn (Later -> Postpone),   *)
(*                         pause_host, QUEUED (the capped in-place wait)    *)
(*   acquire/politeness.py HostLimiter.admit / wait / pause                 *)
(*   acquire/shared_browser.py SharedBrowser.fetch, BROWSER_CONTEXTS        *)
(*                                                                         *)
(* One TLA+ step is one indivisible step of the code: a committed database *)
(* transaction, or the code between two awaits. A task's own transaction  *)
(* (_run: `async with conn.begin()`) is split where other transactions can *)
(* see or block on it: the fenced UPDATE of its url_task row (takes the    *)
(* row lock), the job row lock (settle_job's FOR NO KEY UPDATE), and the   *)
(* commit, which releases both. Everything a transaction wrote before its  *)
(* commit is invisible to the others (READ COMMITTED), so the read of      *)
(* open tasks in settle_job is folded into the commit step: it runs while  *)
(* the job row lock is held and no other transaction can commit a task of  *)
(* that job in between.                                                    *)
(*                                                                         *)
(* Time is a discrete Tick. A countdown at 0 means "due". Timers fire on   *)
(* time: no Tick passes while a task is at its deadline or its deadline    *)
(* failure is still being recorded (CANCEL_GRACE + _LOCK_WAIT, 25 s, fit   *)
(* inside one tick; one tick is less than LEASE - TASK_DEADLINE).          *)
(*                                                                         *)
(* `Bug` selects a broken variant of the code, to show that each property  *)
(* can fail (MUTANTS in tools/verify/worker_queue.py). "none" is the code.   *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    Workers,        \* worker processes (run_worker), each with its own HostLimiter and SharedBrowser
    Slots,          \* loop.TASK_SLOTS
    Tasks,          \* url_task rows
    JobOf,          \* url_task.job_id
    HostOf,         \* the host of url_task.url
    MaxAttempts,    \* queue.MAX_ATTEMPTS
    Deadline,       \* queue.TASK_DEADLINE, in ticks
    Lease,          \* LEASE (db/queue.py), in ticks
    Spacing,        \* the host's interval (HostLimiter.spacing), in ticks
    Bound,          \* polite.QUEUED.bound: the longest in-place wait for a further turn, in ticks
    Pause,          \* HostLimiter.pause after a 429/503 (pause_host), in ticks; longer than Bound
    Backoff,        \* the delay before a requeued task is due (backoff_delay, Retry-After, Later.wait), in ticks
    Contexts,       \* shared_browser.BROWSER_CONTEXTS
    MaxDeaths,      \* worker processes that die (the process restarts, with a new worker id)
    MaxHangs,       \* awaits that never return (a page, a render, a database call)
    MaxLeftBehind,  \* cancellations that do not end within CANCEL_GRACE (loop._LEFT_BEHIND)
    LeftBehindHangs,\* whether work left behind may also never end
    Bug,            \* "none", or the broken variant checked (see Mutants in worker_queue.py)
    None

Jobs == {JobOf[t] : t \in Tasks}
Hosts == {HostOf[t] : t \in Tasks}
TasksOf(j) == {t \in Tasks : JobOf[t] = j}
Min(a, b) == IF a < b THEN a ELSE b
Max(a, b) == IF a > b THEN a ELSE b
Dec(n) == IF n > 0 THEN n - 1 ELSE 0

\* A run is one claimed task in one worker: `run(task)` of run_worker, i.e. the _run_within_deadline coroutine (`dl`)
\* and the work it awaits (`pc`, the coroutine `run()` -> _run -> _execute -> handler). Work left behind outlives its
\* slot, so a worker has records for its slots and for the work it left behind.
Records == Workers \X (1 .. (Slots + MaxLeftBehind + (IF Bug = "claim_slots_not_free" THEN Slots ELSE 0)))

\* pc: where the work is.
\*   "turn"     polite_fetch -> _first_turn: HostLimiter.admit for the first request (QUEUED.postpone)
\*   "http"     the first request in flight (the HTTP rung)
\*   "admit"    the browser retry waiting in place for its turn (admit_next = HostLimiter.wait, up to QUEUED.bound)
\*   "ctx"      SharedBrowser.fetch waiting for a context (`async with self._contexts`)
\*   "render"   the browser request in flight, holding a context
\*   "update"   the handler returned; _execute calls complete_task / fail_task / release_task: the fenced UPDATE.
\*              A run that sent a request holds its job's row lock already: the handler's count_fetch (steps.py)
\*              updated job.usage as its last write (db/usage.py record_usage), in the task's transaction
\*   "locked"   the url_task row is updated and locked; settle_job is taking the job row lock
\*   "settling" both locks held; settle_job reads the open tasks, `ending`, commit
IdleRun == [pc |-> "idle", task |-> None, age |-> 0, cancelled |-> FALSE, stuck |-> FALSE,
            res |-> "none", dl |-> "none", snap |-> FALSE]

VARIABLES
    status,     \* url_task.status (committed): "queued" | "claimed" | "done" | "failed"
    attempts,   \* url_task.attempts (committed)
    leaseLeft,  \* ticks until url_task.lease_until passes
    backoff,    \* ticks until url_task.next_attempt_at
    holder,     \* the run whose claim the row's (claimed_by, lease_until) identifies, or None
    job,        \* job.status: "queued" | "running" | "completed" | "failed"
    run,        \* Records -> the run's state (IdleRun's fields)
    hostNext,   \* [w][h]: ticks until worker w's HostLimiter admits a request to h (HostLimiter._next)
    deaths, hangs, lefts

vars == <<status, attempts, leaseLeft, backoff, holder, job, run, hostNext, deaths, hangs, lefts>>

Live(r) == run[r].pc # "idle"
\* PostgreSQL row locks, held by a transaction from its UPDATE / SELECT FOR UPDATE until it commits or rolls back.
RowLocked(t) == \E r \in Records : run[r].pc \in {"locked", "settling"} /\ run[r].task = t
\* The job row: settle_job's FOR NO KEY UPDATE, or earlier count_fetch's UPDATE of job.usage (a run that sent a request;
\* a Postpone sent none and counts nothing). Both conflict with each other and with settle_job's lock.
HoldsJob(r) == \/ run[r].pc = "settling"
               \/ run[r].pc \in {"update", "locked"} /\ run[r].res \in {"finished", "transient"}
JobLocked(j) == \E r \in Records : HoldsJob(r) /\ JobOf[run[r].task] = j
JobLockedByOther(r) == \E o \in Records \ {r} : HoldsJob(o) /\ JobOf[run[o].task] = JobOf[run[r].task]
InFlight(h) == {r \in Records : run[r].pc \in {"http", "render"} /\ HostOf[run[r].task] = h}
BrowserContexts(w) == {r \in Records : r[1] = w /\ run[r].pc = "render"}
\* run_worker's `running`: the _run_within_deadline coroutines it has started and not yet seen end.
Running(w) == {r \in Records : r[1] = w /\ run[r].dl # "none"}
FreeRecords(w) == {r \in Records : r[1] = w /\ run[r] = IdleRun}
\* claim_tasks' rows: queued, due (next_attempt_at <= now()), not locked by another transaction (SKIP LOCKED).
Due == {t \in Tasks : status[t] = "queued" /\ backoff[t] = 0 /\ ~RowLocked(t)}

\* settle_job: the status a running job ends in once no task of it is queued or claimed (settled_status).
Settled(j, st, open) ==
    IF job[j] # "running" \/ open THEN job[j]
    ELSE IF \A u \in TasksOf(j) : st[u] = "failed" THEN "failed" ELSE "completed"
OpenIn(j, st) == \E u \in TasksOf(j) : st[u] \in {"queued", "claimed"}
SettleAll(st, j) == [job EXCEPT ![j] = Settled(j, st, OpenIn(j, st))]

\* fail_task's transient branch (retried: attempts < MAX_ATTEMPTS) or its end ("failed").
FailTransient(t) == IF attempts[t] < MaxAttempts THEN "queued" ELSE "failed"

\* The work ends (returns or raises). The deadline coroutine of a run that was not cancelled returns with it; one
\* whose work was left behind already moved on.
EndWork(r) ==
    IF run[r].dl = "dfail" THEN [IdleRun EXCEPT !.task = run[r].task, !.dl = "dfail"] ELSE IdleRun

Init ==
    /\ status = [t \in Tasks |-> "queued"]
    /\ attempts = [t \in Tasks |-> 0]
    /\ leaseLeft = [t \in Tasks |-> 0]
    /\ backoff = [t \in Tasks |-> 0]
    /\ holder = [t \in Tasks |-> None]
    /\ job = [j \in Jobs |-> "queued"]
    /\ run = [r \in Records |-> IdleRun]
    /\ hostNext = [w \in Workers |-> [h \in Hosts |-> 0]]
    /\ deaths = 0 /\ hangs = 0 /\ lefts = 0

-----------------------------------------------------------------------------
(* run_worker: `free = TASK_SLOTS - len(running)`; if free, one transaction claim_tasks(conn, worker, free), whose  *)
(* SELECT ... FOR UPDATE SKIP LOCKED + UPDATE lease up to `free` due tasks (any of them: the priority and round     *)
(* robin order is not modelled) and start their jobs (start_jobs); then asyncio.create_task(run(task)) for each.   *)
Claim(w) ==
    LET free == Slots - Cardinality(Running(w))
        n == IF Bug = "claim_slots_not_free" THEN Slots ELSE free   \* claim_tasks(conn, worker, n)
    IN /\ free > 0
       /\ Due # {}
       /\ \E S \in SUBSET Due :
            /\ Cardinality(S) = Min(n, Cardinality(Due))
            /\ \E f \in [S -> FreeRecords(w)] : \A a, b \in S : a # b => f[a] # f[b]
            /\ LET f == CHOOSE g \in [S -> FreeRecords(w)] : \A a, b \in S : a # b => g[a] # g[b]
               IN /\ status' = [t \in Tasks |-> IF t \in S THEN "claimed" ELSE status[t]]
                  /\ attempts' = [t \in Tasks |-> IF t \in S THEN attempts[t] + 1 ELSE attempts[t]]
                  /\ leaseLeft' = [t \in Tasks |-> IF t \in S THEN Lease ELSE leaseLeft[t]]
                  /\ holder' = [t \in Tasks |-> IF t \in S THEN f[t] ELSE holder[t]]
                  /\ job' = [j \in Jobs |-> IF job[j] = "queued" /\ \E t \in S : JobOf[t] = j
                                              THEN "running" ELSE job[j]]
                  /\ run' = [r \in Records |->
                               IF \E t \in S : f[t] = r
                                 THEN [IdleRun EXCEPT !.pc = "turn", !.dl = "run", !.age = Deadline,
                                                      !.task = CHOOSE t \in S : f[t] = r]
                                 ELSE run[r]]
    /\ UNCHANGED <<backoff, hostNext, deaths, hangs, lefts>>

(* polite_fetch -> _first_turn with QUEUED: HostLimiter.admit(host) records the turn and the request goes, or the  *)
(* turn is `wait` away: Later -> the handler returns Postpone (fetch_queued). Or the task ends with no request    *)
(* for its page and none counted (fetch_queued's robots.txt disallow; a stored capture reread, `recent_capture`).  *)
Turn(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "turn" /\ ~run[r].stuck
    /\ \/ IF hostNext[w][h] = 0 \/ Bug = "admit_without_turn"
            THEN /\ hostNext' = [hostNext EXCEPT ![w][h] = Spacing]
                 /\ run' = [run EXCEPT ![r].pc = "http"]
            ELSE /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "postpone"]
                 /\ UNCHANGED hostNext
       \/ /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "unfetched"]
          /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, deaths, hangs, lefts>>

(* The first request answers: an ok page (Finished), a 429/503 (pause_host pauses the host; the handler returns  *)
(* Failed(transient)), or a page that needs the browser rung (the rungs escalate, acquire/rungs.py). An answer   *)
(* the handler ends with is extracted, then counted (count_fetch: UPDATE job.usage, which waits for the job row).  *)
HttpDone(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "http" /\ ~run[r].stuck
    /\ \/ /\ ~JobLockedByOther(r)
          /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "finished"]
          /\ UNCHANGED hostNext
       \/ /\ ~JobLockedByOther(r)
          /\ hostNext' = [hostNext EXCEPT ![w][h] = Max(@, Pause)]
          /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "transient"]
       \/ /\ run' = [run EXCEPT ![r].pc = "admit"]
          /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, deaths, hangs, lefts>>

(* The browser retry's admit_next = HostLimiter.wait(host, gap, QUEUED.bound): admitted when the turn is due     *)
(* (it sleeps until then, Ticks), refused at once when the turn is more than `bound` away: the fetch keeps the  *)
(* outcome it has (a page, or a failure), then count_fetch as in HttpDone.                                       *)
AdmitNext(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "admit" /\ ~run[r].stuck
    /\ IF hostNext[w][h] = 0
         THEN /\ hostNext' = [hostNext EXCEPT ![w][h] = Spacing]
              /\ run' = [run EXCEPT ![r].pc = "ctx"]
         ELSE /\ hostNext[w][h] > Bound /\ ~JobLockedByOther(r)
              /\ \E res \in {"finished", "transient"} : run' = [run EXCEPT ![r].pc = "update", ![r].res = res]
              /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, deaths, hangs, lefts>>

(* SharedBrowser.fetch: `async with self._contexts` (asyncio.Semaphore(BROWSER_CONTEXTS)), then the render.      *)
AcquireContext(r) ==
    /\ run[r].pc = "ctx" /\ ~run[r].stuck
    /\ Bug = "no_context_cap" \/ Cardinality(BrowserContexts(r[1])) < Contexts
    /\ run' = [run EXCEPT ![r].pc = "render"]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, hangs, lefts>>

RenderDone(r) ==
    /\ run[r].pc = "render" /\ ~run[r].stuck /\ ~JobLockedByOther(r)
    /\ \E res \in {"finished", "transient"} : run' = [run EXCEPT ![r].pc = "update", ![r].res = res]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, hangs, lefts>>

(* _move: UPDATE url_task ... WHERE id = :id AND status IN (sources) AND claimed_by = :w AND lease_until = :l.   *)
(* It waits for the row lock (no step while another transaction holds it). No row: LeaseLost, _run rolls back  *)
(* and returns.                                                                                                  *)
UpdateRow(r) ==
    LET t == run[r].task IN
    /\ run[r].pc = "update" /\ ~run[r].stuck
    /\ ~RowLocked(t)
    /\ IF status[t] = "claimed" /\ (holder[t] = r \/ Bug = "no_fence")
         THEN run' = [run EXCEPT ![r].pc = "locked",
                                 ![r].snap = Bug = "settle_before_job_lock"
                                              /\ OpenIn(JobOf[t], [status EXCEPT ![t] = "done"])]
         ELSE run' = [run EXCEPT ![r] = EndWork(r)]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, hangs, lefts>>

(* settle_job: SELECT ... FROM job FOR NO KEY UPDATE: waits while another transaction holds the job row.         *)
LockJob(r) ==
    /\ run[r].pc = "locked" /\ ~run[r].stuck
    /\ ~JobLockedByOther(r)
    /\ run' = [run EXCEPT ![r].pc = "settling"]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, hangs, lefts>>

(* settle_job's read of open tasks (blocking_statuses) and settled_status under the job lock, then the commit:     *)
(* complete_task -> "done"; fail_task(transient) -> requeued after the backoff, or "failed" on the last attempt;    *)
(* release_task (Postpone) -> requeued, the attempt given back. A requeued row loses its lease (transition_task). *)
Commit(r) ==
    LET t == run[r].task  j == JobOf[t]
        new == CASE run[r].res \in {"finished", "unfetched"} -> "done"
                 [] run[r].res = "transient" -> FailTransient(t)
                 [] run[r].res = "postpone"  -> "queued"
        st == [status EXCEPT ![t] = new]
        open == IF Bug = "settle_before_job_lock" THEN run[r].snap ELSE OpenIn(j, st)
    IN
    /\ run[r].pc = "settling" /\ ~run[r].stuck
    /\ status' = st
    /\ attempts' = IF run[r].res = "postpone" THEN [attempts EXCEPT ![t] = @ - 1] ELSE attempts
    /\ backoff' = IF new = "queued" THEN [backoff EXCEPT ![t] = Backoff] ELSE backoff
    /\ holder' = IF new = "queued" THEN [holder EXCEPT ![t] = None] ELSE holder
    /\ job' = [job EXCEPT ![j] = Settled(j, st, open)]
    /\ run' = [run EXCEPT ![r] = EndWork(r)]
    /\ UNCHANGED <<leaseLeft, hostNext, deaths, hangs, lefts>>

(* _run_within_deadline: asyncio.wait(timeout=TASK_DEADLINE) returns with the work not done: work.cancel(), then  *)
(* asyncio.wait(timeout=CANCEL_GRACE). The cancelled work either ends (its transaction rolls back: row and job     *)
(* locks, browser context and request released) or is left behind (_LEFT_BEHIND) and keeps what it holds.          *)
DeadlineFires(r) ==
    /\ Bug # "no_deadline"
    /\ run[r].dl = "run" /\ run[r].age = 0
    /\ \/ /\ run' = [run EXCEPT ![r] = [IdleRun EXCEPT !.task = run[r].task, !.dl = "dfail"]]
          /\ UNCHANGED lefts
       \/ /\ lefts < MaxLeftBehind
          /\ ~run[r].stuck \/ LeftBehindHangs
          /\ lefts' = lefts + 1
          /\ run' = [run EXCEPT ![r].cancelled = TRUE, ![r].dl = "dfail"]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, hangs>>

(* Then, in a transaction of its own with SET LOCAL lock_timeout = _LOCK_WAIT: fail_task(DEADLINE,               *)
(* transient=False) -> "failed", settle_job. A lock held past the lock_timeout raises (DBAPIError, logged) and   *)
(* the task is left to its lease's expiry; LeaseLost is ignored. The deadline coroutine then returns.             *)
DeadlineFail(r) ==
    LET t == run[r].task  j == JobOf[t]
        st == [status EXCEPT ![t] = "failed"]
        rec == IF run[r].pc = "idle" THEN IdleRun ELSE [run[r] EXCEPT !.dl = "none"]
    IN
    /\ run[r].dl = "dfail"
    /\ IF ~RowLocked(t) /\ ~JobLocked(j)
         THEN IF status[t] = "claimed" /\ holder[t] = r
                THEN /\ status' = st
                     /\ job' = SettleAll(st, j)
                ELSE UNCHANGED <<status, job>>
         ELSE \* lock_timeout, when a lock is held by work that will not commit soon: work that is hung or was left
              \* behind. A running transaction commits within _LOCK_WAIT, so the failure waits for it (no step).
              /\ \E o \in Records : /\ run[o].stuck \/ run[o].cancelled
                                   /\ \/ run[o].pc \in {"locked", "settling"} /\ run[o].task = t
                                      \/ HoldsJob(o) /\ JobOf[run[o].task] = j
              /\ UNCHANGED <<status, job>>
    /\ run' = [run EXCEPT ![r] = rec]
    /\ UNCHANGED <<attempts, leaseLeft, backoff, holder, hostNext, deaths, hangs, lefts>>

(* Work left behind takes its cancellation late, at a later await: its transaction rolls back and it ends.        *)
LateCancel(r) ==
    /\ run[r].cancelled /\ Live(r)
    /\ run' = [run EXCEPT ![r] = EndWork(r)]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, hangs, lefts>>

(* An await that never returns: a page or render that hangs, a database call that stalls. Cancellable.          *)
Hang(r) ==
    /\ hangs < MaxHangs
    /\ \/ run[r].pc \in {"http", "render", "locked", "settling"}
       \/ run[r].pc = "update" /\ HoldsJob(r)   \* a frontier write or the fenced UPDATE stalls, job row locked
    /\ ~run[r].stuck
    /\ ~run[r].cancelled \/ LeftBehindHangs
    /\ hangs' = hangs + 1
    /\ run' = [run EXCEPT ![r].stuck = TRUE]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, deaths, lefts>>

(* A worker process dies: its coroutines, browser and HostLimiter go with it; PostgreSQL rolls back its open      *)
(* transactions (row and job locks released). The process restarts with a new worker id and empty limiter.     *)
Die(w) ==
    /\ deaths < MaxDeaths
    /\ deaths' = deaths + 1
    /\ run' = [r \in Records |-> IF r[1] = w THEN IdleRun ELSE run[r]]
    /\ hostNext' = [hostNext EXCEPT ![w] = [h \in Hosts |-> 0]]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hangs, lefts>>

(* The scheduler, every minute: release_expired_leases: claimed rows whose lease_until < now(), FOR UPDATE SKIP    *)
(* LOCKED, each fail_task("lease expired", transient=True) and settle_job (which waits for the job row lock).      *)
ReleaseExpired(t) ==
    LET j == JobOf[t]  new == FailTransient(t)  st == [status EXCEPT ![t] = new] IN
    /\ Bug # "no_lease_release"
    /\ status[t] = "claimed" /\ leaseLeft[t] = 0
    /\ ~RowLocked(t) /\ ~JobLocked(j)
    /\ status' = st
    /\ backoff' = IF new = "queued" THEN [backoff EXCEPT ![t] = Backoff] ELSE backoff
    /\ holder' = IF new = "queued" THEN [holder EXCEPT ![t] = None] ELSE holder
    /\ job' = SettleAll(st, j)
    /\ UNCHANGED <<attempts, leaseLeft, run, hostNext, deaths, hangs, lefts>>

(* Time passes. Timers fire on time: no tick while a deadline is due or a deadline failure is being recorded.    *)
Tick ==
    /\ ~\E r \in Records : (run[r].dl = "run" /\ run[r].age = 0 /\ Bug # "no_deadline") \/ run[r].dl = "dfail"
    /\ leaseLeft' = [t \in Tasks |-> IF status[t] = "claimed" THEN Dec(leaseLeft[t]) ELSE leaseLeft[t]]
    /\ backoff' = [t \in Tasks |-> Dec(backoff[t])]
    /\ hostNext' = [w \in Workers |-> [h \in Hosts |-> Dec(hostNext[w][h])]]
    /\ run' = [r \in Records |-> IF run[r].dl = "run" THEN [run[r] EXCEPT !.age = Dec(@)] ELSE run[r]]
    /\ UNCHANGED <<status, attempts, holder, job, deaths, hangs, lefts>>

WorkStep(r) ==
    Turn(r) \/ HttpDone(r) \/ AdmitNext(r) \/ AcquireContext(r) \/ RenderDone(r) \/ UpdateRow(r)
    \/ LockJob(r) \/ Commit(r)

Next ==
    \/ \E w \in Workers : Claim(w) \/ Die(w)
    \/ \E r \in Records : WorkStep(r) \/ DeadlineFires(r) \/ DeadlineFail(r) \/ Hang(r) \/ LateCancel(r)
    \/ \E t \in Tasks : ReleaseExpired(t)
    \/ Tick

\* Every step of the code, the scheduler and the clock is taken when it stays possible; faults (Hang, Die, a left-
\* behind cancellation) are not forced. A worker's claim, the scheduler and timers are weakly fair.
Fairness ==
    /\ \A w \in Workers : WF_vars(Claim(w))
    /\ \A r \in Records : WF_vars(WorkStep(r)) /\ WF_vars(DeadlineFires(r)) /\ WF_vars(DeadlineFail(r))
    /\ \A t \in Tasks : WF_vars(ReleaseExpired(t))
    /\ WF_vars(Tick)

Spec == Init /\ [][Next]_vars /\ Fairness

-----------------------------------------------------------------------------
(* Properties. Each says what the user would lose if it broke.                                                   *)

TypeOK ==
    /\ status \in [Tasks -> {"queued", "claimed", "done", "failed"}]
    /\ attempts \in [Tasks -> 0 .. MaxAttempts]
    /\ job \in [Jobs -> {"queued", "running", "completed", "failed"}]

\* Never more than TASK_SLOTS tasks running in a worker (claimed only into free slots).
SlotCap == \A w \in Workers : Cardinality(Running(w)) <= Slots

\* Never two requests in flight to one host, across every worker.
HostOneInFlight == \A h \in Hosts : Cardinality(InFlight(h)) <= 1

\* A request goes to a host only when its worker's HostLimiter has the host's turn due (HostLimiter.admit: one request
\* per spacing per host, per process; its documented contract). An action property.
Admits(r) == \/ run[r].pc = "turn" /\ run'[r].pc = "http"
             \/ run[r].pc = "admit" /\ run'[r].pc = "ctx"
HostSpacing == [][\A r \in Records : Admits(r) => hostNext[r[1]][HostOf[run[r].task]] = 0]_vars

\* Never more than BROWSER_CONTEXTS pages rendering at once in a worker's shared browser.
BrowserCap == \A w \in Workers : Cardinality(BrowserContexts(w)) <= Contexts

\* No task is processed twice at once: at most one run of a task that has not been cancelled.
NoDoubleProcessing ==
    \A t \in Tasks : Cardinality({r \in Records : Live(r) /\ run[r].task = t /\ ~run[r].cancelled}) <= 1

\* The strict form: not even work left behind after its cancellation runs beside a new claim of its task.
NoDoubleProcessingStrict ==
    \A t \in Tasks : Cardinality({r \in Records : Live(r) /\ run[r].task = t}) <= 1

\* Every claimed task reaches done or failed.
TaskTerminates == \A t \in Tasks : (status[t] = "claimed") ~> (status[t] \in {"done", "failed"})

\* Every job ends.
JobFinishes == \A j \in Jobs : <>(job[j] \in {"completed", "failed"})
=============================================================================
