"""OpenGraph collector properties (SPEC-05 §4.5): for any sequence of meta tags, a scalar field takes the first value
of its OGP property and a list field every value in document order (Open Graph protocol, "Arrays"), and the collector
never raises."""

from datetime import UTC, datetime
from html import escape

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.locator import parse_locator
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://example.test/", page_url=None)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
        "images": FieldSpec(
            type=FieldType.LIST, description="d", schema_org="Product.image", item=FieldSpec(type=FieldType.IMAGE_URL)
        ),
    },
)

_PROPERTIES = st.sampled_from(["og:title", "og:image", "og:image:url", "og:description", "description"])
# Attribute values without control characters (HTML Standard: the parser rewrites CR and drops NUL) or lone surrogates.
_CONTENT = st.text(st.characters(exclude_categories=("Cc", "Cs")), max_size=20)


@given(st.lists(st.tuples(_PROPERTIES, _CONTENT), max_size=8))
def test_first_value_for_a_scalar_and_all_values_for_a_list(metas: list[tuple[str, str]]) -> None:
    html = "".join(f'<meta property="{escape(p)}" content="{escape(c)}">' for p, c in metas)

    result = OpenGraphCollector().collect(ParsedPage(f"<html><head>{html}</head></html>"), SCHEMA, CTX)

    by_field = {c.field: c for c in result.candidates}
    titles = [c for p, c in metas if p == "og:title"]
    images = [(p, c) for p, c in metas if p in ("og:image", "og:image:url")]
    assert (by_field["title"].raw if "title" in by_field else None) == (titles[0] if titles else None)
    assert (by_field["images"].raw if "images" in by_field else None) == ([c for _, c in images] or None)
    if images:
        assert by_field["images"].locator == f"meta:{images[0][0]}"
    assert all(parse_locator(c.locator).scheme == "meta" for c in result.candidates)
