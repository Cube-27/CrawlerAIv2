"""Process settings, read from `CRAWLERAI_*` environment variables (SPEC-00 §4.4).

The variable names are the contract; later specs add settings here. The two `EVAL_PRIVATE_*` settings are set only
in the custodian's environment (C1) and stay unset everywhere else.
"""

from typing import Annotated, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# `fs:///<absolute path>` or `s3://<bucket>[/<prefix>]` (SPEC-00 §4.4).
ObjectStoreUrl = Annotated[str, Field(pattern=r"^(fs:///.+|s3://[^/]+(/.*)?)$")]

Role = Literal["api", "worker", "scheduler"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRAWLERAI_", frozen=True)

    database_url: SecretStr
    eval_private_database_url: SecretStr | None = None
    object_store: ObjectStoreUrl
    eval_private_object_store: ObjectStoreUrl | None = None
    log_redact_urls: bool = False
    role: Role | None = None
