import os

import pytest
from pydantic import ValidationError

from crawlerai.core.settings import DatabaseSettings, Settings

_REQUIRED = {
    "CRAWLERAI_DATABASE_URL": "postgresql+asyncpg://app:pw@localhost:5432/crawlerai",
    "CRAWLERAI_OBJECT_STORE": "fs:///srv/objects",
}
_OPTIONAL = [
    "CRAWLERAI_EVAL_PRIVATE_DATABASE_URL",
    "CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE",
    "CRAWLERAI_LOG_REDACT_URLS",
    "CRAWLERAI_ROLE",
    "CRAWLERAI_IMPERSONATE",
    "CRAWLERAI_DISABLED_ADAPTERS",
    "CRAWLERAI_EVAL_UI",
    "CRAWLERAI_LLM_PROVIDERS",
    "CRAWLERAI_LLM_FAST_MODEL_ANTHROPIC",
    "CRAWLERAI_LLM_API_KEY_GEMINI",
    "CRAWLERAI_TRUSTED_PROXIES",
    "CRAWLERAI_API_RATE_PER_S",
    "CRAWLERAI_API_RATE_BURST",
]


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
    env.setenv("CRAWLERAI_ROLE", "worker")
    env.setenv("CRAWLERAI_EVAL_UI", "true")

    settings = Settings()

    assert settings.database_url.get_secret_value() == "postgresql+asyncpg://app:pw@localhost:5432/crawlerai"
    assert settings.object_store == "fs:///srv/objects"
    assert settings.log_redact_urls is True
    assert settings.role == "worker"
    assert settings.eval_ui is True


def test_optional_settings_set_empty_take_their_unset_values(env: pytest.MonkeyPatch) -> None:
    # Agents and developers carry the private settings empty, and unset CI secrets arrive as "" (SPEC-00 §4.4).
    unset = Settings()
    for name in _OPTIONAL:
        env.setenv(name, "")

    empty = Settings()

    assert empty == unset
    # Documented defaults: SPEC-06 §4.2 (provider order), SPEC-07 §4.2 (20 req/s, burst 40; no trusted proxies,
    # RFC 7239 §8.1), SPEC-03 §4.10 (labeling API off).
    assert (empty.llm_providers, empty.api_rate_per_s, empty.api_rate_burst, empty.trusted_proxies, empty.eval_ui) == (
        ("anthropic", "gemini"),
        20,
        40,
        (),
        False,
    )
    assert (empty.eval_private_database_url, empty.eval_private_object_store) == (None, None)


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


@pytest.mark.parametrize("store", ["fs:///srv/objects", "s3://bucket/prefix/part"])
def test_object_store_in_fs_or_s3_form_is_accepted(env: pytest.MonkeyPatch, store: str) -> None:
    env.setenv("CRAWLERAI_OBJECT_STORE", store)

    assert Settings().object_store == store


def test_unknown_role_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("CRAWLERAI_ROLE", "admin")

    with pytest.raises(ValidationError):
        Settings()


def test_database_settings_need_only_the_database_url(env: pytest.MonkeyPatch) -> None:
    # Migrations read only the database URL; they must not require the object store.
    env.delenv("CRAWLERAI_OBJECT_STORE")

    url = DatabaseSettings().database_url.get_secret_value()

    assert url == "postgresql+asyncpg://app:pw@localhost:5432/crawlerai"


def test_impersonate_names_a_curl_cffi_browser_profile(env: pytest.MonkeyPatch) -> None:
    env.setenv("CRAWLERAI_IMPERSONATE", "chrome146")
    assert Settings().impersonate == "chrome146"

    env.setenv("CRAWLERAI_IMPERSONATE", "chrome9999")
    with pytest.raises(ValidationError, match="impersonate"):
        Settings()


@pytest.mark.parametrize(
    ("value", "providers"),
    [
        ("gemini,anthropic", ("gemini", "anthropic")),
        (" anthropic , gemini ", ("anthropic", "gemini")),
    ],
)
def test_llm_providers_are_a_comma_separated_failover_order(
    env: pytest.MonkeyPatch, value: str, providers: tuple[str, ...]
) -> None:
    env.setenv("CRAWLERAI_LLM_PROVIDERS", value)
    assert Settings().llm_providers == providers


@pytest.mark.parametrize("value", ["anthropic,anthropic", "anthropic,other"])
def test_a_repeated_or_unknown_llm_provider_is_rejected(env: pytest.MonkeyPatch, value: str) -> None:
    env.setenv("CRAWLERAI_LLM_PROVIDERS", value)
    with pytest.raises(ValidationError, match="llm_providers"):
        Settings()


def test_trusted_proxies_are_a_json_list_of_addresses_or_networks(env: pytest.MonkeyPatch) -> None:
    env.setenv("CRAWLERAI_TRUSTED_PROXIES", '["10.0.0.0/8", "192.0.2.7", "2001:db8::/32"]')
    assert [str(network) for network in Settings().trusted_proxies] == ["10.0.0.0/8", "192.0.2.7/32", "2001:db8::/32"]


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
