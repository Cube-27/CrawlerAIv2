"""The Gemini provider: `generateContent` through the official `google-genai` SDK, with structured
output.

The reply is constrained by `response_json_schema` with `response_mime_type="application/json"`; the client still
validates it. Temperature is 0. The SDK does not retry unless asked to, so a rate limit, a server error
or a timeout raises `ProviderError` at once and the client fails over; any other error status raises
`ProviderRefused`.
"""

from collections.abc import Mapping

import httpx
from google import genai
from google.genai import errors, types

from snowcrawl.core.retry import is_transient
from snowcrawl.llm.client import (
    ModelClass,
    ProviderCall,
    ProviderError,
    ProviderRefused,
    ProviderReply,
    redacted,
)
from snowcrawl.llm.setup import CHECK_TIMEOUT_S


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, api_key: str, models: Mapping[ModelClass, str], http_client: httpx.AsyncClient | None = None
    ) -> None:
        """`models` maps each model class to a model id (settings); `http_client` is for tests."""
        self._sdk = genai.Client(api_key=api_key, http_options=types.HttpOptions(httpx_async_client=http_client))
        self._key = api_key
        self.models = dict(models)

    async def complete(self, call: ProviderCall) -> ProviderReply:
        model = self.models[call.model_class]
        config = types.GenerateContentConfig(
            system_instruction=call.system,
            temperature=0,
            max_output_tokens=call.max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=call.output_schema,
            http_options=types.HttpOptions(timeout=call.timeout_s * 1000),  # milliseconds
        )
        try:
            response = await self._sdk.aio.models.generate_content(
                model=model, contents="\n\n".join([*call.cached, call.user]), config=config
            )
        except httpx.TransportError as error:  # includes timeouts
            raise ProviderError(f"no response ({type(error).__name__})") from error
        except errors.APIError as error:
            if is_transient(error.code):
                raise ProviderError(f"HTTP {error.code}") from error
            raise ProviderRefused(self.name, model, error.code, redacted(error.message or "", self._key)) from error
        usage = response.usage_metadata or types.GenerateContentResponseUsageMetadata()
        candidates = response.candidates or []
        return ProviderReply(
            model=response.model_version or model,
            text=response.text or "",
            tokens_in=usage.prompt_token_count or 0,
            # Thinking tokens are billed as output.
            tokens_out=(usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
            cut=any(candidate.finish_reason == types.FinishReason.MAX_TOKENS for candidate in candidates),
        )

    async def check_model(self, model: str) -> str | None:
        """What the models endpoint says is wrong with the model id `model`; None when it knows it
        (`snowcrawl.llm.setup`)."""
        config = types.GetModelConfig(http_options=types.HttpOptions(timeout=round(CHECK_TIMEOUT_S * 1000)))
        try:
            await self._sdk.aio.models.get(model=model, config=config)
        except httpx.TransportError as error:
            return f"{self.name} did not answer for model {model} ({type(error).__name__})"
        except errors.APIError as error:
            return (
                f"{self.name} answered HTTP {error.code} for model {model}: {redacted(error.message or '', self._key)}"
            )
        return None
