"""Role C on a detail page and a listing (llm spec, INV-12): a deterministic request, grounded
candidates, dropped ungrounded values, claims per block grounded in their block, and failures that leave fields missing
with their reason. The client is scripted; no provider is called. Pages are synthetic (`example.test`)."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.items.lines import BlockText
from crawlerai.collect.labels import field_labels
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import CleanedText, TextRun
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId, SchemaId
from crawlerai.llm.client import (
    BudgetExhausted,
    LLMFailure,
    OutputInvalid,
    ProviderUnavailable,
    request_hash,
)
from crawlerai.llm.providers.fake import ScriptedClient
from crawlerai.llm.roles.c_extract import (
    Filled,
    extract_detail,
    extract_listing,
)
from crawlerai.normalize.base import Context, Ok
from crawlerai.resolve.pipeline import GapReply, GapRequest, ListingGapReply, ListingGapRequest
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

JOB = JobId(uuid7())
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="Name of the item", required=True),
        "released": FieldSpec(type=FieldType.DATE, description="Release date"),
        "sku": FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="Stock keeping unit"),
        "rating": FieldSpec(type=FieldType.NUMBER, description="Average rating"),
    },
)
TEXT = "Widget One\nReleased 2026-09-30\nIn stock"
LABELS = field_labels(SCHEMA)
OWNER = "jsonld:0:$"


def span(value: str, start: int, end: int | None = None) -> dict[str, JsonValue]:
    return {"shown": True, "ref": "", "value": value, "start": start, "end": start + len(value) if end is None else end}


def specs(*names: str) -> dict[str, FieldSpec]:
    return {name: SCHEMA.fields[name] for name in names}


def extract(
    client: ScriptedClient,
    fields: Sequence[str] = ("title", "released"),
    text: str = TEXT,
    runs: tuple[TextRun, ...] = (),
) -> Filled:
    asked = specs(*fields)
    filled = extract_detail(client, CleanedText(text, runs), asked, CTX, owner=OWNER, job_id=JOB, labels=LABELS)
    return asyncio.run(filled)


# The claim of a field the page does not show.
ABSENT: dict[str, JsonValue] = {"shown": False, "ref": "", "value": "", "start": 0, "end": 0}


def claims(fields: Mapping[str, dict[str, JsonValue] | None]) -> dict[str, JsonValue]:
    """The reply's claims for `fields`, a field given as None claimed empty."""
    return {name: ABSENT if value is None else value for name, value in fields.items()}


