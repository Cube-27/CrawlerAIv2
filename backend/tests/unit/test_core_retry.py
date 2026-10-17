"""The retry rules the queue, the politeness layer, the LLM providers and the adapters share (`core.retry`)."""

from datetime import timedelta

import pytest

from crawlerai.acquire.politeness import asked_pause
from crawlerai.acquire.types import AttemptRecord
from crawlerai.core.retry import FIRST_BACKOFF, is_transient
from crawlerai.db.queue import retry_delay


def test_the_queue_and_a_host_that_asked_for_fewer_requests_start_from_the_same_backoff() -> None:
    attempt = AttemptRecord.model_construct(retry_after=None)

    assert retry_delay(1) == FIRST_BACKOFF == asked_pause(attempt) == timedelta(seconds=30)
    assert retry_delay(3) == FIRST_BACKOFF * 4


@pytest.mark.parametrize(("status", "transient"), [(408, True), (429, True), (500, True), (503, True), (599, True)])
def test_timeouts_rate_limits_and_server_errors_say_try_again(status: int, transient: bool) -> None:
    assert is_transient(status) is transient


@pytest.mark.parametrize("status", [0, 200, 301, 400, 401, 403, 404, 410, 451, 600])
def test_other_statuses_do_not(status: int) -> None:
    assert not is_transient(status)
