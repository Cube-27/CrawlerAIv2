"""The configured providers, in failover order (SPEC-06 §4.2): `CRAWLERAI_LLM_PROVIDERS`, the model per class for
each, and each one's API key."""

from pydantic import SecretStr

from crawlerai.core.settings import LLMProviderName, LLMSettings
from crawlerai.llm.client import ModelClass
from crawlerai.llm.providers.anthropic import AnthropicProvider
from crawlerai.llm.providers.gemini import GeminiProvider


def providers_from_settings(settings: LLMSettings) -> list[AnthropicProvider | GeminiProvider]:
    """Raises `ValueError` when a listed provider has no API key: the client is not built half-configured."""
    return [_provider(name, settings) for name in settings.llm_providers]


def _provider(name: LLMProviderName, settings: LLMSettings) -> AnthropicProvider | GeminiProvider:
    if name == "anthropic":
        models: dict[ModelClass, str] = {
            "fast": settings.llm_fast_model_anthropic,
            "strong": settings.llm_strong_model_anthropic,
        }
        return AnthropicProvider(_key(settings.llm_api_key_anthropic, name), models)
    models = {"fast": settings.llm_fast_model_gemini, "strong": settings.llm_strong_model_gemini}
    return GeminiProvider(_key(settings.llm_api_key_gemini, name), models)


def _key(secret: SecretStr | None, name: LLMProviderName) -> str:
    if secret is None:
        raise ValueError(f"CRAWLERAI_LLM_API_KEY_{name.upper()} is not set")
    return secret.get_secret_value()
