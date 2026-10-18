"""The LLM setup check (SPEC-06 §4.2): a listed provider without its key, or a configured model its provider does not
know, makes the setup `unavailable` and is logged at ERROR, rather than surfacing only as `llm_refused` on every
record. Providers answer through a fake HTTP transport: none is called in CI."""

import asyncio
import logging
from collections.abc import Callable

import httpx
import httpx2
import pytest

from crawlerai.llm.client import ModelClass
from crawlerai.llm.providers.anthropic import AnthropicProvider
from crawlerai.llm.providers.gemini import GeminiProvider
from crawlerai.llm.setup import LLMSetup

MODELS: dict[ModelClass, str] = {"fast": "fast-model", "strong": "strong-model"}
KNOWN = frozenset({"fast-model", "strong-model"})


def _anthropic(known: frozenset[str], seen: list[str]) -> AnthropicProvider:
    def respond(request: httpx2.Request) -> httpx2.Response:
        model = request.url.path.rsplit("/", 1)[-1]
        seen.append(model)
        if model not in known:
            return httpx2.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": "nope"}})
        return httpx2.Response(
            200, json={"type": "model", "id": model, "display_name": model, "created_at": "2026-01-01T00:00:00Z"}
        )

    return AnthropicProvider("test-key", MODELS, httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))


def _gemini(respond: Callable[[httpx.Request], httpx.Response]) -> GeminiProvider:
    return GeminiProvider("test-key", MODELS, httpx.AsyncClient(transport=httpx.MockTransport(respond)))


def _gemini_model(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"name": f"models/{request.url.path.rsplit('/', 1)[-1]}"})


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]


def _verified(setup: LLMSetup) -> LLMSetup:
    asyncio.run(setup.verify())
    return setup


def test_a_setup_whose_providers_know_every_model_is_ok(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[str] = []
    setup = LLMSetup((_anthropic(KNOWN, seen), _gemini(_gemini_model)))

    assert setup.status == "checking"
    assert _verified(setup).status == "ok"
    assert sorted(seen) == ["fast-model", "strong-model"]
    assert _errors(caplog) == []


def test_a_model_the_provider_does_not_know_makes_the_setup_unavailable_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    setup = _verified(LLMSetup((_anthropic(frozenset({"fast-model"}), []),)))

    assert setup.status == "unavailable"
    (error,) = _errors(caplog)
    assert error.startswith("LLM setup: anthropic answered HTTP 404 for model strong-model: ")
    assert "nope" in error
