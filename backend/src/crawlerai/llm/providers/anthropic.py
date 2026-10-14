"""The Anthropic provider (SPEC-06 §4.1): the Messages API through the official SDK, with structured output.

The reply is constrained by `output_config.format` (`json_schema`); the client still validates it (§4.2). The SDK's own
retries are off: a rate limit, a server error or a timeout raises `ProviderError` at once, and the client fails over
(§4.2); any other error status raises `ProviderRefused`. No sampling parameter is sent: the current Claude models
reject a non-default `temperature` with a 400, so temperature 0 (§4.2) cannot be asked for here; replays stay
deterministic through the recorded cache (INV-10).
"""

from collections.abc import Mapping

import httpx2
from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic
from anthropic.types import TextBlock

from crawlerai.llm.client import ModelClass, ProviderCall, ProviderError, ProviderRefused, ProviderReply, is_transient


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, api_key: str, models: Mapping[ModelClass, str], http_client: httpx2.AsyncClient | None = None
    ) -> None:
        """`models` maps each model class to a model id (settings); `http_client` is for tests."""
        self._sdk = AsyncAnthropic(api_key=api_key, max_retries=0, http_client=http_client)
        self.models = dict(models)

    async def complete(self, call: ProviderCall) -> ProviderReply:
        schema: dict[str, object] = dict(call.output_schema)
        try:
            message = await self._sdk.messages.create(
                model=self.models[call.model_class],
                max_tokens=call.max_output_tokens,
                system=call.system,
                messages=[{"role": "user", "content": call.user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
                timeout=call.timeout_s,
            )
        except APIConnectionError as error:  # includes APITimeoutError
            raise ProviderError(f"no response ({type(error).__name__})") from error
        except APIStatusError as error:
            if is_transient(error.status_code):
                raise ProviderError(f"HTTP {error.status_code}") from error
            raise ProviderRefused.status(self.name, error.status_code, error.message) from error
        # Thinking blocks may precede the answer; the answer is the text.
        text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
        return ProviderReply(
            model=message.model,
            text=text,
            tokens_in=message.usage.input_tokens,
            tokens_out=message.usage.output_tokens,
        )
