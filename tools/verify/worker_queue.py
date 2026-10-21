"""Model-check the worker and queue concurrency (TLA+, TLC): .claude/skills/verify-worker-queue/SKILL.md.

    python3 tools/verify/worker_queue.py              # the checks, the known findings, the mutants (CI runs this)
    python3 tools/verify/worker_queue.py left-behind  # only the named checks
    python3 tools/verify/worker_queue.py --shard 2/3  # every third check from the second (CI runs 3 shards)

Each check runs TLC on the model (tools/verify/worker_queue/WorkerQueue.tla) with one instance and its properties,
and must end as it expects: no error, or a violation of the named property (a known finding, a mutant). Anything
else exits 1 and prints the counterexample as the steps of the code. Standard library only; it downloads the pinned
tla2tools.jar, and a pinned Temurin JRE when no `java` 11+ is on PATH, into ~/.cache/crawlerai-tla.
"""

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MODEL = Path(__file__).resolve().parent / "worker_queue"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "crawlerai-tla"
# TLA+ tools v1.7.4 ("Xenophanes", the latest stable release).
TLA_JAR = (
    "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar",
    "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88",
)
_JRE = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/"
JRES = {
    "x86_64": (
        _JRE + "OpenJDK21U-jre_x64_linux_hotspot_21.0.12.1_1.tar.gz",
        "2413149700df0f7d440500a84a8f764c535f21e5a5e87d38328b64eec2c5b500",
    ),
    "aarch64": (
        _JRE + "OpenJDK21U-jre_aarch64_linux_hotspot_21.0.12.1_1.tar.gz",
        "14be1f35ebdbd1f6e8d57eb911a3ffb74d6d9aa255abc5daf2b1302002cf2cf2",
    ),
}
HEAP = os.environ.get("TLC_HEAP", "1500m")

# The instances (MC.tla names the sets). Bounds are small on purpose: every behaviour within them is checked.
INSTANCES: dict[str, dict[str, object]] = {
    # Two worker processes, one slot each, two tasks of one job on one host; a worker dies, a page hangs.
    "two-workers": {
        "Workers": "TwoWorkers",
        "Tasks": "TwoTasks",
        "HostOf": "SameHost",
        "Slots": 1,
        "MaxAttempts": 2,
        "MaxDeaths": 1,
        "MaxHangs": 1,
        "MaxLeftBehind": 0,
        "LeftBehindHangs": False,
    },
    # Two workers, one of whose cancelled task is left behind (loop._LEFT_BEHIND) while its slot runs the next task.
    "left-behind": {
        "Workers": "TwoWorkers",
        "Tasks": "TwoTasks",
        "HostOf": "SameHost",
        "Slots": 1,
        "MaxAttempts": 1,
        "MaxDeaths": 0,
        "MaxHangs": 1,
        "MaxLeftBehind": 1,
        "LeftBehindHangs": False,
    },
    # One worker with two slots, three tasks on one host: a postponed task comes due again while a slot is busy, so
    # a claim happens with fewer free slots than due tasks.
    "slots": {
        "Workers": "OneWorker",
        "Tasks": "ThreeTasks",
        "HostOf": "SameHost",
        "Slots": 2,
        "MaxAttempts": 1,
        "MaxDeaths": 0,
        "MaxHangs": 0,
        "MaxLeftBehind": 0,
        "LeftBehindHangs": False,
    },
    # One worker with three slots, three tasks on hosts of their own: three renders could overlap. robots.txt fresh:
    # a stale one's request spends the tick a render needs within Deadline (the same-host instances check robots.txt).
    "browser": {
        "Robots": False,
        "Workers": "OneWorker",
        "Tasks": "ThreeTasks",
        "HostOf": "OwnHost",
        "Slots": 3,
        "MaxAttempts": 1,
        "MaxDeaths": 0,
        "MaxHangs": 1,
        "MaxLeftBehind": 0,
        "LeftBehindHangs": False,
    },
}
SAFETY = ["TypeOK", "SlotCap", "BrowserCap", "HostOneInFlight", "NoDoubleProcessing", "NoDoubleProcessingStrict"]
TEMPORAL = ["HostSpacing", "TaskTerminates", "JobFinishes"]


@dataclass(frozen=True)
class Check:
    name: str
    instance: str
    invariants: list[str]
    properties: list[str]
    expect: str | None = None  # the property TLC must report violated; None: no error
    bug: str = "none"
    overrides: dict[str, object] = field(default_factory=dict)
    why: str = ""


