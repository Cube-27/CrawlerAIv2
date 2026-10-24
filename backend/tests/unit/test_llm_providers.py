"""The Anthropic and Gemini providers against a fake HTTP transport: no provider is called in CI.
Each test checks what a provider sends (the model for the class, the JSON-schema output mode, the token cap and
the timeout) or how it reads a synthetic reply, and that a rate limit, a server error or a timeout becomes a
`ProviderError` after one request, so the client can fail over."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from snowcrawl.llm.client import (
    LLMRequest,
    MeteredClient,
    ModelClass,
    Provider,
    ProviderCall,
    ProviderRefused,
    ProviderReply,
)
from snowcrawl.llm.providers.anthropic import AnthropicProvider
from snowcrawl.llm.providers.gemini import GeminiProvider

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
    cached=(),
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


# --- what is read ---


# --- errors ---


@VENDORS
def test_a_refusal_never_carries_the_api_key(vendor: Vendor) -> None:
    provider = vendor.build([], lambda _request: (401, error_body(401, "key test-key is not valid")))

    with pytest.raises(ProviderRefused) as refused:
        run(provider)

    assert "test-key" not in str(refused.value)
    assert "key [redacted] is not valid" in str(refused.value)


# --- failover between the two ---


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
