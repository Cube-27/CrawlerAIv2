"""Role S's label synonyms (extraction spec, "Label vocabulary"; llm spec, "Role S label synonyms"): the labels pages
write next to each field's value, drafted once per schema and stored with it (`SchemaDef.labels`), never per page.

The request is the schema's labelled fields (`collect.labels.labelled`), each with its type, schema.org path and the
caller's description; the reply is the labels per field, in any language. The reply check refuses a field the
schema does not have, or one given twice; labels that are empty or too long, repeat another's words, or pass the
per-field bound are dropped. The stored labels are the caller's to edit (`PUT /v1/schemas/{id}/labels`), and an edit
of the schema's document clears them, so the next use drafts them again.

No job exists when a schema is first used, so the call is charged to none, as a field-names draft (`KeyCapped`
counts it against the caller's key). Without a model (no provider, a failure, the key's cap) the schema is used as
it is: the vocabulary is then the schema's own words, and the next use asks again.
"""

import logging
from functools import cache, partial
from importlib.resources import files
from typing import Final

from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.collect.labels import labelled, properties, words
from crawlerai.llm.client import LLMClient, LLMFailure, LLMRequest, closed_object
from crawlerai.schemas import registry
from crawlerai.schemas.types import MAX_LABELS, FieldLabels, FieldSpec, Label, SchemaDef

log = logging.getLogger(__name__)

SYSTEM: Final = files("crawlerai.llm").joinpath("prompts/s_labels.txt").read_text(encoding="utf-8")
MAX_OUTPUT_TOKENS: Final = 8_192
# `schemas.types.Label`: the longest label kept, in characters.
_MAX_LABEL_CHARS: Final = 80


@cache
def output_schema() -> dict[str, JsonValue]:
    """One entry per field: its name and its labels."""
    labels: JsonValue = {"type": "array", "items": {"type": "string"}}
    entry = closed_object({"name": {"type": "string"}, "labels": labels})
    return closed_object({"fields": {"type": "array", "items": entry}})


def labels_request(schema: SchemaDef) -> LLMRequest:
    """The request for `schema`'s labelled fields, in the schema's order; no job pays for it (module doc)."""
    lines = "\n".join(_line(name, spec) for name, spec in _labelled_fields(schema).items())
    user = f'<schema page_kind="{schema.page_kind}">\n{lines}\n</schema>'
    return LLMRequest(
        prompt_kind="s_labels",
        model_class="strong",
        system=SYSTEM,
        user=user,
        output_schema=output_schema(),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        job_id=None,
    )


async def with_labels(engine: AsyncEngine, client: LLMClient, schema: SchemaDef) -> SchemaDef:
    """`schema` with its label synonyms: as stored when drafted (or edited) before, else drafted now and stored. Without
    a model's reply, `schema` as it is (module doc)."""
    names = frozenset(_labelled_fields(schema))
    if schema.labels is not None or not names:
        return schema
    try:
        response = await client.complete_json(labels_request(schema), check=partial(_invalid, names=names))
    except LLMFailure as error:
        log.info("label synonyms of schema %s not drafted: %s", schema.name, type(error).__name__)
        return schema
    async with engine.begin() as conn:
        stored = await registry.store_labels(conn, schema, _labels(response.data, schema), drafted=True)
    # Another request drafted them meanwhile, or the schema was edited: `schema` stays as the caller validated it.
    return schema if stored is None else schema.model_copy(update={"labels": stored.labels})


def _labelled_fields(schema: SchemaDef) -> dict[str, FieldSpec]:
    return {name: spec for name, spec in schema.fields.items() if labelled(spec)}


def _line(name: str, spec: FieldSpec) -> str:
    of = f" of {spec.item.type.value}" if spec.item is not None else ""
    parts = [f"- {name}: {spec.type.value}{of}"]
    if spec.scheme is not None:
        parts.append(f"scheme {spec.scheme}")
    if spec.schema_org is not None:
        parts.append(f"schema.org {spec.schema_org}")
    if spec.description is not None:
        parts.append(f"description: {spec.description}")
    return "; ".join(parts)


class _Entry(BaseModel):
    name: str
    labels: list[str]


class _Reply(BaseModel):
    """The reply, which the client checked against `output_schema`."""

    fields: list[_Entry]


def _invalid(data: dict[str, JsonValue], names: frozenset[str]) -> str | None:
    """The client's reply check: a field the request did not name, one it named and the reply lacks, or one named
    twice."""
    given = [entry.name for entry in _Reply.model_validate(data).fields]
    if unknown := sorted(set(given) - names):
        return f"fields not in the schema: {', '.join(unknown)}"
    if missing := sorted(names - set(given)):
        return f"fields missing: {', '.join(missing)}"
    if len(given) != len(set(given)):
        return "a field is given more than once"
    return None


def _labels(data: dict[str, JsonValue], schema: SchemaDef) -> FieldLabels:
    """Each field's labels: short, each with words no other label of the field (nor its own words) has, at most
    `MAX_LABELS`."""
    found: FieldLabels = {}
    for entry in _Reply.model_validate(data).fields:
        spec = schema.fields[entry.name]
        seen = {words(text) for text in (entry.name, *properties(spec), spec.description or "")}
        kept: list[Label] = []
        for text in (" ".join(label.split()) for label in entry.labels):
            form = words(text)
            if form and form not in seen and len(text) <= _MAX_LABEL_CHARS and len(kept) < MAX_LABELS:
                seen.add(form)
                kept.append(text)
        found[entry.name] = kept
    return found