CHECKS = [
    Check("two-workers", "two-workers", SAFETY, TEMPORAL),
    Check("left-behind", "left-behind", SAFETY, TEMPORAL),
    Check("slots", "slots", SAFETY, TEMPORAL),
    Check("browser", "browser", SAFETY, TEMPORAL),
    # One worker, two slots, one host: t2's turn comes due while t1's request is in flight.
    Check("host-in-flight", "two-workers", SAFETY, TEMPORAL, overrides={"Workers": "OneWorker", "Slots": 2}),
    # w1 stalls holding the job row while t2's work is left behind; t2 could be requeued and claimed again.
    Check("left-behind-reclaim", "left-behind", SAFETY, TEMPORAL, overrides={"MaxAttempts": 2}),
    # Work left behind that never ends, holding its url_task row lock.
    Check("left-behind-hangs", "left-behind", SAFETY, TEMPORAL, overrides={"LeftBehindHangs": True}),
]
# What the code does that a requested property forbids: each stays failing (expect = the property) until the code
# changes, and then moves to CHECKS.
FINDINGS: list[Check] = []
# Broken variants of the code (the model's `Bug`, or a constant): each must be caught.
MUTANTS = [
    Check(
        "mutant-no-host-hold",
        "two-workers",
        ["HostOneInFlight"],
        [],
        expect="HostOneInFlight",
        bug="no_host_hold",
        overrides={"Workers": "OneWorker", "Slots": 2},
        why="polite_fetch without `limiter.holding(host)`: admit spaces request starts only",
    ),
    Check(
        "mutant-process-hold",
        "two-workers",
        ["HostOneInFlight"],
        [],
        expect="HostOneInFlight",
        bug="process_hold",
        why="the host's hold is the process's only (HostLimiter without its shared store): two workers overlap",
    ),
    Check(
        "mutant-local-pacing",
        "two-workers",
        [],
        ["HostSpacing"],
        expect="HostSpacing",
        bug="local_pacing",
        why="each process paces a host on its own (no host_turn.next_at)",
    ),
    Check(
        "mutant-no-lease",
        "two-workers",
        [],
        ["TaskTerminates"],
        expect="TaskTerminates",
        bug="no_lease",
        why="a hold with no expiry: a worker that dies holding a host blocks it for good",
    ),
    Check(
        "mutant-renew-cancelled",
        "left-behind",
        [],
        ["TaskTerminates"],
        expect="TaskTerminates",
        bug="renew_cancelled",
        overrides={"LeftBehindHangs": True},
        why="HostLimiter._renew renews the hold of work being cancelled: work left behind holds its host",
    ),
    Check(
        "mutant-robots-unpaced",
        "two-workers",
        ["HostOneInFlight"],
        [],
        expect="HostOneInFlight",
        bug="robots_unpaced",
        why="rules_of requests robots.txt before any turn, outside the hold",
    ),
    Check(
        "mutant-cancelled-admits",
        "left-behind",
        ["HostOneInFlight"],
        [],
        expect="HostOneInFlight",
        bug="cancelled_admits",
        why="HostLimiter.admit admits a task being cancelled",
    ),
    Check(
        "mutant-hold-while-cancelled",
        "left-behind",
        [],
        ["TaskTerminates"],
        expect="TaskTerminates",
        bug="hold_while_cancelled",
        overrides={"LeftBehindHangs": True},
        why="HostLimiter._busy counts a holder being cancelled: work left behind holds its host",
    ),
    Check(
        "mutant-deadline-gives-up",
        "left-behind",
        ["NoDoubleProcessingStrict"],
        [],
        expect="NoDoubleProcessingStrict",
        bug="deadline_gives_up",
        overrides={"MaxAttempts": 2},
        why="_LOCK_WAIT 10 s: the deadline failure gives up on hung work's lock, leaving the task to its lease",
    ),
    Check(
        "mutant-no-end-session",
        "left-behind",
        [],
        ["TaskTerminates"],
        expect="TaskTerminates",
        bug="no_end_session",
        overrides={"LeftBehindHangs": True},
        why="the deadline path does not end the session of work left behind (_END_SESSION)",
    ),
    Check(
        "mutant-no-deadline",
        "two-workers",
        ["NoDoubleProcessing"],
        [],
        expect="NoDoubleProcessing",
        bug="no_deadline",
        why="_run_within_deadline awaits the work with no timeout",
    ),
    Check(
        "mutant-lease-not-longer-than-deadline",
        "two-workers",
        ["NoDoubleProcessing"],
        [],
        expect="NoDoubleProcessing",
        overrides={"Lease": 1, "Deadline": 2},
        why="LEASE < TASK_DEADLINE",
    ),
    Check(
        "mutant-claim-slots-not-free",
        "slots",
        ["SlotCap"],
        [],
        expect="SlotCap",
        bug="claim_slots_not_free",
        why="run_worker calls claim_tasks(conn, worker, TASK_SLOTS), not `free`",
    ),
    Check(
        "mutant-no-context-cap",
        "browser",
        ["BrowserCap"],
        [],
        expect="BrowserCap",
        bug="no_context_cap",
        why="SharedBrowser.render without `async with self._contexts`",
    ),
    Check(
        "mutant-admit-without-turn",
        "two-workers",
        [],
        ["HostSpacing"],
        expect="HostSpacing",
        bug="admit_without_turn",
        why="_first_turn sends the request without HostLimiter.admit",
    ),
    Check(
        "mutant-no-lease-release",
        "two-workers",
        [],
        ["TaskTerminates"],
        expect="TaskTerminates",
        bug="no_lease_release",
        why="the scheduler does not run release_expired_leases",
    ),
    Check(
        "mutant-settle-before-job-lock",
        "two-workers",
        [],
        ["JobFinishes"],
        expect="JobFinishes",
        bug="settle_before_job_lock",
        why="settle_job reads open tasks before it locks the job row",
    ),
]


