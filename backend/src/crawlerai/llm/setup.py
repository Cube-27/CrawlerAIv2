"""The LLM setup check (SPEC-06 §4.2): whether the configured providers can serve calls. A listed provider without its
API key, or a configured model id its provider does not know, would otherwise show only as `llm_unavailable` on every
record while the requests succeed. The check logs each problem at ERROR once, when a process starts, and its status
is what `GET /healthz` reports (the problems stay in the log: the probe is unauthenticated).

A model is asked of its provider's model lookup, which spends no tokens. Nothing is retried; a provider that does
not answer the check leaves the setup `unavailable` until the process restarts.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Literal, Protocol

from crawlerai.core.settings import LLMSettings
from crawlerai.llm.providers.from_settings import providers_from_settings

log = logging.getLogger(__name__)

LLMStatus = Literal["checking", "ok", "unavailable"]


class CheckedProvider(Protocol):
    async def check_models(self) -> tuple[str, ...]:
        """What is wrong with the provider's configured models; empty when it knows them all."""
        ...


class LLMSetup:
    """The setup's status: `checking` until `verify` has asked every provider, then `ok` or `unavailable`."""

    def __init__(self, providers: Sequence[CheckedProvider], status: LLMStatus = "checking") -> None:
        self.status: LLMStatus = status
        self._providers = tuple(providers)

    @classmethod
    def of(cls, settings: LLMSettings) -> "LLMSetup":
        """The setup of `settings`, `unavailable` at once (and logged) when a listed provider has no key or none is
        listed: that needs no provider's answer."""
        try:
            providers = providers_from_settings(settings)
        except ValueError as e:
            return cls._failed(str(e))
        if not providers:
            return cls._failed("no LLM provider is listed (CRAWLERAI_LLM_PROVIDERS)")
        return cls(providers)

    @classmethod
    def _failed(cls, problem: str) -> "LLMSetup":
        log.error("LLM setup: %s", problem)
        return cls((), "unavailable")

    async def verify(self) -> None:
        """Ask every provider about its models, log each problem at ERROR, and settle the status."""
        if self.status != "checking":
            return
        found = await asyncio.gather(*(provider.check_models() for provider in self._providers))
        problems = [problem for problems in found for problem in problems]
        for problem in problems:
            log.error("LLM setup: %s", problem)
        self.status = "unavailable" if problems else "ok"
