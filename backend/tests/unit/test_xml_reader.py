"""The bounded XML reader (XML 1.0; OWASP XXE prevention): a document is its JSON value, and a document that would grow
the parse or reach outside it is refused."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.adapters.xml_reader import read_xml

TEXT = st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E, exclude_characters="<>&"), min_size=1)


def test_children_are_arrays_by_name_and_leaves_are_trimmed_text() -> None:
    body = b"<root><a> x </a><b><c>1</c><c>2</c></b><a/><d><![CDATA[<p>y</p>]]></d><!-- no --></root>"

    assert read_xml(body) == {"root": [{"a": ["x", None], "b": [{"c": ["1", "2"]}], "d": ["<p>y</p>"]}]}


@given(values=st.lists(TEXT, min_size=1, max_size=5))
def test_repeated_elements_keep_document_order(values: list[str]) -> None:
    body = "<r>" + "".join(f"<v>{v}</v>" for v in values) + "</r>"

    assert read_xml(body.encode()) == {"r": [{"v": [v.strip() for v in values]}]}


def test_namespaces_are_dropped_from_names() -> None:
    assert read_xml(b'<f:root xmlns:f="urn:example:feed"><f:item>1</f:item></f:root>') == {"root": [{"item": ["1"]}]}


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html><body><p>not closed",
        b"plain text",
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><r>&b;</r>',
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/hostname">]><r>&x;</r>',
        b"<!DOCTYPE r SYSTEM 'http://example.test/r.dtd'><r/>",
    ],
)
def test_a_malformed_document_or_one_with_a_doctype_is_refused(body: bytes) -> None:
    with pytest.raises(ValueError, match=r"not XML|DOCTYPE"):
        read_xml(body)


def test_nesting_past_the_parser_limit_is_refused() -> None:
    body = b"<a>" * 1000 + b"</a>" * 1000

    with pytest.raises(ValueError, match="not XML"):
        read_xml(body)
