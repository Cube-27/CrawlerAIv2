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
    visible; one per normalized value and owner however often the value repeats (D-1343)."""
    return len(_expected(document, kind, others, page))


def _expected(document: object, kind: str, others: list[Candidate], page: ParsedPage) -> set[tuple[str, str, bool]]:
    anchors = [o for o in others if o.source_kind != kind]
    admitted: set[tuple[str, str, bool]] = set()
    for raw in _strings(document):
        if not isinstance(value := normalize(raw, NAME, CTX), Ok):
            continue
        if anchors:
            admitted |= {
                (json.dumps(value.value), o.entity_id, False)
                for o in anchors
                if isinstance(o.normalized, Ok) and equal(value.value, o.normalized.value, NAME)
            }
        elif checkable(raw, NAME) and page.visible_values.visible(raw):
            admitted.add((json.dumps(value.value), "page", True))
    return admitted


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
    assert len(admitted) == len(set().union(*(_expected(d, "xhr", candidates, page) for d in documents)))


# Forms of a few URLs that the url type's equality (SPEC-04 §4.5, RFC 3986 §6.2 normalization) holds equal or apart.
_URL_FORMS = st.sampled_from(
    [
        "https://example.test/a",
        "HTTPS://EXAMPLE.test/a",
        "https://example.test:443/a",
        "https://example.test/%61",
        "https://example.test/b",
        "/a",
        "not a url",
    ]
)
URL = FieldSpec(type=FieldType.URL, description="d", schema_org="Product.url")
URL_SCHEMA = SCHEMA.model_copy(update={"fields": {"name": NAME, "url": URL}})
_URL_OTHER = st.tuples(st.sampled_from(["jsonld", "og"]), st.sampled_from(["page", "jsonld:0:$", "jsonld:1:$"]))


def _url_other(source_kind: str, entity_id: str, raw: str) -> Candidate:
    return Candidate.model_validate(
        {
            "field": "url",
            "entity_id": entity_id,
            "source_kind": source_kind,
            "raw": raw,
            "normalized": normalize(raw, URL, CTX),
            "locator": _LOCATORS[source_kind],
            "independent": True,
        }
    )


def _pairwise_owners(raw: str, others: list[Candidate]) -> list[str]:
    """The rule read pairwise, as admission was first written: each owner of an equal anchor once, in `others`
    order."""
    value = normalize(raw, URL, CTX)
    if not isinstance(value, Ok):
        return []
    equals = [
        o.entity_id for o in others if isinstance(o.normalized, Ok) and equal(value.value, o.normalized.value, URL)
    ]
    return list(dict.fromkeys(equals))


@given(st.lists(_URL_FORMS, max_size=6), st.lists(st.tuples(_URL_OTHER, _URL_FORMS), min_size=1, max_size=6))
def test_admission_by_equality_owns_as_the_pairwise_rule(
    values: list[str], others: list[tuple[tuple[str, str], str]]
) -> None:
    candidates = [_url_other(kind, owner, raw) for (kind, owner), raw in others]
    page = ParsedPage(f"<html><head><script>var s = {json.dumps(values)};</script></head><body></body></html>")

    admitted = JsStateCollector().collect(page, URL_SCHEMA, CTX, candidates).candidates

    # One candidate per normalized value and owner, the first of its repeats: their locators are equally short (D-1343).
    expected: dict[tuple[str, str], str] = {}
    for raw in values:
        value = normalize(raw, URL, CTX)
        for owner in _pairwise_owners(raw, candidates):
            assert isinstance(value, Ok)
            expected.setdefault((json.dumps(value.value), owner), raw)
    assert [(c.raw, c.entity_id) for c in admitted if c.field == "url"] == [
        (raw, owner) for (_, owner), raw in expected.items()
    ]
    assert all(not c.independent for c in admitted)
