"""Role S's label synonyms (extraction spec, "Label vocabulary"; llm spec, "Role S label synonyms"): the labels pages
write next to each field's value, drafted once per schema and stored with it (`SchemaDef.labels`), never per page.

A request names some of the schema's labelled fields (`collect.labels.labelled`), each with its type, schema.org path
and the caller's description; the reply is the labels per field, in any language. The reply check refuses a field the
request did not name, one it lacks, or one given twice; labels that are empty or too long, repeat another's words, or
pass the per-field bound are dropped. The stored labels are the caller's to edit (`PUT /v1/schemas/{id}/labels`), and
an edit of the schema's document clears them, so the next use drafts them again.

Drafting is off the request path: a request uses the labels stored with its schema, and when there are none it starts
the draft in the background and goes on with the schema as it is (its own words are the vocabulary), so no request
waits on the model; one draft per schema runs at a time in a process, and of drafts in two processes the first stored
stays. The labelled fields are asked for in chunks of `CHUNK_FIELDS`, concurrently, so each reply (the model's thinking
included) stays well under its output cap however many fields the schema has; the labels are stored only when every
chunk answered.

No job exists when a schema is first used, so the calls are charged to none, as a field-names draft (`KeyCapped`
counts them against the caller's key). Without a model (no provider, a failure of any kind, the key's cap) nothing is
stored, and the next use asks again.
"""

import asyncio
import logging
from functools import cache, partial
from importlib.resources import files
from typing import Final

from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.collect.labels import labelled, properties, words
from crawlerai.db.models import SchemaId
from crawlerai.llm.client import LLMClient, LLMRequest, closed_object
from crawlerai.schemas import registry
from crawlerai.schemas.types import MAX_LABELS, FieldLabels, FieldSpec, Label, SchemaDef

log = logging.getLogger(__name__)

SYSTEM: Final = files("crawlerai.llm").joinpath("prompts/s_labels.txt").read_text(encoding="utf-8")
MAX_OUTPUT_TOKENS: Final = 8_192
# The most labelled fields one call asks for: at 32 labels a field, a reply of this many fits its cap with room for the
# model's thinking, which counts against it.
CHUNK_FIELDS: Final = 4
# `schemas.types.Label`: the longest label kept, in characters.
_MAX_LABEL_CHARS: Final = 80


@cache
def output_schema() -> dict[str, JsonValue]:
    """One entry per field: its name and its labels."""
    labels: JsonValue = {"type": "array", "items": {"type": "string"}}
    entry = closed_object({"name": {"type": "string"}, "labels": labels})
    return closed_object({"fields": {"type": "array", "items": entry}})


def labels_request(schema: SchemaDef, names: list[str]) -> LLMRequest:
    """The request for the labelled fields `names` of `schema`, in the schema's order; no job pays for it (module
    doc)."""
    lines = "\n".join(_line(name, schema.fields[name]) for name in names)
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


# The drafts running in this process, by schema; the reference also keeps each task alive until it ends.
_DRAFTING: dict[SchemaId, "asyncio.Task[SchemaDef | None]"] = {}


def with_labels(engine: AsyncEngine, client: LLMClient, schema: SchemaDef) -> SchemaDef:
    """`schema` as it is: with its stored labels when drafted (or edited) before; else its draft starts in the
    background, unless one runs already, and a later use finds the labels stored (module doc)."""
    if schema.labels is None and _labelled_fields(schema) and schema.id not in _DRAFTING:
        task = asyncio.get_running_loop().create_task(draft_labels(engine, client, schema))
        _DRAFTING[schema.id] = task
        task.add_done_callback(lambda _: _DRAFTING.pop(schema.id, None))
    return schema


async def draft_labels(engine: AsyncEngine, client: LLMClient, schema: SchemaDef) -> SchemaDef | None:
    """Draft `schema`'s label synonyms and store them; the stored schema, or None when nothing was stored: a failure of
    any kind (logged), or another draft or an edit of the schema came first."""
    names = list(_labelled_fields(schema))
    chunks = [names[i : i + CHUNK_FIELDS] for i in range(0, len(names), CHUNK_FIELDS)]
    try:
        async with asyncio.TaskGroup() as group:
            replies = [group.create_task(_draft_chunk(client, schema, chunk)) for chunk in chunks]
        labels = {name: kept for reply in replies for name, kept in reply.result().items()}
        async with engine.begin() as conn:
            return await registry.store_labels(conn, schema, labels, drafted=True)
    except Exception as error:  # a draft never fails a request, whatever went wrong (module doc)
        log.warning("label synonyms of schema %s not drafted: %r", schema.name, error)
        return None


async def _draft_chunk(client: LLMClient, schema: SchemaDef, names: list[str]) -> FieldLabels:
    check = partial(_invalid, names=frozenset(names))
    response = await client.complete_json(labels_request(schema, names), check=check)
    return _labels(response.data, schema)


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
