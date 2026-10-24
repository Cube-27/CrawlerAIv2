"""The bounded XML reader (XML 1.0; OWASP XXE prevention): a document is its JSON value, and a document that would grow
the parse or reach outside it is refused."""

import pytest

from snowcrawl.adapters.xml_reader import read_xml


def test_children_are_arrays_by_name_and_leaves_are_trimmed_text() -> None:
    body = b"<root><a> x </a><b><c>1</c><c>2</c></b><a/><d><![CDATA[<p>y</p>]]></d><!-- no --></root>"

    assert read_xml(body) == {"root": [{"a": ["x", None], "b": [{"c": ["1", "2"]}], "d": ["<p>y</p>"]}]}


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
