"""The configured providers (SPEC-06 §4.2): `CRAWLERAI_LLM_PROVIDERS` sets which providers and their failover order;
a listed provider without an API key stops the client from being built, and the log says so."""

import logging

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.settings import LLMSettings
from crawlerai.llm import setup as llm_setup
from crawlerai.llm.client import MeteredClient, Unconfigured
from crawlerai.llm.providers.from_settings import llm_from_settings, providers_from_settings

KEYS = {"llm_api_key_anthropic": SecretStr("a-key"), "llm_api_key_gemini": SecretStr("g-key")}


@pytest.mark.parametrize("order", [("anthropic", "gemini"), ("gemini", "anthropic")], ids=lambda order: ",".join(order))
def test_providers_come_in_the_configured_order(order: tuple[str, ...]) -> None:
    settings = LLMSettings.model_validate({"llm_providers": order} | KEYS)
    assert [provider.name for provider in providers_from_settings(settings)] == list(order)


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


def test_an_unlisted_provider_needs_no_key() -> None:
    settings = LLMSettings.model_validate({"llm_providers": ("gemini",), "llm_api_key_gemini": SecretStr("g-key")})
    assert [provider.name for provider in providers_from_settings(settings)] == ["gemini"]


def test_a_client_without_a_listed_key_says_why_once_when_it_is_built(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-0375, D-0468: the process starts without the client, and the log names the missing key (F05), at ERROR.
    # Alembic's `fileConfig` (migrations/env.py) disables existing loggers when a DB test migrates in this process.
    monkeypatch.setattr(llm_setup.log, "disabled", False)
    settings = LLMSettings.model_validate(
        {"llm_providers": ("anthropic", "gemini")} | KEYS | {"llm_api_key_gemini": None}
    )
    engine = create_async_engine("postgresql+asyncpg://127.0.0.1/unused")  # never connected

    with caplog.at_level(logging.WARNING, logger="crawlerai.llm.setup"):
        client, _ = llm_from_settings(settings, engine)

    assert isinstance(client, Unconfigured)
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("ERROR", "LLM setup: CRAWLERAI_LLM_API_KEY_GEMINI is not set")
    ]


def test_a_configured_client_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    settings = LLMSettings.model_validate({"llm_providers": ("anthropic", "gemini")} | KEYS)

    with caplog.at_level(logging.WARNING):
        client, _ = llm_from_settings(settings, create_async_engine("postgresql+asyncpg://127.0.0.1/unused"))

    assert (isinstance(client, MeteredClient), caplog.records) == (True, [])


def test_role_a_page_input_is_capped_at_60k_characters() -> None:
    assert LLMSettings.model_validate(KEYS).llm_a_max_chars == 60_000
    assert LLMSettings.model_validate(KEYS | {"llm_a_max_chars": 1}).llm_a_max_chars == 1
    with pytest.raises(ValidationError):
        LLMSettings.model_validate(KEYS | {"llm_a_max_chars": 60_001})
