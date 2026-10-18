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


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-8-sig"])
def test_bytes_are_read_in_the_encodings_json_text_is_exchanged_in(encoding: str) -> None:
    # RFC 8259 §8.1 (UTF-8) and RFC 4627 §3 (UTF-16/32 told apart by their first bytes).
    assert parse('{"name": "Café"}'.encode(encoding)) == {"name": "Café"}


def test_bytes_that_are_not_text_are_not_json() -> None:
    body = b'{"name": "' + bytes([0xFF]) + b'"}'  # 0xFF starts no UTF-8 sequence
    with pytest.raises(ValueError):
        parse(body)


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


def test_a_raw_control_character_in_a_string_is_refused_strictly() -> None:
    text = '{"description": "line one\nline two"}'
    with pytest.raises(ValueError, match="control character"):
        parse(text)


@pytest.mark.parametrize("text", ['{"a": 1,}', '{"a": NaN}', '{"a":\x01 1}', "{'a': 1}"])
def test_lenient_parsing_still_refuses_everything_else_that_is_not_json(text: str) -> None:
    with pytest.raises(ValueError):
        parse(text, lenient=True)
