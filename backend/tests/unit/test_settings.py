import os

import pytest
from pydantic import ValidationError

from crawlerai.core.settings import Settings

_REQUIRED = {
    "CRAWLERAI_DATABASE_URL": "postgresql+asyncpg://app:pw@localhost:5432/crawlerai",
    "CRAWLERAI_OBJECT_STORE": "fs:///srv/objects",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in list(os.environ):
        if name.upper().startswith("CRAWLERAI_"):
            monkeypatch.delenv(name)
    for name, value in _REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_reads_crawlerai_prefixed_environment(env: pytest.MonkeyPatch) -> None:
    env.setenv("CRAWLERAI_LOG_REDACT_URLS", "true")
    env.setenv("CRAWLERAI_EVAL_UI", "true")

    settings = Settings()

    assert settings.database_url.get_secret_value() == "postgresql+asyncpg://app:pw@localhost:5432/crawlerai"
    assert settings.object_store == "fs:///srv/objects"
    assert settings.log_redact_urls is True
    assert settings.eval_ui is True


def test_the_database_url_and_llm_api_keys_are_not_shown_in_repr(env: pytest.MonkeyPatch) -> None:
    env.setenv("CRAWLERAI_LLM_API_KEY_ANTHROPIC", "secret-key-value")

    settings = Settings()

    assert "pw@" not in repr(settings)
    assert "secret-key-value" not in repr(settings)
    assert settings.llm_api_key_anthropic is not None
    assert settings.llm_api_key_anthropic.get_secret_value() == "secret-key-value"


@pytest.mark.parametrize("empty", [False, True], ids=["unset", "empty"])
@pytest.mark.parametrize("name", list(_REQUIRED))
def test_required_setting_unset_or_empty_is_rejected(env: pytest.MonkeyPatch, name: str, empty: bool) -> None:
    if empty:
        env.setenv(name, "")
    else:
        env.delenv(name)

    with pytest.raises(ValidationError, match=name.removeprefix("CRAWLERAI_").lower()):
        Settings()


@pytest.mark.parametrize("store", ["fs://relative/path", "file:///srv/objects", "s3://"])
def test_object_store_outside_fs_or_s3_form_is_rejected(env: pytest.MonkeyPatch, store: str) -> None:
    env.setenv("CRAWLERAI_OBJECT_STORE", store)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CRAWLERAI_TRUSTED_PROXIES", '["not-an-address"]'),
        ("CRAWLERAI_API_RATE_PER_S", "0"),
        ("CRAWLERAI_API_RATE_BURST", "0"),
    ],
)
def test_an_invalid_trusted_proxy_or_rate_limit_is_rejected(env: pytest.MonkeyPatch, name: str, value: str) -> None:
    env.setenv(name, value)
    with pytest.raises(ValidationError, match=name.removeprefix("CRAWLERAI_").lower()):
        Settings()
