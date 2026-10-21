"""The two executors agree (learning-configs spec, INV-20): on generated pages and IRs, every field value the engine
executor proposes as valid is the value the release executor gives, and the release executor gives none where the engine
has no valid value. Their code is independent (`.importlinter`), so agreement is the evidence the release check uses."""

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crawlerai.collect.base import PAGE
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor, row_id
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.release_executor import ReleasePage, release_run
from crawlerai.config_ir.release_rules import release_rules
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"

TEXT = FieldSpec(type=FieldType.TEXT, description="d")
URL = FieldSpec(type=FieldType.URL, description="d")
TEXTS = FieldSpec(type=FieldType.LIST, description="d", item=FieldSpec(type=FieldType.TEXT))
DETAIL_FIELDS = {"title": TEXT, "link": URL, "tags": TEXTS}
LISTING_FIELDS = {"title": TEXT, "link": URL, "next_page_url": URL}

_value = st.from_regex(r"[A-Za-z0-9&<]([A-Za-z0-9&< ]{0,10}[A-Za-z0-9&<])?", fullmatch=True)
_padded = st.builds(lambda pad, v: f"{pad}{v}{pad}", st.sampled_from(["", " ", "\n "]), _value)
_href = st.sampled_from(["/p/2", "https://shop.example.test/q", "", "rel?x=1"])

# Steps over every selector kind and post op, for the page `_detail_page` builds.
_DETAIL_STEPS = [
    {"xpath": "normalize-space(//span[@class='v'])"},
    {"css": "span.v", "post": [{"trim": {}}]},
    {"xpath": "//span[@class='v']", "post": [{"text": {}}, {"regex_replace": {"pattern": "([a-z]+)", "repl": "\\1-"}}]},
    {"xpath": "//a/@href", "post": [{"absolutize_url": {}}]},
    {"regex": 'data-x="([^"]*)"'},
    {"jsonld": "$['name']", "when_type": "Product"},
    {"jsonld": "$['offers'][*]['sku']", "when_type": "Product"},
    {"jsonpath": "$['p']['name']", "source": "js_state"},
    {"jsonpath": "$['items'][*]", "source": "xhr"},
    {"jsonpath": "$['r']", "source": "api"},
]
_ROW_STEPS = [
    {"xpath": "em"},
    {"xpath": "normalize-space(em)"},
    {"attr": "data-k"},
    {"xpath": "a/@href", "post": [{"absolutize_url": {}}]},
    {"regex": "[a-z]+"},
]
_steps = st.lists(st.sampled_from(_DETAIL_STEPS), min_size=1, max_size=3)
_row_steps = st.lists(st.sampled_from(_ROW_STEPS), min_size=1, max_size=3)


def _schema(page_kind: str, fields: dict[str, FieldSpec]) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic"}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields})


def _ir(page_kind: str, fields: dict[str, Any], listing: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": page_kind,
            "fetch": {"method": "http"},
            "fields": {name: {"steps": steps, "status": "uncorroborated"} for name, steps in fields.items()},
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


def _engine_values(
    executor: EngineExecutor, page: ParsedPage, schema: SchemaDef, ctx: Context
) -> dict[tuple[str, str], Any]:
    """The engine's valid values by owner and field."""
    result = executor.execute(page, schema, ctx)
    return {(c.entity_id, c.field): c.raw for c in result.candidates if isinstance(c.normalized, Ok)}


def _context(base: bool) -> Context:
    url = PAGE_URL if base else None
    return Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=url, page_url=url)


# Each example parses the page and runs both executors; its time depends on the machine, not on the property.
_RUNS_BOTH_EXECUTORS = settings(deadline=None)


@st.composite
def _detail_page(draw: st.DrawFn) -> tuple[str, tuple[bytes, ...]]:
    spans = "".join(f"<span class='v'>{escape(v)}</span>" for v in draw(st.lists(_padded, max_size=3)))
    links = "".join(f"<a href='{escape(h)}'>l</a>" for h in draw(st.lists(_href, max_size=2)))
    nodes = [
        {"@type": t, "name": n, "offers": [{"@type": "Offer", "sku": s} for s in skus]}
        for t, n, skus in draw(
            st.lists(st.tuples(st.sampled_from(["Product", "Offer"]), _value, st.lists(_value, max_size=2)), max_size=2)
        )
    ]
    jsonld = json.dumps({"@context": "https://schema.org", "@graph": nodes})
    state = json.dumps({"p": {"name": draw(_value)}}) if draw(st.booleans()) else "1"
    attr = escape(draw(_value), quote=True)
    html = (
        f"<html><head><script type='application/ld+json'>{jsonld}</script>"
        f"<script>window.__S = {state};</script></head>"
        f'<body><div data-x="{attr}">{spans}{links}</div></body></html>'
    )
    network = tuple(json.dumps({"items": items}).encode() for items in draw(st.lists(st.lists(_value), max_size=2)))
    return html, network


@_RUNS_BOTH_EXECUTORS
@given(
    _detail_page(),
    st.fixed_dictionaries({}, optional={"title": _steps, "link": _steps, "tags": _steps}),
    st.booleans(),
)
def test_the_executors_agree_on_page_fields(
    page: tuple[str, tuple[bytes, ...]], fields: dict[str, Any], base: bool
) -> None:
    html, network = page
    ir, schema, ctx = _ir("detail", fields), _schema("detail", DETAIL_FIELDS), _context(base)
    engine = _engine_values(EngineExecutor(ir, VOCABULARY), ParsedPage(html, network), schema, ctx)
    released = release_run(ir, ReleasePage(html, network, ctx.base_url), release_rules(schema, ctx))
    assert released.fields == {name: value for (owner, name), value in engine.items() if owner == PAGE}


@st.composite
def _listing_page(draw: st.DrawFn) -> str:
    rows = draw(st.lists(st.tuples(st.lists(_padded, max_size=2), st.none() | _value, st.none() | _href), max_size=4))
    items = "".join(
        "<li"
        + ("" if key is None else f" data-k='{escape(key, quote=True)}'")
        + ">"
        + "".join(f"<em>{escape(v)}</em>" for v in ems)
        + ("" if href is None else f"<a href='{escape(href)}'>r</a>")
        + "</li>"
        for ems, key, href in rows
    )
    next_link = "".join(f"<a rel='next' href='{escape(h)}'>n</a>" for h in draw(st.lists(_href, max_size=2)))
    return f"<html><body><em>outside</em><ul>{items}</ul>{next_link}</body></html>"


@_RUNS_BOTH_EXECUTORS
@given(
    _listing_page(),
    st.fixed_dictionaries({}, optional={"title": _row_steps, "link": _row_steps}),
    st.booleans(),
)
def test_the_executors_agree_on_listing_rows_and_the_next_page(page: str, fields: dict[str, Any], base: bool) -> None:
    listing = {
        "row": {"css": "ul > li"},
        "fields": {name: {"steps": steps, "status": "uncorroborated"} for name, steps in fields.items()},
        "next": {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
    }
    ir, schema, ctx = _ir("listing", {}, listing), _schema("listing", LISTING_FIELDS), _context(base)
    engine = _engine_values(EngineExecutor(ir, VOCABULARY), ParsedPage(page), schema, ctx)
    released = release_run(ir, ReleasePage(page, (), ctx.base_url), release_rules(schema, ctx))
    rows = [
        {name: value for (owner, name), value in engine.items() if owner == row_id(n)}
        for n in range(len(released.rows))
    ]
    assert list(released.rows) == rows
    assert released.fields == {name: value for (owner, name), value in engine.items() if owner == PAGE}
    assert len(released.rows) == page.count("<li")
