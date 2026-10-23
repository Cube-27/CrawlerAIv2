"""The members of the requests that run page tasks (`scrape`, `batch_scrape`, `extract` and `crawl`) and their checks:
the formats a page is read for, how a request names its schema, its `render` member,
and the request as a job row stores it.
"""

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, field_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.content.chunks import ChunkOptions
from crawlerai.content.fit import FitOptions
from crawlerai.core.errors import Refusal
from crawlerai.db.models import PageKind, RenderMode, SchemaId
from crawlerai.llm.client import LLMClient
from crawlerai.llm.roles.s_labels import with_labels
from crawlerai.llm.roles.s_schema import MAX_FIELD_NAMES, draft_fields, normalize_prompt
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.registry import SchemaNotFound, get_by_id
from crawlerai.schemas.types import Name, SchemaDef
from crawlerai.services import schemas
from crawlerai.services.fetch_options import CAPTURE_FORMATS, FetchOptions
from crawlerai.services.schemas import NewSchema

PageFormat = Literal[
    "markdown", "markdown_fit", "chunks", "html", "raw_html", "links", "metadata", "screenshot", "pdf", "records"
]


class Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


# The description of the `min_confidence` member of the requests that extract `records`: a field whose calibrated bucket
# is below it is left unpublished, else every value publishes.
MIN_CONFIDENCE_DESCRIPTION: Final = (
    "Leave unpublished (abstained) a records field whose calibrated confidence is below this. "
    "Unset: every value publishes with its confidence."
)
# The description of the `render` member of the requests that extract `records`: HTTP by
# default; the caller asks the system to find where fields live (`locate`) or to render every page (`always`).
RENDER_DESCRIPTION: Final = (
    "How pages are rendered for fields. `off` (default): HTTP, the browser only when HTTP is refused; a field the HTTP "
    "page does not carry is `missing`. `locate`: find where the fields the HTTP pages leave missing (or `fields`) are "
    "shown, then fetch each page as they need. `always`: render every page."
)
MAX_RENDER_FIELDS: Final = 50


class RenderOptions(Input):
    """The `render` member: its mode, and the schema fields `locate` looks for (else the
    fields the HTTP extraction left missing). Pinned with the request."""

    mode: RenderMode = "off"
    fields: list[Name] = Field(default_factory=list, max_length=MAX_RENDER_FIELDS)


def _render_not_required(schema: dict[str, Any]) -> None:
    required = schema.get("required")
    if isinstance(required, list) and "render" in required:
        required.remove("render")


# A request with a `render` member: one the caller left out is left out of its dump too, so the job stored with it
# inherits its surface's render mode and reads it back absent; the schema never requires it. Each such request sets
# `model_config = RENDER_AS_GIVEN` and `_render_as_given = model_serializer(mode="wrap")(render_as_given)`.
RENDER_AS_GIVEN: Final = ConfigDict(json_schema_extra=_render_not_required)


# Unannotated: pydantic takes a serializer's return annotation as the model's serialization schema. `self`: pydantic
# takes a model serializer whose first parameter is so named as an instance method.
def render_as_given(self: BaseModel, handler: SerializerFunctionWrapHandler):  # type: ignore[no-untyped-def]
    dumped = handler(self)
    if "render" not in self.model_fields_set:
        dumped.pop("render", None)
    return dumped


def absolute_http_url(url: str) -> str:
    """`url`, for a request model's validator: `ValueError` unless it is an absolute http(s) URL."""
    if canonical_url(url, None) is None:
        raise ValueError("not an absolute http or https URL")
    return url


class SchemaById(Input):
    id: SchemaId


class SchemaInline(Input):
    inline: NewSchema


class SchemaPrompt(Input):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, prompt: str) -> str:
        # Role S reads the prompt whitespace-normalized, so one of only whitespace is empty.
        if not normalize_prompt(prompt):
            raise ValueError("the prompt is empty")
        return prompt


class SchemaFields(Input):
    """Field names, drafted into a schema with exactly those top-level fields by role S."""

    fields: list[Name] = Field(min_length=1, max_length=MAX_FIELD_NAMES)

    @field_validator("fields")
    @classmethod
    def _distinct(cls, fields: list[str]) -> list[str]:
        if len(set(fields)) != len(fields):
            raise ValueError("a field name is given twice")
        return fields


# How a request names its schema: by id, inline, as a prompt or as field names to draft from.
SchemaRequest = SchemaById | SchemaInline | SchemaPrompt | SchemaFields


