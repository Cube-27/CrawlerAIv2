---------------------------- MODULE WorkerQueue ----------------------------
(***************************************************************************)
(* The worker and queue concurrency of backend/src/crawlerai:               *)
(*   worker/loop.py        run_worker, _run_within_deadline, _run, _execute *)
(*   db/queue.py           claim_tasks, fail_task, release_task,            *)
(*                         release_expired_leases, _move (the fence),       *)
(*                         settle_job, TASK_DEADLINE, LEASE, MAX_ATTEMPTS   *)
(*   services/polite.py    polite_fetch, _first_turn (Later -> Postpone),   *)
(*                         pause_host, QUEUED (the capped in-place wait)    *)
(*   acquire/politeness.py HostLimiter.admit / wait / pause / holding,      *)
(*                         its shared store (acquire/host_turns.py):        *)
(*                         turns and holds every process shares, a hold a   *)
(*                         lease renewed while its holder runs              *)
(*   services/polite.py    rules_in -> recording: the robots.txt request    *)
(*   acquire/shared_browser.py SharedBrowser.render, BROWSER_CONTEXTS       *)
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
(* time: no Tick passes while a task is at its deadline, or while its      *)
(* deadline failure can be recorded (CANCEL_GRACE fits inside one tick); a *)
(* failure waiting for a lock that hung work holds waits for that work's   *)
(* own deadline, at most one more tick (_LOCK_WAIT covers it), and two     *)
(* ticks end well inside LEASE (Lease = 3: TASK_DEADLINE 3 min, its grace  *)
(* and _LOCK_WAIT end by 6 min 40 s, LEASE 10 min).                        *)
(*                                                                         *)
(* `Bug` selects a broken variant of the code, to show that each property  *)
(* can fail (MUTANTS in tools/verify/worker_queue.py). "none" is the code.   *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    Workers,        \* worker processes (run_worker), each with its own HostLimiter (sharing host_turn) and SharedBrowser
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
    HoldLease,      \* politeness.HOLD_LEASE, in ticks: how long a hold no running holder renews lasts
    Robots,         \* whether the hosts' robots.txt snapshots are stale at the start (a request before the page)
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
\*   "turn"     polite_fetch -> rules_in's robots.txt request or _first_turn: HostLimiter.admit for the first request
\*              (QUEUED.postpone)
\*   "robots"   the robots.txt request in flight (recording, within the polite fetch's hold)
\*   "pageturn" the page's turn after robots.txt's: _first_turn(sent=True) waits in place (HostLimiter.wait, up to
\*              QUEUED.bound), and postpones past it
\*   "http"     the first request of the page in flight (the HTTP rung)
\*   "admit"    the browser retry waiting in place for its turn (admit_next = HostLimiter.wait, up to QUEUED.bound)
\*   "ctx"      SharedBrowser.render (a page or a listing render) waiting for a context (`async with self._contexts`)
\*   "render"   the browser request in flight, holding a context
\*   "update"   the handler returned; _execute calls complete_task / fail_task / release_task: the fenced UPDATE.
\*              A run that sent a request holds its job's row lock already: the handler's count_fetch (steps.py)
\*              updated job.usage as its last write (db/usage.py record_usage), in the task's transaction
\*   "locked"   the url_task row is updated and locked; settle_job is taking the job row lock
\*   "settling" both locks held; settle_job reads the open tasks, `ending`, commit
\*   "behind"   work left behind after its cancellation (cancelled): past the request the cancellation aborted, in
\*              cleanup that does not end (a `finally`, an `async with` exit); it sends nothing and holds no host
\*   "behindctx" the same inside SharedBrowser.render's `async with self._contexts`: it still holds a browser context
\* The host is held (HostLimiter.holding, polite_fetch) from the admitted turn until the fetch returns: HeldPcs. The
\* hold is in host_turn, every process's (HostTurns.take: the turn and the hold in one upsert).
HeldPcs == {"robots", "pageturn", "http", "admit", "ctx", "render"}
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
    hostNext,   \* [w][h]: ticks until worker w's HostLimiter admits a request to h: host_turn.next_at, the same for
                \* every w (the process's own _next only refuses what host_turn refuses too); per worker under
                \* Bug = "local_pacing"
    stale,      \* [h]: ticks left of a hold in host_turn that no running holder renews (its process died, or the
                \* holder was cancelled and left behind): held_until
    fresh,      \* [h]: whether h's robots.txt snapshot is fresh (site.robots_snapshot, 24 h)
    deaths, hangs, lefts

vars == <<status, attempts, leaseLeft, backoff, holder, job, run, hostNext, stale, fresh, deaths, hangs, lefts>>

Live(r) == run[r].pc # "idle"
\* PostgreSQL row locks, held by a transaction from its UPDATE / SELECT FOR UPDATE until it commits or rolls back.
\* Each takes the records' state `rn`, so that the deadline failure can ask after ending a session.
LocksRow(rn, o, t) == rn[o].pc \in {"locked", "settling"} /\ rn[o].task = t
\* The job row: settle_job's FOR NO KEY UPDATE, or earlier count_fetch's UPDATE of job.usage (a run that sent a request;
\* a Postpone sent none and counts nothing). Both conflict with each other and with settle_job's lock.
HoldsJobIn(rn, o) == \/ rn[o].pc = "settling"
                     \/ rn[o].pc \in {"update", "locked"} /\ rn[o].res \in {"finished", "transient"}
HoldsJob(r) == HoldsJobIn(run, r)
RowLocked(t) == \E r \in Records : LocksRow(run, r, t)
JobLocked(j) == \E r \in Records : HoldsJob(r) /\ JobOf[run[r].task] = j
JobLockedByOther(r) == \E o \in Records \ {r} : HoldsJob(o) /\ JobOf[run[o].task] = JobOf[run[r].task]
\* A request in flight to host h from any worker: work left behind included, were it to send one.
InFlight(h) == {r \in Records : run[r].pc \in {"robots", "http", "render"} /\ HostOf[run[r].task] = h}
\* Another task holds r's host: in host_turn (HostTurns.take's condition: another holder whose lease runs), or in r's
\* process (HostLimiter._busy). A running holder's lease is renewed (_renew); one being cancelled holds nothing in its
\* process, and its hold in host_turn is a stale one (`stale`). Bug = "process_hold": the hold is the process's only.
HeldByOther(r) ==
    LET h == HostOf[run[r].task] IN
    \/ Bug # "process_hold" /\ stale[h] > 0
    \/ \E o \in Records \ {r} :
        /\ o[1] = r[1] \/ Bug # "process_hold"
        /\ \/ run[o].pc \in HeldPcs /\ ~run[o].cancelled /\ (Bug # "robots_unpaced" \/ run[o].pc # "robots")
           \/ Bug = "hold_while_cancelled" /\ o[1] = r[1] /\ run[o].pc \in {"behind", "behindctx"}
        /\ HostOf[run[o].task] = h
\* host_turn.next_at set for h (every worker's view), or the process's own under Bug = "local_pacing".
SetNext(w, h, v) ==
    IF Bug = "local_pacing" THEN [hostNext EXCEPT ![w][h] = v]
    ELSE [x \in Workers |-> [hostNext[x] EXCEPT ![h] = v]]
\* The holds a dying process leaves in host_turn, or work left behind: they lapse after HoldLease (no renewal).
Stale(hs) == [h \in Hosts |-> IF h \in hs THEN Max(stale[h], HoldLease) ELSE stale[h]]
BrowserContexts(w) == {r \in Records : r[1] = w /\ run[r].pc \in {"render", "behindctx"}}
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
    /\ stale = [h \in Hosts |-> 0]
    /\ fresh = [h \in Hosts |-> ~Robots]
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
    /\ UNCHANGED <<backoff, hostNext, stale, fresh, deaths, hangs, lefts>>

(* polite_fetch -> _first_turn with QUEUED: HostLimiter.admit(host) records the turn and the request goes (the host *)
(* held, `holding`, with no await between), or the turn is not due or another task of the worker holds the host:  *)
(* Later -> the handler returns Postpone (queued_end). Or the task ends with no request for its page and none      *)
(* counted (queued_end's robots.txt disallow; a stored capture reread, `recent_capture`).                          *)
(* A stale robots.txt snapshot: the first request is rules_in's robots.txt request (recording -> _first_turn),     *)
(* admitted and held as a page's is. Bug = "robots_unpaced": it is sent before any turn, unheld (the code before).  *)
Turn(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "turn" /\ ~run[r].stuck
    /\ \/ IF ~fresh[h] /\ Bug = "robots_unpaced"
            THEN /\ run' = [run EXCEPT ![r].pc = "robots"]
                 /\ UNCHANGED hostNext
          ELSE IF (hostNext[w][h] = 0 /\ (~HeldByOther(r) \/ Bug = "no_host_hold")) \/ Bug = "admit_without_turn"
            THEN /\ hostNext' = SetNext(w, h, Spacing)
                 /\ run' = [run EXCEPT ![r].pc = IF fresh[h] THEN "http" ELSE "robots"]
            ELSE /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "postpone"]
                 /\ UNCHANGED hostNext
       \/ /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "unfetched"]
          /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, stale, fresh, deaths, hangs, lefts>>

(* robots.txt answers: the snapshot is stored (site_robots, in the task's transaction), and the page's turn is     *)
(* waited for in place (_first_turn, sent=True); or it is unreachable: Refused(ROBOTS_UNREACHABLE) -> Failed        *)
(* (transient), its attempts counted (count_fetch). Under "robots_unpaced" the page's turn is the first one.        *)
RobotsDone(r) ==
    LET h == HostOf[run[r].task] IN
    /\ run[r].pc = "robots" /\ ~run[r].stuck
    /\ \/ /\ fresh' = [fresh EXCEPT ![h] = TRUE]
          /\ run' = [run EXCEPT ![r].pc = IF Bug = "robots_unpaced" THEN "turn" ELSE "pageturn"]
       \/ /\ ~JobLockedByOther(r)
          /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "transient"]
          /\ UNCHANGED fresh
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, deaths, hangs, lefts>>

(* The page's turn after robots.txt's: HostLimiter.wait(host, gap, QUEUED.bound) in place, the host still held by  *)
(* this task; a turn further off than the bound postpones the task (Later(bound)).                                  *)
PageTurn(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "pageturn" /\ ~run[r].stuck
    /\ IF hostNext[w][h] = 0
         THEN /\ hostNext' = SetNext(w, h, Spacing)
              /\ run' = [run EXCEPT ![r].pc = "http"]
         ELSE /\ hostNext[w][h] > Bound
              /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "postpone"]
              /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, stale, fresh, deaths, hangs, lefts>>

(* The first request answers: an ok page (Finished), a 429/503 (pause_host pauses the host; the handler returns  *)
(* Failed(transient)), or a page that needs the browser rung (the rungs escalate, acquire/rungs.py: a block, a   *)
(* shell, a 503 interstitial or a 429, the last two after the pause admit_next waits out). An answer            *)
(* the handler ends with is extracted, then counted (count_fetch: UPDATE job.usage, which waits for the job row).  *)
HttpDone(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "http" /\ ~run[r].stuck
    /\ \/ /\ ~JobLockedByOther(r)
          /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "finished"]
          /\ UNCHANGED hostNext
       \/ /\ ~JobLockedByOther(r)
          /\ hostNext' = SetNext(w, h, Max(hostNext[w][h], Pause))
          /\ run' = [run EXCEPT ![r].pc = "update", ![r].res = "transient"]
       \/ /\ run' = [run EXCEPT ![r].pc = "admit"]
          /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, stale, fresh, deaths, hangs, lefts>>

(* The browser retry's admit_next = HostLimiter.wait(host, gap, QUEUED.bound): admitted when the turn is due     *)
(* (it sleeps until then, Ticks), refused at once when the turn is more than `bound` away: the fetch keeps the  *)
(* outcome it has (a page, or a failure), then count_fetch as in HttpDone.                                       *)
(* Work whose cancellation was swallowed reaches its next admission there: HostLimiter.admit raises CancelledError *)
(* in a task being cancelled (`cancelling()`), and the work ends.                                                   *)
AdmitNext(r) ==
    LET w == r[1]  h == HostOf[run[r].task] IN
    /\ run[r].pc = "admit" /\ ~run[r].stuck
    /\ IF run[r].cancelled /\ Bug # "cancelled_admits"
         THEN /\ run' = [run EXCEPT ![r] = EndWork(r)]
              /\ UNCHANGED hostNext
       ELSE IF hostNext[w][h] = 0
         THEN /\ hostNext' = SetNext(w, h, Spacing)
              /\ run' = [run EXCEPT ![r].pc = "ctx"]
         ELSE /\ hostNext[w][h] > Bound /\ ~JobLockedByOther(r)
              /\ \E res \in {"finished", "transient"} : run' = [run EXCEPT ![r].pc = "update", ![r].res = res]
              /\ UNCHANGED hostNext
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, stale, fresh, deaths, hangs, lefts>>

(* SharedBrowser.render: `async with self._contexts` (asyncio.Semaphore(BROWSER_CONTEXTS)), then the render.     *)
AcquireContext(r) ==
    /\ run[r].pc = "ctx" /\ ~run[r].stuck
    /\ Bug = "no_context_cap" \/ Cardinality(BrowserContexts(r[1])) < Contexts
    /\ run' = [run EXCEPT ![r].pc = "render"]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, fresh, deaths, hangs, lefts>>

RenderDone(r) ==
    /\ run[r].pc = "render" /\ ~run[r].stuck /\ ~JobLockedByOther(r)
    /\ \E res \in {"finished", "transient"} : run' = [run EXCEPT ![r].pc = "update", ![r].res = res]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, fresh, deaths, hangs, lefts>>

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
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, fresh, deaths, hangs, lefts>>

(* settle_job: SELECT ... FROM job FOR NO KEY UPDATE: waits while another transaction holds the job row.         *)
LockJob(r) ==
    /\ run[r].pc = "locked" /\ ~run[r].stuck
    /\ ~JobLockedByOther(r)
    /\ run' = [run EXCEPT ![r].pc = "settling"]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, fresh, deaths, hangs, lefts>>

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
    /\ UNCHANGED <<leaseLeft, hostNext, stale, fresh, deaths, hangs, lefts>>

(* _run_within_deadline: asyncio.wait(timeout=TASK_DEADLINE) returns with the work not done: work.cancel(), then  *)
(* asyncio.wait(timeout=CANCEL_GRACE). The cancelled work either ends (its transaction rolls back: row and job     *)
(* locks, browser context and request released) or is left behind (_LEFT_BEHIND). Left behind, the request it    *)
(* awaited is aborted (CancelledError at that await), and it is in cleanup ("behind", inside SharedBrowser.render  *)
(* still holding a context), or it swallowed the cancellation and goes on to its next admission ("admit"); in its  *)
(* transaction ("update", "locked", "settling") it keeps its locks until the deadline failure ends its session.   *)
DeadlineFires(r) ==
    LET pc == run[r].pc IN
    /\ Bug # "no_deadline"
    /\ run[r].dl = "run" /\ run[r].age = 0
    /\ \/ /\ run' = [run EXCEPT ![r] = [IdleRun EXCEPT !.task = run[r].task, !.dl = "dfail"]]
          /\ UNCHANGED <<lefts, stale>>
       \/ /\ lefts < MaxLeftBehind
          /\ ~run[r].stuck \/ LeftBehindHangs
          /\ lefts' = lefts + 1
          \* Its holding block does not end: its hold in host_turn stays until _renew gives it up (the task is being
          \* cancelled), within its lease.
          /\ stale' = IF pc \in HeldPcs THEN Stale({HostOf[run[r].task]}) ELSE stale
          /\ \E next \in IF pc \in {"update", "locked", "settling"} THEN {pc}
                         ELSE {IF pc = "render" THEN "behindctx" ELSE "behind", "admit"} :
               run' = [run EXCEPT ![r].cancelled = TRUE, ![r].dl = "dfail", ![r].pc = next]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, fresh, deaths, hangs>>

(* Then, in a transaction of its own: work left behind has its session ended first (pg_terminate_backend of the  *)
(* session whose application_name names the claim, _session_name): its transaction rolls back, releasing its     *)
(* locks, and its database calls fail from then on. Then SET LOCAL lock_timeout = _LOCK_WAIT, fail_task(DEADLINE, *)
(* transient=False) -> "failed", settle_job; LeaseLost is ignored. The deadline coroutine then returns.            *)
EndSession(r) ==
    IF run[r].cancelled /\ Bug # "no_end_session" /\ run[r].pc \in {"update", "locked", "settling"}
      THEN [run EXCEPT ![r].pc = "behind"]
      ELSE run
\* The transactions the failure waits for: those holding the task's row or its job's row once r's session ended.
Blockers(r) ==
    LET rn == EndSession(r)  t == run[r].task IN
    {o \in Records : LocksRow(rn, o, t) \/ (HoldsJobIn(rn, o) /\ JobOf[rn[o].task] = JobOf[t])}
\* A blocker that hangs is cancelled at its own deadline, or left behind and its session ended then: the failure
\* waits for it (_LOCK_WAIT is TASK_DEADLINE + CANCEL_GRACE + 10 s), and time passes meanwhile. A running
\* transaction commits at once.
WaitsForDeadline(r) == Blockers(r) # {} /\ \A o \in Blockers(r) : run[o].stuck /\ ~run[o].cancelled
\* The code before this change: lock_timeout 10 s, and a lock held by hung or left-behind work makes the failure give
\* up (DBAPIError, logged), leaving the task to its lease's expiry.
GivesUp(r) == Bug = "deadline_gives_up" /\ \E o \in Blockers(r) : run[o].stuck \/ run[o].cancelled
DeadlineFail(r) ==
    LET t == run[r].task  j == JobOf[t]
        st == [status EXCEPT ![t] = "failed"]
        rn == EndSession(r)
        rec == IF rn[r].pc = "idle" THEN IdleRun ELSE [rn[r] EXCEPT !.dl = "none"]
    IN
    /\ run[r].dl = "dfail"
    /\ IF Blockers(r) = {}
         THEN IF status[t] = "claimed" /\ holder[t] = r
                THEN /\ status' = st
                     /\ job' = SettleAll(st, j)
                ELSE UNCHANGED <<status, job>>
         ELSE /\ GivesUp(r)
              /\ UNCHANGED <<status, job>>
    /\ run' = [rn EXCEPT ![r] = rec]
    /\ UNCHANGED <<attempts, leaseLeft, backoff, holder, hostNext, stale, fresh, deaths, hangs, lefts>>

(* Work left behind in cleanup: the cleanup returns and the work ends (rolled back, or its session already ended). *)
Behind(r) ==
    /\ run[r].pc \in {"behind", "behindctx"} /\ ~run[r].stuck
    /\ run' = [run EXCEPT ![r] = EndWork(r)]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, fresh, deaths, hangs, lefts>>

(* An await that never returns: a page or render that hangs, a database call that stalls. Cancellable.          *)
Hang(r) ==
    /\ hangs < MaxHangs
    /\ \/ run[r].pc \in {"robots", "http", "render", "locked", "settling", "behind", "behindctx"}
       \/ run[r].pc = "update" /\ HoldsJob(r)   \* a frontier write or the fenced UPDATE stalls, job row locked
    /\ ~run[r].stuck
    /\ ~run[r].cancelled \/ LeftBehindHangs
    /\ hangs' = hangs + 1
    /\ run' = [run EXCEPT ![r].stuck = TRUE]
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, hostNext, stale, fresh, deaths, lefts>>

(* A worker process dies: its coroutines, browser and HostLimiter go with it; PostgreSQL rolls back its open      *)
(* transactions (row and job locks released). The process restarts with a new worker id and empty limiter. Its    *)
(* holds stay in host_turn until their leases lapse (HOLD_LEASE, nobody renews them); host_turn.next_at stays.     *)
Die(w) ==
    /\ deaths < MaxDeaths
    /\ deaths' = deaths + 1
    /\ run' = [r \in Records |-> IF r[1] = w THEN IdleRun ELSE run[r]]
    /\ hostNext' = IF Bug = "local_pacing" THEN [hostNext EXCEPT ![w] = [h \in Hosts |-> 0]] ELSE hostNext
    /\ stale' = Stale({HostOf[run[r].task] : r \in {o \in Records : o[1] = w /\ run[o].pc \in HeldPcs}})
    /\ UNCHANGED <<status, attempts, leaseLeft, backoff, holder, job, fresh, hangs, lefts>>

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
    /\ UNCHANGED <<attempts, leaseLeft, run, hostNext, stale, fresh, deaths, hangs, lefts>>

(* Time passes. Timers fire on time: no tick while a deadline is due or a deadline failure can be recorded; one    *)
(* waiting for hung work's deadline waits through it.                                                              *)
Tick ==
    /\ ~\E r \in Records :
          \/ run[r].dl = "run" /\ run[r].age = 0 /\ Bug # "no_deadline"
          \/ run[r].dl = "dfail" /\ (Bug = "deadline_gives_up" \/ ~WaitsForDeadline(r))
    /\ leaseLeft' = [t \in Tasks |-> IF status[t] = "claimed" THEN Dec(leaseLeft[t]) ELSE leaseLeft[t]]
    /\ backoff' = [t \in Tasks |-> Dec(backoff[t])]
    /\ hostNext' = [w \in Workers |-> [h \in Hosts |-> Dec(hostNext[w][h])]]
    \* A stale hold lapses (held_until). Bug = "no_lease": a hold has no expiry (a lock on a connection the dead or
    \* stuck holder keeps); "renew_cancelled": _renew keeps renewing the hold of work being cancelled while it lives.
    /\ stale' = [h \in Hosts |->
                   IF \/ Bug = "no_lease"
                      \/ Bug = "renew_cancelled"
                         /\ \E o \in Records : Live(o) /\ run[o].cancelled /\ HostOf[run[o].task] = h
                   THEN stale[h] ELSE Dec(stale[h])]
    /\ run' = [r \in Records |-> IF run[r].dl = "run" THEN [run[r] EXCEPT !.age = Dec(@)] ELSE run[r]]
    /\ UNCHANGED <<status, attempts, holder, job, fresh, deaths, hangs, lefts>>

WorkStep(r) ==
    Turn(r) \/ RobotsDone(r) \/ PageTurn(r) \/ HttpDone(r) \/ AdmitNext(r) \/ AcquireContext(r) \/ RenderDone(r) \/ UpdateRow(r)
    \/ LockJob(r) \/ Commit(r) \/ Behind(r)

Next ==
    \/ \E w \in Workers : Claim(w) \/ Die(w)
    \/ \E r \in Records : WorkStep(r) \/ DeadlineFires(r) \/ DeadlineFail(r) \/ Hang(r)
    \/ \E t \in Tasks : ReleaseExpired(t)
    \/ Tick

\* Every step of the code, the scheduler and the clock is taken when it stays possible (cleanup that does not hang
\* returns); faults (Hang, Die, a left-behind cancellation) are not forced. A worker's claim, the scheduler and timers are weakly fair.
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

\* Never two requests in flight to one host, from any workers (owner plan 2026-10-19, P1: the hold is shared through
\* host_turn), robots.txt's included.
HostOneInFlight == \A h \in Hosts : Cardinality(InFlight(h)) <= 1

\* A request goes to a host only when the host's turn is due for every worker (HostLimiter.admit and host_turn: one
\* request per spacing per host, across processes). An action property.
Admits(r) == \/ run[r].pc = "turn" /\ run'[r].pc \in {"http", "robots"}
             \/ run[r].pc = "pageturn" /\ run'[r].pc = "http"
             \/ run[r].pc = "admit" /\ run'[r].pc = "ctx"
HostSpacing == [][\A r \in Records : Admits(r) => \A x \in Workers : hostNext[x][HostOf[run[r].task]] = 0]_vars

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