def reply(**fields: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    return {"fields": claims(fields)}


# --- the request ---


# --- grounding the reply ---


def test_a_grounded_value_becomes_an_llm_candidate_owned_by_the_target() -> None:
    filled = extract(ScriptedClient(reply(title=span("Widget One", 0), released=None)))

    assert filled.candidates == (
        Candidate(
            field="title",
            entity_id=OWNER,
            source_kind="llm",
            raw="Widget One",
            normalized=Ok("Widget One"),
            locator="text:0-10",
            independent=True,
        ),
    )
    assert filled.diagnostics == ()


CHECKED = (
    "Widget One\nRef.: AB-12\nReleased: 2026\nhttps://cdn.example.test/img/QX9.jpg\nItem 123 / 12\n#SKU-7\n"
    "5 stars 100% (4)"
)


@pytest.mark.parametrize(
    ("field", "claimed", "start", "kept"),
    [
        ("sku", "Ref.: AB-12", 11, ("AB-12", "text:17-22")),  # a label kept before an identifier is not part of it
        ("sku", "QX9", 0, None),  # an identifier only in an address is no identifier the page states
        ("title", "2026", 0, None),  # a span the page labels as another field is not this field's
        ("sku", "12", 80, ("12", "text:86-88")),  # the head of `123` is no value: the whole `12` is
        ("sku", "#SKU-7", 89, ("#SKU-7", "text:89-95")),  # a number sign before no number is the identifier's
        ("rating", "100%", 104, None),  # a percentage is no value on the rating's scale
        ("rating", "100", 104, None),
        ("rating", "5", 96, ("5", "text:96-97")),
    ],
)
def test_a_grounded_span_is_checked_for_its_field(field: str, claimed: str, start: int, kept: tuple[str, str]) -> None:
    filled = extract(ScriptedClient(reply(**{field: span(claimed, start)})), fields=(field,), text=CHECKED)

    assert [(c.raw, c.locator) for c in filled.candidates] == ([] if kept is None else [kept])
    assert filled.unverified == (() if kept else (field,))


# `Ref.: ` in one span, `AB-12` in the next; `1234` and `WHT` in two sibling spans of one line.
RUNS = "Ref.: AB-12\n(#1234 WHT)"
SPANS = (
    TextRun(0, 5, "/html[1]/body[1]/p[1]/span[1]"),
    TextRun(6, 11, "/html[1]/body[1]/p[1]/span[2]"),
    TextRun(12, 14, "/html[1]/body[1]/p[2]"),
    TextRun(14, 18, "/html[1]/body[1]/p[2]/span[1]"),
    TextRun(19, 22, "/html[1]/body[1]/p[2]/span[2]"),
    TextRun(22, 23, "/html[1]/body[1]/p[2]"),
)


@pytest.mark.parametrize(
    ("claimed", "start", "kept"),
    [
        ("Ref.: AB-12", 0, ("AB-12", "text:6-11")),  # the label's run is cut off, the identifier is one run
        ("1234 WHT", 14, None),  # two runs' values joined are no identifier the page states
        ("1234", 14, ("1234", "text:14-18")),
    ],
)
def test_an_identifier_lies_within_one_text_run(claimed: str, start: int, kept: tuple[str, str] | None) -> None:
    filled = extract(ScriptedClient(reply(sku=span(claimed, start))), fields=("sku",), text=RUNS, runs=SPANS)

    assert [(c.raw, c.locator) for c in filled.candidates] == ([] if kept is None else [kept])


# --- failures (§4.7) ---


@pytest.mark.parametrize(
    ("failure", "diagnostic"),
    [
        (BudgetExhausted("no llm_calls left"), "role C: llm_budget"),
        (ProviderUnavailable("fake: 503"), "role C: llm_unavailable (fake: 503)"),
        (OutputInvalid("at $: not an object"), "role C: llm_output_invalid"),
    ],
)
def test_a_call_without_a_valid_reply_leaves_the_reason_and_no_candidates(failure: LLMFailure, diagnostic: str) -> None:
    filled = extract(ScriptedClient(failure))

    assert (filled.candidates, filled.reply) == ((), failure)
    assert filled.diagnostics == (diagnostic,)


# --- the bound hook ---


def fill(client: ScriptedClient, request: GapRequest) -> GapReply:
    async def run() -> GapReply:
        return await role_c(client, job_id=JOB).detail(request)

    return asyncio.run(run())


def gap_request(html: str, missing: tuple[str, ...], schema: SchemaDef = SCHEMA) -> GapRequest:
    target = Entity(id=OWNER, types=("Product",), urls=(PAGE_URL,), parent=None)
    return GapRequest(ParsedPage(html), schema, CTX, target, missing)


def test_the_hook_reads_the_cleaned_text_and_records_the_call() -> None:
    client = ScriptedClient(reply(title=span("Widget One", 0)))
    request = gap_request("<html><body><h1>Widget One</h1><script>var x = 1;</script></body></html>", ("title",))

    answer = fill(client, request)

    assert "<page_text>\nWidget One\n</page_text>" in client.requests[0].user
    assert [(c.field, c.raw, c.locator) for c in answer.candidates] == [("title", "Widget One", "text:0-10")]
    (call,) = answer.llm_calls
    assert (call.prompt_kind, call.provider, call.model, call.tokens_in, call.tokens_out) == (
        "c_extract_detail",
        "fake",
        "fake-fast",
        10,
        5,
    )
    assert call.request_hash == request_hash(client.requests[0])
    assert (answer.failure, answer.diagnostics) == (None, ())


LINKED_SCHEMA = SCHEMA.model_copy(
    update={
        "fields": {
            **SCHEMA.fields,
            "apply_url": FieldSpec(type=FieldType.URL, description="Where to apply"),
            "image": FieldSpec(type=FieldType.IMAGE_URL, description="Main image"),
        }
    }
)
LINKED_PAGE = (
    '<html><body><h1>Widget One</h1><img src="/img/w1.png" alt="Widget One, front">'
    '<p><a href="/p/1/apply">Apply</a> <a href="#top">Top</a></p>'
    "<p>Released 2026-09-30</p><p>Ships 2026-09-30</p></body></html>"
)
LINKED_CTX = CTX.model_copy(update={"base_url": PAGE_URL})


def linked_request(*missing: str) -> GapRequest:
    target = Entity(id=OWNER, types=("Product",), urls=(PAGE_URL,), parent=None)
    return GapRequest(ParsedPage(LINKED_PAGE), LINKED_SCHEMA, LINKED_CTX, target, missing)


def test_the_text_marks_the_links_and_images_the_fields_asked_can_claim() -> None:
    client = ScriptedClient(reply(apply_url=None, image=None, title=None))

    fill(client, linked_request("apply_url", "image", "title"))
    only_text = ScriptedClient(reply(title=None))
    fill(only_text, linked_request("title"))

    page_text = "Widget One[I1: Widget One, front]\nApply[L1] Top\nReleased 2026-09-30\nShips 2026-09-30"
    assert f"<page_text>\n{page_text}\n</page_text>" in client.requests[0].user
    assert "<page_text>\nWidget One\nApply Top\nReleased 2026-09-30\nShips 2026-09-30\n</page_text>" in (
        only_text.requests[0].user
    )


# --- a recorded runaway reply (F29) ---


# --- a recorded reply (D-1021) ---


# --- listings: claims per block (llm spec, "Role C input, claims and candidates") ---

ROW_SPECS = {
    "title": FieldSpec(type=FieldType.TEXT, description="Name of the item", required=True, scope="row"),
    "sku": FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="Stock keeping unit", scope="row"),
}
PAGE_SPECS = {"heading": FieldSpec(type=FieldType.TEXT, description="Heading of the list", scope="page")}


