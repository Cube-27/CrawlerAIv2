"""Process settings, read from `CRAWLERAI_*` environment variables (SPEC-00 §4.4).

The variable names are the contract; later specs add settings here. The two `EVAL_PRIVATE_*` settings are set only
in the custodian's environment (C1) and are empty everywhere else.
An empty value counts as unset, so unset CI secrets (which arrive as "") behave like absent variables.
"""

from typing import Annotated, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# `fs:///<absolute path>` or `s3://<bucket>[/<prefix>]` (SPEC-00 §4.4).
OBJECT_STORE_URL_PATTERN = r"^(fs:///.+|s3://[^/]+(/.*)?)$"
ObjectStoreUrl = Annotated[str, Field(pattern=OBJECT_STORE_URL_PATTERN)]

Role = Literal["api", "worker", "scheduler"]


class DatabaseSettings(BaseSettings):
    """The subset that migrations need, so running them does not require the rest."""

    model_config = SettingsConfigDict(env_prefix="CRAWLERAI_", env_ignore_empty=True, frozen=True)

    database_url: SecretStr


class Settings(DatabaseSettings):
    eval_private_database_url: SecretStr | None = None
    object_store: ObjectStoreUrl
    eval_private_object_store: ObjectStoreUrl | None = None
    log_redact_urls: bool = False
    role: Role | None = None
