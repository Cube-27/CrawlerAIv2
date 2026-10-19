"""The RSC Flight reader (extraction spec, "Source documents"): a Flight stream pushed in `self.__next_f.push` chunks,
or captured as a `text/x-component` body, read by React's row grammar into JSON model rows by row id."""

import base64
import json

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.js_state import state_documents
from crawlerai.collect.xhr import network_documents
from crawlerai.content.page import ParsedPage, ScriptBlock
from crawlerai.content.rsc import read_rows
from crawlerai.content.state import flight_rows
from crawlerai.storage.capture_bundle import NetworkBody, sha256_hex

_TEXT = "line one\nlíne twö — €\n"
_ROWS = (
    b'0:["$","$L1",null,{"children":"$@2"}]\n'
    b'1:I["chunk-1",["a.js"],"Price"]\n'
    b'2:{"name":"Lamp","price":"$$19.99","currency":"EUR","desc":"$3"}\n'
    + f"3:T{len(_TEXT.encode()):x},{_TEXT}".encode()
)
_BINARY_ROW = b'a:{"offers":[{"price":12.5}]}\n'
_EXPECTED: list[tuple[str, str, JsonValue]] = [
    ("0", "", ["$", "$L1", None, {"children": "$@2"}]),
    ("1", "I", '["chunk-1",["a.js"],"Price"]'),
    ("2", "", {"name": "Lamp", "price": "$19.99", "currency": "EUR", "desc": "$3"}),
    ("3", "T", _TEXT),
    ("a", "", {"offers": [{"price": 12.5}]}),
]


def _push(segment: int, chunk: str | None = None) -> str:
    return f"self.__next_f.push([{segment}{'' if chunk is None else ', ' + json.dumps(chunk)}])"


def _scripts() -> list[ScriptBlock]:
    """The fixture's stream as Next.js writes it: a bootstrap, UTF-8 chunks split inside rows (inside the `T` row's
    text too), a form state segment, and one base64 chunk."""
    text = _ROWS.decode()
    cut_json, cut_text = text.index("Lamp"), text.index("twö")
    pushes = [
        "(self.__next_f=self.__next_f||[]).push([0])",
        _push(1, text[:cut_json]),
        _push(1, text[cut_json:cut_text]),
        _push(2, None),
        _push(1, text[cut_text:]),
        _push(3, base64.b64encode(_BINARY_ROW).decode()),
    ]
    return [ScriptBlock("", push, f"/html[1]/body[1]/script[{n}]") for n, push in enumerate(pushes, 1)]


def test_pushed_chunks_split_mid_row_make_one_stream_of_rows() -> None:
    diagnostics: list[str] = []
    found = flight_rows(_scripts(), diagnostics)

    assert found is not None
    address, rows = found
    assert address == "/html[1]/body[1]/script[2]"
    assert [(r.id, r.tag, r.value) for r in rows] == _EXPECTED
    assert diagnostics == []


def test_the_json_rows_are_one_state_document_and_one_xhr_document() -> None:
    html = "<html><body>" + "".join(f"<script>{s.text}</script>" for s in _scripts()) + "</body></html>"
    stream = _ROWS + _BINARY_ROW
    entry = NetworkBody(
        url="https://shop.example.test/p/1?_rsc=1",
        status=200,
        content_type="text/x-component; charset=utf-8",
        sha256=sha256_hex(stream),
        file="network/0001.json",
    )
    page = ParsedPage(html, (stream,), (entry,))
    model = {row_id: value for row_id, tag, value in _EXPECTED if not tag}

    assert [d.data for d in state_documents(page, [])][-1] == model
    assert [(d.data, d.address) for d in network_documents(page, [])] == [(model, "0")]


def test_a_malformed_row_is_a_diagnostic_and_the_other_rows_are_read() -> None:
    diagnostics: list[str] = []
    data = b'0:{"a":1}\nzz:{"b":2}\n1:{"broken"\n2:T,x\n3:"ok"\n4:T10,short'

    rows = read_rows(data, "xhr:0", diagnostics)

    assert [(r.id, r.value) for r in rows] == [("0", {"a": 1}), ("3", "ok")]
    assert [d.split(": ", 1)[1].split(" (")[0] for d in diagnostics] == [
        "RSC row without an id at byte 10",
        "RSC row 1 is not JSON",
        "RSC row 2 without a length",
        "RSC row 4 longer than the payload",
    ]


# Text is UTF-8, which holds no lone surrogate.
_TEXTS = st.text(st.characters(exclude_categories=["Cs"]))
_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | _TEXTS,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(_TEXTS, inner, max_size=4),
    max_leaves=12,
)


def _escaped(value: JsonValue) -> JsonValue:
    """React's encoding of a string value that starts with `$`: `$$`."""
    if isinstance(value, str):
        return "$" + value if value.startswith("$") else value
    if isinstance(value, list):
        return [_escaped(item) for item in value]
    if isinstance(value, dict):
        return {key: _escaped(member) for key, member in value.items()}
    return value


@given(st.lists(st.one_of(_JSON.map(lambda v: ("", v)), _TEXTS.map(lambda t: ("T", t))), max_size=8))
def test_rows_encoded_with_the_grammar_read_back(rows: list[tuple[str, JsonValue]]) -> None:
    stream = b""
    for row_id, (tag, value) in enumerate(rows):
        if tag == "T":
            assert isinstance(value, str)
            text = value.encode()
            stream += f"{row_id:x}:T{len(text):x},".encode() + text
        else:
            stream += f"{row_id:x}:{json.dumps(_escaped(value), ensure_ascii=False)}\n".encode()
    diagnostics: list[str] = []

    read = read_rows(stream, "xhr:0", diagnostics)

    assert [(r.id, r.tag, r.value) for r in read] == [(f"{i:x}", tag, value) for i, (tag, value) in enumerate(rows)]
    assert diagnostics == []
