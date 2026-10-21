"""Every role's output schema stays inside every provider's structured-output subset (llm spec), for any
fields a schema can ask for: a provider refuses a schema outside it with a 400, and the role then extracts nothing."""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.config_ir import synthesis
from crawlerai.config_ir.api_recipe import role_d
from crawlerai.llm.client import closed_object
from crawlerai.llm.roles import c_extract, s_schema
from crawlerai.schemas.types import NAME_PATTERN
from tests.support.schema_subset import SUBSET_FILES, SchemaSubset, violations

_DATA = Path(__file__).parents[2] / "data"
SUBSETS = {
    provider: SchemaSubset.model_validate_json((_DATA / name).read_bytes()) for provider, name in SUBSET_FILES.items()
}
ANTHROPIC, GEMINI = SUBSETS["anthropic"], SUBSETS["gemini"]
PROVIDERS = pytest.mark.parametrize("subset", SUBSETS.values(), ids=SUBSETS.keys())
# Up to twice the most unions or optional properties a provider allows, so a per-field union or option would show.
names = st.lists(st.from_regex(rf"^{NAME_PATTERN}$", fullmatch=True), min_size=1, max_size=40, unique=True)


def _arrays(schema: JsonValue) -> int:
    """How many array schemas `schema` holds, at any depth."""
    if isinstance(schema, list):
        return sum(_arrays(item) for item in schema)
    if not isinstance(schema, dict):
        return 0
    return (schema.get("type") == "array") + sum(_arrays(value) for value in schema.values())


@given(names)
def test_a_role_c_detail_reply_holds_one_claim_per_field_asked_in_every_subset(fields: list[str]) -> None:
    # F29: a closed object with one required claim per field and no array, so no reply can run on with more claims
    # than the fields asked (neither provider's subset has `maxItems` and `maxLength` both).
    schema: Any = c_extract.output_schema(fields)
    claims = schema["properties"]["fields"]

    assert (_arrays(schema), sorted(claims["properties"]), claims["required"]) == (0, sorted(fields), sorted(fields))
    assert claims["additionalProperties"] is False
    # One claim form, referenced by every field: a provider compiles the schema into a grammar whose size it caps, and
    # the claim written out under each field outgrew it from 18 fields on Anthropic (D-1008).
    assert json.dumps(schema).count('"start"') == 2
    assert {provider: violations(schema, subset) for provider, subset in SUBSETS.items()} == {p: [] for p in SUBSETS}


@given(names | st.just([]), st.booleans(), names)
def test_role_a(page: list[str], row: bool, rows: list[str]) -> None:
    schema = synthesis.output_schema(page, row, rows)

    # The step form appears once per list, whatever the number of fields: a provider caps its compiled grammar.
    assert _arrays(schema) == 3 * bool(page) + row + 3 * bool(rows)
    assert {provider: violations(schema, subset) for provider, subset in SUBSETS.items()} == {p: [] for p in SUBSETS}


@PROVIDERS
def test_role_s(subset: SchemaSubset) -> None:
    assert violations(s_schema.output_schema(), subset) == []


@PROVIDERS
def test_role_d(subset: SchemaSubset) -> None:
    assert violations(role_d.OUTPUT_SCHEMA, subset) == []


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
        (closed_object({"a": {"$ref": "#"}}), ANTHROPIC, ["$: recursive $ref through #"]),
        (SPAN, GEMINI, []),
    ],
)
def test_violations_names_each_rule_broken(
    schema: dict[str, JsonValue], subset: SchemaSubset, found: list[str]
) -> None:
    assert violations(schema, subset) == found
