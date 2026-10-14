"""Scripted test doubles (SPEC-06 §6): no provider is called in CI.

`FakeProvider` answers each call with the next scripted reply, or raises the next scripted error (a `ProviderError`, or
a `ProviderRefused`), and keeps
the calls it received so tests can check what the client sent. `ScriptedClient` does the same one level up, for a role
under test: it stands in for the LLM client.
"""

from collections.abc import Iterable, Mapping

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from crawlerai.llm.client import (
    LLMRequest,
    LLMResponse,
    ProviderCall,
    ProviderError,
    ProviderReply,
    ReplyCheck,
    request_hash,
)


class FakeProvider:
    def __init__(self, script: Iterable[ProviderReply | Exception], name: str = "fake") -> None:
        self.name = name
        self._script = list(script)
        self.calls: list[ProviderCall] = []

    async def complete(self, call: ProviderCall) -> ProviderReply:
        self.calls.append(call)
        if not self._script:
            raise ProviderError("no scripted reply left")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class ScriptedClient:
    """Answers each call with the next scripted reply, or raises the next scripted failure; keeps the requests. Like the
    real client, it validates every reply against the request's output schema."""

    def __init__(self, *script: Mapping[str, JsonValue] | Exception, model: str = "fake-fast") -> None:
        self._script = list(script)
        self._model = model
        self.requests: list[LLMRequest] = []

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        self.requests.append(req)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        Draft202012Validator(req.output_schema).validate(step)
        return LLMResponse(
            data=dict(step),
            provider="fake",
            model=self._model,
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            request_hash=request_hash(req),
        )
