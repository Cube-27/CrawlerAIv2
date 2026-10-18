"""The extraction pipeline (extraction spec): a capture and a schema in, every field's outcome out.

Pages are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch, Shape
from crawlerai.adapters.registry import Registry
from crawlerai.collect.base import Candidate
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.pipeline import (
    EngineData,
    GapReply,
    GapRequest,
    ListingGapReply,
    ListingGapRequest,
    RoleC,
    extract_page,
)
from crawlerai.resolve.preference import PRECEDENCE_FILE, PRECEDENCE_TYPES, load_precedence
from crawlerai.resolve.types import ExtractionResult, LLMCallRecord
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    Headers,
    NetworkBody,
    network_file,
    sha256_hex,
)

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
# The order committed under `backend/data/` (extraction spec), as the engine loads it when no fit has replaced it.
COMMITTED_ORDERS = load_precedence(Path(__file__).parents[2] / "data" / PRECEDENCE_FILE)
COMMITTED = EngineData(vocabulary=VOCABULARY, orders=COMMITTED_ORDERS, calibration=None)


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


PRODUCT = _schema(
    title=FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
    price=FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"),
    sku=FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku"),
)
PRICE: JsonValue = {"amount": "19.90", "currency": "EUR"}


def _product(name: str = "Widget One", url: str = PAGE_URL, *, price: str | None = "19.90") -> dict[str, Any]:
    node: dict[str, Any] = {"@type": "Product", "name": name, "url": url, "sku": "W-1"}
    if price is not None:
        node["offers"] = {"@type": "Offer", "price": price, "priceCurrency": "EUR"}
    return node


def _html(*nodes: Mapping[str, Any], head: str = "", body: str = "") -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )
    return f'<html lang="en"><head>{blocks}{head}</head><body><h1>Widget One</h1>{body}</body></html>'


def _bundle(
    body: str,
    *,
    block_class: BlockClass = "ok",
    method: CaptureMethod = "http",
    url: str = PAGE_URL,
    final_url: str | None = None,
) -> CaptureBundle:
    raw = body.encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=final_url or url,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method=method,
        status_code=200,
        block_class=block_class,
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=raw, network=())


def _extract(
    bundle: CaptureBundle,
    schema: SchemaDef = PRODUCT,
    *,
    role_c: RoleC | None = None,
    data: EngineData = DATA,
) -> ExtractionResult:
    return asyncio.run(extract_page(bundle, schema, None, role_c, data=data))


def _statuses(result: ExtractionResult) -> dict[str, tuple[str, str | None]]:
    assert result.entity is not None
    return {name: (outcome.status, outcome.reason) for name, outcome in result.entity.items()}


# --- a served page ---


def test_a_product_page_publishes_its_structured_values() -> None:
    result = _extract(_bundle(_html(_product())))
    assert result.outcome == "extracted"
    assert result.entity is not None
    published = {name: (o.value, o.evidence, o.source_kind) for name, o in result.entity.items()}
    assert published == {
        "title": ("Widget One", "structured", "jsonld"),
        "price": (PRICE, "structured", "jsonld"),
        "sku": ("W-1", "structured", "jsonld"),
    }
    # No calibration was fitted, so every field is uncalibrated and the record has no confidence (§4.9).
    assert not any(o.calibrated for o in result.entity.values())
    assert result.record_confidence is None


def test_a_page_missing_a_required_field_is_partial() -> None:
    result = _extract(_bundle(_html(_product(price=None))))
    assert result.outcome == "partial"
    assert _statuses(result)["price"] == ("missing", "no_candidates")


def _group(*prices: str) -> dict[str, Any]:
    # A ProductGroup whose offers sit only under its variants, each variant repeating the group's URL.
    variants = [
        {
            "@type": "Product",
            "url": PAGE_URL,
            "sku": f"W-1-{i}",
            "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR"},
        }
        for i, price in enumerate(prices)
    ]
    return {"@type": "ProductGroup", "name": "Widget One", "url": PAGE_URL, "hasVariant": variants}


def test_a_product_group_whose_variant_offers_agree_publishes_their_price() -> None:
    result = _extract(_bundle(_html(_group("19.90", "19.90", "19.90"))))
    assert result.entity is not None
    assert (result.entity["title"].value, result.entity["price"].value) == ("Widget One", PRICE)
    # Each variant's sku is the variant's, not the group's (§4.6): the group states none.
    assert _statuses(result)["sku"] == ("missing", "not_owned")


# --- pages that were not served (INV-11) ---


# --- one parse per parser (INV-26) ---


# --- failures (§4.14) ---


# --- the LLM hook (§4.13) ---

CALL = LLMCallRecord(
    prompt_kind="c_extract_detail",
    provider="provider-a",
    model="model-a",
    request_hash="0" * 64,
    tokens_in=9,
    tokens_out=3,
)


class FakeRoleC:
    """On a detail page, answers each missing field with the money value the page text shows, grounded on the target,
    or with `failure`; on a listing, gives `listing_reply`, or with `fill_blocks` fills each asked field of each block
    with the block's first line, grounded there. `error` is raised instead of either."""

    def __init__(
        self,
        *,
        failure: str | None = None,
        listing_reply: ListingGapReply | None = None,
        fill_blocks: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[GapRequest] = []
        self.listing_requests: list[ListingGapRequest] = []
        self._failure = failure
        self._listing_reply = listing_reply or ListingGapReply(candidates=(), llm_calls=())
        self._fill_blocks = fill_blocks
        self._error = error

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        self.listing_requests.append(request)
        if self._error is not None:
            raise self._error
        if self._fill_blocks:
            filled = tuple(
                _llm(name, block.row, block.text.split("\n")[0], block.start)
                for block in request.blocks
                for name in block.fields
            )
            return ListingGapReply(candidates=filled, llm_calls=(LISTING_CALL,))
        return self._listing_reply

    async def detail(self, request: GapRequest) -> GapReply:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._failure is not None:
            return GapReply((), (), failure=self._failure, diagnostics=(f"role C: {self._failure}",))
        candidates = tuple(
            Candidate(
                field=name,
                entity_id=request.target.id,
                source_kind="llm",
                raw="19.90 EUR",
                normalized=Ok(PRICE),
                locator="text:0-9",
                independent=True,
            )
            for name in request.missing
        )
        return GapReply(candidates=candidates, llm_calls=(CALL,))


def test_required_fields_left_missing_go_to_role_c_once() -> None:
    role_c = FakeRoleC()
    result = _extract(_bundle(_html(_product(price=None))), role_c=role_c)
    assert [r.missing for r in role_c.requests] == [("price",)]
    assert role_c.requests[0].target.types == ("Product",)
    assert result.entity is not None
    assert (result.entity["price"].value, result.entity["price"].evidence) == (PRICE, "llm_grounded")
    assert result.llm_calls == (CALL,)
    assert result.outcome == "extracted"


def test_role_c_is_not_called_for_conflicts() -> None:
    # §4.13: a conflict is never sent to the LLM; with no single target every field is one.
    role_c = FakeRoleC()
    page = _html(
        _product("Widget Two", "https://shop.example.test/p/2"),
        _product("Widget Three", "https://shop.example.test/p/3"),
    )
    result = _extract(_bundle(page), role_c=role_c)
    assert _statuses(result) == dict.fromkeys(("title", "price", "sku"), ("conflict", "intent_ambiguous"))
    assert (result.outcome, role_c.requests, result.llm_calls) == ("partial", [], ())


# --- api captures (D-0445) ---


class FakeAdapter:
    """A platform whose page URLs are under `/jobs/` of the synthetic host, whose API is under `/api/`, and whose
    answer is a JobPosting with a `title` member."""

    name = "synthetic"

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="t", page_kind="detail") if "/jobs/" in url else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return "/api/" in endpoint

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        raise AssertionError("extraction fetches nothing")

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return (Shape(type="JobPosting", properties={"title": ("title",)}),)


