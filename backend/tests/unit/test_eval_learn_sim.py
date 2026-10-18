"""The learning simulation's accounting (`eval.learn_sim`): role A's first calls counted and answered with no step, and
the aggregates by category. No provider is called."""

import pytest

from crawlerai.config_ir.executability import Executability
from crawlerai.eval.learn_sim import HostRun, RoleATokens, summary
from crawlerai.llm.client import AnsweredCall


def _run(category: str, *, activated: bool, calls: int, fields: int) -> HostRun:
    classes: dict[Executability, int] = {"static-html": fields, "needs-browser": 0, "api-call": 0, "unexecutable": 0}
    return HostRun(category, "detail", 1, activated, fields, classes, calls, calls * 400, RoleATokens())


def test_a_host_is_zero_touch_when_its_config_activates_without_role_a() -> None:
    runs = [
        _run("job_board", activated=True, calls=0, fields=4),
        _run("job_board", activated=True, calls=1, fields=6),
        _run("job_board", activated=False, calls=0, fields=0),
        _run("custom_store", activated=True, calls=0, fields=2),
    ]
    found = summary(runs, usd_per_char=0.001)
    assert found["job_board"] == {
        "hosts": 3,
        "pages_per_host": 1.0,
        "zero_touch": 0.333,
        "activated": 0.667,
        "fields_per_host": 3.33,
        "executability": {"static-html": 10, "needs-browser": 0, "api-call": 0, "unexecutable": 0},
        "role_a_hosts": 1,
        "role_a_calls": 1,
        "role_a_chars": 400,
        "role_a_usd_estimate": 0.4,
        "role_a_live_hosts": 0,
        "role_a_tokens_in": 0,
        "role_a_tokens_out": 0,
        "role_a_cache_read_tokens": 0,
        "role_a_cache_write_tokens": 0,
        "role_a_usd": None,
    }
    assert found["all"]["zero_touch"] == 0.5  # type: ignore[index,call-overload]


def test_a_live_role_a_reports_the_tokens_it_used_with_its_cache_tokens_and_their_price() -> None:
    # The shipped price of the default strong model: input 2, output 10, cache read 0.2, cache write 2.5 USD per MTok.
    call = AnsweredCall(
        provider="anthropic",
        model="claude-sonnet-5-5",
        request_hash="h",
        tokens_in=1_000,
        tokens_out=2_000,
        cache_read_tokens=100_000,
        cache_write_tokens=20_000,
    )
    tokens = RoleATokens().plus(call).plus(call)
    assert (tokens.tokens_in, tokens.tokens_out, tokens.cache_read, tokens.cache_write) == (
        2_000,
        4_000,
        200_000,
        40_000,
    )
    run = HostRun("c", "detail", 1, True, 1, {"static-html": 1}, 2, 10, tokens)
    found = summary([run], usd_per_char=None)["all"]
    assert found["role_a_cache_read_tokens"] == 200_000  # type: ignore[index,call-overload]
    assert found["role_a_usd"] == round(tokens.usd or 0, 4)  # type: ignore[index,call-overload]
    assert tokens.usd == pytest.approx(0.184)
