"""The learning simulation's accounting (`eval.learn_sim`): role A's first calls counted and answered with no step, and
the aggregates by category. No provider is called."""

import asyncio

from pydantic import JsonValue

from crawlerai.config_ir.synthesis import output_schema
from crawlerai.eval.learn_sim import NO_STEP, HostRun, RoleACounter, summary
from crawlerai.llm.client import LLMRequest
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
    return HostRun(category, "detail", 1, activated, fields, calls, calls * 400)


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
        "role_a_hosts": 1,
        "role_a_calls": 1,
        "role_a_chars": 400,
        "role_a_usd_estimate": 0.4,
    }
    assert found["all"]["zero_touch"] == 0.5  # type: ignore[index,call-overload]


def test_a_live_role_a_has_its_repairs_counted_as_the_provider_is_called_for_them() -> None:
    reply: dict[str, JsonValue] = {"fields": [], "listing": {"row": NO_STEP, "fields": []}}
    live = ScriptedClient(reply, reply)
    counter = RoleACounter(ScriptedClient(), live)
    asyncio.run(counter.complete_json(_request("a_synth", "abcd")))
    asyncio.run(counter.complete_json(_request("a_repair", "abcdefgh")))
    assert (counter.calls, counter.chars, len(live.requests)) == (2, 14, 2)
