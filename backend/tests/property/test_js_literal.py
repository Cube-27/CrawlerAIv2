"""JS literal reader properties: JSON text and the JS object-literal forms a
serializer writes (unquoted keys, single quotes, trailing commas, `undefined`) read back as the value they write."""

import json
import re

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.content.js_literal import read_literal

_json_values: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=30,
)
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*", re.ASCII)


def _js_string(value: str, data: st.DataObject) -> str:
    quote = data.draw(st.sampled_from(["'", '"']))
    escaped = []
    for char in value:
        if char in (quote, "\\"):
            escaped.append("\\" + char)
        elif ord(char) < 0x20 or ord(char) in (0x2028, 0x2029) or (ord(char) > 0x7E and data.draw(st.booleans())):
            escaped.append(f"\\u{{{ord(char):x}}}" if data.draw(st.booleans()) else json.dumps(char)[1:-1])
        else:
            escaped.append(char)
    return quote + "".join(escaped) + quote


def _js_uneval_like(value: JsonValue, data: st.DataObject) -> str:
    """`value` written as a JS literal the way serializers vary it: `undefined` or `void 0` for null, either quote,
    unquoted identifier keys, optional trailing commas and spaces."""
    space = data.draw(st.sampled_from(["", " ", "\n "]))
    trailing = "," if data.draw(st.booleans()) else ""
    if value is None:
        return data.draw(st.sampled_from(["null", "undefined", "void 0"]))
    if isinstance(value, str):
        return _js_string(value, data)
    if isinstance(value, list):
        items = [_js_uneval_like(item, data) for item in value]
        return "[" + space + f",{space}".join(items) + (trailing if items else "") + "]"
    if isinstance(value, dict):
        members = [
            (key if _IDENTIFIER.fullmatch(key) and data.draw(st.booleans()) else _js_string(key, data))
            + f"{space}:{space}"
            + _js_uneval_like(member, data)
            for key, member in value.items()
        ]
        return "{" + space + f",{space}".join(members) + (trailing if members else "") + "}"
    return json.dumps(value)


@given(_json_values)
def test_json_text_reads_as_its_value(value: JsonValue) -> None:
    assert read_literal(json.dumps(value)) == (value, len(json.dumps(value)))


@given(_json_values, st.data())
def test_a_js_literal_reads_as_the_value_it_writes(value: JsonValue, data: st.DataObject) -> None:
    written = _js_uneval_like(value, data)

    assert read_literal(written + ";rest") == (value, len(written))
