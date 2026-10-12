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

    settings = Settings()

    assert settings.database_url.get_secret_value() == "postgresql+asyncpg://app:pw@localhost:5432/crawlerai"
    assert settings.object_store == "fs:///srv/objects"
    assert settings.log_redact_urls is True
    assert settings.role == "worker"


@pytest.mark.parametrize("empty", [False, True], ids=["unset", "empty"])
def test_optional_settings_unset_or_empty_take_their_unset_values(env: pytest.MonkeyPatch, empty: bool) -> None:
    # Agents and developers carry the private settings empty, and unset CI secrets arrive as "" (SPEC-00 §4.4).
    if empty:
        for name in _OPTIONAL:
            env.setenv(name, "")

    settings = Settings()

    assert settings.eval_private_database_url is None
    assert settings.eval_private_object_store is None
    assert settings.log_redact_urls is False
    assert settings.role is None


def test_database_url_is_not_shown_in_repr(env: pytest.MonkeyPatch) -> None:
    assert "pw@" not in repr(Settings())


@pytest.mark.parametrize("empty", [False, True], ids=["unset", "empty"])
@pytest.mark.parametrize("name", list(_REQUIRED))
def test_required_setting_unset_or_empty_is_rejected(env: pytest.MonkeyPatch, name: str, empty: bool) -> None:
    if empty:
        env.setenv(name, "")
    else:
        env.delenv(name)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("store", ["fs://relative/path", "file:///srv/objects", "/srv/objects", "s3://"])
def test_object_store_outside_fs_or_s3_form_is_rejected(env: pytest.MonkeyPatch, store: str) -> None:
    env.setenv("CRAWLERAI_OBJECT_STORE", store)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("store", ["fs:///srv/objects", "s3://bucket", "s3://bucket/prefix/part"])
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