JOB = _schema(title=FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="JobPosting.title"))
JOB_URL = "https://jobs.example.test/jobs/1"
JOB_API = "https://jobs.example.test/api/jobs/1"


def test_an_api_capture_is_read_by_the_adapter_that_detects_its_page_url_and_serves_its_endpoint() -> None:
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry([FakeAdapter()]))
    bundle = _bundle('{"title": "Engineer"}', method="api", url=JOB_URL, final_url=JOB_API)
    result = _extract(bundle, JOB, data=data)
    assert result.entity is not None
    title = result.entity["title"]
    assert (title.value, title.source_kind, title.evidence, title.locator) == (
        "Engineer",
        "adapter",
        "adapter",
        "adapter:synthetic:$['title']",
    )


# --- cold listings (§4.7 "Listings", §8.6) ---

LISTING_URL = "https://shop.example.test/c/widgets?page=2"
LISTING = _schema(
    "listing",
    title=PRODUCT.fields["title"],
    url=FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
    price=FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    # og:title fills text fields whose path ends in `.name` (the OGP table, §4.5); on the page, only the page owns it.
    page_title=FieldSpec(type=FieldType.TEXT, description="d", scope="page", schema_org="Product.name"),
    next_page_url=FieldSpec(type=FieldType.URL, description="d", scope="page"),
)


