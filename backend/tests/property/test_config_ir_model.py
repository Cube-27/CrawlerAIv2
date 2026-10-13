"""The config IR model (SPEC-08 §4.2, ARCHITECTURE §12.1): every valid IR survives a JSON round trip, CSS steps
carry an XPath 1.0 translation that selects the same elements, and malformed steps and post ops are refused."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from lxml import html
from pydantic import ValidationError

from crawlerai.config_ir.model import CssStep, ExtractionConfigIR, FieldSteps, NormalizeOp
from crawlerai.schemas.types import FieldType

_TAGS = ["div", "span", "p", "a", "li", "ul"]
_CLASSES = ["x", "y", "price-now", "z1"]
_IDS = ["i1", "i2"]

# --- generated IRs --------------------------------------------------------------------------------------------------

_xpath = st.sampled_from(
    ["//h1", "normalize-space(//h1[@data-testid='t'])", "//a[@rel='next']/@href", "//ul/li[1]", "string(//p)"]
)
_css = st.sampled_from(["div.x > span", "a#i1", "li[data-k='v']", "ul li:nth-child(2)", "p:not(.y)"])
_jsonpath = st.from_regex(r"\$(\.[a-z][A-Za-z]{0,8}){1,3}", fullmatch=True)
_regex = st.sampled_from([r"sku:\s*(\w+)", r"(\d+)", r"^\s*(.+?)\s*$"])
_post: st.SearchStrategy[list[dict[str, Any]]] = st.lists(
    st.one_of(
        st.sampled_from([t.value for t in FieldType if t not in (FieldType.LIST, FieldType.OBJECT)]).map(
            lambda name: {name: {}}
        ),
        st.just({"trim": {}}),
        st.just({"absolutize_url": {}}),
        _regex.map(lambda pattern: {"regex_replace": {"pattern": pattern, "repl": r"\1"}}),
    ),
    max_size=3,
)
_step: st.SearchStrategy[dict[str, Any]] = st.one_of(
    st.builds(lambda xpath, post: {"xpath": xpath, "post": post}, _xpath, _post),
    st.builds(lambda css, post: {"css": css, "post": post}, _css, _post),
    st.builds(
        lambda path, when, post: {"jsonld": path, "when_type": when, "post": post},
        _jsonpath,
        st.sampled_from([None, "Product", "JobPosting"]),
        _post,
    ),
    st.builds(
        lambda path, source: {"jsonpath": path, "source": source},
        _jsonpath,
        st.sampled_from(["jsonld", "js_state", "xhr", "api"]),
    ),
    st.builds(lambda regex: {"regex": regex}, _regex),
    st.builds(lambda name: {"attr": name}, st.sampled_from(["href", "data-sku", "content"])),
)
_ratio = st.none() | st.floats(min_value=0, max_value=1)
_field = st.builds(
    lambda steps, status, yield_, validity: {"steps": steps, "status": status, "yield": yield_, "validity": validity},
    st.lists(_step, min_size=1, max_size=3),
    st.sampled_from(["corroborated", "uncorroborated", "operator", "suspended"]),
    _ratio,
    _ratio,
)
_fields = st.dictionaries(st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True), _field, max_size=4)
_listing = st.none() | st.builds(
    lambda row, fields, next_: {"row": row, "fields": fields, "next": next_}, _step, _fields, st.none() | _step
)
_ir = st.builds(
    lambda fields, listing, origin, kind, method: {
        "ir_version": "1",
        "site": "shop.example.com",
        "schema": {"name": "commerce_detail", "version": 2},
        "page_kind": kind,
        "fetch": {"method": method},
        "fields": fields,
        "listing": listing,
        "provenance": {
            "origin": origin,
            "validated_on": ["0190b2a0-0000-7000-8000-000000000001"],
            "learned_at": "2026-10-13T10:00:00Z",
            "engine_version": "abc1234+cal.none",
        },
    },
    _fields,
    _listing,
    st.sampled_from(["adapter", "induced", "llm_synth", "operator"]),
    st.sampled_from(["detail", "listing"]),
    st.sampled_from(["http", "browser"]),
)


@given(_ir)
def test_ir_survives_a_json_round_trip(document: dict[str, Any]) -> None:
    ir = ExtractionConfigIR.model_validate(document)
    assert ExtractionConfigIR.model_validate_json(ir.model_dump_json()) == ir
    assert ExtractionConfigIR.model_validate(ir.model_dump(mode="json")) == ir


def test_ir_serializes_in_the_architecture_shape() -> None:
    ir = ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "example.com",
            "schema": {"name": "commerce_detail", "version": 1},
            "page_kind": "detail",
            "fetch": {"method": "http"},
            "fields": {
                "price": {
                    "steps": [{"css": "span.p1", "post": [{"money": {}}, {"trim": {}}]}],
                    "status": "uncorroborated",
                    "yield": 0.5,
                }
            },
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": datetime(2026, 10, 13, tzinfo=UTC),
                "engine_version": "abc1234+cal.none",
            },
        }
    )
    dumped = ir.model_dump(mode="json")
    assert dumped["schema"] == {"name": "commerce_detail", "version": 1}
    assert dumped["fields"]["price"] == {
        "steps": [
            {
                "css": "span.p1",
                "xpath": "descendant-or-self::span[@class and contains(@class, 'p1') "
                "and contains(concat(' ', normalize-space(@class), ' '), ' p1 ')]",
                "post": [{"money": {}}, {"trim": {}}],
            }
        ],
        "status": "uncorroborated",
        "yield": 0.5,
        "validity": None,
    }
    assert ir.fields["price"].steps[0] == CssStep.model_validate(
        {"css": "span.p1", "post": [{"money": {}}, {"trim": {}}]}
    )


# --- CSS → XPath equivalence ----------------------------------------------------------------------------------------

# A compound selector: a tag or `*`, then classes, an id and attribute tests; a selector chains compounds with the
# descendant or child combinator (Selectors Level 3 §5 to 8).
_compound = st.builds(
    lambda tag, classes, id_: {"tag": tag, "classes": classes, "id": id_},
    st.sampled_from([*_TAGS, "*"]),
    st.lists(st.sampled_from(_CLASSES), max_size=2, unique=True),
    st.none() | st.sampled_from(_IDS),
)
_selector = st.lists(st.tuples(st.sampled_from([" ", " > "]), _compound), min_size=1, max_size=3)


def _css_text(selector: Sequence[tuple[str, dict[str, Any]]]) -> str:
    parts = []
    for i, (combinator, compound) in enumerate(selector):
        text = compound["tag"] + "".join(f".{c}" for c in compound["classes"])
        text += f"#{compound['id']}" if compound["id"] else ""
        parts.append(text if i == 0 else combinator + text)
    return "".join(parts)


_element = st.builds(
    lambda tag, classes, id_: (tag, classes, id_),
    st.sampled_from(_TAGS),
    st.lists(st.sampled_from(_CLASSES), max_size=3, unique=True),
    st.none() | st.sampled_from(_IDS),
)
_tree: st.SearchStrategy[tuple[Any, list[Any]]] = st.recursive(
    st.builds(lambda element: (element, []), _element),
    lambda children: st.builds(lambda element, kids: (element, kids), _element, st.lists(children, max_size=3)),
    max_leaves=12,
)


def _html(node: tuple[Any, list[Any]]) -> str:
    (tag, classes, id_), children = node
    attributes = f' class=" {"  ".join(classes)} "' if classes else ""
    attributes += f' id="{id_}"' if id_ else ""
    return f"<{tag}{attributes}>{''.join(_html(child) for child in children)}</{tag}>"


def _matches_compound(element: html.HtmlElement, compound: dict[str, Any]) -> bool:
    classes = set((element.get("class") or "").split())
    return (
        compound["tag"] in ("*", element.tag)
        and classes.issuperset(compound["classes"])
        and compound["id"] in (None, element.get("id"))
    )


def _matches(element: html.HtmlElement | None, selector: Sequence[tuple[str, dict[str, Any]]]) -> bool:
    """A reference matcher, read right to left as Selectors Level 3 §8 defines the combinators."""
    if element is None or not _matches_compound(element, selector[-1][1]):
        return False
    if len(selector) == 1:
        return True
    combinator, rest = selector[-1][0], selector[:-1]
    if combinator == " > ":
        return _matches(element.getparent(), rest)
    ancestor = element.getparent()
    while ancestor is not None:
        if _matches(ancestor, rest):
            return True
        ancestor = ancestor.getparent()
    return False


@given(_selector, st.lists(_tree, min_size=1, max_size=3))
def test_css_translation_selects_what_the_selector_matches(
    selector: list[tuple[str, dict[str, Any]]], trees: list[tuple[Any, list[Any]]]
) -> None:
    document = html.document_fromstring(f"<html><body>{''.join(_html(tree) for tree in trees)}</body></html>")
    step = CssStep.model_validate({"css": _css_text(selector)})
    selected = document.xpath(step.xpath)
    expected = [element for element in document.iter() if _matches(element, selector)]
    assert selected == expected


# --- rejections -----------------------------------------------------------------------------------------------------


def _validate_step(step: object) -> None:
    FieldSteps.model_validate({"steps": [step], "status": "operator"})


@pytest.mark.parametrize(
    "step",
    [
        {},
        {"post": []},
        {"xpath": "//a", "regex": "x"},
        {"jsonld": "$.name", "jsonpath": "$.name", "source": "jsonld"},
        {"attr": "href", "css": "a"},
        {"xpath": "//a", "when_type": "Product"},
        {"jsonpath": "$.name"},
        {"jsonpath": "$.name", "source": "cookies"},
        {"jsonld": "name"},
        {"jsonld": "$.name", "when_type": "product"},
        {"attr": "a b"},
        {"css": "a::attr(href)"},
        {"css": "a", "xpath": "//b"},
        {"xpath": "upper-case(//a)"},
        {"regex": r"\Z"},
        {"xpath": "//a", "selector": "x"},
    ],
)
def test_malformed_steps_are_refused(step: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _validate_step(step)


@pytest.mark.parametrize(
    "post",
    [
        {},
        {"trim": {}, "money": {}},
        {"list": {}},
        {"object": {}},
        {"money": {"currency": "EUR"}},
        {"trim": {"x": 1}},
        {"uppercase": {}},
        {"regex_replace": {"pattern": "(a)"}},
        {"regex_replace": {"pattern": "(a)", "repl": r"\2"}},
        {"regex_replace": {"pattern": r"\Z", "repl": ""}},
    ],
)
def test_malformed_post_ops_are_refused(post: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _validate_step({"xpath": "//a", "post": [post]})


def test_a_normalizer_post_op_names_its_field_type() -> None:
    step = CssStep.model_validate({"css": "a", "post": [{"date": {}}]})
    assert step.post == [NormalizeOp(type=FieldType.DATE)]
    assert step.model_dump()["post"] == [{"date": {}}]


@pytest.mark.parametrize(
    "fields",
    [
        {"price": {"steps": [], "status": "operator"}},
        {"price": {"steps": [{"xpath": "//a"}], "status": "learned"}},
        {"price": {"steps": [{"xpath": "//a"}], "status": "operator", "yield": 1.5}},
        {"Price": {"steps": [{"xpath": "//a"}], "status": "operator"}},
    ],
)
def test_malformed_fields_are_refused(fields: dict[str, Any]) -> None:
    document = {
        "ir_version": "1",
        "site": "example.com",
        "schema": {"name": "s", "version": 1},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": fields,
        "provenance": {
            "origin": "operator",
            "validated_on": [],
            "learned_at": "2026-10-13T00:00:00Z",
            "engine_version": "x",
        },
    }
    with pytest.raises(ValidationError):
        ExtractionConfigIR.model_validate(document)