def _fetch(url: str, sha256: str, dest: Path) -> Path:
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - a pinned https URL
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        sys.exit(f"{url}: sha256 {digest}, expected {sha256}")
    dest.write_bytes(data)
    return dest


def _java() -> str:
    found = shutil.which("java")
    if found:
        version = subprocess.run([found, "-version"], capture_output=True, text=True).stderr  # noqa: S603 - PATH java
        major = re.search(r'version "(\d+)', version)
        if major and int(major.group(1)) >= 11:
            return found
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("arm64", "aarch64")
    if platform.system() != "Linux" or machine not in JRES:
        sys.exit("TLC needs Java 11 or later on PATH")
    url, sha256 = JRES[machine]
    home = CACHE / f"jre-{sha256[:12]}"
    java = next(home.glob("*/bin/java"), None)
    if java is None:
        archive = _fetch(url, sha256, CACHE / Path(url).name)
        with tarfile.open(archive) as tar:
            tar.extractall(home, filter="data")
        java = next(home.glob("*/bin/java"))
    return str(java)


def _config(check: Check) -> str:
    values = {**INSTANCES[check.instance], **check.overrides, "Bug": f'"{check.bug}"'}
    # The instance's values replace base.cfg's (TLC refuses a constant given twice).
    base = [line for line in (MODEL / "base.cfg").read_text().splitlines() if line.split("=")[0].strip() not in values]
    lines = [*base, "CONSTANTS"]
    for name, value in values.items():
        if isinstance(value, bool):
            lines.append(f"    {name} = {'TRUE' if value else 'FALSE'}")
        elif isinstance(value, str) and not value.startswith('"'):
            lines.append(f"    {name} <- {value}")
        else:
            lines.append(f"    {name} = {value}")
    if check.invariants:
        lines.append("INVARIANTS " + " ".join(check.invariants))
    if check.properties:
        lines.append("PROPERTIES " + " ".join(check.properties))
    return "\n".join(lines) + "\n"


def _violated(output: str, check: Check) -> str | None:
    """The property TLC reports violated, or None when it found no error."""
    if "Model checking completed. No error has been found." in output:
        return None
    if found := re.search(r"Invariant (\w+) is violated", output):
        return found.group(1)
    if found := re.search(r"Action property (\w+) .*is violated", output):
        return found.group(1)
    if "Temporal properties were violated" in output and len(check.properties) == 1:
        return check.properties[0]
    if "Temporal properties were violated" in output:
        return "a temporal property"
    return "an error: " + next((line for line in output.splitlines() if line.startswith("Error")), "see the log")


