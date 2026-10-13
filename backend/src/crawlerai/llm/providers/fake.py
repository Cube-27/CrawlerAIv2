"""A scripted provider for tests (SPEC-06 §6): no provider is called in CI.

It answers each call with the next scripted reply, or raises the next scripted `ProviderError`, and keeps the calls
it received so tests can check what the client sent.
"""

from collections.abc import Iterable

from crawlerai.llm.client import ProviderCall, ProviderError, ProviderReply


class FakeProvider:
    def __init__(self, script: Iterable[ProviderReply | ProviderError], name: str = "fake") -> None:
        self.name = name
        self._script = list(script)
        self.calls: list[ProviderCall] = []

    async def complete(self, call: ProviderCall) -> ProviderReply:
        self.calls.append(call)
        if not self._script:
            raise ProviderError("no scripted reply left")
        step = self._script.pop(0)
        if isinstance(step, ProviderError):
            raise step
        return step
