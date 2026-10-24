"""Request and response models shared by the routers: the API's OpenAPI contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from snowcrawl.db.models import JobId
from snowcrawl.llm.setup import LLMStatus
from snowcrawl.schemas.types import SchemaDef
from snowcrawl.services.configs import ConfigSummary
from snowcrawl.services.records import ExtractedRecord


class Model(BaseModel):
    # The API sends every member, defaulted ones too, so its document marks them all `required` (OpenAPI 3.1).
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class FieldErrorOut(Model):
    field: str  # dotted path in the request; "" for the whole document
    reason: str


class Problem(Model):
    """RFC 9457 problem details. `type` is one of the API's problem types, or `about:blank` when the
    HTTP status says all there is to say (RFC 9457 §4.2.1); `instance` is the request's path."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    errors: list[FieldErrorOut] = []


# Declares a problem body under its media type, so the generated client types the error responses.
PROBLEM_RESPONSE: dict[str, object] = {
    "model": Problem,
    "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}},
}


class Health(Model):
    status: Literal["ok"] = "ok"
    # The LLM setup check (`snowcrawl.llm.setup`): `unavailable` when a listed provider has no key or refuses a
    # configured model; the log names the problem. The API serves either way: only LLM calls are affected.
    llm: LLMStatus


class SchemaList(Model):
    items: list[SchemaDef]  # by name


class ReplayRequest(Model):
    # A replay calls an LLM only when asked. None does yet: role C is bound by the LLM layer.
    allow_llm: bool = False


class ReplayResult(Model):
    records: list[ExtractedRecord]  # not stored


class ConfigList(Model):
    items: list[ConfigSummary]  # by schema, page kind, then version


class LearnStarted(Model):
    job_id: JobId
