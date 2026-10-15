"""The Anthropic and Gemini providers (SPEC-06 §4.1, §4.2) against a fake HTTP transport: no provider is called in CI
(§6). Each test checks what a provider sends (the model for the class, the JSON-schema output mode, the token cap and
the timeout) or how it reads a synthetic reply, and that a rate limit, a server error or a timeout becomes a
`ProviderError` after one request, so the client can fail over."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.llm.client import (
    LLMRequest,
    MeteredClient,
    ModelClass,
    Provider,
    ProviderCall,
    ProviderError,
    ProviderRefused,
    ProviderReply,
)
from crawlerai.llm.providers.anthropic import AnthropicProvider
from crawlerai.llm.providers.gemini import GeminiProvider

MODELS: dict[ModelClass, str] = {"fast": "fast-model", "strong": "strong-model"}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

CALL = ProviderCall(
    model_class="strong",
    system="system prompt",
    user="user prompt",
    output_schema=SCHEMA,
    max_output_tokens=256,
    timeout_s=120,
)

ANSWER = '{"summary": "a summary"}'

# A handler gets the request (`httpx.Request` for Gemini, `httpx2.Request` for Anthropic; the same shape) and returns
# the status and JSON body of the synthetic response.
Handler = Callable[[Any], tuple[int, dict[str, Any]]]


def anthropic_body(text: str, cut: bool = False) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "strong-model-version",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": text}],
        "stop_reason": "max_tokens" if cut else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }


def gemini_body(text: str, cut: bool = False) -> dict[str, Any]:
    finish = "MAX_TOKENS" if cut else "STOP"
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3, "thoughtsTokenCount": 1},
        "modelVersion": "strong-model-version",
    }


def error_body(status: int, message: str = "synthetic error") -> dict[str, Any]:
    return {"type": "error", "error": {"code": status, "message": message, "status": "ERROR"}}


@dataclass(frozen=True)
class Vendor:
    name: str
    body: Callable[[str, bool], dict[str, Any]]
    build: Callable[[list[Any], Handler], Provider]
    timeout_error: Callable[..., Exception]  # the transport's timeout exception


def _anthropic(requests: list[Any], handler: Handler) -> Provider:
    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        status, body = handler(request)
        return httpx2.Response(status, json=body)

    return AnthropicProvider("test-key", MODELS, httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))


def _gemini(requests: list[Any], handler: Handler) -> Provider:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status, body = handler(request)
        return httpx.Response(status, json=body)

    return GeminiProvider("test-key", MODELS, httpx.AsyncClient(transport=httpx.MockTransport(respond)))


ANTHROPIC = Vendor("anthropic", anthropic_body, _anthropic, httpx2.ReadTimeout)
GEMINI = Vendor("gemini", gemini_body, _gemini, httpx.ReadTimeout)
VENDORS = pytest.mark.parametrize("vendor", [ANTHROPIC, GEMINI], ids=lambda vendor: vendor.name)


def run(provider: Provider, call: ProviderCall = CALL) -> ProviderReply:
    return asyncio.run(provider.complete(call))


def answering(vendor: Vendor, text: str = ANSWER, cut: bool = False) -> Handler:
    return lambda _request: (200, vendor.body(text, cut))


def failing(status: int) -> Handler:
    return lambda _request: (status, error_body(status))


# --- what is sent ---


def test_anthropic_asks_for_the_class_model_with_a_json_schema_output() -> None:
    requests: list[Any] = []
    run(ANTHROPIC.build(requests, answering(ANTHROPIC)))

    [request] = requests
    assert (request.method, request.url.path) == ("POST", "/v1/messages")
    assert json.loads(request.content) == {
        "model": "strong-model",
        "max_tokens": 256,
        "system": "system prompt",
        "messages": [{"role": "user", "content": "user prompt"}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }


def test_an_anthropic_fast_call_asks_for_low_effort() -> None:
    # F29: thinking tokens count against `max_tokens`; copying spans out of a page needs no reasoning.
    requests: list[Any] = []
    run(ANTHROPIC.build(requests, answering(ANTHROPIC)), CALL.model_copy(update={"model_class": "fast"}))

    [request] = requests
    assert json.loads(request.content)["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "low",
    }


def test_gemini_asks_for_the_class_model_with_a_json_schema_output_at_temperature_0() -> None:
    requests: list[Any] = []
    run(GEMINI.build(requests, answering(GEMINI)))

    [request] = requests
    assert (request.method, request.url.path) == ("POST", "/v1beta/models/strong-model:generateContent")
    assert json.loads(request.content) == {
        "contents": [{"role": "user", "parts": [{"text": "user prompt"}]}],
        "systemInstruction": {"role": "user", "parts": [{"text": "system prompt"}]},
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
            "responseJsonSchema": SCHEMA,
        },
    }


@VENDORS
def test_the_model_follows_the_model_class(vendor: Vendor) -> None:
    # The strong class's model is in each vendor's request test above.
    requests: list[Any] = []
    run(vendor.build(requests, answering(vendor)), CALL.model_copy(update={"model_class": "fast"}))
    [request] = requests
    sent = request.url.path.removeprefix("/v1beta/models/").removesuffix(":generateContent")
    assert json.loads(request.content).get("model", sent) == "fast-model"


@VENDORS
def test_the_call_timeout_is_the_request_timeout(vendor: Vendor) -> None:
    requests: list[Any] = []
    run(vendor.build(requests, answering(vendor)), CALL.model_copy(update={"timeout_s": 60}))
    assert requests[0].extensions["timeout"]["read"] == 60


# --- what is read ---


@VENDORS
def test_the_reply_text_model_and_token_counts_are_read(vendor: Vendor) -> None:
    # Anthropic's thinking block is skipped; Gemini's thinking tokens are billed as output (3 + 1).
    reply = run(vendor.build([], answering(vendor)))
    assert reply == ProviderReply(model="strong-model-version", text=ANSWER, tokens_in=12, tokens_out=4)


@VENDORS
def test_a_reply_stopped_at_the_token_cap_is_marked_cut(vendor: Vendor) -> None:
    # A reply that ends normally is not cut: test_the_reply_text_model_and_token_counts_are_read.
    assert run(vendor.build([], answering(vendor, '{"summ', cut=True))).cut is True


@VENDORS
def test_an_invalid_reply_is_passed_on_for_the_client_to_check(vendor: Vendor) -> None:
    assert run(vendor.build([], answering(vendor, "not json"))).text == "not json"


# --- errors ---


@VENDORS
@pytest.mark.parametrize("status", [408, 429, 500])
def test_a_transient_status_is_a_provider_error_after_one_request(vendor: Vendor, status: int) -> None:
    requests: list[Any] = []
    provider = vendor.build(requests, failing(status))

    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        run(provider)
    assert len(requests) == 1  # the SDK does not retry; the client fails over


@VENDORS
def test_a_timeout_is_a_provider_error(vendor: Vendor) -> None:
    def time_out(request: Any) -> tuple[int, dict[str, Any]]:
        raise vendor.timeout_error("synthetic timeout", request=request)

    provider = vendor.build([], time_out)
    with pytest.raises(ProviderError, match="no response"):
        run(provider)


@VENDORS
def test_a_rejected_request_is_refused_with_the_providers_message(vendor: Vendor) -> None:
    # A bad key, an unknown model or a refused schema: the request's own fault, which a retry does not fix (§4.7).
    requests: list[Any] = []
    provider = vendor.build(requests, failing(400))

    with pytest.raises(ProviderRefused, match=f"{vendor.name}: HTTP 400: .*synthetic error") as refused:
        run(provider)
    assert (refused.value.code, refused.value.field_reason, len(requests)) == ("llm_unavailable", "llm_unavailable", 1)
    assert (refused.value.provider, refused.value.model, refused.value.status) == (vendor.name, "strong-model", 400)


@VENDORS
def test_a_refusal_never_carries_the_api_key(vendor: Vendor) -> None:
    provider = vendor.build([], lambda _request: (401, error_body(401, "key test-key is not valid")))

    with pytest.raises(ProviderRefused) as refused:
        run(provider)

    assert "test-key" not in str(refused.value)
    assert "key [redacted] is not valid" in str(refused.value)


# --- failover between the two (§4.2) ---


@pytest.mark.parametrize(("first", "second"), [(ANTHROPIC, GEMINI), (GEMINI, ANTHROPIC)], ids=["a-g", "g-a"])
def test_the_client_fails_over_from_one_provider_to_the_other(first: Vendor, second: Vendor) -> None:
    down: list[Any] = []
    up: list[Any] = []
    client = MeteredClient(
        [first.build(down, failing(529)), second.build(up, answering(second))],
        create_async_engine("postgresql+asyncpg://127.0.0.1/unused"),  # no job: never connected
    )
    request = LLMRequest(
        prompt_kind="s_draft",
        model_class="strong",
        system="system prompt",
        user="user prompt",
        output_schema=SCHEMA,
        max_output_tokens=256,
        job_id=None,
    )

    response = asyncio.run(client.complete_json(request))

    assert (response.provider, response.data, len(down), len(up)) == (second.name, {"summary": "a summary"}, 1, 1)


def test_a_refused_request_is_not_failed_over() -> None:
    refused: list[Any] = []
    other: list[Any] = []
    client = MeteredClient(
        [ANTHROPIC.build(refused, failing(400)), GEMINI.build(other, answering(GEMINI))],
        create_async_engine("postgresql+asyncpg://127.0.0.1/unused"),  # no job: never connected
    )
    request = LLMRequest(
        prompt_kind="s_draft",
        model_class="strong",
        system="system prompt",
        user="user prompt",
        output_schema=SCHEMA,
        max_output_tokens=256,
        job_id=None,
    )

    call = client.complete_json(request)
    with pytest.raises(ProviderRefused):
        asyncio.run(call)
    assert (len(refused), len(other)) == (1, 0)
