"""Process settings, read from `CRAWLERAI_*` environment variables (SPEC-00 §4.4).

The variable names are the contract; later specs add settings here. The two `EVAL_PRIVATE_*` settings are set only
in the custodian's environment (C1) and are empty everywhere else.
An empty value counts as unset, so unset CI secrets (which arrive as "") behave like absent variables.
"""

from typing import Annotated, Literal

from curl_cffi.requests import BrowserTypeLiteral
from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from crawlerai.core.proxy import ProxyEndpoint

# `fs:///<absolute path>` or `s3://<bucket>[/<prefix>]` (SPEC-00 §4.4).
OBJECT_STORE_URL_PATTERN = r"^(fs:///.+|s3://[^/]+(/.*)?)$"
ObjectStoreUrl = Annotated[str, Field(pattern=OBJECT_STORE_URL_PATTERN)]

Role = Literal["api", "worker", "scheduler"]

# The newest Chrome profile curl_cffi supports at lock time (SPEC-02 §4.7).
IMPERSONATE_DEFAULT: BrowserTypeLiteral = "chrome150"


class _Base(BaseSettings):
    # Validation errors leave out the input: settings hold credentials (database and proxy URLs).
    model_config = SettingsConfigDict(
        env_prefix="CRAWLERAI_", env_ignore_empty=True, frozen=True, hide_input_in_errors=True
    )


class DatabaseSettings(_Base):
    """The subset that migrations need, so running them does not require the rest."""

    database_url: SecretStr


class EvalPrivateDatabaseSettings(_Base):
    """What migrating the private eval database needs (`alembic -n private`). Custodian machines only (C1)."""

    eval_private_database_url: SecretStr


class AcquireSettings(_Base):
    """The subset a fetch needs, so `crawlerai fetch` runs without a database or object store."""

    impersonate: BrowserTypeLiteral = IMPERSONATE_DEFAULT
    # `CRAWLERAI_PROXY_POOLS`, JSON `{pool_name: proxy_url}` (SPEC-02 §3, OPEN_QUESTIONS #10).
    proxy_pools: dict[str, Annotated[ProxyEndpoint, BeforeValidator(ProxyEndpoint.parse)]] = Field(default_factory=dict)


class ApiSettings(_Base):
    """What the app factory reads to decide which routers to mount."""

    # Mounts the labeling endpoints (SPEC-03 §4.10). They serve the dev split only (C1).
    eval_ui: bool = False


class Settings(DatabaseSettings, AcquireSettings, ApiSettings):
    eval_private_database_url: SecretStr | None = None
    object_store: ObjectStoreUrl
    eval_private_object_store: ObjectStoreUrl | None = None
    log_redact_urls: bool = False
    role: Role | None = None