def block(index: int, text: str, start: int = 0, fields: Sequence[str] = ("sku", "title")) -> BlockText:
    return BlockText(index, f"https://shop.example.test/p/{index}", f"item_block:{index}", start, text, tuple(fields))


def claim(index: int, field: str, value: str) -> dict[str, JsonValue]:
    return {"block": index, "field": field, "value": value}


def claims_reply(*claimed: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"claims": list(claimed)}


# --- the bound listing hook ---

LISTING_SCHEMA = SCHEMA.model_copy(update={"page_kind": "listing", "fields": ROW_SPECS | PAGE_SPECS})
LISTING_PAGE = ParsedPage("<html><body><h1>All widgets</h1><p>Widget One</p></body></html>")


def listing_fill(
    client: ScriptedClient, blocks: tuple[BlockText, ...], page_missing: tuple[str, ...]
) -> ListingGapReply:
    request = ListingGapRequest(LISTING_PAGE, LISTING_SCHEMA, CTX, blocks, page_missing)
    return asyncio.run(role_c(client, job_id=JOB).listing(request))


def test_the_listing_hook_reads_the_blocks_then_the_page_fields_in_the_whole_text() -> None:
    blocks = (block(0, "Widget One", 12, fields=("title",)),)
    client = ScriptedClient(claims_reply(claim(0, "title", "Widget One")), reply(heading=span("All widgets", 0)))

    answer = listing_fill(client, blocks, ("heading",))

    rows, page = client.requests
    assert "[0] Widget One\n</items>\n\nFields, for each item:\n- title (text): Name of the item" in rows.user
    assert "<page_text>\nAll widgets\nWidget One\n</page_text>" in page.user
    assert [(c.entity_id, c.field, c.locator) for c in answer.candidates] == [
        ("item_block:0", "title", "text:12-22"),
        (PAGE, "heading", "text:0-11"),
    ]
    assert [(call.prompt_kind, call.request_hash) for call in answer.llm_calls] == [
        ("c_extract_listing", request_hash(rows)),
        ("c_extract_listing", request_hash(page)),
    ]
    assert answer.failure is None


