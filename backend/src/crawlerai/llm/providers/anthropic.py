"""The Anthropic provider (llm spec): the Messages API through the official SDK, with structured output.

The reply is constrained by `output_config.format` (`json_schema`); the client still validates it (§4.2). The SDK's own
retries are off: a rate limit, a server error or a timeout raises `ProviderError` at once, and the client fails over
(§4.2); any other error status raises `ProviderRefused`. No sampling parameter is sent: the current Claude models
reject a non-default `temperature` with a 400, so temperature 0 (§4.2) cannot be asked for here; a replay stays
deterministic because it calls no LLM (INV-10).

The current Claude models think before they answer unless told otherwise, and thinking tokens are billed as output
and count against `max_tokens`. A `fast` call (role C copies spans out of a page) asks for `low` effort, the API's
documented `output_config.effort` setting, so the reply is not spent on reasoning (F29); a `strong` call keeps the
model's default.
"""

from collections.abc import Mapping

import httpx2
from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic
from anthropic.types import CacheControlEphemeralParam, OutputConfigParam, TextBlock, TextBlockParam

from crawlerai.core.retry import is_transient
from crawlerai.llm.client import (
    ModelClass,
    ProviderCall,
    ProviderError,
    ProviderRefused,
    ProviderReply,
    redacted,
)
from crawlerai.llm.setup import CHECK_TIMEOUT_S

_CACHE: CacheControlEphemeralParam = {"type": "ephemeral"}


def _system(call: ProviderCall) -> str | list[TextBlockParam]:
    """The system prompt; a call with cached parts caches it too (a breakpoint is the end of a cached prefix: tools,
    system, then the messages' blocks in order)."""
    if not call.cached:
        return call.system
    return [{"type": "text", "text": call.system, "cache_control": _CACHE}]


def _content(call: ProviderCall) -> str | list[TextBlockParam]:
    """The user message: each cached part is a block ending a cached prefix, then the uncached `user` text."""
    if not call.cached:
        return call.user
    blocks: list[TextBlockParam] = [{"type": "text", "text": part, "cache_control": _CACHE} for part in call.cached]
    return [*blocks, {"type": "text", "text": call.user}]


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, api_key: str, models: Mapping[ModelClass, str], http_client: httpx2.AsyncClient | None = None
    ) -> None:
        """`models` maps each model class to a model id (settings); `http_client` is for tests."""
        self._sdk = AsyncAnthropic(api_key=api_key, max_retries=0, http_client=http_client)
        self._key = api_key
        self.models = dict(models)

    async def complete(self, call: ProviderCall) -> ProviderReply:
        model = self.models[call.model_class]
        output: OutputConfigParam = {"format": {"type": "json_schema", "schema": dict(call.output_schema)}}
        if call.model_class == "fast":
            output["effort"] = "low"
        try:
            message = await self._sdk.messages.create(
                model=model,
                max_tokens=call.max_output_tokens,
                system=_system(call),
                messages=[{"role": "user", "content": _content(call)}],
                output_config=output,
                timeout=call.timeout_s,
            )
        except APIConnectionError as error:  # includes APITimeoutError
            raise ProviderError(f"no response ({type(error).__name__})") from error
        except APIStatusError as error:
            if is_transient(error.status_code):
                raise ProviderError(f"HTTP {error.status_code}") from error
            reason = redacted(error.message, self._key)
            raise ProviderRefused(self.name, model, error.status_code, reason) from error
        # Thinking blocks may precede the answer; the answer is the text.
        text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
        return ProviderReply(
            model=message.model,
            text=text,
            tokens_in=message.usage.input_tokens,
            tokens_out=message.usage.output_tokens,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
            cut=message.stop_reason == "max_tokens",
        )

    async def check_model(self, model: str) -> str | None:
        """What the Models API says is wrong with the model id `model`; None when it knows it
        (`crawlerai.llm.setup`)."""
        try:
            await self._sdk.models.retrieve(model, timeout=CHECK_TIMEOUT_S)
        except APIConnectionError as error:
            return f"{self.name} did not answer for model {model} ({type(error).__name__})"
        except APIStatusError as error:
            reason = redacted(error.message, self._key)
            return f"{self.name} answered HTTP {error.status_code} for model {model}: {reason}"
        return None
