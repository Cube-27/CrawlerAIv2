"""JSON-LD collector properties (SPEC-05 §4.5, INV-22): any JSON in a block is collected without raising, every
entity names a JSON object of its block, and each candidate's locator reads its raw value back."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.locator import parse_locator
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://shop.example.test/p/1")
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
        "brand": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name"),
    },
)

# Keys and strings drawn mostly from the JSON-LD and schema.org terms the collector reads, so that generated
# documents hold entities, references and contexts, plus arbitrary text.
TERMS = st.sampled_from(
    ["@context", "@type", "@id", "@graph", "@value", "@vocab", "name", "brand", "url", "offers", "Product", "Thing"]
)
IRIS = st.sampled_from(["https://schema.org", "http://schema.org/", "#a", "#b", "_:b0", "http://[x"])
SCALARS = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=8), TERMS, IRIS)


def _nodes(inner: st.SearchStrategy[JsonValue]) -> st.SearchStrategy[JsonValue]:
    """schema.org-like nodes: a type, maybe a context and an `@id`, and properties holding anything."""
    optional = {key: st.one_of(st.text(max_size=4), inner) for key in ("name", "brand", "url", "offers", "@graph")}
    return st.fixed_dictionaries(
        {
            "@type": st.one_of(
                st.sampled_from(["Product", "Thing", "Brand", "Offer", "Widget", "http://schema.org/Product"]), inner
            )
        },
        optional={"@context": st.one_of(IRIS, inner), "@id": IRIS, "@value": inner, **optional},
    )


JSON: st.SearchStrategy[JsonValue] = st.recursive(
    SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.dictionaries(st.one_of(TERMS, st.text(max_size=4)), inner, max_size=5),
        _nodes(inner),
        st.fixed_dictionaries({"@id": IRIS}),
    ),
    max_leaves=40,
)
# A block, most often in schema.org's context, as pages write them.
BLOCKS = st.one_of(JSON, JSON.map(lambda graph: {"@context": "https://schema.org", "@graph": graph}))

# RFC 9535 §2.7: the escapes in a normalized path's member names.
ESCAPE = re.compile(r"\\(u[0-9a-f]{4}|.)")
SINGLE = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "'": "'", "\\": "\\"}
SEGMENT = re.compile(r"\['((?:[^'\\]|\\.)*)'\]|\[(\d+)\]")


def _unescaped(match: re.Match[str]) -> str:
    escape = match[1]
    return chr(int(escape[1:], 16)) if escape.startswith("u") else SINGLE[escape]


def _read(document: JsonValue, path: str) -> JsonValue:
    """The value at a normalized path made of `['name']` and `[index]` segments."""
    value = document
    for name, index in SEGMENT.findall(path.removeprefix("$")):
        if index:
            assert isinstance(value, list)
            value = value[int(index)]
        else:
            assert isinstance(value, dict)
            value = value[ESCAPE.sub(_unescaped, name)]
    return value


def _script(document: JsonValue) -> str:
    # HTML Standard, script content restrictions: `</` would end the element; JSON may escape `/` as `\/`.
    return '<script type="application/ld+json">' + json.dumps(document).replace("</", "<\\/") + "</script>"


@given(st.lists(BLOCKS, min_size=1, max_size=3))
def test_locators_read_back_the_raw_values(generated: list[JsonValue]) -> None:
    # A known Product first, so a collector that finds nothing fails.
    known: JsonValue = {"@context": "https://schema.org", "@type": "Product", "name": "Known title"}
    documents = [known, *generated]
    page = ParsedPage("<html><head>" + "".join(map(_script, documents)) + "</head></html>")
    result = JsonLdCollector(VOCABULARY).collect(page, SCHEMA, CTX)
    assert ("title", "Known title", "jsonld:0:$['name']") in [(c.field, c.raw, c.locator) for c in result.candidates]
    for entity in result.entities:
        _, block, path = entity.id.split(":", 2)
        assert isinstance(_read(documents[int(block)], path), dict)
    for candidate in result.candidates:
        block, path = parse_locator(candidate.locator).parts
        value = _read(documents[int(block)], path)
        assert value == candidate.raw or (isinstance(value, dict) and value.get("@value") == candidate.raw)


# A paragraph with text: an empty one renders no line (HTML Standard rendering: an empty block box has no line box).
_WORDS = st.text(st.characters(categories=("L", "N", "P", "Zs"), exclude_characters="<>&"), max_size=40).filter(
    str.strip
)
_DESCRIBED = SCHEMA.model_copy(
    update={"fields": {"description": FieldSpec(type=FieldType.LONG_TEXT, description="d", schema_org="Product.name")}}
)


@given(st.lists(_WORDS, min_size=1, max_size=4))
def test_paragraph_markup_reads_as_the_lines_of_its_text(paragraphs: list[str]) -> None:
    # HTML Standard rendering: each `p` is a block box, so a fragment of paragraphs reads as their texts, one a line.
    plain = "\n".join(paragraphs)
    markup = "".join(f"<p>{p}</p>" for p in paragraphs)

    read = [_described(raw) for raw in (plain, markup)]

    assert read[0] == read[1]


def _described(raw: str) -> object:
    block = json.dumps({"@context": "https://schema.org", "@type": "Product", "name": raw})
    page = ParsedPage(f'<script type="application/ld+json">{block}</script>')
    return [c.normalized for c in JsonLdCollector(VOCABULARY).collect(page, _DESCRIBED, CTX).candidates]
