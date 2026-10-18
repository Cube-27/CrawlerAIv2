"""The config IR model (SPEC-08 §4.2, ARCHITECTURE §12.1): every valid IR survives a JSON round trip, and every step
one through role A's wire form (§4.6), CSS steps carry an XPath 1.0 translation that selects the same elements, and
malformed steps and post ops are refused."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from crawlerai.config_ir import step_wire
from crawlerai.config_ir.model import ExtractionConfigIR, FieldSteps, Step
from crawlerai.schemas.types import FieldType

_TAGS = ["div", "span", "p", "a", "li", "ul"]
_CLASSES = ["x", "y", "price-now", "z1"]
_IDS = ["i1", "i2"]

# --- generated IRs --------------------------------------------------------------------------------------------------

_xpath = st.sampled_from(
    ["//h1", "normalize-space(//h1[@data-testid='t'])", "//a[@rel='next']/@href", "//ul/li[1]", "string(//p)"]
)
_css = st.sampled_from(["div.x > span", "a#i1", "li[data-k='v']", "ul li:nth-child(2)", "p:not(.y)"])
# The RFC 9535 subset the engine reads: name, wildcard and index segments (the `select` of `json_doc`).
_jsonpath = st.from_regex(r"\$(\['[a-z][A-Za-z]{0,8}'\]|\[\*\]|\[[0-9]\]){1,3}", fullmatch=True)
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
_RECIPE = {
    "method": "GET",
    "url": "https://api.example.test/v1/products/{p1}",
    "params_from_url": {"p1": "path:1"},
    "headers": {"Accept": "application/json"},
    "map": {"title": "$['data']['name']"},
    "proof": {
        "validated_on": ["0190b2a0-0000-7000-8000-000000000002"],
        "headers_tried": 0,
        "bound_by": "deterministic",
    },
}
_ir = st.builds(
    lambda fields, listing, origin, kind, method, recipe: {
        "ir_version": "1",
        "site": "shop.example.com",
        "schema": {"name": "commerce_detail", "digest": "0" * 64},
        "page_kind": kind,
        "fetch": {"method": method},
        "fields": fields,
        "listing": listing,
        "api_recipe": recipe,
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
    st.sampled_from([None, _RECIPE]),
)


@given(_ir)
def test_ir_survives_a_json_round_trip(document: dict[str, Any]) -> None:
    ir = ExtractionConfigIR.model_validate(document)
    assert ExtractionConfigIR.model_validate_json(ir.model_dump_json()) == ir
    assert ExtractionConfigIR.model_validate(ir.model_dump(mode="json")) == ir


class _OneStep(BaseModel):
    step: Step


# `api` is the source of API recipe steps (SPEC-09), which role A does not write.
@given(_step.filter(lambda raw: raw.get("source") != "api"))
def test_a_step_survives_role_a_wire_form(raw: dict[str, Any]) -> None:
    step = _OneStep.model_validate({"step": raw}).step

    wire = step_wire.to_wire(step)

    assert list(Draft202012Validator(step_wire.STEP_SCHEMA).iter_errors(wire)) == []
    assert _OneStep.model_validate({"step": step_wire.from_wire(wire)}).step == step


@pytest.mark.parametrize(
    "recipe",
    [
        {**_RECIPE, "headers": {"Cookie": "a=b"}},  # a recipe never carries credentials (SPEC-09 §4.6)
        {key: value for key, value in _RECIPE.items() if key != "proof"},  # an IR recipe is a validated one (§4.7)
    ],
)
def test_ir_refuses_a_recipe_the_recipe_model_refuses(recipe: dict[str, Any]) -> None:
    document = {
        "ir_version": "1",
        "site": "shop.example.test",
        "schema": {"name": "commerce_detail", "digest": "0" * 64},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {},
        "api_recipe": recipe,
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-14T00:00:00Z",
            "engine_version": "abc1234+cal.none",
        },
    }
    with pytest.raises(ValidationError, match="api_recipe"):
        ExtractionConfigIR.model_validate(document)


# --- rejections -----------------------------------------------------------------------------------------------------


def _validate_step(step: object) -> None:
    FieldSteps.model_validate({"steps": [step], "status": "operator"})


@pytest.mark.parametrize(
    "step",
    [
        {},
        {"xpath": "//a", "regex": "x"},
        {"jsonpath": "$['name']", "source": "cookies"},
        {"xpath": "upper-case(//a)"},
    ],
)
def test_malformed_steps_are_refused(step: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _validate_step(step)


@pytest.mark.parametrize(
    "post",
    [
        {},
        {"uppercase": {}},
        {"regex_replace": {"pattern": "(a)", "repl": r"\2"}},
    ],
)
def test_malformed_post_ops_are_refused(post: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _validate_step({"xpath": "//a", "post": [post]})
