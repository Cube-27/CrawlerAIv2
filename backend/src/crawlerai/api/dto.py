"""Request and response models shared by the routers: the API's OpenAPI contract (SPEC-07 §4.1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from crawlerai.schemas.types import SchemaDef


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


class SchemaList(Model):
    items: list[SchemaDef]  # by name, then version
