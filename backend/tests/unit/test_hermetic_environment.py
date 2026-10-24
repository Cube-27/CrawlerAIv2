"""Tests are hermetic: the developer's `SNOWCRAWL_*` variables (the Makefile exports `.env` under `make check`) never
reach a test, so a settings object a test builds reads only what the test sets. The test databases' own variables
(`SNOWCRAWL_TEST_*`) are the exception: they name where DB tests may write."""

import pytest

from snowcrawl.core.settings import LLMSettings


def test_settings_built_in_a_test_see_only_the_tests_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNOWCRAWL_LLM_PROVIDERS", "gemini")
    settings = LLMSettings()
    assert (settings.llm_providers, settings.llm_api_key_anthropic, settings.llm_api_key_gemini) == (
        ("gemini",),
        None,
        None,
    )
