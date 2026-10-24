"""The LLM setup check: whether the configured providers can serve calls. A listed provider without its
API key (`ProviderUnavailable`: `llm_unavailable`), or a configured model id its provider does not know (the provider
refuses it: `llm_refused`), would otherwise show only on every record while the requests succeed. Each problem is
logged at ERROR once, when a process starts, and the status is what `GET /healthz` reports (the problems stay in the
log: the probe is unauthenticated).

A model is asked of its provider's model lookup, which spends no tokens. Nothing is retried; a provider that does
not answer the check leaves the setup `unavailable` until the process restarts.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from snowcrawl.llm.client import ModelClass

log = logging.getLogger(__name__)

LLMStatus = Literal["checking", "ok", "unavailable"]
# The bound on one model lookup: a probe, not a call.
CHECK_TIMEOUT_S = 10.0


class CheckedProvider(Protocol):
    @property
    def models(self) -> Mapping[ModelClass, str]: ...

    async def check_model(self, model: str) -> str | None:
        """What is wrong with the model id `model`; None when the provider knows it."""
        ...


class LLMSetup:
    """The setup's status: `checking` until `verify` has asked every provider about its models, then `ok` or
    `unavailable`; `unavailable` from the start without providers (`unavailable`)."""

    def __init__(self, providers: Sequence[CheckedProvider]) -> None:
        self.status: LLMStatus = "checking"
        self._providers = tuple(providers)

    @classmethod
    def unavailable(cls, problem: str) -> "LLMSetup":
        """A setup no provider can serve, for `problem`, which is logged."""
        log.error("LLM setup: %s", problem)
        setup = cls(())
        setup.status = "unavailable"
        return setup

    async def verify(self) -> None:
        """Ask every provider about each of its models at once, log each problem at ERROR, and settle the status."""
        if not self._providers:
            return
        checks = [
            provider.check_model(model)
            for provider in self._providers
            for model in sorted(set(provider.models.values()))
        ]
        problems = [problem for problem in await asyncio.gather(*checks) if problem is not None]
        for problem in problems:
            log.error("LLM setup: %s", problem)
        self.status = "unavailable" if problems else "ok"
