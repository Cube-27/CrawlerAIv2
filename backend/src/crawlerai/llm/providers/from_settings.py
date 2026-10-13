"""The configured providers, in failover order (SPEC-06 §4.2): `CRAWLERAI_LLM_PROVIDERS`, the model per class for
each, and each one's API key."""

from typing import assert_never

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.core.settings import LLMProviderName, LLMSettings
from crawlerai.llm.client import LLMClient, MeteredClient, ModelClass, Unconfigured
from crawlerai.llm.providers.anthropic import AnthropicProvider
from crawlerai.llm.providers.gemini import GeminiProvider


def providers_from_settings(settings: LLMSettings) -> list[AnthropicProvider | GeminiProvider]:
    """Raises `ValueError` when a listed provider has no API key: the client is not built half-configured."""
    return [_provider(name, settings) for name in settings.llm_providers]


def client_from_settings(settings: LLMSettings, engine: AsyncEngine) -> LLMClient:
    """The configured providers' client, or, when a listed provider has no API key, an `Unconfigured` one that names
    the missing key on every call: a process starts without keys, and work that needs no call still runs."""
    try:
        return MeteredClient(providers_from_settings(settings), engine)
    except ValueError as e:
        return Unconfigured(str(e))


def _provider(name: LLMProviderName, settings: LLMSettings) -> AnthropicProvider | GeminiProvider:
    models: dict[ModelClass, str]
    match name:
        case "anthropic":
            models = {"fast": settings.llm_fast_model_anthropic, "strong": settings.llm_strong_model_anthropic}
            return AnthropicProvider(_key(settings.llm_api_key_anthropic, name), models)
        case "gemini":
            models = {"fast": settings.llm_fast_model_gemini, "strong": settings.llm_strong_model_gemini}
            return GeminiProvider(_key(settings.llm_api_key_gemini, name), models)
        case _:  # a new provider name fails type-checking here until it has a case
            assert_never(name)


def _key(secret: SecretStr | None, name: LLMProviderName) -> str:
    if secret is None:
        raise ValueError(f"CRAWLERAI_LLM_API_KEY_{name.upper()} is not set")
    return secret.get_secret_value()
