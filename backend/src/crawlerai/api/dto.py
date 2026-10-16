"""Request and response models shared by the routers: the API's OpenAPI contract (SPEC-07 §4.1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from crawlerai.db.models import JobId
from crawlerai.llm.setup import LLMStatus
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.configs import ConfigSummary
from crawlerai.services.records import ExtractedRecord


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldErrorOut(Model):
    field: str  # dotted path in the request; "" for the whole document
    reason: str


class Problem(Model):
    """RFC 9457 problem details (SPEC-07 §4.3). `type` is one of the API's problem types, or `about:blank` when the
    HTTP status says all there is to say (RFC 9457 §4.2.1); `instance` is the request's path (§3.1.5)."""

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
    eval_ui: bool  # the labeling endpoints are mounted (SPEC-12 §4.3 reads it for its navigation)
    # The LLM setup check (`crawlerai.llm.setup`): `unavailable` when a listed provider has no key or refuses a
    # configured model; the log names the problem. The API serves either way: only LLM calls are affected.
    llm: LLMStatus


class SchemaList(Model):
    items: list[SchemaDef]  # by name, then version


class ReplayRequest(Model):
    # SPEC-07 §4.6: a replay calls an LLM only when asked. None does yet: role C is bound with SPEC-06 PR 4.
    allow_llm: bool = False


class ReplayResult(Model):
    records: list[ExtractedRecord]  # not stored (ARCHITECTURE §13.1)


class ConfigList(Model):
    items: list[ConfigSummary]  # by schema version, page kind, then version


class LearnStarted(Model):
    job_id: JobId