def test_a_place_in_a_block_heading_is_not_taken_when_the_block_states_remote() -> None:
    # The heading names the item; a line of its own stating the job is remote is where the block states its place.
    places = {"locations": FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.LOCATION), description="d")}
    text = "Sales Rep - Austin, TX\nRemote"
    remote = BlockText(0, "https://jobs.example.test/j/0", "item_block:0", 5, text, ("locations",), heading=(5, 27))
    stated = BlockText(1, "https://jobs.example.test/j/1", "item_block:1", 40, "Sales Rep - Austin, TX", ("locations",))
    stated = replace(stated, heading=(40, 62))
    client = ScriptedClient(claims_reply(claim(0, "locations", "Austin, TX"), claim(1, "locations", "Austin, TX")))

    filled = asyncio.run(extract_listing(client, (remote, stated), places, CTX, job_id=JOB, labels={}))

    assert [(c.entity_id, c.locator) for c in filled.candidates] == [("item_block:1", "text:52-62")]


def test_a_place_keeps_the_remote_label_written_on_the_line_above_it() -> None:
    # Normalization spec, "location as stated": the label the place is written under is part of how the page states it.
    places = {"locations": FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.LOCATION), description="d")}
    text = "Video Editor\nRemote from\nUSA\nWork type"
    labelled = BlockText(0, "https://jobs.example.test/j/0", "item_block:0", 5, text, ("locations",), heading=(5, 17))
    plain = BlockText(1, "https://jobs.example.test/j/1", "item_block:1", 60, "Editor\nOffice\nUSA", ("locations",))
    client = ScriptedClient(claims_reply(claim(0, "locations", "USA"), claim(1, "locations", "USA")))

    filled = asyncio.run(extract_listing(client, (labelled, plain), places, CTX, job_id=JOB, labels={}))

    assert [(c.raw, c.locator) for c in filled.candidates] == [
        ("Remote from\nUSA", "text:18-33"),
        ("USA", "text:74-77"),
    ]
    values = [c.normalized.value for c in filled.candidates if isinstance(c.normalized, Ok)]
    assert [[place.get("text") for place in v if isinstance(place, dict)] for v in values if isinstance(v, list)] == [
        ["Remote from USA"],
        ["USA"],
    ]


def test_a_nested_block_shows_its_context_and_grounds_claims_in_its_own_text_first() -> None:
    # Listings spec, "Role C rows": the enclosing item's text comes first on the block's line; a value is grounded in
    # the block's own text when it holds it, else in the context, at that text's offset in the cleaned text.
    url, row, context = "https://shop.example.test/p/0", "item_block:0", "Unit A\nSKU-1 block"
    nested = BlockText(0, url, row, 40, "SKU-1 Unit A", ("sku", "title"), context, 10)
    client = ScriptedClient(claims_reply(claim(0, "title", "SKU-1 block"), claim(0, "sku", "SKU-1")))

    answer = listing_fill(client, (nested,), ())

    (rows,) = client.requests
    assert "[0] Unit A SKU-1 block SKU-1 Unit A\n</items>" in rows.user
    assert [(c.field, c.locator) for c in answer.candidates] == [("title", "text:17-28"), ("sku", "text:40-45")]
