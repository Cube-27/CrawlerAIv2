"""Process settings, read from `CRAWLERAI_*` environment variables (SPEC-00 §4.4).

The variable names are the contract; later specs add settings here. The two `EVAL_PRIVATE_*` settings are set only
in the custodian's environment (C1) and are empty everywhere else.
An empty value counts as unset, so unset CI secrets (which arrive as "") behave like absent variables.
"""

from typing import Annotated, Literal

from curl_cffi.requests import BrowserTypeLiteral
from pydantic import BeforeValidator, Field, IPvAnyNetwork, PositiveFloat, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from crawlerai.core.proxy import ProxyPool

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


def _comma_separated(value: object) -> object:
    """`a,b` as `("a", "b")`; duplicates are refused (for providers, the order is the failover order)."""
    if not isinstance(value, str):
        return value
    names = tuple(name.strip() for name in value.split(","))
    if len(set(names)) != len(names):
        raise ValueError("a name is listed twice")
    return names


class AcquireSettings(_Base):
    """The subset a fetch needs, so `crawlerai fetch` runs without a database or object store."""

    impersonate: BrowserTypeLiteral = IMPERSONATE_DEFAULT
    # `CRAWLERAI_PROXY_POOLS`, JSON `{pool_name: proxy_url | {"endpoints": [proxy_url, ...], "mode": ...}}` (SPEC-02
    # §3, OPEN_QUESTIONS #10, D-1323).
    proxy_pools: dict[str, ProxyPool] = Field(default_factory=dict)
    # `CRAWLERAI_DISABLED_ADAPTERS`, comma-separated: the platform adapters that do not run (SPEC-15 §4.8). Every
    # registered adapter runs unless named here (owner, 2026-10-16).
    disabled_adapters: Annotated[tuple[str, ...], NoDecode, BeforeValidator(_comma_separated)] = ()


class ApiSettings(_Base):
    """What the app factory reads: which routers to mount, and how to admit requests (SPEC-07 §4.2)."""

    # Mounts the labeling endpoints (SPEC-03 §4.10). They serve the dev split only (C1).
    eval_ui: bool = False
    # JSON list of the proxies whose `Forwarded`/`X-Forwarded-For` name the client (RFC 7239 §8.1, INV-32).
    trusted_proxies: tuple[IPvAnyNetwork, ...] = ()
    # The per-key token bucket in front of authentication (D-0027).
    api_rate_per_s: PositiveFloat = 20
    api_rate_burst: PositiveInt = 40


class McpSettings(_Base):
    """What the MCP server's stdio process reads besides `Settings` (SPEC-10 §4.7): the API key it acts with."""

    api_key: SecretStr


LLMProviderName = Literal["anthropic", "gemini"]


class LLMSettings(_Base):
    """The LLM providers (SPEC-06 §4.2, OPEN_QUESTIONS #5): which, in failover order, and a model per model class.

    The model ids are the current Haiku- and Flash-Lite-class models for `fast` (role C) and Sonnet- and Flash-class
    models for `strong` (A, D, S) (ARCHITECTURE Appendix C); change them here, not in code.
    """

    llm_providers: Annotated[tuple[LLMProviderName, ...], NoDecode, BeforeValidator(_comma_separated)] = (
        "anthropic",
        "gemini",
    )
    llm_fast_model_anthropic: str = "claude-haiku-5-5"
    llm_strong_model_anthropic: str = "claude-sonnet-5-5"
    llm_fast_model_gemini: str = "gemini-3.5-flash-lite"
    llm_strong_model_gemini: str = "gemini-3.8-flash"
    # SPEC-08 §4.6: role A reads each sample page's reduced HTML cut to this many characters.
    llm_a_max_chars: int = Field(default=120_000, gt=0)
    # From the secret store (ARCHITECTURE §18); required for each listed provider when a client is built.
    llm_api_key_anthropic: SecretStr | None = None
    llm_api_key_gemini: SecretStr | None = None


class Settings(DatabaseSettings, AcquireSettings, ApiSettings, LLMSettings):
    eval_private_database_url: SecretStr | None = None
    object_store: ObjectStoreUrl
    eval_private_object_store: ObjectStoreUrl | None = None
    log_redact_urls: bool = False
    role: Role | None = None
