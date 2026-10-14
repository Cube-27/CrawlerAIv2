"""The admission rule for embedded JSON state and network bodies (SPEC-05 §4.5, ARCHITECTURE §8.1), for any document,
page text and set of other candidates: a value is admitted exactly when it equals another source kind's candidate of
the field (then owned by that candidate's entity, not independent) or, for a field with no such candidate whose type
has a checkable syntax, when it is visible (then owned by the page, independent). The field here is text, which has
none, so its visible values are never admitted on their own."""

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.base import Candidate
from crawlerai.collect.js_state import JsStateCollector
from crawlerai.collect.xhr import XhrCollector
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import checkable, equal, normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://example.test/", page_url=None)
NAME = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name")
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    version=1,
    page_kind="detail",
    fields={"name": NAME},
)

# Few words, so that values, page text and other candidates often coincide.
_WORDS = st.sampled_from(["alpha", "Alpha", "beta", "gamma delta", "  beta "])
_DOCUMENT = st.recursive(
    _WORDS | st.integers(-3, 3) | st.booleans() | st.none(),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.sampled_from(["a", "b", "c"]), inner, max_size=3),
    max_leaves=8,
)
_LOCATORS = {
    "jsonld": "jsonld:0:$",
    "og": "meta:og:title",
    "js_state": "js_state:/html[1]/script[1]:$",
    "xhr": "xhr:0:$",
}
_OTHER = st.tuples(
    st.sampled_from(["jsonld", "og", "js_state", "xhr"]), st.sampled_from(["page", "jsonld:0:$"]), _WORDS
)


def _other(source_kind: str, entity_id: str, raw: str) -> Candidate:
    return Candidate.model_validate(
        {
            "field": "name",
            "entity_id": entity_id,
            "source_kind": source_kind,
            "raw": raw,
            "normalized": normalize(raw, NAME, CTX),
            "locator": _LOCATORS[source_kind],
            "independent": True,
        }
    )


def _check(admitted: tuple[Candidate, ...], kind: str, others: list[Candidate], page: ParsedPage) -> None:
    anchors = [o for o in others if o.source_kind != kind]
    for candidate in admitted:
        assert isinstance(candidate.raw, str)
        assert isinstance(candidate.normalized, Ok)
        if candidate.independent:
            assert (candidate.entity_id, anchors) == ("page", [])
            assert checkable(candidate.raw, NAME)
            assert page.visible_values.visible(candidate.raw)
        else:
            assert any(
                o.entity_id == candidate.entity_id
                and isinstance(o.normalized, Ok)
                and equal(candidate.normalized.value, o.normalized.value, NAME)
                for o in anchors
            )


def _expected_count(document: object, kind: str, others: list[Candidate], page: ParsedPage) -> int:
    """How many candidates the rule admits from `document`'s strings: one per equal owner, or one when checkable and
    visible."""
    anchors = [o for o in others if o.source_kind != kind]
    count = 0
    for raw in _strings(document):
        if not isinstance(value := normalize(raw, NAME, CTX), Ok):
            continue
        if anchors:
            equals = {
                o.entity_id
                for o in anchors
                if isinstance(o.normalized, Ok) and equal(value.value, o.normalized.value, NAME)
            }
            count += len(equals)
        else:
            count += checkable(raw, NAME) and page.visible_values.visible(raw)
    return count


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for child in value.values() for s in _strings(child)]
    if isinstance(value, list):
        return [s for child in value for s in _strings(child)]
    return []


@given(_DOCUMENT, st.lists(_WORDS, max_size=3), st.lists(_OTHER, max_size=3))
def test_js_state_admits_exactly_by_equality_or_visibility(
    document: object, shown: list[str], others: list[tuple[str, str, str]]
) -> None:
    candidates = [_other(*o) for o in others]
    script = f"var s = {json.dumps([document])};"  # wrapped in an array: state is an object or an array
    page = ParsedPage(f"<html><head><script>{script}</script></head><body><p>{' | '.join(shown)}</p></body></html>")

    admitted = JsStateCollector().collect(page, SCHEMA, CTX, candidates).candidates

    _check(admitted, "js_state", candidates, page)
    assert len(admitted) == _expected_count(document, "js_state", candidates, page)


@given(st.lists(_DOCUMENT, max_size=3), st.lists(_WORDS, max_size=3), st.lists(_OTHER, max_size=3))
def test_xhr_admits_exactly_by_equality_or_visibility(
    documents: list[object], shown: list[str], others: list[tuple[str, str, str]]
) -> None:
    candidates = [_other(*o) for o in others]
    page = ParsedPage(
        f"<html><body><p>{' | '.join(shown)}</p></body></html>", tuple(json.dumps(d).encode() for d in documents)
    )

    admitted = XhrCollector().collect(page, SCHEMA, CTX, candidates).candidates

    _check(admitted, "xhr", candidates, page)
    assert len(admitted) == sum(_expected_count(d, "xhr", candidates, page) for d in documents)
