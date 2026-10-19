"""Model-check the worker and queue concurrency (TLA+, TLC): .claude/skills/verify-worker-queue/SKILL.md.

    python3 tools/verify/worker_queue.py              # the checks and the known findings (CI runs this)
    python3 tools/verify/worker_queue.py --mutants    # also each broken variant, which must be caught
    python3 tools/verify/worker_queue.py left-behind  # only the named checks

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
    # One worker with three slots, three tasks on hosts of their own: three renders could overlap.
    "browser": {
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
SAFETY = ["TypeOK", "SlotCap", "BrowserCap", "NoDoubleProcessing"]
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
    Check("browser", "browser", SAFETY, TEMPORAL),
]
# What the code does that a requested property forbids. Each stays failing until the code changes; then move it.
FINDINGS = [
    Check(
        "finding-host-in-flight",
        "two-workers",
        ["HostOneInFlight"],
        [],
        expect="HostOneInFlight",
        overrides={"Workers": "OneWorker", "Slots": 2},
        why="HostLimiter spaces request starts per process; it does not hold a host while a request is in flight",
    ),
    Check(
        "finding-left-behind-beside-reclaim",
        "left-behind",
        ["NoDoubleProcessingStrict"],
        [],
        expect="NoDoubleProcessingStrict",
        overrides={"MaxAttempts": 2},
        why="work left behind keeps running past its lease while the requeued task runs again",
    ),
    Check(
        "finding-left-behind-hangs-on-its-row",
        "left-behind",
        [],
        ["TaskTerminates"],
        expect="TaskTerminates",
        overrides={"LeftBehindHangs": True},
        why="left-behind work that never ends holding its url_task row lock: release_expired_leases skips the row",
    ),
]
# Broken variants of the code (the model's `Bug`, or a constant): each must be caught.
MUTANTS = [
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
        "mutant-claim-without-free-slot",
        "two-workers",
        ["SlotCap"],
        [],
        expect="SlotCap",
        bug="claim_without_free_slot",
        why="run_worker claims TASK_SLOTS tasks, not `free`",
    ),
    Check(
        "mutant-no-context-cap",
        "browser",
        ["BrowserCap"],
        [],
        expect="BrowserCap",
        bug="no_context_cap",
        why="SharedBrowser.fetch without `async with self._contexts`",
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
    """A state's variables; a function of records (`run`) splits into one entry per record."""
    values: dict[str, str] = {}
    for match in re.finditer(r"^/\\ (\w+) = (.*?)(?=^/\\ |\Z)", body, flags=re.M | re.S):
        name, value = match.group(1), " ".join(match.group(2).split())
        records = re.findall(r"<<(\w+), (\d+)>> :> \[ (.*?) \]", value)
        if not records:
            values[name] = value
        for worker, slot, fields in records:
            values[f"{name}[{worker},{slot}]"] = fields.replace(" |-> ", "=")
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
    states = re.findall(r"([\d,]+) distinct states found", output)
    size = f"{states[-1]} states" if states else "?"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mutants", action="store_true", help="also check that each broken variant is caught")
    parser.add_argument("checks", nargs="*", help="run only these checks (by name)")
    args = parser.parse_args()
    every = CHECKS + FINDINGS + MUTANTS
    chosen = [c for c in every if c.name in args.checks] if args.checks else CHECKS + FINDINGS
    if args.mutants and not args.checks:
        chosen += MUTANTS
    if unknown := set(args.checks) - {c.name for c in every}:
        sys.exit(f"unknown checks {sorted(unknown)}; known: {[c.name for c in every]}")
    jar = _fetch(*TLA_JAR, CACHE / f"tla2tools-{TLA_JAR[1][:12]}.jar")
    java = _java()
    results = [run(check, java, jar) for check in chosen]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
