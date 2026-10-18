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


@MACHINES
def test_every_status_has_a_row(transitions: Mapping[str, frozenset[str]], statuses: tuple[str, ...]) -> None:
    assert set(transitions) == set(statuses)
    assert set().union(*transitions.values()) <= set(statuses)


@pytest.mark.parametrize(
    ("transitions", "statuses", "terminal"),
    [
        (JOB_TRANSITIONS, get_args(JobStatus), {"completed", "failed", "cancelled"}),
        (TASK_TRANSITIONS, get_args(TaskStatus), {"done", "failed", "cancelled"}),
    ],
    ids=["job", "url_task"],
)
def test_only_the_ended_statuses_have_no_exit(
    transitions: Mapping[str, frozenset[str]], statuses: tuple[str, ...], terminal: set[str]
) -> None:
    assert {status for status in statuses if not transitions[status]} == terminal


counts = st.fixed_dictionaries({status: st.integers(min_value=0, max_value=50) for status in get_args(TaskStatus)})


@given(counts, st.booleans())
def test_a_job_with_a_claimed_task_never_settles(counts: dict[TaskStatus, int], cancel_requested: bool) -> None:
    counts["claimed"] += 1

    assert settled_status(counts, cancel_requested=cancel_requested) is None


@given(st.integers(min_value=1, max_value=50))
def test_a_job_fails_only_when_every_task_failed(failed: int) -> None:
    assert settled_status({"failed": failed}, cancel_requested=False) == "failed"
    assert settled_status({"failed": failed, "done": 1}, cancel_requested=False) == "completed"
    assert settled_status({"failed": failed, "cancelled": 1}, cancel_requested=False) == "completed"
