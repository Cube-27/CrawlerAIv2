"""The Gemini provider (SPEC-06 §4.1): `generateContent` through the official `google-genai` SDK, with structured
output.

The reply is constrained by `response_json_schema` with `response_mime_type="application/json"`; the client still
validates it (§4.2). Temperature is 0 (§4.2). The SDK does not retry unless asked to, so a rate limit, a server error
or a timeout raises `ProviderError` at once and the client fails over (§4.2); any other error status raises
`ProviderRefused`.
"""

from collections.abc import Mapping

import httpx
from google import genai
from google.genai import errors, types

from crawlerai.llm.client import ModelClass, ProviderCall, ProviderError, ProviderRefused, ProviderReply, is_transient


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, api_key: str, models: Mapping[ModelClass, str], http_client: httpx.AsyncClient | None = None
    ) -> None:
        """`models` maps each model class to a model id (settings); `http_client` is for tests."""
        self._sdk = genai.Client(api_key=api_key, http_options=types.HttpOptions(httpx_async_client=http_client))
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
            response = await self._sdk.aio.models.generate_content(model=model, contents=call.user, config=config)
        except httpx.TransportError as error:  # includes timeouts
            raise ProviderError(f"no response ({type(error).__name__})") from error
        except errors.APIError as error:
            if is_transient(error.code):
                raise ProviderError(f"HTTP {error.code}") from error
            raise ProviderRefused.status(self.name, error.code, error.message or "") from error
        usage = response.usage_metadata or types.GenerateContentResponseUsageMetadata()
        return ProviderReply(
            model=response.model_version or model,
            text=response.text or "",
            tokens_in=usage.prompt_token_count or 0,
            # Thinking tokens are billed as output.
            tokens_out=(usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
        )
