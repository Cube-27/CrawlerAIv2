"""Role C on a detail page through the pipeline (llm spec "Role C input, claims and candidates", resolution spec "LLM
gap hook"): it reads the product's own text, not other items' cards; every missing field goes in one call; a claimed
value the evidence does not hold stays `missing` with reason `unverified`. The client is scripted; no provider is
called. Pages are synthetic (`example.test`)."""

from pydantic import JsonValue

from crawlerai.config_ir.role_c import role_c
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId
from crawlerai.llm.providers.fake import ScriptedClient
from crawlerai.resolve.pipeline import UNVERIFIED
from crawlerai.schemas.types import FieldSpec, FieldType
from tests.unit.test_pipeline import PRODUCT, _bundle, _extract, _html, _product

SCHEMA = PRODUCT.model_copy(
    update={"fields": {**PRODUCT.fields, "released": FieldSpec(type=FieldType.DATE, description="Release date")}}
)
# The product's block, then two other items' cards, each leading to its own page and showing its own price.
CARDS = '<ul><li><a href="/p/2">Oak chair</a> 12.00 EUR</li><li><a href="/p/3">Oak stool</a> 8.00 EUR</li></ul>'
PAGE = _html(_product(price=None), body=f"<p>Solid widget, released 2026-09-30</p>{CARDS}")
# What role C reads: the product's block only.
EVIDENCE = "Widget One\nSolid widget, released 2026-09-30"


def claim(value: str, start: int) -> dict[str, JsonValue]:
    return {"shown": True, "ref": "", "value": value, "start": start, "end": start + len(value)}


def test_role_c_reads_the_product_only_asks_once_and_never_publishes_an_unverified_claim() -> None:
    at = EVIDENCE.index("2026-09-30")
    # The price is quoted from nowhere in the evidence (a card's price is cut from it): it is not grounded.
    reply: dict[str, JsonValue] = {
        "fields": {"price": claim("12.00 EUR", 0), "released": claim("2026-09-30", at)},
    }
    client = ScriptedClient(reply)

    result = _extract(_bundle(PAGE), SCHEMA, role_c=role_c(client, job_id=JobId(uuid7())))

    (request,) = client.requests  # one call for every missing field
    read = request.user.partition("<page_text>")[2].partition("</page_text>")[0]
    assert read.strip() == EVIDENCE  # neither card's name nor price
    assert result.entity is not None
    price, released = result.entity["price"], result.entity["released"]
    assert (price.status, price.reason) == ("missing", UNVERIFIED)
    assert (released.status, released.value) == ("published", "2026-09-30")
    assert not any(c.field == "price" and c.source_kind == "llm" for c in result.candidates)
