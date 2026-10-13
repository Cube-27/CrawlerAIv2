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
from anthropic import APIStatusError
from google.genai.errors import ClientError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.llm.client import (
    LLMRequest,
    MeteredClient,
    ModelClass,
    Provider,
    ProviderCall,
    ProviderError,
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


def anthropic_body(text: str) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "strong-model-version",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }


def gemini_body(text: str) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3, "thoughtsTokenCount": 1},
        "modelVersion": "strong-model-version",
    }


def error_body(status: int) -> dict[str, Any]:
    return {"type": "error", "error": {"code": status, "message": "synthetic error", "status": "ERROR"}}


@dataclass(frozen=True)
class Vendor:
    name: str
    body: Callable[[str], dict[str, Any]]
    build: Callable[[list[Any], Handler], Provider]
    timeout_error: Callable[..., Exception]  # the transport's timeout exception
    rejected: type[Exception]


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


ANTHROPIC = Vendor("anthropic", anthropic_body, _anthropic, httpx2.ReadTimeout, APIStatusError)
GEMINI = Vendor("gemini", gemini_body, _gemini, httpx.ReadTimeout, ClientError)
VENDORS = pytest.mark.parametrize("vendor", [ANTHROPIC, GEMINI], ids=lambda vendor: vendor.name)


def run(provider: Provider, call: ProviderCall = CALL) -> ProviderReply:
    return asyncio.run(provider.complete(call))


def answering(vendor: Vendor, text: str = ANSWER) -> Handler:
    return lambda _request: (200, vendor.body(text))


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
@pytest.mark.parametrize(("model_class", "model"), [("fast", "fast-model"), ("strong", "strong-model")])
def test_the_model_follows_the_model_class(vendor: Vendor, model_class: str, model: str) -> None:
    requests: list[Any] = []
    run(vendor.build(requests, answering(vendor)), CALL.model_copy(update={"model_class": model_class}))
    [request] = requests
    sent = request.url.path.removeprefix("/v1beta/models/").removesuffix(":generateContent")
    assert json.loads(request.content).get("model", sent) == model


@VENDORS
@pytest.mark.parametrize("timeout_s", [60, 120])
def test_the_call_timeout_is_the_request_timeout(vendor: Vendor, timeout_s: int) -> None:
    requests: list[Any] = []
    run(vendor.build(requests, answering(vendor)), CALL.model_copy(update={"timeout_s": timeout_s}))
    assert requests[0].extensions["timeout"]["read"] == timeout_s


# --- what is read ---


@VENDORS
def test_the_reply_text_model_and_token_counts_are_read(vendor: Vendor) -> None:
    # Anthropic's thinking block is skipped; Gemini's thinking tokens are billed as output (3 + 1).
    reply = run(vendor.build([], answering(vendor)))
    assert reply == ProviderReply(model="strong-model-version", text=ANSWER, tokens_in=12, tokens_out=4)


@VENDORS
def test_an_invalid_reply_is_passed_on_for_the_client_to_check(vendor: Vendor) -> None:
    assert run(vendor.build([], answering(vendor, "not json"))).text == "not json"


# --- errors ---


@VENDORS
@pytest.mark.parametrize("status", [408, 429, 500, 503, 529])
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
@pytest.mark.parametrize("status", [400, 401, 404])
def test_a_rejected_request_is_not_a_provider_error(vendor: Vendor, status: int) -> None:
    # A bad key, an unknown model or a refused schema would fail on any provider, so it is not failed over.
    provider = vendor.build([], failing(status))
    with pytest.raises(vendor.rejected):
        run(provider)


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
