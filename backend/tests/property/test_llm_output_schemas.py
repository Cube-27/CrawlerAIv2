"""Every role's output schema stays inside every provider's structured-output subset (SPEC-06 §4.1, §4.2), for any
fields a schema can ask for: a provider refuses a schema outside it with a 400, and the role then extracts nothing."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.config_ir import synthesis
from crawlerai.config_ir.api_recipe import role_d
from crawlerai.llm.client import closed_object
from crawlerai.llm.roles import c_extract, s_schema
from crawlerai.llm.schema_subset import SchemaSubset, read_subsets, violations
from crawlerai.schemas.types import NAME_PATTERN

SUBSETS = read_subsets(Path(__file__).parents[2] / "data")
ANTHROPIC, GEMINI = SUBSETS["anthropic"], SUBSETS["gemini"]
PROVIDERS = pytest.mark.parametrize("subset", SUBSETS.values(), ids=SUBSETS.keys())
# Up to twice the most unions or optional properties a provider allows, so a per-field union or option would show.
names = st.lists(st.from_regex(rf"^{NAME_PATTERN}$", fullmatch=True), min_size=1, max_size=40, unique=True)


@PROVIDERS
@given(names)
def test_role_c_detail(subset: SchemaSubset, fields: list[str]) -> None:
    assert violations(c_extract.output_schema(fields), subset) == []


@PROVIDERS
@given(names, st.lists(st.from_regex(rf"^{NAME_PATTERN}$", fullmatch=True), max_size=10, unique=True))
def test_role_c_listing(subset: SchemaSubset, rows: list[str], page: list[str]) -> None:
    assert violations(c_extract.listing_output_schema(rows, page), subset) == []


@PROVIDERS
@given(names | st.just([]), st.booleans(), names)
def test_role_a(subset: SchemaSubset, page: list[str], row: bool, rows: list[str]) -> None:
    assert violations(synthesis.output_schema(page, row, rows), subset) == []


@PROVIDERS
def test_role_s(subset: SchemaSubset) -> None:
    assert violations(s_schema.output_schema(), subset) == []


@PROVIDERS
def test_role_d(subset: SchemaSubset) -> None:
    assert violations(role_d.OUTPUT_SCHEMA, subset) == []


def test_each_subset_file_is_its_providers() -> None:
    assert [subset.provider for subset in SUBSETS.values()] == list(SUBSETS)


# --- what `violations` finds ---

SPAN = closed_object({"value": {"type": "string"}, "start": {"type": "integer", "minimum": 0}})


def _union(n: int) -> dict[str, JsonValue]:
    return closed_object({f"f{i}": {"anyOf": [{"type": "string"}, {"type": "null"}]} for i in range(n)})


@pytest.mark.parametrize(
    ("schema", "subset", "found"),
    [
        (SPAN, ANTHROPIC, ["$.properties.start: keyword 'minimum'"]),
        ({"type": "object", "properties": {}}, ANTHROPIC, ["$: object without additionalProperties false"]),
        (_union(17), ANTHROPIC, ["$: 17 union parameters (at most 16)"]),
        (
            {"type": "object", "properties": {f"f{i}": {"type": "string"} for i in range(25)}, "required": []}
            | {"additionalProperties": False},
            ANTHROPIC,
            ["$: 25 optional properties (at most 24)"],
        ),
        (closed_object({"a": {"type": "array", "minItems": 2}}), ANTHROPIC, ["$.properties.a: minItems 2"]),
        (
            closed_object({"a": {"$ref": "#/$defs/x", "description": "d"}}),
            GEMINI,
            ["$.properties.a: $ref with sibling keywords"],
        ),
        (
            closed_object({"a": {"$ref": "#/$defs/node"}})
            | {"$defs": {"node": closed_object({"child": {"$ref": "#/$defs/node"}})}},
            GEMINI,
            ["$: recursive $ref through node"],
        ),
        (closed_object({"a": {"$ref": "#"}}), ANTHROPIC, ["$: recursive $ref through #"]),
        (_union(17), GEMINI, []),
        (SPAN, GEMINI, []),
    ],
)
def test_violations_names_each_rule_broken(
    schema: dict[str, JsonValue], subset: SchemaSubset, found: list[str]
) -> None:
    assert violations(schema, subset) == found
