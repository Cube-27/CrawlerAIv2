"""The configured providers: `CRAWLERAI_LLM_PROVIDERS` sets which providers and their failover order;
a listed provider without an API key stops the client from being built, and the log says so."""

import pytest
from pydantic import SecretStr

from crawlerai.core.settings import LLMSettings
from crawlerai.llm.providers.from_settings import providers_from_settings

KEYS = {"llm_api_key_anthropic": SecretStr("a-key"), "llm_api_key_gemini": SecretStr("g-key")}


def test_each_provider_gets_its_model_per_class() -> None:
    models = {
        "llm_fast_model_anthropic": "a-fast",
        "llm_strong_model_anthropic": "a-strong",
        "llm_fast_model_gemini": "g-fast",
        "llm_strong_model_gemini": "g-strong",
    }
    settings = LLMSettings.model_validate({"llm_providers": ("anthropic", "gemini")} | models | KEYS)

    anthropic, gemini = providers_from_settings(settings)

    assert (anthropic.models, gemini.models) == (
        {"fast": "a-fast", "strong": "a-strong"},
        {"fast": "g-fast", "strong": "g-strong"},
    )


@pytest.mark.parametrize("missing", ["anthropic", "gemini"])
def test_a_listed_provider_without_a_key_is_refused(missing: str) -> None:
    keys = {name: key for name, key in KEYS.items() if not name.endswith(missing)}
    settings = LLMSettings.model_validate({"llm_providers": ("anthropic", "gemini")} | keys)
    with pytest.raises(ValueError, match=f"CRAWLERAI_LLM_API_KEY_{missing.upper()} is not set"):
        providers_from_settings(settings)