def _values(body: str) -> dict[str, str]:
    """A state's variables (`/\\ name = value`, the value over one or more lines); a function of records (`run`)
    splits into one entry per record."""
    raw: dict[str, list[str]] = {}
    name = ""
    for line in body.splitlines():
        if line.startswith("/\\ ") and " = " in line:
            name, _, first = line[3:].partition(" = ")
            raw[name] = [first]
        elif name:
            raw[name].append(line)
    values: dict[str, str] = {}
    for name, lines in raw.items():
        value = " ".join(" ".join(lines).split())
        records = [part.partition(" :> [ ") for part in value.split(" @@ ")] if " :> [ " in value else []
        if not records:
            values[name] = value
        for key, _, fields in records:
            slot = key.strip("( <>").replace(" ", "")
            values[f"{name}[{slot}]"] = fields.rstrip(" ])").replace(" |-> ", "=")
    return values


def _trace(output: str) -> str:
    """The counterexample as steps: each action with the variables it changed."""
    previous: dict[str, str] = {}
    steps = []
    for number, state in enumerate(re.split(r"^State \d+: ", output, flags=re.M)[1:], 1):
        head, _, body = state.partition("\n")
        body = body.split("\n\n")[0]
        action = re.sub(r" line \d+, col .*of module \w+", "", head).strip("<> ")
        current = _values(body)
        changed = [f"{k} = {v}" for k, v in current.items() if number > 1 and previous.get(k) != v]
        previous = current or previous
        steps.append(f"  {number}. {action}" + "".join(f"\n       {line}" for line in changed))
    return "\n".join(steps)


def run(check: Check, java: str, jar: Path) -> bool:
    (CACHE / "runs").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tlc-", dir=CACHE / "runs") as scratch:
        cfg = Path(scratch) / "MC.cfg"
        cfg.write_text(_config(check))
        for module in ("MC.tla", "WorkerQueue.tla"):
            shutil.copy(MODEL / module, scratch)
        started = time.monotonic()
        result = subprocess.run(  # noqa: S603 - the pinned java and jar
            [
                java,
                f"-Xmx{HEAP}",
                "-XX:+UseParallelGC",
                "-cp",
                str(jar),
                "tlc2.TLC",
                "-workers",
                "auto",
                "-deadlock",
                "-cleanup",
                "-metadir",
                str(Path(scratch) / "states"),
                "-config",
                str(cfg),
                "MC",
            ],
            cwd=scratch,
            capture_output=True,
            text=True,
        )
        seconds = time.monotonic() - started
    output = result.stdout + result.stderr
    log = CACHE / "logs" / f"{check.name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(output)
    violated = _violated(output, check)
    found = [line.split(", ")[1].split()[0] for line in output.splitlines() if line.endswith("states left on queue.")]
    size = f"{found[-1]} states" if found else "?"
    ok = violated == check.expect
    verdict = "pass" if violated is None else f"violates {violated}"
    print(
        f"{'ok  ' if ok else 'FAIL'} {check.name}: {verdict} ({size}, {seconds:.0f} s)"
        + (f" -- {check.why}" if check.why else "")
    )
    if not ok:
        expected = "no error" if check.expect is None else f"a violation of {check.expect}"
        print(f"     expected {expected}; TLC's log: {log}")
        if violated:
            print(f"     Counterexample:\n{_trace(output)}")
    return ok


def _shard(value: str) -> tuple[int, int]:
    index, _, count = value.partition("/")
    if not (index.isdigit() and count.isdigit() and 1 <= int(index) <= int(count)):
        raise argparse.ArgumentTypeError(f"{value!r} is not I/N with 1 <= I <= N")
    return int(index), int(count)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("checks", nargs="*", help="run only these checks (by name)")
    parser.add_argument("--shard", type=_shard, help="I/N: run only checks I, I+N, I+2N, ... (1-based) of the chosen")
    args = parser.parse_args()
    every = CHECKS + FINDINGS + MUTANTS
    chosen = [c for c in every if c.name in args.checks] if args.checks else every
    if args.shard:
        index, count = args.shard
        chosen = chosen[index - 1 :: count]
    if unknown := set(args.checks) - {c.name for c in every}:
        sys.exit(f"unknown checks {sorted(unknown)}; known: {[c.name for c in every]}")
    jar = _fetch(*TLA_JAR, CACHE / f"tla2tools-{TLA_JAR[1][:12]}.jar")
    java = _java()
    failures = sum(not run(check, java, jar) for check in chosen)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
