"""Eager fragments in the locate run (learning-configs spec, "Locate run"; extraction spec, "Source documents"): a
value or a listing's rows that only an eager Turbo frame's answer holds are located as `http`, since the HTTP capture
includes the frame's answer as the page shows it.

Pages are synthetic captures on `.test` hosts: the HTTP capture holds the frame element and, as a network body, the
frame's answer (the companion call the HTTP rung makes); the render holds the frame filled.
"""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.held_out import StoredPage, read_bundle
from crawlerai.config_ir.induction import SamplePage
from crawlerai.config_ir.locate import Located, Sampled, locate
from crawlerai.config_ir.model import ExtractionConfigIR, Fetch, Provenance, SchemaRef
from crawlerai.config_ir.validation import Facts, HeldOutPage
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, PageKind
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
SITE = "https://shop.example.test"
MATERIALS = ("Oak wood", "Pine wood", "Elm wood")
ITEMS = 4


def _schema(page_kind: PageKind, fields: dict[str, object]) -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": uuid7(),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": fields,
        }
    )


DETAIL = _schema(
    "detail",
    {
        "title": {"type": "text", "required": True, "description": "d"},
        "material": {"type": "text", "description": "d"},
    },
)
LISTING = _schema(
    "listing",
    {
        "title": {"type": "text", "required": True, "description": "d", "schema_org": "Product.name"},
        "url": {"type": "url", "required": True, "description": "d", "schema_org": "Product.url"},
    },
)


def _bundle(n: int, html: str, method: CaptureMethod, answer: str | None) -> CaptureBundle:
    body = html.encode()
    url = f"{SITE}/p/{n}"
    bodies = () if answer is None else ((f"{SITE}/f/{n}", answer.encode()),)
    entries = tuple(
        NetworkBody(
            url=src,
            status=200,
            content_type="text/html",
            sha256=sha256_hex(data),
            file=f"network/{i + 1:04d}.json",
            method="GET",
            resource_type="fetch",
        )
        for i, (src, data) in enumerate(bodies)
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
        fetched_at=datetime(2026, 10, 20, tzinfo=UTC),
        method=method,
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("content-type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(body),
        network_bodies=entries,
        fetch_policy={},
        engine_version="test",
    )
    return CaptureBundle(manifest=manifest, body=body, network=tuple(data for _, data in bodies))


def _page(n: int, inside: str, *, filled: bool) -> str:
    frame = f"<turbo-frame id='offer' src='/f/{n}'>{inside if filled else ''}</turbo-frame>"
    return f"<html><body><h1>Item {n}</h1><nav><a href='/'>Home</a></nav>{frame}</body></html>"


def _sampled(
    n: int, inside: str, published: Mapping[str, JsonValue], rows: Sequence[Mapping[str, JsonValue]] = ()
) -> Sampled:
    """Page `n` whose frame holds `inside`: the HTTP capture with the frame's answer, and the render with it filled."""
    http = _bundle(n, _page(n, inside, filled=False), "http", f"<turbo-frame id='offer'>{inside}</turbo-frame>")
    parsed, ctx = read_bundle(http)
    stored = StoredPage(HeldOutPage(CaptureId(uuid7()), parsed, ctx, Facts()), SamplePage(parsed, ctx, {}), http)
    render = _bundle(n, _page(n, inside, filled=True), "browser", None)
    rendered, rendered_ctx = read_bundle(render)
    return Sampled(stored, render, rendered, rendered_ctx, published, rows)


def _base(schema: SchemaDef) -> ExtractionConfigIR:
    return ExtractionConfigIR(
        ir_version="1",
        site="shop.example.test",
        schema_=SchemaRef(name=schema.name, digest=document_digest(schema)),
        page_kind=schema.page_kind,
        fetch=Fetch(method="http"),
        fields={},
        provenance=Provenance(
            origin="induced", validated_on=[], learned_at=datetime(2026, 10, 20, tzinfo=UTC), engine_version="test"
        ),
    )


def _locate(schema: SchemaDef, names: list[str], pages: list[Sampled]) -> Located:
    return asyncio.run(locate(_base(schema), schema, names, pages, VOCABULARY, None))


def test_a_value_only_an_eager_frame_holds_is_located_as_http() -> None:
    pages = [
        _sampled(n, f"<p class='material'>{MATERIALS[n]}</p>", {"title": f"Item {n}", "material": MATERIALS[n]})
        for n in range(3)
    ]

    located = _locate(DETAIL, ["material"], pages)

    assert located.fields["material"].needs == "http"
    assert set(located.sources["material"]) == {"http", "browser"}


def test_rows_an_eager_frame_holds_are_located_as_http() -> None:
    def cards(n: int) -> str:
        return "".join(
            f"<li class='card'><a href='/p/{n}-{i}'><h3>Item {n}-{i}</h3></a>"
            f"<img src='/i/{n}-{i}.jpg' alt='Item {n}-{i}'><span class='badge'>Tag {i}</span></li>"
            for i in range(ITEMS)
        )

    rows = [[{"title": f"Item {n}-{i}", "url": f"{SITE}/p/{n}-{i}"} for i in range(ITEMS)] for n in range(3)]
    pages = [_sampled(n, f"<ul class='grid'>{cards(n)}</ul>", {}, rows[n]) for n in range(3)]

    located = _locate(LISTING, ["title", "url"], pages)

    assert located.rows is not None
    assert located.rows.listing is not None
    assert {steps.needs for steps in located.rows.listing.fields.values()} == {"http"}