def _row(n: int, **extra: Any) -> dict[str, Any]:
    return {**_product(f"Widget {n}", f"https://shop.example.test/p/{n}", price=f"{n}.50"), **extra}


def _item_list(*items: Mapping[str, Any]) -> dict[str, Any]:
    elements = [{"@type": "ListItem", "position": i + 1, "item": item} for i, item in enumerate(items)]
    return {"@type": "ItemList", "itemListElement": elements}


def _listing(page: str, schema: SchemaDef = LISTING, **kwargs: Any) -> ExtractionResult:
    return _extract(_bundle(page, url=LISTING_URL), schema, **kwargs)


def _row_values(result: ExtractionResult) -> list[dict[str, JsonValue]]:
    return [{name: o.value for name, o in row.items() if o.status == "published"} for row in result.rows]


def test_the_items_of_an_item_list_are_the_rows() -> None:
    result = _listing(_html(_item_list(_row(1), _row(2))))
    assert _row_values(result) == [
        {"title": "Widget 1", "url": "https://shop.example.test/p/1", "price": {"amount": "1.50", "currency": "EUR"}},
        {"title": "Widget 2", "url": "https://shop.example.test/p/2", "price": {"amount": "2.50", "currency": "EUR"}},
    ]
    # Each row holds its row-scoped fields; the page-scoped ones resolve once, against the page.
    assert {frozenset(row) for row in result.rows} == {frozenset({"title", "url", "price"})}
    assert result.entity is not None
    assert set(result.entity) == {"page_title", "next_page_url"}
    assert result.outcome == "extracted"


def _branded(n: int) -> str:
    return f'<li class="card"><h3><a href="/p/{n}">Widget {n}</a></h3><span>{n}.50 EUR</span><p>Acme {n}</p></li>'


BRANDED = _schema(
    "listing",
    title=LISTING.fields["title"],
    url=LISTING.fields["url"],
    brand=FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name"),
)


def test_role_c_fills_the_block_rows_when_a_row_field_publishes_on_no_row() -> None:
    # Listings spec, "Role C rows": no block publishes `brand`, so each block's row is asked for it, and only for it.
    role_c = FakeRoleC(fill_blocks=True)
    page = _html(body=f"<ul>{''.join(_branded(n) for n in (1, 2, 3))}</ul>")

    result = _listing(page, BRANDED, role_c=role_c, data=COMMITTED)

    (request,) = role_c.listing_requests
    assert [(block.index, block.url, block.fields) for block in request.blocks] == [
        (n - 1, f"https://shop.example.test/p/{n}", ("brand",)) for n in (1, 2, 3)
    ]
    assert [block.text for block in request.blocks] == [f"Widget {n}\n{n}.50 EUR\nAcme {n}" for n in (1, 2, 3)]
    assert [block.row for block in request.blocks] == [f"item_block:0:{i}" for i in range(3)]
    # The fake fills `brand` with the first line: the claim fills the block's row, the block's own values stand.
    assert [(row["title"].value, row["brand"].value, row["brand"].evidence) for row in result.rows] == [
        (f"Widget {n}", f"Widget {n}", "llm_grounded") for n in (1, 2, 3)
    ]


LISTING_CALL = CALL.model_copy(update={"prompt_kind": "c_extract_listing"})


def _llm(field: str, owner: str, raw: str, start: int) -> Candidate:
    return Candidate(
        field=field,
        entity_id=owner,
        source_kind="llm",
        raw=raw,
        normalized=Ok(raw),
        locator=f"text:{start}-{start + len(raw)}",
        independent=True,
    )


# A listing schema whose page title is required: role C is asked for the page fields when it is missing.
TITLED = _schema(
    "listing",
    **{**LISTING.fields, "page_title": LISTING.fields["page_title"].model_copy(update={"required": True})},
)


def test_the_page_fields_are_asked_when_a_required_one_is_missing() -> None:
    role_c = FakeRoleC(listing_reply=ListingGapReply((_llm("page_title", "page", "All widgets", 0),), (LISTING_CALL,)))

    result = _listing(_html(body="<h1>All widgets</h1>"), TITLED, role_c=role_c)

    (request,) = role_c.listing_requests
    assert (request.blocks, request.page_missing) == ((), ("page_title", "next_page_url"))
    assert result.entity is not None
    assert (result.entity["page_title"].value, result.entity["page_title"].evidence) == ("All widgets", "llm_grounded")
    assert result.llm_calls == (LISTING_CALL,)


