"""The learning simulation's accounting (`eval.learn_sim`): role A's first calls counted and answered with no step, and
the aggregates by category. No provider is called."""

import asyncio

import pytest
from pydantic import JsonValue

from crawlerai.config_ir.executability import Executability
from crawlerai.config_ir.synthesis import output_schema
from crawlerai.eval.learn_sim import NO_STEP, HostRun, RoleACounter, RoleATokens, summary
from crawlerai.llm.client import AnsweredCall, LLMRequest
from crawlerai.llm.providers.fake import ScriptedClient


def _request(kind: str, user: str = "page") -> LLMRequest:
    return LLMRequest(
        prompt_kind=kind,  # type: ignore[arg-type]
        model_class="strong",
        system="s",
        user=user,
        output_schema=output_schema(("title",), True, ("url",)),
        max_output_tokens=10,
        job_id=None,
    )


def test_role_a_first_calls_are_counted_and_answered_with_no_step_in_the_requests_shape() -> None:
    other = ScriptedClient()
    counter = RoleACounter(other, None)
    first = asyncio.run(counter.complete_json(_request("a_synth", "abcd")))
    asyncio.run(counter.complete_json(_request("a_repair", "abcdefgh")))
    assert (counter.calls, counter.chars, other.requests) == (1, 5, [])
    assert first.data == {"fields": [], "listing": {"row": NO_STEP, "fields": []}}


def test_other_calls_go_to_the_replayed_client_uncounted() -> None:
    other = ScriptedClient({"fields": [], "listing": {"row": NO_STEP, "fields": []}})
    counter = RoleACounter(other, None)
    asyncio.run(counter.complete_json(_request("c_extract_detail")))
    assert (counter.calls, len(other.requests)) == (0, 1)


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


def test_a_live_role_a_has_its_repairs_counted_as_the_provider_is_called_for_them() -> None:
    reply: dict[str, JsonValue] = {"fields": [], "listing": {"row": NO_STEP, "fields": []}}
    live = ScriptedClient(reply, reply)
    counter = RoleACounter(ScriptedClient(), live)
    asyncio.run(counter.complete_json(_request("a_synth", "abcd")))
    asyncio.run(counter.complete_json(_request("a_repair", "abcdefgh")))
    assert (counter.calls, counter.chars, len(live.requests)) == (2, 14, 2)


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


def test_a_call_with_no_price_leaves_the_cost_unknown() -> None:
    call = AnsweredCall(provider="anthropic", model="unpriced-model", request_hash="h", tokens_in=1, tokens_out=1)
    assert RoleATokens().plus(call).usd is None


def test_hosts_tokens_are_summed_and_an_unpriced_host_leaves_the_total_cost_unknown() -> None:
    priced = RoleATokens(tokens_in=10, tokens_out=5, cache_read=100, cache_write=50, usd=0.25)
    unpriced = RoleATokens(tokens_in=1, tokens_out=1, usd=None)
    classes: dict[Executability, int] = {"static-html": 1, "needs-browser": 0, "api-call": 0, "unexecutable": 0}

    def host(tokens: RoleATokens) -> HostRun:
        return HostRun("c", "detail", 1, True, 1, classes, 1, 10, tokens)

    both = summary([host(priced), host(priced)], usd_per_char=None)["all"]
    assert both["role_a_usd"] == 0.5  # type: ignore[index,call-overload]
    assert both["role_a_tokens_in"] == 20  # type: ignore[index,call-overload]
    mixed = summary([host(priced), host(unpriced), host(RoleATokens())], usd_per_char=None)["all"]
    assert (mixed["role_a_usd"], mixed["role_a_live_hosts"]) == (None, 2)  # type: ignore[index,call-overload]
