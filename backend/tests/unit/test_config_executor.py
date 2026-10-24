"""The engine executor: an IR's steps run in order over the `ParsedPage`, the first valid value
is the field's `config` candidate, multi-matches are invalid, and listings give one entity per row."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from snowcrawl.collect.base import Candidate, Entity
from snowcrawl.collect.config import Executed
from snowcrawl.collect.jsonld import JsonLdCollector
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.config_ir.executor import EngineExecutor
from snowcrawl.config_ir.model import ExtractionConfigIR
from snowcrawl.content.page import ParsedPage
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import SchemaId
from snowcrawl.normalize.base import Context, Ok
from snowcrawl.resolve.evidence import assess_fields
from snowcrawl.resolve.ownership import EntityGraph
from snowcrawl.resolve.preference import PRECEDENCE_TYPES, PageFacts, Resolver
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
TEXT = FieldSpec(type=FieldType.TEXT, description="d")
URL = FieldSpec(type=FieldType.URL, description="d")
MONEY = FieldSpec(type=FieldType.MONEY, description="d")


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": fields,
        }
    )


def _ir(
    fields: dict[str, Any],
    *,
    page_kind: str = "detail",
    listing: dict[str, Any] | None = None,
    fetch: str = "http",
) -> EngineExecutor:
    document = {
        "ir_version": "1",
        "site": "shop.example.test",
        "schema": {"name": "synthetic", "digest": "0" * 64},
        "page_kind": page_kind,
        "fetch": {"method": fetch},
        "fields": {
            name: {"steps": steps, "status": "uncorroborated"} if isinstance(steps, list) else steps
            for name, steps in fields.items()
        },
        "listing": listing,
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
    }
    return EngineExecutor(ExtractionConfigIR.model_validate(document), VOCABULARY)


def _run(executor: EngineExecutor, html: str, schema: SchemaDef, ctx: Context = CTX, **page: Any) -> Executed:
    return executor.execute(ParsedPage(html, **page), schema, ctx)


def _only(result: Executed) -> Candidate:
    (candidate,) = result.candidates
    return candidate


def _config(field: str, raw: Any, normalized: Any, locator: str, entity_id: str = "page") -> Candidate:
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind="config",
        raw=raw,
        normalized=normalized,
        locator=locator,
        independent=False,
    )


def test_the_browser_fields_are_the_running_fields_whose_source_is_the_render() -> None:
    def steps(needs: str, status: str = "uncorroborated") -> dict[str, Any]:
        return {"steps": [{"xpath": "//h1"}], "status": status, "needs": needs}

    executor = _ir({"title": steps("browser"), "brand": steps("http"), "sku": steps("browser", "suspended")})
    assert executor.browser_fields == {"title"}
    # The config's fetch method says nothing of a field's source.
    assert _ir({"title": [{"xpath": "//h1"}]}, fetch="browser").browser_fields == frozenset()


def test_an_xpath_step_proposes_the_node_string_value_owned_by_the_page() -> None:
    executor = _ir({"title": [{"xpath": "//h1"}]})
    result = _run(executor, "<h1>Blue <b>mug</b></h1>", _schema(title=TEXT))
    assert result == Executed(
        rows=(), candidates=(_config("title", "Blue mug", Ok("Blue mug"), "config:title:0://h1"),)
    )
    # No match gives no candidate.
    assert _run(executor, "<p>x</p>", _schema(title=TEXT)) == Executed(rows=(), candidates=())


def _ld(*blocks: Any) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)


def test_jsonpath_reads_the_documents_of_its_source() -> None:
    html = (
        _ld({"name": "from-ld"})
        + '<script type="application/json">{"p": {"name": "from-state"}}</script>'
        + '<script>window.s = {"q": "from-assignment"};</script>'
    )
    network = (b'{"r": "from-xhr"}', b"not json")
    schema = _schema(title=TEXT)

    def value(path: str, source: str) -> Any:
        return _only(_run(_ir({"title": [{"jsonpath": path, "source": source}]}), html, schema, network=network)).raw

    assert value("$['name']", "jsonld") == "from-ld"
    assert value("$['p']['name']", "js_state") == "from-state"
    assert value("$['q']", "js_state") == "from-assignment"
    assert value("$['r']", "xhr") == "from-xhr"


LISTING_HTML = """
<ul>
  <li class="r"><a href="/a">A</a><span>1.00 EUR</span></li>
  <li class="r"><a href="/b">B</a></li>
</ul>
<a rel="next" href="?page=2">next</a>
"""


def _listing_schema() -> SchemaDef:
    return _schema(
        page_kind="listing",
        title=TEXT,
        url=URL,
        price=MONEY,
        next_page_url=FieldSpec(type=FieldType.URL, description="d", scope="page"),
    )


def test_a_listing_gives_one_row_entity_per_row_with_fields_relative_to_it() -> None:
    listing = {
        "row": {"css": "li.r"},
        "fields": {
            "title": {"steps": [{"xpath": "a"}], "status": "uncorroborated"},
            "url": {"steps": [{"xpath": "a/@href", "post": [{"absolutize_url": {}}]}], "status": "uncorroborated"},
            "price": {"steps": [{"xpath": "span"}], "status": "uncorroborated"},
        },
        "next": {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
    }
    result = _run(_ir({}, page_kind="listing", listing=listing), LISTING_HTML, _listing_schema())
    assert result.rows == (
        Entity(id="config:row:0", types=("ListItem",), urls=(), parent=None),
        Entity(id="config:row:1", types=("ListItem",), urls=(), parent=None),
    )
    assert [(c.entity_id, c.field, c.raw) for c in result.candidates] == [
        ("config:row:0", "title", "A"),
        ("config:row:0", "url", "https://shop.example.test/a"),
        ("config:row:0", "price", "1.00 EUR"),
        ("config:row:1", "title", "B"),
        ("config:row:1", "url", "https://shop.example.test/b"),
        ("page", "next_page_url", "https://shop.example.test/p/1?page=2"),
    ]


def test_config_candidates_enter_resolution_with_their_field_status_bucket() -> None:
    """§8.4: config candidates resolve like any other; a corroborated field's value is `config_corroborated`, an
    uncorroborated one's `config_uncorroborated`."""
    html = (
        _ld({"@context": "https://schema.org", "@type": "Product", "name": "Mug"}) + "<h1>Blue mug</h1><p>12.50 EUR</p>"
    )
    page, schema = ParsedPage(html), _schema("detail", title=TEXT, price=MONEY)
    fields = {"title": {"steps": [{"xpath": "//h1"}], "status": "corroborated"}, "price": [{"xpath": "//p"}]}
    executor = _ir(fields)
    collected, executed = JsonLdCollector(VOCABULARY).collect(page, schema, CTX), executor.execute(page, schema, CTX)
    (product,) = collected.entities
    resolver = Resolver(
        graph=EntityGraph.of((*collected.entities, *executed.rows), VOCABULARY),
        target=product,
        page=PageFacts.of(PAGE_URL, lambda _: True),
        orders=dict.fromkeys(PRECEDENCE_TYPES, ("config", "jsonld")),
    )
    decisions = resolver.prefer(schema, (*collected.candidates, *executed.candidates))
    corroborated = frozenset(name for name, status in executor.field_status.items() if status == "corroborated")
    outcomes = assess_fields(schema, decisions, None, corroborated=corroborated)
    assert {name: (o.value, o.evidence, o.locator) for name, o in outcomes.items()} == {
        "title": ("Blue mug", "config_corroborated", "config:title:0://h1"),
        "price": ({"amount": "12.50", "currency": "EUR"}, "config_uncorroborated", "config:price:0://p"),
    }
