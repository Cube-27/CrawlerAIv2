from collections.abc import Mapping
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.jobs import JOB_TRANSITIONS, TASK_TRANSITIONS, settled_status
from crawlerai.db.models import JobStatus, TaskStatus

MACHINES = pytest.mark.parametrize(
    ("transitions", "statuses"),
    [(JOB_TRANSITIONS, get_args(JobStatus)), (TASK_TRANSITIONS, get_args(TaskStatus))],
    ids=["job", "url_task"],
)


def _reachable(transitions: Mapping[str, frozenset[str]], start: str) -> set[str]:
    seen, frontier = {start}, [start]
    while frontier:
        for target in transitions[frontier.pop()] - seen:
            seen.add(target)
            frontier.append(target)
    return seen


@MACHINES
def test_every_status_has_a_row(transitions: Mapping[str, frozenset[str]], statuses: tuple[str, ...]) -> None:
    assert set(transitions) == set(statuses)
    assert set().union(*transitions.values()) <= set(statuses)


@MACHINES
def test_every_status_is_reachable_from_queued(
    transitions: Mapping[str, frozenset[str]], statuses: tuple[str, ...]
) -> None:
    assert _reachable(transitions, "queued") == set(statuses)


@MACHINES
def test_every_status_can_still_end(transitions: Mapping[str, frozenset[str]], statuses: tuple[str, ...]) -> None:
    terminal = {status for status in statuses if not transitions[status]}

    for status in statuses:
        assert _reachable(transitions, status) & terminal, status


def test_job_lifecycle() -> None:
    assert {status for status, targets in JOB_TRANSITIONS.items() if not targets} == {
        "completed",
        "failed",
        "cancelled",
    }
    assert JOB_TRANSITIONS["queued"] == {"running", "cancelled"}
    assert JOB_TRANSITIONS["running"] == {"completed", "failed", "cancelled"}


def test_task_lifecycle() -> None:
    assert {status for status, targets in TASK_TRANSITIONS.items() if not targets} == {"done", "failed", "cancelled"}
    assert TASK_TRANSITIONS["queued"] == {"claimed", "cancelled"}
    # Back to `queued`: a retry after a transient failure, or a lease that expired (SPEC-01 §4.3).
    assert TASK_TRANSITIONS["claimed"] == {"queued", "done", "failed", "cancelled"}


counts = st.fixed_dictionaries({status: st.integers(min_value=0, max_value=50) for status in get_args(TaskStatus)})


@given(counts, st.booleans())
def test_a_job_with_a_claimed_task_never_settles(counts: dict[TaskStatus, int], cancel_requested: bool) -> None:
    counts["claimed"] += 1

    assert settled_status(counts, cancel_requested=cancel_requested) is None


@given(counts)
def test_a_cancel_settles_once_no_task_is_claimed(counts: dict[TaskStatus, int]) -> None:
    counts["claimed"] = 0

    assert settled_status(counts, cancel_requested=True) == "cancelled"


@given(counts)
def test_a_job_with_queued_tasks_keeps_running(counts: dict[TaskStatus, int]) -> None:
    counts["queued"] += 1

    assert settled_status(counts, cancel_requested=False) is None


@given(st.integers(min_value=1, max_value=50))
def test_a_job_fails_only_when_every_task_failed(failed: int) -> None:
    assert settled_status({"failed": failed}, cancel_requested=False) == "failed"
    assert settled_status({"failed": failed, "done": 1}, cancel_requested=False) == "completed"
    assert settled_status({"failed": failed, "cancelled": 1}, cancel_requested=False) == "completed"


@given(counts)
def test_a_drained_job_with_a_done_task_completes(counts: dict[TaskStatus, int]) -> None:
    counts["queued"] = counts["claimed"] = 0
    counts["done"] += 1

    assert settled_status(counts, cancel_requested=False) == "completed"


def test_a_job_with_no_tasks_completes() -> None:
    assert settled_status({}, cancel_requested=False) == "completed"
