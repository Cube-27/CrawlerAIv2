"""The engine's one JSON reader (RFC 8259): text or bytes, strict or lenient about raw control characters, and every
failure a `ValueError`, a document nested deeper than the parser follows too."""

import json
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.core.json_text import parse, parse_prefix

DEEP = "[" * 100_000 + "]" * 100_000


def test_a_document_nested_deeper_than_the_parser_follows_is_not_json() -> None:
    as_bytes, assignment = DEEP.encode(), "x = " + DEEP
    with pytest.raises(ValueError, match="nested too deeply"):
        parse(DEEP)
    with pytest.raises(ValueError, match="nested too deeply"):
        parse(as_bytes, lenient=True)
    with pytest.raises(ValueError, match="nested too deeply"):
        parse_prefix(assignment, 4)


# RFC 8259 §7: a string's control characters (U+0000-U+001F) must be escaped; json.dumps writes them as these escapes.
_CONTROL_ESCAPE = re.compile(r"\\(\\|u00[01][0-9a-f]|[bfnrt])")
_SHORT = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _raw_controls(match: re.Match[str]) -> str:
    """Each control-character escape written back as the raw character; an escaped backslash stays escaped."""
    escape = match[1]
    if escape == "\\":
        return "\\\\"
    return chr(int(escape[1:], 16)) if escape.startswith("u") else _SHORT[escape]


control_text = st.text(alphabet=st.characters(max_codepoint=0x7F), max_size=8)
documents_with_controls = st.recursive(
    st.none() | st.booleans() | st.integers() | control_text,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(control_text, children, max_size=4),
    max_leaves=20,
)


@given(document=documents_with_controls)
def test_raw_control_characters_inside_strings_parse_leniently_as_the_same_document(document: JsonValue) -> None:
    text = _CONTROL_ESCAPE.sub(_raw_controls, json.dumps(document))
    assert parse(text, lenient=True) == document


def test_a_number_with_leading_zeros_parses_leniently_as_its_written_digits() -> None:
    text = '{"gtin13": 0745114652584, "note": "0, 07", "n": [0, -012.5]}'
    assert parse(text, lenient=True) == {"gtin13": "0745114652584", "note": "0, 07", "n": [0, "-012.5"]}
    assert parse(" 007 ", lenient=True) == "007"
    with pytest.raises(ValueError, match="delimiter"):
        parse(text)
    with pytest.raises(ValueError, match="delimiter"):
        parse("[0\u0661]", lenient=True)
