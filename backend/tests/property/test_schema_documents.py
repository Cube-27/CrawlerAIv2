"""Schema documents (SPEC-04 §6): generated valid documents round-trip through the model and its JSON, and through
role S's wire form (SPEC-06 §4.5), and a `schema_org` path that breaks the schema.org naming conventions is rejected
wherever it appears."""

from typing import Any, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from crawlerai.llm.roles.s_wire import from_wire, to_wire, wire_schema
from crawlerai.schemas.types import FieldType, IdentifierScheme, SchemaDocument

_names = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_type_name = st.from_regex(r"[A-Z][A-Za-z0-9]{0,8}", fullmatch=True)
_property = st.from_regex(r"[a-z][A-Za-z0-9]{0,8}", fullmatch=True)
_schema_org = st.builds(
    lambda t, props, joined: f"{t}.{'.'.join(props)}" + (f"+{joined}" if joined else ""),
    _type_name,
    st.lists(_property, min_size=1, max_size=3),
    st.none() | _property,
)
_SCALARS = [t for t in FieldType if t not in (FieldType.LIST, FieldType.OBJECT)]


def _parameters(type_: FieldType) -> st.SearchStrategy[dict[str, Any]]:
    if type_ is FieldType.ENUM:
        return st.builds(
            lambda v: {"vocab": v}, st.from_regex(r"(schema:[A-Z][a-z]{1,6}|type:[a-z]{1,6})", fullmatch=True)
        )
    if type_ is FieldType.IDENTIFIER:
        return st.builds(lambda s: {"scheme": s}, st.sampled_from(get_args(IdentifierScheme)))
    return st.just({})


def _spec(depth: int, *, described: bool) -> st.SearchStrategy[dict[str, Any]]:
    types = list(FieldType) if depth < 3 else _SCALARS
    return st.sampled_from(types).flatmap(lambda t: _spec_of(t, depth, described=described))


def _spec_of(type_: FieldType, depth: int, *, described: bool) -> st.SearchStrategy[dict[str, Any]]:
    common = st.fixed_dictionaries(
        {"type": st.just(type_.value)},
        optional={"required": st.booleans(), "schema_org": _schema_org},
    )
    parts = [common, _parameters(type_)]
    if described:
        parts.append(st.builds(lambda d: {"description": d}, st.text(max_size=20).map(str.strip).filter(bool)))
    if type_ is FieldType.LIST:
        parts.append(st.builds(lambda i: {"item": i}, _spec(depth + 1, described=False)))
    if type_ is FieldType.OBJECT:
        parts.append(
            st.builds(
                lambda f: {"fields": f},
                st.dictionaries(_names, _spec(depth + 1, described=True), min_size=1, max_size=3),
            )
        )
    return st.tuples(*parts).map(lambda ds: {k: v for d in ds for k, v in d.items()})


_documents = st.fixed_dictionaries(
    {
        "name": _names,
        "version": st.integers(min_value=1, max_value=10_000),
        "page_kind": st.just("detail"),
        "fields": st.dictionaries(_names, _spec(1, described=True), min_size=1, max_size=4),
    }
)


@given(_documents)
def test_valid_documents_round_trip_through_json(raw: dict[str, Any]) -> None:
    document = SchemaDocument.model_validate(raw)

    assert SchemaDocument.model_validate_json(document.model_dump_json(exclude_none=True)) == document
    assert document.model_dump(mode="json", exclude_none=True, exclude_defaults=True) == {
        **raw,
        "fields": _without_defaults(raw["fields"]),
    }


@given(_documents)
def test_valid_documents_round_trip_through_the_role_s_wire_form(raw: dict[str, Any]) -> None:
    document = SchemaDocument.model_validate(raw)

    wire = to_wire(document.model_dump(mode="json", exclude={"name", "version"}, exclude_none=True))

    assert list(Draft202012Validator(wire_schema()).iter_errors(wire)) == []
    assert (
        SchemaDocument.model_validate({**from_wire(wire), "name": raw["name"], "version": raw["version"]}) == document
    )


def _without_defaults(fields: dict[str, Any]) -> dict[str, Any]:
    return {name: _spec_without_defaults(spec) for name, spec in fields.items()}


def _spec_without_defaults(spec: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in spec.items() if not (k == "required" and v is False)}
    if "item" in out:
        out["item"] = _spec_without_defaults(out["item"])
    if "fields" in out:
        out["fields"] = _without_defaults(out["fields"])
    return out


_bad_paths = (
    _property  # no type
    | st.builds(lambda p: f"{p}.name", _property)  # lowercase type
    | st.builds(lambda t: f"{t}.Name", _type_name)  # uppercase property
    | st.builds(lambda path: f"{path}+", _schema_org.filter(lambda p: "+" not in p))  # empty joined property
    | st.builds(lambda path, p: f"{path}+{p}+{p}", _schema_org.filter(lambda p: "+" not in p), _property)
)


@given(_documents, _bad_paths)
def test_a_malformed_schema_org_path_is_rejected(raw: dict[str, Any], path: str) -> None:
    name = next(iter(raw["fields"]))
    raw["fields"][name] = {**raw["fields"][name], "schema_org": path}

    with pytest.raises(ValidationError) as error:
        SchemaDocument.model_validate(raw)

    assert any(e["loc"][-1] == "schema_org" for e in error.value.errors())