def test_a_listing_role_c_error_propagates() -> None:
    html, role_c = _html(), FakeRoleC(error=LookupError("no recorded response"))
    with pytest.raises(LookupError, match="no recorded response"):
        _listing(html, TITLED, role_c=role_c)


def _card(n: int, *links: str) -> str:
    anchors = "".join(f'<a href="{href}">Widget {n}</a>' for href in links)
    return f'<li class="card"><h3>{anchors or f"Widget {n}"}</h3><span>{n}.50 EUR</span></li>'


def test_a_grid_of_cards_gives_its_rows_before_role_c_is_asked() -> None:
    # Listings spec, "Rows from blocks": each card's heading link and price; its `#reviews` link is the same document.
    cards = "".join(_card(n, f"/p/{n}", f"/p/{n}#reviews") for n in (1, 2, 3))
    role_c = FakeRoleC()

    result = _listing(_html(body=f"<ul>{cards}</ul>"), role_c=role_c, data=COMMITTED)

    assert _row_values(result) == [
        {
            "title": f"Widget {n}",
            "url": f"https://shop.example.test/p/{n}",
            "price": {"amount": f"{n}.50", "currency": "EUR"},
        }
        for n in (1, 2, 3)
    ]
    assert [(row["url"].source_kind, row["url"].locator) for row in result.rows] == [
        ("dom", f"dom:/html[1]/body[1]/ul[1]/li[{n}]/h3[1]/a[1]") for n in (1, 2, 3)
    ]
    assert (role_c.listing_requests, result.outcome) == ([], "extracted")


# --- listing rows from captured calls (Appendix A #58) ---


def _network_listing(*items: Mapping[str, Any], shown: Sequence[Mapping[str, Any]] | None = None) -> CaptureBundle:
    """A rendered listing showing each item's link and price (`shown`'s, else the call's), and the call it loaded
    `items` with."""
    cards = "".join(f'<li><a href="{i["href"]}">{i["href"]}</a> <span>{i["price"]}</span></li>' for i in shown or items)
    raw = f'<html lang="en"><body><h1>All widgets</h1><ul>{cards}</ul></body></html>'.encode()
    data = json.dumps({"results": list(items)}).encode()
    entry = NetworkBody(
        url="https://api.example.test/widgets?page=1",
        status=200,
        content_type="application/json",
        sha256=sha256_hex(data),
        file=network_file(0),
        method="GET",
    )
    bundle = _bundle(raw.decode(), method="browser", url=LISTING_URL)
    manifest = bundle.manifest.model_copy(update={"network_bodies": (entry,)})
    return CaptureBundle(manifest=manifest, body=bundle.body, network=(data,))


NETWORK_ITEMS = [
    {"name": f"Widget {n}", "href": f"https://shop.example.test/p/{n}", "price": f"€{n}.50"} for n in (1, 2, 3)
]


def test_a_listing_without_structured_rows_takes_the_rows_of_its_captured_call() -> None:
    result = _extract(_network_listing(*NETWORK_ITEMS), LISTING, data=COMMITTED)

    assert _row_values(result) == [
        {"url": f"https://shop.example.test/p/{n}", "price": {"amount": f"{n}.50", "currency": "EUR"}}
        for n in (1, 2, 3)
    ]
    # The cards show each item's link and price: the price agrees with the call's, the link is the page's spelling.
    assert {(row["price"].evidence, row["price"].source_kind) for row in result.rows} == {("agreed", "xhr")}
    assert [row["url"].locator for row in result.rows] == [
        f"dom:/html[1]/body[1]/ul[1]/li[{n}]/a[1]" for n in (1, 2, 3)
    ]
    # The titles are text, admitted by equality only: every row lacks its required title.
    assert result.outcome == "partial"


def test_complete_rows_of_a_call_do_not_call_role_c() -> None:
    role_c = FakeRoleC()
    schema = _schema("listing", url=LISTING.fields["url"], price=LISTING.fields["price"])
    result = _extract(_network_listing(*NETWORK_ITEMS), schema, role_c=role_c, data=COMMITTED)

    assert (role_c.listing_requests, result.outcome, len(result.rows)) == ([], "extracted", 3)
