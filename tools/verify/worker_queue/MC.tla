---- MODULE MC ----
\* The instances TLC checks WorkerQueue on (tools/verify/worker_queue.py picks one per check).
EXTENDS WorkerQueue
CONSTANTS w1, w2, t1, t2, t3, j1, h1, h2, h3
OneWorker == {w1}
TwoWorkers == {w1, w2}
TwoTasks == {t1, t2}
ThreeTasks == {t1, t2, t3}
\* One job: two tasks finishing at once is the settle race (settle_job), and a job ends only when all its tasks do.
OneJob == [t \in ThreeTasks |-> j1]
\* Both tasks on one host: they compete for the host's turns.
SameHost == [t \in ThreeTasks |-> h1]
\* Each task on a host of its own: the host's pacing does not serialize the renders.
OwnHost == (t1 :> h1) @@ (t2 :> h2) @@ (t3 :> h3)
====
