"""Steps as role A writes them (SPEC-08 §4.6): a form inside every provider's structured-output subset.

An IR step is an object with one selector key and optional parameters, and a post op is an object keyed by its op
(`model.Step`, `model.PostOp`); neither is a closed object with every property required, which a provider's strict
output needs (`llm.schema_subset`: no optional properties, every object closed). The wire form says the same with
fixed keys:
- a step is `{selector, expression, when_type, source, post}`, `selector` naming the IR's selector key;
- a post op is `{op, pattern, repl}`, `op` being `trim`, `absolutize_url`, `regex_replace` or a field type;
- `""` stands for a parameter the step or op does not have.

`from_wire` writes a wire step as the IR document it stands for, keeping every parameter the model gave, so the IR's
own rules refuse a misplaced one (`invalid_step`). `to_wire` writes an IR step, such as a verified row selector shown
to the model, in the same form.
"""

from collections.abc import Mapping
from typing import Final, cast

from pydantic import JsonValue

from crawlerai.config_ir.model import Step, selector_key
from crawlerai.llm.client import closed_object
from crawlerai.schemas.types import FieldType

_NONE: Final = ""
SELECTORS: Final = ("xpath", "css", "jsonld", "jsonpath", "regex", "attr")
# The sources role A may name; `api` belongs to API recipes (SPEC-09), not to steps the model writes.
_SOURCES: Final = ("jsonld", "js_state", "xhr")
_REGEX_REPLACE: Final = "regex_replace"
_PARAMETERLESS: Final = ("trim", "absolutize_url")
# SPEC-04 §4.1: `list` and `object` have no normalizer of their own, so no post op names them.
_NORMALIZERS: Final = tuple(t.value for t in FieldType if t not in (FieldType.LIST, FieldType.OBJECT))


def _string_enum(values: tuple[str, ...]) -> dict[str, JsonValue]:
    return {"type": "string", "enum": list[JsonValue](values)}


POST_OP_SCHEMA: Final = closed_object(
    {
        "op": _string_enum((*_PARAMETERLESS, _REGEX_REPLACE, *_NORMALIZERS)),
        "pattern": {"type": "string"},
        "repl": {"type": "string"},
    }
)
STEP_SCHEMA: Final = closed_object(
    {
        "selector": _string_enum(SELECTORS),
        "expression": {"type": "string"},
        "when_type": {"type": "string"},
        "source": _string_enum((_NONE, *_SOURCES)),
        "post": {"type": "array", "items": POST_OP_SCHEMA},
    }
)


def from_wire(step: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The IR step document a wire step stands for, for the IR model to validate."""
    document: dict[str, JsonValue] = {cast(str, step["selector"]): step["expression"]}
    document |= {key: step[key] for key in ("when_type", "source") if step[key] != _NONE}
    if ops := cast(list[JsonValue], step["post"]):
        document["post"] = [_op(cast(dict[str, JsonValue], op)) for op in ops]
    return document


def _op(op: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    name = cast(str, op["op"])
    if name == _REGEX_REPLACE:
        return {name: {"pattern": op["pattern"], "repl": op["repl"]}}
    return {name: {key: op[key] for key in ("pattern", "repl") if op[key] != _NONE}}


def to_wire(step: Step) -> dict[str, JsonValue]:
    """`step` in the wire form. A CSS step's `xpath` is its translation, which the model does not write."""
    document = cast(dict[str, JsonValue], step.model_dump(mode="json", exclude_defaults=True))
    selector = cast(str, selector_key(step))
    return {
        "selector": selector,
        "expression": document[selector],
        "when_type": document.get("when_type", _NONE),
        "source": document.get("source", _NONE),
        "post": [_wire_op(cast(dict[str, JsonValue], op)) for op in cast(list[JsonValue], document.get("post", []))],
    }


def _wire_op(op: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    ((name, raw),) = op.items()
    params = cast(dict[str, JsonValue], raw)
    return {"op": name, "pattern": params.get("pattern", _NONE), "repl": params.get("repl", _NONE)}