def check_formats(
    formats: list[PageFormat], fetch: FetchOptions, fit: FitOptions | None, chunking: ChunkOptions | None
) -> None:
    """The options a request's formats take. Raises `ValueError`, for a request model's validator: a screenshot or PDF
    is made in the browser, so `method_hint` cannot be `http`; `fit` and `chunking` are the options of `markdown_fit`
    and `chunks`."""
    if CAPTURE_FORMATS.intersection(formats) and fetch.method_hint == "http":
        raise ValueError("screenshot and pdf are made in the browser, so method_hint cannot be http")
    if CAPTURE_FORMATS.intersection(formats) and fetch.headers:
        raise ValueError("headers are sent over HTTP only, so they cannot go with screenshot or pdf")
    if fit is not None and "markdown_fit" not in formats:
        raise ValueError("fit is the option of the markdown_fit format")
    if chunking is not None and "chunks" not in formats:
        raise ValueError("chunking is the option of the chunks format")


def check_records(formats: list[PageFormat], schema: SchemaRequest | None, page_kind: PageKind | None) -> None:
    """`records` needs a schema and a `page_kind`, and the schema's page kind must be that one. Raises
    `ValueError`, for a request model's validator."""
    if "records" not in formats:
        return
    if schema is None:
        raise ValueError("the records format needs a schema")
    if page_kind is None:
        raise ValueError("the records format needs a page_kind")
    if isinstance(schema, SchemaInline) and schema.inline.page_kind != page_kind:
        raise ValueError(f"the inline schema is for {schema.inline.page_kind} pages, not {page_kind}")


class SchemaUnusable(Refusal):
    """The request's `schema` is one `records` cannot use: no such id, a retired version, or another page kind."""


async def fields_schema(engine: AsyncEngine, llm: LLMClient, fields: list[Name], page_kind: PageKind) -> SchemaDef:
    """Role S's draft of `fields` for `page_kind` pages, checked usable for them. Raises the LLM
    client's `LLMFailure`, and `SchemaUnusable` for a retired draft."""
    drafted = await draft_fields(engine, llm, fields=fields, page_kind=page_kind)
    check_usable(drafted, page_kind)
    return drafted


async def named_schema(
    engine: AsyncEngine, schema: SchemaRequest | None, page_kind: PageKind | None, llm: LLMClient
) -> SchemaDef | None:
    """The schema a request names by id, stores (or matches) inline, or drafts from field names with `llm`, with its
    label synonyms when stored, else their draft started (`s_labels.with_labels`); None for a prompt, whose draft needs
    a page. Raises `SchemaUnusable`, the schemas service's `SchemaConflict` or `InvalidSchema` for an inline schema,
    and the LLM client's `LLMFailure` for field names it could not draft."""
    found = await _stated_schema(engine, schema, page_kind, llm)
    return None if found is None else with_labels(engine, llm, found)


async def _stated_schema(
    engine: AsyncEngine, schema: SchemaRequest | None, page_kind: PageKind | None, llm: LLMClient
) -> SchemaDef | None:
    match schema:
        case SchemaFields(fields=fields):
            if page_kind is None:
                raise SchemaUnusable("field names need a page_kind to draft a schema for")
            return await fields_schema(engine, llm, fields, page_kind)
        case SchemaById(id=schema_id):
            async with engine.connect() as conn:
                try:
                    found = await get_by_id(conn, schema_id)
                except SchemaNotFound as e:
                    raise SchemaUnusable(str(e)) from e
            check_usable(found, page_kind)
            return found
        case SchemaInline(inline=inline):
            async with engine.begin() as conn:
                return await schemas.inline(conn, inline)
    return None


def stored_request(request: BaseModel, context: dict[str, object] | None = None) -> dict[str, Any]:
    """`request` as a job row stores it (a `render` the caller left out stays out: `render_as_given`)."""
    stored: dict[str, Any] = request.model_dump(mode="json", by_alias=True, context=context)
    return stored


def check_render(render: RenderOptions, schema: SchemaDef | None) -> None:
    """`SchemaUnusable` when `render.fields` names a field the request's schema does not have: no locate run fills it.
    Without a resolved schema (a prompt, drafted on the page), none is checked."""
    if schema is None:
        return
    unknown = [name for name in render.fields if name not in schema.fields]
    if unknown:
        raise SchemaUnusable(f"render.fields names fields schema {schema.name} lacks: {', '.join(unknown)}")


def check_usable(schema: SchemaDef, page_kind: PageKind | None) -> None:
    if schema.status == "retired":
        raise SchemaUnusable(f"schema {schema.name} is retired")
    if schema.page_kind != page_kind:
        raise SchemaUnusable(f"schema {schema.name} is for {schema.page_kind} pages, not {page_kind}")
