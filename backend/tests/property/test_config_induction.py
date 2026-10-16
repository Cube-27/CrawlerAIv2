"""Induction on generated sample pages (SPEC-08 §4.5): positional predicates are dropped and stable anchors kept, hashed
class tokens never anchor, a selector that over-matches on one sample page is rejected, and a JSON-LD value becomes one
`jsonld` step relative to its typed node whatever the node's index in the block."""

import json
from datetime import UTC, datetime
from html import escape

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.induction import Published, SamplePage, induce, stable_class_token
from crawlerai.config_ir.model import FieldSteps, JsonLdStep, XPathStep
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
TEXT = FieldSpec(type=FieldType.TEXT, description="d")
VOCABULARY = Vocabulary(
    {"Thing": frozenset({"Thing"}), "Product": frozenset({"Product", "Thing"}), "Offer": frozenset({"Offer", "Thing"})}
)
HAS_CLASS = "contains(concat(' ', normalize-space(@class), ' '), ' {} ')"

_value = st.from_regex(r"[A-Za-z][A-Za-z0-9 ]{0,10}[A-Za-z0-9]", fullmatch=True)
_stable = st.from_regex(r"[a-z]{2,6}(-[a-z]{2,6})?", fullmatch=True)
# Tokens a build tool hashes: an uppercase letter or underscore, or a run of three digits.
_hashed = st.one_of(
    st.from_regex(r"[a-z]{1,3}[A-Z_][A-Za-z0-9]{0,4}", fullmatch=True),
    st.from_regex(r"[a-z]{1,3}-?[0-9]{3,6}", fullmatch=True),
)
_position = st.integers(min_value=0, max_value=3)
_pages = st.lists(st.tuples(_value, _position, _position, _hashed), min_size=5, max_size=5)


def _schema(page_kind: str = "detail") -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": {"title": TEXT},
        }
    )


def _sample(html: str, value: str, locator: str) -> SamplePage:
    published = normalize(value, TEXT, CTX)
    assert isinstance(published, Ok)
    return SamplePage(ParsedPage(html), CTX, {"title": Published(published.value, locator)})


def _classed_page(value: str, before: int, inside: int, hashed: str, stable: str, *, extra: str = "") -> SamplePage:
    """`before` unanchored divs, then a div of `inside` plain spans and the value's span, classed `hashed stable`."""
    noise = "<div><span>n</span></div>" * before
    spans = "<span>n</span>" * inside
    target = f"<span class='{hashed} {stable}'>{escape(value)}</span>"
    html = f"<html><body>{noise}<div class='{hashed}'>{spans}{target}</div>{extra}</body></html>"
    return _sample(html, value, f"microdata:/html[1]/body[1]/div[{before + 1}]/span[{inside + 1}]")


@given(_pages, _stable)
def test_a_stable_class_token_anchors_a_path_without_positions(
    pages: list[tuple[str, int, int, str]], stable: str
) -> None:
    sample = [_classed_page(value, before, inside, hashed, stable) for value, before, inside, hashed in pages]
    induced = induce(_schema(), sample, VOCABULARY)
    expected = XPathStep(xpath=f"normalize-space(//span[{HAS_CLASS.format(stable)}])")
    assert induced.fields == {"title": FieldSteps(steps=[expected], status="uncorroborated")}
    assert induced.to_synthesize == {}


@given(_pages, _stable, st.integers(min_value=0, max_value=4))
def test_a_selector_that_over_matches_on_one_sample_page_is_rejected(
    pages: list[tuple[str, int, int, str]], stable: str, crowded: int
) -> None:
    sample = [
        _classed_page(
            value, before, inside, hashed, stable, extra=f"<p><span class='{stable}'>x</span></p>" * (n == crowded)
        )
        for n, (value, before, inside, hashed) in enumerate(pages)
    ]
    induced = induce(_schema(), sample, VOCABULARY)
    assert (induced.fields, induced.to_synthesize) == ({}, {"title": "no_verified_selector"})


@given(st.lists(st.tuples(_value, _position, _position), min_size=5, max_size=5), _stable)
def test_an_id_on_an_ancestor_anchors_the_path_below_it(pages: list[tuple[str, int, int]], anchor: str) -> None:
    sample = [
        _sample(
            f"<html><body>{'<div>n</div>' * before}<div id='{anchor}'>{'<i>n</i>' * inside}<b>{escape(value)}</b></div>"
            "</body></html>",
            value,
            f"microdata:/html[1]/body[1]/div[{before + 1}]/b[1]",
        )
        for value, before, inside in pages
    ]
    induced = induce(_schema(), sample, VOCABULARY)
    assert induced.fields["title"].steps == [XPathStep(xpath=f"normalize-space(//div[@id='{anchor}']/b)")]


@given(st.lists(_value, min_size=5, max_size=5))
def test_a_value_in_an_attribute_is_read_from_that_attribute(values: list[str]) -> None:
    sample = [
        _sample(
            f"<html><head><meta itemprop='name' content='{escape(value)}'></head><body></body></html>",
            value,
            "microdata:/html[1]/head[1]/meta[1]",
        )
        for value in values
    ]
    induced = induce(_schema(), sample, VOCABULARY)
    assert induced.fields["title"].steps == [XPathStep(xpath="//meta[@itemprop='name']/@content")]


@given(st.lists(st.tuples(_value, _position), min_size=5, max_size=5))
def test_a_jsonld_value_becomes_one_step_relative_to_its_typed_node(pages: list[tuple[str, int]]) -> None:
    sample = []
    for value, at in pages:
        graph = [{"@type": "Thing", "name": "other"}] * at + [{"@type": "Product", "name": value}]
        block = json.dumps({"@context": "https://schema.org", "@graph": graph})
        html = f"<html><head><script type='application/ld+json'>{block}</script></head></html>"
        sample.append(_sample(html, value, f"jsonld:0:$['@graph'][{at}]['name']"))
    induced = induce(_schema(), sample, VOCABULARY)
    assert induced.fields["title"].steps == [JsonLdStep(jsonld="$['name']", when_type="Product")]


@given(st.from_regex(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", fullmatch=True))
def test_a_kebab_case_token_is_stable_unless_it_has_a_long_digit_run(token: str) -> None:
    assert stable_class_token(token) == all(not token[i : i + 3].isdigit() for i in range(len(token) - 2))


@given(_hashed)
def test_a_hashed_token_is_never_stable(token: str) -> None:
    assert not stable_class_token(token)
